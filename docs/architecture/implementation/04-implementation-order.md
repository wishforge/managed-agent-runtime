# 04 — Implementation Order

## Dependency chain

`DESIGN DECISION`：Run、Attempt、immutable Binding Epoch、Extension facts、Recovery、Artifact trust、Supervisor 的 ownership 与边界已冻结。`IMPLEMENTATION DECISION`：按这些语义依赖实现，不按 API/CRD/controller 的表面层次倒置顺序。

```text
Run
  ↓ owns lineage and Attempt set
Attempt
  ↓ fixes one immutable Binding Epoch
Binding Epoch
  ↓ authorizes one execution boundary
Execution Extension
  ↓ reports attributed observations
Observation
  ↓ supplies facts, not verdicts
UNKNOWN / Recovery
  ↓ verifies before retry or compensation
Artifact
  ↓ records provenance/integrity/trust
Supervisor
  ↓ reconciles all durable state and facts
```

## Ordered decisions

1. **Run first**：没有稳定 Run identity，Attempt lineage、recovery history 和最终 outcome 无法归属。
2. **Attempt second**：先冻结独立 execution boundary 与 state machine，才能区分 transport retry、managed retry 和 crash UNKNOWN。
3. **Binding Epoch third**：Attempt 创建时必须固定执行语义 snapshot；否则 provider/session/capability/isolation mutation 会污染 provenance。
4. **Concurrency/fencing with M1**：fence 不是后补的数据库优化，而是 identity/state semantics 的一部分；必须与 durable transition 一起实现。
5. **Execution Extension fourth**：adapter 只能在 Run/Attempt/epoch 已存在后报告可归因 facts；否则 start/observe 无法安全落账。
6. **UNKNOWN/Recovery fifth**：Recovery 依赖 Attempt state machine、epoch boundary 与 durable observations；在此之前 retry 会把未知副作用误当成未发生。
7. **Artifact sixth**：先有 producing Attempt/epoch provenance，再加 digest/trust；不能先建“可信 artifact”而没有来源链。
8. **Supervisor last**：Supervisor 是这些 durable facts 的 reconciliation consumer；先做它会把 controller/loop 变成事实 owner，违反 boundary。

## First production slice

第一批只实现 M1：`Run + Attempt + Binding Epoch + state machine + durable version/fencing`。用 in-memory 或现有 persistence seam 做语义验证即可，不提前引入 API、CRD、DB migration 或真实 provider。

## Explicitly rejected orders

- 不先做 Supervisor：没有 durable state model，它只能猜测 live process。
- 不先做 Artifact trust：没有 provenance，digest 只能证明 bytes，不能证明来源。
- 不先做 Recovery：没有 Attempt state machine，UNKNOWN 无法落在正确边界。
- 不把 Codex/Claude/Pi adapter 与 M1 捆绑：provider facts 不应决定核心 semantics。
