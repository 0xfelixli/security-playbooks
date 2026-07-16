---
id: security-diff-review-lite
uri: owner://security-diff-review-lite
version: '2026.07.16'
title: Security Diff Review Lite
summary: 'Thin launcher: resolve the Phabricator revision, then run diff_review_talon_comment.py which fetches the diff, audits it with talon --diff-file -, and posts the result as a comment.'
attended_mode: unattended
approval_policy: auto-normal
inputs:
  revision_id:
    type: string
    required: false
    default: ''
    description: Phabricator Differential Revision id, e.g. D118482. If empty, extracted from event_context.
  event_context:
    type: object
    required: false
    default: {}
    description: Sanitized event payload injected by Workmate event automations. Used to extract subject.display_id.
  post_comment:
    type: boolean
    required: false
    default: true
    description: Passed to the script as POST_COMMENT (1/0). When false the script prints the comment but does not post.
  max_diff_chars:
    type: number
    required: false
    default: 60000
    description: Passed to the script as MAX_DIFF_CHARS — cap on diff bytes piped to talon.
actors:
  runner:
    provider: codex
    mode: edit
    context_scope: fresh
workflow:
- job:
    actor: runner
    wall_clock_seconds: 3600
    timeout: 3600
    prompt: |
      {% set subj = inputs.event_context.get('subject', {}) if inputs.event_context else {} %}
      解析 revision_id，然后运行安全 diff review 脚本。脚本自身完成：抓最新 diff → `talon --diff-file -` 审计 → 通过 Conduit 发评论。你只是启动器：定位并运行脚本、把它的 JSON 输出原样带回。不要自己审 diff、不要调 MCP、不要自己发评论。

      Step 1 — 解析 revision_id（不读本地文件/不猜）：
      优先 `{{ inputs.revision_id }}`（非空且非模板字面量）；否则用 event display_id `{{ subj.get('display_id', '') }}`。
      纯数字如 `118556` 归一为 `D118556`；已 `D` 开头保留。
      若拿不到以 `D` 开头的合法 id → 直接结束：posted=false, skipped_reason="no resolvable revision id", 不运行脚本。

      Step 2 — 定位脚本：
      运行 `printenv WORKMATE_FS_READ_ALLOWLIST`（`:` 分隔的绝对路径），取最后一段为 `security-diff-review-lite` 的条目 P；SCRIPT=`P/diff_review_talon_comment.py`。
      若从 allowlist 找不到，兜底用固定部署路径 `/workspace/workmate/.workmate/playbooks/security-diff-review-lite/diff_review_talon_comment.py`。两者都不存在 → posted=false, error 说明。

      Step 3 — 运行脚本（pod 环境已含 PHA_API_TOKEN / PHA_API_URL / TALON 相关配置）：
      ```bash
      POST_COMMENT={% if inputs.post_comment %}1{% else %}0{% endif %} MAX_DIFF_CHARS={{ inputs.max_diff_chars }} python3 "$SCRIPT" "<解析出的 revision_id>"
      ```
      脚本向 stdout 打印一行 JSON：`{revision_id, status, findings, posted, skipped_reason}`。发帖由脚本完成，你不要重复发。

      Step 4 — 解析脚本最后一行 JSON 填入 output。脚本非零退出或无 JSON → 填 error（附 stderr 末尾片段）。

      结构化输出返回，无 ask_owner。收到 `{"ok": true}` 后立即结束。
    output_schema:
      revision_id: string
      status: string
      findings: number
      posted: boolean
      skipped_reason: string
      error: string
    output: run
- done:
    message: |
      Security Diff Review Lite finished for {{ artifacts.run.revision_id }}. status={{ artifacts.run.status }} findings={{ artifacts.run.findings }} posted={{ artifacts.run.posted }}{% if artifacts.run.error %} error={{ artifacts.run.error }}{% endif %}

---

# Security Diff Review Lite

Thin launcher playbook. A single `runner` actor resolves the revision id (from event_context / revision_id),
locates the bundled `diff_review_talon_comment.py` (shipped in this playbook dir, found via
WORKMATE_FS_READ_ALLOWLIST), and runs it. The script does all the real work — fetch the latest diff via
Conduit, audit it with `talon --diff-file -`, and post the audit as a comment on the revision — so the
playbook itself holds no review logic and needs no MCP grant (the script talks to Conduit directly using
the pod's PHA_API_TOKEN). Participant gating (subscriber/reviewer/author) is done upstream by the Workmate
gateway source_filter.
