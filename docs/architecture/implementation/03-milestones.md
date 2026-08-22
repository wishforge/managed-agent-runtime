# 03 — Milestones

每个 milestone 都有独立语义验收；后一个 milestone 不得用未完成的前一个 milestone 的隐式状态替代 durable contract。

`DESIGN DECISION`：既有 core-runtime/implementation-design 的 invariant 与 ownership 不在 milestone 中重定义。`IMPLEMENTATION DECISION`：以下按最小可验证增量拆分。

## M1 — Durable Execution Core

**范围**：Run identity、Attempt identity、Binding Epoch identity/snapshot、Attempt state machine、durable transition history、expected-version 与 fencing token。

**验收**：能创建 Run→Attempt→epoch；合法 transition 成功；非法 transition、terminal 回退、旧 epoch admission、stale writer 均被拒绝；runtime restart 后可重建 semantic state。

**不包含**：真实 provider、REST、CRD、migration、Supervisor loop。

## M2 — Binding / Execution Extension

**范围**：Binding admission 与 immutable epoch freeze；最小 adapter contract：`start / observe / terminate / inspect`；可归因 execution observations。

**验收**：start 只从已 admission 的 epoch 发出；observation 必须带 Run/Attempt/epoch correlation；disconnect/handle loss 进入事实记录，不直接写成功。

## M3 — Recovery

**范围**：`UNKNOWN`、`RESOLVING`、verification record、receipt reference、recovery decision、新 Attempt lineage、termination decision。

**验收**：process/session/transport loss 不会把 UNKNOWN 改为 FAILURE；重启后 UNKNOWN 保留；无验证证据时禁止 blind retry；验证后可安全 terminal 或创建新 Attempt。

## M4 — Artifact

**范围**：artifact identity/provenance、digest calculation/verification、replacement detection、minimum trust decision。

**验收**：Artifact 能追溯到 producing Attempt/epoch；digest mismatch 或 provenance 不完整阻断消费；artifact restore 不被记录为 world-state compensation。

## M5 — Supervisor

**范围**：reconciliation loop、stale detection、recovery orchestration、termination、有限重试/清理预算。

**验收**：Supervisor 只基于 durable state + facts 作决定；stale supervisor 被 fence；能安排 verify/new Attempt/terminate，不能覆盖旧 identity 或伪造 outcome。

## Milestone gate rule

M1 是第一批 production implementation 的唯一前置；M2–M5 可在 M1 上逐步接入。任何 milestone 若发现语义不变量需要改变，必须回到 `06-implementation-gate.md`，不能在代码中偷偷扩展语义。
