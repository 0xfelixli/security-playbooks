---
id: security-audit
uri: builtin://security-audit
version: "2026.07.13"
title: Security Audit
summary: |
  全仓代码安全审计 orchestrator：文件级穷举审查（三路信号播种），输出机读 findings.json 与覆盖报告。
attended_mode: unattended
approval_policy: security-owner
approval_policies:
  security-owner:
    normal: approve
    sensitive: approve
limits:
  wall_clock_seconds: 21600
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
        scan_depth: "{{ inputs.scan_depth }}"

  - done:
      message: |
        安全审计完成 | Run {{ artifacts.init.run_id }}
        覆盖 {{ artifacts.coverage_metrics.coverage_percent }}% (未覆盖 {{ artifacts.coverage_metrics.uncovered_after }}) | 达标 {{ artifacts.final.coverage_passed }}
        类别 {{ artifacts.entrypoints.recommended_categories }} | 预扫描（{{ artifacts.prescan.scanner_used }}）命中 {{ artifacts.prescan.prescan_hits }} | authn 兄弟端点对比 {{ artifacts.authn_sibling.authn_sibling_suspects_count }}
        文件级穷举：{{ artifacts.unit_file_results.total_units }} 组 / worklist {{ artifacts.unit_file_results.worklist_units }} 单元（新增 issue 见下方 issues/ 统计）

        Final: confirmed {{ artifacts.final.final_confirmed }} / escalate {{ artifacts.final.final_escalate }} / refuted {{ artifacts.final.final_refuted }} / blocked {{ artifacts.final.final_blocked }} (评分 {{ artifacts.final.risk_score_final }}/10)

        产物：{{ artifacts.init.run_dir }}/{findings.json(有效漏洞), refuted.json(否决留痕), run.json(元数据), vulnerabilities.csv(平铺索引), coverage.json, coverage-critic.json, audit-log.md, cumulative-issues.md, entrypoints/, analysis/, issues/, verify/(PoC 骨架), work/(中间草稿)}

        confirmed: jq '.findings[] | select(.status == "confirmed")' {{ artifacts.init.run_dir }}/findings.json
        人工复核项: final_verdict == blocked 的 issue 需人工选择受控环境和验证方式后再处理；本 playbook 不自动执行 PoC。

---

全仓代码安全审计 orchestrator（覆盖：全仓文件级穷举审查）：调度初始化（系统理解+入口枚举）、发现+覆盖（预扫描/authn横向对比信号播种 + 全仓穷举审查+核对+补审）、报告（去重+汇总）三个阶段子 playbook，输出机器可读 findings.json，并在 verify/ 下补充 confirmed/escalate/blocked issue 的 PoC 脚本骨架（不自动执行）。
