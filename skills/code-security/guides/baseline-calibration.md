# Baseline 校准（同类对标）

判"算不算漏洞"和"定 severity"时，除了看代码本身，先建立一个**外部参照系**：
同类成熟系统在同样场景下是怎么做的。给主观判断一个客观锚点。

## 怎么用（3 步）

1. **命名 1-2 个真实同类参照**（如 Stripe / Django REST Framework / Kubernetes /
   主流 OAuth/OIDC 库），而不是泛泛地说"业界一般"。参照要和目标的领域、信任模型可比。
2. **判断目标是【符合】还是【偏离】参照的标准做法**：
   - **偏离** → 真问题的强信号，severity **不因"少见"而降**。
   - **符合** → 倾向不报，但见下方排除项——符合 ≠ 一定安全。
3. **查这个 pattern 有没有公开利用先例 / 对应 CVE 类别**
   （如 `pickle`/`yaml.load` 反序列化、裸 `redirect`/`next` 开放重定向、ECB 模式、
   JWT `alg=none`、签名不校验等）。

## 关键规则（反直觉）

- **有 CVE / 被公开利用过的 pattern = 更强证据，不是"太常见所以没事"**。
  很多真实漏洞恰恰源于流行的错误写法。此时 severity **不降级**；
  若发现影响比原假设更重，在 discovery 阶段用 `escalate`、在 challenger 阶段用
  `UPGRADED` 上调（两个阶段都需具体代码行号证据）。
- severity 的**源头与上调**只在 discovery（`unit_reviewer` 写 `severity` / `escalate`）
  与 challenger（`UPGRADED`）两处发生；其余阶段不改 severity。

## 排除（不能拿 baseline 当否决真漏洞的借口）

- **"业界都这么写" 不能单独作为 `refuted` / `REFUTED` 理由**——见上方，流行写法照样有 CVE。
  否决真漏洞必须有"该路径上存在有效防护或不可达"的具体代码行证据。
- 参照系符合，但目标的**信任边界 / 部署模型不同**（如同一接口在目标里对公网暴露、
  参照里只在内网）→ 仍需独立判断，不能直接套用参照结论。
- 与 `false-positive-traps.md` 冲突时，以后者列出的"不可作为否决理由的场景"为准。
