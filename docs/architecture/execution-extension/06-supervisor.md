# 06 — Supervisor

Supervisor 与 Execution Extension 的边界是：

```text
Execution Extension: 执行 live primitives
Supervisor: 观察 durable state，修复 desired/actual 不一致
```

## Reconciliation loop

```text
observe durable state + execution facts
        ↓
detect drift / missing fact / stale handle
        ↓
submit facts to / consume decision from M3
        ↓
orchestrate admitted M1 transition and M2 live action
```

Supervisor 负责 reconciliation，并编排已由 M3 决定的 restart、UNKNOWN resolution、compensation 与 termination action；它遵守 retry、cleanup、人工审批预算，不自行改写 decision semantics。

这里的 `UNKNOWN resolution` 是控制面上的 reconciliation/orchestration；恢复
事实由 M1 持久化，verification、receipt interpretation 与 recovery policy
decision 属于 M3。Supervisor 不因此成为 live executor，也不绕过 M1 的
transition/fence 规则。

## Cases

- **process crash**：确认进程事实；无法确认副作用时保留 UNKNOWN，不直接重放。
- **session disconnect**：区分 transport 断开与 session/Attempt 终止；按 Binding epoch 规则恢复或新建 Attempt。
- **event loss**：以 durable checkpoints、receipt 或 verification 补事实；缺失时标为 UNKNOWN。
- **UNKNOWN**：先 verification，再按副作用分类选择新 Attempt、人工 gate、compensation 或终止。
- **stuck Attempt**：基于 lease/heartbeat/timeout 等 Runtime policy 重新归因，不能只看 live process。
- **stale binding**：拒绝继续使用旧 epoch，迁移到新 Attempt 或终止。
- **artifact inconsistency**：阻断消费，进入 trust verification/replacement/rollback 流程。

Supervisor 不拥有 Provider 的执行实现，也不把“进程已重启”当作“Run 已恢复”。
