from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class ConflictError(RuntimeError):
    """The writer's version or fencing token is stale."""


class ImmutableError(RuntimeError):
    """An immutable durable object was modified."""


class InvalidTransition(RuntimeError):
    """An attempt state transition is not part of the semantic model."""


class AttemptState(str, Enum):
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    UNKNOWN = "UNKNOWN"
    RESOLVING = "RESOLVING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunState(str, Enum):
    OPEN = "OPEN"
    EXECUTING = "EXECUTING"
    WAITING_RECOVERY = "WAITING_RECOVERY"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


TERMINAL = {AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.CANCELLED}
TRANSITIONS = {
    AttemptState.PENDING: {AttemptState.STARTING, AttemptState.CANCELLED},
    AttemptState.STARTING: {AttemptState.RUNNING, AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.UNKNOWN},
    AttemptState.RUNNING: {AttemptState.WAITING, AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.UNKNOWN},
    AttemptState.WAITING: {AttemptState.RUNNING, AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.UNKNOWN},
    AttemptState.UNKNOWN: {AttemptState.RESOLVING},
    AttemptState.RESOLVING: {AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.CANCELLED},
    AttemptState.SUCCEEDED: set(),
    AttemptState.FAILED: set(),
    AttemptState.CANCELLED: set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Run:
    run_id: str
    intent: str
    created_at: str
    state: RunState
    version: int
    fencing_token: int


@dataclass(frozen=True)
class BindingEpoch:
    epoch_id: str
    binding_id: str
    number: int
    snapshot: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True)
class Binding:
    binding_id: str


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    run_id: str
    epoch_id: str
    state: AttemptState
    created_at: str
    updated_at: str
    version: int
    fencing_token: int
    execution_handle: str | None = None


class RuntimeStore:
    """Small SQLite-backed semantic store for the M1 durable core."""

    def __init__(self, path: str | Path = ":memory:"):
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, intent TEXT NOT NULL, created_at TEXT NOT NULL,
                state TEXT NOT NULL, version INTEGER NOT NULL, fencing_token INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bindings (
                binding_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS epochs (
                epoch_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, number INTEGER NOT NULL,
                snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(binding_id) REFERENCES bindings(binding_id),
                UNIQUE(binding_id, number)
            );
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, epoch_id TEXT NOT NULL,
                state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                version INTEGER NOT NULL, fencing_token INTEGER NOT NULL,
                execution_handle TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id),
                FOREIGN KEY(epoch_id) REFERENCES epochs(epoch_id)
            );
            CREATE TABLE IF NOT EXISTS transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL,
                from_state TEXT NOT NULL, to_state TEXT NOT NULL, version INTEGER NOT NULL,
                fencing_token INTEGER NOT NULL, occurred_at TEXT NOT NULL,
                FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id)
            );
            CREATE TABLE IF NOT EXISTS run_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                from_state TEXT NOT NULL, to_state TEXT NOT NULL, version INTEGER NOT NULL,
                fencing_token INTEGER NOT NULL, occurred_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            """
        )

    def close(self) -> None:
        self._db.close()

    def create_run(self, intent: str) -> Run:
        value = (str(uuid.uuid4()), intent, _now(), RunState.OPEN.value, 0, 1)
        self._db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", value)
        return self.get_run(value[0])

    def get_run(self, run_id: str) -> Run:
        row = self._db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return Run(row["run_id"], row["intent"], row["created_at"], RunState(row["state"]), row["version"], row["fencing_token"])

    def acquire_run_fence(self, run_id: str) -> Run:
        with self._db:
            if self._db.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone() is None:
                raise KeyError(run_id)
            self._db.execute("UPDATE runs SET version = version + 1, fencing_token = fencing_token + 1 WHERE run_id = ?", (run_id,))
        return self.get_run(run_id)

    def transition_run(self, run_id: str, state: RunState, expected_version: int, fencing_token: int) -> Run:
        state = RunState(state)
        allowed = {
            RunState.OPEN: {RunState.EXECUTING, RunState.CANCELLED, RunState.UNKNOWN},
            RunState.EXECUTING: {RunState.WAITING_RECOVERY, RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED, RunState.UNKNOWN},
            RunState.WAITING_RECOVERY: {RunState.EXECUTING, RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED, RunState.UNKNOWN},
            RunState.UNKNOWN: {RunState.WAITING_RECOVERY},
            RunState.SUCCEEDED: set(), RunState.FAILED: set(), RunState.CANCELLED: set(),
        }
        with self._db:
            row = self._db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = RunState(row["state"])
            if row["version"] != expected_version or row["fencing_token"] != fencing_token:
                raise ConflictError(f"stale run writer: {run_id}")
            if state not in allowed[current]:
                raise InvalidTransition(f"{current.value} -> {state.value}")
            self._db.execute("UPDATE runs SET state = ?, version = version + 1 WHERE run_id = ? AND version = ? AND fencing_token = ?", (state.value, run_id, expected_version, fencing_token))
            self._db.execute("INSERT INTO run_transitions(run_id, from_state, to_state, version, fencing_token, occurred_at) VALUES (?, ?, ?, ?, ?, ?)", (run_id, current.value, state.value, expected_version + 1, fencing_token, _now()))
        return self.get_run(run_id)

    def run_transition_history(self, run_id: str) -> list[tuple[str, str, int, int, str]]:
        return [tuple(row) for row in self._db.execute("SELECT from_state, to_state, version, fencing_token, occurred_at FROM run_transitions WHERE run_id = ? ORDER BY id", (run_id,))]

    def create_binding_epoch(self, binding_id: str, snapshot: Mapping[str, Any]) -> BindingEpoch:
        self.create_binding(binding_id)
        number = self._db.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM epochs WHERE binding_id = ?", (binding_id,)).fetchone()[0]
        epoch_id = str(uuid.uuid4())
        self._db.execute("INSERT INTO epochs VALUES (?, ?, ?, ?, ?)", (epoch_id, binding_id, number, json.dumps(dict(snapshot), sort_keys=True), _now()))
        return self.get_binding_epoch(epoch_id)

    def create_binding(self, binding_id: str | None = None) -> Binding:
        binding_id = binding_id or str(uuid.uuid4())
        self._db.execute("INSERT OR IGNORE INTO bindings(binding_id) VALUES (?)", (binding_id,))
        return Binding(binding_id)

    def get_binding(self, binding_id: str) -> Binding:
        if self._db.execute("SELECT 1 FROM bindings WHERE binding_id = ?", (binding_id,)).fetchone() is None:
            raise KeyError(binding_id)
        return Binding(binding_id)

    def get_binding_epoch(self, epoch_id: str) -> BindingEpoch:
        row = self._db.execute("SELECT * FROM epochs WHERE epoch_id = ?", (epoch_id,)).fetchone()
        if row is None:
            raise KeyError(epoch_id)
        return BindingEpoch(row["epoch_id"], row["binding_id"], row["number"], MappingProxyType(json.loads(row["snapshot"])), row["created_at"])

    def update_binding_epoch(self, epoch_id: str, snapshot: Mapping[str, Any]) -> None:
        raise ImmutableError(f"binding epoch {epoch_id} is immutable")

    def create_attempt(self, run_id: str, epoch_id: str) -> Attempt:
        self.get_run(run_id)
        self.get_binding_epoch(epoch_id)
        now = _now()
        attempt_id = str(uuid.uuid4())
        self._db.execute("INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (attempt_id, run_id, epoch_id, AttemptState.PENDING.value, now, now, 0, 1, None))
        return self.get_attempt(attempt_id)

    def get_attempt(self, attempt_id: str) -> Attempt:
        row = self._db.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        return Attempt(row["attempt_id"], row["run_id"], row["epoch_id"], AttemptState(row["state"]), row["created_at"], row["updated_at"], row["version"], row["fencing_token"], row["execution_handle"])

    def list_attempts(self, run_id: str) -> list[Attempt]:
        return [self.get_attempt(row["attempt_id"]) for row in self._db.execute("SELECT attempt_id FROM attempts WHERE run_id = ? ORDER BY created_at", (run_id,))]

    def acquire_fence(self, attempt_id: str) -> Attempt:
        with self._db:
            row = self._db.execute("SELECT version, fencing_token FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            self._db.execute("UPDATE attempts SET version = version + 1, fencing_token = fencing_token + 1, updated_at = ? WHERE attempt_id = ?", (_now(), attempt_id))
        return self.get_attempt(attempt_id)

    def transition_attempt(self, attempt_id: str, state: AttemptState, expected_version: int, fencing_token: int) -> Attempt:
        state = AttemptState(state)
        with self._db:
            row = self._db.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            current = AttemptState(row["state"])
            if row["version"] != expected_version or row["fencing_token"] != fencing_token:
                raise ConflictError(f"stale attempt writer: {attempt_id}")
            if state not in TRANSITIONS[current]:
                raise InvalidTransition(f"{current.value} -> {state.value}")
            version = expected_version + 1
            now = _now()
            self._db.execute("UPDATE attempts SET state = ?, version = ?, updated_at = ? WHERE attempt_id = ? AND version = ? AND fencing_token = ?", (state.value, version, now, attempt_id, expected_version, fencing_token))
            if self._db.execute("SELECT changes()").fetchone()[0] != 1:
                raise ConflictError(f"stale attempt writer: {attempt_id}")
            self._db.execute("INSERT INTO transitions(attempt_id, from_state, to_state, version, fencing_token, occurred_at) VALUES (?, ?, ?, ?, ?, ?)", (attempt_id, current.value, state.value, version, fencing_token, now))
        return self.get_attempt(attempt_id)

    def transition_history(self, attempt_id: str) -> list[tuple[str, str, int, int, str]]:
        return [tuple(row) for row in self._db.execute("SELECT from_state, to_state, version, fencing_token, occurred_at FROM transitions WHERE attempt_id = ? ORDER BY id", (attempt_id,))]
