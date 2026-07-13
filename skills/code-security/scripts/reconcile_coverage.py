"""Reconcile unit-review records against the AST worklist.

Usage: python3 reconcile_coverage.py <RUN_DIR>

Reads:  <RUN_DIR>/work/worklist.jsonl
        <RUN_DIR>/work/unit-records/*.json
Writes: <RUN_DIR>/coverage-audit.json
"""
import json
import pathlib
import sys


def main() -> None:
    run_dir = pathlib.Path(sys.argv[1])

    wl: dict[str, object] = {}
    for line in (run_dir / "work/worklist.jsonl").read_text().splitlines():
        if line.strip():
            u = json.loads(line)
            wl[u["unit_id"]] = u

    recs_dir = run_dir / "work/unit-records"
    records: dict[str, object] = {}
    if recs_dir.exists():
        for rf in recs_dir.glob("*.json"):
            try:
                r = json.loads(rf.read_text())
            except Exception:
                continue
            if r.get("unit_id"):
                records[r["unit_id"]] = r

    violations: dict[str, list[object]] = {
        "hash_mismatch": [],
        "phantom_unit": [],
        "lines_out_of_range": [],
        "empty_evidence": [],
        "weak_evidence": [],
        "blocked_empty_evidence": [],
    }
    state = {"reviewed_clean": 0, "reviewed_issue": 0, "reviewed_blocked": 0}
    covered: set[str] = set()

    # Hard violations invalidate a review — the unit is NOT counted as covered, so it
    # falls into missing_units and gets re-reviewed (a fabricated/stale review must not
    # inflate coverage). Soft violations (weak_evidence) stay covered but flagged.
    hard_invalid: list[str] = []
    for uid, r in records.items():
        u = wl.get(uid)
        if u is None:
            violations["phantom_unit"].append(uid)
            continue
        hard = False
        if r.get("file_hash") != u["file_hash"]:
            violations["hash_mismatch"].append(uid)
            hard = True
        lo, hi = u["lineno"], u["end_lineno"]
        for ln in r.get("lines_inspected", []):
            if not (lo <= ln <= hi):
                violations["lines_out_of_range"].append({"unit_id": uid, "line": ln})
                hard = True
                break
        verdict = r.get("verdict", "")
        evidence = (r.get("evidence") or "").strip()
        if verdict == "clean" and not evidence:
            violations["empty_evidence"].append(uid)
            hard = True
        elif verdict == "clean" and "`" not in evidence:
            violations["weak_evidence"].append(uid)
        elif verdict == "blocked" and not evidence:
            violations["blocked_empty_evidence"].append(uid)
        if hard:
            # invalid review: do not count as covered or reviewed — needs re-review
            hard_invalid.append(uid)
            continue
        if verdict == "clean":
            state["reviewed_clean"] += 1
        elif verdict == "issue":
            state["reviewed_issue"] += 1
        elif verdict == "blocked":
            state["reviewed_blocked"] += 1
        covered.add(uid)

    missing = sorted(uid for uid in wl if uid not in covered)
    audit = {
        "total_units": len(wl),
        "units_with_record": len(covered),
        "missing_units": missing,
        "missing_count": len(missing),
        "hard_invalid_units": sorted(hard_invalid),
        "hard_invalid_count": len(hard_invalid),
        "three_state": {
            "reviewed_clean": state["reviewed_clean"],
            "reviewed_issue": state["reviewed_issue"],
            "known_blind": len(missing) + state["reviewed_blocked"],
        },
        "integrity_violations": violations,
        "integrity_violation_count": sum(len(v) for v in violations.values()),
        "coverage_complete": len(missing) == 0,
    }
    (run_dir / "coverage-audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False)
    )
    print(json.dumps({
        "total": len(wl),
        "covered": len(covered),
        "missing": len(missing),
        "violations": audit["integrity_violation_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
