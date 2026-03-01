"""Guided-flow verification suite with replay fixtures.

End-to-end tests validating state-machine and artifact-ledger consistency
across the full guided pipeline flow.  Uses replay fixture JSON files
(golden files) to detect regressions in state transitions, artifact emission,
and cross-cutting invariants.

Run the verification suite::

    docker exec ica-app-1 python -m pytest tests/test_guided/test_verification.py -v

Acceptance criteria (ica-476.9):
    1) Full happy path from step 1 through final assets
    2) At least one redo branch and one resume-after-interruption branch
    3) Run-state and artifact-ledger consistency validated
    4) Referenced from CLI help / verification docs
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from ica.guided.artifacts import ArtifactLedger, ArtifactStore, ArtifactType
from ica.guided.runner import run_guided
from ica.guided.state import RunPhase, StepStatus, TestRunState, TestRunStore
from ica.pipeline.orchestrator import PipelineContext, StepName

# ---------------------------------------------------------------------------
# Fixture data — same as test_artifact_completeness (step populators)
# ---------------------------------------------------------------------------

_SHEETS_REFS = {
    "spreadsheet_id": "sheet-test-001",
    "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet-test-001/edit",
    "sheet_name": "Sheet1",
}


def _populate_curation(ctx: PipelineContext) -> None:
    ctx.articles = [{"title": "AI Revolution", "url": "https://example.com/1"}]
    ctx.newsletter_id = "nl-test-001"


def _populate_summarization(ctx: PipelineContext) -> None:
    ctx.summaries = [{"url": "https://example.com/1", "summary": "AI is changing..."}]


def _populate_theme_generation(ctx: PipelineContext) -> None:
    ctx.theme_name = "The Rise of AI Agents"


def _populate_markdown_generation(ctx: PipelineContext) -> None:
    ctx.markdown_doc_id = "md-doc-001"


def _populate_html_generation(ctx: PipelineContext) -> None:
    ctx.html_doc_id = "html-doc-001"


def _populate_alternates_html(ctx: PipelineContext) -> None:
    ctx.extra["alternates_unused_summaries"] = [{"url": "https://example.com/unused"}]


def _populate_email_subject(ctx: PipelineContext) -> None:
    ctx.extra["email_subject"] = "This Week in AI: Agents Take Over"
    ctx.extra["email_doc_id"] = "email-doc-001"


def _populate_social_media(ctx: PipelineContext) -> None:
    ctx.extra["social_media_doc_id"] = "social-doc-001"


def _populate_linkedin_carousel(ctx: PipelineContext) -> None:
    ctx.extra["linkedin_carousel_doc_id"] = "carousel-doc-001"


_STEP_POPULATORS = {
    StepName.CURATION.value: _populate_curation,
    StepName.SUMMARIZATION.value: _populate_summarization,
    StepName.THEME_GENERATION.value: _populate_theme_generation,
    StepName.MARKDOWN_GENERATION.value: _populate_markdown_generation,
    StepName.HTML_GENERATION.value: _populate_html_generation,
    StepName.ALTERNATES_HTML.value: _populate_alternates_html,
    StepName.EMAIL_SUBJECT.value: _populate_email_subject,
    StepName.SOCIAL_MEDIA.value: _populate_social_media,
    StepName.LINKEDIN_CAROUSEL.value: _populate_linkedin_carousel,
}


def _make_populating_step(step_name_value: str) -> AsyncMock:
    """Create a mock step that populates context with realistic data."""
    populator = _STEP_POPULATORS[step_name_value]

    async def step_fn(ctx: PipelineContext) -> PipelineContext:
        populator(ctx)
        return ctx

    return AsyncMock(side_effect=step_fn)


def _patch_all_steps():
    """Patch get_step_fn to return data-populating mocks for every step."""

    def _get_step(name: StepName) -> AsyncMock:
        return _make_populating_step(name.value)

    return patch("ica.guided.runner.get_step_fn", side_effect=_get_step)


def _patch_sheets_refs():
    return patch("ica.guided.runner._get_sheets_refs", return_value=_SHEETS_REFS)


# ---------------------------------------------------------------------------
# Replay fixture loader
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    """Load a replay fixture JSON file by name (without extension)."""
    path = _FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Consistency assertion helpers
# ---------------------------------------------------------------------------


def assert_state_artifact_consistency(
    state: TestRunState,
    ledger: ArtifactLedger,
) -> None:
    """Verify cross-cutting invariants between run state and artifact ledger.

    Checks:
    1. Every COMPLETED step has at least one ledger entry.
    2. Attempt numbers in state match max attempt in ledger per step.
    3. All ledger entries share the same run_id as state.
    4. Steps with artifact_history have entries for all historical attempts.
    5. No PENDING step has ledger entries.
    6. Ledger timestamps are non-decreasing (chronological ordering).
    """
    # 1: Completed steps have artifacts
    for step in state.steps:
        if step.status == StepStatus.COMPLETED:
            step_entries = ledger.by_step(step.name)
            assert len(step_entries) >= 1, (
                f"COMPLETED step '{step.name}' has no artifact entries"
            )

    # 2: Attempt alignment
    for step in state.steps:
        if step.status in (StepStatus.COMPLETED, StepStatus.FAILED):
            step_entries = ledger.by_step(step.name)
            if step_entries:
                max_ledger_attempt = max(e.attempt_number for e in step_entries)
                assert max_ledger_attempt == step.attempt, (
                    f"Step '{step.name}': state attempt={step.attempt}, "
                    f"max ledger attempt={max_ledger_attempt}"
                )

    # 3: All entries share run_id
    for entry in ledger.entries:
        assert entry.run_id == state.run_id, (
            f"Entry run_id '{entry.run_id}' != state run_id '{state.run_id}'"
        )

    # 4: Artifact history implies multi-attempt ledger entries
    for step in state.steps:
        if step.artifact_history:
            step_entries = ledger.by_step(step.name)
            historical_attempts = {h["attempt"] for h in step.artifact_history}
            ledger_attempts = {e.attempt_number for e in step_entries}
            assert historical_attempts <= ledger_attempts, (
                f"Step '{step.name}': history attempts {historical_attempts} "
                f"not all in ledger {ledger_attempts}"
            )

    # 5: Pending steps have no entries
    for step in state.steps:
        if step.status == StepStatus.PENDING:
            step_entries = ledger.by_step(step.name)
            assert len(step_entries) == 0, (
                f"PENDING step '{step.name}' has {len(step_entries)} entries"
            )

    # 6: Chronological ordering
    timestamps = [e.timestamp for e in ledger.entries]
    assert timestamps == sorted(timestamps), "Ledger entries not in chronological order"


def assert_matches_fixture(
    ledger: ArtifactLedger,
    expected_entries: list[dict],
) -> None:
    """Compare ledger entries against replay fixture (structural keys only).

    Compares step_name, artifact_type, key, and attempt_number. Ignores
    volatile fields (run_id, timestamp, value, metadata).
    """
    structural_keys = ("step_name", "artifact_type", "key", "attempt_number")

    actual = [
        {
            k: e.artifact_type.value if k == "artifact_type" else getattr(e, k)
            for k in structural_keys
        }
        for e in ledger.entries
    ]
    expected = [{k: e[k] for k in structural_keys} for e in expected_entries]

    assert actual == expected, (
        f"Ledger entries do not match fixture.\n"
        f"  actual ({len(actual)}):   {actual}\n"
        f"  expected ({len(expected)}): {expected}"
    )


# ---------------------------------------------------------------------------
# Happy path verification
# ---------------------------------------------------------------------------


class TestHappyPathVerification:
    """Full 9-step flow: state + artifact consistency + fixture comparison."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def _run_happy_path(self, store_dir: Path) -> tuple[TestRunState, ArtifactLedger]:
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        artifact_store = ArtifactStore(store_dir)
        ledger = artifact_store.get_ledger(state.run_id)
        return state, ledger

    async def test_state_reaches_completed(self, store_dir: Path) -> None:
        state, _ = await self._run_happy_path(store_dir)
        assert state.phase == RunPhase.COMPLETED

    async def test_all_steps_completed(self, store_dir: Path) -> None:
        state, _ = await self._run_happy_path(store_dir)
        for step in state.steps:
            assert step.status == StepStatus.COMPLETED, (
                f"Step '{step.name}' is {step.status.value}, not completed"
            )

    async def test_all_steps_single_attempt(self, store_dir: Path) -> None:
        state, _ = await self._run_happy_path(store_dir)
        for step in state.steps:
            assert step.attempt == 1, (
                f"Step '{step.name}' has attempt={step.attempt}"
            )

    async def test_nine_continue_decisions(self, store_dir: Path) -> None:
        state, _ = await self._run_happy_path(store_dir)
        assert len(state.decisions) == 9
        assert all(d.action == "continue" for d in state.decisions)

    async def test_state_artifact_consistency(self, store_dir: Path) -> None:
        state, ledger = await self._run_happy_path(store_dir)
        assert_state_artifact_consistency(state, ledger)

    async def test_matches_replay_fixture(self, store_dir: Path) -> None:
        """Compare against golden-file happy_path.json."""
        _, ledger = await self._run_happy_path(store_dir)
        fixture = _load_fixture("happy_path")
        assert_matches_fixture(ledger, fixture["entries"])

    async def test_fixture_state_summary(self, store_dir: Path) -> None:
        """Verify state summary matches fixture expectations."""
        state, _ = await self._run_happy_path(store_dir)
        fixture = _load_fixture("happy_path")
        expected_state = fixture["state"]

        assert state.phase.value == expected_state["phase"]
        completed = sum(1 for s in state.steps if s.status == StepStatus.COMPLETED)
        pending = sum(1 for s in state.steps if s.status == StepStatus.PENDING)
        failed = sum(1 for s in state.steps if s.status == StepStatus.FAILED)
        assert completed == expected_state["completed_steps"]
        assert pending == expected_state["pending_steps"]
        assert failed == expected_state["failed_steps"]
        assert max(s.attempt for s in state.steps) == expected_state["max_attempt"]

    async def test_context_snapshot_persisted(self, store_dir: Path) -> None:
        """Final state has a context snapshot for potential resume."""
        state, _ = await self._run_happy_path(store_dir)
        assert state.context_snapshot  # Non-empty dict
        assert state.context_snapshot.get("run_id") == state.run_id

    async def test_state_survives_disk_round_trip(self, store_dir: Path) -> None:
        """State persisted to JSON can be reloaded faithfully."""
        state, _ = await self._run_happy_path(store_dir)
        reloaded = TestRunStore(store_dir).load(state.run_id)
        assert reloaded.phase == state.phase
        assert reloaded.run_id == state.run_id
        assert len(reloaded.steps) == len(state.steps)
        for orig, loaded in zip(state.steps, reloaded.steps, strict=True):
            assert orig.name == loaded.name
            assert orig.status == loaded.status
            assert orig.attempt == loaded.attempt


# ---------------------------------------------------------------------------
# Redo branch verification
# ---------------------------------------------------------------------------


class TestRedoBranchVerification:
    """Redo theme_generation, then continue — state + artifact consistency."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def _run_redo_branch(self, store_dir: Path) -> tuple[TestRunState, ArtifactLedger]:
        console = Console(file=MagicMock())
        # Steps 1-2 continue, step 3 redo then continue, steps 4-9 continue
        inputs = iter(["c", "c", "r", "c"] + ["c"] * 6)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        artifact_store = ArtifactStore(store_dir)
        ledger = artifact_store.get_ledger(state.run_id)
        return state, ledger

    async def test_redo_step_has_attempt_2(self, store_dir: Path) -> None:
        state, _ = await self._run_redo_branch(store_dir)
        theme_step = state.steps[2]
        assert theme_step.name == "theme_generation"
        assert theme_step.attempt == 2

    async def test_non_redo_steps_stay_attempt_1(self, store_dir: Path) -> None:
        state, _ = await self._run_redo_branch(store_dir)
        for i, step in enumerate(state.steps):
            if i != 2:
                assert step.attempt == 1, (
                    f"Step '{step.name}' has attempt={step.attempt}, expected 1"
                )

    async def test_redo_step_has_artifact_history(self, store_dir: Path) -> None:
        state, _ = await self._run_redo_branch(store_dir)
        theme_step = state.steps[2]
        assert len(theme_step.artifact_history) >= 1
        assert theme_step.artifact_history[0]["attempt"] == 1

    async def test_state_artifact_consistency(self, store_dir: Path) -> None:
        state, ledger = await self._run_redo_branch(store_dir)
        assert_state_artifact_consistency(state, ledger)

    async def test_ledger_has_both_attempts_for_redo_step(self, store_dir: Path) -> None:
        _, ledger = await self._run_redo_branch(store_dir)
        theme_entries = ledger.by_step("theme_generation")
        attempts = sorted({e.attempt_number for e in theme_entries})
        assert attempts == [1, 2]

    async def test_matches_replay_fixture(self, store_dir: Path) -> None:
        """Compare against golden-file redo_branch.json."""
        _, ledger = await self._run_redo_branch(store_dir)
        fixture = _load_fixture("redo_branch")
        assert_matches_fixture(ledger, fixture["entries"])

    async def test_decisions_include_redo(self, store_dir: Path) -> None:
        state, _ = await self._run_redo_branch(store_dir)
        actions = [d.action for d in state.decisions]
        assert "redo" in actions
        # Total: 2 continues + 1 redo + 1 continue (after redo) + 6 continues = 10
        assert len(actions) == 10

    async def test_run_completes_successfully(self, store_dir: Path) -> None:
        state, _ = await self._run_redo_branch(store_dir)
        assert state.phase == RunPhase.COMPLETED
        assert all(s.status == StepStatus.COMPLETED for s in state.steps)


# ---------------------------------------------------------------------------
# Resume after interruption verification
# ---------------------------------------------------------------------------


class TestResumeAfterInterruption:
    """Simulate crash (KeyboardInterrupt), resume from persisted state, complete.

    The runner catches KeyboardInterrupt during step execution, saves the
    context snapshot, and returns with the state still in RUNNING phase.
    Calling ``run_guided(run_id=...)`` detects the RUNNING phase and invokes
    ``sm.resume()`` to restart the interrupted step with an incremented attempt.
    """

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def _interrupt_and_resume(
        self, store_dir: Path
    ) -> tuple[TestRunState, TestRunState, ArtifactLedger]:
        """Run 3 steps, crash on step 4, resume, complete.

        Returns (interrupted_state, final_state, ledger).
        """
        console = Console(file=MagicMock())
        call_count = {"markdown_generation": 0}

        def _get_step_with_crash(name: StepName) -> AsyncMock:
            """Step 4 (markdown_generation) crashes on first call."""
            if name == StepName.MARKDOWN_GENERATION:

                async def crash_then_succeed(
                    ctx: PipelineContext,
                ) -> PipelineContext:
                    call_count["markdown_generation"] += 1
                    if call_count["markdown_generation"] == 1:
                        raise KeyboardInterrupt()
                    _populate_markdown_generation(ctx)
                    return ctx

                return AsyncMock(side_effect=crash_then_succeed)
            return _make_populating_step(name.value)

        step_patch = patch(
            "ica.guided.runner.get_step_fn", side_effect=_get_step_with_crash
        )

        # Phase 1: Run until crash at step 4 (markdown_generation)
        inputs_phase1 = iter(["c"] * 9)  # plenty of continues

        with step_patch, _patch_sheets_refs():
            interrupted_state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs_phase1),
            )

        # Phase 2: Resume the interrupted run — step 4 now succeeds
        inputs_phase2 = iter(["c"] * 9)

        with step_patch, _patch_sheets_refs():
            final_state = await run_guided(
                run_id=interrupted_state.run_id,
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs_phase2),
            )

        artifact_store = ArtifactStore(store_dir)
        ledger = artifact_store.get_ledger(final_state.run_id)
        return interrupted_state, final_state, ledger

    async def test_interrupted_state_is_running(self, store_dir: Path) -> None:
        interrupted, _, _ = await self._interrupt_and_resume(store_dir)
        assert interrupted.phase == RunPhase.RUNNING

    async def test_final_state_completes(self, store_dir: Path) -> None:
        _, final, _ = await self._interrupt_and_resume(store_dir)
        assert final.phase == RunPhase.COMPLETED
        assert all(s.status == StepStatus.COMPLETED for s in final.steps)

    async def test_same_run_id(self, store_dir: Path) -> None:
        interrupted, final, _ = await self._interrupt_and_resume(store_dir)
        assert interrupted.run_id == final.run_id

    async def test_resumed_step_has_attempt_2(self, store_dir: Path) -> None:
        """The crashed step gets attempt 2 on resume."""
        _, final, _ = await self._interrupt_and_resume(store_dir)
        md_step = next(s for s in final.steps if s.name == "markdown_generation")
        assert md_step.attempt == 2

    async def test_pre_crash_artifacts_survive(self, store_dir: Path) -> None:
        """Artifacts from steps before the crash are still in the ledger."""
        _, _, ledger = await self._interrupt_and_resume(store_dir)
        fixture = _load_fixture("resume_after_stop")

        for expected in fixture["pre_stop_entries"]:
            step_entries = ledger.by_step(expected["step_name"])
            matching = [
                e for e in step_entries
                if e.key == expected["key"]
                and e.artifact_type.value == expected["artifact_type"]
            ]
            assert len(matching) >= 1, (
                f"Pre-crash entry missing: {expected['step_name']}/{expected['key']}"
            )

    async def test_post_resume_artifacts_present(self, store_dir: Path) -> None:
        """Artifacts from after resume are present in the ledger."""
        _, _, ledger = await self._interrupt_and_resume(store_dir)
        fixture = _load_fixture("resume_after_stop")

        for expected in fixture["post_resume_entries_include"]:
            step_entries = ledger.by_step(expected["step_name"])
            matching = [
                e for e in step_entries
                if e.key == expected["key"]
                and e.artifact_type.value == expected["artifact_type"]
            ]
            assert len(matching) >= 1, (
                f"Post-resume entry missing: {expected['step_name']}/{expected['key']}"
            )

    async def test_state_artifact_consistency(self, store_dir: Path) -> None:
        _, final, ledger = await self._interrupt_and_resume(store_dir)
        assert_state_artifact_consistency(final, ledger)

    async def test_context_snapshot_preserved_across_resume(
        self, store_dir: Path
    ) -> None:
        """Context data from pre-crash steps is available after resume."""
        _, final, _ = await self._interrupt_and_resume(store_dir)
        assert final.context_snapshot
        assert final.context_snapshot.get("run_id") == final.run_id


# ---------------------------------------------------------------------------
# Parameterized consistency invariant checks
# ---------------------------------------------------------------------------


class TestConsistencyInvariants:
    """Verify specific state-artifact invariants across different scenarios."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def _run_scenario(
        self, store_dir: Path, operator_inputs: list[str]
    ) -> tuple[TestRunState, ArtifactLedger]:
        console = Console(file=MagicMock())
        inputs = iter(operator_inputs)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        artifact_store = ArtifactStore(store_dir)
        ledger = artifact_store.get_ledger(state.run_id)
        return state, ledger

    @pytest.mark.parametrize(
        "desc, inputs",
        [
            ("happy_path", ["c"] * 9),
            ("redo_first", ["r", "c"] + ["c"] * 8),
            ("redo_last", ["c"] * 8 + ["r", "c"]),
            ("redo_middle", ["c", "c", "r", "c"] + ["c"] * 6),
            ("double_redo", ["r", "r", "c"] + ["c"] * 8),
            ("stop_early", ["c", "s"]),
        ],
        ids=lambda x: x if isinstance(x, str) else "",
    )
    async def test_consistency_across_scenarios(
        self, store_dir: Path, desc: str, inputs: list[str]
    ) -> None:
        state, ledger = await self._run_scenario(store_dir, inputs)

        # Consistency check applies to all terminal states
        if state.phase in (RunPhase.COMPLETED, RunPhase.ABORTED):
            # Relax invariant checks for aborted runs — only check completed steps
            for step in state.steps:
                if step.status == StepStatus.COMPLETED:
                    step_entries = ledger.by_step(step.name)
                    assert len(step_entries) >= 1, (
                        f"[{desc}] COMPLETED step '{step.name}' "
                        f"has no artifact entries"
                    )

            # All entries belong to this run
            for entry in ledger.entries:
                assert entry.run_id == state.run_id, (
                    f"[{desc}] Entry run_id mismatch"
                )

            # Timestamps are ordered
            timestamps = [e.timestamp for e in ledger.entries]
            assert timestamps == sorted(timestamps), (
                f"[{desc}] Ledger timestamps not ordered"
            )

    async def test_step_count_alignment(self, store_dir: Path) -> None:
        """Number of steps with ledger entries equals non-PENDING steps."""
        state, ledger = await self._run_scenario(store_dir, ["c"] * 9)

        steps_with_entries = {e.step_name for e in ledger.entries}
        non_pending_steps = {
            s.name for s in state.steps if s.status != StepStatus.PENDING
        }
        assert steps_with_entries == non_pending_steps

    async def test_partial_run_step_alignment(self, store_dir: Path) -> None:
        """In a partial run (stop after 3), only completed steps have entries."""
        state, ledger = await self._run_scenario(
            store_dir, ["c", "c", "c", "s"]
        )

        steps_with_entries = {e.step_name for e in ledger.entries}
        completed_steps = {
            s.name for s in state.steps if s.status == StepStatus.COMPLETED
        }
        assert steps_with_entries == completed_steps

    async def test_ledger_entry_types_valid(self, store_dir: Path) -> None:
        """All ledger entries have valid ArtifactType values."""
        _, ledger = await self._run_scenario(store_dir, ["c"] * 9)

        valid_types = set(ArtifactType)
        for entry in ledger.entries:
            assert entry.artifact_type in valid_types, (
                f"Invalid artifact type: {entry.artifact_type}"
            )

    async def test_ledger_entries_have_non_empty_keys(self, store_dir: Path) -> None:
        """All ledger entries have non-empty key fields."""
        _, ledger = await self._run_scenario(store_dir, ["c"] * 9)

        for entry in ledger.entries:
            assert entry.key, f"Entry in step '{entry.step_name}' has empty key"

    async def test_ledger_entries_have_non_null_values(self, store_dir: Path) -> None:
        """All ledger entries have non-null value fields."""
        _, ledger = await self._run_scenario(store_dir, ["c"] * 9)

        for entry in ledger.entries:
            assert entry.value is not None, (
                f"Entry '{entry.key}' in step '{entry.step_name}' has null value"
            )
