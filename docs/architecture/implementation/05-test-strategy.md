# 05 — Test Strategy

测试验证 semantic contract，不验证某个 API、数据库或 provider 的偶然实现。每项测试都应能在 runtime restart、重复 command 或丢失 live handle 后重放。

`DESIGN DECISION`：测试对象是 durable semantic facts 与 invariants。`IMPLEMENTATION DECISION`：先用最小 unit/restart/contract-fake checks 验证 M1，再逐 milestone 接入真实 adapter/store。

## Identity

- Run identity 在 retry/resume/recovery 后稳定。
- Attempt identity 在 transition、reconnect、process restart 后稳定；managed retry/resume 产生新 identity。
- Binding Epoch identity 与 snapshot immutable；Attempt 恰引用一个 epoch，跨 epoch 必须新 Attempt。

## Lifecycle

- 覆盖所有 valid transitions：`PENDING/STARTING/RUNNING/WAITING/UNKNOWN/RESOLVING` 到允许的 terminal 或新 Attempt decision。
- 覆盖 invalid transitions：terminal 回 active、跨 epoch observation、未 admission 直接 start、未 resolve UNKNOWN 直接 retry。
- terminal state protection：旧 Attempt 的结果、receipt、UNKNOWN history 不被新 Attempt 覆盖。

## Crash and restart

- extension process loss、session loss、transport loss 分别产生 observation；证据不足均为 UNKNOWN。
- runtime restart/controller restart 后 UNKNOWN、epoch、transition history 可重建。
- 有连续性证据时允许 observation recovery；无证据时不能伪造 RUNNING 或 SUCCESS。

## UNKNOWN

- 明确断言 `UNKNOWN != FAILURE` 且 `UNKNOWN != SUCCESS`。
- unresolved side effect 上 blind retry 被拒绝。
- verification 成功、verification timeout、无 probe/receipt、compensation 不可用分别走不同 decision。
- 新 Attempt 与旧 UNKNOWN 通过 recovery lineage 关联，旧事实保留。

## Concurrency and fencing

- duplicate command 返回同一 operation/result，不创建重复 Attempt。
- stale writer、stale supervisor、旧 epoch writer 的 token/version 校验失败，只能追加 stale observation。
- concurrent transition 只有一个获胜；输者重新读取，不覆盖 terminal/UNKNOWN。
- cancel 与 retry race 按 Runtime transition guard 排序，旧 retry 不得重新 admission。

## Artifact

- provenance 能沿 Run→Attempt→epoch→Extension observation 追踪。
- digest mismatch、读取时 replacement、缺失 provenance、未满足 trust anchor 均阻断消费。
- trust verdict 与 integrity evidence 分开；artifact restore 不改变 side-effect fact。

## Recovery and Supervisor

- verification、receipt、compensation、new Attempt、termination 的每个 decision 都有 durable append-only record。
- stale detection 能停止旧 epoch admission；Supervisor 不能 mutate identity。
- recovery failure 有有限出口（继续 resolving、人工 gate 或 terminal），不会无限隐式重试。

## Minimal verification levels

1. **M1 unit/property checks**：纯 state transition、identity、version/fence invariants。
2. **restart checks**：持久化后重建，注入丢失 handle/重复消息。
3. **contract fakes**：fake Extension、fake verifier、fake receipt source，只验证 boundary，不模拟真实 provider。
4. **integration later**：M2–M5 完成后再接真实 adapter/store；不能用 integration 通过掩盖 M1 semantic failure。
