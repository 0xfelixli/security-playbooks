---
name: code-security
description: "Security guidelines for writing secure code. Use when writing code, reviewing code for vulnerabilities, or asking about secure coding practices like 'check for SQL injection' or 'review security'. IMPORTANT: Always consult this skill when writing or reviewing any code that handles user input, authentication, file operations, database queries, network requests, cryptography, or infrastructure configuration (Terraform, Kubernetes, Docker, GitHub Actions) — even if the user doesn't explicitly mention security. Also use when users ask to 'review my code', 'check this for bugs', or 'is this safe'."
---

# Code Security Guidelines

Comprehensive security rules for writing secure code across 15+ languages. Covers OWASP Top 10, infrastructure security, and coding best practices with 32 rule categories across 10 Critical, 19 High, 2 Medium, and 1 Low impact level.

## How to Use This Skill

**Proactive mode** — When writing or reviewing code, automatically check for relevant vulnerabilities based on the language and patterns present. You don't need to wait for the user to ask about security.

**Reactive mode** — When the user asks about security, use the categories below to find the relevant rule file, then read it for detailed vulnerable/secure code examples.

### Workflow
1. Identify the language and what the code does (handles input? queries a DB? reads files?)
2. Check the relevant rules below — focus on Critical and High impact first
3. Read the specific rule file from `rules/` for detailed code examples in that language
4. Apply the secure patterns, or flag the vulnerable patterns if reviewing

## Language-Specific Priority Rules

When writing code in these languages, check these rules first:

| Language / Framework | Priority Rules to Check |
|----------------------|------------------------|
| **Python** | SQL injection, command injection, path traversal, code injection, SSRF, insecure crypto |
| **FastAPI** | framework-fastapi (auth≠authz, field leakage, CORS, async DoS), SQL injection, IDOR |
| **Django / DRF** | framework-django (mark_safe XSS, CSRF, cookie flags, ViewSet permissions), SQL injection, IDOR |
| **Celery** | celery (task SSRF, command injection, auth not inherited, sensitive args in broker, replay) |
| **OAuth / OIDC** | oauth (code interception, redirect_uri open redirect, PKCE, state CSRF, token validation) |
| **JavaScript/TypeScript** | XSS, prototype pollution, code injection, insecure transport, CSRF |
| **React** | XSS (dangerouslySetInnerHTML), insecure transport, secrets |
| **Java** | SQL injection, XXE, insecure deserialization, insecure crypto, SSRF |
| **Go** | SQL injection, command injection, path traversal, insecure transport |
| **C/C++** | Memory safety, unsafe functions, command injection, path traversal |
| **Ruby** | SQL injection, command injection, code injection, insecure deserialization |
| **PHP** | SQL injection, XSS, command injection, code injection, path traversal |
| **HCL/YAML** | Terraform (AWS/Azure/GCP), Kubernetes, Docker, GitHub Actions |

## Categories

### Critical Impact
- **SQL Injection** (`rules/sql-injection.md`) - Use parameterized queries, never concatenate user input
- **Command Injection** (`rules/command-injection.md`) - Avoid shell commands with user input, use safe APIs
- **XSS** (`rules/xss.md`) - Escape output, use framework protections
- **XXE** (`rules/xxe.md`) - Disable external entities in XML parsers
- **Path Traversal** (`rules/path-traversal.md`) - Validate and sanitize file paths
- **Insecure Deserialization** (`rules/insecure-deserialization.md`) - Never deserialize untrusted data
- **Code Injection** (`rules/code-injection.md`) - Never eval() user input
- **Hardcoded Secrets** (`rules/secrets.md`) - Use environment variables or secret managers
- **Memory Safety** (`rules/memory-safety.md`) - Prevent buffer overflows, use-after-free, integer overflow (C/C++)
- **Business Logic** (`rules/business-logic.md`) - State machine bypass, approval flow bypass, mass assignment, trust anchor confusion

### High Impact
- **Insecure Crypto** (`rules/insecure-crypto.md`) - Use SHA-256+, AES-256, avoid MD5/SHA1/DES
- **Insecure Transport** (`rules/insecure-transport.md`) - Use HTTPS, verify certificates
- **SSRF** (`rules/ssrf.md`) - Validate URLs, use allowlists
- **JWT Issues** (`rules/authentication-jwt.md`) - Always verify signatures
- **CSRF** (`rules/csrf.md`) - Use CSRF tokens on state-changing requests
- **Prototype Pollution** (`rules/prototype-pollution.md`) - Validate object keys in JavaScript
- **IDOR** (`rules/idor.md`) - Verify ownership on every object access, never trust caller-supplied IDs alone
- **API Replay Attack** (`rules/replay-attack.md`) - Require nonce + timestamp on critical operations
- **FastAPI Security** (`rules/framework-fastapi.md`) - Auth≠authz, sensitive field leakage, CORS, async DoS, SQL in raw queries
- **Django / DRF Security** (`rules/framework-django.md`) - mark_safe XSS, CSRF bypass, cookie flags, ViewSet permissions, file uploads
- **OAuth 2.0 / OIDC** (`rules/oauth.md`) - Code interception, redirect_uri validation, state/PKCE, ID token claims, refresh token rotation
- **Celery Task Security** (`rules/celery.md`) - SSRF via callback URLs, command injection, auth not inherited from enqueue context, sensitive data in broker logs, replay attacks
- **Entry Point Enumeration** (`guides/entrypoints.md`) - Backend: HTTP routes, async queues (Celery/Kafka/SQS), WebSocket, CLI, GraphQL grep patterns. Frontend: URL params, API response rendering, WebSocket messages, postMessage, localStorage, third-party scripts, dangerous sinks (dangerouslySetInnerHTML, innerHTML, eval)

### Infrastructure
- **Terraform AWS/Azure/GCP** (`rules/terraform-aws.md`, `rules/terraform-azure.md`, `rules/terraform-gcp.md`) - Encryption, least privilege, no public access
- **Kubernetes** (`rules/kubernetes.md`) - No privileged containers, run as non-root
- **Docker** (`rules/docker.md`) - Don't run as root, pin image versions
- **GitHub Actions** (`rules/github-actions.md`) - Avoid script injection, pin action versions

### Medium/Low Impact
- **Regex DoS** (`rules/regex-dos.md`) - Avoid catastrophic backtracking
- **Race Conditions** (`rules/race-condition.md`) - Use proper synchronization; TOCTOU in financial flows → see `business-logic.md` (CRITICAL)
- **Best Practices** (`rules/best-practice.md`) - General secure coding patterns

See `rules/_sections.md` for the full index with CWE/OWASP references.

## Code Quality Guides

Language and framework-specific code quality patterns. Use alongside security rules when reviewing code in these stacks.

| Guide | Path | Key Topics |
|-------|------|-----------|
| **False Positive Traps** | `guides/false-positive-traps.md` | 7 种最常见的错误否决真实漏洞场景；unit_reviewer 和 challenger 开工前必读 |
| **Baseline Calibration** | `guides/baseline-calibration.md` | 同类对标校准：用成熟参照系判误报与定 severity；有 CVE 先例的 pattern 不因"常见"降级；unit_reviewer 与 challenger 开工前必读 |
| **Go** | `guides/go.md` | Error handling, goroutine leaks, context, interface design, common gotchas |
| **Python** | `guides/python.md` | Type hints, async/await, exception handling, common pitfalls, testing, performance |
| **TypeScript** | `guides/typescript.md` | Type safety, generics, strict mode, async patterns, immutability, ESLint |
| **React** | `guides/react.md` | Hooks rules, useEffect patterns, useMemo/useCallback, RSC, React 19, TanStack Query v5 |
| **FastAPI** | `guides/fastapi.md` | Dependency injection, Pydantic v2, async correctness, N+1, test-driven verification |
| **Django / DRF** | `guides/django.md` | N+1 optimization, serializer patterns, ViewSet practices, async views |

> Security-specific patterns for FastAPI and Django are in `rules/framework-fastapi.md` and `rules/framework-django.md`.

## Quick Reference

| Vulnerability | Key Prevention |
|--------------|----------------|
| SQL Injection | Parameterized queries |
| XSS | Output encoding |
| Command Injection | Avoid shell, use APIs |
| Path Traversal | Validate paths |
| SSRF | URL allowlists |
| Secrets | Environment variables |
| Crypto | SHA-256, AES-256 |

## 维护约定（新增 / 修改 rules 与 guides）

- `rules/` 只放**安全漏洞**规则——能帮 agent 判断"是否应上报一个漏洞"。普通代码风格、性能、可维护性建议不属于这里。
- 每个 `rules/*.md` 必须包含：漏洞成立条件、触发信号（grep 模式 / 危险函数）、`Not a Finding` 排除项、修复方向。排除项用于避免把框架默认行为或低风险风格误报成漏洞。
- `guides/` 放方法论与框架 / 语言理解材料（入口枚举、调用链、框架机制），影响扫描路径但**不等于"发现即上报"**的漏洞规则。
- 新增 rule 后同步更新 `rules/_sections.md` 的分节与 Rule File Summary 表（编号、impact、CWE/OWASP）。

## 审计脚手架脚本（scripts/）

本 skill 随附 `scripts/` 目录，是 security-audit playbook 的**确定性工具**（非 LLM 判断，供 playbook 调用；`code-security` 作为审计 skill 的一部分随其一起分发/同步）：

- `init_run_dir.py` — 建 RUN_DIR + 标准子目录，解析 `audit_skills_dir` / `scripts_dir` 并校验 skills 布局（rules/ guides/ SCHEMA-issue.md）。用 `__file__` 自定位（skill 根 = 脚本父目录的父目录，scripts_dir = 脚本父目录），不 import 框架、不依赖 cwd。
- `generate_worklist.py` — 按函数/文件单元生成全仓穷举审查的确定性 worklist。
- `reconcile_coverage.py` — 覆盖核对：worklist 与 per-unit record 对账，防漏审。
- `merge_dedup.py` — report 阶段的**确定性去重 + 建 index.jsonl**：读 unit_reviewer 写的机读旁路 `work/issue-meta/*.json`（纯 JSON，不解析 LLM 手写 YAML），按 SCHEMA 去重 key 分组、选 canonical、severity 取最高、标 `.md` frontmatter、写 `issues/index.jsonl`、打印四桶计数。把去重从 issue_merger 的 LLM turn 挪出。
- `plan_challenger_batches.py` — report 阶段对抗复核的**预算排序 + 分批**（确定性）：读 `issues/index.jsonl` 的 canonical 行，按 severity→discovery_verdict→issue_id 排序、算 quota（CRITICAL/HIGH 强制全入）、每 5 个切批、写 `work/challenger-dispatch.jsonl`、给未入选 issue 标 `skipped_quota` frontmatter，stdout 打印 `challenger_batches` 等字段。把这段机械活挪出 issue_merger 的 LLM turn，避免手搓大数组导致 stall。

调用约定：init 阶段以 `<SKILLS>/scripts/init_run_dir.py` 运行，其输出的 `scripts_dir`（= `<SKILLS>/scripts`）沿 playbook 传给 coverage 阶段运行其余两个脚本。这些脚本是审计流水线专用，不属于"写安全代码"的通用知识；修改时注意与 playbook 的调用契约（参数、stdout JSON 字段）保持一致。
