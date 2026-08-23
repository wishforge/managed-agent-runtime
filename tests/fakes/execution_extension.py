"""Provider-neutral M2 contract fake; deliberately has no RuntimeStore access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class Correlation:
    run_id: str
    attempt_id: str
    epoch_id: str


@dataclass(frozen=True)
class ExecutionIntent:
    run_id: str
    attempt_id: str
    epoch_id: str
    binding_epoch: Mapping[str, Any]
    request: Any
    execution_policy: Mapping[str, Any]
    isolation_requirements: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("run_id", "attempt_id", "epoch_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        for name in ("binding_epoch", "request", "execution_policy", "isolation_requirements"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    @property
    def correlation(self) -> Correlation:
        return Correlation(self.run_id, self.attempt_id, self.epoch_id)


@dataclass(frozen=True)
class ExecutionHandle:
    handle_id: str
    run_id: str
    attempt_id: str
    epoch_id: str

    @property
    def correlation(self) -> Correlation:
        return Correlation(self.run_id, self.attempt_id, self.epoch_id)


@dataclass(frozen=True)
class FactSpec:
    category: str
    fact: Any
    observation_id: str | None = None
    sequence: int | None = None


@dataclass(frozen=True)
class ExecutionObservation:
    correlation: Correlation | None
    execution_handle: ExecutionHandle | None
    category: str
    fact: Any
    observed_at: str
    observation_id: str | None = None
    sequence: int | None = None
    correlation_error: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    handle: ExecutionHandle | None
    observations: tuple[ExecutionObservation, ...]


class FakeExecutionExtension:
    """Deterministic facts-only extension double for M2 contract tests."""

    def __init__(self) -> None:
        self._next_handle = 1
        self._handles: dict[str, ExecutionHandle] = {}
        self._next_observation = 1

    def _handle_for(self, intent: ExecutionIntent) -> ExecutionHandle:
        handle = ExecutionHandle(
            f"fake-h{self._next_handle}",
            intent.run_id,
            intent.attempt_id,
            intent.epoch_id,
        )
        self._next_handle += 1
        self._handles[handle.handle_id] = handle
        return handle

    def _check_handle(self, intent: ExecutionIntent, handle: ExecutionHandle | None) -> None:
        if handle is not None and handle.correlation != intent.correlation:
            raise ValueError("handle correlation does not match intent")

    def _observation(
        self,
        intent: ExecutionIntent,
        category: str,
        fact: Any,
        handle: ExecutionHandle | None,
        observation_id: str | None = None,
        sequence: int | None = None,
    ) -> ExecutionObservation:
        if observation_id is None:
            observation_id = f"fake-o{self._next_observation}"
            self._next_observation += 1
        return ExecutionObservation(
            intent.correlation,
            handle,
            category,
            _freeze(fact),
            datetime.now(timezone.utc).isoformat(),
            observation_id,
            sequence,
        )

    def _facts(
        self,
        intent: ExecutionIntent,
        handle: ExecutionHandle | None,
        facts: tuple[FactSpec, ...],
    ) -> tuple[ExecutionObservation, ...]:
        return tuple(
            self._observation(intent, spec.category, spec.fact, handle, spec.observation_id, spec.sequence)
            for spec in facts
        )

    def start(
        self,
        intent: ExecutionIntent,
        *,
        status: str = "accepted",
        facts: tuple[FactSpec, ...] = (),
    ) -> ExecutionResult:
        if status not in {"accepted", "rejected", "inconclusive"}:
            raise ValueError(status)
        handle = self._handle_for(intent) if status == "accepted" else None
        if not facts:
            facts = (FactSpec("started", {"accepted": status == "accepted"}),) if handle else (
                FactSpec("error", {"kind": status}),
            )
        return ExecutionResult(status, handle, self._facts(intent, handle, facts))

    def observe(
        self,
        intent: ExecutionIntent,
        handle: ExecutionHandle | None,
        *,
        status: str = "ok",
        facts: tuple[FactSpec, ...] = (),
        gap: tuple[int, int] | None = None,
    ) -> ExecutionResult:
        self._check_handle(intent, handle)
        if status == "disconnected":
            facts = (FactSpec("disconnected", {"kind": "transport_disconnect", "outcome": "inconclusive"}),)
        elif status == "gap" and handle is None and not facts:
            facts = (FactSpec("error", {"kind": "missing_handle", "termination_proven": False}),)
        observations = list(self._facts(intent, handle, facts))
        if gap is not None:
            observations.append(
                self._observation(
                    intent,
                    "error",
                    {"kind": "event_gap", "from_sequence": gap[0], "to_sequence": gap[1]},
                    handle,
                )
            )
        return ExecutionResult(status, handle, tuple(observations))

    def inspect(self, intent: ExecutionIntent, handle: ExecutionHandle | None, *, state: str = "unknown") -> ExecutionResult:
        self._check_handle(intent, handle)
        fact = {"state": state}
        if state in {"stale", "not_found", "unknown"}:
            fact["inconclusive"] = True
        return ExecutionResult("observed", handle, (self._observation(intent, "inspect_result", fact, handle),))

    def terminate(self, intent: ExecutionIntent, handle: ExecutionHandle | None, *, status: str = "accepted") -> ExecutionResult:
        self._check_handle(intent, handle)
        kind = {
            "accepted": "termination_requested",
            "observed": "termination_observed",
            "not_observed": "termination_not_observed",
            "cleanup_incomplete": "cleanup_incomplete",
        }.get(status)
        if kind is None:
            raise ValueError(status)
        fact = {"kind": kind, "durable_outcome": None}
        return ExecutionResult(status, handle, (self._observation(intent, "terminated" if status == "observed" else "error", fact, handle),))

    def reconnect(self, intent: ExecutionIntent, handle: ExecutionHandle, *, new_handle: bool) -> ExecutionResult:
        self._check_handle(intent, handle)
        replacement = self._handle_for(intent) if new_handle else handle
        fact = {
            "kind": "reconnect",
            "same_handle": replacement == handle,
            "attempt_continuity": "undecided",
            "new_attempt_id": None,
        }
        observation = self._observation(intent, "inspect_result", fact, replacement)
        return ExecutionResult("reconnected", replacement, (observation,))

    def uncorrelatable_fact(self, category: str, fact: Any) -> ExecutionObservation:
        return ExecutionObservation(
            None,
            None,
            category,
            _freeze(fact),
            datetime.now(timezone.utc).isoformat(),
            correlation_error="provider_did_not_supply_identity",
        )
