#!/usr/bin/env python3
"""Talon-only diff review: read a raw unified diff (stdin or --diff-file), audit with
`talon --diff-file -`, print one-line JSON with a ready-to-post Chinese `comment_markdown`.
No Phabricator I/O — the playbook actor fetches the diff and posts the comment.

    talon_review.py --revision D118482 < changed.diff

Env: TALON_CMD (default "talon" on PATH; set "uv run talon" for a checkout), TALON_DIR (optional
cwd for a checkout install), TALON_TIMEOUT (3000). The full diff is passed to talon — never truncated.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEV_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}


def _argv_opt(name: str) -> str:
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return ""


# --------------------------------------------------------------------------- talon

def run_talon(diff_text: str) -> list[dict]:
    """Pipe the diff into `talon --diff-file - -n`, return the findings list."""
    talon_dir_env = os.environ.get("TALON_DIR", "").strip()
    talon_dir = Path(talon_dir_env) if talon_dir_env else None
    if talon_dir is not None and not talon_dir.is_dir():
        raise RuntimeError(f"TALON_DIR set but not a dir: {talon_dir}")
    cwd = str(talon_dir) if talon_dir else None
    cmd = os.environ.get("TALON_CMD", "talon").split()  # PATH-installed talon; override "uv run talon" for a checkout
    cmd += ["--diff-file", "-", "-n"]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        input=diff_text,
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("TALON_TIMEOUT", "3000")),
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    base = talon_dir if talon_dir else Path.cwd()
    candidates = []
    m = re.search(r"Report:\s*(\S+)", combined)
    if m:
        candidates.append(Path(m.group(1).strip()) / "vulnerabilities.json")
    candidates += sorted(
        base.glob("talon_runs/*/vulnerabilities.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for vjson in candidates:
        if vjson.is_file():
            loaded = json.loads(vjson.read_text("utf-8"))
            if isinstance(loaded, list):
                return loaded
            if isinstance(loaded, dict):
                return loaded.get("findings") or loaded.get("vulnerabilities") or []
    if proc.returncode != 0:
        raise RuntimeError(f"talon exited {proc.returncode}: {combined.strip()[-800:]}")
    return []


# --------------------------------------------------------------------------- markdown

def build_comment(findings: list[dict], status: str, note: str = "") -> str:
    requester = os.environ.get("REVIEW_REQUESTED_BY", "defei.li@cobo.com")
    footer = f"\n\n---\n🤖 //Automated security review requested by {requester}//"
    if status == "blocked":
        return f"⚠️ **安全 Diff Review · 未能完成**\n\n> {note}{footer}"
    if not findings:
        return f"🔒 **安全 Diff Review** · talon\n\n✅ 已审查，未见明显安全问题。{footer}"

    findings = sorted(findings, key=lambda f: SEV_ORDER.get((f.get("severity") or "low").lower(), 9))
    counts: dict[str, int] = {}
    for f in findings:
        s = (f.get("severity") or "low").lower()
        counts[s] = counts.get(s, 0) + 1
    tally = " · ".join(
        f"{SEV_EMOJI.get(s, '⚪')} {counts[s]} {s}" for s in ("critical", "high", "medium", "low") if counts.get(s)
    )
    lines = [f"🔒 **安全 Diff Review** · talon", "", f"发现 **{len(findings)}** 个问题：{tally}", ""]
    for f in findings:
        sev = (f.get("severity") or "low").lower()
        emoji = SEV_EMOJI.get(sev, "⚪")
        title = f.get("title") or "(untitled)"
        meta = []
        locs = f.get("code_locations") or []
        if locs:
            meta.append(f"`{locs[0].get('file', '?')}:{locs[0].get('start_line', '?')}`")
        if f.get("cwe"):
            meta.append(str(f["cwe"]))
        meta_str = (" · " + " · ".join(meta)) if meta else ""
        lines.append(f"{emoji} **{sev.upper()} · {title}**{meta_str}")
        if f.get("description"):
            lines.append(f"> {str(f['description']).strip()}")
        if f.get("remediation_steps"):
            lines.append(f"**修复**：{str(f['remediation_steps']).strip()}")
        lines.append("")
    return "\n".join(lines).rstrip() + footer


# --------------------------------------------------------------------------- main

def main() -> int:
    revision_id = _argv_opt("--revision") or "D?"

    diff_file = _argv_opt("--diff-file")
    diff_text = Path(diff_file).read_text("utf-8") if diff_file else sys.stdin.read()

    status, note, findings = "ok", "", []
    try:
        if not diff_text.strip():
            status, note = "blocked", "diff 为空"
        else:
            findings = run_talon(diff_text)
    except Exception as exc:  # noqa: BLE001 — any failure becomes a blocked comment
        status, note = "blocked", f"{type(exc).__name__}: {exc}"

    comment_status = "blocked" if status == "blocked" else (
        "security-issues-found" if findings else "no-obvious-security-issue"
    )
    markdown = build_comment(findings, comment_status, note)

    print(json.dumps({
        "revision_id": revision_id,
        "status": comment_status,
        "findings": len(findings),
        "should_post": True,
        "comment_markdown": markdown,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
