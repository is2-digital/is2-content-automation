"""Integration tests for Google Docs write and Sheets update in guided mode.

Tests:
(1) Docs step creates a document and stores doc_id in artifacts.
(2) Sheets step writes rows and stores spreadsheet_id + row range.
(3) Redo on a Docs step creates a second document (both IDs in history).
(4) Redo on a Sheets step appends versioned rows.
(5) Missing target ID at startup raises clear validation error.

Mock at the service boundary (_make_docs, _make_sheets) not at the HTTP level.

Ref: ica-476.5.4
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.guided.runner import run_guided
from ica.guided.state import RunPhase, StepStatus
from ica.pipeline.orchestrator import PipelineContext, StepName

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_google_validation():
    return patch("ica.guided.runner.validate_google_settings")


def _patch_sheets_refs(**overrides: str):
    """Patch _get_sheets_refs to return controlled values."""
    refs = {
        "spreadsheet_id": overrides.get("spreadsheet_id", "sheet-test-001"),
        "spreadsheet_url": overrides.get(
            "spreadsheet_url",
            "https://docs.google.com/spreadsheets/d/sheet-test-001/edit",
        ),
        "sheet_name": overrides.get("sheet_name", "Sheet1"),
    }
    return patch("ica.guided.runner._get_sheets_refs", return_value=refs)


def _noop_step() -> AsyncMock:
    """A pipeline step that does nothing (used for steps we don't care about)."""

    async def step_fn(ctx: PipelineContext) -> PipelineContext:
        return ctx

    return AsyncMock(side_effect=step_fn)


def _make_docs_step(
    mock_docs: AsyncMock,
    *,
    ctx_attr: str = "markdown_doc_id",
    extra_key: str | None = None,
) -> AsyncMock:
    """Create a pipeline step that creates a Google Doc via the mock service.

    Sets the doc ID on the appropriate context attribute (or extra key)
    so ``_extract_artifacts`` can find it.
    """

    async def step_fn(ctx: PipelineContext) -> PipelineContext:
        doc_id = await mock_docs.create_document("Test Document")
        await mock_docs.insert_content(doc_id, "# Newsletter Content")
        if extra_key:
            ctx.extra[extra_key] = doc_id
        else:
            setattr(ctx, ctx_attr, doc_id)
        return ctx

    return AsyncMock(side_effect=step_fn)


def _make_sheets_step(mock_sheets: AsyncMock) -> AsyncMock:
    """Create a pipeline step that writes rows via the mock sheets service.

    Sets ``ctx.articles`` and ``ctx.newsletter_id`` so ``_extract_artifacts``
    picks up the expected curation artifacts.
    """

    async def step_fn(ctx: PipelineContext) -> PipelineContext:
        spreadsheet_id = await mock_sheets.ensure_spreadsheet("", "Test Curation")
        await mock_sheets.ensure_tab(spreadsheet_id, "Sheet1")
        rows = [{"title": "AI Article 1", "url": "https://example.com/1"}]
        attempt = ctx.extra.get("guided_attempt")
        if attempt:
            for row in rows:
                row["attempt"] = attempt
        await mock_sheets.append_rows(spreadsheet_id, "Sheet1", rows)
        ctx.articles = rows
        ctx.newsletter_id = "NL-TEST-001"
        return ctx

    return AsyncMock(side_effect=step_fn)


def _route_steps(
    target_name: StepName,
    target_fn: AsyncMock,
) -> MagicMock:
    """Build a get_step_fn replacement that returns *target_fn* for the
    target step and a no-op passthrough for all others."""
    noop = _noop_step()

    def get_step_fn(step_name: StepName) -> AsyncMock:
        if step_name == target_name:
            return target_fn
        return noop

    mock = MagicMock(side_effect=get_step_fn)
    return mock


def _inputs(*values: str):
    """Create a prompt_fn that yields operator inputs in order."""
    it = iter(values)
    return lambda _: next(it)


# ---------------------------------------------------------------------------
# (1) Docs step creates a document and stores doc_id in artifacts
# ---------------------------------------------------------------------------


class TestDocsStepCreatesDocument:
    """A Docs step creates a Google Doc and the runner stores its ID in artifacts."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with _patch_google_validation():
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_markdown_doc_id_in_step_artifacts(self, store_dir: Path) -> None:
        """After MARKDOWN_GENERATION completes, artifacts contain doc_id and URL."""
        mock_docs = AsyncMock()
        mock_docs.create_document = AsyncMock(return_value="doc-md-001")
        mock_docs.insert_content = AsyncMock()

        step_fn = _make_docs_step(mock_docs)
        get_step = _route_steps(StepName.MARKDOWN_GENERATION, step_fn)

        with patch("ica.guided.runner.get_step_fn", get_step):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                # continue through curation, summarization, theme_generation, then stop
                prompt_fn=_inputs("c", "c", "c", "s"),
            )

        md_step = state.steps[3]  # MARKDOWN_GENERATION
        assert md_step.status == StepStatus.COMPLETED
        assert md_step.artifacts["markdown_doc_id"] == "doc-md-001"
        assert "docs.google.com/document/d/doc-md-001" in md_step.artifacts["document_url"]

        mock_docs.create_document.assert_awaited_once_with("Test Document")
        mock_docs.insert_content.assert_awaited_once_with("doc-md-001", "# Newsletter Content")

    async def test_html_doc_id_in_step_artifacts(self, store_dir: Path) -> None:
        """After HTML_GENERATION completes, artifacts contain html_doc_id."""
        mock_docs = AsyncMock()
        mock_docs.create_document = AsyncMock(return_value="doc-html-001")
        mock_docs.insert_content = AsyncMock()

        step_fn = _make_docs_step(mock_docs, ctx_attr="html_doc_id")
        get_step = _route_steps(StepName.HTML_GENERATION, step_fn)

        with patch("ica.guided.runner.get_step_fn", get_step):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                # continue through steps 0-3, then stop at step 4 (HTML_GENERATION)
                prompt_fn=_inputs("c", "c", "c", "c", "s"),
            )

        html_step = state.steps[4]  # HTML_GENERATION
        assert html_step.status == StepStatus.COMPLETED
        assert html_step.artifacts["html_doc_id"] == "doc-html-001"
        assert "docs.google.com/document/d/doc-html-001" in html_step.artifacts["document_url"]

    async def test_extra_doc_id_in_email_subject_artifacts(self, store_dir: Path) -> None:
        """EMAIL_SUBJECT stores its doc_id via ctx.extra and it appears in artifacts."""
        mock_docs = AsyncMock()
        mock_docs.create_document = AsyncMock(return_value="doc-email-001")
        mock_docs.insert_content = AsyncMock()

        step_fn = _make_docs_step(mock_docs, extra_key="email_doc_id")
        get_step = _route_steps(StepName.EMAIL_SUBJECT, step_fn)

        with patch("ica.guided.runner.get_step_fn", get_step):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                # continue through steps 0-5, then stop at step 6 (EMAIL_SUBJECT)
                prompt_fn=_inputs("c", "c", "c", "c", "c", "c", "s"),
            )

        email_step = state.steps[6]  # EMAIL_SUBJECT
        assert email_step.status == StepStatus.COMPLETED
        assert email_step.artifacts["email_doc_id"] == "doc-email-001"
        assert "docs.google.com/document/d/doc-email-001" in email_step.artifacts["document_url"]


# ---------------------------------------------------------------------------
# (2) Sheets step writes rows and stores spreadsheet_id + row range
# ---------------------------------------------------------------------------


class TestSheetsStepWritesRows:
    """A Sheets step writes rows and the runner stores spreadsheet_id in artifacts."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with _patch_google_validation():
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_curation_artifacts_include_spreadsheet_id(
        self, store_dir: Path
    ) -> None:
        """CURATION step writes rows, artifacts contain spreadsheet_id and article_count."""
        mock_sheets = AsyncMock()
        mock_sheets.ensure_spreadsheet = AsyncMock(return_value="sheet-cur-001")
        mock_sheets.ensure_tab = AsyncMock()
        mock_sheets.append_rows = AsyncMock(return_value=1)

        step_fn = _make_sheets_step(mock_sheets)
        get_step = _route_steps(StepName.CURATION, step_fn)

        with (
            patch("ica.guided.runner.get_step_fn", get_step),
            _patch_sheets_refs(spreadsheet_id="sheet-cur-001"),
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                prompt_fn=_inputs("s"),  # stop after first step
            )

        cur_step = state.steps[0]  # CURATION
        assert cur_step.status == StepStatus.COMPLETED
        assert cur_step.artifacts["spreadsheet_id"] == "sheet-cur-001"
        assert cur_step.artifacts["article_count"] == 1
        assert cur_step.artifacts["newsletter_id"] == "NL-TEST-001"
        assert cur_step.artifacts["sheet_name"] == "Sheet1"

        mock_sheets.ensure_spreadsheet.assert_awaited_once()
        mock_sheets.ensure_tab.assert_awaited_once_with("sheet-cur-001", "Sheet1")
        mock_sheets.append_rows.assert_awaited_once()

    async def test_summarization_artifacts_include_spreadsheet_id(
        self, store_dir: Path
    ) -> None:
        """SUMMARIZATION step artifacts include spreadsheet_id and summary_count."""
        mock_sheets = AsyncMock()
        mock_sheets.ensure_spreadsheet = AsyncMock(return_value="sheet-sum-001")
        mock_sheets.ensure_tab = AsyncMock()
        mock_sheets.append_rows = AsyncMock(return_value=2)

        # Build a step function that sets ctx.summaries for SUMMARIZATION
        async def sum_step_fn(ctx: PipelineContext) -> PipelineContext:
            spreadsheet_id = await mock_sheets.ensure_spreadsheet("", "Test Summaries")
            await mock_sheets.ensure_tab(spreadsheet_id, "Sheet1")
            rows = [
                {"title": "Summary 1", "content": "..."},
                {"title": "Summary 2", "content": "..."},
            ]
            await mock_sheets.append_rows(spreadsheet_id, "Sheet1", rows)
            ctx.summaries = rows
            return ctx

        step_fn = AsyncMock(side_effect=sum_step_fn)
        get_step = _route_steps(StepName.SUMMARIZATION, step_fn)

        with (
            patch("ica.guided.runner.get_step_fn", get_step),
            _patch_sheets_refs(spreadsheet_id="sheet-sum-001"),
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                # continue past curation, stop at summarization
                prompt_fn=_inputs("c", "s"),
            )

        sum_step = state.steps[1]  # SUMMARIZATION
        assert sum_step.status == StepStatus.COMPLETED
        assert sum_step.artifacts["spreadsheet_id"] == "sheet-sum-001"
        assert sum_step.artifacts["summary_count"] == 2


# ---------------------------------------------------------------------------
# (3) Redo on a Docs step creates a second document (both IDs in history)
# ---------------------------------------------------------------------------


class TestDocsRedoCreatesSecondDocument:
    """Redo on a Docs step creates a new doc; the old doc_id is in artifact_history."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with _patch_google_validation():
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_redo_produces_two_distinct_doc_ids(self, store_dir: Path) -> None:
        """After redo, artifact_history has attempt 1's doc_id and current has attempt 2's."""
        mock_docs = AsyncMock()
        mock_docs.create_document = AsyncMock(side_effect=["doc-v1", "doc-v2"])
        mock_docs.insert_content = AsyncMock()

        step_fn = _make_docs_step(mock_docs)
        get_step = _route_steps(StepName.MARKDOWN_GENERATION, step_fn)

        with patch("ica.guided.runner.get_step_fn", get_step):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                # continue through 3 steps, then redo markdown, then stop
                prompt_fn=_inputs("c", "c", "c", "r", "s"),
            )

        md_step = state.steps[3]  # MARKDOWN_GENERATION
        assert md_step.status == StepStatus.COMPLETED
        assert md_step.attempt == 2

        # Current artifacts have the second doc
        assert md_step.artifacts["markdown_doc_id"] == "doc-v2"
        assert "doc-v2" in md_step.artifacts["document_url"]

        # Artifact history preserves the first doc
        assert len(md_step.artifact_history) == 1
        hist = md_step.artifact_history[0]
        assert hist["attempt"] == 1
        assert hist["artifacts"]["markdown_doc_id"] == "doc-v1"
        assert "doc-v1" in hist["artifacts"]["document_url"]

        # Service was called twice — once per attempt
        assert mock_docs.create_document.await_count == 2

    async def test_redo_clears_stale_doc_id_before_step_reruns(
        self, store_dir: Path
    ) -> None:
        """On redo, _prepare_redo_context clears the old doc_id so the step
        creates a fresh document instead of reusing the old one."""
        captured_doc_ids: list[str | None] = []
        mock_docs = AsyncMock()
        mock_docs.create_document = AsyncMock(side_effect=["doc-a", "doc-b"])
        mock_docs.insert_content = AsyncMock()

        async def capturing_step(ctx: PipelineContext) -> PipelineContext:
            # Capture the state of markdown_doc_id BEFORE we set it
            captured_doc_ids.append(ctx.markdown_doc_id)
            doc_id = await mock_docs.create_document("Test")
            await mock_docs.insert_content(doc_id, "Content")
            ctx.markdown_doc_id = doc_id
            return ctx

        step_fn = AsyncMock(side_effect=capturing_step)
        get_step = _route_steps(StepName.MARKDOWN_GENERATION, step_fn)

        with patch("ica.guided.runner.get_step_fn", get_step):
            await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                prompt_fn=_inputs("c", "c", "c", "r", "s"),
            )

        # First run: markdown_doc_id was None (never set before)
        assert captured_doc_ids[0] is None
        # Redo: _prepare_redo_context cleared it back to None
        assert captured_doc_ids[1] is None

    async def test_redo_extra_doc_step_clears_extra_key(self, store_dir: Path) -> None:
        """Redo on an extra-doc step (e.g. EMAIL_SUBJECT) clears the stale
        extra key so a fresh document is created."""
        mock_docs = AsyncMock()
        mock_docs.create_document = AsyncMock(side_effect=["email-v1", "email-v2"])
        mock_docs.insert_content = AsyncMock()

        step_fn = _make_docs_step(mock_docs, extra_key="email_doc_id")
        get_step = _route_steps(StepName.EMAIL_SUBJECT, step_fn)

        with patch("ica.guided.runner.get_step_fn", get_step):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                # continue through 6 steps, redo email_subject, then stop
                prompt_fn=_inputs("c", "c", "c", "c", "c", "c", "r", "s"),
            )

        email_step = state.steps[6]  # EMAIL_SUBJECT
        assert email_step.attempt == 2
        assert email_step.artifacts["email_doc_id"] == "email-v2"

        assert len(email_step.artifact_history) == 1
        assert email_step.artifact_history[0]["artifacts"]["email_doc_id"] == "email-v1"


# ---------------------------------------------------------------------------
# (4) Redo on a Sheets step appends versioned rows
# ---------------------------------------------------------------------------


class TestSheetsRedoAppendsVersionedRows:
    """Redo on a Sheets step injects guided_attempt so rows are tagged."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with _patch_google_validation():
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_redo_injects_attempt_tag_into_context(self, store_dir: Path) -> None:
        """On redo of CURATION, ctx.extra['guided_attempt'] == 2 so the step
        can tag its rows with the attempt number."""
        captured_attempts: list[int | None] = []
        mock_sheets = AsyncMock()
        mock_sheets.ensure_spreadsheet = AsyncMock(return_value="sheet-redo-001")
        mock_sheets.ensure_tab = AsyncMock()
        mock_sheets.append_rows = AsyncMock(return_value=1)

        async def tracking_step(ctx: PipelineContext) -> PipelineContext:
            captured_attempts.append(ctx.extra.get("guided_attempt"))
            spreadsheet_id = await mock_sheets.ensure_spreadsheet("", "Test")
            await mock_sheets.ensure_tab(spreadsheet_id, "Sheet1")
            rows = [{"title": "Article"}]
            attempt = ctx.extra.get("guided_attempt")
            if attempt:
                rows[0]["attempt"] = attempt
            await mock_sheets.append_rows(spreadsheet_id, "Sheet1", rows)
            ctx.articles = rows
            ctx.newsletter_id = "NL-TEST-002"
            return ctx

        step_fn = AsyncMock(side_effect=tracking_step)
        get_step = _route_steps(StepName.CURATION, step_fn)

        with (
            patch("ica.guided.runner.get_step_fn", get_step),
            _patch_sheets_refs(spreadsheet_id="sheet-redo-001"),
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                prompt_fn=_inputs("r", "s"),  # redo curation, then stop
            )

        # First attempt: no guided_attempt tag
        assert captured_attempts[0] is None
        # Second attempt: guided_attempt == 2
        assert captured_attempts[1] == 2

        # Step ran twice
        assert mock_sheets.append_rows.await_count == 2
        assert state.steps[0].attempt == 2

    async def test_redo_sheets_rows_tagged_with_attempt(self, store_dir: Path) -> None:
        """Rows appended on redo carry the attempt number in their data."""
        appended_rows: list[list[dict]] = []
        mock_sheets = AsyncMock()
        mock_sheets.ensure_spreadsheet = AsyncMock(return_value="sheet-tag-001")
        mock_sheets.ensure_tab = AsyncMock()

        async def capture_append(
            spreadsheet_id: str, sheet_name: str, rows: list[dict]
        ) -> int:
            appended_rows.append(rows)
            return len(rows)

        mock_sheets.append_rows = AsyncMock(side_effect=capture_append)

        step_fn = _make_sheets_step(mock_sheets)
        get_step = _route_steps(StepName.CURATION, step_fn)

        with (
            patch("ica.guided.runner.get_step_fn", get_step),
            _patch_sheets_refs(spreadsheet_id="sheet-tag-001"),
        ):
            await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                prompt_fn=_inputs("r", "s"),  # redo, then stop
            )

        # First call: no attempt tag
        assert "attempt" not in appended_rows[0][0]
        # Second call: attempt == 2
        assert appended_rows[1][0]["attempt"] == 2

    async def test_redo_sheets_artifact_history_preserved(
        self, store_dir: Path
    ) -> None:
        """After redo, artifact_history contains attempt 1's artifacts."""
        mock_sheets = AsyncMock()
        mock_sheets.ensure_spreadsheet = AsyncMock(return_value="sheet-hist-001")
        mock_sheets.ensure_tab = AsyncMock()
        mock_sheets.append_rows = AsyncMock(return_value=1)

        step_fn = _make_sheets_step(mock_sheets)
        get_step = _route_steps(StepName.CURATION, step_fn)

        with (
            patch("ica.guided.runner.get_step_fn", get_step),
            _patch_sheets_refs(spreadsheet_id="sheet-hist-001"),
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                prompt_fn=_inputs("r", "s"),
            )

        cur_step = state.steps[0]  # CURATION

        # Artifact history has attempt 1
        assert len(cur_step.artifact_history) == 1
        hist = cur_step.artifact_history[0]
        assert hist["attempt"] == 1
        assert hist["artifacts"]["spreadsheet_id"] == "sheet-hist-001"
        assert hist["artifacts"]["article_count"] == 1

        # Current artifacts have attempt 2
        assert cur_step.artifacts["spreadsheet_id"] == "sheet-hist-001"
        assert cur_step.artifacts["article_count"] == 1


# ---------------------------------------------------------------------------
# (5) Missing target ID at startup raises clear validation error
# ---------------------------------------------------------------------------


def _mock_settings(*, spreadsheet_id: str = "", drive_folder_id: str = "") -> MagicMock:
    s = MagicMock()
    s.guided_test_spreadsheet_id = spreadsheet_id
    s.guided_test_drive_folder_id = drive_folder_id
    return s


class TestMissingTargetIdValidation:
    """Missing Google target IDs abort the guided run at startup."""

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    @patch("ica.config.settings.get_settings")
    async def test_missing_sheets_id_aborts_run(
        self, mock_get: MagicMock, store_dir: Path
    ) -> None:
        """Run aborts when GUIDED_TEST_SPREADSHEET_ID is missing and Sheets steps are in path."""
        mock_get.return_value = _mock_settings()

        state = await run_guided(
            store_dir=store_dir,
            console=MagicMock(),
            prompt_fn=_inputs("s"),
        )

        assert state.phase == RunPhase.ABORTED

    @patch("ica.config.settings.get_settings")
    async def test_missing_docs_folder_aborts_run(
        self, mock_get: MagicMock, store_dir: Path
    ) -> None:
        """Run aborts when GUIDED_TEST_DRIVE_FOLDER_ID is missing and Docs steps are in path."""
        mock_get.return_value = _mock_settings()

        state = await run_guided(
            store_dir=store_dir,
            console=MagicMock(),
            prompt_fn=_inputs("s"),
        )

        assert state.phase == RunPhase.ABORTED

    @patch("ica.config.settings.get_settings")
    async def test_missing_id_error_mentions_setting_name(
        self, mock_get: MagicMock, store_dir: Path
    ) -> None:
        """The abort message includes the name of the missing setting."""
        console = MagicMock()
        mock_get.return_value = _mock_settings()

        await run_guided(
            store_dir=store_dir,
            console=console,
            prompt_fn=_inputs("s"),
        )

        # Console should have printed the error with the setting name
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "GUIDED_TEST_SPREADSHEET_ID" in printed or "GUIDED_TEST_DRIVE_FOLDER_ID" in printed

    @patch("ica.config.settings.get_settings")
    async def test_configured_ids_allow_run_to_proceed(
        self, mock_get: MagicMock, store_dir: Path
    ) -> None:
        """When all Google target IDs are set, the run proceeds past validation."""
        mock_get.return_value = _mock_settings(
            spreadsheet_id="sheet-ok-001",
            drive_folder_id="folder-ok-001",
        )
        step_fn = _noop_step()

        with patch("ica.guided.runner.get_step_fn", return_value=step_fn):
            state = await run_guided(
                store_dir=store_dir,
                console=MagicMock(),
                prompt_fn=_inputs("s"),  # stop after first step
            )

        # Run proceeded past validation (step 0 completed, then aborted by operator)
        assert state.steps[0].status == StepStatus.COMPLETED
        assert state.phase == RunPhase.ABORTED
