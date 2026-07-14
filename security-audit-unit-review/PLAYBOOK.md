---
id: security-audit-unit-review
uri: builtin://security-audit-unit-review
version: "2026.07.14"
title: Security Audit Unit Review
summary: |
  文件级穷举安全审查：对一组文件逐函数穷举 8 类漏洞，并入三路信号作为强制关注点。security-audit 的 sub-playbook。
attended_mode: unattended
approval_policy: security-owner
approval_policies:
  security-owner:
    normal: approve
    sensitive: approve
limits:
  wall_clock_seconds: 1800
inputs:
  repo_path:
    type: string
    required: true
    description: "被审计目标目录绝对路径"
  run_dir:
    type: string
    required: true
    description: "本次审计的 RUN_DIR 绝对路径"
  unit_files:
    type: array
    required: true
    description: |
      待穷举审查的文件绝对路径列表。主流程由 generate_worklist.py 按函数单元数
      确定性装箱分组（目录内聚，约 12 单元/组）；补审时由 coverage_reconciler
      按缺失文件 3-5 个一组重组。均经框架 parallel 内联 call 传入。
  audit_skills:
    type: string
    required: false
    default: ""
    description: "审计 skill 目录绝对路径（含 rules/、guides/）。由上游 playbook 调用时传入；留空时 actor 自行解析。"
  worklist_path:
    type: string
    required: false
    default: ""
    description: |
      确定性 AST worklist 文件绝对路径（由覆盖阶段生成）。
      列出本组文件应被审查的全部函数/方法/模块单元，作为 per-unit record 的分母。
      留空时回退到 <run_dir>/work/worklist.jsonl。
  prescan_path:
    type: string
    required: false
    default: ""
    description: "prescan-suspects.jsonl 绝对路径（grep 规则引擎命中）。留空时跳过该信号源。"
  high_risk_paths_path:
    type: string
    required: false
    default: ""
    description: "work/high-risk-paths.jsonl 绝对路径（system_analyst 产出的高风险路径落盘版）。留空时跳过该信号源。"
  authn_suspects_path:
    type: string
    required: false
    default: ""
    description: "work/authn-sibling-suspects.jsonl 绝对路径（authn 兄弟端点横向对比结果）。留空时跳过该信号源。"
  scan_depth:
    type: string
    required: false
    default: "balanced"
    description: "扫描深度模式（balanced|deep）。deep 时调用链追踪强制至少 3 层上溯、suspect 候选不设上限。"
actors:
  unit_reviewer:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ inputs.audit_skills }}"]
worktree:
  enabled: false
workflow:
  - job:
      actor: unit_reviewer
      wall_clock_seconds: 1800
      timeout: 1800
      prompt: |
        目标目录：{{ inputs.repo_path }}
        本次审计 RUN_DIR：{{ inputs.run_dir }}
        待审查文件：{{ inputs.unit_files }}

        ## 前置：解析 AUDIT_SKILLS 目录

        {% if inputs.audit_skills %}
        AUDIT_SKILLS = {{ inputs.audit_skills }}
        {% else %}
        AUDIT_SKILLS 未传入，自行解析 playbook bundle 内置路径。校验 `rules/` 和 `guides/` 都存在。
        {% endif %}

        ## 开工前必读：审查标准纪律（强制）

        Read `AUDIT_SKILLS/guides/reviewer-discipline.md`，严格执行其中全部纪律（含 false-positive-traps /
        baseline-calibration 两个必读 guide、refuted 的 recall-safe 门槛、任何 verdict 都必须写盘）。
        这是 unit-review 审查基准，不因具体任务改变。

        ## 你的角色

        你是独立安全研究员，不知道其他信号源已经标记过什么，从零视角穷举审查这批文件。
        **目标**：找出没有匹配 grep 模式、没有信号命中的漏洞——IDOR、业务逻辑绕过、
        隐式重放、并发缺陷等往往没有"危险函数"信号，只有通过完整阅读才能发现。

        **召回优先于精准**：有疑问时选 `blocked`，不选 `refuted`。漏掉一个真实高危漏洞，
        比多留一个待人工复查的 issue 代价高得多。

        ## 步骤 0：读取三路外部信号，过滤出本组文件相关的条目（强制关注点）

        以下三个信号文件若存在，各自读取后按 `file ∈ {{ inputs.unit_files }}`（或 `location` 前缀匹配）过滤：

        1. **prescan（{% if inputs.prescan_path %}{{ inputs.prescan_path }}{% else %}留空，跳过{% endif %}）**：
           grep 规则引擎命中，字段 `{file, line, rule_id, message, category}`。
        2. **high_risk_paths（{% if inputs.high_risk_paths_path %}{{ inputs.high_risk_paths_path }}{% else %}留空，跳过{% endif %}）**：
           system_analyst 产出的高风险路径，字段 `{location, category, assumption_at_risk}`。
        3. **authn 兄弟端点横向对比（{% if inputs.authn_suspects_path %}{{ inputs.authn_suspects_path }}{% else %}留空，跳过{% endif %}）**：
           跨入口对比得出的 IDOR/越权 suspect，字段 `{location, hypothesis, domain, entrypoint_id, source_pass}`。

        过滤出的条目都是**必须处理的强制关注点**——不允许因为"感觉不像漏洞"而跳过，与下面步骤 3
        穷举审查发现的可疑点合并处理，作为同一批 issue 的输入来源（issue 里不需要单独标出信号来源，
        `source_pass` 统一按本 playbook 约定填 `unit_review`）。
        若三个信号文件都留空或都无匹配条目，正常进入步骤 1，不受影响。

        ## 步骤 1：读取所有文件

        对 `{{ inputs.unit_files }}` 中的每个文件路径：
        - Read 文件全文，列出文件内所有 symbol 及源码

        如果 unit_files 为空，立即输出：
        `processed_count=0, issue_files="", verdict_summary="no files", summary="no files to review"` 并结束。

        ## 步骤 2：枚举所有可审查单元

        列出这批文件里所有可审查单元（handler 函数、service 方法、class method、模块级逻辑）。
        忽略：纯数据类（只有字段定义）、测试辅助函数、日志/工具函数。

        **非 Python 文件**（JS/Go/Java 等）：worklist 里以单个文件级单元 `<file>::<file>`（kind=`file`）出现，
        没有 AST 函数拆分——把整个文件作为一个单元通读审查，并对该 `<file>` 单元回交一条 record。

        ## 步骤 3：跨类别穷举安全审查

        对每个可审查单元，**不绑定单一类别**，依次检查 8 个安全维度：

        | 类别 | 核心问题 |
        |------|---------|
        | authn | 操作的资源归属是否校验（org_id / user_id / account_id）？是否信任调用方传的 ID？有 authz 还是只有 authn？ |
        | injection | 用户可控输入是否流入 SQL / shell / file path / URL / template？中间有无参数化 / 白名单？ |
        | business_logic | 状态机迁移条件是否完整？金额/数量是否校验范围和符号？审批步骤能否跳过？idempotency 是否缺失？ |
        | replay | 签名/token 消费后是否标记已用？同一 nonce/challenge 能否被多次消费？认证 ≠ 防重放 |
        | concurrency | critical section 是否在事务/锁内？并发能否导致双扣、状态跳跃？select_for_update 是否正确使用？ |
        | data | 返回值/日志是否含 token/密钥/PII/内部错误栈？serializer 是否过滤敏感字段？ |
        | crypto | 随机数来源是否安全（secrets/os.urandom，非 random）？加密是否有认证（GCM）？密钥硬编码？ |
        | config | 硬编码密钥？DEBUG 行为？CORS `*`？不应暴露的管理接口？ |
        > 框架隐含契约问题（DRF `permission_classes` 默认、FastAPI `response_model` 过滤、Celery 无 request context、ORM lazy eval）按安全后果归入上述 8 类（如 permission_classes→authn、response_model→data），不另立类别。

        对每个**有疑问**的单元，读文件追踪：
        - 向上追所有调用入口：grep 符号名找调用点，逐层上溯，确认攻击路径可达
        - 向下追数据流到 sink

        {% if inputs.scan_depth == 'deep' %}
        ### deep 模式追加要求

        scan_depth=deep，执行以下额外步骤（不可跳过）：

        1. **调用链穷举**：对每个可疑函数/方法，grep 其名字找调用者、逐层向上追溯调用链，
           至少追 3 层（caller → caller's caller → caller's caller's caller）。
           不允许因为"直接调用点没问题"就停止——防护可能只覆盖了部分调用路径。
        2. **suspect 候选上限放宽**：不要因为候选数量多而主动裁剪。
           将所有满足「攻击者可控输入可能到达危险位置」的点都列为 suspect（写入 issue），
           哪怕置信度较低。
        3. **跨模块调用链追踪**：对每个可疑点的 location，读源码顺调用关系检查
           是否存在从不同模块（service / util / middleware）到达此点的间接路径，
           防止遗漏间接注入链路。
        {% endif %}

        读取对应入口在 `{{ inputs.run_dir }}/entrypoints/index.jsonl` 里的 `authn_level`（按 entrypoint_id 匹配），
        写入 issue frontmatter，并在 severity 评估时参考：`internal` 入口优先级低于 `public`/`authenticated`。

        ## 步骤 4：给出 discovery_verdict（4 选 1）

        - **confirmed**：攻击路径完整，可利用
        - **escalate**：发现比预期更严重（升级 severity 或换 vuln_type）
        - **refuted**：有明确防护且已追踪所有调用路径——门槛极高（三条件见 reviewer-discipline.md，须全满足、引用具体行号，否则一律 blocked）
        - **blocked**：需要运行时信息，或静态无法定论；有疑问时选此，不选 refuted


        ## 步骤 5：写入 issue 文件（任何 verdict 都写）

        路径：`{{ inputs.run_dir }}/issues/<issue_id>.md`

        **字段、frontmatter 结构、issue_id 构造规则、正文模板、cwe 取值与"同位置多漏洞"拆分规则**：完全按 `AUDIT_SKILLS/SCHEMA-issue.md` 执行——**执行前先 Read 一次**确认字段名和约束（尤其 cwe 的取值来源，以及"同一 symbol/endpoint/file:line 上存在多个独立 CWE 时必须拆成多条独立 issue、不得合成一条"的强制拆分规则——它直接决定下游 merge_dedup 去重是否正确）。

        discovery 阶段写齐所有必填字段（`canonical` 固定 `true`、`source_pass` 填 `unit_review`）；**不要预填**合并阶段字段（`duplicate_files`/`superseded_by`/`final_verdict` 等，由 merge_dedup.py 写）。

        **同时写机读旁路 issue-meta**（供 report 阶段确定性去重脚本 merge_dedup.py 读取，避免下游解析 LLM 手写 YAML）：每写一条 issue `.md`，就按 SCHEMA-issue.md「机读旁路」小节的格式，用 apply_patch 在 `{{ inputs.run_dir }}/work/issue-meta/<issue_id>.json` 写一份同字段值的纯 JSON 副本（值与刚写的 `.md` frontmatter 完全一致；数组字段缺失填 `[]`、`primary_symbol` 不定填 `""`）。**这是 merge_dedup 去重的唯一数据源，必须每条 issue 都写、`issue_file` 用绝对路径。**

        ## 步骤 6：为每个单元回交 proof-of-work record（强制，防偷懒）

        **不是只对有问题的单元写。** 对你分配文件里每一个函数/方法/模块单元，
        都要写一条 record 到 `{{ inputs.run_dir }}/work/unit-records/<safe_unit_id>.json`
        （`safe_unit_id` = unit_id 里非字母数字字符替换为 `-`）。
        单元清单以 worklist 为准（{% if inputs.worklist_path %}{{ inputs.worklist_path }}{% else %}{{ inputs.run_dir }}/work/worklist.jsonl{% endif %}）：
        读该文件，筛出 `file` ∈ 你的 `unit_files` 的行，逐个单元回交。

        record 字段（只有真读了代码才填得出，coverage 阶段的确定性对账会拿 AST 反向验真）：
        ```json
        {"unit_id":"<file>::<qualname>","file_hash":"<worklist 里同单元的 file_hash>","symbols_reviewed":["<qualname>"],"lines_inspected":[42,43,50],"categories_checked":["authn","injection"],"verdict":"clean","evidence":"必须含至少一处反引号代码引用，例如：`filter(org_id=request.user.org_id)` — 已有 org 过滤；纯描述性句子视为无效证据","issue_ids":[]}
        ```
        约束：
        - `verdict` ∈ `{clean, issue, blocked}`；`issue` 时 `issue_ids` 填对应 issue 文件 stem
        - `file_hash` 必须照抄 worklist 同单元的值（不要自己算，对账靠它）
        - `lines_inspected` 必须落在该单元 `[lineno, end_lineno]` 内（越界会被判造假）
        - `clean` 的 `evidence` 必须含至少一处反引号包裹的代码片段（例如 `` `foo(bar)` ``）；纯描述性语句视为无效（coverage_reconciler 会标记 weak_evidence）
        - `blocked` 的 `evidence` 必须说明缺少什么运行时信息才能判断，不能为空字符串
        - 缺单元 = coverage 阶段对账时判定被跳过并触发补审

        ## 输出

        `processed_count`：审查的函数/方法总数。
        `issue_files`：写入的 issue 文件路径列表（换行分隔）。
        `verdict_summary`：confirmed/escalate/refuted/blocked 各数量。
        `summary`：一句话说明审查范围，例如"穷举审查 4 个文件，23 个函数，发现 3 个 issue"。

        用结构化 output（turn_complete）回传上述字段，不要把结果 dump 到终端。禁止 ask_owner 或任何需人工应答的提问（unattended，无人应答；判不清的单元按步骤 4 的 `blocked` verdict 处理并继续）。收到 `{"ok": true}` 后立即结束本轮，不再调用任何工具或继续输出。
      output_schema:
        processed_count: number
        issue_files: string
        verdict_summary: string
        summary: string
      output: result

  - done:
      message: |
        文件级穷举审查完成：{{ artifacts.result.summary }}
        Verdict：{{ artifacts.result.verdict_summary }}
        Issues：
        {{ artifacts.result.issue_files }}

---

文件级穷举安全审查：穷举读取文件内所有函数/方法，跨全部 8 个安全类别寻找漏洞，融合 prescan/high-risk-paths/authn-sibling 三路外部信号作为强制关注点。
