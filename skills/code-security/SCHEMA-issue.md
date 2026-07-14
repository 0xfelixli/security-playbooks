---
title: Issue 文件 + 索引 schema 契约
kind: contract
applies_to: [security-audit, security-audit-coverage, security-audit-unit-review, security-audit-report]
---

# Issue Schema 契约

本文件是 `<RUN_DIR>/issues/` 下 issue 文件以及 `<RUN_DIR>/issues/index.jsonl` 索引行的 **唯一字段定义**。所有 actor（unit_reviewer / coverage_critic / final_reporter）必须按本契约读写，**不要在 prompt 里重新列出字段清单**。

---

## Issue 文件路径

```
<RUN_DIR>/issues/<issue_id>.md
```

`issue_id` 构造规则（稳定且避免并发同名覆盖）：
- 格式：`<vuln_type_slug>-<location_slug>-<hypothesis_hash8>`
- `location_slug`：suspect.location 路径分隔符和非字母数字字符改为 `-`，保留主要文件名/函数名
- `hypothesis_hash8`：location + hypothesis + domain 三者组合取 8 位短 hash
- 已存在同名文件 → 加 `-r2`/`-r3` 后缀，frontmatter 写 `duplicate_candidate_of: <原 issue_id>`

---

## Issue 文件 frontmatter（YAML）

### 必填字段（discovery 阶段由 unit_reviewer 写入）

| 字段 | 类型 | 值约束 |
|---|---|---|
| `issue_id` | string | 同文件名 stem |
| `title` | string | 一句话漏洞摘要，供 findings.json 直用；缺失则 final_reporter 用 H1 兜底并标注 |
| `canonical` | bool | discovery 时默认 `true`，去重阶段（`merge_dedup.py`）可改 `false` |
| `discovery_verdict` | enum | `confirmed` \| `escalate` \| `refuted` \| `blocked` |
| `discovery_category` | array | 类别数组，如 `[authn]` 或 `[authn, business_logic]` |
| `source_pass` | enum | 产出该 issue 的来路（下游按它过滤/归类，**必填**）：`unit_review`（发现+覆盖阶段的逐单元审查，含补审；authn 兄弟端点 / prescan suspect 转正的 issue 也统一填此值） |
| `discovery_at` | string | ISO8601 timestamp |
| `primary_location` | string | `path:line` 形式 |
| `primary_symbol` | string | 该 location 所属的函数/方法限定名（如 `WalletService.get_balance`），读源码确定；模块级/无法确定时填 `""`。这是**去重的稳定锚**——见下方"去重 key 规范" |
| `suspect_hypothesis` | string | 攻击假设摘要 |
| `vuln_type` | string | `IDOR` / `权限绕过` / `注入` / `SSRF` / ...（自由文本，仅供人读；**不参与去重**） |
| `cwe` | string | CWE 标识，格式 `"CWE-<number>"`（如 `"CWE-639"`、`"CWE-89"`）。**去重的决定性 discriminator**——同一位置若同时存在多个独立 CWE（例如 IDOR + Mass Assignment + SQLi），必须拆成多条 issue、每条填独立 CWE。取值来源：优先看 `AUDIT_SKILLS/rules/*.md` 顶部 frontmatter 的 `tags` 里的 `cwe-<n>`；命中多个 CWE 时选与本 issue 攻击路径最直接对应的那个（不是最上位的）；确实无对应规则/无法判定时填 `"CWE-UNKNOWN"`（**UNKNOWN 视为唯一 key，永不折叠**——见下方"去重 key 规范"） |
| `severity` | enum | `CRITICAL` \| `HIGH` \| `MEDIUM` \| `LOW` \| `INFO` |
| `affected_entrypoints` | array | `entrypoint_id` 列表；可空 `[]` |
| `authn_level` | enum | 主受影响入口的认证级别：`public` \| `authenticated` \| `privileged` \| `internal`；从 entrypoints/index.jsonl 对应入口读取；无关联入口时填 `authenticated` |
| `duplicate_candidate_of` | string \| null | 同名碰撞时填原 issue_id；否则 null |

### 合并 + 定稿字段（`merge_dedup.py` 写入，report 阶段 coverage_critic 步骤 0 调用）

| 字段 | 类型 | 何时写 |
|---|---|---|
| `duplicate_files` | array | canonical 主 issue 上列其他重复 issue 路径；非 canonical 留 `[]` |
| `superseded_by` | string \| null | 非 canonical 文件指向 canonical 路径 |
| `duplicate_reason` | string \| null | 非 canonical 一句话说明合并依据 |
| `final_verdict` | enum | canonical issue 的最终结论。本流水线**无对抗复核阶段**，`final_verdict = discovery_verdict` 原样落定（`confirmed` \| `escalate` \| `refuted` \| `blocked`） |
| `final_verdict_reason` | string | 一句话说明；无对抗复核时固定为 `no_adversarial_stage` |

### 去重 key 规范（`merge_dedup.py` 等所有去重点的唯一依据）

合并两个 issue **当且仅当其去重 key 相等**。key 按优先级取第一个可用锚，`cwe` 恒为组成部分：

1. `primary_symbol` 非空 → `("sym", norm_symbol, cwe)`
2. 否则 `affected_entrypoints[0]` 非空 → `("ep", norm_endpoint, cwe)`
3. 否则 → `("fl", primary_location 的文件路径, 行号, cwe)`（**保留行号**，见下"保守去重"）

- `cwe` 是**决定性 discriminator**：同一 `primary_symbol`（或 endpoint / file:line）上存在多个独立 CWE 时，key 不相等，各自独立成条——这是本次规范的核心目的，防止同函数的 IDOR + Mass Assignment + SQLi 被误折叠成一条（不同 CWE ≠ 重复）
- `cwe == "CWE-UNKNOWN"` **视为唯一 key，永不与任何其他 issue 折叠**（哪怕另一条也是 UNKNOWN）——UNKNOWN 表示 unit_reviewer 拿不准 CWE，保守起见 recall-safe，宁可留重复也不错合
- **不再使用 `discovery_category[0]` 作为去重维度**（旧规范）：category 是粗桶（只有 8 个），会把同函数的 `authn` 桶下 IDOR 和 Mass Assignment 误合并；`vuln_type` 是自由文本、跨 actor 措辞漂移。CWE 号是标准枚举，既细粒度又稳定
- `norm_symbol` = `primary_symbol` 小写、去除非字母数字下划线、取最后一段（`rsplit('.')[-1]`）——函数/方法名是跨 pass / 跨 actor 改写都稳定的锚，**行号变化或措辞差异都不影响折叠**
- `norm_endpoint` = 路径参数归一（`/x/<id>` 与 `/x/{id}` 视为同一）
- **severity 收敛**：合并后 canonical 的 `severity` 取被合并各 issue 中的**最高**（安全审计保守，避免同一漏洞 1×CRITICAL + 3×HIGH 被取低）
- canonical 选 `primary_symbol` 非空且信息最完整的那条；其余按"合并阶段字段"标记为非 canonical
- **回退到 fl 级时保留行号（保守去重）**：`primary_symbol` 为空（无法静态确定 symbol / 动态调用）时，不同函数的漏洞若只按"同文件 + 同 cwe"会被**误合并**；故第 3 级回退键含行号——宁可同一漏洞因行号不同而轻微重复，也不能把同文件不同函数的两个真漏洞错合成一条（过度合并 = 漏报，比重复更危险）。symbol 锚（第 1 级）才是消除"同函数不同行/不同措辞"重复的主力

> 当前 key：`("sym", norm_symbol, cwe)`——CWE 细粒度 discriminator + symbol 稳定锚，同函数不同 CWE 独立成条，UNKNOWN 不折叠。历史演进见 git log。

---

## Issue 文件正文模板

```markdown
# <漏洞名称>（与 frontmatter title 保持一致）

## 漏洞分析
（引用具体文件路径和行号；写明攻击者如何控制输入、沿途经过哪些函数、最终触达哪个 sink）

## 攻击路径
- confirmed/escalate：端到端可操作步骤
- refuted：说明为什么不成立（指明阻断点的代码行号）
- blocked：列出缺什么运行时信息才能判断

## PoC
- confirmed/escalate：curl 命令或 pytest 脚本框架（不需要真跑通）
- refuted/blocked：N/A

## 修复建议
（refuted 可填"无需修复"，并引用阻断点）
```

---

## 机读旁路 `<RUN_DIR>/work/issue-meta/<issue_id>.json`（unit_reviewer 写）

每写一条 issue `.md`，unit_reviewer **同时**写一份同名 JSON 旁路，字段值与 `.md` frontmatter 完全一致，作为 report 阶段确定性去重脚本 `merge_dedup.py` 的**唯一数据源**（脚本读纯 JSON、不解析 LLM 手写 YAML，稳健性对齐 coverage 的 unit-records）：

```json
{"issue_id":"...","issue_file":"/abs/issues/<issue_id>.md","discovery_verdict":"confirmed","discovery_category":["authn"],"primary_location":"src/api/wallet.py:142","primary_symbol":"WalletService.get_balance","vuln_type":"IDOR","cwe":"CWE-639","severity":"HIGH","authn_level":"authenticated","affected_entrypoints":["http:GET:/wallet/balance"]}
```

只含 discovery 期字段（不含 `canonical`/`duplicate_files`/`final_verdict`——那些由 `merge_dedup.py` 写入 `.md` frontmatter）。`issue_file` 用绝对路径；数组字段缺失填 `[]`，`primary_symbol` 不定填 `""`。

## 索引文件 `<RUN_DIR>/issues/index.jsonl`

由 `merge_dedup.py`（report 阶段 coverage_critic 步骤 0 调用）写，每行一个 canonical issue：

```json
{"issue_id":"idor-wallet-balance-a1b2c3d4","issue_file":"/abs/path/issues/idor-wallet-balance-a1b2c3d4.md","canonical":true,"discovery_verdict":"confirmed","final_verdict":"confirmed","discovery_category":["authn"],"primary_location":"src/api/wallet.py:142","primary_symbol":"WalletService.get_balance","vuln_type":"IDOR","cwe":"CWE-639","severity":"HIGH","authn_level":"authenticated","affected_entrypoints":["http:GET:/wallet/balance"],"duplicate_files":[]}
```

字段映射均直取自 frontmatter；`issue_file` 用绝对路径。`final_verdict` 由 `merge_dedup.py` 落为 `discovery_verdict`（无对抗复核阶段）。

---

## findings.json 字段映射（final_reporter 用）

> **输出分流**：`findings.json` 的 `findings[]` 只含 `final_verdict ∈ {confirmed, escalate, blocked}`（要修 + 要人工看）；
> `final_verdict == refuted` 分流到同目录 `refuted.json`（审计留痕，schema 相同）。
> 两文件的 `summary` 都给全量四桶计数。下表字段映射对两者通用。

`findings[]` 每项：

| findings 字段 | 来源 |
|---|---|
| `issue_id` | index.jsonl 同名 |
| `issue_file` | index.jsonl 绝对路径 |
| `title` | issue frontmatter `title`（缺失用 H1 兜底）|
| `category` | index.jsonl `vuln_type` |
| `cwe` | index.jsonl `cwe`（格式 `"CWE-<n>"` 或 `"CWE-UNKNOWN"`） |
| `entry` | `affected_entrypoints[0]` 归一化：`http:GET:/foo`→`GET /foo`、`celery:task:foo`→`Celery foo`、空→`""` |
| `file` | `primary_location` 拆 `:` 取 path |
| `line` | `primary_location` 拆 `:` 取 line，无填 `0` |
| `severity` | index.jsonl `severity`（合并阶段已取被合并各 issue 中的最高值） |
| `status` | index.jsonl `final_verdict` |
| `final_verdict_reason` | issue frontmatter 同名（无对抗复核时为 `no_adversarial_stage`） |
| `authn_level` | issue frontmatter `authn_level` |

排序：`severity DESC`（CRITICAL > HIGH > MEDIUM > LOW > INFO），同级按 `status`（confirmed > escalate > blocked > refuted）。

---

## 写入规则（不变量）

1. **任何 verdict 都写 issue 文件**（含 refuted/blocked）—— 保留完整审计留痕
2. **不删除、不移动任何 issue 文件**，重复条目通过 frontmatter 标记
3. **`issues/index.jsonl` 是 canonical issue 的 source of truth**，其他 actor 不直接改 issue frontmatter 后再读 index，必须重生成 index
4. **`findings.json` 仅由 final_reporter 生成**
