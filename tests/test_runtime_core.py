import tempfile
import unittest
from pathlib import Path

from managed_runtime import (
    AttemptState,
    BindingEpoch,
    ConflictError,
    ImmutableError,
    InvalidTransition,
    RuntimeStore,
    RunState,
)


class DurableCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "runtime.sqlite3"
        self.store = RuntimeStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def create_attempt(self):
        run = self.store.create_run("ship it")
        epoch = self.store.create_binding_epoch("binding-1", {"provider": "local"})
        attempt = self.store.create_attempt(run.run_id, epoch.epoch_id)
        return run, epoch, attempt

    def test_identities_and_ownership_are_stable(self):
        run, epoch, attempt = self.create_attempt()
        self.assertEqual(attempt.run_id, run.run_id)
        self.assertEqual(attempt.epoch_id, epoch.epoch_id)
        self.assertNotEqual(attempt.attempt_id, "process-1")
        self.assertEqual(self.store.list_attempts(run.run_id), [attempt])

    def test_run_lifecycle_and_identity_are_durable(self):
        run = self.store.create_run("ship it")
        moved = self.store.transition_run(run.run_id, RunState.EXECUTING, run.version, run.fencing_token)
        self.assertEqual(moved.run_id, run.run_id)
        self.assertEqual(moved.state, RunState.EXECUTING)
        self.assertEqual(len(self.store.run_transition_history(run.run_id)), 1)
        with self.assertRaises(InvalidTransition):
            self.store.transition_run(run.run_id, RunState.OPEN, moved.version, moved.fencing_token)

    def test_epoch_is_immutable(self):
        _, epoch, _ = self.create_attempt()
        with self.assertRaises(ImmutableError):
            self.store.update_binding_epoch(epoch.epoch_id, {"provider": "other"})

    def test_state_machine_and_unknown_semantics(self):
        _, _, attempt = self.create_attempt()
        current = attempt
        for state in (AttemptState.STARTING, AttemptState.RUNNING, AttemptState.UNKNOWN, AttemptState.RESOLVING):
            current = self.store.transition_attempt(current.attempt_id, state, current.version, current.fencing_token)
        self.assertEqual(current.state, AttemptState.RESOLVING)
        with self.assertRaises(InvalidTransition):
            self.store.transition_attempt(current.attempt_id, AttemptState.RUNNING, current.version, current.fencing_token)
        current = self.store.transition_attempt(current.attempt_id, AttemptState.SUCCEEDED, current.version, current.fencing_token)
        self.assertEqual(len(self.store.transition_history(current.attempt_id)), 5)
        with self.assertRaises(InvalidTransition):
            self.store.transition_attempt(current.attempt_id, AttemptState.RUNNING, current.version, current.fencing_token)

    def test_restart_recovers_durable_state(self):
        run, epoch, attempt = self.create_attempt()
        attempt = self.store.transition_attempt(attempt.attempt_id, AttemptState.STARTING, 0, 1)
        self.store.close()
        self.store = RuntimeStore(self.path)
        self.assertEqual(self.store.get_run(run.run_id).run_id, run.run_id)
        self.assertEqual(self.store.get_binding_epoch(epoch.epoch_id).snapshot["provider"], "local")
        recovered = self.store.get_attempt(attempt.attempt_id)
        self.assertEqual(recovered.state, AttemptState.STARTING)
        self.assertEqual(recovered.version, 1)

    def test_stale_writer_and_duplicate_transition_are_rejected(self):
        _, _, attempt = self.create_attempt()
        fresh = self.store.acquire_fence(attempt.attempt_id)
        with self.assertRaises(ConflictError):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.STARTING, 0, attempt.fencing_token)
        fresh = self.store.transition_attempt(attempt.attempt_id, AttemptState.STARTING, fresh.version, fresh.fencing_token)
        with self.assertRaises(ConflictError):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.RUNNING, 0, fresh.fencing_token)
        self.assertEqual(self.store.get_attempt(attempt.attempt_id).state, AttemptState.STARTING)


if __name__ == "__main__":
    unittest.main()
