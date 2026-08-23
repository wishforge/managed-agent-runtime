from dataclasses import FrozenInstanceError

import pytest

from managed_runtime import (
    Correlation,
    ExecutionExtension,
    ExecutionHandle,
    ExecutionIntent,
    ExecutionObservation,
    ExecutionResult,
)


def intent() -> ExecutionIntent:
    return ExecutionIntent(
        run_id="run-1",
        attempt_id="attempt-1",
        epoch_id="epoch-1",
        binding_epoch={"provider": "opaque", "nested": {"values": [1, 2]}},
        request={"operation": "run"},
        execution_policy={"timeout_seconds": 5},
        isolation_requirements={"workspace": "isolated"},
    )


def test_intent_is_deeply_immutable_and_preserves_runtime_identity():
    value = intent()

    with pytest.raises(FrozenInstanceError):
        value.attempt_id = "other"
    with pytest.raises(TypeError):
        value.binding_epoch["nested"]["values"] += (3,)

    assert value.correlation == Correlation("run-1", "attempt-1", "epoch-1")
    assert value.binding_epoch["nested"]["values"] == (1, 2)


def test_handle_scope_is_explicit_and_cannot_cross_attempt_or_epoch():
    value = intent()
    handle = ExecutionHandle("opaque-h1", value.run_id, value.attempt_id, value.epoch_id)

    assert handle.correlation == value.correlation
    handle.assert_scope(value.correlation)
    with pytest.raises(ValueError):
        handle.assert_scope(Correlation("run-1", "attempt-2", "epoch-1"))
    with pytest.raises(ValueError):
        handle.assert_scope(Correlation("run-1", "attempt-1", "epoch-2"))


def test_observation_requires_matching_correlation_when_present():
    value = intent()
    handle = ExecutionHandle("opaque-h1", value.run_id, value.attempt_id, value.epoch_id)

    observation = ExecutionObservation(
        correlation=value.correlation,
        execution_handle=handle,
        category="disconnected",
        fact={"kind": "transport"},
        observed_at="2026-08-23T00:00:00+00:00",
    )
    assert observation.correlation == value.correlation

    with pytest.raises(ValueError):
        ExecutionObservation(
            correlation=Correlation("run-1", "attempt-2", "epoch-1"),
            execution_handle=handle,
            category="error",
            fact={"kind": "timeout"},
            observed_at="2026-08-23T00:00:00+00:00",
        )


def test_missing_correlation_is_explicit_not_guessed():
    observation = ExecutionObservation(
        correlation=None,
        execution_handle=None,
        category="disconnected",
        fact={"scope": "transport"},
        observed_at="2026-08-23T00:00:00+00:00",
        correlation_error="provider_did_not_supply_identity",
    )

    assert observation.correlation is None
    assert observation.correlation_error


def test_result_preserves_facts_and_rejects_terminal_authority():
    value = intent()
    result = ExecutionResult(
        correlation=value.correlation,
        status="inconclusive",
        observations=(
            ExecutionObservation(
                correlation=value.correlation,
                execution_handle=None,
                category="error",
                fact={"kind": "timeout", "termination_proven": False},
                observed_at="2026-08-23T00:00:00+00:00",
            ),
        ),
    )

    assert result.status == "inconclusive"
    assert result.observations[0].fact["kind"] == "timeout"
    for status in ("succeeded", "failed", "cancelled", "SUCCESS", "FAILED"):
        with pytest.raises(ValueError):
            ExecutionResult(value.correlation, status)


@pytest.mark.parametrize(
    ("category", "fact"),
    [
        ("disconnected", {"kind": "transport_disconnect", "outcome": "inconclusive"}),
        ("error", {"kind": "timeout", "termination_proven": False}),
        ("inspect_result", {"state": "stale", "inconclusive": True}),
    ],
)
def test_uncertain_boundary_facts_remain_evidence(category, fact):
    value = intent()
    observation = ExecutionObservation(
        correlation=value.correlation,
        execution_handle=None,
        category=category,
        fact=fact,
        observed_at="2026-08-23T00:00:00+00:00",
    )

    result = ExecutionResult(value.correlation, "inconclusive", observations=(observation,))

    assert result.observations[0].fact == fact
    assert result.status == "inconclusive"
    assert result.status.lower() not in {"succeeded", "failed", "cancelled"}


def test_result_rejects_observation_from_another_scope():
    value = intent()
    observation = ExecutionObservation(
        correlation=Correlation("run-1", "attempt-2", "epoch-1"),
        execution_handle=None,
        category="running",
        fact={},
        observed_at="2026-08-23T00:00:00+00:00",
    )

    with pytest.raises(ValueError):
        ExecutionResult(value.correlation, "observed", observations=(observation,))


def test_extension_is_only_a_facts_protocol():
    methods = {"start", "observe", "inspect", "terminate"}
    assert methods <= set(ExecutionExtension.__dict__)
    assert "transition_attempt" not in ExecutionExtension.__dict__
    assert "create_attempt" not in ExecutionExtension.__dict__
    assert "transition_run" not in ExecutionExtension.__dict__
