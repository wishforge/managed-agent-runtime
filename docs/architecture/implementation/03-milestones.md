# 03 — Milestones

每个 milestone 都有独立语义验收；后一个 milestone 不得用未完成的前一个 milestone 的隐式状态替代 durable contract。

`DESIGN DECISION`：既有 core-runtime/implementation-design 的 invariant 与 ownership 不在 milestone 中重定义。`IMPLEMENTATION DECISION`：以下按最小可验证增量拆分。

## M1 — Durable Semantic Substrate

**范围**：Run identity、Attempt identity、Binding Epoch identity/snapshot、Attempt state machine、durable transition history、expected-version 与 fencing token；以及 durable `UNKNOWN`、`UnknownEvidence`、`RESOLVING` fact 和 recovery fact history。

**验收**：能创建 Run→Attempt→epoch；合法 transition 成功；非法 transition、terminal 回退、旧 epoch admission、stale writer 均被拒绝；带证据的 `UNKNOWN` 与 `UNKNOWN → RESOLVING` fact 可持久化；runtime restart 后可重建 semantic state。

**不包含**：真实 provider、REST、CRD、migration、Execution Extension adapter、verification、retry/compensation/termination policy、Supervisor loop。

## M2 — Execution Extension

**范围**：消费 M1 已 admission 的 immutable epoch；最小 adapter contract：`start / observe / terminate / inspect`；execution handle 与可归因 execution observations。

**验收**：start 只从 M1 已 admission 的 epoch 发出；observation 必须带 Run/Attempt/epoch correlation；disconnect/handle loss 进入事实记录，不直接写成功；adapter 不拥有 durable Attempt 或 outcome。

## M3 — Recovery Decision

**范围**：消费 M1 的 `UNKNOWN`/`RESOLVING` facts 与 M2 execution facts，产出 verification request/result、receipt interpretation、recovery decision、retry admission、新 Attempt lineage、compensation decision、termination decision 及其 durable decision record。

**验收**：process/session/transport loss 的事实不会把 `UNKNOWN` 改为 `FAILURE`；无验证证据时禁止 blind retry；验证后可安全 terminal 或创建新 Attempt；M3 不成为 live executor，且所有 state/lineage 变更仍通过 M1 语义与 fence。

## M4 — Artifact

**范围**：artifact identity/provenance、digest calculation/verification、replacement detection、minimum trust decision。

**验收**：Artifact 能追溯到 producing Attempt/epoch；digest mismatch 或 provenance 不完整阻断消费；artifact restore 不被记录为 world-state compensation。

## M5 — Supervisor

**范围**：reconciliation loop、stale detection、recovery/termination orchestration、有限重试/清理预算。

**验收**：Supervisor 只基于 durable state + facts 以及 M3 已记录 decision 编排 action；stale supervisor 被 fence；能安排 verify/new Attempt/terminate，不能自行生成 recovery verdict、覆盖旧 identity 或伪造 outcome。

## Milestone gate rule

M1 是第一批 production implementation 的唯一前置；M2–M5 可在 M1 上逐步接入。任何 milestone 若发现语义不变量需要改变，必须回到 `06-implementation-gate.md`，不能在代码中偷偷扩展语义。
