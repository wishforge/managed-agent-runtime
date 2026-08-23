# 09 — M3 Operation Recovery Contract

## Status and governing statements

This document freezes the smallest provider-neutral semantic contract for M3.
It is a documentation-only gate. It does not implement recovery, change M1 or
M2 semantics, define a persistence schema, or authorize provider integration.

> **Operation is a business-semantic action, not a transport request.**

> **Retrying an Operation preserves the same operation identity.**

> **UNKNOWN is an evidence state, not a retry command.**

> **Safe retry requires caller-side operation identity plus called-system idempotency,
> deduplication, queryability, receipt, or trusted verification.**

> **M3 decides recovery; M2 executes live actions; M1 persists durable semantics.**

## 1. M3 purpose

M3 determines what the available durable and live evidence means for one
business Operation. It resolves or preserves uncertainty and records a policy
decision to admit retry, authorize compensation, require a human gate,
terminate recovery, or support a terminal business outcome.

M3 is a decision boundary. A decision may request M2 live work or an M1
transition, but the decision itself neither executes the work nor mutates
durable state.

## 2. Operation semantic model

The model has three distinct levels:

```text
Run (one logical user execution)
└── Attempt (one Runtime execution boundary)
    ├── Operation O1 (one business-semantic action)
    ├── Operation O2
    └── Operation O3
        ├── request R1
        └── retry request R2
```

- A **Run** is the logical user execution and owns its business Operations.
- An **Attempt** is one Runtime execution boundary. It is not a process: one
  Attempt may involve multiple processes, sessions, handles, or requests.
- An **Operation** is one business-semantic action performed within an
  Attempt, such as “create order 42” or “publish artifact A”. One Attempt may
  contain zero, one, or multiple Operations.
- A **request** is one transport or execution invocation for an Operation.
  Retransmission, reconnect, and request retry do not create a new Operation.

The tree shows where an Operation is executed, not exclusive identity
ownership. An Operation belongs to one Run and may be executed by more than one
Attempt when recovery admits a new execution boundary.

## 3. Operation identity

Every Operation has a stable `operation_id` with these invariants:

1. The Runtime/caller assigns or accepts the identity before the first request
   that can cause the business action.
2. Exactly one Run owns the Operation. The identity must not move to another
   Run or be silently rebound to different business intent.
3. Every request, receipt, verification fact, decision, and Attempt association
   used for recovery must be attributable to that Operation, or be marked
   uncorrelated and insufficient for an identity-dependent conclusion.
4. One Attempt may execute multiple Operations.
5. One Operation may have multiple transport requests/retries and may be
   associated with multiple Attempts across recovery.
6. A different business action requires a new `operation_id`, even when it was
   caused by recovery of an earlier Operation.

Operation identity is distinct from Run identity, Attempt identity, execution
handle, request identity, provider receipt identity, and idempotency key.

## 4. SUCCESS / FAILURE / UNKNOWN

M3 uses a three-state business outcome for an Operation:

| Outcome | Required meaning | Example evidence |
|---|---|---|
| `SUCCESS` | Trusted evidence is sufficient under Runtime policy to establish the defined business action completed. | A trusted query finds the created object with the same Operation identity, or an accepted commit receipt proves the required completion. |
| `FAILURE` | Trusted evidence is sufficient under Runtime policy to establish the defined business action failed. | A trusted rejection states that validation failed before the action was admitted, or a query proves the requested state was not created and can no longer be created by the original request. |
| `UNKNOWN` | Current evidence cannot establish either `SUCCESS` or `FAILURE`. | A request timed out after dispatch, a receipt is ambiguous, a handle disappeared, or verification is absent/inconclusive. |

`SUCCESS` and `FAILURE` require business evidence, not merely a successful or
failed adapter call. `FAILURE` does not universally prove that no partial side
effect exists; the evidence and policy must state the scope of the failure.

`UNKNOWN` is not `FAILURE`, is not `SUCCESS`, and is not permission to retry.
Operation outcome is also separate from M1 Attempt state: ending an Attempt or
losing its process does not by itself determine the Operation outcome.

## 5. UNKNOWN recovery flow

The conceptual flow is:

```text
UNKNOWN
   |
   v
verification / query, when available and required
   |
   +------------------+------------------+
   |                  |                  |
   v                  v                  v
SUCCESS            FAILURE            UNKNOWN
                                         |
                                         v
                                Recovery Decision
                                ├── retry admission
                                ├── compensation
                                ├── human gate
                                └── termination
```

Verification is not assumed to exist. When it does not exist, or remains
inconclusive, M3 must preserve `UNKNOWN` and choose only an action permitted for
that uncertainty. Retry is not the default branch.

## 6. Verification contract

Verification is an evidence-producing activity scoped to an Operation. It may:

- query current business state;
- inspect a trusted receipt;
- compare the observed operation identity with the expected `operation_id`;
- invoke a provider- or business-specific probe; or
- collect other evidence explicitly trusted by Runtime policy.

A verification result records facts, source, correlation, time/freshness,
scope, and any limitation or inconclusive result. Verification does not itself
become `SUCCESS` or `FAILURE`; M3 applies the active Runtime policy to decide
whether the returned evidence is sufficient for an outcome or action.

If policy requires verification, retry admission cannot be recorded until the
required verification has completed. A missing, timed-out, stale, or
uncorrelated verifier result remains evidence of uncertainty.

## 7. Receipt semantics

A receipt is evidence issued by a called system or another explicitly trusted
authority. It may attest to acceptance, rejection, commit, deduplication,
current state, or another precisely scoped fact.

Receipt interpretation requires at least its issuer/authority, claim and
scope, operation correlation when available, observation or issue time, and
any trust/freshness limitation. A receipt for “request accepted” is not a
receipt for business completion. A receipt whose Operation identity differs
from the expected identity cannot prove this Operation's outcome.

Receipt presence is not universal proof of `SUCCESS`; receipt absence is not
proof of `FAILURE` or non-execution. Runtime policy decides which receipt
claims are trusted and what they establish.

## 8. Idempotency / deduplication semantics

The following concepts remain separate:

| Concept | Meaning |
|---|---|
| Operation identity | Stable identity of one business action across all executions. |
| Request identity | Identity of one transport/execution invocation; a retry normally has a new request identity. |
| Transport retry | Re-sending or reissuing a request for the same Operation. |
| Idempotency key | A value conveyed to a called system so repeated invocations can have one defined effect; it may encode or map to `operation_id` but is not semantically identical to it. |
| Business deduplication | Called-system behavior that recognizes duplicate business actions and suppresses or returns the existing result. |

Safe retry requires cooperation between the caller and the called system. The
caller/Runtime preserves stable Operation identity and supplies the required
correlation. The called system must provide sufficient idempotency,
deduplication, queryability, receipt, verification, or a policy-approved
combination of those capabilities.

This contract does not claim exactly-once transport or exactly-once execution.
It permits an at-least-once request pattern only when the business effect is
made safe or its outcome can be established under policy.

## 9. Retry admission

Retry admission is a durable M3 decision about whether another request for the
same Operation may be executed. It is not an Operation, request, or M2
primitive.

A retry may be admitted only when all of the following hold:

- the same `operation_id` and unchanged business intent will be preserved;
- recovery policy permits retry for this Operation and evidence state;
- known evidence does not establish `SUCCESS` or another unsafe duplicate;
- the called system's idempotency, deduplication, queryability, receipt, or
  verification capability is sufficient for that policy; and
- every verification required by policy has completed.

Admission records whether execution stays in the current Attempt or requires a
new Attempt. The resulting request gets its own request identity while retaining
the Operation identity.

Retry is forbidden when any required condition above is false, including when:

- Operation identity or business intent cannot be preserved;
- `SUCCESS` is already established;
- a duplicate effect may be unsafe and protection or trusted verification is
  insufficient;
- required verification is pending, stale, failed, or inconclusive;
- the Operation or active policy is non-retryable;
- evidence is correlated to another Operation or cannot be attributed safely;
- compensation or a human gate is required before any further execution; or
- the relevant Run/Attempt/epoch admission or fence rules reject execution.

## 10. Attempt vs Operation relationship

Attempt identity and Operation identity never collapse:

- **Retry the same Operation:** preserve `operation_id`; create a new request
  identity; remain in the current Attempt only if M2 execution-boundary
  continuity and Runtime policy permit it.
- **Create a new Attempt:** allocate a new `attempt_id` under M1 rules and
  record lineage to the prior Attempt. The new Attempt may execute the same
  Operation with the same `operation_id`.
- **Create a new Operation:** allocate a new `operation_id` because the
  business action is different. Sharing a Run, Attempt, payload, or provider
  does not make two business actions the same Operation.

A process/session/handle change does not automatically create a new Attempt.
Conversely, a new Attempt does not create a new business Operation merely
because the execution process changed. M3 decides whether recovery should
request a new Attempt; M1 remains the authority that creates and persists it.

## 11. Compensation

Compensation is a conditional recovery action intended to counter or reconcile
an earlier business effect. It is allowed only when:

- the called system declares a meaningful compensation capability;
- policy explicitly authorizes its use for the Operation and evidence state;
- evidence is sufficient to justify the compensation without creating an
  unsafe second effect; and
- the decision and resulting lineage are durably recorded before execution.

Compensation is itself a different business action and therefore uses a new
Operation identity linked to the original Operation. Its own outcome may be
`SUCCESS`, `FAILURE`, or `UNKNOWN`.

Not every Operation is compensatable. Terminating a process, session, Attempt,
or recovery loop does not compensate an external side effect.

## 12. Human gate

M3 requires a human gate when policy cannot safely automate a decision from
the available evidence, especially for unresolved `UNKNOWN` with material or
irreversible duplicate/compensation risk.

The gate records the question, evidence presented, permitted choices, policy
basis, and the authorized human decision. Waiting for or applying that decision
does not erase the prior `UNKNOWN`. Human gate is an M3 recovery decision, not
an Execution Extension primitive and not a Supervisor-owned verdict.

## 13. Termination

Termination has four separate meanings:

| Meaning | Contract |
|---|---|
| Terminate live execution | M2 best-effort stop/cancel/cleanup against a handle; returns facts only. |
| Terminate Attempt | An M1 state transition requested under policy, evidence, version, and fence rules. |
| Terminate Operation recovery | M3 decides that no further automated or human recovery action will be admitted under the active policy; the Operation may remain `UNKNOWN`. |
| Terminal business outcome | `SUCCESS` or `FAILURE` established by sufficient accepted evidence. |

M2 `terminate()` does not imply an M3 verdict, an M1 terminal transition, an
Operation outcome, or compensation. Stopping recovery is not permission to
rewrite unresolved uncertainty as `FAILURE`.

## 14. Durable decision record semantics

Each M3 decision must durably preserve, at semantic level:

- the `operation_id`, owning `run_id`, relevant `attempt_id`, and any prior/new
  Attempt lineage;
- immutable references or snapshots for the input facts/evidence, including
  source, correlation, time/freshness, scope, and trust limitation;
- verification activity and its result, or the explicit fact that no trusted
  verification capability exists;
- the decision: accepted Operation outcome or recovery action/admission;
- the policy identifier/version and the rule or basis applied;
- the resulting action, denial, admission constraints, or human gate;
- actor/authority and decision time; and
- later execution/result evidence as linked facts, without rewriting the
  original decision.

Records are append-only audit facts. A later decision supersedes by lineage; it
does not delete or mutate the evidence and policy basis of an earlier decision.
This section defines required meaning, not tables, fields, serialization, or an
API.

## 15. M3 ownership

M3 owns:

- Operation outcome interpretation (`SUCCESS`, `FAILURE`, `UNKNOWN`);
- verification requests and interpretation of verification facts;
- receipt trust and interpretation under Runtime policy;
- retry admission or denial;
- the decision to request a new Attempt and its recovery lineage;
- compensation admission;
- human-gate decisions;
- recovery-termination and terminal-outcome decisions; and
- the semantic content of durable recovery decision records.

## 16. M3 non-ownership

M3 does not own:

- process, session, transport, tool, workspace, or provider execution;
- `ExecutionHandle` allocation or lifecycle;
- M2 observation production or provider capability implementation;
- direct M1 state transitions, Attempt creation, persistence mechanics,
  version checks, or fencing;
- Supervisor reconciliation/orchestration;
- generation of provider receipts or business facts; or
- real Codex, Claude, Pi, or other provider APIs.

M3 decides what should happen. M2 performs admitted live execution. M1
persists the durable semantic state and records through its authority boundary.

## 17. M2 → M3 input mapping

M2 facts remain evidence and gain Operation meaning only through trusted
correlation with Runtime-owned Operation context. The existing M2
`(run_id, attempt_id, epoch_id)` correlation is preserved; this M3 contract
does not add fields or authority to M2. An opaque request/operation reference,
receipt, or M1 admission/decision context may supply the Operation association.
If that association cannot be established, M3 must not guess an `operation_id`.

| M2 input | M3 interpretation boundary |
|---|---|
| `started`, `running`, `waiting` | Evidence that a live boundary reached a phase; not Operation success. |
| `output_event`, `tool_result` | Candidate result, receipt, operation-reference, or probe evidence; trust and business meaning remain undecided. |
| `disconnected`, timeout, event gap | Evidence of an observation boundary that may produce or preserve `UNKNOWN`; never retry admission by itself. |
| `inspect_result` | Freshness-qualified live/stale/not-found/terminated facts; not proof of side-effect absence. |
| `terminated`, cancellation, cleanup facts | Evidence about live stop/exit scope; not compensation or a business outcome. |
| `error` | Scoped execution/provider/tool error evidence; not automatically Operation `FAILURE`. |
| handle identity/change | Live-reference correlation only; never Operation or Attempt lineage by itself. |

M3 combines these M2 facts with M1 Run/Attempt/epoch state, durable `UNKNOWN`
evidence, recovery history, Operation context, prior decisions, policy, and any
trusted business verification.

## 18. Valid / invalid recovery examples

### Valid

- “Create order” times out after dispatch. The Runtime preserves the same
  `operation_id`, queries by that identity, accepts a matching committed order
  as `SUCCESS`, and records no retry admission.
- A called system returns a trusted dedup receipt for the same Operation. M3
  accepts the receipt under policy and records `SUCCESS` without another
  business action.
- Verification proves the first request was rejected before admission. Policy
  admits a new request in a new Attempt with the same `operation_id` and a new
  request identity.
- No query, receipt, or idempotency capability exists for an irreversible
  action. M3 preserves `UNKNOWN` and records a human gate or recovery
  termination instead of retrying.
- Policy authorizes compensation from sufficient evidence. M3 records a new
  compensation Operation linked to the original before asking M2 to execute it.

### Invalid

- Treating an HTTP retry, provider SDK retry, or new process as a new Operation.
- Generating a new `operation_id` to avoid a called system's deduplication.
- Translating timeout, disconnect, missing handle, or M2 `terminate()` into
  Operation `FAILURE`.
- Retrying unresolved `UNKNOWN` because verification is unavailable.
- Calling a receipt `SUCCESS` without checking its claim, authority, scope,
  freshness, and Operation correlation under policy.
- Reusing the original `operation_id` for compensation, which is a different
  business action.
- Letting M3 write M1 state directly or letting M2/Supervisor invent the
  recovery verdict.

## 19. M3 acceptance gate

M3 is **READY FOR IMPLEMENTATION** only when this document is the semantic
source of truth and implementation can prove all of the following without
changing frozen M1 or M2 semantics:

1. Run, Attempt, Operation, request, handle, receipt, and idempotency identities
   remain distinct and correctly correlated.
2. Retrying preserves `operation_id`; new business action creates a new one.
3. `SUCCESS`, `FAILURE`, and `UNKNOWN` require policy-accepted evidence, and
   `UNKNOWN` never grants retry.
4. Verification and receipts return facts whose trust, scope, freshness, and
   correlation are evaluated by policy.
5. Retry admission enforces every required condition and explicit prohibition.
6. A new Attempt can execute the same Operation while Attempt lineage and
   Operation identity remain separate.
7. Compensation, human gate, recovery termination, and terminal business
   outcome remain distinct, conditional decisions.
8. Every decision has a durable, auditable evidence and policy basis.
9. M3 requests M1/M2 actions only through their existing authority boundaries
   and cannot act as executor, store, provider, or Supervisor.
10. Provider-neutral contract fakes can demonstrate valid and invalid cases
    without real-provider assumptions.

Gate result: **READY FOR IMPLEMENTATION** at the provider-neutral semantic
boundary. Production recovery, schema changes, and provider integrations each
require separate authorization.

## 20. Explicit non-goals

This contract does not define or implement:

- production recovery code or a `RecoveryEngine`;
- a database schema, migration, wire format, public API, or policy language;
- changes to M1 Run/Attempt/Binding Epoch semantics or M2 execution-extension
  semantics;
- Supervisor or reconciliation loops;
- real Codex, Claude, Pi, or other provider integration;
- provider-specific receipt, query, idempotency, deduplication, or undo APIs;
- universal verification or compensation capability;
- exactly-once transport, execution, or business effects; or
- automatic retry, compensation, terminal verdict, or human approval.
