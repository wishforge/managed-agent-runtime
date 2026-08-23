# 07 — M1 / M2 / M3 Semantic Boundary

## Status and governing sentence

This document freezes the implementation milestone boundary against the
published M1 implementation and the architecture documents listed in the
implementation plan. It is a documentation-only clarification. It does not
authorize production code, tests, M2, M3, or Supervisor implementation.

> **M1 persists recovery facts; M3 decides what recovery means.**

The word *recovery* is overloaded unless it is qualified:

1. **Durable recovery substrate** — states and append-only facts that preserve
   what was observed and what transition was recorded. This is M1.
2. **Execution observation** — live process/session/transport/tool facts and
   correlated handles/events. This is M2.
3. **Recovery decision** — verification and policy interpretation that chooses
   retry, a new Attempt, compensation, termination, or a terminal outcome. This
   is M3.

## 1. Why the previous boundary was ambiguous

The original documents described the complete MVP and the future architecture
in the same vocabulary, but did not mark which recovery artifacts were already
implemented and which recovery policy was still absent. In particular:

- `01-scope.md` puts verification requests/results, receipt references,
  decisions, and new Attempt lineage in the first-version scope without
  splitting the M1 substrate from the later decision layer.
- `03-milestones.md` places `UNKNOWN` and `RESOLVING` under M3 even though the
  M1 state machine already persists both states and their evidence/history.
- The execution-extension documents use “Managed Runtime recovery semantics”
  and “Supervisor UNKNOWN resolution” correctly as architecture ownership, but
  do not distinguish a durable fact from a policy verdict.
- `RecoveryRecord` is a durable record of the fact that `UNKNOWN` entered
  `RESOLVING`; it is not a recovery verdict, retry authorization, or proof that
  a side effect was safe to repeat.

The correction is a milestone split, not a semantic expansion: M1 keeps facts;
M2 supplies live facts; M3 interprets facts and decides.

## 2. M1 — Durable Semantic Substrate

### Responsibilities

M1 owns the durable, provider-neutral semantic substrate:

- stable `Run` identity and `RunState` transitions;
- stable `Attempt` identity, Run ownership, Attempt state machine, and terminal
  protection;
- `Binding` identity and immutable `BindingEpoch` identity/number/snapshot;
- epoch admission closure (a closed epoch cannot admit a new Attempt);
- durable transition history for Run and Attempt;
- expected-version checks and fencing tokens for stale-writer rejection;
- durable `UNKNOWN` and `RESOLVING` states;
- durable `UnknownEvidence` for the cause, boundary, observation, and time of an
  `UNKNOWN` transition;
- durable `RecoveryRecord` for the fact of an `UNKNOWN → RESOLVING` transition;
- evidence attached to terminal transitions;
- restart reconstruction of the above facts.

M1 stores facts supplied at the semantic boundary. It does not infer whether a
side effect happened or whether a retry is safe.

### Explicit non-ownership

M1 does not own an Execution Extension adapter, live process/session/tool
execution, observation collection, receipt interpretation, verification
policy, recovery verdict, retry admission, compensation, termination policy,
artifact trust, or a Supervisor reconciliation loop.

Persisting an observation field is storage; it is not observation production or
recovery policy.

## 3. M2 — Execution Extension

### Responsibilities

M2 owns the live execution boundary and its provider-facing facts:

- Execution Extension adapter contract;
- `start`, `observe`, `terminate`, and `inspect` primitives;
- execution handles and their process/session/transport/tool associations;
- process, session, transport, tool, event, workspace, timeout, disconnect, and
  cancellation facts;
- correlated execution observations carrying `run_id`, `attempt_id`, and
  `epoch_id` (plus the execution handle where applicable);
- provider/tool capabilities and tool-specific receipt, probe, idempotency, or
  undo hooks when the underlying system supports them.

M2 reports observations and references to M1. An observation is a fact or
signal, not a durable outcome or policy verdict.

### Explicit non-ownership

M2 does not own durable Run/Attempt semantics, Attempt lineage, epoch admission,
transition authority, durable outcome, retry admission, recovery verdict,
artifact provenance/integrity/trust, compensation policy, or termination
policy. M2 must not silently create a new Attempt or translate handle loss into
`FAILED`/`SUCCEEDED`.

## 4. M3 — Recovery Decision

### Responsibilities

M3 consumes M1 durable facts and M2 execution facts and owns policy decisions:

- verification request and verification result;
- receipt interpretation and operation-identity/idempotency interpretation;
- recovery decision for an `UNKNOWN`/`RESOLVING` Attempt;
- retry admission (including the explicit no-blind-retry decision);
- new Attempt lineage decision when retry/resume/fork is admitted;
- compensation decision when capability and policy permit it;
- termination decision and the evidence required for a terminal transition;
- durable decision records that link the decision to its input facts.

M3 may request M2 to execute an admitted operation and may ask M1 to persist a
transition or create a new Attempt. Those requests do not make M3 the executor
or M2 the semantic owner.

### Explicit non-ownership

M3 does not own process/session/transport/tool implementation, execution
handles, live observation production, or the M1 identity/state/fencing store.
It cannot directly mutate a Run or Attempt outside M1's transition and fence
rules, and it cannot manufacture a receipt, verification fact, or terminal
evidence.

## 5. State and data flow

```text
             M1: durable semantic substrate
  Run + Binding + immutable Epoch + Attempt state/history
                       |
       admitted execution intent (Run/Attempt/Epoch)
                       v
             M2: Execution Extension
       start / observe / terminate / inspect
       handle + process/session/tool observations
                       |
       correlated facts (including loss/disconnect/receipt refs)
                       v
             M1: append durable facts
       transition evidence / UNKNOWN / recovery fact
                       |
                       v
             M3: Recovery Decision
 verification + receipt interpretation + policy decision
      | retry/new Attempt | compensation | termination | terminal outcome
      +-------------------+----------------+--------------+
                       |
                       v
             M1 persists the authorized transition/lineage
             M2 executes only the admitted live operation
```

`UNKNOWN` is a durable state and fact boundary, not a verdict that the side
effect did or did not happen. `RESOLVING` records that resolution has started;
M3 supplies the meaning and next action.

## 6. Existing implementation symbols mapped to milestones

| Existing symbol or behavior | Milestone | Evidence/status |
|---|---|---|
| `Run`, `RunState`, `create_run`, `get_run`, `transition_run`, run history | M1 | Implemented in `managed_runtime/core.py` |
| `Binding`, `BindingEpoch`, `create_binding_epoch`, immutable/deep-frozen snapshot | M1 | Implemented; old epoch admission closes |
| `Attempt`, `AttemptState`, `create_attempt`, `get_attempt`, `list_attempts` | M1 | Implemented; Attempt links one Run and one epoch |
| `TRANSITIONS`, terminal protection, transition guards | M1 | Implemented |
| `version`, `expected_version`, `fencing_token`, `acquire_fence` | M1 | Implemented for stale-writer rejection |
| `transitions` and `run_transitions` tables/history | M1 | Implemented and restart-readable |
| `UnknownEvidence`, `unknown_evidence`, evidence-required `UNKNOWN` transition | M1 | Implemented and durable |
| `RecoveryRecord`, `attempt_recoveries`, `recovery_history` | M1 | Implemented for `UNKNOWN → RESOLVING` fact history only |
| `execution_handle` field on `Attempt` | M1 persistence seam for an M2-owned reference | Nullable field is present; M2 handle creation/lifecycle is not implemented |
| `start`, `observe`, `terminate`, `inspect` adapter | M2 | Not implemented |
| correlated execution observation contract | M2 | Not implemented |
| verification/receipt/recovery/retry/lineage/compensation/termination decision records | M3 | Not implemented |
| Supervisor reconciliation loop | Later control-plane work | Not implemented; not part of M1/M2 implementation here |

## 7. Existing tests mapped to milestones

All current tests exercise M1. They do not prove M2 or M3 behavior.

| M1 contract covered | Tests in `tests/test_runtime_core.py` |
|---|---|
| Run/Attempt identity and lifecycle | `test_identities_and_ownership_are_stable`, `test_run_lifecycle_and_identity_are_durable`, `test_terminal_run_cannot_create_attempt` |
| Epoch immutability, deep snapshot, and restart | `test_epoch_is_immutable`, `test_epoch_snapshot_is_deeply_immutable`, `test_epoch_snapshot_nested_list_is_immutable`, `test_epoch_snapshot_isolated_from_input_mutation`, `test_epoch_snapshot_survives_restart`, `test_new_binding_epoch_closes_old_epoch_admission` |
| State-machine guards and terminal evidence | `test_running_to_succeeded_requires_evidence`, `test_running_to_succeeded_accepts_required_evidence`, `test_running_to_failed_requires_evidence`, `test_running_to_failed_accepts_required_evidence`, `test_running_to_cancelled_requires_evidence`, `test_running_to_cancelled_accepts_required_evidence`, `test_state_machine_and_unknown_semantics` |
| Durable UNKNOWN and recovery facts | `test_unknown_requires_evidence`, `test_unknown_cannot_directly_transition_to_failed`, `test_unknown_evidence_survives_restart`, `test_unknown_to_resolving_writes_recovery_record`, `test_unknown_requires_evidence_and_cannot_fail_directly`, `test_resolving_to_succeeded_requires_verification_evidence` |
| Restart and schema boundary | `test_restart_recovers_durable_state`, `test_run_history_survives_restart`, `test_runtime_store_does_not_implicitly_migrate_schema` |
| Version/fencing/concurrency | `test_stale_writer_and_duplicate_transition_are_rejected`, `test_run_stale_writer_has_no_phantom_history`, `test_run_competing_writers_have_one_winner_and_one_history_append` |

No current test can demonstrate an M2 adapter call or an M3 recovery policy
decision; adding those belongs to the corresponding milestone, not to M1.

## 8. Already implemented vs next to implement

### Already implemented (M1)

Run/Attempt identity, Binding Epoch identity and immutable snapshot, epoch
admission closure, state transitions, terminal evidence, version/fencing,
durable transition history, restart recovery, `UNKNOWN`, `UnknownEvidence`, and
durable `UNKNOWN → RESOLVING` `RecoveryRecord` history.

### Next to implement (M2)

M2 is ready to begin under the gate below: define and implement the adapter
contract and live primitives (`start`, `observe`, `terminate`, `inspect`),
execution handles, and correlated provider facts. M2 must feed facts into M1
without moving policy into the adapter.

### Later to implement (M3)

Only after the M3 gate: verification and receipt interpretation, recovery and
retry admission decisions, new Attempt lineage, compensation and termination
decisions, and their durable decision records. Supervisor orchestration remains
a separate later implementation concern.

## 9. Acceptance gate for M2

The semantic entry gate is open: M1 is complete and the ownership boundary is
frozen. M2 is accepted only when the following are explicit and testable
without changing M1 semantics:

1. `start`, `observe`, `terminate`, and `inspect` have a provider-neutral
   contract and execution-handle lifecycle.
2. Every returned fact is correlated to exactly one Run/Attempt/epoch boundary.
3. Handle loss, disconnect, timeout, and event gaps are reported as facts; they
   do not directly produce a terminal outcome or new Attempt.
4. The adapter cannot bypass M1 transition, epoch-admission, version, or fence
   checks.
5. Contract-fake checks prove M1 remains green while M2 facts can be persisted.

M2 gate result: **READY TO BEGIN; NOT YET ACCEPTED**, with M1 frozen.

## 10. Acceptance gate for M3

M3 is not ready to begin until M2's execution-fact contract is accepted. After
that dependency is met, M3 is accepted only when the following are explicit
and testable:

1. Verification requests/results and receipt references are correlated to the
   originating Attempt/epoch and durably recorded.
2. Receipt interpretation is policy-driven and never treated as universal
   proof of side-effect success.
3. `UNKNOWN` cannot receive blind retry admission; each decision names the
   evidence and policy used.
4. A transport retry/reconnect may remain in the same Attempt only when the
   original execution boundary and semantics remain continuous. Managed
   retry/resume creates an explicitly linked new Attempt; identities are never
   reused.
5. Compensation and termination are conditional decisions with durable
   evidence, not implicit adapter behavior.
6. M3 requests M1 transitions/new Attempt creation and M2 execution; it does
   not become the live executor.

M3 gate result: **NOT READY TO BEGIN — BLOCKED ON ACCEPTED M2 FACTS**. Its
semantic ownership is frozen; implementation authorization is not.

## 11. Boundary decision and contradiction record

The frozen decision is:

- M1 owns durable recovery substrate (`UNKNOWN`, evidence, and recovery fact
  history).
- M2 owns live execution and correlated execution observations.
- M3 owns recovery meaning and policy decisions.
- Supervisor, when implemented, orchestrates reconciliation around those
  contracts; it does not move M3 policy into M2 or bypass M1.

The direct contradiction in the previous milestone text was assigning the
already-implemented `UNKNOWN`/`RESOLVING` substrate to M3. The broad MVP scope
was not removed; it is now decomposed into substrate (M1), execution (M2), and
decision (M3) portions. Architecture documents that say “Runtime owns recovery
semantics” remain true at the system level; this file defines which milestone
implements which slice.

## 12. M1 status

M1 remains **GREEN** at the published verification level (`python -m pytest -q`:
28 passed, 3 subtests passed, as recorded for the current commits). This boundary
freeze does not expand M1 retroactively, does not change production code, and
does not add tests. M2 is the next implementation milestone; M3 follows M2 and
consumes both durable M1 facts and live M2 facts.
