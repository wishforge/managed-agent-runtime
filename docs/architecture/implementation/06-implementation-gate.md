# 06 — Implementation Gate

`DESIGN DECISION`：Gate 只检查既有 semantic model 是否被实现计划正确承接。`OPEN PARAMETER`：带有 implementation parameter 的 gate 必须按 02 文档的最小决定落地，不能在代码中隐式选择。`IMPLEMENTATION DECISION`：本轮最终 gate 为 `READY FOR IMPLEMENTATION`，授权范围仅为 M1。

## Gate A — Run / Attempt semantics frozen

**CLOSED**。`Run` 是 stable logical execution；`Attempt` 是独立 execution boundary；retry/resume 默认新 Attempt；terminal Attempt 不回 active。

## Gate B — Binding Epoch semantics frozen

**CLOSED WITH IMPLEMENTATION PARAMETER**。每个 Attempt 恰引用一个 immutable epoch；跨 semantic mutation 必须新 epoch/new Attempt。编号编码与迁移原子性按 [02-open-parameters.md](02-open-parameters.md) 冻结最小实现选择。

## Gate C — Concurrency / fencing frozen

**CLOSED**。transition version、expected version、lease owner 与 fencing token 是语义要求；旧 writer 只能产生 stale observation，不能覆盖 state。

## Gate D — UNKNOWN recovery contract frozen

**CLOSED WITH IMPLEMENTATION PARAMETER**。`UNKNOWN != FAILURE`；先 verification，再 safe retry、compensation、human gate 或 termination；verification timeout 与 tool-class details 可配置但不能允许 blind retry。

Milestone boundary：M1 持久化 `UNKNOWN`、evidence 与 recovery facts；M3 解释这些事实并作出 recovery decision。

## Gate E — Execution Extension adapter contract frozen

**CLOSED**。adapter 输入 immutable epoch/intent/policy，输出带 correlation 的 execution facts；adapter 不拥有 Run、Attempt、trust 或 recovery verdict。

## Gate F — Minimum artifact trust contract frozen

**CLOSED WITH IMPLEMENTATION PARAMETER**。必须保存 provenance、digest evidence 与 Runtime trust verdict；缺失或 mismatch 阻断消费。具体算法、manifest、anchor implementation 可按 artifact class 延后。

## Gate G — Isolation minimum frozen

**CLOSED WITH IMPLEMENTATION PARAMETER**。MVP 必须持久化并检查 process、workspace、network、credential、tenant、tool 六类 policy；缺失维度默认拒绝 admission。具体 isolation catalog、attestation 与 sandbox 技术延后。

## Final result

```text
READY FOR IMPLEMENTATION
```

理由：核心 semantic ownership、identity、state machine、epoch boundary、UNKNOWN/recovery boundary、adapter boundary、minimum trust/isolation 与 fencing 已足够明确；剩余参数已被显式分类，不再需要把不确定性藏进生产代码。

## First implementation authorization

只授权 M1 Durable Semantic Substrate：Run、Attempt、Binding Epoch、状态机、durable state/history、`UNKNOWN` evidence/recovery facts、并发 fencing 与 semantic tests。M2–M5、REST、CRD、migration、controller、UI 和 provider adapter 等待各自 milestone gate。
