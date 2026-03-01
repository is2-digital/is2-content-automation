"""Test-run state machine for the guided pipeline test flow.

Provides a persisted state model that tracks a test run through the pipeline
step-by-step, supporting continue, redo, restart, and resume-after-crash
operations at each checkpoint.

Persistence uses JSON files — one per test run — so state survives process
restarts without requiring database migrations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from ica.pipeline.orchestrator import StepName

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RunPhase(StrEnum):
    """Overall test-run lifecycle phase."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    CHECKPOINT = "checkpoint"
    COMPLETED = "completed"
    ABORTED = "aborted"


class StepStatus(StrEnum):
    """Status of an individual step within a test run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OperatorAction(StrEnum):
    """Actions an operator can take at a checkpoint."""

    CONTINUE = "continue"
    REDO = "redo"
    RESTART = "restart"
    STOP = "stop"


# ---------------------------------------------------------------------------
# Step ordering — all 9 steps run sequentially in guided mode
# ---------------------------------------------------------------------------

GUIDED_STEP_ORDER: list[StepName] = [
    StepName.CURATION,
    StepName.SUMMARIZATION,
    StepName.THEME_GENERATION,
    StepName.MARKDOWN_GENERATION,
    StepName.HTML_GENERATION,
    StepName.ALTERNATES_HTML,
    StepName.EMAIL_SUBJECT,
    StepName.SOCIAL_MEDIA,
    StepName.LINKEDIN_CAROUSEL,
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class StepRecord:
    """Record of a single step execution within a test run.

    Redo semantics for Google resources:

    * **Google Docs** — each redo creates a *new* document so the operator
      can compare attempts side-by-side.  The previous document ID is
      preserved in ``artifact_history``; it is **not** overwritten or
      deleted.
    * **Google Sheets** — each redo appends new rows tagged with an
      ``attempt`` number so data from all attempts remains visible in
      the same spreadsheet.
    * ``artifact_history`` accumulates one entry per completed attempt
      before a redo, keyed by attempt number.  This lets the operator
      (and downstream integration tests) trace every Google resource
      created across the run.
    """

    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    attempt: int = 1
    artifacts: dict[str, Any] = field(default_factory=dict)
    artifact_history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OperatorDecision:
    """Record of an operator decision at a checkpoint."""

    step: str
    action: str
    timestamp: str
    note: str | None = None


@dataclass
class TestRunState:
    """Persisted state for a guided pipeline test run.

    Attributes:
        run_id: Unique identifier for the test run.
        phase: Current lifecycle phase of the run.
        current_step_index: Index into :data:`GUIDED_STEP_ORDER`.
        steps: Per-step execution records.
        decisions: History of operator decisions.
        context_snapshot: Serialised ``PipelineContext`` for resume.
        created_at: ISO timestamp when the run was created.
        updated_at: ISO timestamp of last state change.
    """

    __test__ = False

    run_id: str
    phase: RunPhase = RunPhase.NOT_STARTED
    current_step_index: int = 0
    steps: list[StepRecord] = field(default_factory=list)
    decisions: list[OperatorDecision] = field(default_factory=list)
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = _now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.steps:
            self.steps = [StepRecord(name=s.value) for s in GUIDED_STEP_ORDER]

    @property
    def current_step(self) -> StepRecord:
        """The step record at :attr:`current_step_index`."""
        return self.steps[self.current_step_index]

    @property
    def current_step_name(self) -> StepName:
        """The :class:`StepName` of the current step."""
        return StepName(self.current_step.name)

    @property
    def is_last_step(self) -> bool:
        """Whether the current step is the final one in the guided order."""
        return self.current_step_index >= len(self.steps) - 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """Raised when a state transition violates the state machine rules."""


class TestRunNotFoundError(Exception):
    """Raised when a requested test run file does not exist."""

    __test__ = False


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestRunStateMachine:
    """Manages state transitions and persistence for a guided test run.

    All mutating methods validate the transition, update the state, and
    persist to the backing :class:`TestRunStore` atomically.
    """

    __test__ = False

    def __init__(self, state: TestRunState, store: TestRunStore) -> None:
        self._state = state
        self._store = store

    @property
    def state(self) -> TestRunState:
        return self._state

    # --- Lifecycle transitions ---

    def start(self) -> None:
        """Begin the test run from the first step.

        Raises:
            InvalidTransition: If the run is not in ``NOT_STARTED`` phase.
        """
        self._require_phase(RunPhase.NOT_STARTED, "start")
        self._state.phase = RunPhase.RUNNING
        self._state.current_step_index = 0
        step = self._state.current_step
        step.status = StepStatus.RUNNING
        step.started_at = _now_iso()
        self._save()

    def complete_step(self, *, artifacts: dict[str, Any] | None = None) -> None:
        """Mark the current step as completed and enter checkpoint.

        Args:
            artifacts: Optional outputs to record on the step.

        Raises:
            InvalidTransition: If not in ``RUNNING`` phase or step is not running.
        """
        self._require_phase(RunPhase.RUNNING, "complete step")
        step = self._state.current_step
        self._require_step_status(step, StepStatus.RUNNING, "complete")
        step.status = StepStatus.COMPLETED
        step.completed_at = _now_iso()
        if artifacts:
            step.artifacts.update(artifacts)
        self._state.phase = RunPhase.CHECKPOINT
        self._save()

    def fail_step(self, error: str) -> None:
        """Mark the current step as failed and enter checkpoint.

        Args:
            error: Description of the failure.

        Raises:
            InvalidTransition: If not in ``RUNNING`` phase or step is not running.
        """
        self._require_phase(RunPhase.RUNNING, "fail step")
        step = self._state.current_step
        self._require_step_status(step, StepStatus.RUNNING, "fail")
        step.status = StepStatus.FAILED
        step.completed_at = _now_iso()
        step.error = error
        self._state.phase = RunPhase.CHECKPOINT
        self._save()

    def apply_decision(self, action: OperatorAction, *, note: str | None = None) -> None:
        """Apply an operator decision at a checkpoint.

        Args:
            action: The operator's chosen action.
            note: Optional free-text note for the decision log.

        Raises:
            InvalidTransition: If not at a checkpoint, or if ``CONTINUE``
                is attempted on a failed step.
        """
        self._require_phase(RunPhase.CHECKPOINT, "apply decision")
        current = self._state.current_step

        self._state.decisions.append(
            OperatorDecision(
                step=current.name,
                action=action.value,
                timestamp=_now_iso(),
                note=note,
            )
        )

        if action == OperatorAction.CONTINUE:
            if current.status != StepStatus.COMPLETED:
                raise InvalidTransitionError(
                    f"Cannot continue: step '{current.name}' has status "
                    f"'{current.status}', must be completed"
                )
            if self._state.is_last_step:
                self._state.phase = RunPhase.COMPLETED
            else:
                self._state.current_step_index += 1
                self._state.phase = RunPhase.RUNNING
                next_step = self._state.current_step
                next_step.status = StepStatus.RUNNING
                next_step.started_at = _now_iso()

        elif action == OperatorAction.REDO:
            # Archive the current attempt's artifacts before resetting so
            # the operator can trace every Google Doc / Sheet produced
            # across attempts.
            if current.artifacts:
                current.artifact_history.append(
                    {"attempt": current.attempt, "artifacts": dict(current.artifacts)}
                )
            current.artifacts = {}
            current.status = StepStatus.RUNNING
            current.started_at = _now_iso()
            current.completed_at = None
            current.error = None
            current.attempt += 1
            self._state.phase = RunPhase.RUNNING

        elif action == OperatorAction.RESTART:
            self._state.phase = RunPhase.NOT_STARTED
            self._state.current_step_index = 0
            self._state.steps = [StepRecord(name=s.value) for s in GUIDED_STEP_ORDER]
            self._state.context_snapshot = {}

        elif action == OperatorAction.STOP:
            self._state.phase = RunPhase.ABORTED

        self._save()

    def resume(self) -> None:
        """Resume after an interruption (e.g. process crash while running).

        Resets the current step for a fresh attempt, incrementing the attempt
        counter. This is safe because a partially-executed step cannot be
        trusted.

        Raises:
            InvalidTransition: If the run is not in ``RUNNING`` phase.
        """
        self._require_phase(RunPhase.RUNNING, "resume")
        step = self._state.current_step
        step.status = StepStatus.RUNNING
        step.started_at = _now_iso()
        step.completed_at = None
        step.error = None
        step.attempt += 1
        self._save()

    def save_context(self, snapshot: dict[str, Any]) -> None:
        """Persist a ``PipelineContext`` snapshot for later resume."""
        self._state.context_snapshot = snapshot
        self._save()

    # --- Internal helpers ---

    def _require_phase(self, expected: RunPhase, action: str) -> None:
        if self._state.phase != expected:
            raise InvalidTransitionError(
                f"Cannot {action}: run is '{self._state.phase}', expected '{expected}'"
            )

    def _require_step_status(self, step: StepRecord, expected: StepStatus, action: str) -> None:
        if step.status != expected:
            raise InvalidTransitionError(
                f"Cannot {action} step '{step.name}': status is "
                f"'{step.status}', expected '{expected}'"
            )

    def _save(self) -> None:
        self._state.updated_at = _now_iso()
        self._store.save(self._state)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestRunStore:
    """JSON-file-based persistence for test run state.

    Each test run is stored as a separate ``{run_id}.json`` file under
    *base_dir*.
    """

    __test__ = False

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def save(self, state: TestRunState) -> None:
        """Write *state* to disk."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        path = self._run_path(state.run_id)
        data = _serialize_state(state)
        path.write_text(json.dumps(data, indent=2))

    def load(self, run_id: str) -> TestRunState:
        """Load a test run by *run_id*.

        Raises:
            TestRunNotFound: If no file exists for *run_id*.
        """
        path = self._run_path(run_id)
        if not path.exists():
            raise TestRunNotFoundError(f"No test run found: {run_id}")
        data = json.loads(path.read_text())
        return _deserialize_state(data)

    def list_runs(self) -> list[str]:
        """Return sorted run IDs for all persisted test runs."""
        if not self._base_dir.exists():
            return []
        return sorted(p.stem for p in self._base_dir.glob("*.json"))

    def delete(self, run_id: str) -> None:
        """Delete a test run file. No-op if it doesn't exist."""
        path = self._run_path(run_id)
        if path.exists():
            path.unlink()

    def _run_path(self, run_id: str) -> Path:
        return self._base_dir / f"{run_id}.json"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_state(state: TestRunState) -> dict[str, Any]:
    """Convert a ``TestRunState`` to a JSON-compatible dict."""
    return asdict(state)


def _deserialize_state(data: dict[str, Any]) -> TestRunState:
    """Reconstruct a ``TestRunState`` from a dict (as loaded from JSON)."""
    steps = [
        StepRecord(
            name=s["name"],
            status=StepStatus(s["status"]),
            started_at=s.get("started_at"),
            completed_at=s.get("completed_at"),
            error=s.get("error"),
            attempt=s.get("attempt", 1),
            artifacts=s.get("artifacts", {}),
            artifact_history=s.get("artifact_history", []),
        )
        for s in data.pop("steps", [])
    ]
    decisions = [OperatorDecision(**d) for d in data.pop("decisions", [])]
    data["phase"] = RunPhase(data["phase"])
    return TestRunState(**data, steps=steps, decisions=decisions)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()
