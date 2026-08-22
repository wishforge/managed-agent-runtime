# 01 — MVP Scope

## Scope rule

`ARCHAEOLOGY EVIDENCE` 证明的是 process/session/transport/tool/event 等可复用 primitive，不是 durable Run/Attempt contract。`DESIGN DECISION` 已将 durable identity、state attribution、epoch、trust、recovery 与 reconciliation 放在 Managed Runtime。`IMPLEMENTATION DECISION` 因此先实现语义核心，再接执行与控制面。

## In scope

第一版 Managed Agent Runtime 必须能：

- 创建稳定的 **Run** identity，保存 logical execution intent 与 lineage。
- 创建稳定的 **Attempt** identity，并保证每个 Attempt 恰属于一个 Run。
- 创建不可变的 **Binding Epoch**，每个 Attempt 恰引用一个 epoch。
- 持久化 Runtime semantic state、transition history、outcome 与必要 observation。
- 执行 Attempt state machine：`PENDING → STARTING → RUNNING/WAITING → terminal`，证据不足进入 `UNKNOWN → RESOLVING`。
- 以版本/epoch fence 防止 duplicate command、stale writer、stale supervisor 和旧 epoch admission。
- 通过最小 **Execution Extension adapter** 接入 `start / observe / terminate / inspect`，只接收可归因 facts，不让 adapter 拥有 durable semantics。
- 保留 `UNKNOWN` 及其原因；重启后可重建并进入 recovery，而不是把 UNKNOWN 改写成 FAILURE。
- 支持 recovery 的最小 durable record：verification request/result、receipt reference、decision 与新 Attempt lineage。
- 为 Artifact 保存最小 provenance、integrity evidence 与 trust verdict；不实现通用 artifact store。
- 提供 Supervisor reconciliation 的语义入口：stale detection、verification、new Attempt、termination；执行编排可先是最小实现。

## Out of scope

- multi-region 与跨 region failover。
- distributed workflow engine replacement。
- advanced compensation framework 或通用 exactly-once side-effect protocol。
- generic artifact storage platform、artifact build system 或跨产品 registry。
- provider-specific optimization、模型路由优化、prompt 优化。
- UI、dashboard、用户体验层。
- billing、quota 产品化与计费控制面。
- 超出必要 tenant/isolation boundary 的 tenant control plane。
- REST API、Kubernetes CRD、database migration、controller、SDK 和具体 Codex/Claude/Pi adapter 实现。

## MVP acceptance boundary

MVP 只有在“Run/Attempt/epoch 可持久化、合法状态可推进、非法状态被拒绝、旧 writer 不可覆盖、UNKNOWN 可重建”全部成立后，才算 Core 可用。Extension、Artifact、Supervisor 先以最小 contract/fake 验证，不扩展为完整平台。
