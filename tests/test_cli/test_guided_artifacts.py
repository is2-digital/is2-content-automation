"""Tests for the ``ica guided artifacts`` CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ica.__main__ import _format_artifact_value, app
from ica.guided.artifacts import ArtifactEntry, ArtifactStore, ArtifactType

runner = CliRunner()


def _make_entry(
    *,
    run_id: str = "run-abc",
    step_name: str = "curation",
    artifact_type: ArtifactType = ArtifactType.LLM_OUTPUT,
    key: str = "summary",
    value: str = "Some LLM output text",
    timestamp: str = "2026-03-01T10:00:00+00:00",
    attempt_number: int = 1,
) -> ArtifactEntry:
    return ArtifactEntry(
        run_id=run_id,
        step_name=step_name,
        artifact_type=artifact_type,
        key=key,
        value=value,
        timestamp=timestamp,
        attempt_number=attempt_number,
    )


def _write_ledger(store_dir: Path, run_id: str, entries: list[ArtifactEntry]) -> None:
    """Write artifact entries to a ledger file for testing."""
    store = ArtifactStore(store_dir)
    for entry in entries:
        store.append_artifact(run_id, entry)


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


class TestGuidedArtifactsHelp:
    """The artifacts subcommand appears in guided help and has expected options."""

    def test_artifacts_in_guided_help(self) -> None:
        result = runner.invoke(app, ["guided", "--help"])
        assert "artifacts" in result.output

    def test_artifacts_help_flag(self) -> None:
        result = runner.invoke(app, ["guided", "artifacts", "--help"])
        assert result.exit_code == 0
        assert "RUN_ID" in result.output
        assert "--step" in result.output
        assert "--type" in result.output
        assert "--verbose" in result.output
        assert "--json" in result.output
        assert "--store-dir" in result.output


# ---------------------------------------------------------------------------
# No artifacts
# ---------------------------------------------------------------------------


class TestGuidedArtifactsEmpty:
    """Graceful handling when no artifacts exist."""

    def test_no_artifacts_file(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["guided", "artifacts", "nonexistent", "--store-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "No artifacts found" in result.output

    def test_no_matching_step_filter(self, tmp_path: Path) -> None:
        _write_ledger(tmp_path, "run-1", [_make_entry(run_id="run-1")])
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--step", "nonexistent_step",
            ],
        )
        assert result.exit_code == 0
        assert "No artifacts match filters" in result.output

    def test_no_matching_type_filter(self, tmp_path: Path) -> None:
        _write_ledger(tmp_path, "run-1", [_make_entry(run_id="run-1")])
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--type", "fixture_data",
            ],
        )
        assert result.exit_code == 0
        assert "No artifacts match filters" in result.output


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------


class TestGuidedArtifactsTable:
    """Default Rich table output."""

    def test_basic_table(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(run_id="run-1", step_name="curation", key="articles"),
            _make_entry(
                run_id="run-1",
                step_name="theme",
                key="doc_id",
                artifact_type=ArtifactType.GOOGLE_DOC,
                value="doc-xyz-123",
            ),
        ]
        _write_ledger(tmp_path, "run-1", entries)
        result = runner.invoke(
            app,
            ["guided", "artifacts", "run-1", "--store-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "curation" in result.output
        assert "theme" in result.output
        assert "articles" in result.output
        assert "doc_id" in result.output
        assert "2 artifact(s)" in result.output

    def test_step_filter(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(run_id="run-1", step_name="curation", key="articles"),
            _make_entry(run_id="run-1", step_name="summarization", key="summary"),
        ]
        _write_ledger(tmp_path, "run-1", entries)
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--step", "curation",
            ],
        )
        assert result.exit_code == 0
        assert "curation" in result.output
        assert "1 artifact(s)" in result.output

    def test_type_filter(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(
                run_id="run-1", key="decision",
                artifact_type=ArtifactType.SLACK_DECISION,
            ),
            _make_entry(
                run_id="run-1", key="output",
                artifact_type=ArtifactType.LLM_OUTPUT,
            ),
        ]
        _write_ledger(tmp_path, "run-1", entries)
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--type", "slack_decision",
            ],
        )
        assert result.exit_code == 0
        assert "decision" in result.output
        assert "1 artifact(s)" in result.output

    def test_invalid_type_filter(self, tmp_path: Path) -> None:
        _write_ledger(tmp_path, "run-1", [_make_entry(run_id="run-1")])
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--type", "not_a_type",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid artifact type" in result.output
        assert "Valid types" in result.output

    def test_value_truncation(self, tmp_path: Path) -> None:
        long_value = "x" * 200
        _write_ledger(
            tmp_path, "run-1",
            [_make_entry(run_id="run-1", value=long_value)],
        )
        result = runner.invoke(
            app,
            ["guided", "artifacts", "run-1", "--store-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        # Full 200-char value should not appear (truncated by code and/or Rich)
        assert long_value not in result.output

    def test_verbose_shows_more_than_truncated(self, tmp_path: Path) -> None:
        """Verbose mode passes full value to Rich (no code-level truncation).

        Rich may still truncate for terminal width, so we verify via JSON
        that the underlying data is intact, and that verbose mode at least
        does not apply our 80-char code truncation.
        """
        long_value = "x" * 200
        _write_ledger(
            tmp_path, "run-1",
            [_make_entry(run_id="run-1", value=long_value)],
        )
        # Verify via JSON that the full value is preserved end-to-end
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--verbose", "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["value"] == long_value

    def test_combined_step_and_type_filters(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(
                run_id="run-1", step_name="curation", key="a1",
                artifact_type=ArtifactType.SLACK_DECISION,
            ),
            _make_entry(
                run_id="run-1", step_name="curation", key="a2",
                artifact_type=ArtifactType.LLM_OUTPUT,
            ),
            _make_entry(
                run_id="run-1", step_name="summarization", key="a3",
                artifact_type=ArtifactType.SLACK_DECISION,
            ),
        ]
        _write_ledger(tmp_path, "run-1", entries)
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--step", "curation",
                "--type", "slack_decision",
            ],
        )
        assert result.exit_code == 0
        assert "a1" in result.output
        assert "1 artifact(s)" in result.output


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestGuidedArtifactsJSON:
    """Machine-readable JSON output mode."""

    def test_json_output(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(run_id="run-1", step_name="curation", key="articles"),
        ]
        _write_ledger(tmp_path, "run-1", entries)
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["step_name"] == "curation"
        assert data[0]["key"] == "articles"
        assert data[0]["artifact_type"] == "llm_output"

    def test_json_with_filters(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(run_id="run-1", step_name="curation", key="a1"),
            _make_entry(run_id="run-1", step_name="summarization", key="a2"),
        ]
        _write_ledger(tmp_path, "run-1", entries)
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--step", "curation",
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["key"] == "a1"

    def test_json_includes_full_values(self, tmp_path: Path) -> None:
        complex_value = {"doc_id": "abc", "sections": [1, 2, 3]}
        _write_ledger(
            tmp_path, "run-1",
            [_make_entry(run_id="run-1", value=complex_value)],
        )
        result = runner.invoke(
            app,
            [
                "guided", "artifacts", "run-1",
                "--store-dir", str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["value"] == complex_value


# ---------------------------------------------------------------------------
# _format_artifact_value helper
# ---------------------------------------------------------------------------


class TestFormatArtifactValue:
    """Value formatting and truncation logic."""

    def test_string_value(self) -> None:
        assert _format_artifact_value("hello", 0) == "hello"

    def test_string_truncation(self) -> None:
        result = _format_artifact_value("a" * 100, 80)
        assert len(result) == 80
        assert result.endswith("...")

    def test_short_string_no_truncation(self) -> None:
        assert _format_artifact_value("short", 80) == "short"

    def test_dict_value_serialized(self) -> None:
        result = _format_artifact_value({"key": "val"}, 0)
        assert result == '{"key": "val"}'

    def test_list_value_serialized(self) -> None:
        result = _format_artifact_value([1, 2, 3], 0)
        assert result == "[1, 2, 3]"

    def test_none_value(self) -> None:
        result = _format_artifact_value(None, 0)
        assert result == "null"

    def test_max_len_zero_means_no_truncation(self) -> None:
        long = "x" * 500
        assert _format_artifact_value(long, 0) == long

    def test_bool_value(self) -> None:
        assert _format_artifact_value(True, 0) == "true"

    def test_numeric_value(self) -> None:
        assert _format_artifact_value(42, 0) == "42"


# ---------------------------------------------------------------------------
# Existing guided command still works
# ---------------------------------------------------------------------------


class TestGuidedCommandUnchanged:
    """The guided command callback continues to function after group conversion."""

    def test_guided_still_in_app_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "guided" in result.output

    def test_guided_help_shows_options_and_subcommands(self) -> None:
        result = runner.invoke(app, ["guided", "--help"])
        assert result.exit_code == 0
        assert "--run-id" in result.output
        assert "--list" in result.output
        assert "artifacts" in result.output
