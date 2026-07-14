---
id: security-audit-report
uri: builtin://security-audit-report
version: "2026.07.14"
title: Security Audit Report
summary: |
  安全审计报告阶段：去重 → 完整性批评 → 生成 findings.json。security-audit 第三阶段子 playbook。
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
    description: "RUN_DIR 绝对路径"
  audit_skills_dir:
    type: string
    required: true
    description: "AUDIT_SKILLS 目录绝对路径"
  analysis_dir:
    type: string
    required: true
    description: "analysis/ 目录绝对路径（由 security-audit-init 产出）"
  scan_depth:
    type: string
    required: false
    default: "balanced"
    description: "扫描深度模式（balanced|deep），透传自主 playbook；仅用于 run.json 元数据。"
worktree:
  enabled: false
actors:
  coverage_critic:
    provider: claude
    mode: edit
    fs_read_paths: ["{{ inputs.audit_skills_dir }}", "{{ inputs.analysis_dir }}"]
  final_reporter:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ inputs.audit_skills_dir }}"]
workflow:
  - job:
      actor: coverage_critic
      timeout: 1800
      prompt: |
        目标目录：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ inputs.run_dir }}
        审计 skill 目录：{{ inputs.audit_skills_dir }}
        analysis 目录：{{ inputs.analysis_dir }}

        **字段、frontmatter、index.jsonl schema**：按 `{{ inputs.audit_skills_dir }}/SCHEMA-issue.md` 执行。执行前 Read 一次。

        ## 步骤 0：跑脚本做确定性去重 + 写 index.jsonl（本阶段唯一的 index 生成点，禁止手工去重）

        后续所有盲区盘点都以 `issues/index.jsonl` 为基准盘，而它由确定性脚本生成——去重 key、canonical
        选择、severity 收敛在 SCHEMA 里是**完全确定性**的。**不要手工比对去重、不要手算 index.jsonl**，
        先跑这一条命令（读 unit_reviewer 写的机读旁路 `work/issue-meta/*.json`，纯 JSON）：

        ```bash
        python3 "{{ inputs.audit_skills_dir }}/scripts/merge_dedup.py" "{{ inputs.run_dir }}"
        ```

        脚本（确定性，无 LLM 判断）：
        - 读所有 `work/issue-meta/*.json`，按 SCHEMA "去重 key 规范"（`primary_symbol` 锚 + `cwe`，回退 endpoint / 文件+行号；`CWE-UNKNOWN` 永不折叠）分组
        - 每组选 canonical（primary_symbol 非空 → 信息最完整 → issue_id 稳定序），severity 取组内最高
        - 给 canonical `.md` 标 `canonical:true`/`duplicate_files`/`severity`，并写 `final_verdict`（本阶段无对抗复核，`final_verdict = discovery_verdict` 原样透传）；非 canonical `.md` 标 `canonical:false`/`superseded_by`/`duplicate_reason`（只改这几个标量，其余原值不动，不删不移任何文件）
        - 写 `RUN_DIR/issues/index.jsonl`（每行一个 canonical，`final_verdict = discovery_verdict`）
        - stdout 打印一行 JSON：`{total_issues, total_canonical, discovery_confirmed, discovery_escalate, discovery_refuted, discovery_blocked}`

        **不要删除任何 refuted / blocked issue 文件**。脚本非零退出或 JSON 缺字段 → 记录 stderr 并终止，run 不继续。

        ## 任务

        index 建好后，从三个维度盘点已产出 issue 未覆盖的盲区（category × authn_level / 孤儿入口 / 未命中的高风险路径），
        产出 gap 清单供 final_reporter 计入"未完成项"。**只批评不重跑**——不派发补审、不改 issue 文件。

        ## 步骤 1：读四份 evidence

        1. `{{ inputs.run_dir }}/issues/index.jsonl` —— 步骤 0 刚生成的最终 index，`canonical == true` 行即所有主 issue，
           带 `discovery_category`、`vuln_type`、`cwe`、`severity`、`authn_level`、`affected_entrypoints`、
           `final_verdict`、`primary_location`。**基准盘**——统计"哪些格子有 issue"。
        2. `{{ inputs.run_dir }}/coverage.json` —— 文件级覆盖率（`total_units` / `missing_count` /
           `coverage_passed`）。**先决条件**——如果 `coverage_passed == false`，coverage 阶段自己就漏审了，
           你的盲区判断必须叠加这一层。
        3. `{{ inputs.run_dir }}/entrypoints/index.jsonl` —— 全部入口，字段
           `{entrypoint_id, type, handler, authn_level, active_status, active_status_reason, ...}`。
           **对照盘**——哪些 active 入口一条 issue 都没引用。
        4. `{{ inputs.run_dir }}/work/high-risk-paths.jsonl`（若存在）—— system_analyst 产出的高风险路径，
           字段 `{location, category, assumption_at_risk}`。**热点盘**——每条高风险路径是否被某条 issue 命中。
        5. `{{ inputs.analysis_dir }}/auth-model.md` / `sensitive-data-map.md` / `security-assumptions.md`
           （若存在）—— 用于判断某个类别的"零覆盖"是否合理（例如没有 crypto 操作的仓库，`crypto` 类别为 0 是正常的）。

        ## 步骤 2：三个维度盘点盲区

        对每个维度分别产出 gap 清单：

        **维度 A：类别 × authn_level 矩阵**

        8 个类别：`authn / injection / business_logic / replay / concurrency / data / crypto / config`
        4 个 authn_level：`public / authenticated / privileged / internal`

        对每个 (category, authn_level) 组合，若同时满足：
        - 存在至少 1 个 `active_status == "active"` 且该 `authn_level` 的入口（有代码可审）
        - 该 (category, authn_level) 下 `final_verdict ∈ {confirmed, escalate, blocked}` 的 issue 数 = 0

        判为一个**候选 gap**。然后依据 `auth-model` / `sensitive-data-map` 二分：
        - `plausible_gap`：代码里明显存在此类风险面但零 issue——需要人工/下次 run 补审。
          必须给出**至少一处佐证**：具体 file:line 或 entrypoint_id，说明"这里理应有此类别的攻击面"
        - `explained_gap`：能明确解释为什么 0 是合理的（如：仓库无加密操作、无异步任务、
          此 authn_level 下所有入口都是纯读且不涉及资源归属）——必须给出 rationale 一句话

        **维度 B：孤儿高风险入口**

        对 `entrypoints/index.jsonl` 里 `active_status == "active"` 且 `authn_level ∈ {public, authenticated, privileged}`
        的每个 entrypoint_id，检查 issues 里的 `affected_entrypoints` 是否引用过它。
        零引用的入口列为候选 gap，同样二分 `plausible_gap` / `explained_gap`：
        - plausible：入口非平凡（有资源操作 / 有用户输入），却零 issue → 疑似漏审
        - explained：例如纯健康检查 / 静态资源 / 已确认无副作用的只读端点 → 给 rationale

        **维度 C：未命中的高风险路径**

        对 `work/high-risk-paths.jsonl` 每条记录，检查是否有 issue 的 `primary_location` 命中该 `location`
        （文件路径匹配，行号 ±20 视为命中）。未命中的列为候选 gap：
        - plausible：system_analyst 已标为高风险但 issue 未落地 → 疑似漏审
        - explained：unit_reviewer 已在 unit-record 里以 `clean` verdict 显式覆盖此位置（读
          `{{ inputs.run_dir }}/work/unit-records/` 相应 record 确认）→ 给 rationale

        区分两种情况：文件**存在但为空** → system_analyst 合法地未识别出高风险路径，本维度跳过、gap 计 0，正常；
        文件**不存在** → 上游 system_analyst 未落盘该产出（管线异常），不得静默当 0，须在 audit-log 显式告警
        `high-risk-paths.jsonl 缺失，维度 C 未执行`并把它列入本 run 的未完成项。

        ## 步骤 3：产出两份交付（务必都写）

        **3a. `RUN_DIR/coverage-critic.json`（机读）**

        ```json
        {
          "generated_at": "<ISO8601>",
          "coverage_passed_upstream": <boolean, 来自 coverage.json>,
          "total_gaps": <plausible + explained 总数>,
          "plausible_gaps_count": <N>,
          "explained_gaps_count": <N>,
          "plausible_gaps": [
            {
              "dimension": "category_x_authn" | "orphan_entrypoint" | "unhit_high_risk_path",
              "key": "<维度 A: '<category>|<authn_level>'; 维度 B: entrypoint_id; 维度 C: file:line>",
              "evidence": "<至少一处 file:line 或 entrypoint_id，证明此处应有 issue 而未见>",
              "suggested_action": "<一句话建议：审哪个文件/入口/子系统，聚焦哪类漏洞>"
            }
          ],
          "explained_gaps": [
            {
              "dimension": "...",
              "key": "...",
              "rationale": "<一句话说明为何 0 是合理的，引用 auth-model / sensitive-data-map 或 unit-record 佐证>"
            }
          ]
        }
        ```

        **3b. audit-log.md 追加一段**

        在 `RUN_DIR/audit-log.md` 末尾追加：

        ```
        ## Coverage Critic（完整性批评）

        Upstream coverage_passed: <true/false>
        总 gap 数：<N>（plausible=<X>，explained=<Y>）

        ### Plausible gaps（疑似漏审，需人工/下次 run 补审）
        - [<dimension>] <key> — <evidence>；建议：<suggested_action>
        - ...（每个 plausible gap 一行）

        ### Explained gaps（0 issue 合理，附证据）
        - [<dimension>] <key> — <rationale>
        - ...
        ```

        ## 纪律

        - **recall-safe**：拿不准归 plausible，不归 explained
        - **不改任何 issue 文件**、不重生成 index.jsonl、不派发补审、不引入 loop（只批评这一版 index.jsonl）
        - 不猜——plausible_gap 必须给具体 file:line / entrypoint_id evidence；explained_gap 必须给 rationale
        - `total_gaps == 0` 时仍写全部字段（`plausible_gaps: []` / `explained_gaps: []`）

        ## 输出

        用结构化 output（turn_complete）回传字段。**禁止调用 ask_owner 或发起任何需要人工回答的
        提问**——本 job 在 unattended 模式下运行，没有人会应答，拿不准时按上文 recall-safe 归入
        `plausible_gap` 并继续。**调用 turn_complete 后立即结束本轮**，不要再调用任何工具。
      output_schema:
        total_gaps: number
        plausible_gaps_count: number
        explained_gaps_count: number
        coverage_passed_upstream: boolean
      output: critic

  - job:
      actor: final_reporter
      wall_clock_seconds: 1800
      prompt: |
        工作目录：{{ inputs.run_dir }}
        Coverage Critic 统计（宏观完整性批评）：
        - total_gaps: {{ artifacts.critic.total_gaps }}
        - plausible_gaps_count: {{ artifacts.critic.plausible_gaps_count }}
        - explained_gaps_count: {{ artifacts.critic.explained_gaps_count }}
        - coverage_passed_upstream: {{ artifacts.critic.coverage_passed_upstream }}

        本 run **无对抗复核阶段**：`issues/index.jsonl` 已由上一步（coverage_critic 的步骤 0）经 merge_dedup.py
        生成，每个 canonical issue 的 `final_verdict` 按 `discovery_verdict` 原样落定。你以 index.jsonl 为
        source of truth 做统计与交付物生成，不改判任何 issue。discovery 四桶统计 == final 四桶统计（同一 verdict）。

        ## 任务

        1. 优先读取 `RUN_DIR/issues/index.jsonl`，按主 issue 的 `final_verdict` 字段分桶统计：
           - confirmed
           - escalate
           - refuted
           - blocked（需人工复核项）
           `issues/index.jsonl` 是 issue 的唯一 source of truth。若它缺失或字段不完整，**不得**用可能不全的
           frontmatter 扫描直接顶替统计（会漏统计 confirmed 漏洞而报告照常"完成"）——必须先遍历
           `RUN_DIR/issues/*.md` 逐条抽取 frontmatter **重建完整的 index.jsonl**（`final_verdict = discovery_verdict`），
           并在 audit-log 记录"索引已重建、覆盖 N 条 issue"，再基于重建后的索引统计。
        2. 给出最终风险评分（1-10，仅基于 final_verdict 为 confirmed/escalate 的 issue）
        3. 列出所有 `final_verdict == blocked` 的 issue（需人工复核/验证项）
        4. 读取 `RUN_DIR/coverage.json`，确认 `coverage_passed`。如果为 false，最终汇总仍写入，并在未完成项里列出未审文件单元数（`uncovered_after` / `missing_count`）。
        4b. 读取 `RUN_DIR/coverage-critic.json`（Coverage Critic 产出）。若缺失，说明 critic 未执行、宏观盲区未覆盖——
            **在未完成项里显式列 `coverage_critic_missing`**（不只在 audit-log 记一笔），提醒人工/下次 run 补跑。
            把 `plausible_gaps` 逐条列入"未完成项"——它们是 unit-review 过完之后仍被判"疑似漏审"的宏观盲区，
            人工/下次 run 需要吸收。`explained_gaps` 不进未完成项，仅在 audit-log 参考段引述数量
            （`Critic gaps: plausible=X / explained=Y`）。
            plausible gap 不影响风险评分；但 `plausible_gaps_count > 0` 时最终评分 ≥ 3。
        5. 在 RUN_DIR/audit-log.md 末尾追加：
           ```
           ## 综合汇总

           ### Discovery 阶段
           - 类别实际执行：<M> 个（按 entrypoint_finder 推荐的 recommended_categories 顺序）
           - 发现方法：全仓文件级穷举审查（unit_review），融合 prescan（grep）+ high_risk_paths + authn 兄弟端点横向对比三路信号作为强制关注点
           - 文件级覆盖率：<coverage_percent>%（未覆盖单元 <N>）
           - discovery_verdict 统计：confirmed=X / escalate=Y / refuted=Z / blocked=W

           ### Final
           - final_verdict 统计：confirmed=A / escalate=B / refuted=C / blocked=D（= discovery_verdict，无对抗复核）
           - 风险评分：<1-10>

           ### 人工复核项
           - 需人工验证/复核（blocked）：[...]

           ### Coverage Critic（宏观完整性）
           - 总 gap 数：<N>（plausible=<X>，explained=<Y>）
           - Plausible gaps（疑似漏审）：逐条列 [<dimension>] <key> — <evidence>；建议 <suggested_action>
           - 详见 `coverage-critic.json`

           ### 未完成项
           - 未覆盖文件单元：<N>（应为 0）
           - Critic plausible gaps：<X>（每条含 evidence + suggested_action，见 coverage-critic.json）
           ```
        6. 生成机读交付文件（**唯一来源**：`issues/index.jsonl` 中 `canonical == true` 的主 issue；
           **字段映射 + 排序**：按 `{{ inputs.audit_skills_dir }}/SCHEMA-issue.md` 的 "findings.json 字段映射" 小节执行）：

           **6a. `RUN_DIR/findings.json`（主交付物，供 CI / dashboard / 告警消费）**——`findings[]` **只收**
          `final_verdict ∈ {confirmed, escalate, blocked}` 的主 issue（要修的 + 要人工看的；**refuted 不进此数组**）。
          每条 finding 必须按 SCHEMA 带上 `final_verdict` 与 `final_verdict_reason`，让下游能区分要修与待人工复核：
           ```json
           {
             "run_id": "<RUN_ID>", "repo_path": "<绝对路径>", "generated_at": "<ISO8601>",
             "summary": {
               "total": <全部四桶主 issue 总数（含 refuted，全量计数，不受 findings[] 分流影响）>,
               "confirmed": <N>, "escalate": <N>, "blocked": <N>, "refuted": <N>,
               "by_severity": {"CRITICAL": <N>, "HIGH": <N>, "MEDIUM": <N>, "LOW": <N>, "INFO": <N>},
               "coverage_passed": <boolean>
             },
             "findings": [ /* 只含 confirmed/escalate/blocked，按 SCHEMA 字段映射 + 排序 */ ]
           }
           ```
           `summary` 仍给**全部四桶**完整计数（让消费方一眼知道否决/待人工各多少），仅 `findings[]` 不含 refuted。

           **6b. `RUN_DIR/refuted.json`（审计留痕）**——`findings[]` **只收** `final_verdict == refuted` 的主 issue，
           字段映射同上，额外带 `final_verdict_reason`。顶层结构同 6a，`summary.refuted` = 条数、其余桶填 0。
           refuted 的完整正文仍在 `issues/*.md`，此文件只是机读汇总。

           **6c. `RUN_DIR/run.json`（元数据，跟 talon `writer.py:write_run_record` 对齐）**——一次 run 的机读身份证：
           ```json
           {
             "run_id": "<RUN_ID>",
             "repo_path": "<绝对路径>",
             "started_at": "<从 RUN_ID 前缀 YYYYMMDD-HHMMSS 解析成 ISO8601>",
             "finished_at": "<当前 ISO8601>",
             "scan_depth": "<balanced | deep>",
             "coverage_passed": <boolean>,
             "final": {"confirmed": <N>, "escalate": <N>, "refuted": <N>, "blocked": <N>, "risk_score": <1-10>}
           }
           ```
           `scan_depth` 从主 playbook 注入的对应字段直接透传；`started_at` 从 RUN_ID 时间戳前缀
           反向解析（`20260709-145823` → `2026-07-09T14:58:23`）。**不含 LLM usage**（Workmate 侧另有记账，不重复）。

           **6d. `RUN_DIR/vulnerabilities.csv`（平铺索引，跟 talon `writer.py` 的 5 列 CSV 对齐）**——从 `findings.json`
           的 `findings[]` 派生（不含 refuted），5 列表头：`id,title,severity,discovered_at,location`：
           - `id` = `issue_id`；`title` 中的逗号/引号按 RFC 4180 转义（含逗号则用 `"..."` 包裹、内部 `"` 加倍）
           - `severity` 为 issue 生效 severity
           - `discovered_at` 取 issue frontmatter 的 `discovery_at`
           - `location` = `file:line`（file 用相对 repo 的相对路径，去除 `repo_path` 前缀）
           按 severity DESC 排序（同 findings.json）。0 条时也写文件（只有表头）。

           约束：4 个文件都必须生成；0 条也写空 findings 数组 + summary 零值 / CSV 只有表头；仅由本步骤生成。
        7. 为 `final_verdict ∈ {confirmed, escalate, blocked}` 的 issue，在
           `RUN_DIR/verify/` 下补充一个 PoC 脚本骨架（**只补充脚本，绝不执行验证**）：
           - 文件名：`verify/<issue_id>.poc.<ext>`（按目标技术栈选 `.py` / `.sh` / `.http` 等）
           - 内容：复现该 issue 的最小步骤骨架——目标接口、构造的恶意输入、预期 vs 实际、
             前置条件（账号 / token / 环境），以及"需人工在受控环境执行"的醒目注释
           - 脚本顶部注释引用对应 `issues/<issue_id>.md` 与其 `primary_location`
           - **不要运行脚本、不要发起任何真实请求**；本 playbook 不自动执行 PoC，只补充骨架供人工接手
        8. **目录清扫（最后一步，保持交付目录整洁）**：把 `RUN_DIR` 根目录下不在交付白名单内的
           所有文件移动到 `RUN_DIR/work/`。
           - 白名单文件：`findings.json`、`refuted.json`、`run.json`、`vulnerabilities.csv`、`coverage.json`、`coverage-audit.json`、`coverage-critic.json`、`audit-log.md`、`cumulative-issues.md`
           - 白名单目录：`entrypoints/`、`analysis/`、`issues/`、`verify/`、`work/`
           - 其余（如 `prescan-suspects.jsonl`、`*-suspects-*.jsonl` 等中间草稿）一律 `mv` 进 `work/`，不删除

        **禁止调用 ask_owner 或发起任何需要人工回答的提问**——本 job 在 unattended 模式下运行，
        没有人会应答；汇总/评分拿不准时按上文规则自行决策并继续，不要阻塞等待人工。
      output_schema:
        final_confirmed: number
        final_escalate: number
        final_refuted: number
        final_blocked: number
        risk_score_final: number
        coverage_passed: boolean
      output: final

  - done:
      message: |
        报告阶段完成：
        Critic：plausible={{ artifacts.critic.plausible_gaps_count }} / explained={{ artifacts.critic.explained_gaps_count }}
        Final：confirmed {{ artifacts.final.final_confirmed }} / escalate {{ artifacts.final.final_escalate }} / refuted {{ artifacts.final.final_refuted }} / blocked {{ artifacts.final.final_blocked }} (评分 {{ artifacts.final.risk_score_final }}/10)
        产物：{{ inputs.run_dir }}/findings.json（有效漏洞）+ refuted.json（否决留痕）+ coverage-critic.json（宏观盲区）

---

安全审计报告阶段：跨类别去重（final_verdict = discovery_verdict，无对抗复核）→ 完整性批评 → 生成 findings.json 和 PoC 骨架。security-audit 主 playbook 的第三阶段子 playbook。
