---
id: talon-diff
uri: owner://talon-diff
version: '2026.07.16'
title: Talon Diff Review
summary: 'Actor fetches the revision diff via MCP, runs talon_review.py (talon diff-only audit), posts the result as a comment via MCP, and Slack-notifies the author on CRITICAL/HIGH.'
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
mcp:
  # All Phabricator I/O is done by the actor through its MCP grant (direct Conduit is blocked on the pod).
  # The bundled talon_review.py does NOT touch the network — it only runs talon on the diff text.
  - server_id: "000000000007"
    tools:
      - pha_diff_get
      - pha_diff_get_content
      - pha_diff_add_comment
      - pha_user_search
    purpose: "Resolve the latest diff id, fetch the raw unified diff, post the review comment, and resolve the diff author for critical/high notifications."
  - server_id: "000000000006"
    tools:
      - Slack_Bot_Send_Message
    purpose: "Notify the diff author on Slack when talon finds a CRITICAL or HIGH issue."
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
      编排安全 diff review：MCP 取 diff → talon 脚本审计 → MCP 发评论 → 有 CRITICAL/HIGH 就 Slack 通知 author。
      所有 Phabricator I/O 走 MCP server `000000000007`（pod 直连 Conduit 不通）；talon_review.py 不碰 Phabricator（无 Conduit/MCP），但 talon 本身会调 LLM（需 pod 能出网到 LLM）。无 ask_owner。

      1. revision：优先 `{{ inputs.revision_id }}`，否则 event display_id `{{ subj.get('display_id', '') }}`，归一成 `D<n>`。拿不到 → 结束，status=blocked, skipped_reason="no revision id"。

      2. 取 diff：`pha_diff_get(revision_id=D号)` → 从 `revision.all_diffs[]` 取 `phid==revision.fields.diffPHID` 那条的 `id`（找不到取 `all_diffs[0].id`）→ `pha_diff_get_content(diff_id)` 拿 `diff_content`。任一步失败/空 → status=blocked。留着 `revision.fields`（authorPHID/uri）备用。

      3. 跑脚本（命令里一律用**字面绝对路径**，禁用 `$VAR` 展开——静态校验会拦带变量的命令）：
      **确定性落盘**：把 Step 2 拿到的 `diff_content` 用 **quoted heredoc 原样**写入字面文件 `/tmp/talon_diff.diff`：
      ```bash
      cat > /tmp/talon_diff.diff <<'TALON_DIFF_EOF'
      <把 diff_content 逐字粘在这里>
      TALON_DIFF_EOF
      ```
      单引号定界符 `'TALON_DIFF_EOF'` 保证内容不做变量/反引号展开、原样落盘。**不要**把 diff 塞进带变量的命令、不要靠 `echo "$x"`、**不要刮 pane.log**。
      然后跑 `python3 /workspace/workmate/.workmate/playbooks/talon-diff/talon_review.py --revision D号 --diff-file /tmp/talon_diff.diff`，解析 stdout 最后一行 JSON。非零退出/无 JSON → status=blocked。

      4. 发评论：`{{ inputs.post_comment }}` 且 should_post 时 `pha_diff_add_comment(revision_id, comment=comment_markdown, action="comment")`（绝不 accept/reject）。post_comment=false 则不发。blocked 时 comment_markdown 用脚本给的"未能完成"文案，同样按此规则发。

      5. 通知：仅当 `critical_count>0` 或 `severity_counts.high>0`。`pha_user_search(phids=[authorPHID])` 拿 `userName` → `Slack_Bot_Send_Message(server 000000000006, target="<userName>@cobo.com", text=...)`，文案含 D号+URL、critical/high 计数、critical_titles、"请尽快处理"。解析不到 author 或失败 → notified=false 记原因，不影响 posted。

      结构化输出返回。
    output_schema:
      revision_id: string
      status: string
      findings: number
      posted: boolean
      notified: boolean
      notify_reason: string
      skipped_reason: string
      error: string
    output: run
- done:
    message: |
      Talon Diff Review finished for {{ artifacts.run.revision_id }}. status={{ artifacts.run.status }} findings={{ artifacts.run.findings }} posted={{ artifacts.run.posted }} notified={{ artifacts.run.notified }}{% if artifacts.run.error %} error={{ artifacts.run.error }}{% endif %}

---

# Talon Diff Review

Actor fetches the diff via MCP, runs the bundled `talon_review.py` (talon `--diff-file -`), posts the
review via `pha_diff_add_comment`, and Slack-notifies the author on CRITICAL/HIGH.
