---
id: security-audit-diff
uri: builtin://security-audit-diff
version: "2026.07.14"
title: Security Audit Diff
summary: |
  增量（diff）代码安全审计：解析 PR/commit 变更范围 → 抓 diff → 跨 8 类安全审查 → 生成 findings.json。
  独立 playbook，面向 CI/PR gate，与全仓 security-audit orchestrator 并列。
attended_mode: unattended
approval_policy: security-owner
approval_policies:
  security-owner:
    normal: approve
    sensitive: approve
limits:
  wall_clock_seconds: 7200
inputs:
  repo_path:
    type: string
    required: false
    default: ""
    description: "被审计目标 git 仓库的绝对路径（**纯只读输入**，审计不往里写任何产物）。与 diff_file **二选一，至少提供其一**：默认（不给 diff_file）走 git range 模式，此时 repo_path 必填、且需要完整 git 历史（shallow clone 会让 merge-base 失败——CI 里设 fetch-depth: 0）；只给 diff_file 时可省略 repo_path（纯 diff-only 快审）。scan_depth=deep 需要源码追调用链，故 deep 必须提供 repo_path，否则自动降级为 fast。"
  artifacts_root:
    type: string
    required: false
    default: "~/workmate/security-audit"
    description: "审计产物根目录，与被审计仓库分离。产物落到 <artifacts_root>/<repo_slug>/<run_id>/。默认 ~/workmate/security-audit（Workmate 同步根内，agent 有写权限）。**任何情况下都不写进被审计仓库**——repo_path 是纯只读输入。"
  diff_base:
    type: string
    required: false
    default: ""
    description: "diff 的对比基线（如 origin/main、某个 tag 或 commit SHA）。留空时按优先级自动推导：GITHUB_BASE_REF → origin HEAD → origin/main → origin/master。审计范围恒为 merge-base 三点语法 `<merge_base>...HEAD`，只审本分支独有的变更。"
  diff_file:
    type: string
    required: false
    default: ""
    description: "直接提供 unified diff 文件的绝对路径（如已用 `git diff`/`gh pr diff` 导出）。给定时跳过 git range 解析，直接以该文件为审计输入，**此时 repo_path 可省略**；与 diff_base 互斥（diff_base 被忽略）。与 repo_path 二选一至少其一。"
  scan_depth:
    type: string
    required: false
    default: "fast"
    description: "审计深度。fast（默认）：diff-only 快审，只看 diff 文本，看不到下游 blast radius 时只降 severity、不丢 finding，速度优先，适合 CI gate。deep：在 fast 基础上给源码访问，对变更文件 + 一跳调用方追调用链穷举，召回更全但更慢，适合高价值 PR 彻查。"
  min_confidence:
    type: number
    required: false
    default: 0.7
    description: "finding 成条的置信度下限（0.0–1.0）。confidence 指『diff 文本本身是否显示真实违规』的确信度，不是下游影响范围的确信度（后者归入 severity）。低于此值太投机，不写成 issue。默认 0.7（对齐 talon diff_review）。"
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
  diff_scoper:
    provider: codex
    mode: edit
  diff_reviewer:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ artifacts.init.audit_skills_dir }}"]
  diff_reporter:
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
        `<...>/playbooks/builtin/security-audit-diff` 或
        `<...>/.workmate/playbooks/security-audit-diff`）自动注入其中。

        **推导 `bundle_skills`**（bundle 内置 skills，作 skills 兜底候选；脚本随 skill 走）：
        1. 存在最后一级目录名为 `security-audit` 的条目 P → `bundle_skills = P/skills/code-security`
        2. 否则取最后一级目录名为 `security-audit-diff` 的条目 Q →
           `bundle_skills = <Q 的父目录>/security-audit/skills/code-security`
        3. 两者皆无 → `bundle_skills` 填空串，`resolution` 填 `failed`，
           `note` 附上该环境变量原文（便于人工定位），其余字段照下面规则填。

        **推导 `synced_candidate`**（同步根共享 skills，默认审计 skills 位置——pod 与本地绝对路径不同、
        相对结构一致，运行时推导天然可移植）：
        若锚点条目路径含 `/.workmate/playbooks/`，截取到 `.workmate` 为止得配置根 W →
        `synced_candidate = W/skills/code-security`；锚点不含 `.workmate`
        （如从仓库 builtin 运行）→ 填空串。`resolution` 填 `derived`，
        `note` 一句话写用了哪个锚点条目。

        **禁止就地验证**：推导出的路径不在只读 allowlist，不要 `ls`/`cat`/`test`。存在性校验由 initializer 完成。

        ## 回传与收尾

        用结构化 output（turn_complete）填 `bundle_skills` / `synced_candidate` / `resolution` / `note` 四个字段，不要 echo/写脚本拼 JSON。禁止 ask_owner 或任何需人工应答的提问（unattended，无人应答；不确定时自行按最合理方案决策并继续，说明写进 `note`）。收到 `{"ok": true}` 后立即结束本轮，不再调用任何工具或继续输出。
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
        阶段 skills_locator 产出的候选：
        - 同步根共享 skills 候选（synced_candidate，默认审计 skills 位置）：`{{ artifacts.skills_probe.synced_candidate }}`
        - bundle 内置 skills（bundle_skills，兜底候选）：`{{ artifacts.skills_probe.bundle_skills }}`

        ## 任务：选定 SKILLS → 跑脚手架脚本，建 RUN_DIR 并解析路径

        脚手架脚本 `init_run_dir.py` 随 skill 一起分发，位于 `<SKILLS>/scripts/init_run_dir.py`；
        `merge_dedup.py` 同在 `<SKILLS>/scripts/`（下游报告阶段用）。

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

        运行下面这一条命令（脚本随选定的 SKILLS 走——用 `__file__` 自定位 skill 根与 scripts/，
        **不 import 框架、不依赖 cwd、任何 python3 都能跑**；选定的 SKILLS 作 override 参数传入）：

        ```bash
        python3 "<SKILLS>/scripts/init_run_dir.py" "{% if inputs.repo_path %}{{ inputs.repo_path }}{% else %}diff-review{% endif %}" "<SKILLS>" "{{ inputs.artifacts_root }}"
        ```

        （repo_path 为空即纯 diff_file 模式：上面第一个参数已用字面 `diff-review` 代替，仅用于生成 RUN_DIR 的 slug，不代表真实仓库路径。）

        它确定性地建 RUN_DIR + 5 子目录（entrypoints/ analysis/ issues/ verify/ work/）+
        audit-log.md / cumulative-issues.md 骨架，解析 audit_skills_dir / scripts_dir（= `<SKILLS>/scripts`），
        校验 skills 布局（rules/ 和 guides/ 都在）。diff 审计不产 entrypoints/ analysis/，那两个子目录留空即可。

        脚本向 stdout 打印一行 JSON：`{run_id, run_dir, audit_skills_dir, scripts_dir}`。

        若打印 `{"error": "audit_skills_invalid", ...}` 或命令非零退出 → skills 解析失败：
        记录尝试过的路径 + 解决方案（确保 skills 就位于同步根 `<配置根>/.workmate/skills/code-security`
        或 bundle 内置目录，含 rules/ guides/ SCHEMA-issue.md），run_dir 留空并终止，**不要继续**。

        ## 输出

        把脚本打印的 4 个字段原样填入 output。下游 actor 通过 `artifacts.init.*` 引用这些值。

        **回传方式**：用结构化 output（turn_complete）填这些字段，不要用 shell（`echo`/`python3 -c` 等）拼装或打印 JSON 再回传——`audit_skills_dir`/`scripts_dir` 是工作区外的 bundle 路径，经 shell 回传会被工作区文件白名单拦截、触发无谓重试；turn_complete 通道天然豁免白名单。禁止 ask_owner 或任何需人工应答的提问（unattended，无人应答；skills 路径歧义等按上面规则自行决策或按失败分支终止）。
      output_schema:
        run_id: string
        run_dir: string
        audit_skills_dir: string
        scripts_dir: string
      output: init

  - job:
      actor: diff_scoper
      wall_clock_seconds: 600
      timeout: 600
      prompt: |
        目标目录（git 仓库）：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ artifacts.init.run_dir }}
        显式基线 diff_base：`{{ inputs.diff_base }}`（留空则自动推导）
        显式 diff 文件 diff_file：`{{ inputs.diff_file }}`（非空则直接用它，跳过 git range）

        ## 任务：确定审计范围，抓取 diff 文本并分类变更文件

        所有 git 命令都在 `{{ inputs.repo_path }}` 内**只读**执行（`git -C "{{ inputs.repo_path }}" ...`），不改工作树、不 checkout、不 fetch。产物只写进 RUN_DIR。

        ## 步骤 0：输入校验（repo_path 与 diff_file 二选一至少其一）

        - repo_path（`{% if inputs.repo_path %}已提供{% else %}空{% endif %}`）与 diff_file（`{% if inputs.diff_file %}已提供{% else %}空{% endif %}`）**都为空** → 无审计输入，**立即终止**：`analyzable_count` 填 0、`stop_reason` 写"未提供 repo_path 也未提供 diff_file，无审计输入"。
        - diff_file 非空 → 走下面分支 A（不依赖 repo_path，repo_path 为空也可）。
        - diff_file 空、repo_path 非空 → 走分支 B（git range，需在 repo 内跑 git）。

        {% if inputs.diff_file %}
        ### 分支 A：diff_file 已提供

        直接把 `{{ inputs.diff_file }}` 拷贝到 `{{ artifacts.init.run_dir }}/work/changed.diff`（`cp`，不改内容）。
        `base_ref` 与 `merge_base` 记为 `"(diff_file)"`。从 diff 头部的 `diff --git a/... b/...` /
        `+++ b/...` 行解析出变更文件清单，跳到下面「## 分类变更文件」。
        {% else %}
        ### 分支 B：从 git range 解析（默认）

        **步骤 1：拒绝 shallow 仓库**
        ```bash
        git -C "{{ inputs.repo_path }}" rev-parse --is-shallow-repository
        ```
        输出 `true` → **立即终止**：output 里 `changed_diff_path` 留空、`stop_reason` 写
        "仓库是 shallow clone，无法计算 merge-base；CI 里请对 checkout 设 `fetch-depth: 0` 后重跑"。不要试图 fetch 补全。

        **步骤 2：解析 base_ref（按优先级取第一个能解析成功的）**
        1. `diff_base` 非空 → `base_ref = {{ inputs.diff_base }}`
        2. 环境变量 `GITHUB_BASE_REF` 非空 → `base_ref = refs/remotes/origin/$GITHUB_BASE_REF`
        3. `git -C <repo> symbolic-ref refs/remotes/origin/HEAD` 能解析 → 用它
        4. `refs/remotes/origin/main` 存在 → 用它
        5. `refs/remotes/origin/master` 存在 → 用它
        6. 都失败 → **终止**：`stop_reason` 写"无法自动确定 diff 基线，请显式传 diff_base（如 origin/main）"。

        对候选用 `git -C <repo> rev-parse --verify "<ref>^{commit}"` 校验可解析，第一个通过的即 `base_ref`。

        **步骤 3：算 merge-base，锁定三点语法范围**
        ```bash
        git -C "{{ inputs.repo_path }}" merge-base "<base_ref>" HEAD
        ```
        得到 `<merge_base>`。审计范围恒为 `<merge_base>...HEAD`（三点语法：只审本分支从 base 分叉后独有的变更，不含 base 上的历史提交）。

        **步骤 4：抓 diff 文本**
        ```bash
        git -C "{{ inputs.repo_path }}" diff --find-renames --find-copies "<merge_base>...HEAD" > "{{ artifacts.init.run_dir }}/work/changed.diff"
        ```
        （renames/copies 归一，避免把改名当成整文件新增。）
        {% endif %}

        ## 分类变更文件

        {% if not inputs.diff_file %}
        ```bash
        git -C "{{ inputs.repo_path }}" diff --name-status -z --find-renames --find-copies "<merge_base>...HEAD"
        ```
        {% endif %}
        按状态位分类（diff_file 分支从 diff 头解析等价信息）：
        - `A`/`M`/`R`/`C`（新增/修改/改名/复制）→ **analyzable**（有新代码可审）
        - `D`（删除）→ deleted，不审代码本身，但记录下来（删掉的安全控制可能是回归）

        对 **analyzable** 文件再剔除以下（不进审计清单，但计数保留）：
        - 测试文件（`test_*` / `*_test.*` / `tests/` / `__tests__/` / `*.spec.*`）
        - 纯文档（`*.md` / `*.rst` / `*.txt`）、锁文件、生成文件（`*.lock` / `*.min.js` / `dist/`）
        - 二进制 / 图片 / 数据资源

        ## 写盘：diff-scope.json + changed.diff

        把审计范围元数据写到 `{{ artifacts.init.run_dir }}/work/diff-scope.json`（纯 JSON，供 diff_reviewer / diff_reporter 读）：
        ```json
        {
          "base_ref": "<base_ref 或 (diff_file)>",
          "merge_base": "<merge_base 或 (diff_file)>",
          "commit_range": "<merge_base>...HEAD 或 (diff_file)",
          "changed_diff_path": "{{ artifacts.init.run_dir }}/work/changed.diff",
          "analyzable_files": ["<相对 repo 路径>", "..."],
          "deleted_files": ["..."],
          "skipped_files": ["<测试/文档/生成物>", "..."],
          "diff_char_count": <changed.diff 字节数>
        }
        ```

        {% if inputs.scan_depth == 'deep' %}
        ### deep 模式追加：一跳调用方（affected_files）

        scan_depth=deep。**仅当 repo_path 非空时可行**（纯 diff_file 模式无源码可 grep）：
        对每个 analyzable 文件里被改动的函数/方法/导出符号，
        用 `git grep -n "<symbol>"`（在 repo 内只读）找出**直接调用它们的文件**（一跳 caller），
        去重后写入 diff-scope.json 的额外字段 `"affected_files": ["..."]`（不含 analyzable 自身）。
        这些文件不在 diff 里，但改动的 blast radius 会经它们放大，供 diff_reviewer 追调用链时读。
        找不到调用方或符号无法静态确定时，该字段填 `[]`，不阻塞。
        repo_path 为空（纯 diff_file 且 deep）→ `affected_files` 填 `[]`，diff_reviewer 会自动降级为 fast。
        {% endif %}

        ## 输出

        用结构化 output（turn_complete）回传下方字段。若因 shallow / 无法定基线而终止，`analyzable_count` 填 0、`stop_reason` 写明原因；正常时 `stop_reason` 留空。禁止 ask_owner 或任何需人工应答的提问（unattended，无人应答；基线歧义按上文优先级自行决策）。收到 `{"ok": true}` 后立即结束本轮，不再调用任何工具或继续输出。
      output_schema:
        base_ref: string
        commit_range: string
        changed_diff_path: string
        analyzable_count: number
        deleted_count: number
        diff_char_count: number
        stop_reason: string
      output: scope

  - job:
      actor: diff_reviewer
      wall_clock_seconds: 3600
      timeout: 3600
      prompt: |
        目标目录：{{ inputs.repo_path }}
        工作目录（RUN_DIR）：{{ artifacts.init.run_dir }}
        审计 skill 目录（AUDIT_SKILLS）：{{ artifacts.init.audit_skills_dir }}
        diff 范围：{{ artifacts.scope.commit_range }}（base：{{ artifacts.scope.base_ref }}）
        diff 文本：{{ artifacts.scope.changed_diff_path }}
        范围元数据：{{ artifacts.init.run_dir }}/work/diff-scope.json
        置信度下限 min_confidence：{{ inputs.min_confidence }}
        扫描深度 scan_depth：{{ inputs.scan_depth }}

        ## 前置：范围为空时直接结束

        若上游 `stop_reason` 非空（{% if artifacts.scope.stop_reason %}"{{ artifacts.scope.stop_reason }}"{% else %}无{% endif %}）或
        `analyzable_count == 0`（当前 {{ artifacts.scope.analyzable_count }}）→ 无可审变更：
        输出 `processed_count=0, issue_files="", verdict_summary="no changes", summary="<原因>"` 并结束，不写任何 issue。

        ## 开工前必读：审查标准纪律（强制）

        Read `AUDIT_SKILLS/guides/reviewer-discipline.md`，严格执行其中全部纪律（含 false-positive-traps /
        baseline-calibration 两个必读 guide、refuted 的 recall-safe 门槛、任何 verdict 都必须写盘）。
        这是审查基准，不因具体任务改变。

        ## 你的角色与本 playbook 的核心权衡

        你在做**增量 diff 安全审计**：只对本次变更引入或修改的代码找漏洞，而不是全仓审计。

        {% if inputs.scan_depth == 'deep' %}
        **deep 模式**：{% if inputs.repo_path %}你有源码访问权。以 `changed.diff` 为起点，但可以 Read/grep 仓库源码，
        对变更函数向上追调用方（diff-scope.json 的 `affected_files` 是一跳 caller 起点）、向下追数据流到 sink，
        确认攻击路径真实可达。目标是消除 fast 模式"看不到下游"的盲区。{% else %}未提供 repo_path，无源码可 Read/grep，
        **deep 追踪不可用，自动降级为 fast**：只看 diff 文本，遵循下方 fast 纪律，并在 `summary` 注明"deep 降级：无 repo_path"。{% endif %}
        {% else %}
        **fast 模式（默认）**：你**只看 diff 文本**（`changed.diff`），这是速度换上下文的刻意权衡——
        不去 Read 仓库其余源码、不追跨文件调用链。以下纪律是本模式的灵魂：

        > **CRITICAL INSTRUCTION**：只要 diff 文本本身清楚显示了一个违规——被删/被禁用的安全检查、
        > 已知危险的 sink、同僚兄弟代码有而这段新代码缺的控制——就上报，**即使你看不到结果在下游怎么被消费**。
        > 看不到完整 blast radius 影响的是 **severity（保守下调，如把 CRITICAL 记成 MEDIUM），不是要不要报**。不要因为"看不到下游"就丢弃 finding。
        {% endif %}

        **召回优先于精准**：diff 里有疑问时选 `blocked`（需运行时/下游信息才能定论），不轻易 `refuted`。
        漏掉一个真实高危漏洞，比多留一个待人工复查的 issue 代价高得多。

        ## 步骤 1：读 diff，切分审查单元

        Read `{{ artifacts.scope.changed_diff_path }}`。若 `diff_char_count` 很大（> 60000 字节），
        **按 `diff --git a/... b/...` 文件边界把 diff 切成多批**，每批累计 ≤ 60000 字节，逐批读审——
        不要因为 diff 大就只看开头。每个变更文件（及其新增/修改的 hunk）是一个审查单元。

        {% if inputs.scan_depth == 'deep' %}
        deep 模式：额外把 diff-scope.json 的 `affected_files`（一跳调用方）纳入阅读，
        对每个可疑变更函数至少上溯 3 层调用链确认可达性，别因"直接调用点没问题"就停。
        {% endif %}

        ## 步骤 2：跨类别穷举安全审查（8 维度）

        对每个变更单元，**不绑定单一类别**，依次检查 8 个安全维度（需要具体判据/CWE 取值时 Read
        `AUDIT_SKILLS/rules/<相关规则>.md`，如 idor / ssrf / sql-injection / replay-attack / race-condition /
        prototype-pollution / insecure-crypto / secrets）：

        | 类别 | 核心问题（结合 diff 特有判据） |
        |------|---------|
        | authn | 新增/改动的接口用 ID 查资源，但 diff 上下文里看不到归属过滤（`user=request.user` / `org_id=request.auth.org` 类）→ 标记（**IDOR/BOLA**）。信任调用方传入的 ID？有 authz 还是只有 authn？被删掉的鉴权 decorator？ |
        | injection | 用户可控输入流入 SQL / shell / file path / URL / template / eval？中间有无参数化 / 白名单？新增的字符串拼接 sink？ |
        | business_logic | **Mass Assignment**：`request.data` / `**kwargs` / `model_validate(body)` 未经白名单直传 ORM/model。状态机迁移条件是否完整？金额/数量范围与符号？审批步骤能否跳过？idempotency 缺失？ |
        | replay | 支付/提现/认证路径新代码看不到 nonce/时间窗口/一次性消费标记？签名/token/challenge 消费后是否标记已用？认证 ≠ 防重放。短数字 OTP/PIN 或小空间 token 无限次校验 = **真漏洞必报**（不算限流 nitpick）。 |
        | concurrency | 新增的读-改-写是否在事务/锁内？`select_for_update` / 原子 SQL 缺失导致双扣或状态跳跃（TOCTOU）？ |
        | data | 新代码返回值/日志含 token/密钥/PII/内部错误栈？serializer/response_model 是否过滤敏感字段？写入 DB 后被再读渲染（second-order / stored XSS）？ |
        | crypto | 随机数来源安全（secrets/os.urandom，非 random）？加密有认证（GCM）？**硬编码密钥/凭证**？弱算法、证书校验被关？ |
        | config | 硬编码密钥？DEBUG 打开？CORS `*` + `allow_credentials=True`？不该暴露的管理接口？框架特定：Django `mark_safe()`、JWT `alg=none`/未验签/信任调用方公钥。JS/TS：`for...in` merge 未过滤 `__proto__`（**Prototype Pollution**）。 |
        > 框架隐含契约（DRF `permission_classes` 默认、FastAPI `response_model` 过滤、Celery 无 request context 却收用户可控 URL → SSRF、ORM lazy eval）按安全后果归入上述 8 类。

        ## 步骤 3：severity 与 confidence（diff 审计特有尺度）

        **severity**（看不到下游时保守取低档，但不丢 finding）：
        - `CRITICAL`：几乎无前提即击穿 认证 / 资金 / 签名 / 托管
        - `HIGH`：同类被击穿，但需一个前提（一个已抓包的请求、一份已持有的凭证、一次竞态）
        - `MEDIUM`：真实但有界
        - `LOW`：加固 / 纵深防御，当下无具体可利用路径

        **confidence**（0.0–1.0）：你对『**diff 文本本身显示了真实违规**』的确信度——**不是**对下游 blast radius 的确信度
        （后者归入 severity）。低于 `{{ inputs.min_confidence }}` 太投机 → **不写成 issue**（可在 summary 里一句话提一嘴被舍弃的数量）。
        confidence 只用于这个"是否成条"的门槛，**不落盘**（issue frontmatter 无此字段）。

        ## 步骤 4：给出 discovery_verdict（4 选 1）

        - **confirmed**：diff 文本（deep 模式含追踪到的调用链）清楚显示违规、攻击路径成立
        - **escalate**：比初判更严重（升 severity 或换 vuln_type）
        - **refuted**：diff 内有明确防护、且（fast 模式限 diff 可见范围内 / deep 模式追完所有调用路径）——门槛极高，三条件见 reviewer-discipline.md，须全满足并引用具体行号，否则一律 blocked
        - **blocked**：需要 diff 之外的运行时/下游信息才能定论；fast 模式看不到下游而无法排除风险时选此，不选 refuted

        ## 步骤 5：写 issue 文件（任何 verdict 都写）

        路径：`{{ artifacts.init.run_dir }}/issues/<issue_id>.md`

        **字段、frontmatter 结构、issue_id 构造规则、正文模板、cwe 取值与"同位置多漏洞"拆分规则**：完全按
        `AUDIT_SKILLS/SCHEMA-issue.md` 执行——**执行前先 Read 一次**确认字段名和约束（尤其 cwe 取值来源，
        以及"同一 symbol/endpoint/file:line 上多个独立 CWE 必须拆成多条独立 issue、不得合成一条"的强制拆分规则——
        它直接决定下游 merge_dedup 去重是否正确）。

        discovery 阶段写齐所有必填字段：`canonical` 固定 `true`、**`source_pass` 填 `diff_review`**、
        `primary_location` 用 diff 里的 `path:line`（相对 repo）、`affected_entrypoints` 无法从 diff 确定时填 `[]`、
        `authn_level` 无关联入口时填 `authenticated`；**不要预填**合并阶段字段（`duplicate_files`/`superseded_by`/`final_verdict` 等，由 merge_dedup.py 写）。

        **同时写机读旁路 issue-meta**（供报告阶段确定性去重脚本 merge_dedup.py 读取）：每写一条 issue `.md`，
        就按 SCHEMA-issue.md「机读旁路」小节格式，用 apply_patch 在
        `{{ artifacts.init.run_dir }}/work/issue-meta/<issue_id>.json` 写一份同字段值的纯 JSON 副本
        （值与 `.md` frontmatter 完全一致；数组字段缺失填 `[]`、`primary_symbol` 不定填 `""`）。
        **这是 merge_dedup 去重的唯一数据源，必须每条 issue 都写、`issue_file` 用绝对路径。**

        ## 输出

        `processed_count`：审查的变更单元（文件/hunk）总数。
        `issue_files`：写入的 issue 文件路径列表（换行分隔）。
        `verdict_summary`：confirmed/escalate/refuted/blocked 各数量。
        `summary`：一句话说明审查范围，例如"diff 审查 6 个变更文件，发现 2 个 issue（1 confirmed / 1 blocked），舍弃 1 个 confidence<0.7 的可疑点"。

        用结构化 output（turn_complete）回传上述字段，不要把结果 dump 到终端。禁止 ask_owner 或任何需人工应答的提问（unattended，无人应答；判不清的单元按步骤 4 的 `blocked` verdict 处理并继续）。收到 `{"ok": true}` 后立即结束本轮，不再调用任何工具或继续输出。
      output_schema:
        processed_count: number
        issue_files: string
        verdict_summary: string
        summary: string
      output: review

  - job:
      actor: diff_reporter
      wall_clock_seconds: 1200
      prompt: |
        工作目录（RUN_DIR）：{{ artifacts.init.run_dir }}
        审计 skill 目录：{{ artifacts.init.audit_skills_dir }}
        diff 审查结果：{{ artifacts.review.summary }} | {{ artifacts.review.verdict_summary }}

        **字段、frontmatter、index.jsonl schema、findings.json 字段映射**：按
        `{{ artifacts.init.audit_skills_dir }}/SCHEMA-issue.md` 执行。执行前 Read 一次。

        ## 前置：无 issue 时也要产出空交付

        若 diff_reviewer `processed_count == 0` 或没有任何 issue-meta：跳过去重，直接写空交付
        （findings.json 空 `findings[]` + summary 零值、refuted.json 同、run.json、vulnerabilities.csv 只有表头），并结束。

        ## 步骤 0：确定性去重 + 写 index.jsonl（唯一 index 生成点，禁止手工去重）

        先跑这一条命令（读 diff_reviewer 写的机读旁路 `work/issue-meta/*.json`，纯 JSON）：

        ```bash
        python3 "{{ artifacts.init.audit_skills_dir }}/scripts/merge_dedup.py" "{{ artifacts.init.run_dir }}"
        ```

        脚本（确定性，无 LLM 判断）：按 SCHEMA「去重 key 规范」分组、每组选 canonical、severity 取组内最高、
        给 canonical/非 canonical `.md` 打标并写 `final_verdict = discovery_verdict`（本流水线无对抗复核），
        写 `RUN_DIR/issues/index.jsonl`，stdout 打印一行 JSON
        `{total_issues, total_canonical, discovery_confirmed, discovery_escalate, discovery_refuted, discovery_blocked}`。
        **不要删除任何 refuted / blocked issue 文件**。脚本非零退出或 JSON 缺字段 → 记录 stderr 并终止。

        ## 步骤 1：以 index.jsonl 为 source of truth 统计

        读 `RUN_DIR/issues/index.jsonl`，按主 issue `final_verdict` 分桶（confirmed / escalate / refuted / blocked）。
        若 index.jsonl 缺失或字段不完整，**不得**用可能不全的 frontmatter 扫描顶替——先遍历 `RUN_DIR/issues/*.md`
        逐条抽 frontmatter 重建完整 index.jsonl（`final_verdict = discovery_verdict`），在 audit-log 记"索引已重建、覆盖 N 条"，再统计。
        给出风险评分（1-10，仅基于 final_verdict 为 confirmed/escalate 的 issue）。

        ## 步骤 2：生成机读交付（唯一来源：index.jsonl 中 canonical==true 的主 issue）

        读 `RUN_DIR/work/diff-scope.json` 取 diff 元数据（base_ref/commit_range/analyzable/deleted 计数）。
        下方所有 `repo_path` 字段：inputs.repo_path 非空用其绝对路径 `{{ inputs.repo_path }}`，纯 diff_file 模式（为空）时填 `"(diff_file)"`。

        **2a. `RUN_DIR/findings.json`（主交付物，供 CI / dashboard / 告警消费）**——`findings[]` **只收**
        `final_verdict ∈ {confirmed, escalate, blocked}` 的主 issue（要修 + 要人工看；**refuted 不进此数组**）。
        每条 finding 按 SCHEMA「findings.json 字段映射」小节生成，带 `status`（=final_verdict）与 `final_verdict_reason`：
        ```json
        {
          "run_id": "<RUN_ID>", "repo_path": "<绝对路径>", "generated_at": "<ISO8601>",
          "scope": {
            "mode": "diff", "scan_depth": "{{ inputs.scan_depth }}",
            "base_ref": "<diff-scope.base_ref>", "commit_range": "<diff-scope.commit_range>",
            "analyzable_files": <N>, "deleted_files": <N>
          },
          "summary": {
            "total": <全部四桶主 issue 总数（含 refuted）>,
            "confirmed": <N>, "escalate": <N>, "blocked": <N>, "refuted": <N>,
            "by_severity": {"CRITICAL": <N>, "HIGH": <N>, "MEDIUM": <N>, "LOW": <N>, "INFO": <N>}
          },
          "findings": [ /* 只含 confirmed/escalate/blocked，按 SCHEMA 字段映射 + severity DESC 排序 */ ]
        }
        ```

        **2b. `RUN_DIR/refuted.json`（审计留痕）**——`findings[]` 只收 `final_verdict == refuted` 的主 issue，
        字段映射同上、额外带 `final_verdict_reason`；顶层结构同 2a，`summary.refuted` = 条数、其余桶填 0。

        **2c. `RUN_DIR/run.json`（元数据）**：
        ```json
        {
          "run_id": "<RUN_ID>", "repo_path": "<绝对路径>",
          "started_at": "<从 RUN_ID 前缀 YYYYMMDD-HHMMSS 解析成 ISO8601>",
          "finished_at": "<当前 ISO8601>",
          "mode": "diff", "scan_depth": "{{ inputs.scan_depth }}",
          "base_ref": "<diff-scope.base_ref>", "commit_range": "<diff-scope.commit_range>",
          "final": {"confirmed": <N>, "escalate": <N>, "refuted": <N>, "blocked": <N>, "risk_score": <1-10>}
        }
        ```

        **2d. `RUN_DIR/vulnerabilities.csv`（平铺索引）**——从 findings.json 的 `findings[]` 派生（不含 refuted），
        5 列表头 `id,title,severity,discovered_at,location`：`id`=issue_id；`title` 按 RFC 4180 转义（含逗号则 `"..."` 包裹、内部 `"` 加倍）；
        `severity` 取生效值；`discovered_at` 取 frontmatter `discovery_at`；`location`=`file:line`（相对 repo 路径）。按 severity DESC。0 条也写（只表头）。

        约束：4 个文件都必须生成；0 条也写空数组 / 只表头；仅由本步骤生成。

        ## 步骤 3：PoC 骨架 + audit-log

        为 `final_verdict ∈ {confirmed, escalate, blocked}` 的 issue，在 `RUN_DIR/verify/<issue_id>.poc.<ext>`
        补一个复现骨架（目标接口、恶意输入、预期 vs 实际、前置条件，含"需人工在受控环境执行"的醒目注释，
        顶部注释引用对应 `issues/<issue_id>.md` 与 `primary_location`）——**只补脚本，绝不执行、不发真实请求**。

        在 `RUN_DIR/audit-log.md` 末尾追加一段 `## Diff 审计汇总`：base_ref / commit_range / scan_depth、
        analyzable/deleted 文件数、final 四桶统计与风险评分、findings.json 路径。

        ## 输出

        用结构化 output（turn_complete）回传字段。禁止 ask_owner 或任何需人工应答的提问（unattended，无人应答；拿不准按上文规则自行决策并继续）。收到 `{"ok": true}` 后立即结束本轮，不再调用任何工具或继续输出。
      output_schema:
        final_confirmed: number
        final_escalate: number
        final_refuted: number
        final_blocked: number
        risk_score_final: number
      output: final

  - done:
      message: |
        Diff 安全审计完成 | Run {{ artifacts.init.run_id }}
        范围：{{ artifacts.scope.commit_range }}（base {{ artifacts.scope.base_ref }}）| 深度 {{ inputs.scan_depth }}
        变更文件：analyzable {{ artifacts.scope.analyzable_count }} / deleted {{ artifacts.scope.deleted_count }} | diff {{ artifacts.scope.diff_char_count }} 字节
        {% if artifacts.scope.stop_reason %}⚠ 未审：{{ artifacts.scope.stop_reason }}{% endif %}

        Final：confirmed {{ artifacts.final.final_confirmed }} / escalate {{ artifacts.final.final_escalate }} / refuted {{ artifacts.final.final_refuted }} / blocked {{ artifacts.final.final_blocked }}（评分 {{ artifacts.final.risk_score_final }}/10）

        产物：{{ artifacts.init.run_dir }}/{findings.json（要修+待人工看）, refuted.json（否决留痕）, run.json, vulnerabilities.csv, issues/, verify/（PoC 骨架）, work/（changed.diff, diff-scope.json, 中间草稿）}

        要修项: jq '.findings[] | select(.status == "confirmed" or .status == "escalate")' {{ artifacts.init.run_dir }}/findings.json
        人工复核项: final_verdict == blocked（多为 fast 模式看不到下游而无法排除，deep 模式或人工可进一步定论）；本 playbook 不自动执行 PoC。

---

增量（diff）代码安全审计（独立 playbook，面向 CI/PR gate）：定位 skill → 建 RUN_DIR → 解析 merge-base 三点语法变更范围并抓 diff → 跨 8 类安全审查（fast 只看 diff、看不到下游只降 severity 不丢 finding；deep 追一跳调用方与调用链）→ 确定性去重生成 findings.json。复用 security-audit 的 code-security skill（rules/guides/SCHEMA-issue.md）与 merge_dedup.py，产物与全仓 security-audit 对齐。
