# Managed Agent Runtime Implementation Planning

本目录把既有 Runtime semantics 切成可控、可验证的实施路线。它是 implementation planning，不是生产代码、REST API、CRD、数据库 migration 或 controller 实现。

## Source and evidence boundary

- `ARCHAEOLOGY EVIDENCE`：来自 `docs/archaeology/execution-extension-synthesis/`，只说明已有项目观察到的 execution primitives、局部恢复能力与负面证据。
- `DESIGN DECISION`：来自 `docs/architecture/execution-extension/`，是 Managed Runtime 的规范性语义与 ownership。
- `OPEN PARAMETER`：不改变既有 invariant 的实现前选择。
- `IMPLEMENTATION DECISION`：本阶段为第一批实现选择的范围、顺序和验证方式。

## Deliverables

1. [01-scope.md](01-scope.md) — MVP 边界。
2. [02-open-parameters.md](02-open-parameters.md) — 必须冻结与延后参数。
3. [03-milestones.md](03-milestones.md) — 最小里程碑。
4. [04-implementation-order.md](04-implementation-order.md) — 依赖顺序。
5. [05-test-strategy.md](05-test-strategy.md) — 语义测试策略。
6. [06-implementation-gate.md](06-implementation-gate.md) — 第一批 production implementation gate。
7. [07-m1-m2-m3-boundary.md](07-m1-m2-m3-boundary.md) — M1 durable substrate、M2 execution facts、M3 recovery decision 的冻结边界。

## Phase 7 outcome

```text
READY FOR IMPLEMENTATION
```

该结论只授权开始最小 Durable Execution Core；不授权同时实现 provider adapters、artifact platform、Supervisor controller 或外部接口。
