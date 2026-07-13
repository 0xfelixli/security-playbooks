---
id: security-audit-challenger
uri: builtin://security-audit-challenger
version: "2.0"
title: Security Audit Challenger
summary: |
  对已写入的 issue 做对抗复核（独立怀疑者视角）：基于代码证据给出 adversarial_verdict，回写 issue 文件。security-audit 的 sub-playbook；也可独立调用重审单条 issue。
attended_mode: unattended
approval_policy: security-owner
approval_policies:
  security-owner:
    normal: approve
    sensitive: approve
limits:
  wall_clock_seconds: 3600
inputs:
  repo_path:
    type: string
    required: true
    description: "被审计目标目录绝对路径"
  run_dir:
    type: string
    required: true
    description: "本次审计的 RUN_DIR 绝对路径"
  issue_paths:
    type: array
    required: true
    description: "批量待复核 issue 文件绝对路径列表，例如 [<RUN_DIR>/issues/idor-wallet.md, ...]"
  audit_skills:
    type: string
    required: false
    default: ""
    description: "审计 skill 目录绝对路径（含 rules/、guides/）。由上游 playbook 调用时传入；留空时 actor 自行解析。"
actors:
  challenger:
    provider: claude
    model: claude-opus-4-8
    # opus 单价高，给单 actor 成本兜底防止取证读代码时失控；正常单批复核远低于此，超限视为异常。
    max_cost_usd: 30.0
    mode: edit
    profile: security-audit-reviewer
    fs_read_paths: ["{{ inputs.audit_skills }}"]
worktree:
  enabled: false
workflow:
  - job:
      actor: challenger
      wall_clock_seconds: 3600
      timeout: 3600
      prompt: |
        目标目录：{{ inputs.repo_path }}
        批量待复核 issue 文件：{{ inputs.issue_paths }}
        RUN_DIR：{{ inputs.run_dir }}

        ## 前置：解析 AUDIT_SKILLS 目录

        {% if inputs.audit_skills %}
        AUDIT_SKILLS = {{ inputs.audit_skills }}
        {% else %}
        AUDIT_SKILLS 未传入，自行解析 playbook bundle 内置路径。校验 `rules/` 和 `guides/` 都存在。
        {% endif %}


        ## 你的角色：独立复核者

        你是一名独立的防御侧安全工程师，任务是**逐个复核** discovery 阶段写出的 issue，
        独立判断每个 issue 是否成立。每个 issue 必须独立阅读、独立记录证据、独立写回；
        不要把一个 issue 的结论套用到另一个 issue。

        ## 证据规则

        只有满足以下至少一项，你才能改变 discovery 的 verdict：

        - 你引用了 discovery 报告未提到的新代码行号，并显示存在保护性控制措施
          （中间件鉴权、签名校验、租户过滤、参数白名单等）。
        - 你证明攻击路径在实际代码中**不可达**
          （入口受 IP 白名单/内网限制、参数被上游强制覆盖、handler 实际未被注册到 router 等）。
        - 你识别出 discovery 遗漏的已存在认证检查、签名验证、CSRF 防护。

        以下内容不能作为改变 verdict 的依据：
        - discovery 措辞自信
        - 未定位到具体代码的上游防护假设
        - 主观可能性判断
        - "影响小"——影响 ≠ verdict（影响调整 severity，verdict 看是否成立）

        ## 召回偏置原则（优先于精准）

        **有疑问时，选 `NEEDS_POC`，不选 `REFUTED`。**

        使用 `REFUTED` 的门槛非常高——必须同时满足：
        - 读文件逐层上溯追踪了**所有**调用路径，无一例外都有完整防护
        - 防护在危险操作执行**之前**生效
        - 防护检查的是正确的资源归属（org_id / user_id / account_id），不只是"已登录"
        - 你引用了具体的代码行号作为证据

        以下情形必须选 `NEEDS_POC`，不得选 `REFUTED`：
        - 防护在中间件 / 基类 / 其他文件中，但你未完整追踪其覆盖范围
        - 攻击路径有多条，你只排除了其中一条
        - 认证存在但未确认有 nonce 消费防重放（认证 ≠ 防重放）
        - 鉴权只检查"已登录"但未检查资源归属（authn ≠ authz）

        ## 工作步骤

        对每个 issue path 依次执行：

        1. 读 issue 文件全文。

        2. **独立验证调用链**（不要只信 issue 文件里引用的位置；读文件独立核实）：
           - 读 `primary_location` 的精确源码 + 调用者，独立确认 discovery 引用的代码行是否属实
           - 向上追至入口（grep 符号名找调用点逐层上溯），独立验证 handler 是否真的被注册到 router（dead code 里的 location 在调用链上会断掉）
           - 读相关文件独立寻找 discovery 可能遗漏的中间件鉴权、签名校验、租户过滤
           - 第三方依赖（`.venv/lib/python3.*/site-packages/cobo_libs/` 等）直接读包内源码定位 symbol，不假设库内有防护

        3. 给出 adversarial_verdict（5 选 1）：
           - **CONFIRMED**：discovery 判断正确，漏洞成立
           - **REFUTED**：discovery 判断错误，引用具体行号证明（见证据规则 + 召回偏置原则）。
             **注意：你的 REFUTED 只是"删除提案"、不直接生效**——杀掉一个 finding 需要 report 阶段
             独立上下文会签。按下方写回规则，你判 REFUTED 时先写
             `final_verdict: blocked` + `final_verdict_reason: refute_proposed`，等会签通过才变 `refuted`。
           - **DOWNGRADED**：漏洞成立但严重性应降低（如 HIGH → MEDIUM），说明理由
           - **UPGRADED**：漏洞成立且严重性被低估、应上调（如 MEDIUM → HIGH），填 `severity_upgraded_to`
           - **NEEDS_POC**：静态读代码无法定论，需要动态 PoC 验证

           **`UPGRADED` 门槛与 REFUTED 对称**：必须引用 discovery 未提到的新代码行证据；纯主观"更严重"一律保持 CONFIRMED（详见 SCHEMA UPGRADED 条目）。

        4. **反驳自检**（仅当 verdict 为 REFUTED 时执行）：
           在最终写入 REFUTED 之前，做一次反向假设检验：
           - 假设这个 finding **是真实的**
           - 问自己："我的否决理由在哪条代码路径上可能不成立？"
             - 是否有其他调用路径绕过了我找到的防护？
             - 防护措施是否可能只在特定条件下生效？
             - 参考 `AUDIT_SKILLS/guides/false-positive-traps.md` 的每个陷阱
           - 如果**能想到任何**让否决不成立的场景，将 verdict 改为 `NEEDS_POC`
           - 只有在反向假设检验后仍找不到任何漏洞的才最终保留 `REFUTED`

        ## 写回 issue 文件（delta-only）

        **完整 frontmatter 字段、对抗验证 section 模板、final_verdict 计算表**：全部按
        `AUDIT_SKILLS/SCHEMA-issue.md` 的"对抗复核字段"和"Issue 文件正文模板"小节执行。
        执行前先 Read 一次 SCHEMA-issue.md。

        本 actor 只做 **2 件事**（其余字段一律保持原值，不重写、不删除）：

        1. **append** 文件末尾的 "## 对抗验证（Challenger）" section（按 SCHEMA 模板填）
        2. **补/改** frontmatter 4 个字段（DOWNGRADED / UPGRADED 时 5 个）：
           - `adversarial_verdict`
           - `adversarial_at`
           - `final_verdict`（按 SCHEMA "final_verdict 计算" 表）
           - `final_verdict_reason`
           - `severity_downgraded_to`（仅 DOWNGRADED 时）/ `severity_upgraded_to`（仅 UPGRADED 时；两者互斥）

        **严禁**：覆盖 `severity` / 修改 `discovery_*` 字段 / 删除原内容 / 重写整份 frontmatter。

        ## 主动补漏扫描（复核完所有 issue 后执行）

        独立对抗复核结束后，还要做一轮**主动补漏扫描**——检查 discovery 阶段可能遗漏的问题。

        步骤：
        1. 统计本批次 issue 涉及的所有文件路径（从 `primary_location` 提取），
           对每个路径，先读该位置（`file:line`）确定对应的 symbol 名，
           再 grep 该 symbol 名取第一层 caller 文件
           （通常是 handler 层）——handler 层的权限检查缺失往往不在 primary_location
           所在的 service 文件里，必须把 caller 文件也纳入扫描范围。
           若一行落在多个 symbol 内，取行号范围最小包含该行的那个；
           若 grep 不到调用者，跳过 caller 扩展并在 work/ 记录。
           扫描范围 = primary_location 文件 ∪ 其直接 caller 文件（去重）。
        2. 对扫描范围内每个文件，通读后自问：
           - "这个文件中有哪些入口点未出现在本批 issue 的 `affected_entrypoints` 里？"
           - 重点关注：authn / IDOR / business_logic / replay（这几类最容易被反向扫描遗漏）
        3. 对发现的可疑遗漏，写新的 issue 文件到 `{{ inputs.run_dir }}/issues/`
           - `discovery_verdict: confirmed`（challenger 直接判断成立）或 `blocked`（需要 PoC）
           - `source_pass: challenger_supplement`（标记来源区别于 discovery 阶段）
           - **必须同步写齐对抗复核字段**（你本身就是对抗复核者，补漏 issue 不会再经第二次 challenger，
             因此 discovery 与 adversarial 字段都由你一次写全，否则 final_reporter 按 `final_verdict`
             分桶时该 issue 的 status 为空、被统计漏掉）：
             - `adversarial_verdict`：`CONFIRMED`（你已完整追踪攻击路径、确认成立）或 `NEEDS_POC`（需动态验证）
             - `adversarial_at`：ISO8601
             - `final_verdict`：按 SCHEMA "final_verdict 计算" 表——本补漏 issue 的 `CONFIRMED → confirmed`；
               `NEEDS_POC → blocked`
             - `final_verdict_reason`：一句话
           - 其余 frontmatter 必填字段（含 `severity`/`authn_level`/`vuln_type` 等）按
             `AUDIT_SKILLS/SCHEMA-issue.md` 完整填写

        约束：
        - 只报高置信度（自己能完整追踪到攻击路径）的遗漏，不要因为这一步降低精准度
        - 若文件无遗漏，跳过，不写任何文件
        - 新增 issue 数量写入 output 的 `supplemented_count`

        ## 输出

        `issue_paths` 用换行列出本次复核的所有 issue 文件路径。
        `verdict_summary` 汇总 CONFIRMED / REFUTED / DOWNGRADED / UPGRADED / NEEDS_POC 数量。
        `supplemented_count` 主动补漏扫描新增的 issue 数量（0 表示无遗漏）。

        直接用结构化 output（turn_complete）回传上述字段，不要把结果 dump 到终端。
        **禁止调用 ask_owner 或发起任何需要人工回答的提问**——本 job 在 unattended 模式下运行，
        没有人会应答；判不清的 verdict 按上文 `NEEDS_POC` 处理并继续，不要阻塞等待人工。
        **调用 turn_complete 后立即结束本轮**，不要再调用任何工具、不要继续输出。
      output_schema:
        processed_count: number
        issue_paths: string
        verdict_summary: string
        changed_from_discovery: string
        supplemented_count: number
      output: result

  - done:
      message: |
        对抗复核完成：{{ artifacts.result.processed_count }} 个 issue
        Verdict：{{ artifacts.result.verdict_summary }}
        分歧：{{ artifacts.result.changed_from_discovery }}
        补漏新增：{{ artifacts.result.supplemented_count }} 个 issue
        Issues：
        {{ artifacts.result.issue_paths }}

---

对已写入的 issue 做对抗复核（独立怀疑者视角）：基于代码证据给出 adversarial_verdict 并回写。security-audit 子 playbook，也支持独立调用重审单条 issue。
