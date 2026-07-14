---
id: security-audit-init
uri: builtin://security-audit-init
version: "2026.07.13"
title: Security Audit Init
summary: |
  安全审计初始化：定位 skills → 建 RUN_DIR → 系统理解（analysis/）→ 入口枚举分类。security-audit 第一阶段子 playbook。
attended_mode: unattended
approval_policy: security-owner
approval_policies:
  security-owner:
    normal: approve
    sensitive: approve
limits:
  wall_clock_seconds: 5400
inputs:
  repo_path:
    type: string
    required: true
    description: "被审计目标目录的绝对路径"
  artifacts_root:
    type: string
    required: false
    default: ""
    description: "审计产物根目录。产物落到 <artifacts_root>/<repo_slug>/（与被审计仓库分离，不污染源码库）。留空时默认 ~/workmate/security-audit；**任何情况下都不得写进被审计仓库**——repo_path 是纯只读输入。由主 playbook 透传。"
worktree:
  enabled: false
actors:
  skills_locator:
    provider: codex
    mode: edit
  initializer:
    provider: codex
    mode: edit
    fs_read_paths:
      - "{% if artifacts.skills_probe.bundle_skills %}{{ artifacts.skills_probe.bundle_skills }}{% endif %}"
      - "{% if artifacts.skills_probe.synced_candidate %}{{ artifacts.skills_probe.synced_candidate }}{% endif %}"
  system_analyst:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ artifacts.init.audit_skills_dir }}"]
  entrypoint_finder:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ artifacts.init.audit_skills_dir }}"]
workflow:
  - job:
      actor: skills_locator
      wall_clock_seconds: 300
      prompt: |
        ## 任务：产出审计 skills 的候选路径（纯字符串推导，零文件访问）

        **第一步**：执行

        ```bash
        printenv WORKMATE_FS_READ_ALLOWLIST
        ```

        输出是若干绝对路径，按 `:` 分隔。框架会把本 playbook 源目录（形如
        `<...>/playbooks/builtin/security-audit-init` 或
        `<...>/.workmate/playbooks/security-audit-init`）自动注入其中。

        **推导 `bundle_skills`**（bundle 内置 skills，作 skills 兜底候选；脚本现随 skill 走，见下）：
        1. 存在最后一级目录名为 `security-audit` 的条目 P → `bundle_skills = P/skills/code-security`
        2. 否则取最后一级目录名为 `security-audit-init` 的条目 Q →
           `bundle_skills = <Q 的父目录>/security-audit/skills/code-security`
        3. 两者皆无 → `bundle_skills` 填空串，`resolution` 填 `failed`，
           `note` 附上该环境变量原文（便于人工定位），其余字段照下面规则填。

        **推导 `synced_candidate`**（同步根共享 skills，默认审计 skills 位置——pod 与本地的绝对路径不同、
        相对结构一致，运行时推导天然可移植）：
        若锚点条目路径含 `/.workmate/playbooks/`，截取到 `.workmate` 为止得配置根 W →
        `synced_candidate = W/skills/code-security`；锚点不含 `.workmate`
        （如从仓库 builtin 运行）→ 填空串。`resolution` 填 `derived`，
        `note` 一句话写用了哪个锚点条目。

        **禁止就地验证**：推导出的路径不在只读 allowlist，不要 `ls`/`cat`/`test`。存在性校验由 initializer 完成。

        ## 回传与收尾

        直接用结构化 output（turn_complete）填 `bundle_skills` /
        `synced_candidate` / `resolution` / `note` 四个字段，不要 echo/写脚本拼 JSON。
        **禁止调用 ask_owner 或发起任何需要人工回答的提问**——本 job 在 unattended 模式下运行，
        没有人会应答；遇到不确定的判断，自行按最合理的方案决策并继续，说明写进 `note` 字段即可。
        调用 turn_complete 收到 `{"ok": true}` 后立即结束本轮，不要再调用任何工具、不要继续输出。
      output_schema:
        bundle_skills: string
        synced_candidate: string
        resolution: string
        note: string
      output: skills_probe

  - job:
      actor: initializer
      wall_clock_seconds: 600
      prompt: |
        目标目录：{{ inputs.repo_path }}
        阶段 1.0 skills_locator 产出的候选：
        - 同步根共享 skills 候选（synced_candidate，默认审计 skills 位置）：`{{ artifacts.skills_probe.synced_candidate }}`
        - bundle 内置 skills（bundle_skills，兜底候选）：`{{ artifacts.skills_probe.bundle_skills }}`

        ## 任务：选定 SKILLS → 跑脚手架脚本，建 RUN_DIR 并解析路径

        脚手架脚本 `init_run_dir.py` 随 skill 一起分发，位于 `<SKILLS>/scripts/init_run_dir.py`；
        `generate_worklist.py` / `reconcile_coverage.py` 同在 `<SKILLS>/scripts/`（下游经 scripts_dir 使用）。

        **前置校验**：若 synced_candidate 与 bundle_skills **都为空**（skills_locator 推导失败，无从定位 skill 与脚本）→
        **不要继续**，在 output 把 `run_dir` 留空，原因写明"audit skills 自动定位失败
        （见 skills_probe.note）：请确认 skills 已就位于同步根共享目录
        `<配置根>/.workmate/skills/code-security`（含 rules/ guides/ SCHEMA-issue.md 及 scripts/），或 bundle 内置目录存在后重跑"，然后终止。

        **选定 SKILLS**（skills_probe 已按 synced > bundle 优先级压进字段）：
        1. synced_candidate 非空 → 探测其布局（已在只读白名单内，可直接 test）：
           ```bash
           test -d "<synced_candidate>/rules" && test -d "<synced_candidate>/guides" && test -f "<synced_candidate>/SCHEMA-issue.md" && echo OK
           ```
           输出 OK → `SKILLS = synced_candidate`；否则回退（下游硬依赖 SCHEMA-issue.md）。
        2. `SKILLS = bundle_skills`。

        运行下面这一条命令（脚本随选定的 SKILLS 走——脚本用 `__file__` 自定位出 skill 根与 scripts/，
        **不 import 框架、不依赖 cwd、任何 python3 都能跑**；选定的 SKILLS 作 override 参数传入）：

        ```bash
        python3 "<SKILLS>/scripts/init_run_dir.py" "{{ inputs.repo_path }}" "<SKILLS>" "{{ inputs.artifacts_root }}"
        ```

        它确定性地建 RUN_DIR + 5 子目录（entrypoints/ analysis/ issues/ verify/ work/）+
        audit-log.md / cumulative-issues.md 骨架，解析 audit_skills_dir / scripts_dir（= `<SKILLS>/scripts`），
        校验 skills 布局（rules/ 和 guides/ 都在）。

        脚本向 stdout 打印一行 JSON：`{run_id, run_dir, audit_skills_dir, scripts_dir}`。

        若打印 `{"error": "audit_skills_invalid", ...}` 或命令非零退出 → skills 解析失败：
        记录尝试过的路径 + 解决方案（确保 skills 就位于同步根 `<配置根>/.workmate/skills/code-security`
        或 bundle 内置目录，含 rules/ guides/ SCHEMA-issue.md），run_dir 留空并终止，**不要继续**。

        ## 输出

        把脚本打印的 4 个字段原样填入 output。下游 actor 通过 `artifacts.init.*` 引用这些值。

        **回传方式**：直接用结构化 output（turn_complete）填这些字段，**不要用 shell 命令
        （`echo` / `python3 -c` 等）拼装或打印 JSON 再回传**——`audit_skills_dir` / `scripts_dir`
        是工作区外的 bundle 路径，经 shell 回传时会被工作区文件白名单拦截，触发一次无谓的失败重试。
        结构化 output 走 turn_complete MCP 通道，天然豁免白名单，一次成功。

        **禁止调用 ask_owner 或发起任何需要人工回答的提问**——本 job 在 unattended 模式下运行，
        没有人会应答；遇到不确定的判断（如 skills 路径歧义），按上面规则自行决策或按失败分支终止，
        不要阻塞等待人工。
      output_schema:
        run_id: string
        run_dir: string
        audit_skills_dir: string
        scripts_dir: string
      output: init

  - job:
      actor: system_analyst
      wall_clock_seconds: 5400
      timeout: 5400
      prompt: |
        目标目录：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ artifacts.init.run_dir }}
        审计 skill 目录（AUDIT_SKILLS）：{{ artifacts.init.audit_skills_dir }}

        ## 任务：先理解系统，再扫漏洞（把分析过程沉淀到 RUN_DIR/analysis/）

        以"刚入职工程师第一次读这个系统"的视角自由阅读核心业务实体、关键操作流程、
        服务间调用关系、配置与初始化代码，**不带任何 checklist**。
        （此时入口清单尚未枚举——直接读代码自行识别攻击面，不依赖预生成的入口列表。）
        把分析过程写成以下三份文档（写入 `RUN_DIR/analysis/`，不得只口头总结）：

        1. `analysis/auth-model.md`：权限如何执行（decorator / middleware / guard / permission class）、
           有哪些角色 / 租户 / 服务、trust boundary 在哪。**下游 entrypoint 分类与每个类别分析直接引用，不重新推导。**
        2. `analysis/security-assumptions.md`：四类基础资产——
           - 核心资产（账号 / 租户 / 订单 / 资金 / 密钥 / PII / 权限关系 / 业务状态）
           - 安全假设（如"用户只能操作自己租户数据""订单状态单向流转""提现需双重审批"）
           - 信任边界（公网用户 / 登录用户 / 管理员 / 内部服务 / 异步 worker / 第三方 webhook 之间）
           - 必查高风险路径（资产读取导出 / 状态变更 / 权限变更 / 金额额度变化 / 外部回调 / 文件解析）
        3. `analysis/sensitive-data-map.md`：token / 密钥 / PII / 跨租户数据存在哪、怎么流动；
           额外记录"写入 DB 后被再读出渲染的字段"（stored XSS / second-order 来源）。
           **数据暴露类漏洞没有入口锚点，这张图是 data 类别的主要召回来源。**

        若某核心资产或信任边界无法从代码确认，在文档中标注 `unknown` 作为 TODO，不要臆断为安全。
        所有过程性草稿写入 `RUN_DIR/work/`；三份正式文档写入 `RUN_DIR/analysis/`。

        ## 输出高风险路径（喂给阶段 2 召回）

        把每条"可能有问题或暂时无法证明安全"的观察整理成 `high_risk_paths[]`，每项含：
        - `location`：file:line 或模块路径
        - `category`：8 类之一（authn/replay/concurrency/business_logic/injection/data/crypto/config）
        - `assumption_at_risk`：被打破或待验证的安全假设，一句话

        ## 回传方式

        analysis/ 三份文档写完后，直接用结构化 output（turn_complete）一次性提交下方 5 个字段，
        `high_risk_paths` 作为结构化数组直接提交。**禁止**写脚本拼 JSON、dump 大数组到终端、
        复制产物到 scratch——框架从 VT100 pane 回收巨型输出会超时挂起。

        **禁止调用 ask_owner 或发起任何需要人工回答的提问**——本 job 在 unattended 模式下运行，
        没有人会应答；某项资产/边界无法从代码确认时按上文规则标 `unknown` 继续，不要阻塞等待人工。

        **调用 turn_complete 收到 `{"ok": true}` 后立即结束本轮**——不要再调用任何工具、不要继续输出。
      output_schema:
        analysis_dir: string
        auth_model_summary: string
        sensitive_data_summary: string
        trust_boundaries: string
        high_risk_paths: array
      output: analysis

  - job:
      actor: entrypoint_finder
      wall_clock_seconds: 5400
      timeout: 5400
      prompt: |
        目标目录：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ artifacts.init.run_dir }}
        审计 skill 目录（AUDIT_SKILLS）：{{ artifacts.init.audit_skills_dir }}

        固定类别全集（候选池，不要全跑）：`[authn, replay, concurrency, business_logic, injection, data, crypto, config]`

        ## 0. 先读系统理解（用于 authn_level / 类别判断，不盲判）

        开工前先读 `{{ artifacts.init.run_dir }}/analysis/auth-model.md` 与
        `{{ artifacts.init.run_dir }}/analysis/security-assumptions.md`（system_analyst 已写入；
        路径直取 run_dir/analysis/，不依赖 analysis_dir 字段值），建立权限模型 / 信任边界认知。
        下面 step 3（authn_level）与 step 4（推荐类别）**必须结合 auth-model 判断**，而不是只靠
        route/装饰器 pattern 启发式——例如自定义中间件鉴权、服务级 trust boundary、
        非标准认证装饰器，pattern 看不出来，auth-model 能。
        这两份文档是上一个 system_analyst job 的**强制产出**，是 authn_level / 类别判断的地基。
        若缺失，说明上游已异常、管线已损坏——**立即终止本 job**：在 audit-log 与
        `category_recommendation_reason` 写明"analysis/auth-model.md 或 security-assumptions.md 缺失，
        system_analyst 未正常产出，请重跑 init"，其余字段留空并结束本轮。**严禁**降级到纯 pattern
        启发式继续分类——鉴权分类没有 auth-model 支撑就是不可信的，静默降级会让整份审计失去意义。

        ## 1. 多源入口枚举（按 AUDIT_SKILLS/guides/entrypoints.md 操作）

        三来源取并集，全部写入 `RUN_DIR/entrypoints/index.jsonl`（**唯一 source of truth**，后续阶段不维护任何 Markdown 状态表）：
        - **decorator**：grep route/task/websocket/CLI 注册装饰器
        - **config**：walk urls.py / routes/ / openapi.yaml / swagger.json / Postman collection，跟 include/register_blueprint/include_router
        - **test**：grep tests/ 里 client.get/post 与 handler import；只在 tests 出现的入口加入并标 `sources:["test"]`

        必须覆盖：HTTP / 异步队列（Celery/Kafka/RabbitMQ/SQS）/ 定时任务 / WebSocket / CLI / GraphQL / Webhook / gRPC / 内部 RPC。

        每行 jsonl 字段（**固定 schema**）：
        ```json
        {"entrypoint_id":"http:POST:/api/v2/orders","type":"HTTP","name":"POST /api/v2/orders","handler":"src/api/orders.py:42","authn":"session","required_permission":"org-member","authn_level":"authenticated","sources":["decorator","config"],"single_source":false,"active_status":"active","active_status_reason":""}
        ```
        约束：
        - `entrypoint_id` 形如 `<type>:<method-or-kind>:<route-or-name>`，稳定唯一
        - `handler` = `path:line`（无行号填 path）
        - `sources` ⊆ `{decorator, config, test}`；`single_source = (len(sources) == 1)`
        - `active_status` ∈ `{active, dead, unknown}`
        - `authn_level` ∈ `{public, authenticated, privileged, internal}`（step 3 写入，无法判断时填 `authenticated`）

        ## 2. test-only 入口活跃状态判定（一次性，后续不重做）

        对 `single_source && sources==["test"]` 的入口：
        - 正式代码（不含 tests/ docs/）grep handler 名 / handler 文件是否被路由/装饰器引用
        - 全无引用 → `active_status="dead"` + `reason` 写证据
        - 否则 → `active`/`unknown`

        ## 3. 判定 authn_level（结合 auth-model，与 step 2 同批处理，一次性完成）

        对每个入口按以下优先级打标，**patch** index.jsonl 对应行的 `authn_level` 字段（只追加该字段，不重写整行其他字段）。
        **优先以 auth-model.md 描述的实际鉴权机制为准**，pattern 只作辅助：
        - `internal`：handler 路径含 `internal_rpc/` / `internal/`，或装饰器含 `service_auth` / `internal_only` / mutual TLS 标记，或 auth-model 标明仅内网 service mesh 可达
        - `privileged`：`required_permission` 含 `admin` / `super` / `audit` / `approve` / `withdraw_review`，或装饰器含 `admin_required` / `role_required` / `permission_required`，或 auth-model 标明需特权角色
        - `public`：route 路径含 `/login` / `/register` / `/health` / `/callback` / `/webhook`，或装饰器无任何认证要求，或 handler 明确跳过认证（`@no_auth` / `AllowAny`），且 auth-model 未标额外鉴权
        - `authenticated`：其余所有情况（有认证但非特权，典型的已登录客户接口）

        ## 4. 推荐审计类别（结合 auth-model 与 security-assumptions）

        从全集挑选实际相关的类别（避免空跑），按业务排序输出 `recommended_categories`：
        `authn > replay > concurrency > business_logic > injection > data > crypto > config`

        **`authn` 强制始终包含在 `recommended_categories`（不论信号是否命中）**——逐入口授权检查是账户接管的核心防线，
        必须始终作为审计的关注类别保留；`recommended_categories` 在 coverage 阶段作为 prescan 命中的 category
        归一化兜底与审计关注锚点。（authn 兄弟端点横向对比在 coverage 阶段是无条件执行的固定 job，不受本列表影响。）
        其余类别仍按下方信号矩阵挑选。

        结合 security-assumptions.md 的核心资产/高风险路径调整优先级；判断信号矩阵：

        | 信号 | 关联类别 |
        |---|---|
        | HTTP / WebSocket / GraphQL 入口 | authn, injection, data |
        | Celery / 定时任务 / 队列消费者 | replay, concurrency, business_logic |
        | DB 写入 / 事务（select_for_update / get_or_create / save） | concurrency, business_logic |
        | 签名 / token / HMAC / 加密调用 | crypto, replay |
        | `os.system` / `eval` / 拼接 SQL / SSRF | injection |
        | settings / DEBUG / CORS | config |
        | 日志含 user/PII/token | data |
        | 金额 / quantity / 状态机 | business_logic |
        | 鉴权装饰器 / org_id / tenant 过滤 | authn |

        无法判断时默认取全集 8 类（宁全勿漏）。

        ## 5. 写 audit-log + 输出

        在 audit-log.md 追加：
        - `## 入口枚举` 段：三来源各找到多少、union 总数、单源列表 + active_status 分布、index.jsonl 路径与行数
        - `## 推荐类别` 段：候选全集、本次推荐、跳过列表、一句话推荐理由（说明 auth-model 如何影响判断）

        `single_source_summary` 输出：每行 `<entrypoint_id> (来源: <source>) [active_status]`，便于人工不翻 jsonl 直读。

        **同时产出以下两个字段（供下游消费，不可留空）**：
        - `tech_stack`：一句话概括技术栈（语言 / Web 框架 / 异步框架 / 认证体系），例如
          `Python Django/DRF OAuth service; Celery workers; Auth0/JWT`。coverage 阶段 authn_sibling_analyst 用它校准视角。
        - `api_summary`：一句话概括接口面（入口总数、主要协议类型分布、最值得关注的入口域）。

        ## 6. 回传与收尾（务必遵守）

        直接用结构化 output（turn_complete）一次性填齐下面字段，数组字段作结构化数组直接提交，
        不要写脚本拼 JSON、不要把结果 dump 到终端。**禁止调用 ask_owner 或发起任何需要人工回答的
        提问**——本 job 在 unattended 模式下运行，没有人会应答；类别/authn_level 判断不了时按上文
        回退规则自行决策，不要阻塞等待人工。**调用 turn_complete 后立即结束本轮**：收到
        `{"ok": true}` 即代表回传成功，**不要再调用任何工具、不要继续输出、不要做补充验证**——
        收尾继续动工具会与框架 turn 结束检测抢跑，偶发导致框架识别不到已完成、本 job 无限挂起。
      output_schema:
        api_summary: string
        tech_stack: string
        total_entrypoints: number
        single_source_summary: string
        recommended_categories: array
        skipped_categories: array
        category_recommendation_reason: string
      output: entrypoints

  - done:
      message: |
        初始化完成：{{ artifacts.entrypoints.total_entrypoints }} 个入口 | Run {{ artifacts.init.run_id }}
        推荐类别：{{ artifacts.entrypoints.recommended_categories }}
        高风险路径：{{ artifacts.analysis.high_risk_paths | length }} 条
        RUN_DIR：{{ artifacts.init.run_dir }}

---

安全审计初始化：脚手架（init_run_dir.py 建 RUN_DIR + 解析路径）→ 系统理解（核心地基）→ 入口枚举与分类（带 auth-model 辅助，不盲判）。输出 RUN_DIR、推荐类别和 analysis/ 文档供发现+覆盖阶段使用。
