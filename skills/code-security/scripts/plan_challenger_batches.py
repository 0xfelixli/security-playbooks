"""Plan the challenger adversarial-review batches deterministically.

Usage: python3 plan_challenger_batches.py <RUN_DIR> <challenger_max_ratio> [batch_size]

This is the mechanical half of the report stage's issue_merger job (task B),
pulled out of the LLM turn so it cannot stall: sorting / quota / batching /
skipped-quota marking are pure computation and must be deterministic.

Reads:  <RUN_DIR>/issues/index.jsonl        (canonical issues, source of truth)
Writes: <RUN_DIR>/work/challenger-dispatch.jsonl   (one line per batch)
        frontmatter of skipped-quota issue files   (adversarial_verdict etc.)
        appends a section to <RUN_DIR>/audit-log.md
Prints: one JSON line for the calling actor to relay into its output:
        {total_canonical, challenger_quota, actual_quota, selected_count,
         skipped_quota, batch_count, challenger_batches}

No cobo_agents import, no cwd dependence, no third-party deps (no pyyaml) —
runs with any python3. index.jsonl already carries issue_file / severity /
discovery_verdict / canonical, so no markdown frontmatter parsing is needed to
plan; frontmatter is only *written* for skipped issues via a minimal setter.
"""
import json
import math
import pathlib
import sys

_SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
_VERDICT_RANK = {"confirmed": 0, "escalate": 1, "blocked": 2, "refuted": 3}
_FORCED_SEVERITIES = {"CRITICAL", "HIGH"}
_DEFAULT_BATCH_SIZE = 5


def _read_index(run_dir: pathlib.Path) -> list[dict]:
    index_path = run_dir / "issues" / "index.jsonl"
    if not index_path.is_file():
        return []
    rows: list[dict] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("canonical") is True:
            rows.append(row)
    return rows


def _sort_key(row: dict):
    sev = _SEVERITY_RANK.get(str(row.get("severity", "")).upper(), 99)
    verdict = _VERDICT_RANK.get(str(row.get("discovery_verdict", "")).lower(), 99)
    return (sev, verdict, str(row.get("issue_id", "")))


def _set_frontmatter_keys(issue_file: pathlib.Path, updates: dict[str, str]) -> None:
    # Minimal, dependency-free YAML-frontmatter setter. Operates ONLY inside the
    # first '---' ... '---' fence and only on '^key:' scalar lines, so it can
    # never corrupt the markdown body. Replaces an existing key line or inserts
    # a new one before the closing fence.
    if not issue_file.is_file():
        return
    lines = issue_file.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return
    close = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        return
    remaining = dict(updates)
    for i in range(1, close):
        stripped = lines[i].lstrip()
        for key in list(remaining):
            if stripped.startswith(f"{key}:"):
                indent = lines[i][: len(lines[i]) - len(stripped)]
                lines[i] = f"{indent}{key}: {remaining.pop(key)}"
                break
    if remaining:
        insert = [f"{key}: {val}" for key, val in remaining.items()]
        lines[close:close] = insert
        close += len(insert)
    issue_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _yaml_scalar(value: str) -> str:
    # Quote when the value contains YAML-significant characters; enums stay bare.
    if value and all(c.isalnum() or c in "_-" for c in value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    run_dir = pathlib.Path(sys.argv[1]).expanduser()
    try:
        ratio = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].strip() else 0.3
    except ValueError:
        ratio = 0.3
    ratio = min(1.0, max(0.0, ratio))
    try:
        batch_size = int(sys.argv[3]) if len(sys.argv) > 3 else _DEFAULT_BATCH_SIZE
    except ValueError:
        batch_size = _DEFAULT_BATCH_SIZE
    batch_size = max(1, batch_size)

    canonical = _read_index(run_dir)
    n = len(canonical)
    canonical.sort(key=_sort_key)

    quota = 0 if n == 0 else max(1, math.ceil(n * ratio))
    forced = sum(
        1 for r in canonical if str(r.get("severity", "")).upper() in _FORCED_SEVERITIES
    )
    actual_quota = 0 if n == 0 else max(quota, forced)

    selected = canonical[:actual_quota]
    skipped = canonical[actual_quota:]

    # Batch selected issue files (absolute paths) into groups of batch_size.
    selected_paths = [str(r.get("issue_file", "")) for r in selected if r.get("issue_file")]
    batches = [
        selected_paths[i : i + batch_size]
        for i in range(0, len(selected_paths), batch_size)
    ]

    work_dir = run_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    dispatch = work_dir / "challenger-dispatch.jsonl"
    with dispatch.open("w", encoding="utf-8") as fh:
        for idx, batch in enumerate(batches):
            fh.write(
                json.dumps({"batch_index": idx, "issue_paths": batch}, ensure_ascii=False)
                + "\n"
            )

    # Mark skipped-quota issues in their frontmatter (SCHEMA "final_verdict 计算"):
    # final_verdict = discovery_verdict, but refuted -> blocked (未经 challenger 不能杀).
    reason = f"challenger_quota_reached (N={n}, quota={quota})"
    for row in skipped:
        issue_file = row.get("issue_file")
        if not issue_file:
            continue
        discovery = str(row.get("discovery_verdict", "")).lower()
        final_verdict = "blocked" if discovery == "refuted" else discovery
        _set_frontmatter_keys(
            pathlib.Path(issue_file).expanduser(),
            {
                "adversarial_verdict": "skipped_quota",
                "final_verdict": final_verdict or "blocked",
                "final_verdict_reason": _yaml_scalar(reason),
            },
        )

    if skipped:
        log = run_dir / "audit-log.md"
        entry = [
            "",
            "## Challenger 预算截断（skipped_quota）",
            f"- N(canonical)={n} | challenger_max_ratio={ratio} | quota={quota} "
            f"| 强制(CRIT/HIGH)={forced} | actual_quota={actual_quota} | batch_size={batch_size}",
            f"- 入选复核 {len(selected_paths)} 条（{len(batches)} 批），跳过 {len(skipped)} 条：",
        ]
        for row in skipped:
            entry.append(
                f"  - {row.get('issue_id','')} | {row.get('severity','')} "
                f"| discovery={row.get('discovery_verdict','')}"
            )
        with log.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(entry) + "\n")

    print(
        json.dumps(
            {
                "total_canonical": n,
                "challenger_quota": quota,
                "actual_quota": actual_quota,
                "selected_count": len(selected_paths),
                "skipped_quota": len(skipped),
                "batch_count": len(batches),
                "challenger_batches": batches,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
