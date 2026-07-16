#!/usr/bin/env python3
"""Fetch a Phabricator revision's latest diff, run `talon --diff-file -`, post the audit as a comment.

Designed to run as a Workmate event automation (kind: script) on the pod, but also runnable by hand:

    PHA_API_TOKEN=... python3 diff_review_talon_comment.py D118482
    git diff origin/main... | PHA_API_TOKEN=... python3 diff_review_talon_comment.py D118482 --stdin-diff

Revision source priority: argv[1] -> WORKMATE_EVENT_CONTEXT_JSON (subject.display_id / subject.id).

Environment:
  PHA_API_URL      Conduit API base. Default: https://pha.1cobo.com/api
  PHA_API_TOKEN    Conduit API token. REQUIRED (not auto-injected into pod scripts — set it explicitly).
  TALON_DIR        talon checkout dir. Default: /workspace/cobo-code-security-review
  TALON_CMD        Override the talon invocation. Default: "uv run talon"
  POST_COMMENT     "1" to post (default), "0" to dry-run (print the comment, do not post).
  MAX_DIFF_CHARS   Cap on diff bytes piped to talon. Default: 60000.

Behavior: ALWAYS posts a comment when a valid revision id is resolvable (findings -> report them;
no findings -> "已审，未见问题"; fetch/talon failure -> "无法获取/审计失败"). Only skips when no
revision id is resolvable or POST_COMMENT=0.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MARKER_PREFIX = "workmate-security-diff-review-talon"
DEFAULT_SECRETS_FILE = "/workspace/workmate/.workmate/secrets/phabricator.env"


# --------------------------------------------------------------------------- secrets

def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines from a .env secrets file into os.environ (real env wins via setdefault)."""
    if not path.is_file():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


# --------------------------------------------------------------------------- Conduit (stdlib only)

def _flatten(prefix: str, value, out: dict[str, str]) -> None:
    """Phabricator conduit form-encoding: nested dicts/lists -> bracketed keys."""
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}[{k}]" if prefix else str(k), v, out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out[prefix] = "true" if value else "false"
    else:
        out[prefix] = str(value)


def conduit(method: str, params: dict) -> dict:
    api_url = os.environ.get("PHA_API_URL", "https://pha.1cobo.com/api").rstrip("/")
    token = os.environ.get("PHA_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("PHA_API_TOKEN is not set — cannot call Conduit")
    form: dict[str, str] = {}
    for k, v in params.items():
        _flatten(k, v, form)
    form["api.token"] = token
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(f"{api_url}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("error_code"):
        raise RuntimeError(f"Conduit {method} error: {payload.get('error_code')} {payload.get('error_info')}")
    return payload.get("result", {})


def resolve_latest_diff_id(revision_num: int) -> tuple[str, int]:
    """Return (revision_phid, latest_diff_id) for a numeric revision id."""
    rev = conduit("differential.revision.search", {"constraints": {"ids": [revision_num]}})
    data = rev.get("data") or []
    if not data:
        raise RuntimeError(f"revision D{revision_num} not found")
    phid = data[0]["phid"]
    diffs = conduit(
        "differential.diff.search",
        {"constraints": {"revisionPHIDs": [phid]}, "order": "newest", "limit": 1},
    )
    ddata = diffs.get("data") or []
    if not ddata:
        raise RuntimeError(f"no diff found for D{revision_num}")
    return phid, int(ddata[0]["id"])


def get_raw_diff(diff_id: int) -> str:
    # differential.getrawdiff returns the raw unified diff string as `result`.
    api_url = os.environ.get("PHA_API_URL", "https://pha.1cobo.com/api").rstrip("/")
    token = os.environ["PHA_API_TOKEN"].strip()
    data = urllib.parse.urlencode({"diffID": diff_id, "api.token": token}).encode()
    req = urllib.request.Request(f"{api_url}/differential.getrawdiff", data=data)
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("error_code"):
        raise RuntimeError(f"getrawdiff error: {payload.get('error_info')}")
    return payload.get("result") or ""


def post_comment(revision_id: str, markdown: str) -> None:
    conduit(
        "differential.revision.edit",
        {
            "objectIdentifier": revision_id,
            "transactions": [{"type": "comment", "value": markdown}],
        },
    )


# --------------------------------------------------------------------------- talon

def run_talon(diff_text: str, run_name: str) -> list[dict]:
    """Pipe the diff into `talon --diff-file - -n`, return the findings list."""
    talon_dir = Path(os.environ.get("TALON_DIR", "/workspace/cobo-code-security-review"))
    if not talon_dir.is_dir():
        raise RuntimeError(f"TALON_DIR not found: {talon_dir}")
    cmd = os.environ.get("TALON_CMD", "uv run talon").split()
    cmd += ["--diff-file", "-", "-n", "--run-name", run_name]
    proc = subprocess.run(
        cmd,
        cwd=str(talon_dir),
        input=diff_text,
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("TALON_TIMEOUT", "3000")),  # < job wall_clock (leave room for post)
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # talon prints `Report: <run_dir>` in its summary; prefer that, else fall back to talon_runs/<run_name>.
    run_dir = None
    m = re.search(r"Report:\s*(\S+)", combined)
    if m:
        run_dir = Path(m.group(1).strip())
    candidates = []
    if run_dir:
        candidates.append(run_dir / "vulnerabilities.json")
    candidates.append(talon_dir / "talon_runs" / run_name / "vulnerabilities.json")
    candidates += list(talon_dir.glob(f"**/{run_name}/vulnerabilities.json"))
    for vjson in candidates:
        if vjson.is_file():
            loaded = json.loads(vjson.read_text("utf-8"))
            if isinstance(loaded, list):
                return loaded
            if isinstance(loaded, dict):
                return loaded.get("findings") or loaded.get("vulnerabilities") or []
    if proc.returncode != 0:
        raise RuntimeError(f"talon exited {proc.returncode}: {combined.strip()[-800:]}")
    # No report file but talon succeeded → treat as clean.
    return []


# --------------------------------------------------------------------------- markdown

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


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

def resolve_revision() -> str:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    if argv:
        raw = argv[0]
    else:
        ev = json.loads(os.environ.get("WORKMATE_EVENT_CONTEXT_JSON", "{}") or "{}")
        subj = ev.get("subject") or {}
        raw = subj.get("display_id") or subj.get("id") or ""
    raw = str(raw).strip()
    if not raw:
        return ""
    if raw.upper().startswith("D") and raw[1:].isdigit():
        return "D" + raw[1:]
    if raw.isdigit():
        return "D" + raw
    return ""  # unrecognized -> no valid target


def main() -> int:
    load_env_file(Path(os.environ.get("PHA_SECRETS_FILE", DEFAULT_SECRETS_FILE)))
    post = os.environ.get("POST_COMMENT", "1") != "0"
    max_chars = int(os.environ.get("MAX_DIFF_CHARS", "60000"))

    revision_id = resolve_revision()
    if not revision_id:
        print(json.dumps({
            "revision_id": "", "status": "blocked", "findings": 0,
            "posted": False, "skipped_reason": "no resolvable revision id",
        }, ensure_ascii=False))
        return 0

    revision_num = int(revision_id[1:])
    status, note, findings, truncated = "ok", "", [], False
    try:
        if "--stdin-diff" in sys.argv:
            diff_text = sys.stdin.read()
            diff_id = 0
        else:
            _phid, diff_id = resolve_latest_diff_id(revision_num)
            diff_text = get_raw_diff(diff_id)
        if not diff_text.strip() or diff_text.lstrip().startswith("/workspace"):
            status, note = "blocked", "无法获取该 revision 的 diff 内容"
        else:
            clipped, truncated = truncate_diff(diff_text, max_chars)
            run_name = f"diffreview-{revision_id}-{diff_id}"
            findings = run_talon(clipped, run_name)
    except Exception as exc:  # noqa: BLE001 — any failure becomes a blocked comment
        status, note = "blocked", f"{type(exc).__name__}: {exc}"

    comment_status = "blocked" if status == "blocked" else (
        "security-issues-found" if findings else "no-obvious-security-issue"
    )
    markdown = build_comment(revision_id, findings, comment_status, note, truncated)

    posted = False
    skipped_reason = ""
    if not post:
        skipped_reason = "POST_COMMENT=0 (dry-run)"
        print("----- comment (dry-run) -----")
        print(markdown)
    else:
        try:
            post_comment(revision_id, markdown)
            posted = True
        except Exception as exc:  # noqa: BLE001
            skipped_reason = f"post failed: {type(exc).__name__}: {exc}"

    print(json.dumps({
        "revision_id": revision_id,
        "status": comment_status,
        "findings": len(findings),
        "posted": posted,
        "skipped_reason": skipped_reason,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
