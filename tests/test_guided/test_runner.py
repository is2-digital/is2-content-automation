"""Tests for ica.guided.runner — the guided pipeline runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from ica.guided.artifacts import ArtifactEntry, ArtifactStore, ArtifactType
from ica.guided.runner import (
    _build_step_entries,
    _emit_slack_artifacts,
    _emit_step_artifacts,
    _entries_to_summary,
    _get_sheets_refs,
    _google_doc_url,
    _google_sheet_url,
    _prepare_redo_context,
    _raise_template_not_found,
    _resolve_template,
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
# Artifact entry builders and summary helpers
# ---------------------------------------------------------------------------

_RUN_ID = "test-run"
_ATTEMPT = 1


class TestGoogleUrlHelpers:
    """URL builder helpers for Google Docs and Sheets."""

    def test_google_doc_url(self) -> None:
        url = _google_doc_url("abc123")
        assert url == "https://docs.google.com/document/d/abc123/edit"

    def test_google_sheet_url(self) -> None:
        url = _google_sheet_url("sheet456")
        assert url == "https://docs.google.com/spreadsheets/d/sheet456/edit"

    def test_get_sheets_refs_guided(self) -> None:
        """Prefers guided_test_spreadsheet_id when set."""
        mock_settings = MagicMock()
        mock_settings.guided_test_spreadsheet_id = "test-sheet-id"
        mock_settings.curated_articles_google_sheet_id = "prod-sheet-id"
        with patch("ica.config.settings.get_settings", return_value=mock_settings):
            refs = _get_sheets_refs()
        assert refs["spreadsheet_id"] == "test-sheet-id"
        assert refs["sheet_name"] == "Sheet1"
        assert "spreadsheet_url" in refs

    def test_get_sheets_refs_fallback_to_prod(self) -> None:
        """Falls back to production spreadsheet ID when guided is empty."""
        mock_settings = MagicMock()
        mock_settings.guided_test_spreadsheet_id = ""
        mock_settings.curated_articles_google_sheet_id = "prod-sheet-id"
        with patch("ica.config.settings.get_settings", return_value=mock_settings):
            refs = _get_sheets_refs()
        assert refs["spreadsheet_id"] == "prod-sheet-id"

    def test_get_sheets_refs_empty(self) -> None:
        """Returns empty dict when no spreadsheet is configured."""
        mock_settings = MagicMock()
        mock_settings.guided_test_spreadsheet_id = ""
        mock_settings.curated_articles_google_sheet_id = ""
        with patch("ica.config.settings.get_settings", return_value=mock_settings):
            refs = _get_sheets_refs()
        assert refs == {}


class TestBuildStepEntries:
    """_build_step_entries produces typed ArtifactEntry objects per step."""

    def _mock_sheets_refs(self, spreadsheet_id: str = "sheet-1"):
        """Patch _get_sheets_refs to return predictable values."""
        refs = {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_url": _google_sheet_url(spreadsheet_id),
            "sheet_name": "Sheet1",
        }
        return patch("ica.guided.runner._get_sheets_refs", return_value=refs)

    def test_curation_entries(self) -> None:
        ctx = PipelineContext(
            articles=[{"title": "A"}, {"title": "B"}],
            newsletter_id="nl-1",
        )
        with self._mock_sheets_refs():
            entries = _build_step_entries(
                StepName.CURATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
            )
        assert len(entries) == 3
        assert entries[0].artifact_type == ArtifactType.LLM_OUTPUT
        assert entries[0].key == "article_count"
        assert entries[0].value == 2
        assert entries[1].key == "newsletter_id"
        assert entries[1].value == "nl-1"
        assert entries[2].artifact_type == ArtifactType.GOOGLE_SHEET
        assert entries[2].key == "curated_articles_sheet"
        assert entries[2].value["spreadsheet_id"] == "sheet-1"

    def test_summarization_entries(self) -> None:
        ctx = PipelineContext(summaries=[{"url": "a"}, {"url": "b"}, {"url": "c"}])
        with self._mock_sheets_refs():
            entries = _build_step_entries(
                StepName.SUMMARIZATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
            )
        assert entries[0].key == "summary_count"
        assert entries[0].value == 3
        assert entries[1].artifact_type == ArtifactType.GOOGLE_SHEET

    def test_theme_generation_entries(self) -> None:
        ctx = PipelineContext(theme_name="AI Future")
        entries = _build_step_entries(
            StepName.THEME_GENERATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert len(entries) == 1
        assert entries[0].artifact_type == ArtifactType.LLM_OUTPUT
        assert entries[0].key == "theme_name"
        assert entries[0].value == "AI Future"

    def test_markdown_generation_entries(self) -> None:
        ctx = PipelineContext(markdown_doc_id="doc-123")
        entries = _build_step_entries(
            StepName.MARKDOWN_GENERATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert len(entries) == 1
        assert entries[0].artifact_type == ArtifactType.GOOGLE_DOC
        assert entries[0].key == "markdown_doc"
        assert entries[0].value["markdown_doc_id"] == "doc-123"
        assert entries[0].value["document_url"] == _google_doc_url("doc-123")

    def test_html_generation_entries(self) -> None:
        ctx = PipelineContext(html_doc_id="html-456")
        entries = _build_step_entries(
            StepName.HTML_GENERATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert len(entries) == 1
        assert entries[0].artifact_type == ArtifactType.GOOGLE_DOC
        assert entries[0].value["html_doc_id"] == "html-456"

    def test_email_subject_entries(self) -> None:
        ctx = PipelineContext(
            extra={"email_subject": "Breaking News", "email_doc_id": "email-doc-1"}
        )
        entries = _build_step_entries(
            StepName.EMAIL_SUBJECT, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert len(entries) == 2
        assert entries[0].artifact_type == ArtifactType.LLM_OUTPUT
        assert entries[0].key == "email_subject"
        assert entries[0].value == "Breaking News"
        assert entries[1].artifact_type == ArtifactType.GOOGLE_DOC
        assert entries[1].value["email_doc_id"] == "email-doc-1"

    def test_email_subject_without_doc(self) -> None:
        ctx = PipelineContext(extra={"email_subject": "Breaking News"})
        entries = _build_step_entries(
            StepName.EMAIL_SUBJECT, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert len(entries) == 1
        assert entries[0].key == "email_subject"

    def test_social_media_entries(self) -> None:
        ctx = PipelineContext(extra={"social_media_doc_id": "sm-789"})
        entries = _build_step_entries(
            StepName.SOCIAL_MEDIA, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert len(entries) == 1
        assert entries[0].artifact_type == ArtifactType.GOOGLE_DOC
        assert entries[0].value["social_media_doc_id"] == "sm-789"

    def test_linkedin_carousel_entries(self) -> None:
        ctx = PipelineContext(extra={"linkedin_carousel_doc_id": "lc-111"})
        entries = _build_step_entries(
            StepName.LINKEDIN_CAROUSEL, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert len(entries) == 1
        assert entries[0].value["linkedin_carousel_doc_id"] == "lc-111"

    def test_alternates_html_entries(self) -> None:
        ctx = PipelineContext(extra={"alternates_unused_summaries": [1, 2]})
        entries = _build_step_entries(
            StepName.ALTERNATES_HTML, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert len(entries) == 1
        assert entries[0].key == "unused_article_count"
        assert entries[0].value == 2

    def test_empty_context_curation(self) -> None:
        ctx = PipelineContext()
        with self._mock_sheets_refs():
            entries = _build_step_entries(
                StepName.CURATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
            )
        # article_count (0) + sheet entry, no newsletter_id
        assert entries[0].key == "article_count"
        assert entries[0].value == 0
        assert not any(e.key == "newsletter_id" for e in entries)

    def test_no_doc_entries_when_no_doc_id(self) -> None:
        ctx = PipelineContext()
        entries = _build_step_entries(
            StepName.MARKDOWN_GENERATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert entries == []

    def test_entries_carry_run_id_and_attempt(self) -> None:
        ctx = PipelineContext(theme_name="test")
        entries = _build_step_entries(
            StepName.THEME_GENERATION, ctx, run_id="my-run", attempt=3
        )
        assert entries[0].run_id == "my-run"
        assert entries[0].attempt_number == 3
        assert entries[0].step_name == "theme_generation"


# ---------------------------------------------------------------------------
# _entries_to_summary — backward-compatible dict from entries
# ---------------------------------------------------------------------------


class TestEntriesToSummary:
    """Summary dict is backward-compatible with the old _extract_artifacts output."""

    def _mock_sheets_refs(self, spreadsheet_id: str = "sheet-1"):
        refs = {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_url": _google_sheet_url(spreadsheet_id),
            "sheet_name": "Sheet1",
        }
        return patch("ica.guided.runner._get_sheets_refs", return_value=refs)

    def test_curation_summary(self) -> None:
        ctx = PipelineContext(
            articles=[{"title": "A"}, {"title": "B"}],
            newsletter_id="nl-1",
        )
        with self._mock_sheets_refs():
            entries = _build_step_entries(
                StepName.CURATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
            )
        summary = _entries_to_summary(entries)
        assert summary["article_count"] == 2
        assert summary["newsletter_id"] == "nl-1"
        assert summary["spreadsheet_id"] == "sheet-1"
        assert summary["sheet_name"] == "Sheet1"
        assert "spreadsheet_url" in summary

    def test_markdown_summary_flattens_doc(self) -> None:
        ctx = PipelineContext(markdown_doc_id="doc-123")
        entries = _build_step_entries(
            StepName.MARKDOWN_GENERATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        summary = _entries_to_summary(entries)
        assert summary["markdown_doc_id"] == "doc-123"
        assert summary["document_url"] == _google_doc_url("doc-123")

    def test_empty_entries_produce_empty_dict(self) -> None:
        assert _entries_to_summary([]) == {}

    def test_scalar_entries_use_key(self) -> None:
        entry = ArtifactEntry(
            run_id="r",
            step_name="s",
            artifact_type=ArtifactType.LLM_OUTPUT,
            key="theme_name",
            value="AI Future",
        )
        assert _entries_to_summary([entry]) == {"theme_name": "AI Future"}


# ---------------------------------------------------------------------------
# _emit_step_artifacts — emits to store and returns summary
# ---------------------------------------------------------------------------


class TestEmitStepArtifacts:
    """_emit_step_artifacts persists entries and returns backward-compatible dict."""

    def test_emits_to_artifact_store(self, tmp_path: Path) -> None:
        store = ArtifactStore(tmp_path / "runs")
        ctx = PipelineContext(markdown_doc_id="doc-abc")
        summary = _emit_step_artifacts(
            StepName.MARKDOWN_GENERATION,
            ctx,
            run_id="run-1",
            attempt=1,
            artifact_store=store,
        )
        # Summary dict is populated
        assert summary["markdown_doc_id"] == "doc-abc"
        # Ledger file was written
        ledger = store.get_ledger("run-1")
        assert len(ledger.entries) == 1
        assert ledger.entries[0].artifact_type == ArtifactType.GOOGLE_DOC
        assert ledger.entries[0].key == "markdown_doc"

    def test_multiple_steps_accumulate(self, tmp_path: Path) -> None:
        store = ArtifactStore(tmp_path / "runs")
        ctx = PipelineContext(theme_name="AI")
        _emit_step_artifacts(
            StepName.THEME_GENERATION,
            ctx,
            run_id="run-1",
            attempt=1,
            artifact_store=store,
        )
        ctx2 = PipelineContext(markdown_doc_id="doc-1")
        _emit_step_artifacts(
            StepName.MARKDOWN_GENERATION,
            ctx2,
            run_id="run-1",
            attempt=1,
            artifact_store=store,
        )
        ledger = store.get_ledger("run-1")
        assert len(ledger.entries) == 2

    def test_redo_appends_not_replaces(self, tmp_path: Path) -> None:
        store = ArtifactStore(tmp_path / "runs")
        ctx1 = PipelineContext(markdown_doc_id="doc-v1")
        _emit_step_artifacts(
            StepName.MARKDOWN_GENERATION,
            ctx1,
            run_id="run-1",
            attempt=1,
            artifact_store=store,
        )
        ctx2 = PipelineContext(markdown_doc_id="doc-v2")
        _emit_step_artifacts(
            StepName.MARKDOWN_GENERATION,
            ctx2,
            run_id="run-1",
            attempt=2,
            artifact_store=store,
        )
        ledger = store.get_ledger("run-1")
        assert len(ledger.entries) == 2
        assert ledger.entries[0].attempt_number == 1
        assert ledger.entries[0].value["markdown_doc_id"] == "doc-v1"
        assert ledger.entries[1].attempt_number == 2
        assert ledger.entries[1].value["markdown_doc_id"] == "doc-v2"

    def test_empty_context_emits_nothing_for_doc_steps(self, tmp_path: Path) -> None:
        store = ArtifactStore(tmp_path / "runs")
        ctx = PipelineContext()
        summary = _emit_step_artifacts(
            StepName.MARKDOWN_GENERATION,
            ctx,
            run_id="run-1",
            attempt=1,
            artifact_store=store,
        )
        assert summary == {}
        ledger = store.get_ledger("run-1")
        assert ledger.entries == []


# ---------------------------------------------------------------------------
# _emit_slack_artifacts
# ---------------------------------------------------------------------------


class TestEmitSlackArtifacts:
    """Slack interactions are emitted as SLACK_DECISION entries."""

    def test_emits_one_entry_per_interaction(self, tmp_path: Path) -> None:
        store = ArtifactStore(tmp_path / "runs")
        interactions = [
            {"method": "send_and_wait", "response": "approved", "timestamp": "t1"},
            {"method": "send_and_wait_form", "response": {"choice": "A"}, "timestamp": "t2"},
        ]
        _emit_slack_artifacts(
            interactions,
            StepName.CURATION,
            run_id="run-1",
            attempt=1,
            artifact_store=store,
        )
        ledger = store.get_ledger("run-1")
        assert len(ledger.entries) == 2
        assert all(e.artifact_type == ArtifactType.SLACK_DECISION for e in ledger.entries)
        assert ledger.entries[0].key == "slack_send_and_wait"
        assert ledger.entries[1].key == "slack_send_and_wait_form"

    def test_empty_interactions_emits_nothing(self, tmp_path: Path) -> None:
        store = ArtifactStore(tmp_path / "runs")
        _emit_slack_artifacts(
            [],
            StepName.CURATION,
            run_id="run-1",
            attempt=1,
            artifact_store=store,
        )
        ledger = store.get_ledger("run-1")
        assert ledger.entries == []

    def test_interaction_value_is_full_dict(self, tmp_path: Path) -> None:
        store = ArtifactStore(tmp_path / "runs")
        interaction = {"method": "send_and_wait", "response": "ok", "channel": "C123"}
        _emit_slack_artifacts(
            [interaction],
            StepName.THEME_GENERATION,
            run_id="run-1",
            attempt=2,
            artifact_store=store,
        )
        entry = store.get_ledger("run-1").entries[0]
        assert entry.value == interaction
        assert entry.attempt_number == 2
        assert entry.step_name == "theme_generation"


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


# ---------------------------------------------------------------------------
# _prepare_redo_context — redo semantics for Google resources
# ---------------------------------------------------------------------------


class TestPrepareRedoContext:
    """Redo context preparation clears doc IDs and injects attempt tags."""

    def test_clears_markdown_doc_id(self) -> None:
        ctx = PipelineContext(markdown_doc_id="old-doc-123")
        _prepare_redo_context(StepName.MARKDOWN_GENERATION, 2, ctx)
        assert ctx.markdown_doc_id is None

    def test_clears_html_doc_id(self) -> None:
        ctx = PipelineContext(html_doc_id="old-html-456")
        _prepare_redo_context(StepName.HTML_GENERATION, 2, ctx)
        assert ctx.html_doc_id is None

    def test_clears_email_doc_id_from_extra(self) -> None:
        ctx = PipelineContext(extra={"email_doc_id": "old-email"})
        _prepare_redo_context(StepName.EMAIL_SUBJECT, 2, ctx)
        assert "email_doc_id" not in ctx.extra

    def test_clears_social_media_doc_id_from_extra(self) -> None:
        ctx = PipelineContext(extra={"social_media_doc_id": "old-sm"})
        _prepare_redo_context(StepName.SOCIAL_MEDIA, 2, ctx)
        assert "social_media_doc_id" not in ctx.extra

    def test_clears_linkedin_carousel_doc_id_from_extra(self) -> None:
        ctx = PipelineContext(extra={"linkedin_carousel_doc_id": "old-lc"})
        _prepare_redo_context(StepName.LINKEDIN_CAROUSEL, 2, ctx)
        assert "linkedin_carousel_doc_id" not in ctx.extra

    def test_injects_guided_attempt_for_curation(self) -> None:
        ctx = PipelineContext()
        _prepare_redo_context(StepName.CURATION, 3, ctx)
        assert ctx.extra["guided_attempt"] == 3

    def test_injects_guided_attempt_for_summarization(self) -> None:
        ctx = PipelineContext()
        _prepare_redo_context(StepName.SUMMARIZATION, 2, ctx)
        assert ctx.extra["guided_attempt"] == 2

    def test_no_attempt_tag_for_doc_steps(self) -> None:
        """Doc steps should not inject guided_attempt."""
        ctx = PipelineContext()
        _prepare_redo_context(StepName.MARKDOWN_GENERATION, 2, ctx)
        assert "guided_attempt" not in ctx.extra

    def test_noop_for_theme_generation(self) -> None:
        """Steps without Google resources are unaffected."""
        ctx = PipelineContext(theme_name="AI Today")
        _prepare_redo_context(StepName.THEME_GENERATION, 2, ctx)
        assert ctx.theme_name == "AI Today"
        assert "guided_attempt" not in ctx.extra

    def test_preserves_other_extra_keys(self) -> None:
        """Clearing one doc ID does not affect other extra keys."""
        ctx = PipelineContext(extra={"email_doc_id": "old", "email_subject": "Test"})
        _prepare_redo_context(StepName.EMAIL_SUBJECT, 2, ctx)
        assert "email_doc_id" not in ctx.extra
        assert ctx.extra["email_subject"] == "Test"


# ---------------------------------------------------------------------------
# render_checkpoint — artifact history display
# ---------------------------------------------------------------------------


class TestRenderCheckpointArtifactHistory:
    """Checkpoint renderer shows artifact history from previous redo attempts."""

    def test_shows_previous_doc_ids(self) -> None:
        state = TestRunState(run_id="r1")
        state.steps[0].status = StepStatus.COMPLETED
        state.steps[0].attempt = 2
        state.steps[0].artifacts = {"markdown_doc_id": "doc-v2", "document_url": "url-v2"}
        state.steps[0].artifact_history = [
            {"attempt": 1, "artifacts": {"markdown_doc_id": "doc-v1", "document_url": "url-v1"}}
        ]
        console = Console(file=MagicMock(), force_terminal=True)
        render_checkpoint(state, console)
        # Should not raise — smoke test that history rendering works

    def test_no_history_section_on_first_attempt(self) -> None:
        """No 'Previous attempts' section when there is no history."""
        state = TestRunState(run_id="r1")
        state.steps[0].status = StepStatus.COMPLETED
        state.steps[0].artifacts = {"doc_id": "abc"}
        output = MagicMock()
        console = Console(file=output, force_terminal=True)
        render_checkpoint(state, console)
        # MagicMock.write captures all output; check that "Previous" is absent
        written = "".join(str(call) for call in output.write.call_args_list)
        assert "Previous" not in written

    def test_shows_non_doc_artifacts_for_sheets_steps(self) -> None:
        state = TestRunState(run_id="r1")
        state.steps[0].status = StepStatus.COMPLETED
        state.steps[0].attempt = 2
        state.steps[0].artifacts = {"article_count": 5}
        state.steps[0].artifact_history = [
            {"attempt": 1, "artifacts": {"article_count": 3, "sheet_name": "Sheet1"}}
        ]
        console = Console(file=MagicMock(), force_terminal=True)
        render_checkpoint(state, console)
        # Smoke test — should not raise


# ---------------------------------------------------------------------------
# _resolve_template — template version pinning
# ---------------------------------------------------------------------------


class TestResolveTemplate:
    """Template resolution loads from TemplateStore and injects into context."""

    @pytest.fixture
    def template_dir(self, tmp_path: Path) -> Path:
        """Create a temporary template store with a known template."""
        from ica.guided.templates import TemplateStore

        store = TemplateStore(tmp_path / ".guided-templates")
        store.save("weekly", "<html>v1</html>", "1.0.0", description="first")
        store.save("weekly", "<html>v2</html>", "2.0.0", description="second")
        return tmp_path

    def test_resolves_specific_version(self, template_dir: Path) -> None:
        ctx = PipelineContext()
        console = Console(file=MagicMock())
        _resolve_template("weekly", "1.0.0", template_dir / "runs", ctx, console)

        assert ctx.extra["template_name"] == "weekly"
        assert ctx.extra["template_version"] == "1.0.0"
        assert ctx.extra["template_html"] == "<html>v1</html>"

    def test_resolves_latest_when_no_version(self, template_dir: Path) -> None:
        ctx = PipelineContext()
        console = Console(file=MagicMock())
        _resolve_template("weekly", None, template_dir / "runs", ctx, console)

        assert ctx.extra["template_name"] == "weekly"
        assert ctx.extra["template_version"] == "2.0.0"
        assert ctx.extra["template_html"] == "<html>v2</html>"

    def test_noop_when_template_not_found_unpinned(self, tmp_path: Path) -> None:
        ctx = PipelineContext()
        console = Console(file=MagicMock())
        _resolve_template("nonexistent", None, tmp_path / "runs", ctx, console)

        assert "template_name" not in ctx.extra
        assert "template_version" not in ctx.extra
        assert "template_html" not in ctx.extra

    def test_raises_when_template_not_found_pinned(self, tmp_path: Path) -> None:
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError):
            _resolve_template("nonexistent", "1.0.0", tmp_path / "runs", ctx, console)

    def test_raises_when_version_not_found_pinned(self, template_dir: Path) -> None:
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError):
            _resolve_template("weekly", "9.9.9", template_dir / "runs", ctx, console)

    def test_noop_when_store_empty(self, tmp_path: Path) -> None:
        ctx = PipelineContext()
        console = Console(file=MagicMock())
        _resolve_template("default", None, tmp_path / "runs", ctx, console)

        assert "template_html" not in ctx.extra


# ---------------------------------------------------------------------------
# HTML_GENERATION template info in artifact entries and summary
# ---------------------------------------------------------------------------


class TestBuildStepEntriesTemplateInfo:
    """HTML generation entries include template metadata."""

    def test_includes_template_entry(self) -> None:
        ctx = PipelineContext(
            html_doc_id="html-1",
            extra={"template_name": "weekly", "template_version": "2.0.0"},
        )
        entries = _build_step_entries(
            StepName.HTML_GENERATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        tpl_entries = [e for e in entries if e.key == "template_info"]
        assert len(tpl_entries) == 1
        assert tpl_entries[0].value == {"template_name": "weekly", "template_version": "2.0.0"}
        # Summary backward compat
        summary = _entries_to_summary(entries)
        assert summary["template_name"] == "weekly"
        assert summary["template_version"] == "2.0.0"
        assert summary["html_doc_id"] == "html-1"

    def test_omits_template_when_not_set(self) -> None:
        ctx = PipelineContext(html_doc_id="html-1")
        entries = _build_step_entries(
            StepName.HTML_GENERATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        assert not any(e.key == "template_info" for e in entries)
        summary = _entries_to_summary(entries)
        assert "template_name" not in summary
        assert "template_version" not in summary
        assert summary["html_doc_id"] == "html-1"

    def test_includes_template_without_doc_id(self) -> None:
        ctx = PipelineContext(
            extra={"template_name": "weekly", "template_version": "1.0.0"},
        )
        entries = _build_step_entries(
            StepName.HTML_GENERATION, ctx, run_id=_RUN_ID, attempt=_ATTEMPT
        )
        summary = _entries_to_summary(entries)
        assert summary["template_name"] == "weekly"
        assert summary["template_version"] == "1.0.0"
        assert "html_doc_id" not in summary


# ---------------------------------------------------------------------------
# _resolve_template — pinned version error handling
# ---------------------------------------------------------------------------


class TestResolveTemplatePinnedErrors:
    """When a template version is explicitly pinned, missing templates raise errors."""

    @pytest.fixture
    def template_dir(self, tmp_path: Path) -> Path:
        """Create a template store with known templates for error testing."""
        from ica.guided.templates import TemplateStore

        store = TemplateStore(tmp_path / ".guided-templates")
        store.save("weekly", "<html>v1</html>", "1.0.0", description="first")
        store.save("weekly", "<html>v2</html>", "2.0.0", description="second")
        store.save("daily", "<html>daily</html>", "1.0.0")
        return tmp_path

    def test_pinned_version_not_found_raises(self, template_dir: Path) -> None:
        """Pinning a nonexistent version raises TemplateNotFoundError."""
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError, match=r"version '9\.9\.9' not found"):
            _resolve_template("weekly", "9.9.9", template_dir / "runs", ctx, console)

    def test_pinned_version_not_found_lists_available(self, template_dir: Path) -> None:
        """Error message includes available versions for the template."""
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError, match=r"Available versions: 1\.0\.0, 2\.0\.0"):
            _resolve_template("weekly", "9.9.9", template_dir / "runs", ctx, console)

    def test_pinned_version_not_found_includes_import_hint(
        self, template_dir: Path
    ) -> None:
        """Error message includes how to import a template."""
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError, match=r"store\.save"):
            _resolve_template("weekly", "9.9.9", template_dir / "runs", ctx, console)

    def test_pinned_template_not_found_lists_alternatives(
        self, template_dir: Path
    ) -> None:
        """When template name is missing, error lists other available templates."""
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError, match=r"Available templates:.*weekly"):
            _resolve_template("nope", "1.0.0", template_dir / "runs", ctx, console)

    def test_pinned_template_not_found_includes_import_hint(
        self, template_dir: Path
    ) -> None:
        """Error for missing template name includes import instructions."""
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError, match=r"store\.save"):
            _resolve_template("nope", "1.0.0", template_dir / "runs", ctx, console)

    def test_empty_store_pinned_raises_setup_instructions(self, tmp_path: Path) -> None:
        """Empty store with pinned version gives first-time setup instructions."""
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError, match="First-time setup"):
            _resolve_template("default", "1.0.0", tmp_path / "runs", ctx, console)

    def test_empty_store_pinned_includes_import_steps(self, tmp_path: Path) -> None:
        """First-time setup error includes step-by-step import instructions."""
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError, match=r"store\.save"):
            _resolve_template("default", "1.0.0", tmp_path / "runs", ctx, console)

    def test_unpinned_still_falls_back_silently(self, tmp_path: Path) -> None:
        """Without a pinned version, missing templates still fall back silently."""
        ctx = PipelineContext()
        console = Console(file=MagicMock())
        _resolve_template("nonexistent", None, tmp_path / "runs", ctx, console)
        assert "template_name" not in ctx.extra

    def test_unpinned_missing_version_falls_back(self, template_dir: Path) -> None:
        """Unpinned (latest) resolution still works when template exists."""
        ctx = PipelineContext()
        console = Console(file=MagicMock())
        _resolve_template("weekly", None, template_dir / "runs", ctx, console)
        assert ctx.extra["template_name"] == "weekly"
        assert ctx.extra["template_version"] == "2.0.0"

    def test_pinned_version_context_not_modified_on_error(
        self, template_dir: Path
    ) -> None:
        """Context remains unmodified when a pinned version error is raised."""
        from ica.guided.templates import TemplateNotFoundError

        ctx = PipelineContext()
        console = Console(file=MagicMock())
        with pytest.raises(TemplateNotFoundError):
            _resolve_template("weekly", "9.9.9", template_dir / "runs", ctx, console)
        assert "template_name" not in ctx.extra
        assert "template_version" not in ctx.extra
        assert "template_html" not in ctx.extra


# ---------------------------------------------------------------------------
# _raise_template_not_found — unit tests for error message building
# ---------------------------------------------------------------------------


class TestRaiseTemplateNotFound:
    """Direct tests for the error-building helper."""

    def test_empty_store_error_mentions_store_path(self, tmp_path: Path) -> None:
        from ica.guided.templates import TemplateNotFoundError, TemplateStore

        templates_dir = tmp_path / ".guided-templates"
        store = TemplateStore(templates_dir)
        with pytest.raises(TemplateNotFoundError, match=str(templates_dir)):
            _raise_template_not_found("default", "1.0.0", store, templates_dir)

    def test_missing_name_lists_available(self, tmp_path: Path) -> None:
        from ica.guided.templates import TemplateNotFoundError, TemplateStore

        templates_dir = tmp_path / ".guided-templates"
        store = TemplateStore(templates_dir)
        store.save("weekly", "<html>w</html>", "1.0.0")
        store.save("daily", "<html>d</html>", "1.0.0")
        with pytest.raises(
            TemplateNotFoundError, match="Available templates: daily, weekly"
        ):
            _raise_template_not_found("monthly", "1.0.0", store, templates_dir)

    def test_missing_version_lists_versions(self, tmp_path: Path) -> None:
        from ica.guided.templates import TemplateNotFoundError, TemplateStore

        templates_dir = tmp_path / ".guided-templates"
        store = TemplateStore(templates_dir)
        store.save("weekly", "<html>v1</html>", "1.0.0")
        store.save("weekly", "<html>v2</html>", "2.0.0")
        with pytest.raises(
            TemplateNotFoundError, match=r"Available versions: 1\.0\.0, 2\.0\.0"
        ):
            _raise_template_not_found("weekly", "3.0.0", store, templates_dir)

    def test_import_hint_uses_requested_name_and_version(self, tmp_path: Path) -> None:
        from ica.guided.templates import TemplateNotFoundError, TemplateStore

        templates_dir = tmp_path / ".guided-templates"
        store = TemplateStore(templates_dir)
        with pytest.raises(
            TemplateNotFoundError, match=r'store\.save\("custom", html_content, "5\.0\.0"\)'
        ):
            _raise_template_not_found("custom", "5.0.0", store, templates_dir)
