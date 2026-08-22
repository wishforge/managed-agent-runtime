import sqlite3
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

    def running_attempt(self):
        run, epoch, attempt = self.create_attempt()
        attempt = self.store.transition_attempt(attempt.attempt_id, AttemptState.STARTING, attempt.version, attempt.fencing_token)
        attempt = self.store.transition_attempt(attempt.attempt_id, AttemptState.RUNNING, attempt.version, attempt.fencing_token)
        return run, epoch, attempt

    def test_terminal_run_cannot_create_attempt(self):
        for terminal in (RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED):
            with self.subTest(terminal=terminal):
                run = self.store.create_run(terminal.value)
                current = self.store.transition_run(run.run_id, RunState.EXECUTING, run.version, run.fencing_token)
                current = self.store.transition_run(run.run_id, terminal, current.version, current.fencing_token)
                epoch = self.store.create_binding_epoch(f"binding-{terminal.value}", {"provider": "local"})
                before = self.store.list_attempts(run.run_id)
                history = self.store.run_transition_history(run.run_id)
                with self.assertRaises(InvalidTransition):
                    self.store.create_attempt(run.run_id, epoch.epoch_id)
                self.assertEqual(self.store.get_run(run.run_id), current)
                self.assertEqual(self.store.list_attempts(run.run_id), before)
                self.assertEqual(self.store.run_transition_history(run.run_id), history)

    def test_running_to_succeeded_requires_evidence(self):
        _, _, attempt = self.running_attempt()
        with self.assertRaises(ValueError):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.SUCCEEDED, attempt.version, attempt.fencing_token)

    def test_running_to_succeeded_accepts_required_evidence(self):
        _, _, attempt = self.running_attempt()
        succeeded = self.store.transition_attempt(
            attempt.attempt_id, AttemptState.SUCCEEDED, attempt.version, attempt.fencing_token,
            cause="completed", boundary="result", observation={"result": "ok"},
        )
        self.assertEqual(succeeded.state, AttemptState.SUCCEEDED)

    def test_running_to_failed_requires_evidence(self):
        _, _, attempt = self.running_attempt()
        with self.assertRaises(ValueError):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.FAILED, attempt.version, attempt.fencing_token)

    def test_running_to_failed_accepts_required_evidence(self):
        _, _, attempt = self.running_attempt()
        failed = self.store.transition_attempt(
            attempt.attempt_id, AttemptState.FAILED, attempt.version, attempt.fencing_token,
            cause="error", boundary="execution", observation={"error": "boom"},
        )
        self.assertEqual(failed.state, AttemptState.FAILED)

    def test_running_to_cancelled_requires_evidence(self):
        _, _, attempt = self.running_attempt()
        with self.assertRaises(ValueError):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.CANCELLED, attempt.version, attempt.fencing_token)

    def test_running_to_cancelled_accepts_required_evidence(self):
        _, _, attempt = self.running_attempt()
        cancelled = self.store.transition_attempt(
            attempt.attempt_id, AttemptState.CANCELLED, attempt.version, attempt.fencing_token,
            cause="cancelled", boundary="control", observation={"requested": True},
        )
        self.assertEqual(cancelled.state, AttemptState.CANCELLED)

    def test_resolving_to_succeeded_requires_verification_evidence(self):
        _, _, attempt = self.running_attempt()
        attempt = self.store.transition_attempt(
            attempt.attempt_id, AttemptState.UNKNOWN, attempt.version, attempt.fencing_token,
            cause="lost", boundary="transport", observation={"request_id": "r1"},
        )
        attempt = self.store.transition_attempt(attempt.attempt_id, AttemptState.RESOLVING, attempt.version, attempt.fencing_token)
        with self.assertRaises(ValueError):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.SUCCEEDED, attempt.version, attempt.fencing_token)

    def test_unknown_requires_evidence(self):
        _, _, attempt = self.create_attempt()
        attempt = self.store.transition_attempt(attempt.attempt_id, AttemptState.STARTING, attempt.version, attempt.fencing_token)
        with self.assertRaises(ValueError):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.UNKNOWN, attempt.version, attempt.fencing_token)

    def test_unknown_cannot_directly_transition_to_failed(self):
        _, _, attempt = self.running_attempt()
        attempt = self.store.transition_attempt(
            attempt.attempt_id, AttemptState.UNKNOWN, attempt.version, attempt.fencing_token,
            cause="lost", boundary="transport", observation="not observed",
        )
        with self.assertRaises(InvalidTransition):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.FAILED, attempt.version, attempt.fencing_token)

    def test_epoch_snapshot_is_deeply_immutable(self):
        epoch = self.store.create_binding_epoch("binding-deep", {"model": {"name": "test", "parameters": {"temperature": 0.2}}})
        with self.assertRaises(TypeError):
            epoch.snapshot["model"]["parameters"]["temperature"] = 1.0

    def test_epoch_snapshot_nested_list_is_immutable(self):
        epoch = self.store.create_binding_epoch("binding-list", {"tools": [{"name": "shell"}]})
        with self.assertRaises(AttributeError):
            epoch.snapshot["tools"].append({"name": "python"})

    def test_epoch_snapshot_isolated_from_input_mutation(self):
        source = {"dict": {"list": [{"value": 1}]}}
        epoch = self.store.create_binding_epoch("binding-isolated", source)
        source["dict"]["list"][0]["value"] = 2
        source["dict"]["list"].append({"value": 3})
        self.assertEqual(epoch.snapshot["dict"]["list"][0]["value"], 1)
        self.assertEqual(len(epoch.snapshot["dict"]["list"]), 1)

    def test_epoch_snapshot_survives_restart(self):
        source = {"model": {"parameters": {"temperature": 0.2}}, "tools": [{"name": "shell"}]}
        epoch = self.store.create_binding_epoch("binding-restart", source)
        expected = epoch.snapshot
        self.store.close()
        self.store = RuntimeStore(self.path)
        recovered = self.store.get_binding_epoch(epoch.epoch_id)
        self.assertEqual(recovered.snapshot, expected)
        with self.assertRaises(TypeError):
            recovered.snapshot["model"]["parameters"]["temperature"] = 1.0

    def test_runtime_store_does_not_implicitly_migrate_schema(self):
        self.store.close()
        self.path.unlink()
        old = sqlite3.connect(self.path)
        old.executescript("""
            CREATE TABLE runs (run_id TEXT PRIMARY KEY, intent TEXT NOT NULL, created_at TEXT NOT NULL, state TEXT NOT NULL, version INTEGER NOT NULL, fencing_token INTEGER NOT NULL);
            CREATE TABLE bindings (binding_id TEXT PRIMARY KEY);
            CREATE TABLE epochs (epoch_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, number INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(binding_id) REFERENCES bindings(binding_id), UNIQUE(binding_id, number));
            CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, epoch_id TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL, fencing_token INTEGER NOT NULL, execution_handle TEXT, FOREIGN KEY(run_id) REFERENCES runs(run_id), FOREIGN KEY(epoch_id) REFERENCES epochs(epoch_id));
            CREATE TABLE transitions (id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL, version INTEGER NOT NULL, fencing_token INTEGER NOT NULL, occurred_at TEXT NOT NULL, FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id));
            CREATE TABLE run_transitions (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL, version INTEGER NOT NULL, fencing_token INTEGER NOT NULL, occurred_at TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id));
        """)
        old.close()
        def schema(connection):
            tables = connection.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
            columns = {
                name: connection.execute(f"PRAGMA table_info({name})").fetchall()
                for name, _ in tables
            }
            return tables, columns

        connection = sqlite3.connect(self.path)
        before = schema(connection)
        connection.close()
        with self.assertRaises(sqlite3.OperationalError):
            RuntimeStore(self.path)
        connection = sqlite3.connect(self.path)
        self.assertEqual(schema(connection), before)
        connection.close()
        self.store = RuntimeStore(":memory:")

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
        current = self.store.transition_attempt(current.attempt_id, AttemptState.STARTING, current.version, current.fencing_token)
        current = self.store.transition_attempt(current.attempt_id, AttemptState.RUNNING, current.version, current.fencing_token)
        # UNKNOWN is durable only when its cause, boundary, and observation are recorded.
        current = self.store.transition_attempt(
            current.attempt_id,
            AttemptState.UNKNOWN,
            current.version,
            current.fencing_token,
            cause="transport_lost",
            boundary="request/response",
            observation={"request_id": "req-1"},
        )
        current = self.store.transition_attempt(current.attempt_id, AttemptState.RESOLVING, current.version, current.fencing_token)
        self.assertEqual(current.state, AttemptState.RESOLVING)
        with self.assertRaises(InvalidTransition):
            self.store.transition_attempt(current.attempt_id, AttemptState.RUNNING, current.version, current.fencing_token)
        current = self.store.transition_attempt(
            current.attempt_id, AttemptState.SUCCEEDED, current.version, current.fencing_token,
            cause="verified", boundary="result", observation={"result": "ok"},
        )
        self.assertEqual(len(self.store.transition_history(current.attempt_id)), 5)
        with self.assertRaises(InvalidTransition):
            self.store.transition_attempt(current.attempt_id, AttemptState.RUNNING, current.version, current.fencing_token)

    def test_unknown_evidence_survives_restart(self):
        run, _, attempt = self.create_attempt()
        unknown = self.store.transition_attempt(
            attempt.attempt_id,
            AttemptState.STARTING,
            attempt.version,
            attempt.fencing_token,
        )
        unknown = self.store.transition_attempt(
            unknown.attempt_id,
            AttemptState.UNKNOWN,
            unknown.version,
            unknown.fencing_token,
            cause="session_lost",
            boundary="execution_handle",
            observation={"handle": "h-1", "last_seen": "starting"},
        )
        evidence = self.store.unknown_evidence(unknown.attempt_id)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].cause, "session_lost")
        self.assertEqual(evidence[0].boundary, "execution_handle")
        self.assertEqual(evidence[0].observation["handle"], "h-1")
        self.store.close()
        self.store = RuntimeStore(self.path)
        self.assertEqual(self.store.get_attempt(unknown.attempt_id).state, AttemptState.UNKNOWN)
        self.assertEqual(self.store.unknown_evidence(unknown.attempt_id), evidence)

    def test_unknown_to_resolving_writes_recovery_record(self):
        _, _, attempt = self.create_attempt()
        current = self.store.transition_attempt(attempt.attempt_id, AttemptState.STARTING, 0, 1)
        current = self.store.transition_attempt(
            current.attempt_id,
            AttemptState.UNKNOWN,
            current.version,
            current.fencing_token,
            cause="event_gap",
            boundary="transport",
            observation="response was not observed",
        )
        self.store.transition_attempt(current.attempt_id, AttemptState.RESOLVING, current.version, current.fencing_token)
        recoveries = self.store.recovery_history(current.attempt_id)
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].from_state, AttemptState.UNKNOWN)
        self.assertEqual(recoveries[0].to_state, AttemptState.RESOLVING)
        self.store.close()
        self.store = RuntimeStore(self.path)
        self.assertEqual(self.store.recovery_history(current.attempt_id), recoveries)

    def test_unknown_requires_evidence_and_cannot_fail_directly(self):
        _, _, attempt = self.create_attempt()
        with self.assertRaises(InvalidTransition):
            self.store.transition_attempt(attempt.attempt_id, AttemptState.UNKNOWN, 0, 1)
        current = self.store.transition_attempt(
            attempt.attempt_id,
            AttemptState.STARTING,
            0,
            1,
        )
        with self.assertRaises(ValueError):
            self.store.transition_attempt(current.attempt_id, AttemptState.UNKNOWN, current.version, current.fencing_token)
        current = self.store.transition_attempt(
            current.attempt_id,
            AttemptState.UNKNOWN,
            current.version,
            current.fencing_token,
            cause="lost",
            boundary="process",
            observation="crashed",
        )
        with self.assertRaises(InvalidTransition):
            self.store.transition_attempt(current.attempt_id, AttemptState.FAILED, current.version, current.fencing_token)

    def test_new_binding_epoch_closes_old_epoch_admission(self):
        run = self.store.create_run("ship it")
        epoch1 = self.store.create_binding_epoch("binding-1", {"provider": "one"})
        first_attempt = self.store.create_attempt(run.run_id, epoch1.epoch_id)
        epoch2 = self.store.create_binding_epoch("binding-1", {"provider": "two"})
        self.assertTrue(self.store.get_binding_epoch(epoch1.epoch_id).admission_closed)
        self.assertFalse(epoch2.admission_closed)
        self.assertEqual(self.store.get_attempt(first_attempt.attempt_id).epoch_id, epoch1.epoch_id)
        with self.assertRaises(ConflictError):
            self.store.create_attempt(run.run_id, epoch1.epoch_id)
        second_attempt = self.store.create_attempt(run.run_id, epoch2.epoch_id)
        self.assertEqual(second_attempt.epoch_id, epoch2.epoch_id)

    def test_run_stale_writer_has_no_phantom_history(self):
        run = self.store.create_run("ship it")
        stale = run
        winner = self.store.transition_run(run.run_id, RunState.EXECUTING, run.version, run.fencing_token)
        history = self.store.run_transition_history(run.run_id)
        with self.assertRaises(ConflictError):
            self.store.transition_run(run.run_id, RunState.CANCELLED, stale.version, stale.fencing_token)
        self.assertEqual(self.store.get_run(run.run_id), winner)
        self.assertEqual(self.store.run_transition_history(run.run_id), history)

    def test_run_competing_writers_have_one_winner_and_one_history_append(self):
        run = self.store.create_run("ship it")
        other = RuntimeStore(self.path)
        try:
            writer_a = self.store.get_run(run.run_id)
            writer_b = other.get_run(run.run_id)
            outcomes = []
            for store, snapshot, state in (
                (self.store, writer_a, RunState.EXECUTING),
                (other, writer_b, RunState.CANCELLED),
            ):
                try:
                    store.transition_run(run.run_id, state, snapshot.version, snapshot.fencing_token)
                    outcomes.append("success")
                except ConflictError:
                    outcomes.append("conflict")
            self.assertEqual(outcomes.count("success"), 1)
            self.assertEqual(outcomes.count("conflict"), 1)
            self.assertEqual(len(self.store.run_transition_history(run.run_id)), 1)
        finally:
            other.close()

    def test_run_history_survives_restart(self):
        run = self.store.create_run("ship it")
        current = run
        for state in (RunState.EXECUTING, RunState.WAITING_RECOVERY, RunState.SUCCEEDED):
            current = self.store.transition_run(run.run_id, state, current.version, current.fencing_token)
        history = self.store.run_transition_history(run.run_id)
        self.store.close()
        self.store = RuntimeStore(self.path)
        self.assertEqual(self.store.run_transition_history(run.run_id), history)

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
