"""Generate AST unit worklist AND deterministically group files for review.

Usage: python3 generate_worklist.py <RUN_DIR> [target_units_per_group]

Reads:  <RUN_DIR>/work/source-files.txt      (one absolute source-file path per line)
        <RUN_DIR>/entrypoints/index.jsonl     (optional; entry-reachable files sort first)
Writes: <RUN_DIR>/work/worklist.jsonl          (全仓函数/方法/模块单元 = 覆盖分母)
        <RUN_DIR>/work/worklist-scope.json     (文件数 / 单元数统计)
        <RUN_DIR>/work/unit-review-groups.jsonl (按函数单元数均衡的最终分组)
        <RUN_DIR>/work/unit-review-plan.json    (分组自检摘要)

分组是**确定性的**（按函数单元数贪心装箱 + 目录内聚 + 入口可达优先），由代码定、
不交给 LLM——文件大小差异极大，按单元数分组才能让每个 unit-review 分支负担均衡、
在单个 turn 内跑完。
"""
import ast
import hashlib
import json
import pathlib
import sys

DEFAULT_TARGET_UNITS = 20


def _emit_units(w, f: str, src: str, h: str) -> tuple[int, bool]:
    """Write all units of one file to the worklist. Return (unit_count, is_non_python)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # Non-Python source (JS/Go/Java/...): no Python AST, but still in scope for
        # whole-repo coverage — emit ONE file-level unit so it enters the denominator.
        w.write(json.dumps({
            "unit_id": f + "::<file>", "file": f, "file_hash": h,
            "qualname": "<file>", "kind": "file", "lineno": 1,
            "end_lineno": len(src.splitlines()) or 1,
        }) + "\n")
        return 1, True

    count = 1
    w.write(json.dumps({
        "unit_id": f + "::<module>", "file": f, "file_hash": h,
        "qualname": "<module>", "kind": "module", "lineno": 1,
        "end_lineno": len(src.splitlines()) or 1,
    }) + "\n")

    def visit(node: ast.AST, prefix: str) -> None:
        nonlocal count
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + child.name
                w.write(json.dumps({
                    "unit_id": f + "::" + q, "file": f, "file_hash": h,
                    "qualname": q,
                    "kind": "method" if prefix else "function",
                    "lineno": child.lineno,
                    "end_lineno": getattr(child, "end_lineno", child.lineno),
                }) + "\n")
                count += 1
                visit(child, q + ".")

    visit(tree, "")
    return count, False


def _entry_basenames(run_dir: pathlib.Path) -> set[str]:
    """Handler file basenames from entrypoints/index.jsonl (entry-reachable → sort first)."""
    idx = run_dir / "entrypoints" / "index.jsonl"
    names: set[str] = set()
    if not idx.exists():
        return names
    for line in idx.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("handler", "file", "primary_file", "path", "handler_file"):
            v = obj.get(key)
            if isinstance(v, str) and v:
                names.add(pathlib.Path(v.split(":", 1)[0]).name)
    return names


def _group(file_units: dict[str, int], entry_names: set[str], target: int) -> list[list[str]]:
    """Greedy bin-pack files into groups of ~target units, directory-cohesive, entry-first."""
    def is_entry(f: str) -> bool:
        return pathlib.Path(f).name in entry_names

    # entry-reachable first, then directory-cohesive (same dir adjacent), then path.
    ordered = sorted(
        file_units,
        key=lambda f: (0 if is_entry(f) else 1, str(pathlib.Path(f).parent), f),
    )
    groups: list[list[str]] = []
    cur: list[str] = []
    cur_count = 0
    for f in ordered:
        c = file_units[f]
        # Close the current group before a big file (single-file group) or an overflow.
        if cur and (c >= target or cur_count + c > target):
            groups.append(cur)
            cur, cur_count = [], 0
        cur.append(f)
        cur_count += c
        if cur_count >= target:
            groups.append(cur)
            cur, cur_count = [], 0
    if cur:
        groups.append(cur)
    return groups


def main() -> None:
    run_dir = pathlib.Path(sys.argv[1])
    target = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TARGET_UNITS
    src_list = run_dir / "work" / "source-files.txt"
    out_file = run_dir / "work" / "worklist.jsonl"

    files: list[str] = []
    seen: set[str] = set()
    for line in src_list.read_text().splitlines():
        f = line.strip()
        if f and f not in seen:
            seen.add(f)
            files.append(f)

    file_units: dict[str, int] = {}
    skipped_missing: list[str] = []
    non_python_files: list[str] = []
    n = 0
    with out_file.open("w") as w:
        for f in files:
            p = pathlib.Path(f)
            if not p.exists():
                skipped_missing.append(f)
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            h = hashlib.sha256(src.encode("utf-8", "replace")).hexdigest()[:16]
            count, non_py = _emit_units(w, f, src, h)
            file_units[f] = count
            n += count
            if non_py:
                non_python_files.append(f)

    groups = _group(file_units, _entry_basenames(run_dir), target)
    groups_file = run_dir / "work" / "unit-review-groups.jsonl"
    with groups_file.open("w") as g:
        for i, grp in enumerate(groups, 1):
            g.write(json.dumps({
                "unit_id": f"unit-{i:03d}",
                "files": grp,
                "unit_count": sum(file_units[x] for x in grp),
            }, ensure_ascii=False) + "\n")

    (run_dir / "work" / "unit-review-plan.json").write_text(json.dumps({
        "source_file_count": len(file_units),
        "group_count": len(groups),
        "grouping_strategy": "by-unit-count",
        "target_units_per_group": target,
        "total_units": n,
    }, indent=2, ensure_ascii=False))

    scope = {
        "files_in": len(files),
        "worklist_units": n,
        "non_python_files": non_python_files,
        "non_python_file_count": len(non_python_files),
        "skipped_missing_count": len(skipped_missing),
        "note": "whole-repo: Python -> AST units; non-Python -> file-level unit",
    }
    (run_dir / "work/worklist-scope.json").write_text(
        json.dumps(scope, indent=2, ensure_ascii=False)
    )
    print(f"worklist units: {n} | files: {len(file_units)} | groups: {len(groups)} "
          f"(target {target} units/group) | non-python: {len(non_python_files)}")


if __name__ == "__main__":
    main()
