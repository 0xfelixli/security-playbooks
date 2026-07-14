# 审查/深挖标准纪律（每次审查都必须遵守，不因具体任务而改变）

作为 security-audit 的代码审查/深挖 actor，以下纪律对**每一次**审查强制适用，不因具体任务而改变。开工前先读完本文件建立判断基准，再动手。

## 开工前必读（建立判断基准，再动手）
- Read `AUDIT_SKILLS/guides/false-positive-traps.md`：建立"哪些情况**不能**作为否决（refuted）理由"的基准。
- Read `AUDIT_SKILLS/guides/baseline-calibration.md`：判误报时用同类成熟系统做外部对标校准。注意两点——「符合业界写法」**不能单独**作为 `refuted` 理由；它同时是你判断 severity 定级与 `escalate`（severity 被低估时上调）的依据。

## 选 `refuted` 的门槛（recall-safe，门槛极高）
把某个 suspect 判为 `refuted` 前，**必须全部满足**，否则一律选 `blocked`（留待人工复核，不直接杀）：
1. 已追踪**所有**调用路径——读文件逐层上溯所有调用者，确认攻击路径在**所有入口**上都不可达或有完整防护；
2. 防护在**危险操作之前**生效（不是操作后才校验）；
3. 防护检查了**资源归属**，而非只检查"已登录"。

## verdict 写盘纪律
**任何 verdict（含 `refuted` / `blocked`）都必须写 issue 文件**——保留完整审计留痕，不得因"判了否决"就不落档。
