"""End-to-end artifact completeness tests for the guided pipeline flow.

Runs a full 9-step guided flow with mocked services and verifies:
- Every step emits at least one artifact entry
- Artifact types are correct per step
- Redo produces additional entries without losing prior ones
- Ledger is queryable by step and type
- CLI subcommand renders the ledger correctly (table and JSON)
- Persistence round-trip preserves all entries
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ica.__main__ import app
from ica.guided.artifacts import ArtifactStore, ArtifactType
from ica.guided.runner import run_guided
from ica.guided.state import RunPhase, StepStatus
from ica.pipeline.orchestrator import PipelineContext, StepName

cli_runner = CliRunner()

# ---------------------------------------------------------------------------
# Step data — what each mock step puts on the context
# ---------------------------------------------------------------------------

# Map step name → function that mutates PipelineContext with realistic data.
# This ensures _build_step_entries will emit at least one entry per step.

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

# Expected artifact types per step (at minimum)
_EXPECTED_TYPES: dict[str, set[ArtifactType]] = {
    StepName.CURATION.value: {ArtifactType.LLM_OUTPUT, ArtifactType.GOOGLE_SHEET},
    StepName.SUMMARIZATION.value: {ArtifactType.LLM_OUTPUT, ArtifactType.GOOGLE_SHEET},
    StepName.THEME_GENERATION.value: {ArtifactType.LLM_OUTPUT},
    StepName.MARKDOWN_GENERATION.value: {ArtifactType.GOOGLE_DOC},
    StepName.HTML_GENERATION.value: {ArtifactType.GOOGLE_DOC},
    StepName.ALTERNATES_HTML.value: {ArtifactType.LLM_OUTPUT},
    StepName.EMAIL_SUBJECT.value: {ArtifactType.LLM_OUTPUT, ArtifactType.GOOGLE_DOC},
    StepName.SOCIAL_MEDIA.value: {ArtifactType.GOOGLE_DOC},
    StepName.LINKEDIN_CAROUSEL.value: {ArtifactType.GOOGLE_DOC},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """Patch _get_sheets_refs to return predictable values."""
    return patch("ica.guided.runner._get_sheets_refs", return_value=_SHEETS_REFS)


# ---------------------------------------------------------------------------
# Full-flow artifact completeness
# ---------------------------------------------------------------------------


class TestFullFlowArtifactCompleteness:
    """Run all 9 steps and verify every step emits correct artifacts."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def _run_full_flow(self, store_dir: Path) -> tuple[str, ArtifactStore]:
        """Execute a full 9-step guided run and return (run_id, artifact_store)."""
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        assert state.phase == RunPhase.COMPLETED
        assert all(s.status == StepStatus.COMPLETED for s in state.steps)

        artifact_store = ArtifactStore(store_dir)
        return state.run_id, artifact_store

    async def test_every_step_emits_at_least_one_artifact(
        self, store_dir: Path
    ) -> None:
        run_id, store = await self._run_full_flow(store_dir)
        ledger = store.get_ledger(run_id)

        for step_name in StepName:
            step_entries = ledger.by_step(step_name.value)
            assert len(step_entries) >= 1, (
                f"Step '{step_name.value}' emitted no artifacts"
            )

    async def test_artifact_types_correct_per_step(self, store_dir: Path) -> None:
        run_id, store = await self._run_full_flow(store_dir)
        ledger = store.get_ledger(run_id)

        for step_name_str, expected_types in _EXPECTED_TYPES.items():
            step_entries = ledger.by_step(step_name_str)
            actual_types = {e.artifact_type for e in step_entries}
            assert expected_types <= actual_types, (
                f"Step '{step_name_str}': expected types {expected_types}, "
                f"got {actual_types}"
            )

    async def test_all_entries_carry_correct_run_id(self, store_dir: Path) -> None:
        run_id, store = await self._run_full_flow(store_dir)
        ledger = store.get_ledger(run_id)

        for entry in ledger.entries:
            assert entry.run_id == run_id

    async def test_all_entries_have_timestamps(self, store_dir: Path) -> None:
        run_id, store = await self._run_full_flow(store_dir)
        ledger = store.get_ledger(run_id)

        for entry in ledger.entries:
            assert entry.timestamp, f"Entry {entry.key} missing timestamp"

    async def test_all_first_attempt_entries(self, store_dir: Path) -> None:
        run_id, store = await self._run_full_flow(store_dir)
        ledger = store.get_ledger(run_id)

        for entry in ledger.entries:
            assert entry.attempt_number == 1

    async def test_total_artifact_count(self, store_dir: Path) -> None:
        """Full flow should produce at least 9 entries (one per step minimum)."""
        run_id, store = await self._run_full_flow(store_dir)
        ledger = store.get_ledger(run_id)
        assert len(ledger.entries) >= 9


# ---------------------------------------------------------------------------
# Redo preserves prior entries
# ---------------------------------------------------------------------------


class TestRedoPreservesArtifacts:
    """Redo produces additional entries without losing prior ones."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_redo_first_step_adds_entries(self, store_dir: Path) -> None:
        """Redo the first step (curation), then continue — both attempts present."""
        console = Console(file=MagicMock())
        # Redo curation, then continue through all remaining steps
        inputs = iter(["r", "c"] + ["c"] * 8)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        assert state.phase == RunPhase.COMPLETED
        assert state.steps[0].attempt == 2

        store = ArtifactStore(store_dir)
        ledger = store.get_ledger(state.run_id)

        # Curation entries from both attempts
        curation_entries = ledger.by_step("curation")
        attempt_1 = [e for e in curation_entries if e.attempt_number == 1]
        attempt_2 = [e for e in curation_entries if e.attempt_number == 2]
        assert len(attempt_1) >= 1, "First attempt entries missing"
        assert len(attempt_2) >= 1, "Second attempt entries missing"

    async def test_redo_does_not_erase_other_step_entries(
        self, store_dir: Path
    ) -> None:
        """Redo a middle step — entries from prior steps remain intact."""
        console = Console(file=MagicMock())
        # Complete steps 1-3, redo step 3 (theme_generation), then continue
        inputs = iter(["c", "c", "r", "c"] + ["c"] * 6)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        assert state.phase == RunPhase.COMPLETED

        store = ArtifactStore(store_dir)
        ledger = store.get_ledger(state.run_id)

        # Curation and summarization entries still present
        assert len(ledger.by_step("curation")) >= 1
        assert len(ledger.by_step("summarization")) >= 1

        # Theme generation has entries from both attempts
        theme_entries = ledger.by_step("theme_generation")
        assert len(theme_entries) >= 2

    async def test_redo_attempt_numbers_increment(self, store_dir: Path) -> None:
        """Redo entries have correct attempt_number values."""
        console = Console(file=MagicMock())
        # Redo curation twice, then continue
        inputs = iter(["r", "r", "c"] + ["c"] * 8)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        assert state.phase == RunPhase.COMPLETED
        assert state.steps[0].attempt == 3

        store = ArtifactStore(store_dir)
        ledger = store.get_ledger(state.run_id)

        curation_entries = ledger.by_step("curation")
        attempts = sorted({e.attempt_number for e in curation_entries})
        assert attempts == [1, 2, 3]


# ---------------------------------------------------------------------------
# Ledger queryability
# ---------------------------------------------------------------------------


class TestLedgerQueryability:
    """The full-flow ledger supports filtering by step and type."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def _run_and_get_ledger(self, store_dir: Path):
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        store = ArtifactStore(store_dir)
        return state.run_id, store.get_ledger(state.run_id)

    async def test_by_step_returns_only_matching(self, store_dir: Path) -> None:
        _, ledger = await self._run_and_get_ledger(store_dir)

        for step_name in StepName:
            filtered = ledger.by_step(step_name.value)
            assert all(e.step_name == step_name.value for e in filtered)

    async def test_by_type_returns_only_matching(self, store_dir: Path) -> None:
        _, ledger = await self._run_and_get_ledger(store_dir)

        for atype in ArtifactType:
            filtered = ledger.by_type(atype)
            assert all(e.artifact_type == atype for e in filtered)

    async def test_google_doc_entries_span_multiple_steps(
        self, store_dir: Path
    ) -> None:
        _, ledger = await self._run_and_get_ledger(store_dir)

        doc_entries = ledger.by_type(ArtifactType.GOOGLE_DOC)
        steps_with_docs = {e.step_name for e in doc_entries}
        # At minimum: markdown, html, email, social_media, linkedin_carousel
        assert len(steps_with_docs) >= 5

    async def test_llm_output_entries_span_multiple_steps(
        self, store_dir: Path
    ) -> None:
        _, ledger = await self._run_and_get_ledger(store_dir)

        llm_entries = ledger.by_type(ArtifactType.LLM_OUTPUT)
        steps_with_llm = {e.step_name for e in llm_entries}
        # At minimum: curation, summarization, theme, alternates, email_subject
        assert len(steps_with_llm) >= 5

    async def test_by_attempt_filters_correctly(self, store_dir: Path) -> None:
        _, ledger = await self._run_and_get_ledger(store_dir)

        attempt_1 = ledger.by_attempt(1)
        assert len(attempt_1) == len(ledger.entries)  # All entries are attempt 1

        attempt_2 = ledger.by_attempt(2)
        assert len(attempt_2) == 0  # No redo in this run

    async def test_store_get_artifacts_for_step(self, store_dir: Path) -> None:
        """ArtifactStore.get_artifacts_for_step convenience method works."""
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        store = ArtifactStore(store_dir)
        for step_name in StepName:
            entries = store.get_artifacts_for_step(state.run_id, step_name.value)
            assert len(entries) >= 1


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


class TestPersistenceRoundTrip:
    """Artifact file survives write-read-write cycles with full fidelity."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_ledger_file_is_valid_json(self, store_dir: Path) -> None:
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        ledger_path = store_dir / f"{state.run_id}-artifacts.json"
        assert ledger_path.exists()
        data = json.loads(ledger_path.read_text())
        assert isinstance(data, list)
        assert len(data) >= 9

    async def test_all_fields_survive_round_trip(self, store_dir: Path) -> None:
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        store = ArtifactStore(store_dir)
        ledger = store.get_ledger(state.run_id)

        for entry in ledger.entries:
            assert entry.run_id == state.run_id
            assert entry.step_name  # non-empty
            assert isinstance(entry.artifact_type, ArtifactType)
            assert entry.key  # non-empty
            assert entry.value is not None
            assert entry.timestamp  # non-empty
            assert entry.attempt_number >= 1
            assert isinstance(entry.metadata, dict)

    async def test_raw_json_matches_loaded_ledger(self, store_dir: Path) -> None:
        """Raw JSON on disk matches what ArtifactStore loads."""
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        store = ArtifactStore(store_dir)
        ledger = store.get_ledger(state.run_id)

        ledger_path = store_dir / f"{state.run_id}-artifacts.json"
        raw_data = json.loads(ledger_path.read_text())

        assert len(raw_data) == len(ledger.entries)
        for raw, entry in zip(raw_data, ledger.entries, strict=True):
            assert raw["run_id"] == entry.run_id
            assert raw["step_name"] == entry.step_name
            assert raw["artifact_type"] == entry.artifact_type.value
            assert raw["key"] == entry.key
            assert raw["value"] == entry.value


# ---------------------------------------------------------------------------
# CLI subcommand with full-flow data
# ---------------------------------------------------------------------------


class TestCLIWithFullFlowData:
    """The CLI artifacts subcommand renders full-flow data correctly."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def _run_and_get_run_id(self, store_dir: Path) -> str:
        console = Console(file=MagicMock())
        inputs = iter(["c"] * 9)

        with _patch_all_steps(), _patch_sheets_refs():
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
            )

        assert state.phase == RunPhase.COMPLETED
        return state.run_id

    async def test_table_output_shows_all_steps(self, store_dir: Path) -> None:
        run_id = await self._run_and_get_run_id(store_dir)
        result = cli_runner.invoke(
            app,
            ["guided", "artifacts", run_id, "--store-dir", str(store_dir)],
        )
        assert result.exit_code == 0
        # Rich truncates long column values with ellipsis, so check for
        # a prefix (first 8 chars) that fits within the column width.
        for step_name in StepName:
            prefix = step_name.value[:8]
            assert prefix in result.output, (
                f"Step '{step_name.value}' (prefix '{prefix}') "
                "missing from CLI table output"
            )
        assert "artifact(s)" in result.output

    async def test_json_output_is_parseable(self, store_dir: Path) -> None:
        run_id = await self._run_and_get_run_id(store_dir)
        result = cli_runner.invoke(
            app,
            [
                "guided", "artifacts", run_id,
                "--store-dir", str(store_dir),
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 9

    async def test_json_entries_have_required_fields(self, store_dir: Path) -> None:
        run_id = await self._run_and_get_run_id(store_dir)
        result = cli_runner.invoke(
            app,
            [
                "guided", "artifacts", run_id,
                "--store-dir", str(store_dir),
                "--json",
            ],
        )
        data = json.loads(result.output)
        required_fields = {
            "run_id", "step_name", "artifact_type", "key", "value",
            "timestamp", "attempt_number", "metadata",
        }
        for entry in data:
            assert required_fields <= set(entry.keys()), (
                f"Entry missing fields: {required_fields - set(entry.keys())}"
            )

    async def test_json_step_filter(self, store_dir: Path) -> None:
        run_id = await self._run_and_get_run_id(store_dir)
        result = cli_runner.invoke(
            app,
            [
                "guided", "artifacts", run_id,
                "--store-dir", str(store_dir),
                "--step", "curation",
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(e["step_name"] == "curation" for e in data)
        assert len(data) >= 1

    async def test_json_type_filter(self, store_dir: Path) -> None:
        run_id = await self._run_and_get_run_id(store_dir)
        result = cli_runner.invoke(
            app,
            [
                "guided", "artifacts", run_id,
                "--store-dir", str(store_dir),
                "--type", "google_doc",
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(e["artifact_type"] == "google_doc" for e in data)
        assert len(data) >= 5  # md, html, email, social, linkedin

    async def test_table_step_filter(self, store_dir: Path) -> None:
        run_id = await self._run_and_get_run_id(store_dir)
        result = cli_runner.invoke(
            app,
            [
                "guided", "artifacts", run_id,
                "--store-dir", str(store_dir),
                "--step", "markdown_generation",
            ],
        )
        assert result.exit_code == 0
        # Rich may truncate "markdown_generation" to "markdown_ge…"
        assert "markdown" in result.output
        assert "1 artifact(s)" in result.output
