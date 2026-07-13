---
id: security-audit-coverage
uri: builtin://security-audit-coverage
version: "2.0"
title: Security Audit Coverage
summary: |
  安全审计唯一发现阶段：预扫描（grep 规则引擎）+ authn 兄弟端点横向对比（IDOR 召回）
  两路信号播种，与 system_analyst 的 high_risk_paths 一起喂给全仓文件级穷举审查
  （unit_file_analyst 跑确定性脚本按函数单元数分组）→ 框架 parallel 并行执行 unit-review（每个单元逐一
  穷举 8 类别，三路信号作为强制关注点并入）→ 确定性覆盖核对（AST worklist 对账）→
  框架 parallel 补审缺失单元 → coverage_finalizer 重新对账 + 写文件级覆盖 coverage.json。
  覆盖率 = 全仓函数单元的 per-unit record 覆盖。security-audit 主 playbook 的第二阶段子 playbook。
attended_mode: unattended
approval_policy: security-owner
approval_policies:
  security-owner:
    normal: approve
    sensitive: approve
limits:
  wall_clock_seconds: 10800
inputs:
  repo_path:
    type: string
    required: true
    description: "被审计目标目录绝对路径"
  run_dir:
    type: string
    required: true
    description: "RUN_DIR 绝对路径（由 security-audit-init 产出）"
  audit_skills_dir:
    type: string
    required: true
    description: "AUDIT_SKILLS 目录绝对路径"
  recommended_categories:
    type: array
    required: true
    description: "推荐审计类别列表（供 static_scanner 选取规则集）"
  high_risk_paths:
    type: array
    required: false
    default: []
    description: "高风险路径列表（由 system_analyst 产出），落盘后作为 unit-review 的强制关注信号之一"
  tech_stack:
    type: string
    required: false
    default: ""
    description: "技术栈一句话描述（由 entrypoint_finder 产出），供 authn_sibling_analyst 校准视角"
  scan_depth:
    type: string
    required: false
    default: "balanced"
    description: "扫描深度模式（balanced|deep），由主 playbook 透传，实际由 unit-review 的调用链追踪步骤消费"
  scripts_dir:
    type: string
    required: true
    description: "bundle 内置脚本目录绝对路径（由 security-audit-init 产出），含 generate_worklist.py 和 reconcile_coverage.py"
worktree:
  enabled: false
actors:
  static_scanner:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ inputs.audit_skills_dir }}"]
  authn_sibling_analyst:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ inputs.audit_skills_dir }}"]
  unit_file_analyst:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ inputs.audit_skills_dir }}", "{{ inputs.scripts_dir }}"]
  coverage_reconciler:
    provider: codex
    mode: edit
    reasoning_effort: medium
    fs_read_paths: ["{{ inputs.audit_skills_dir }}", "{{ inputs.scripts_dir }}"]
  coverage_finalizer:
    provider: codex
    mode: edit
    reasoning_effort: medium
    fs_read_paths: ["{{ inputs.audit_skills_dir }}", "{{ inputs.scripts_dir }}"]
workflow:
  - job:
      actor: static_scanner
      prompt: |
        目标目录：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ inputs.run_dir }}
        推荐审计类别：{{ inputs.recommended_categories }}

        ## 任务：运行 grep 规则引擎，产出 prescan-suspects.jsonl

        ### 步骤 1：grep 扫描高危模式

        （命令末尾**不要加 `2>/dev/null` 或任何 stderr 重定向**——重定向会让 Workmate 的写路径
        校验 hook 把 grep 误判成写命令并拦截。grep 的 stderr 很少，直接让它显示即可。）

        ```bash
        cd {{ inputs.repo_path }}
        # SQL 拼接
        grep -rn --include="*.py" -E "(execute|raw|cursor)\s*\(\s*[\"'].*%[s]|f[\"'].*SELECT|f[\"'].*WHERE" .
        # 硬编码 secret
        grep -rn --include="*.py" --include="*.java" --include="*.js" \
          -E "(password|secret|api_key|token)\s*=\s*[\"'][^\"']{8,}[\"']" .
        # shell 注入
        grep -rn --include="*.py" -E "os\.system|subprocess\.(call|run|Popen)\s*\([^,)]*\+" .
        # 反序列化
        grep -rn --include="*.py" -E "pickle\.loads|yaml\.load\s*\([^,)]*\)" .
        # 密码学弱算法
        grep -rn --include="*.py" -E "hashlib\.(md5|sha1)|DES|RC4|ECB" .
        ```

        ### 步骤 2：将结果写入 prescan-suspects.jsonl

        将 grep 输出整理为标准格式，用 apply_patch 一次性落盘到
        `{{ inputs.run_dir }}/prescan-suspects.jsonl`（一行一条 JSON）。
        **禁用 shell 重定向 `>`/`>>`/`tee` 写文件**（会被写路径 hook 拦截）。

        每行格式：
        ```json
        {"file": "src/api/orders.py", "line": 42, "rule_id": "grep.sql-injection", "message": "SQL query built with string concatenation", "category": "injection"}
        ```

        category 字段映射规则（按命中的 grep 模式判断）：
        - SQL 拼接命中 → `injection`
        - shell 注入 / 反序列化命中 → `injection`
        - 硬编码 secret 命中 → `config`
        - 密码学弱算法命中 → `crypto`
        - 其余 → 取 `{{ inputs.recommended_categories }}` 中第一个类别

        若某条 hit 的 category 不在 `{{ inputs.recommended_categories }}` 中，仍写入文件（category 照实填），unit_reviewer 会按自己分配到的文件过滤读取，不按 category 过滤。

        写完后输出统计：
        - `prescan_hits`：写入 prescan-suspects.jsonl 的总条数
        - `scanner_used`：固定填 `grep`

        **禁止调用 ask_owner 或发起任何需要人工回答的提问**——本 job 在 unattended 模式下运行，
        没有人会应答；遇到不确定的判断自行按最合理的方案决策并继续，不要阻塞等待人工。
      output_schema:
        prescan_hits: number
        scanner_used: string
      output: prescan

  - job:
      actor: authn_sibling_analyst
      prompt: |
        目标目录：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ inputs.run_dir }}
        技术栈：{{ inputs.tech_stack }}

        ## 任务：兄弟端点横向对比，召回 IDOR / 越权 suspect

        孤立看单个入口很难判断"该不该有资源归属校验"；把操作同类资源的入口分组后横向对比，
        缺失校验的入口会立刻凸显——这是召回 IDOR 最有效的一步。

        ### 步骤 1：读取入口与权限模型

        - 读取 `{{ inputs.run_dir }}/entrypoints/index.jsonl`，取 `active_status != "dead"` 的全部入口
        - 读取 `{{ inputs.run_dir }}/analysis/auth-model.md`，作为归属校验模式的判断基准（不臆断）

        ### 步骤 2：按资源类型分组

        把入口按"操作的资源类型"分组（wallet / account / order / user / api-key / withdrawal …，
        从路径段和 handler 实际操作的对象判断）。

        ### 步骤 3：组内横向对比归属校验模式

        组内逐入口对比是否校验 `org_id` / `user_id` / `account_id` 等资源归属：
        - 组内多数 scope 到 owner/tenant、个别只验"已登录"或不校验归属 → **那个偏离者是高优先
          IDOR / 越权 suspect**，直接列入（severity 不低于组内同类已确认项，hypothesis 写明
          "兄弟端点 X/Y 均校验 org_id，本入口未校验"）。
        - 组内全都不校验归属 → 可能整组缺失，逐个列为 suspect。

        ### 步骤 4：写出 suspect 列表

        把所有 suspect 汇齐后，用 apply_patch 一次性落盘到
        `{{ inputs.run_dir }}/work/authn-sibling-suspects.jsonl`（一行一个 JSON 对象）。
        **禁用 shell 重定向写文件**（会被写路径 hook 拦截）。每行格式：
        ```json
        {"location": "<file:line>", "hypothesis": "<兄弟端点对比得出的攻击假设>", "domain": "authn", "entrypoint_id": "<id>", "source_pass": "authn_sibling"}
        ```
        若无任何偏离，写一个空文件，直接返回 `authn_sibling_suspects_count=0`。

        **禁止调用 ask_owner 或发起任何需要人工回答的提问**——本 job 在 unattended 模式下运行，
        没有人会应答；分组/归属判断有歧义时自行按最合理的方案决策并继续，不要阻塞等待人工。

        输出 `authn_sibling_suspects_count`：写入了多少个 suspect。
      output_schema:
        authn_sibling_suspects_count: number
      output: authn_sibling

  - job:
      actor: unit_file_analyst
      timeout: 3600
      prompt: |
        目标目录：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ inputs.run_dir }}
        审计 skill 目录：{{ inputs.audit_skills_dir }}

        ## 任务：收集全仓源文件 → 跑确定性脚本（分组 + worklist）→ 输出 unit_groups

        **不要自己创建审查子 run，也不要阻塞等待子 run 完成**——框架会在后续步骤通过 parallel 并行执行 security-audit-unit-review。
        **分组也不由你手工做**——文件收集完交给下面的确定性脚本按函数单元数分组，你只负责收集文件和读结果。

        ### 步骤 1：收集**全仓**源文件，写文件清单

        **目标是全仓覆盖**——不局限于入口可达文件。用 find 枚举目标仓库**所有生产源码文件**
        （命令**不要加 `2>/dev/null`**——stderr 重定向会让 hook 把 find 误判成写命令并拦截）：
        ```bash
        cd {{ inputs.repo_path }}
        find . -type f \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.go" -o -name "*.java" \) \
          -not -path "*/tests/*" -not -path "*/test/*" -not -path "*/migrations/*" \
          -not -path "*/.venv/*" -not -path "*/node_modules/*" -not -path "*/__pycache__/*" \
          -not -path "*/.git/*" -not -path "*/vendor/*" -not -path "*/site-packages/*"
        ```
        排除：测试 / 迁移 / 虚拟环境 / vendored 依赖 / 生成产物。其余生产源码**全部纳入**
        （`settings.py` 等配置代码保留——它们是 config 类漏洞的对象）。这一步决定文件级覆盖的分母 = 全仓生产源码。

        把收集到的**每个文件的绝对路径**用 apply_patch 一次性落盘到
        `{{ inputs.run_dir }}/work/source-files.txt`（一行一个路径）。
        **禁用 shell 重定向写文件**——先用 find 列出、再用 apply_patch 写入。
        **一个文件都不能漏**——这是全仓覆盖。

        ### 步骤 2：跑确定性脚本（AST 展开 worklist + 按函数单元数分组）

        **审查范围与分组都由代码定，不由子 agent 自己挑。** 跑下面这一条命令：

        ```bash
        python3 {{ inputs.scripts_dir }}/generate_worklist.py {{ inputs.run_dir }}
        ```

        脚本读 `work/source-files.txt`，AST 枚举所有函数/方法/模块单元（非 Python 文件以一个文件级
        单元纳入），确定性地产出：
        - `work/worklist.jsonl`：全仓函数级单元 = 覆盖分母（钉死，防 agent 偷懒）
        - `work/unit-review-groups.jsonl`：**按函数单元数均衡分好的最终分组**（贪心装箱 ~20 单元/组 +
          目录内聚 + 入口可达文件优先；单个大文件单独成组；总单元 ≤ 目标则 1 组）——按单元数而非文件数
          分组，消除"文件大小差异导致各组负担差一个量级、大组单 turn 跑不完"的问题
        - `work/unit-review-plan.json`：分组自检摘要（source_file_count / group_count / total_units）
        - `work/worklist-scope.json`：文件数 / 单元数统计

        ### 步骤 3：读取脚本分好的组，构造 unit_groups 输出

        读取 `{{ inputs.run_dir }}/work/unit-review-groups.jsonl`（脚本已分好，**不要自己重分组**），
        转为 array 作为 `unit_groups` 输出。每组结构：
        `{"unit_id": "unit-001", "files": ["/abs/path/handler.py", ...], "unit_count": 21}`

        输出 `total_units` = `unit-review-plan.json` 的 `group_count`（分组数）；
        `worklist_units` = `worklist-scope.json` 的 `worklist_units`（全仓总函数单元数）。

        ### 步骤 4：落盘 high_risk_paths（供 unit-review 按文件过滤读取）

        把下面这个数组用 apply_patch 原样落盘到
        `{{ inputs.run_dir }}/work/high-risk-paths.jsonl`（一行一个 JSON 对象，字段与输入一致：
        `location` / `category` / `assumption_at_risk`）；数组为空则写空文件。
        **禁用 shell 重定向写文件**（会被写路径 hook 拦截）：

        high_risk_paths：{{ inputs.high_risk_paths }}

        **不要自己创建审查子 run，也不要阻塞等待子 run 完成。**
        框架将在下一步通过 `parallel` 调度 `security-audit-unit-review`。

        ## 回传与收尾（务必遵守）

        直接用结构化 output（turn_complete）一次性填齐下面字段，`unit_groups` **作为结构化数组
        直接提交**——不要写脚本拼 JSON、不要把大数组 dump 到终端（框架会退化成从超大 pane 屏幕
        日志里 parse，极慢甚至卡死不 finalize）。**禁止调用 ask_owner 或发起任何需要人工回答的
        提问**——本 job 在 unattended 模式下运行，没有人会应答，遇到不确定的判断自行决策并继续。
        **调用 turn_complete 后立即结束本轮**：收到
        `{"ok": true}` 即代表回传成功，不要再调用任何工具、不要继续输出。

      output_schema:
        total_units: number
        worklist_units: number
        unit_groups: array
      output: unit_file_results

  - parallel:
      concurrent: true
      for_each: "{{ artifacts.unit_file_results.unit_groups }}"
      as: unit_group
      body:
        - call:
            playbook: security-audit-unit-review
            inputs:
              repo_path: "{{ inputs.repo_path }}"
              run_dir: "{{ inputs.run_dir }}"
              audit_skills: "{{ inputs.audit_skills_dir }}"
              unit_files: "{{ unit_group.files }}"
              worklist_path: "{{ inputs.run_dir }}/work/worklist.jsonl"
              prescan_path: "{{ inputs.run_dir }}/prescan-suspects.jsonl"
              high_risk_paths_path: "{{ inputs.run_dir }}/work/high-risk-paths.jsonl"
              authn_suspects_path: "{{ inputs.run_dir }}/work/authn-sibling-suspects.jsonl"
              scan_depth: "{{ inputs.scan_depth }}"
      merge:
        on_error: collect

  - job:
      actor: coverage_reconciler
      timeout: 3600
      prompt: |
        工作目录（RUN_DIR）：{{ inputs.run_dir }}
        审计 skill 目录：{{ inputs.audit_skills_dir }}

        ## 任务：把"AI 有没有审完"从信任问题改造成对账问题

        上一步框架 parallel 内联执行的 unit-review 已对各自分配文件的每个单元写
        `work/unit-records/<safe_unit_id>.json`。
        跑下面这段确定性 python，对照 `work/worklist.jsonl`（AST 钉死的分母）核对：

        ```bash
        python3 {{ inputs.scripts_dir }}/reconcile_coverage.py {{ inputs.run_dir }}
        ```

        ## 构造补审分组

        若 `missing_units` 非空：把缺失单元按文件聚合，对涉及文件按 3-5 个一组重新分组，
        生成 `missing_groups`（格式与 unit_groups 相同）：
        ```json
        [{"unit_id": "补审-001", "files": ["/abs/path/missing_file.py"]}, ...]
        ```
        若无缺失单元，`missing_groups` 输出为空数组 `[]`。

        **不要自己创建补审子 run，也不要阻塞等待子 run 完成**——框架将在下一步通过 parallel 调度补审。

        ## 写 audit-log

        在 `audit-log.md` 追加 `## 文件级覆盖核对` 段：总单元 / 已审 / 缺失 / 各类 integrity
        违规计数，并列出造假信号清单（hash_mismatch / lines_out_of_range / empty_evidence / weak_evidence / blocked_empty_evidence 的 unit_id）。

        ## 输出
        - `coverage_audit_path`：`{{ inputs.run_dir }}/coverage-audit.json`
        - 其余统计字段以 `coverage-audit.json` 内容为准读取，不要解析脚本 stdout
        - `missing_groups`：待补审的分组列表（供框架 parallel 调度；无缺失则为空数组）

        直接用结构化 output（turn_complete）填齐字段，`missing_groups` 作为结构化数组直接提交，
        不要写脚本拼 JSON、不要把大数组 dump 到终端。**禁止调用 ask_owner 或发起任何需要人工回答
        的提问**——本 job 在 unattended 模式下运行，没有人会应答，遇到不确定的判断自行决策并继续。
        **调用 turn_complete 后立即结束本轮**，不要再调用任何工具、不要继续输出。
      output_schema:
        total_units: number
        units_with_record: number
        missing_count: number
        hard_invalid_count: number
        integrity_violation_count: number
        coverage_audit_path: string
        missing_groups: array
      output: coverage_audit

  - parallel:
      concurrent: true
      for_each: "{{ artifacts.coverage_audit.missing_groups }}"
      as: unit_group
      body:
        - call:
            playbook: security-audit-unit-review
            inputs:
              repo_path: "{{ inputs.repo_path }}"
              run_dir: "{{ inputs.run_dir }}"
              audit_skills: "{{ inputs.audit_skills_dir }}"
              unit_files: "{{ unit_group.files }}"
              worklist_path: "{{ inputs.run_dir }}/work/worklist.jsonl"
              prescan_path: "{{ inputs.run_dir }}/prescan-suspects.jsonl"
              high_risk_paths_path: "{{ inputs.run_dir }}/work/high-risk-paths.jsonl"
              authn_suspects_path: "{{ inputs.run_dir }}/work/authn-sibling-suspects.jsonl"
              scan_depth: "{{ inputs.scan_depth }}"
      merge:
        on_error: collect

  - job:
      actor: coverage_finalizer
      timeout: 3600
      prompt: |
        目标目录：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ inputs.run_dir }}
        审计 skill 目录：{{ inputs.audit_skills_dir }}

        ## 任务：补审后重新对账 + 更新 cumulative-issues.md + 写 coverage.json

        文件级补审已由上一步框架 parallel 内联并行完成，unit-records/ 目录已更新。

        ### 步骤 1：重新运行 reconcile 刷新 coverage-audit.json（补审后必做）

        补审让 unit-records/ 新增了记录，必须重新对账才能反映补审结果：
        ```bash
        python3 {{ inputs.scripts_dir }}/reconcile_coverage.py {{ inputs.run_dir }}
        ```
        这会刷新 `{{ inputs.run_dir }}/coverage-audit.json`（文件单元覆盖的权威对账结果）。
        **目录约定**：中间草稿一律写 `RUN_DIR/work/`，RUN_DIR 根目录只允许写 `coverage.json`。

        ### 步骤 2：更新 cumulative-issues.md

        扫描 `{{ inputs.run_dir }}/issues/` 下本阶段新产出的 issue 文件（`source_pass=unit_review`），
        追加到 `cumulative-issues.md`（段标题 `## 文件级穷举审查（unit_review，含 prescan/high-risk/authn-sibling 三路信号）`）。

        ### 步骤 3：写 coverage.json（覆盖率 = 文件单元覆盖，不再用入口×类别矩阵）

        读 `{{ inputs.run_dir }}/coverage-audit.json` 的对账结果，按下面格式写 `coverage.json`：

        ```json
        {"total_units":248,"units_with_record":248,"missing_count":0,"hard_invalid_count":0,"integrity_violation_count":0,"coverage_percent":100.0,"coverage_passed":true}
        ```

        约束（覆盖率基于 worklist 全仓函数单元的 per-unit record 对账）：
        - `coverage_percent = units_with_record / total_units * 100`（total_units==0 时为 0）
        - `coverage_passed` 只有在 `missing_count == 0 且 hard_invalid_count == 0` 时才能为 `true`
        - `uncovered_after` = 补审后仍缺记录的单元数（= 刷新后的 `missing_count`）
        - 所有数值以刷新后的 `coverage-audit.json` 为准，不要臆造

        **禁止调用 ask_owner 或发起任何需要人工回答的提问**——本 job 在 unattended 模式下运行，
        没有人会应答；遇到不确定的判断自行按最合理的方案决策并继续，不要阻塞等待人工。

      output_schema:
        uncovered_after: number
        coverage_percent: number
      output: coverage_metrics

  - done:
      message: |
        发现+覆盖阶段完成：
        预扫描（{{ artifacts.prescan.scanner_used }}）命中 {{ artifacts.prescan.prescan_hits }} 条规则引擎 suspect
        authn 兄弟端点横向对比：{{ artifacts.authn_sibling.authn_sibling_suspects_count }} 个 suspect
        文件穷举：{{ artifacts.unit_file_results.total_units }} 组 / worklist {{ artifacts.unit_file_results.worklist_units }} 单元
        覆盖核对：{{ artifacts.coverage_audit.total_units }} 单元 / 缺失 {{ artifacts.coverage_audit.missing_count }}
        覆盖率：{{ artifacts.coverage_metrics.coverage_percent }}% (未覆盖 {{ artifacts.coverage_metrics.uncovered_after }})

---

安全审计唯一发现阶段：预扫描 + authn 兄弟端点横向对比两路信号播种 → 全仓文件级穷举审查（三路信号作为强制关注点并入）→ AST worklist 对账 → 缺失单元补审 → 文件级覆盖率汇总。原 suspect-driven 的 security-audit-scan 已并入本阶段，避免与 unit-review 重复深挖同一段代码。security-audit 主 playbook 的第二阶段子 playbook。
