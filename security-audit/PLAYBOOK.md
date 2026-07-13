---
id: security-audit
uri: builtin://security-audit
version: "7.0"
title: Security Audit
summary: |
  全仓代码安全审计：① 全仓文件级穷举审查（unit-based，覆盖仓库**全部生产源码文件**——Python 经 AST 拆成函数/方法/模块单元，非 Python 以文件级单元纳入；确定性 worklist + per-unit record 对账防偷懒；排除 tests/migrations/vendor/生成产物），融合预扫描（grep）+ authn 兄弟端点横向对比 + high_risk_paths 三路信号作为强制关注点；② 独立对抗复核。流程：系统理解（analysis/）→ 枚举入口 → 全仓文件级穷举审查（三路信号播种）→ 确定性覆盖核对/补审 → 跨类别去重 → 独立 challenger 对抗复核（含反驳自检+补漏扫描）→ 输出 findings.json + coverage.json + coverage-audit.json + verify/ 下 PoC 脚本骨架。
attended_mode: unattended
approval_policy: security-owner
approval_policies:
  security-owner:
    normal: approve
    sensitive: approve
limits:
  wall_clock_seconds: 21600
  # 成本兜底：非预期开销，仅用于拦截失控（如死循环重试/扇出爆炸），并非正常一次审计的预算。
  # 全仓穷举 + parallel 扇出 + opus 对抗复核属重成本流程，请按目标仓库规模与实际预算调高/调低。
  total_cost_usd: 80.0
inputs:
  repo_path:
    type: string
    required: true
    description: "被审计目标目录的绝对路径（**纯只读输入**，审计不往里写任何产物）。产物默认落到 artifacts_root（见下），不再污染源码库。"
  artifacts_root:
    type: string
    required: false
    default: "~/workmate/security-audit"
    description: "审计产物根目录，与被审计仓库分离。产物落到 <artifacts_root>/<repo_slug>/<run_id>/。默认 ~/workmate/security-audit（在 Workmate 同步根内，agent 有写权限）。**任何情况下都不写进被审计仓库**——repo_path 是纯只读输入；留空即用该默认根。"
  challenger_max_ratio:
    type: number
    required: false
    default: 0.3
    description: "对抗复核覆盖比例（0.0-1.0）。默认 0.3：抽样复核以降低长尾成本，CRITICAL/HIGH 仍强制全复核。实际复核数 = ceil(canonical_issue_count × ratio)，至少 1（canonical 非空时）。超出比例的 issue 标记为 skipped_quota 进入 audit-log。"
  scan_depth:
    type: string
    required: false
    default: "balanced"
    description: "扫描深度模式。balanced：默认，unit-review 正常穷举审查。deep：在 balanced 基础上强制逐层上溯穷举 3 层调用链、suspect 候选数量上限放宽，适合高价值目标彻查。"
actors:
  orchestrator:
    provider: codex
    mode: edit
worktree:
  enabled: false
workflow:

  - call:
      playbook: security-audit-init
      inputs:
        repo_path: "{{ inputs.repo_path }}"
        artifacts_root: "{{ inputs.artifacts_root }}"

  - call:
      playbook: security-audit-coverage
      inputs:
        repo_path: "{{ inputs.repo_path }}"
        run_dir: "{{ artifacts.init.run_dir }}"
        audit_skills_dir: "{{ artifacts.init.audit_skills_dir }}"
        recommended_categories: "{{ artifacts.entrypoints.recommended_categories }}"
        high_risk_paths: "{{ artifacts.analysis.high_risk_paths }}"
        tech_stack: "{{ artifacts.entrypoints.tech_stack }}"
        scan_depth: "{{ inputs.scan_depth }}"
        scripts_dir: "{{ artifacts.init.scripts_dir }}"

  - call:
      playbook: security-audit-report
      inputs:
        repo_path: "{{ inputs.repo_path }}"
        run_dir: "{{ artifacts.init.run_dir }}"
        audit_skills_dir: "{{ artifacts.init.audit_skills_dir }}"
        analysis_dir: "{{ artifacts.analysis.analysis_dir }}"
        challenger_max_ratio: "{{ inputs.challenger_max_ratio }}"
        scan_depth: "{{ inputs.scan_depth }}"

  - done:
      message: |
        安全审计完成 | Run {{ artifacts.init.run_id }}
        覆盖 {{ artifacts.coverage_metrics.coverage_percent }}% (未覆盖 {{ artifacts.coverage_metrics.uncovered_after }}) | 达标 {{ artifacts.final.coverage_passed }}
        类别 {{ artifacts.entrypoints.recommended_categories }} | 预扫描（{{ artifacts.prescan.scanner_used }}）命中 {{ artifacts.prescan.prescan_hits }} | authn 兄弟端点对比 {{ artifacts.authn_sibling.authn_sibling_suspects_count }}
        文件级穷举：{{ artifacts.unit_file_results.total_units }} 组 / worklist {{ artifacts.unit_file_results.worklist_units }} 单元（新增 issue 见下方 issues/ 统计）

        Discovery: confirmed {{ artifacts.merged.discovery_confirmed }} / escalate {{ artifacts.merged.discovery_escalate }} / refuted {{ artifacts.merged.discovery_refuted }} / blocked {{ artifacts.merged.discovery_blocked }} (评分 {{ artifacts.merged.risk_score_discovery }}/10)
        Adversarial: 翻 {{ artifacts.merged.overturned_count }} | 救 {{ artifacts.merged.rescued_count }} | 人工验证 {{ artifacts.final.needs_poc_list }}
        Final: confirmed {{ artifacts.final.final_confirmed }} / escalate {{ artifacts.final.final_escalate }} / refuted {{ artifacts.final.final_refuted }} / blocked {{ artifacts.final.final_blocked }} (评分 {{ artifacts.final.risk_score_final }}/10)

        产物：{{ artifacts.init.run_dir }}/{findings.json(有效漏洞), refuted.json(否决留痕), run.json(元数据), vulnerabilities.csv(平铺索引), coverage.json, coverage-critic.json, audit-log.md, cumulative-issues.md, entrypoints/, analysis/, issues/, verify/(PoC 骨架), work/(中间草稿)}

        confirmed: jq '.findings[] | select(.status == "confirmed")' {{ artifacts.init.run_dir }}/findings.json
        人工验证项: NEEDS_POC / challenge_failed / refutation_not_ratified 需要人工选择受控环境和验证方式后再处理；本 playbook 不自动执行 PoC。

---

全仓代码安全审计 orchestrator（覆盖：全仓文件级穷举审查 + 对抗复核）：调度初始化（系统理解+入口枚举）、发现+覆盖（预扫描/authn横向对比信号播种 + 全仓穷举审查+核对+补审）、报告（去重+对抗复核+汇总）三个阶段子 playbook，输出机器可读 findings.json，并在 verify/ 下补充 confirmed/escalate/NEEDS_POC/refutation_not_ratified issue 的 PoC 脚本骨架（不自动执行）。
