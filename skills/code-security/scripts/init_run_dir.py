"""Initialize a security-audit RUN_DIR and resolve bundle paths.

Usage: python3 init_run_dir.py <repo_path> [audit_skills_override] [artifacts_root_override]

Deterministic scaffolding for the audit run (no LLM judgment):
- Resolve audit_skills_dir. The override arg is the SKILLS dir that the init
  playbook's skills_locator/initializer already selected (synced-root or bundle),
  NOT a user-facing input — that input was removed. When empty, default to this
  script's own skill root (__file__.parent.parent, i.e. .../code-security).
- Resolve scripts_dir (bundle scripts/)
- Validate the skills layout (rules/ + guides/ both present) — done in-process so
  it is NOT subject to the actor's filesystem-allowlist hook
- Generate RUN_ID and create RUN_DIR + standard subdirectories
- Resolve the artifacts root: artifacts live in <root>/<repo_slug>/, always independent
  of the audited repo — the audited repo is read-only and never written to. The root is
  artifacts_root_override when given, else the default ~/workmate/security-audit.

Prints a single JSON object to stdout for the calling actor to capture.
"""
import datetime
import json
import pathlib
import re
import sys


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "target"


def _resolve_bundle_paths(audit_skills_override: str) -> tuple[pathlib.Path, pathlib.Path]:
    # This script lives at <skill>/scripts/init_run_dir.py, so its own parent is the
    # scripts dir and its grandparent is the skill root (code-security). Resolve from
    # __file__ so the script never needs the cobo_agents package importable — it runs
    # even in a bare env (cron/headless) once located.
    scripts_dir = pathlib.Path(__file__).resolve().parent  # <skill>/scripts
    skill_root = scripts_dir.parent  # <skill> = code-security
    override = audit_skills_override.strip()
    if override:
        skills_dir = pathlib.Path(override).expanduser()
    else:
        skills_dir = skill_root
    return skills_dir, scripts_dir


def main(
    repo_path: str,
    audit_skills_override: str = "",
    artifacts_root_override: str = "",
) -> None:
    repo = pathlib.Path(repo_path).expanduser().resolve()
    skills_dir, scripts_dir = _resolve_bundle_paths(audit_skills_override)

    missing = [
        str(skills_dir / sub)
        for sub in ("rules", "guides")
        if not (skills_dir / sub).is_dir()
    ]
    # SCHEMA-issue.md is hard-required by unit_reviewer / coverage_critic /
    # final_reporter downstream; fail fast here instead of mid-scan/report.
    if not (skills_dir / "SCHEMA-issue.md").is_file():
        missing.append(str(skills_dir / "SCHEMA-issue.md"))
    if missing:
        print(json.dumps({
            "error": "audit_skills_invalid",
            "skills_dir": str(skills_dir),
            "missing": missing,
        }, ensure_ascii=False))
        sys.exit(1)

    now = datetime.datetime.now()
    run_id = f"{now:%Y%m%d-%H%M%S}_playbook_{_slug(repo.name)}"
    override = artifacts_root_override.strip()
    # 产物根：<root>/<repo_slug>/，与被审计仓库彻底分开，绝不往源码库里写一个字。
    # 留空时默认 ~/workmate/security-audit（repo_path 是纯只读输入，任何情况都不落进 repo）。
    root = pathlib.Path(override).expanduser() if override else pathlib.Path("~/workmate/security-audit").expanduser()
    artifacts_root = root.resolve() / _slug(repo.name)
    run_dir = artifacts_root / run_id
    for sub in ("entrypoints", "analysis", "issues", "verify", "work"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)

    audit_log = run_dir / "audit-log.md"
    if not audit_log.exists():
        audit_log.write_text(
            "# 安全审计日志\n\n"
            f"- 目标目录：{repo}\n"
            f"- RUN_ID：{run_id}\n"
            f"- 启动时间：{now:%Y-%m-%d %H:%M:%S}\n\n"
            "## 入口枚举\n\n",
            encoding="utf-8",
        )

    cumulative = run_dir / "cumulative-issues.md"
    if not cumulative.exists():
        cumulative.write_text(
            "# 累积 Issue 清单\n\n"
            "按类别累积去重，记录每轮扫描发现的 issue。\n\n",
            encoding="utf-8",
        )

    print(json.dumps({
        "run_id": run_id,
        "run_dir": str(run_dir),
        "audit_skills_dir": str(skills_dir),
        "scripts_dir": str(scripts_dir),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else "",
        sys.argv[3] if len(sys.argv) > 3 else "",
    )
