from dataclasses import FrozenInstanceError

import pytest

from managed_runtime import AttemptState, RunState, RuntimeStore
from tests.fakes.execution_extension import (
    ExecutionIntent,
    FactSpec,
    FakeExecutionExtension,
)


@pytest.fixture
def context():
    store = RuntimeStore(":memory:")
    run = store.create_run("execute request")
    epoch = store.create_binding_epoch("binding-1", {"provider": "fake"})
    attempt = store.create_attempt(run.run_id, epoch.epoch_id)
    intent = ExecutionIntent(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        epoch_id=epoch.epoch_id,
        binding_epoch=epoch.snapshot,
        request={"command": "echo hello"},
        execution_policy={"timeout_seconds": 5},
        isolation_requirements={"workspace": "isolated"},
    )
    yield store, run, epoch, attempt, intent
    store.close()


def test_start_preserves_correlation_and_acceptance_is_not_success(context):
    _, _, _, _, intent = context
    result = FakeExecutionExtension().start(intent)

    assert result.status == "accepted"
    assert result.handle.correlation == intent.correlation
    assert result.observations[0].category == "started"
    assert result.observations[0].correlation == intent.correlation
    assert result.status not in {"succeeded", "failed", "cancelled"}


def test_start_timeout_is_inconclusive_fact(context):
    _, _, _, _, intent = context
    result = FakeExecutionExtension().start(
        intent,
        status="inconclusive",
        facts=(FactSpec("error", {"kind": "timeout"}),),
    )

    assert result.status == "inconclusive"
    assert result.handle is None
    assert result.observations[0].correlation == intent.correlation
    assert result.observations[0].fact["kind"] == "timeout"


def test_observe_preserves_correlation(context):
    _, _, _, _, intent = context
    extension = FakeExecutionExtension()
    handle = extension.start(intent).handle

    result = extension.observe(intent, handle, facts=(FactSpec("running", {"phase": "active"}),))

    assert result.observations[0].correlation == intent.correlation
    assert result.observations[0].execution_handle == handle


def test_disconnect_is_a_fact_not_failure(context):
    _, _, _, _, intent = context
    extension = FakeExecutionExtension()
    handle = extension.start(intent).handle

    result = extension.observe(intent, handle, status="disconnected")

    assert result.observations[0].category == "disconnected"
    assert result.observations[0].fact["kind"] == "transport_disconnect"
    assert result.observations[0].fact["outcome"] == "inconclusive"


def test_missing_handle_is_not_termination_proof(context):
    _, _, _, _, intent = context
    result = FakeExecutionExtension().observe(intent, None, status="gap")

    assert result.observations[0].execution_handle is None
    assert result.observations[0].fact == {
        "kind": "missing_handle",
        "termination_proven": False,
    }


def test_stale_handle_is_reported_as_inconclusive_fact(context):
    _, _, _, _, intent = context
    extension = FakeExecutionExtension()
    handle = extension.start(intent).handle

    result = extension.inspect(intent, handle, state="stale")

    assert result.observations[0].category == "inspect_result"
    assert result.observations[0].fact == {"state": "stale", "inconclusive": True}


def test_inspect_returns_facts_not_recovery_decisions(context):
    _, _, _, _, intent = context
    extension = FakeExecutionExtension()
    handle = extension.start(intent).handle

    result = extension.inspect(intent, handle, state="not_found")

    assert result.observations[0].fact["state"] == "not_found"
    assert "decision" not in result.observations[0].fact


def test_terminate_reports_execution_facts_not_durable_outcome(context):
    _, _, _, _, intent = context
    extension = FakeExecutionExtension()
    handle = extension.start(intent).handle

    result = extension.terminate(intent, handle, status="accepted")

    assert result.observations[0].fact["kind"] == "termination_requested"
    assert result.observations[0].fact["durable_outcome"] is None
    assert result.observations[0].correlation == intent.correlation


@pytest.mark.parametrize("new_handle", [False, True])
def test_reconnect_does_not_create_attempt_continuity(context, new_handle):
    _, _, _, attempt, intent = context
    extension = FakeExecutionExtension()
    original = extension.start(intent).handle

    result = extension.reconnect(intent, original, new_handle=new_handle)

    assert result.handle.attempt_id == attempt.attempt_id
    assert result.observations[0].fact["attempt_continuity"] == "undecided"
    assert result.observations[0].fact["new_attempt_id"] is None


def test_duplicate_reordered_and_gapped_observations_remain_attributable(context):
    _, _, _, _, intent = context
    extension = FakeExecutionExtension()
    handle = extension.start(intent).handle
    facts = (
        FactSpec("output_event", {"text": "second"}, observation_id="obs-2", sequence=2),
        FactSpec("output_event", {"text": "first"}, observation_id="obs-1", sequence=1),
        FactSpec("output_event", {"text": "second"}, observation_id="obs-2", sequence=2),
    )

    result = extension.observe(intent, handle, facts=facts, gap=(2, 4))

    assert [observation.observation_id for observation in result.observations[:3]] == [
        "obs-2",
        "obs-1",
        "obs-2",
    ]
    assert result.observations[-1].fact == {"kind": "event_gap", "from_sequence": 2, "to_sequence": 4}
    assert all(observation.correlation == intent.correlation for observation in result.observations)


def test_fake_never_guesses_missing_identity(context):
    _, _, _, _, intent = context
    extension = FakeExecutionExtension()

    observation = extension.uncorrelatable_fact("disconnected", {"scope": "transport"})

    assert observation.correlation is None
    assert observation.correlation_error == "provider_did_not_supply_identity"
    assert intent.attempt_id not in repr(observation)


def test_extension_cannot_create_attempt_or_mutate_epoch(context):
    store, run, epoch, attempt, intent = context
    extension = FakeExecutionExtension()
    before = store.list_attempts(run.run_id)
    extension.start(intent)
    handle = extension.start(intent).handle
    extension.observe(intent, handle)
    extension.inspect(intent, handle)
    extension.terminate(intent, handle)

    assert store.list_attempts(run.run_id) == before == [attempt]
    assert store.get_binding_epoch(epoch.epoch_id).snapshot == epoch.snapshot
    with pytest.raises(FrozenInstanceError):
        intent.epoch_id = "other"


def test_extension_cannot_perform_m1_durable_transition(context):
    store, run, _, attempt, intent = context
    extension = FakeExecutionExtension()
    result = extension.start(intent)
    extension.observe(intent, result.handle)
    extension.inspect(intent, result.handle)
    extension.terminate(intent, result.handle)

    assert store.get_run(run.run_id).state == RunState.OPEN
    assert store.get_attempt(attempt.attempt_id).state == AttemptState.PENDING
    assert store.transition_history(attempt.attempt_id) == []


def test_m1_transition_authority_remains_green_after_fake_facts(context):
    store, _, _, attempt, intent = context
    result = FakeExecutionExtension().start(intent)

    assert store.get_attempt(attempt.attempt_id).state == AttemptState.PENDING
    moved = store.transition_attempt(attempt.attempt_id, AttemptState.STARTING, 0, 1)
    assert moved.state == AttemptState.STARTING
    assert result.observations[0].category == "started"
