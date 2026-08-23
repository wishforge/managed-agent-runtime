"""Provider-neutral M3 operation identity and retry admission."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


class OperationOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"


class EvidenceClassification(str, Enum):
    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class EvidenceFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"


class EvidenceScope(str, Enum):
    OPERATION = "OPERATION"
    REQUEST = "REQUEST"
    OTHER = "OTHER"


class RetryDecision(str, Enum):
    ALLOW_RETRY = "ALLOW_RETRY"
    DENY_RETRY = "DENY_RETRY"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"


@dataclass(frozen=True)
class Operation:
    """Stable identity for one business action across Attempts and requests."""

    operation_id: str
    run_id: str
    business_intent: str
    current_attempt_id: str | None = None
    prior_attempt_ids: tuple[str, ...] = ()
    retryable: bool = True

    def __post_init__(self) -> None:
        if not self.operation_id or not self.run_id or not self.business_intent:
            raise ValueError("operation_id, run_id, and business_intent are required")
        prior_attempt_ids = tuple(self.prior_attempt_ids)
        if any(not attempt_id for attempt_id in prior_attempt_ids):
            raise ValueError("prior attempt identities must be non-empty")
        object.__setattr__(self, "prior_attempt_ids", prior_attempt_ids)

    def associate_attempt(self, attempt_id: str) -> Operation:
        if not attempt_id:
            raise ValueError("attempt_id is required")
        if attempt_id == self.current_attempt_id:
            return self
        prior = self.prior_attempt_ids
        if self.current_attempt_id is not None:
            prior += (self.current_attempt_id,)
        return replace(self, current_attempt_id=attempt_id, prior_attempt_ids=prior)

    def new_business_action(
        self,
        operation_id: str,
        business_intent: str,
        current_attempt_id: str | None = None,
        *,
        retryable: bool = True,
    ) -> Operation:
        if operation_id == self.operation_id:
            raise ValueError("a new business action requires a new operation_id")
        return Operation(
            operation_id=operation_id,
            run_id=self.run_id,
            business_intent=business_intent,
            current_attempt_id=current_attempt_id,
            retryable=retryable,
        )


@dataclass(frozen=True)
class Evidence:
    """Provider-neutral fact used to interpret one Operation's outcome."""

    operation_id: str | None
    source: str
    kind: str
    observed_at: str
    freshness: EvidenceFreshness
    scope: EvidenceScope
    fact: Any
    classification: EvidenceClassification
    outcome: OperationOutcome = OperationOutcome.UNKNOWN

    def __post_init__(self) -> None:
        if not self.source or not self.kind or not self.observed_at:
            raise ValueError("source, kind, and observed_at are required")
        object.__setattr__(self, "freshness", EvidenceFreshness(self.freshness))
        object.__setattr__(self, "scope", EvidenceScope(self.scope))
        object.__setattr__(self, "classification", EvidenceClassification(self.classification))
        object.__setattr__(self, "outcome", OperationOutcome(self.outcome))
        object.__setattr__(self, "fact", _freeze(self.fact))


@dataclass(frozen=True)
class RetryPolicy:
    """Minimal policy inputs for retrying an unresolved Operation."""

    failure_retry_safe: bool = False
    verification_required: bool = False
    duplicate_protection: bool = False
    unsafe_duplicate_risk: bool = True


@dataclass(frozen=True)
class RetryAdmission:
    operation_id: str
    decision: RetryDecision
    reason: str

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError("operation_id is required")
        object.__setattr__(self, "decision", RetryDecision(self.decision))


def _established_outcome(operation: Operation, evidence: Iterable[Evidence]) -> OperationOutcome:
    outcomes = {
        item.outcome
        for item in evidence
        if item.operation_id == operation.operation_id
        and item.classification is EvidenceClassification.TRUSTED
        and item.freshness is EvidenceFreshness.FRESH
        and item.scope is EvidenceScope.OPERATION
    }
    if OperationOutcome.SUCCESS in outcomes:
        return OperationOutcome.SUCCESS
    if OperationOutcome.FAILURE in outcomes:
        return OperationOutcome.FAILURE
    return OperationOutcome.UNKNOWN


def decide_retry_admission(
    operation: Operation,
    evidence: Iterable[Evidence],
    policy: RetryPolicy,
) -> RetryAdmission:
    """Return a deterministic decision without executing or mutating runtime state."""

    outcome = _established_outcome(operation, evidence)
    if outcome is OperationOutcome.SUCCESS:
        return RetryAdmission(operation.operation_id, RetryDecision.DENY_RETRY, "success established")
    if not operation.retryable:
        return RetryAdmission(operation.operation_id, RetryDecision.DENY_RETRY, "operation is non-retryable")
    if policy.verification_required:
        return RetryAdmission(operation.operation_id, RetryDecision.NEEDS_VERIFICATION, "verification required")
    if outcome is OperationOutcome.FAILURE:
        decision = RetryDecision.ALLOW_RETRY if policy.failure_retry_safe else RetryDecision.DENY_RETRY
        return RetryAdmission(operation.operation_id, decision, "failure retry policy")
    if policy.duplicate_protection:
        return RetryAdmission(operation.operation_id, RetryDecision.ALLOW_RETRY, "duplicate protection sufficient")
    if policy.unsafe_duplicate_risk:
        return RetryAdmission(operation.operation_id, RetryDecision.DENY_RETRY, "unsafe duplicate risk")
    return RetryAdmission(operation.operation_id, RetryDecision.DENY_RETRY, "duplicate protection insufficient")
