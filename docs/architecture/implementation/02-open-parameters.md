# 02 — Open Parameters

`ARCHAEOLOGY EVIDENCE`：参考项目没有提供可移植的 durable Attempt、epoch、artifact trust、通用 receipt/compensation 或 isolation taxonomy。以下选择只冻结 MVP 所需最小语义；未列入的细节继续开放。

## MUST FREEZE BEFORE IMPLEMENTATION

| Parameter | Why needed now | Minimum viable decision | Configurable later | Must remain undecided now |
|---|---|---|---|---|
| Attempt timeout | 否则 stuck Attempt 无法归因，lease 也没有失效边界。 | 先定义 timeout 是 observation 触发器；超时且事实不足进入 `UNKNOWN`，不自动 `FAILED`。数值按 deployment policy 注入。 | duration、heartbeat cadence、grace period。 | 不冻结统一业务数值与 provider-specific SLA。 |
| Attempt lease | fencing 需要区分当前 owner 与 stale owner。 | lease 具有 owner、expiry、单调 fencing token；过期 writer 只能记录 stale observation。 | lease duration、renew cadence、reaper interval。 | 不冻结实现使用 DB lease、CAS 还是外部 coordinator。 |
| Binding epoch numbering | Attempt 与 epoch 的 immutable 关联必须可排序、可审计。 | 使用同一 Binding 下单调递增逻辑序号，并以不可变 `epoch_id` 作为主 identity；禁止复用。 | 外部展示格式、存储编码。 | 不冻结跨 Binding 的全局序号。 |
| Artifact digest | provenance 不能证明 bytes 未被替换。 | artifact 参与 trust/recovery 时必须有 cryptographic digest；digest mismatch 阻断消费。 | algorithm agility、manifest encoding。 | 不冻结具体算法、仓库或 content-addressed layout。 |
| Artifact trust anchor | digest 只证明内容，不证明来源/授权。 | MVP 至少需要 Runtime policy 指向一个可验证 anchor（immutable snapshot 或受信 metadata）；缺失则 `UNTRUSTED`，不得消费。 | signed metadata、attestation、不同 artifact class 的组合。 | 不冻结 provider-specific attestation 格式。 |
| Receipt semantics | UNKNOWN recovery 不能把 tool result 当 side-effect proof。 | receipt 是 operation-correlated observation；默认“不足以证明 effect”，除非 policy 明确其 source/trust。 | per-tool receipt schema、retention。 | 不冻结通用 receipt payload 或 exactly-once。 |
| Verification timeout | RESOLVING 不能无限等待。 | verification 有 deadline；超时保留 UNKNOWN/人工 gate，不得盲重试。 | deadline、probe freshness、backoff。 | 不冻结所有 tool class 的 probe SLA。 |
| Compensation behavior | 外部副作用不能由“重启”隐式撤销。 | 默认不自动 compensation；只有 adapter 声明 capability、Runtime policy 授权且结果可验证时才调度。 | budgets、approval、tool-class policy。 | 不冻结通用 undo protocol。 |
| Isolation policy | admission 前必须知道执行边界，且不能把 process 当 tenant isolation。 | MVP 持久化 policy snapshot，至少覆盖 process/workspace/network/credential/tenant/tool；缺失维度默认拒绝 admission。 | policy catalog、attestation、选择矩阵。 | 不冻结 Level 0…N taxonomy 或具体 sandbox 技术。 |
| Concurrency fencing | duplicate/stale writers 会破坏 state machine 与历史事实。 | 每次 transition/reconcile 使用 expected version + fencing token；冲突拒绝并重新读取；terminal/epoch immutable。 | lock/queue/CAS 实现、分片策略。 | 不冻结全局吞吐与跨资源事务方案。 |

## DEFERRED

- partial-success / multi-output Run outcome。
- human-gate UX、审批角色与 escalation workflow。
- receipt、event、observation 的长期 retention 与 compaction。
- compensation budget、retry backoff、全局 retry quota。
- artifact replacement window、rollback UX 与跨 store copy semantics。
- multi-region、workflow replacement、provider optimization、UI、billing。

Deferred 不得改变 `UNKNOWN != FAILURE`、Attempt identity 不复用、epoch immutable、artifact trust 先于消费、以及旧 fence 不可写入这些既有不变量。
