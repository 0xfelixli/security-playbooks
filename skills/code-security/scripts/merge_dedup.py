"""Deduplicate discovery issues and build issues/index.jsonl deterministically.

Usage: python3 merge_dedup.py <RUN_DIR>

This is the mechanical half of the report stage's issue_merger job (task A),
pulled out of the LLM turn so it cannot stall. It reads machine-readable issue
metadata sidecars (JSON — written by unit_reviewer alongside each issue .md),
NOT the LLM-authored markdown frontmatter, so parsing is unambiguous and needs
no pyyaml (mirrors how reconcile_coverage.py reads unit-records JSON).

Reads:  <RUN_DIR>/work/issue-meta/*.json   (one per issue, discovery-time fields)
Writes: <RUN_DIR>/issues/index.jsonl        (one line per canonical issue)
        canonical / duplicate_files / severity into canonical issue .md frontmatter
        canonical:false / superseded_by / duplicate_reason into non-canonical .md
Prints: one JSON line for the calling actor to relay into its output:
        {total_issues, total_canonical, discovery_confirmed, discovery_escalate,
         discovery_refuted, discovery_blocked}

Dedup key / severity 收敛 / canonical 选择 follow SCHEMA-issue.md 去重 key 规范.
No cobo_agents import, no cwd dependence, no third-party deps — any python3.
"""
import json
import pathlib
import re
import sys

_SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
_COMPLETENESS_FIELDS = ("primary_symbol", "cwe", "primary_location", "vuln_type", "authn_level")


def _read_metas(run_dir: pathlib.Path) -> list[dict]:
    meta_dir = run_dir / "work" / "issue-meta"
    if not meta_dir.is_dir():
        return []
    metas: list[dict] = []
    for mf in sorted(meta_dir.glob("*.json")):
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(m, dict) and m.get("issue_id") and m.get("issue_file"):
            metas.append(m)
    return metas


def _dedup_key(meta: dict):
    cwe = (str(meta.get("cwe", "")).strip() or "CWE-UNKNOWN")
    # CWE-UNKNOWN 视为唯一 key，永不折叠（recall-safe）
    if cwe.upper() == "CWE-UNKNOWN":
        return ("unknown", str(meta.get("issue_id", "")))
    sym = str(meta.get("primary_symbol", "")).strip()
    if sym:
        norm = re.sub(r"[^a-z0-9_]", "", sym.rsplit(".", 1)[-1].lower())
        return ("sym", norm, cwe)
    eps = meta.get("affected_entrypoints") or []
    if eps and str(eps[0]).strip():
        norm_ep = re.sub(r"[<{][^>}]*[>}]", "<>", str(eps[0]))
        return ("ep", norm_ep, cwe)
    loc = str(meta.get("primary_location", "")).strip()
    file_part, _, line_part = loc.rpartition(":") if ":" in loc else (loc, "", "")
    return ("fl", file_part, line_part, cwe)


def _completeness(meta: dict) -> int:
    score = sum(1 for f in _COMPLETENESS_FIELDS if str(meta.get(f, "")).strip())
    score += len(meta.get("affected_entrypoints") or [])
    score += len(meta.get("discovery_category") or [])
    return score


def _max_severity(group: list[dict], fallback: str) -> str:
    best = fallback
    best_rank = _SEV_RANK.get(str(fallback).upper(), 99)
    for m in group:
        sev = str(m.get("severity", "")).upper()
        rank = _SEV_RANK.get(sev, 99)
        if rank < best_rank:
            best_rank, best = rank, sev
    return best


def _set_frontmatter_keys(issue_file: pathlib.Path, updates: dict[str, str]) -> None:
    # Minimal, dependency-free YAML-frontmatter setter (same contract as
    # plan_challenger_batches.py). Operates ONLY inside the first '---' ... '---'
    # fence, on '^key:' scalar lines; values are passed pre-formatted.
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
    issue_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    run_dir = pathlib.Path(sys.argv[1]).expanduser()
    metas = _read_metas(run_dir)

    groups: dict[tuple, list[dict]] = {}
    for m in metas:
        groups.setdefault(_dedup_key(m), []).append(m)

    canonicals: list[dict] = []
    index_rows: list[dict] = []
    for members in groups.values():
        # canonical: primary_symbol 非空优先 → 信息最完整 → issue_id 稳定序
        members.sort(
            key=lambda m: (
                0 if str(m.get("primary_symbol", "")).strip() else 1,
                -_completeness(m),
                str(m.get("issue_id", "")),
            )
        )
        canon = members[0]
        others = members[1:]
        max_sev = _max_severity(members, str(canon.get("severity", "")))
        dup_files = [str(o.get("issue_file", "")) for o in others if o.get("issue_file")]

        # Mark frontmatter: canonical + non-canonical.
        _set_frontmatter_keys(
            pathlib.Path(str(canon["issue_file"])).expanduser(),
            {
                "canonical": "true",
                "severity": max_sev,
                "duplicate_files": json.dumps(dup_files, ensure_ascii=False),
            },
        )
        canon_path = str(canon["issue_file"])
        for o in others:
            _set_frontmatter_keys(
                pathlib.Path(str(o["issue_file"])).expanduser(),
                {
                    "canonical": "false",
                    "superseded_by": json.dumps(canon_path, ensure_ascii=False),
                    "duplicate_reason": json.dumps(
                        f"merged into {canon.get('issue_id','')} (same dedup key)",
                        ensure_ascii=False,
                    ),
                },
            )

        index_rows.append(
            {
                "issue_id": canon.get("issue_id", ""),
                "issue_file": canon_path,
                "canonical": True,
                "discovery_verdict": canon.get("discovery_verdict"),
                "adversarial_verdict": None,
                "final_verdict": None,
                "severity_downgraded_to": None,
                "severity_upgraded_to": None,
                "discovery_category": canon.get("discovery_category") or [],
                "primary_location": canon.get("primary_location", ""),
                "primary_symbol": canon.get("primary_symbol", ""),
                "vuln_type": canon.get("vuln_type", ""),
                "cwe": canon.get("cwe", ""),
                "severity": max_sev,
                "authn_level": canon.get("authn_level", ""),
                "affected_entrypoints": canon.get("affected_entrypoints") or [],
                "duplicate_files": dup_files,
            }
        )
        canonicals.append(canon)

    # Stable index order: severity then issue_id.
    index_rows.sort(
        key=lambda r: (_SEV_RANK.get(str(r.get("severity", "")).upper(), 99), str(r.get("issue_id", "")))
    )
    issues_dir = run_dir / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    (issues_dir / "index.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in index_rows),
        encoding="utf-8",
    )

    buckets = {"confirmed": 0, "escalate": 0, "refuted": 0, "blocked": 0}
    for r in index_rows:
        v = str(r.get("discovery_verdict", "")).lower()
        if v in buckets:
            buckets[v] += 1

    print(
        json.dumps(
            {
                "total_issues": len(metas),
                "total_canonical": len(index_rows),
                "discovery_confirmed": buckets["confirmed"],
                "discovery_escalate": buckets["escalate"],
                "discovery_refuted": buckets["refuted"],
                "discovery_blocked": buckets["blocked"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
