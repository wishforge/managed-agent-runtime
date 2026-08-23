from dataclasses import FrozenInstanceError

import pytest

from managed_runtime import AttemptState, RuntimeStore
from managed_runtime.operation_recovery import (
    Evidence,
    EvidenceClassification,
    EvidenceFreshness,
    EvidenceScope,
    Operation,
    OperationOutcome,
    RetryDecision,
    RetryPolicy,
    decide_retry_admission,
)


def operation(**changes) -> Operation:
    values = {
        "operation_id": "operation-1",
        "run_id": "run-1",
        "business_intent": "create order 42",
        "current_attempt_id": "attempt-1",
        "retryable": True,
    }
    values.update(changes)
    return Operation(**values)


def evidence(outcome: OperationOutcome, **changes) -> Evidence:
    values = {
        "operation_id": "operation-1",
        "source": "order-system",
        "kind": "business-outcome",
        "observed_at": "2026-08-23T00:00:00+00:00",
        "freshness": EvidenceFreshness.FRESH,
        "scope": EvidenceScope.OPERATION,
        "fact": {"outcome": outcome.value},
        "classification": EvidenceClassification.TRUSTED,
        "outcome": outcome,
    }
    values.update(changes)
    return Evidence(**values)


def test_success_blocks_retry():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.SUCCESS),),
        RetryPolicy(duplicate_protection=True),
    )

    assert result.decision is RetryDecision.DENY_RETRY


def test_safe_failure_allows_retry():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.FAILURE),),
        RetryPolicy(failure_retry_safe=True),
    )

    assert result.decision is RetryDecision.ALLOW_RETRY


def test_failure_without_safe_retry_policy_is_denied():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.FAILURE),),
        RetryPolicy(),
    )

    assert result.decision is RetryDecision.DENY_RETRY


def test_required_verification_precedes_safe_failure_retry():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.FAILURE),),
        RetryPolicy(failure_retry_safe=True, verification_required=True),
    )

    assert result.decision is RetryDecision.NEEDS_VERIFICATION


def test_unknown_requires_verification():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.UNKNOWN),),
        RetryPolicy(verification_required=True),
    )

    assert result.decision is RetryDecision.NEEDS_VERIFICATION


def test_unknown_can_retry_with_sufficient_idempotency_or_deduplication():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.UNKNOWN),),
        RetryPolicy(duplicate_protection=True),
    )

    assert result.decision is RetryDecision.ALLOW_RETRY


def test_unknown_blocks_retry_when_duplicate_risk_is_unsafe():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.UNKNOWN),),
        RetryPolicy(unsafe_duplicate_risk=True),
    )

    assert result.decision is RetryDecision.DENY_RETRY


def test_unknown_without_duplicate_protection_is_denied_even_when_risk_is_not_marked_unsafe():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.UNKNOWN),),
        RetryPolicy(unsafe_duplicate_risk=False),
    )

    assert result.decision is RetryDecision.DENY_RETRY


def test_retry_preserves_operation_id():
    original = operation()
    retried = original.associate_attempt("attempt-2")
    result = decide_retry_admission(
        retried,
        (evidence(OperationOutcome.FAILURE),),
        RetryPolicy(failure_retry_safe=True),
    )

    assert retried.operation_id == original.operation_id == result.operation_id


def test_same_operation_can_move_to_a_new_attempt():
    original = operation()

    moved = original.associate_attempt("attempt-2")

    assert moved.operation_id == original.operation_id
    assert moved.current_attempt_id == "attempt-2"
    assert moved.prior_attempt_ids == ("attempt-1",)
    assert original.current_attempt_id == "attempt-1"


def test_new_business_action_requires_new_operation_id():
    original = operation()

    with pytest.raises(ValueError, match="new operation_id"):
        original.new_business_action(original.operation_id, "send confirmation")

    created = original.new_business_action("operation-2", "send confirmation")
    assert created.operation_id == "operation-2"
    assert created.business_intent == "send confirmation"


@pytest.mark.parametrize(
    "changes",
    [
        {"freshness": EvidenceFreshness.STALE},
        {"operation_id": "operation-2"},
        {"operation_id": None},
        {"scope": EvidenceScope.REQUEST},
        {"classification": EvidenceClassification.UNTRUSTED},
        {"classification": EvidenceClassification.INCONCLUSIVE},
    ],
)
def test_stale_foreign_request_scoped_or_untrusted_evidence_cannot_authorize_retry(changes):
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.FAILURE, **changes),),
        RetryPolicy(unsafe_duplicate_risk=True),
    )

    assert result.decision is RetryDecision.DENY_RETRY


def test_decision_object_is_immutable():
    result = decide_retry_admission(
        operation(),
        (evidence(OperationOutcome.FAILURE),),
        RetryPolicy(failure_retry_safe=True),
    )

    with pytest.raises(FrozenInstanceError):
        result.decision = RetryDecision.DENY_RETRY


def test_retry_decision_does_not_mutate_runtime_store():
    store = RuntimeStore(":memory:")
    run = store.create_run("execute request")
    epoch = store.create_binding_epoch("binding-1", {"provider": "fake"})
    attempt = store.create_attempt(run.run_id, epoch.epoch_id)

    result = decide_retry_admission(
        operation(run_id=run.run_id, current_attempt_id=attempt.attempt_id),
        (evidence(OperationOutcome.FAILURE),),
        RetryPolicy(failure_retry_safe=True),
    )

    assert result.decision is RetryDecision.ALLOW_RETRY
    assert store.get_attempt(attempt.attempt_id).state is AttemptState.PENDING
    assert store.list_attempts(run.run_id) == [attempt]
    assert store.transition_history(attempt.attempt_id) == []
    store.close()
