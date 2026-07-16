---
id: security-diff-review-lite
uri: owner://security-diff-review-lite
version: '2026.07.16'
title: Security Diff Review Lite
summary: 'Actor fetches the revision diff via MCP, runs talon_review.py (talon diff-only audit), and posts the result as a comment via MCP.'
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
    description: When true, post the talon review result back to the revision. When false, only produce it.
  max_diff_chars:
    type: number
    required: false
    default: 600000
    description: Passed to the script as MAX_DIFF_CHARS — cap on diff bytes piped to talon.
mcp:
  # All Phabricator I/O is done by the actor through its MCP grant (direct Conduit is blocked on the pod).
  # The bundled talon_review.py does NOT touch the network — it only runs talon on the diff text.
  - server_id: "000000000007"
    tools:
      - pha_diff_get
      - pha_diff_get_content
      - pha_diff_add_comment
    purpose: "Resolve the latest diff id, fetch the raw unified diff, and post the talon security review comment."
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
      你负责编排：用 MCP 取 diff → 运行 talon 脚本审计 → 用 MCP 发评论。全部 Phabricator I/O 走 MCP server `000000000007`（pod 上直连 Conduit 不通）。talon 脚本不联网，只审 diff。

      Step 1 — 解析 revision_id：
      优先 `{{ inputs.revision_id }}`（非空且非模板字面量）；否则用 event display_id `{{ subj.get('display_id', '') }}`。
      纯数字归一为 `D<n>`；已 `D` 开头保留。拿不到合法 `D<n>` → 结束：posted=false, status=blocked, skipped_reason="no resolvable revision id"，不继续。

      Step 2 — 取最新 diff id（MCP）：
      调 `pha_diff_get`（server `000000000007`，revision_id=解析出的 D 号）。从返回的 `revision.all_diffs[]` 里取 `phid == revision.fields.diffPHID` 那条的 `id`；找不到就取 `all_diffs[0].id`（newest-first）。拿不到 → status=blocked, error 说明，跳到 Step 6 发 blocked 评论。

      Step 3 — 取 raw diff（MCP）：
      调 `pha_diff_get_content`（diff_id=上一步的数字 id），取返回的 `diff_content`。空 → status=blocked。

      Step 4 — 定位并运行 talon 脚本：
      `printenv WORKMATE_FS_READ_ALLOWLIST`，取最后一段为 `security-diff-review-lite` 的条目 P；SCRIPT=`P/talon_review.py`；allowlist 找不到则兜底 `/workspace/workmate/.workmate/playbooks/security-diff-review-lite/talon_review.py`。
      把 raw diff 写入一个临时文件（如 `/tmp/diff_<revision>.diff`），运行：
      ```bash
      MAX_DIFF_CHARS={{ inputs.max_diff_chars }} python3 "$SCRIPT" --revision <D号> --diff-file <临时文件>
      ```
      脚本向 stdout 打印一行 JSON：`{revision_id, status, findings, should_post, comment_markdown}`。解析它。脚本非零退出/无 JSON → status=blocked, error 记 stderr 末尾。

      Step 5 — 发评论（MCP，仅当 `{{ inputs.post_comment }}` 为 true 且 should_post 为 true）：
      调 `pha_diff_add_comment`（revision_id=D号, comment=脚本给的 `comment_markdown`, action=`comment`）。绝不 accept/reject。成功→posted=true；失败→posted=false, skipped_reason=错误。
      post_comment=false → 不发，skipped_reason="post_comment=false"。

      Step 6 — blocked 兜底：若前面 status=blocked，comment_markdown 用一句「⚠️ 安全 diff review 未能完成：<原因>」；仍按 Step 5 规则（post_comment=true 时）发出去。

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

A single `runner` actor orchestrates the review. Because direct Conduit is blocked on the pod, ALL
Phabricator I/O goes through the actor's MCP grant (server 000000000007): it resolves the latest diff
id via `pha_diff_get`, fetches the raw unified diff via `pha_diff_get_content`, runs the bundled
`talon_review.py` (talon `--diff-file -`, network-free — just the audit + Chinese comment markdown),
then posts the result via `pha_diff_add_comment`. Participant gating (subscriber/reviewer/author) is
done upstream by the Workmate gateway source_filter. Speed comes from talon doing the review out of the
actor's context rather than the actor reasoning over the whole diff itself.
