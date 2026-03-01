"""Tests for ica.guided.runner — the guided pipeline runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from ica.guided.runner import (
    _extract_artifacts,
    parse_operator_input,
    prompt_operator,
    render_checkpoint,
    render_run_header,
    render_step_table,
    restore_context,
    run_guided,
    snapshot_context,
)
from ica.guided.state import (
    OperatorAction,
    RunPhase,
    StepStatus,
    TestRunState,
    TestRunStore,
)
from ica.pipeline.orchestrator import PipelineContext, StepName

# ---------------------------------------------------------------------------
# parse_operator_input
# ---------------------------------------------------------------------------


class TestParseOperatorInput:
    """Operator input parsing maps shorthand to actions."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("c", OperatorAction.CONTINUE),
            ("C", OperatorAction.CONTINUE),
            ("continue", OperatorAction.CONTINUE),
            ("CONTINUE", OperatorAction.CONTINUE),
            ("r", OperatorAction.REDO),
            ("R", OperatorAction.REDO),
            ("redo", OperatorAction.REDO),
            ("s", OperatorAction.STOP),
            ("S", OperatorAction.STOP),
            ("stop", OperatorAction.STOP),
            ("  c  ", OperatorAction.CONTINUE),
        ],
    )
    def test_valid_inputs(self, raw: str, expected: OperatorAction) -> None:
        assert parse_operator_input(raw) == expected

    @pytest.mark.parametrize("raw", ["", "x", "go", "123", "continue!"])
    def test_invalid_inputs(self, raw: str) -> None:
        assert parse_operator_input(raw) is None


# ---------------------------------------------------------------------------
# prompt_operator
# ---------------------------------------------------------------------------


class TestPromptOperator:
    """Checkpoint prompt collects operator decisions."""

    def _make_state(
        self, *, step_status: StepStatus = StepStatus.COMPLETED, is_last: bool = False
    ) -> TestRunState:
        state = TestRunState(run_id="test")
        state.phase = RunPhase.CHECKPOINT
        idx = len(state.steps) - 1 if is_last else 0
        state.current_step_index = idx
        state.steps[idx].status = step_status
        return state

    def test_continue_on_completed(self) -> None:
        state = self._make_state(step_status=StepStatus.COMPLETED)
        console = Console(file=MagicMock())
        result = prompt_operator(state, console, prompt_fn=lambda _: "c")
        assert result == OperatorAction.CONTINUE

    def test_redo_on_failed(self) -> None:
        state = self._make_state(step_status=StepStatus.FAILED)
        console = Console(file=MagicMock())
        result = prompt_operator(state, console, prompt_fn=lambda _: "r")
        assert result == OperatorAction.REDO

    def test_stop(self) -> None:
        state = self._make_state()
        console = Console(file=MagicMock())
        result = prompt_operator(state, console, prompt_fn=lambda _: "s")
        assert result == OperatorAction.STOP

    def test_eof_returns_stop(self) -> None:
        state = self._make_state()
        console = Console(file=MagicMock())

        def raise_eof(_: str) -> str:
            raise EOFError

        result = prompt_operator(state, console, prompt_fn=raise_eof)
        assert result == OperatorAction.STOP

    def test_keyboard_interrupt_returns_stop(self) -> None:
        state = self._make_state()
        console = Console(file=MagicMock())

        def raise_interrupt(_: str) -> str:
            raise KeyboardInterrupt

        result = prompt_operator(state, console, prompt_fn=raise_interrupt)
        assert result == OperatorAction.STOP

    def test_invalid_then_valid(self) -> None:
        state = self._make_state()
        console = Console(file=MagicMock())
        inputs = iter(["bad", "c"])
        result = prompt_operator(state, console, prompt_fn=lambda _: next(inputs))
        assert result == OperatorAction.CONTINUE

    def test_continue_blocked_on_failed_then_redo(self) -> None:
        state = self._make_state(step_status=StepStatus.FAILED)
        console = Console(file=MagicMock())
        inputs = iter(["c", "r"])
        result = prompt_operator(state, console, prompt_fn=lambda _: next(inputs))
        assert result == OperatorAction.REDO

    def test_last_step_shows_complete(self) -> None:
        state = self._make_state(is_last=True)
        console = Console(file=MagicMock())
        prompts: list[str] = []

        def capture_prompt(p: str) -> str:
            prompts.append(p)
            return "c"

        prompt_operator(state, console, prompt_fn=capture_prompt)
        # The prompt text includes "[C]omplete" (with Rich-style brackets)
        assert any("omplete" in p for p in prompts)


# ---------------------------------------------------------------------------
# Context snapshot/restore
# ---------------------------------------------------------------------------


class TestContextSnapshot:
    """Context serialization round-trips correctly."""

    def test_round_trip(self) -> None:
        ctx = PipelineContext(
            run_id="r1",
            trigger="test",
            articles=[{"title": "A"}],
            theme_name="AI Today",
        )
        snap = snapshot_context(ctx)
        restored = restore_context(snap)
        assert restored.run_id == "r1"
        assert restored.articles == [{"title": "A"}]
        assert restored.theme_name == "AI Today"

    def test_step_results_stripped(self) -> None:
        snap = {"run_id": "r1", "step_results": [{"step": "curation"}]}
        restored = restore_context(snap)
        assert restored.step_results == []


# ---------------------------------------------------------------------------
# _extract_artifacts
# ---------------------------------------------------------------------------


class TestExtractArtifacts:
    """Artifact extraction from PipelineContext."""

    def test_curation_artifacts(self) -> None:
        ctx = PipelineContext(
            articles=[{"title": "A"}, {"title": "B"}],
            newsletter_id="nl-1",
        )
        arts = _extract_artifacts(StepName.CURATION, ctx)
        assert arts["article_count"] == 2
        assert arts["newsletter_id"] == "nl-1"

    def test_summarization_artifacts(self) -> None:
        ctx = PipelineContext(summaries=[{"url": "a"}, {"url": "b"}, {"url": "c"}])
        arts = _extract_artifacts(StepName.SUMMARIZATION, ctx)
        assert arts["summary_count"] == 3

    def test_theme_generation_artifacts(self) -> None:
        ctx = PipelineContext(theme_name="AI Future")
        arts = _extract_artifacts(StepName.THEME_GENERATION, ctx)
        assert arts["theme_name"] == "AI Future"

    def test_markdown_generation_artifacts(self) -> None:
        ctx = PipelineContext(markdown_doc_id="doc-123")
        arts = _extract_artifacts(StepName.MARKDOWN_GENERATION, ctx)
        assert arts["markdown_doc_id"] == "doc-123"

    def test_html_generation_artifacts(self) -> None:
        ctx = PipelineContext(html_doc_id="html-456")
        arts = _extract_artifacts(StepName.HTML_GENERATION, ctx)
        assert arts["html_doc_id"] == "html-456"

    def test_email_subject_artifacts(self) -> None:
        ctx = PipelineContext(extra={"email_subject": "Breaking News"})
        arts = _extract_artifacts(StepName.EMAIL_SUBJECT, ctx)
        assert arts["email_subject"] == "Breaking News"

    def test_social_media_artifacts(self) -> None:
        ctx = PipelineContext(extra={"social_media_doc_id": "sm-789"})
        arts = _extract_artifacts(StepName.SOCIAL_MEDIA, ctx)
        assert arts["social_media_doc_id"] == "sm-789"

    def test_linkedin_carousel_artifacts(self) -> None:
        ctx = PipelineContext(extra={"linkedin_carousel_doc_id": "lc-111"})
        arts = _extract_artifacts(StepName.LINKEDIN_CAROUSEL, ctx)
        assert arts["linkedin_carousel_doc_id"] == "lc-111"

    def test_alternates_html_artifacts(self) -> None:
        ctx = PipelineContext(extra={"alternates_unused_summaries": [1, 2]})
        arts = _extract_artifacts(StepName.ALTERNATES_HTML, ctx)
        assert arts["unused_article_count"] == 2

    def test_empty_artifacts(self) -> None:
        ctx = PipelineContext()
        arts = _extract_artifacts(StepName.CURATION, ctx)
        assert arts["article_count"] == 0
        assert "newsletter_id" not in arts


# ---------------------------------------------------------------------------
# Render helpers (smoke tests — verify they don't crash)
# ---------------------------------------------------------------------------


class TestRenderHelpers:
    """Render functions produce output without errors."""

    def test_render_run_header(self) -> None:
        state = TestRunState(run_id="r1")
        console = Console(file=MagicMock())
        render_run_header(state, console)

    def test_render_step_table(self) -> None:
        state = TestRunState(run_id="r1")
        state.steps[0].status = StepStatus.COMPLETED
        state.steps[0].artifacts = {"doc_id": "abc"}
        console = Console(file=MagicMock())
        render_step_table(state, console)

    def test_render_checkpoint_completed(self) -> None:
        state = TestRunState(run_id="r1")
        state.steps[0].status = StepStatus.COMPLETED
        state.steps[0].artifacts = {"count": 5}
        console = Console(file=MagicMock())
        render_checkpoint(state, console)

    def test_render_checkpoint_failed(self) -> None:
        state = TestRunState(run_id="r1")
        state.steps[0].status = StepStatus.FAILED
        state.steps[0].error = "boom"
        console = Console(file=MagicMock())
        render_checkpoint(state, console)


# ---------------------------------------------------------------------------
# run_guided — integration tests
# ---------------------------------------------------------------------------


def _mock_step(*, fail: bool = False) -> AsyncMock:
    """Create a mock pipeline step that succeeds or fails."""
    step = AsyncMock()
    if fail:
        step.side_effect = RuntimeError("step failed")
    else:
        step.return_value = PipelineContext()
    return step


class TestRunGuided:
    """Integration tests for the guided runner loop."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        """Disable Google settings validation — runner tests focus on flow logic."""
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    def _patch_steps(self, mock_step: AsyncMock | None = None):
        """Patch get_step_fn to return a mock step for all steps."""
        if mock_step is None:
            mock_step = _mock_step()

        def _get_step(name: StepName) -> AsyncMock:
            # Make each call return a fresh context that preserves run_id
            async def step_fn(ctx: PipelineContext) -> PipelineContext:
                return ctx

            return AsyncMock(side_effect=step_fn)

        return patch("ica.guided.runner.get_step_fn", side_effect=_get_step)

    async def test_new_run_complete_all_steps(self, store_dir: Path) -> None:
        """Complete all 9 steps with 'continue' at each checkpoint."""
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with self._patch_steps():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        assert state.phase == RunPhase.COMPLETED
        assert all(s.status == StepStatus.COMPLETED for s in state.steps)

    async def test_stop_after_first_step(self, store_dir: Path) -> None:
        """Operator stops after the first step completes."""
        console = Console(file=MagicMock())

        with self._patch_steps():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
            )

        assert state.phase == RunPhase.ABORTED
        assert state.steps[0].status == StepStatus.COMPLETED
        assert state.steps[1].status == StepStatus.PENDING

    async def test_redo_then_continue(self, store_dir: Path) -> None:
        """Operator redoes the first step then continues."""
        console = Console(file=MagicMock())
        inputs = iter(["r", "c"] + ["c"] * 8)

        with self._patch_steps():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        assert state.phase == RunPhase.COMPLETED
        # First step should have been attempted twice
        assert state.steps[0].attempt == 2

    async def test_step_failure_then_redo(self, store_dir: Path) -> None:
        """Step fails, operator redoes it, then it succeeds."""
        console = Console(file=MagicMock())
        call_count = 0

        async def failing_then_succeeding_step(ctx: PipelineContext) -> PipelineContext:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first try fails")
            return ctx

        mock_step = AsyncMock(side_effect=failing_then_succeeding_step)
        inputs = iter(["r", "c"] + ["c"] * 8)

        with patch(
            "ica.guided.runner.get_step_fn",
            return_value=mock_step,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        assert state.phase == RunPhase.COMPLETED
        assert state.steps[0].attempt == 2

    async def test_resume_from_checkpoint(self, store_dir: Path) -> None:
        """Resume a run that was stopped at a checkpoint."""
        console = Console(file=MagicMock())

        # First: run and stop after step 1
        with self._patch_steps():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
            )

        run_id = state.run_id
        assert state.phase == RunPhase.ABORTED

        # Run is saved — but it's aborted, so resuming should report that
        with self._patch_steps():
            state2 = await run_guided(
                run_id=run_id,
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "c",
            )

        # Aborted runs can't be resumed
        assert state2.phase == RunPhase.ABORTED

    async def test_resume_nonexistent_run(self, store_dir: Path) -> None:
        """Resuming a non-existent run returns aborted state."""
        console = Console(file=MagicMock())

        state = await run_guided(
            run_id="nonexistent",
            store_dir=store_dir,
            console=console,
            prompt_fn=lambda _: "c",
        )

        assert state.phase == RunPhase.ABORTED

    async def test_state_persisted_to_disk(self, store_dir: Path) -> None:
        """Run state is persisted after each step."""
        console = Console(file=MagicMock())

        with self._patch_steps():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
            )

        store = TestRunStore(store_dir)
        loaded = store.load(state.run_id)
        assert loaded.run_id == state.run_id
        assert loaded.phase == RunPhase.ABORTED

    async def test_list_empty_store(self, store_dir: Path) -> None:
        """List runs returns empty when no runs exist."""
        store = TestRunStore(store_dir)
        assert store.list_runs() == []

    async def test_run_id_propagated_to_context(self, store_dir: Path) -> None:
        """The run_id is set on PipelineContext."""
        console = Console(file=MagicMock())
        captured_ctx: list[PipelineContext] = []

        async def capture_step(ctx: PipelineContext) -> PipelineContext:
            captured_ctx.append(ctx)
            return ctx

        with patch(
            "ica.guided.runner.get_step_fn",
            return_value=AsyncMock(side_effect=capture_step),
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
            )

        assert captured_ctx
        assert captured_ctx[0].run_id == state.run_id
