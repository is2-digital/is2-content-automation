"""Tests for ica.guided.state — test-run state machine and persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from ica.guided.state import (
    GUIDED_STEP_ORDER,
    InvalidTransitionError,
    OperatorAction,
    RunPhase,
    StepRecord,
    StepStatus,
    TestRunNotFoundError,
    TestRunState,
    TestRunStateMachine,
    TestRunStore,
)
from ica.pipeline.orchestrator import StepName

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> TestRunStore:
    return TestRunStore(tmp_path / "test-runs")


def _make_sm(tmp_path: Path, run_id: str = "run-001") -> TestRunStateMachine:
    store = _make_store(tmp_path)
    state = TestRunState(run_id=run_id)
    return TestRunStateMachine(state, store)


def _started_sm(tmp_path: Path, run_id: str = "run-001") -> TestRunStateMachine:
    """Return a state machine that has already called ``start()``."""
    sm = _make_sm(tmp_path, run_id)
    sm.start()
    return sm


def _at_checkpoint(tmp_path: Path, *, failed: bool = False) -> TestRunStateMachine:
    """Return a state machine at its first checkpoint (step 0 done)."""
    sm = _started_sm(tmp_path)
    if failed:
        sm.fail_step("boom")
    else:
        sm.complete_step(artifacts={"doc_id": "abc"})
    return sm


# ---------------------------------------------------------------------------
# GUIDED_STEP_ORDER
# ---------------------------------------------------------------------------


class TestGuidedStepOrder:
    def test_contains_all_nine_steps(self):
        assert len(GUIDED_STEP_ORDER) == 9

    def test_sequential_before_parallel(self):
        names = [s.value for s in GUIDED_STEP_ORDER]
        assert names.index("html_generation") < names.index("alternates_html")

    def test_matches_step_name_enum(self):
        for step in GUIDED_STEP_ORDER:
            assert isinstance(step, StepName)


# ---------------------------------------------------------------------------
# TestRunState
# ---------------------------------------------------------------------------


class TestTestRunState:
    def test_defaults(self):
        state = TestRunState(run_id="r1")
        assert state.phase == RunPhase.NOT_STARTED
        assert state.current_step_index == 0
        assert len(state.steps) == 9
        assert state.steps[0].name == "curation"
        assert state.steps[-1].name == "linkedin_carousel"
        assert state.decisions == []
        assert state.context_snapshot == {}
        assert state.created_at  # non-empty
        assert state.updated_at  # non-empty

    def test_steps_initialized_from_guided_order(self):
        state = TestRunState(run_id="r2")
        step_names = [s.name for s in state.steps]
        expected = [s.value for s in GUIDED_STEP_ORDER]
        assert step_names == expected

    def test_all_steps_start_pending(self):
        state = TestRunState(run_id="r3")
        for step in state.steps:
            assert step.status == StepStatus.PENDING

    def test_current_step(self):
        state = TestRunState(run_id="r4")
        assert state.current_step.name == "curation"
        state.current_step_index = 3
        assert state.current_step.name == "markdown_generation"

    def test_current_step_name(self):
        state = TestRunState(run_id="r5")
        assert state.current_step_name == StepName.CURATION

    def test_is_last_step(self):
        state = TestRunState(run_id="r6")
        assert state.is_last_step is False
        state.current_step_index = len(state.steps) - 1
        assert state.is_last_step is True

    def test_existing_steps_not_overwritten(self):
        """Passing non-empty steps to __init__ should preserve them."""
        custom = [StepRecord(name="custom_step")]
        state = TestRunState(run_id="r7", steps=custom)
        assert len(state.steps) == 1
        assert state.steps[0].name == "custom_step"

    def test_existing_timestamps_preserved(self):
        state = TestRunState(run_id="r8", created_at="2024-01-01T00:00:00+00:00")
        assert state.created_at == "2024-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# State machine — start
# ---------------------------------------------------------------------------


class TestStart:
    def test_transitions_to_running(self, tmp_path: Path):
        sm = _make_sm(tmp_path)
        sm.start()
        assert sm.state.phase == RunPhase.RUNNING
        assert sm.state.current_step_index == 0
        assert sm.state.current_step.status == StepStatus.RUNNING
        assert sm.state.current_step.started_at is not None

    def test_rejects_double_start(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        with pytest.raises(InvalidTransitionError, match="expected 'not_started'"):
            sm.start()

    def test_persists_on_start(self, tmp_path: Path):
        sm = _make_sm(tmp_path)
        sm.start()
        loaded = sm._store.load("run-001")
        assert loaded.phase == RunPhase.RUNNING


# ---------------------------------------------------------------------------
# State machine — complete_step
# ---------------------------------------------------------------------------


class TestCompleteStep:
    def test_transitions_to_checkpoint(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        sm.complete_step()
        assert sm.state.phase == RunPhase.CHECKPOINT
        assert sm.state.current_step.status == StepStatus.COMPLETED
        assert sm.state.current_step.completed_at is not None

    def test_stores_artifacts(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        sm.complete_step(artifacts={"doc_id": "abc", "word_count": 500})
        assert sm.state.current_step.artifacts == {
            "doc_id": "abc",
            "word_count": 500,
        }

    def test_rejects_when_not_running(self, tmp_path: Path):
        sm = _make_sm(tmp_path)
        with pytest.raises(InvalidTransitionError, match="expected 'running'"):
            sm.complete_step()

    def test_rejects_when_step_not_running(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        sm.complete_step()
        # Now at checkpoint — if we somehow call again, phase check catches it
        with pytest.raises(InvalidTransitionError, match="expected 'running'"):
            sm.complete_step()


# ---------------------------------------------------------------------------
# State machine — fail_step
# ---------------------------------------------------------------------------


class TestFailStep:
    def test_transitions_to_checkpoint_with_error(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        sm.fail_step("LLM timeout")
        assert sm.state.phase == RunPhase.CHECKPOINT
        assert sm.state.current_step.status == StepStatus.FAILED
        assert sm.state.current_step.error == "LLM timeout"
        assert sm.state.current_step.completed_at is not None

    def test_rejects_when_not_running(self, tmp_path: Path):
        sm = _make_sm(tmp_path)
        with pytest.raises(InvalidTransitionError):
            sm.fail_step("error")


# ---------------------------------------------------------------------------
# State machine — apply_decision: CONTINUE
# ---------------------------------------------------------------------------


class TestContinue:
    def test_advances_to_next_step(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.CONTINUE)
        assert sm.state.phase == RunPhase.RUNNING
        assert sm.state.current_step_index == 1
        assert sm.state.current_step.name == "summarization"
        assert sm.state.current_step.status == StepStatus.RUNNING
        assert sm.state.current_step.started_at is not None

    def test_completes_run_on_last_step(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        # Advance through all 9 steps
        for step_idx in range(9):
            sm.complete_step()
            if step_idx < 8:
                sm.apply_decision(OperatorAction.CONTINUE)
        # At checkpoint on last step — continue should complete run
        sm.apply_decision(OperatorAction.CONTINUE)
        assert sm.state.phase == RunPhase.COMPLETED

    def test_rejects_continue_on_failed_step(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path, failed=True)
        with pytest.raises(InvalidTransitionError, match="must be completed"):
            sm.apply_decision(OperatorAction.CONTINUE)

    def test_records_decision(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.CONTINUE, note="looks good")
        assert len(sm.state.decisions) == 1
        d = sm.state.decisions[0]
        assert d.step == "curation"
        assert d.action == "continue"
        assert d.note == "looks good"
        assert d.timestamp  # non-empty

    def test_rejects_when_not_at_checkpoint(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        with pytest.raises(InvalidTransitionError, match="expected 'checkpoint'"):
            sm.apply_decision(OperatorAction.CONTINUE)


# ---------------------------------------------------------------------------
# State machine — apply_decision: REDO
# ---------------------------------------------------------------------------


class TestRedo:
    def test_resets_step_for_retry(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.REDO)
        assert sm.state.phase == RunPhase.RUNNING
        assert sm.state.current_step_index == 0
        step = sm.state.current_step
        assert step.status == StepStatus.RUNNING
        assert step.attempt == 2
        assert step.completed_at is None
        assert step.error is None

    def test_redo_after_failure(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path, failed=True)
        sm.apply_decision(OperatorAction.REDO)
        assert sm.state.phase == RunPhase.RUNNING
        assert sm.state.current_step.status == StepStatus.RUNNING
        assert sm.state.current_step.attempt == 2
        assert sm.state.current_step.error is None

    def test_multiple_redos_increment_attempt(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.REDO)
        sm.complete_step()
        sm.apply_decision(OperatorAction.REDO)
        assert sm.state.current_step.attempt == 3


# ---------------------------------------------------------------------------
# State machine — apply_decision: RESTART
# ---------------------------------------------------------------------------


class TestRestart:
    def test_resets_to_not_started(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.RESTART)
        assert sm.state.phase == RunPhase.NOT_STARTED
        assert sm.state.current_step_index == 0

    def test_resets_all_steps(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.RESTART)
        for step in sm.state.steps:
            assert step.status == StepStatus.PENDING
            assert step.attempt == 1
            assert step.started_at is None

    def test_clears_context_snapshot(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.save_context({"run_id": "run-001", "articles": [{"url": "x"}]})
        sm.apply_decision(OperatorAction.RESTART)
        assert sm.state.context_snapshot == {}

    def test_can_start_again_after_restart(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.RESTART)
        sm.start()
        assert sm.state.phase == RunPhase.RUNNING
        assert sm.state.current_step.name == "curation"


# ---------------------------------------------------------------------------
# State machine — apply_decision: STOP
# ---------------------------------------------------------------------------


class TestStop:
    def test_transitions_to_aborted(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.STOP)
        assert sm.state.phase == RunPhase.ABORTED

    def test_stop_after_failure(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path, failed=True)
        sm.apply_decision(OperatorAction.STOP, note="giving up")
        assert sm.state.phase == RunPhase.ABORTED
        assert sm.state.decisions[-1].note == "giving up"


# ---------------------------------------------------------------------------
# State machine — resume
# ---------------------------------------------------------------------------


class TestResume:
    def test_resume_resets_running_step(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        # Simulate crash: state is RUNNING, step is RUNNING
        sm.resume()
        step = sm.state.current_step
        assert step.status == StepStatus.RUNNING
        assert step.attempt == 2

    def test_resume_rejects_when_not_running(self, tmp_path: Path):
        sm = _make_sm(tmp_path)
        with pytest.raises(InvalidTransitionError, match="expected 'running'"):
            sm.resume()

    def test_resume_after_reload(self, tmp_path: Path):
        """Simulate a crash-and-reload cycle."""
        sm = _started_sm(tmp_path)
        sm.save_context({"run_id": "run-001", "articles": []})

        # "Crash" — reload from disk
        loaded_state = sm._store.load("run-001")
        sm2 = TestRunStateMachine(loaded_state, sm._store)
        assert sm2.state.phase == RunPhase.RUNNING

        sm2.resume()
        assert sm2.state.current_step.attempt == 2
        assert sm2.state.context_snapshot == {"run_id": "run-001", "articles": []}


# ---------------------------------------------------------------------------
# State machine — save_context
# ---------------------------------------------------------------------------


class TestSaveContext:
    def test_persists_snapshot(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        snapshot = {"run_id": "run-001", "articles": [{"url": "https://example.com"}]}
        sm.save_context(snapshot)
        loaded = sm._store.load("run-001")
        assert loaded.context_snapshot == snapshot


# ---------------------------------------------------------------------------
# Full workflow — multi-step progression
# ---------------------------------------------------------------------------


class TestFullWorkflow:
    def test_advance_through_three_steps(self, tmp_path: Path):
        sm = _started_sm(tmp_path)

        # Step 0: curation
        sm.complete_step(artifacts={"newsletter_id": "NL-1"})
        sm.apply_decision(OperatorAction.CONTINUE)

        # Step 1: summarization
        assert sm.state.current_step.name == "summarization"
        sm.complete_step()
        sm.apply_decision(OperatorAction.CONTINUE)

        # Step 2: theme_generation
        assert sm.state.current_step.name == "theme_generation"
        assert sm.state.current_step_index == 2
        assert sm.state.phase == RunPhase.RUNNING

    def test_fail_redo_then_continue(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        sm.fail_step("network error")
        sm.apply_decision(OperatorAction.REDO)
        sm.complete_step()
        sm.apply_decision(OperatorAction.CONTINUE)
        assert sm.state.current_step.name == "summarization"
        assert len(sm.state.decisions) == 2

    def test_full_run_to_completion(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        for _i in range(9):
            sm.complete_step()
            sm.apply_decision(OperatorAction.CONTINUE)
        assert sm.state.phase == RunPhase.COMPLETED
        assert len(sm.state.decisions) == 9


# ---------------------------------------------------------------------------
# Persistence — TestRunStore
# ---------------------------------------------------------------------------


class TestTestRunStore:
    def test_save_and_load_round_trip(self, tmp_path: Path):
        store = _make_store(tmp_path)
        state = TestRunState(run_id="rt-1")
        store.save(state)
        loaded = store.load("rt-1")
        assert loaded.run_id == "rt-1"
        assert loaded.phase == RunPhase.NOT_STARTED
        assert len(loaded.steps) == 9

    def test_load_preserves_step_status(self, tmp_path: Path):
        store = _make_store(tmp_path)
        state = TestRunState(run_id="rt-2")
        state.steps[0].status = StepStatus.COMPLETED
        state.steps[0].artifacts = {"key": "val"}
        store.save(state)
        loaded = store.load("rt-2")
        assert loaded.steps[0].status == StepStatus.COMPLETED
        assert loaded.steps[0].artifacts == {"key": "val"}

    def test_load_preserves_decisions(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.CONTINUE, note="approved")
        loaded = sm._store.load("run-001")
        assert len(loaded.decisions) == 1
        assert loaded.decisions[0].action == "continue"
        assert loaded.decisions[0].note == "approved"

    def test_load_nonexistent_raises(self, tmp_path: Path):
        store = _make_store(tmp_path)
        with pytest.raises(TestRunNotFoundError, match="no-such-run"):
            store.load("no-such-run")

    def test_list_runs_empty(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.list_runs() == []

    def test_list_runs(self, tmp_path: Path):
        store = _make_store(tmp_path)
        for rid in ["run-c", "run-a", "run-b"]:
            store.save(TestRunState(run_id=rid))
        assert store.list_runs() == ["run-a", "run-b", "run-c"]

    def test_delete(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(TestRunState(run_id="del-me"))
        assert "del-me" in store.list_runs()
        store.delete("del-me")
        assert "del-me" not in store.list_runs()

    def test_delete_nonexistent_is_noop(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.delete("nope")  # should not raise

    def test_creates_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "runs"
        store = TestRunStore(nested)
        store.save(TestRunState(run_id="r1"))
        assert nested.exists()

    def test_overwrite_on_save(self, tmp_path: Path):
        store = _make_store(tmp_path)
        state = TestRunState(run_id="ow-1")
        store.save(state)
        state.phase = RunPhase.COMPLETED
        store.save(state)
        loaded = store.load("ow-1")
        assert loaded.phase == RunPhase.COMPLETED


# ---------------------------------------------------------------------------
# Edge cases and invalid transitions
# ---------------------------------------------------------------------------


class TestInvalidTransitionErrors:
    def test_complete_on_not_started(self, tmp_path: Path):
        sm = _make_sm(tmp_path)
        with pytest.raises(InvalidTransitionError):
            sm.complete_step()

    def test_fail_on_not_started(self, tmp_path: Path):
        sm = _make_sm(tmp_path)
        with pytest.raises(InvalidTransitionError):
            sm.fail_step("error")

    def test_decision_on_running(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        with pytest.raises(InvalidTransitionError):
            sm.apply_decision(OperatorAction.CONTINUE)

    def test_decision_on_completed_run(self, tmp_path: Path):
        sm = _started_sm(tmp_path)
        for _i in range(9):
            sm.complete_step()
            sm.apply_decision(OperatorAction.CONTINUE)
        with pytest.raises(InvalidTransitionError):
            sm.apply_decision(OperatorAction.CONTINUE)

    def test_start_on_aborted(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        sm.apply_decision(OperatorAction.STOP)
        with pytest.raises(InvalidTransitionError):
            sm.start()

    def test_resume_on_checkpoint(self, tmp_path: Path):
        sm = _at_checkpoint(tmp_path)
        with pytest.raises(InvalidTransitionError):
            sm.resume()
