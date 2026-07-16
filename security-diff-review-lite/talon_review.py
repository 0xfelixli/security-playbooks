#!/usr/bin/env python3
"""Talon-only diff security review. Reads a raw unified diff, audits it with `talon --diff-file -`,
and prints a one-line JSON result with a ready-to-post Chinese `comment_markdown`.

No network, no Conduit, no MCP: the Workmate playbook actor fetches the diff and posts the comment
through its own MCP grant. This script just runs talon and formats the result.

Usage (diff on stdin):
    talon_review.py --revision D118482 < changed.diff
    talon_review.py --revision D118482 --diff-file changed.diff

Env:
  TALON_DIR       talon checkout dir. Default: /workspace/cobo-code-security-review
  TALON_CMD       talon invocation. Default: "uv run talon"
  TALON_TIMEOUT   talon subprocess timeout (s). Default: 3000.
  MAX_DIFF_CHARS  cap on diff bytes piped to talon. Default: 600000.

Output JSON: {revision_id, status, findings, should_post, comment_markdown}.
  status ∈ {security-issues-found, no-obvious-security-issue, blocked}.
  should_post is always True (the actor gates on its own post_comment input); blocked also posts
  a "无法审查" note so every reviewed revision gets a comment.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MARKER_PREFIX = "workmate-security-diff-review-talon"
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _argv_opt(name: str) -> str:
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return ""


# --------------------------------------------------------------------------- talon

def truncate_diff(text: str, max_chars: int) -> tuple[str, bool]:
    """Clip to <= max_chars at a file boundary (`\\ndiff --git `), else a newline — never mid-line."""
    if len(text) <= max_chars:
        return text, False
    head = text[:max_chars]
    cut = head.rfind("\ndiff --git ")
    if cut <= 0:
        cut = head.rfind("\n")
    if cut <= 0:
        cut = max_chars
    return text[:cut], True


def run_talon(diff_text: str) -> list[dict]:
    """Pipe the diff into `talon --diff-file - -n`, return the findings list."""
    talon_dir = Path(os.environ.get("TALON_DIR", "/workspace/cobo-code-security-review"))
    if not talon_dir.is_dir():
        raise RuntimeError(f"TALON_DIR not found: {talon_dir}")
    cmd = os.environ.get("TALON_CMD", "uv run talon").split()
    cmd += ["--diff-file", "-", "-n"]
    proc = subprocess.run(
        cmd,
        cwd=str(talon_dir),
        input=diff_text,
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("TALON_TIMEOUT", "3000")),
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    candidates = []
    m = re.search(r"Report:\s*(\S+)", combined)
    if m:
        candidates.append(Path(m.group(1).strip()) / "vulnerabilities.json")
    candidates += sorted(
        talon_dir.glob("talon_runs/*/vulnerabilities.json"),
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

def build_comment(revision_id: str, findings: list[dict], status: str, note: str = "", truncated: bool = False) -> str:
    marker = f"<!-- {MARKER_PREFIX} revision={revision_id} status={status} -->"
    trunc_note = "\n\n> ⚠️ diff 超长已截断，尾部未审查。" if truncated else ""
    if status == "blocked":
        return f"⚠️ 安全 diff review 未能完成：{note}\n\n{marker}"
    if not findings:
        return f"🔒 安全 diff review（talon）：✅ 已审查，未见明显安全问题。{trunc_note}\n\n{marker}"
    findings = sorted(findings, key=lambda f: SEV_ORDER.get((f.get("severity") or "low").lower(), 9))
    lines = [f"🔒 安全 diff review（talon）：发现 {len(findings)} 个问题{trunc_note}\n"]
    for f in findings:
        sev = (f.get("severity") or "").upper()
        title = f.get("title") or "(untitled)"
        cwe = f" · {f.get('cwe')}" if f.get("cwe") else ""
        locs = f.get("code_locations") or []
        loc = ""
        if locs:
            first = locs[0]
            loc = f" · `{first.get('file','?')}:{first.get('start_line','?')}`"
        lines.append(f"**[{sev}] {title}**{cwe}{loc}")
        if f.get("description"):
            lines.append(str(f["description"]).strip())
        if f.get("remediation_steps"):
            lines.append(f"_修复_：{str(f['remediation_steps']).strip()}")
        lines.append("")
    lines.append(marker)
    return "\n".join(lines)


# --------------------------------------------------------------------------- main

def main() -> int:
    revision_id = _argv_opt("--revision") or "D?"
    max_chars = int(os.environ.get("MAX_DIFF_CHARS", "600000"))

    diff_file = _argv_opt("--diff-file")
    diff_text = Path(diff_file).read_text("utf-8") if diff_file else sys.stdin.read()

    status, note, findings, truncated = "ok", "", [], False
    try:
        if not diff_text.strip():
            status, note = "blocked", "diff 为空"
        else:
            clipped, truncated = truncate_diff(diff_text, max_chars)
            findings = run_talon(clipped)
    except Exception as exc:  # noqa: BLE001 — any failure becomes a blocked comment
        status, note = "blocked", f"{type(exc).__name__}: {exc}"

    comment_status = "blocked" if status == "blocked" else (
        "security-issues-found" if findings else "no-obvious-security-issue"
    )
    markdown = build_comment(revision_id, findings, comment_status, note, truncated)

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
