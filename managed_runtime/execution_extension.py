"""Provider-neutral M2 execution facts boundary."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class Correlation:
    run_id: str
    attempt_id: str
    epoch_id: str

    def __post_init__(self) -> None:
        if not all((self.run_id, self.attempt_id, self.epoch_id)):
            raise ValueError("run_id, attempt_id, and epoch_id are required")


@dataclass(frozen=True)
class ExecutionIntent:
    """Immutable Runtime admission for exactly one execution boundary."""

    run_id: str
    attempt_id: str
    epoch_id: str
    binding_epoch: Any
    request: Any
    execution_policy: Mapping[str, Any]
    isolation_requirements: Mapping[str, Any]

    def __post_init__(self) -> None:
        Correlation(self.run_id, self.attempt_id, self.epoch_id)
        object.__setattr__(self, "binding_epoch", _freeze(self.binding_epoch))
        object.__setattr__(self, "request", _freeze(self.request))
        object.__setattr__(self, "execution_policy", _freeze(self.execution_policy))
        object.__setattr__(self, "isolation_requirements", _freeze(self.isolation_requirements))

    @property
    def correlation(self) -> Correlation:
        return Correlation(self.run_id, self.attempt_id, self.epoch_id)


@dataclass(frozen=True)
class ExecutionHandle:
    """Opaque live reference scoped to one Runtime identity triple."""

    handle_id: str
    run_id: str
    attempt_id: str
    epoch_id: str

    def __post_init__(self) -> None:
        if not self.handle_id:
            raise ValueError("handle_id is required")
        Correlation(self.run_id, self.attempt_id, self.epoch_id)

    @property
    def correlation(self) -> Correlation:
        return Correlation(self.run_id, self.attempt_id, self.epoch_id)

    def assert_scope(self, correlation: Correlation) -> None:
        if self.correlation != correlation:
            raise ValueError("execution handle is scoped to another Run/Attempt/Epoch")


@dataclass(frozen=True)
class ExecutionObservation:
    """Immutable execution evidence; never a durable outcome or verdict."""

    correlation: Correlation | None
    execution_handle: ExecutionHandle | None
    category: str
    fact: Any
    observed_at: str
    observation_id: str | None = None
    sequence: int | None = None
    correlation_error: str | None = None

    def __post_init__(self) -> None:
        if not self.category:
            raise ValueError("category is required")
        if self.correlation is None and not self.correlation_error:
            raise ValueError("missing correlation must be explicit")
        if self.execution_handle is not None and self.correlation is not None:
            self.execution_handle.assert_scope(self.correlation)
        object.__setattr__(self, "fact", _freeze(self.fact))


_TERMINAL_STATUSES = {"success", "succeeded", "failure", "failed", "cancelled", "canceled"}


@dataclass(frozen=True)
class ExecutionResult:
    """Facts returned by one operation; status has no M1 terminal authority."""

    correlation: Correlation
    status: str
    handle: ExecutionHandle | None = None
    observations: tuple[ExecutionObservation, ...] = ()

    def __post_init__(self) -> None:
        if self.status.lower() in _TERMINAL_STATUSES:
            raise ValueError("execution result cannot declare a terminal outcome")
        if self.handle is not None:
            self.handle.assert_scope(self.correlation)
        observations = tuple(self.observations)
        for observation in observations:
            if observation.correlation is not None and observation.correlation != self.correlation:
                raise ValueError("observation correlation does not match result")
        object.__setattr__(self, "observations", observations)


@runtime_checkable
class ExecutionExtension(Protocol):
    """Provider-neutral live operations; implementations only return facts."""

    def start(self, intent: ExecutionIntent) -> ExecutionResult:
        ...

    def observe(self, intent: ExecutionIntent, handle: ExecutionHandle | None = None) -> ExecutionResult:
        ...

    def inspect(self, intent: ExecutionIntent, handle: ExecutionHandle | None = None) -> ExecutionResult:
        ...

    def terminate(self, intent: ExecutionIntent, handle: ExecutionHandle | None = None) -> ExecutionResult:
        ...
