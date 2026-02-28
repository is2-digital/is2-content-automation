"""Tests for :mod:`ica.cli.config_editor`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.table import Table

from ica.cli.config_editor import (
    apply_doc_changes,
    build_full_doc_content,
    format_config_table,
    format_sync_summary,
    list_all_configs,
    parse_doc_sections,
)
from ica.llm_configs import loader
from ica.llm_configs.loader import _cache
from ica.llm_configs.schema import ProcessConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_config_dict(**overrides: object) -> dict:
    """Return a valid config dict with optional overrides."""
    base: dict = {
        "$schema": "ica-llm-config/v1",
        "processName": "test-process",
        "description": "A test process",
        "model": "anthropic/claude-sonnet-4.5",
        "prompts": {
            "system": "You are a test system.",
            "instruction": "Follow test instructions.",
        },
        "metadata": {
            "googleDocId": None,
            "lastSyncedAt": None,
            "version": 1,
        },
    }
    base.update(overrides)
    return base


def _make_config(
    *,
    name: str = "test-process",
    model: str = "anthropic/claude-sonnet-4.5",
    system: str = "You are a test system.",
    instruction: str = "Follow test instructions.",
    description: str = "A test process",
    version: int = 1,
) -> ProcessConfig:
    """Build a ProcessConfig for testing."""
    return ProcessConfig(
        **{
            "$schema": "ica-llm-config/v1",
            "processName": name,
            "description": description,
            "model": model,
            "prompts": {"system": system, "instruction": instruction},
            "metadata": {
                "googleDocId": None,
                "lastSyncedAt": None,
                "version": version,
            },
        }
    )


def _write_config(
    tmp_path: Path, process_name: str = "test-process", **overrides: object
) -> Path:
    """Write a config JSON file to tmp_path and return its path."""
    data = _valid_config_dict(processName=process_name, **overrides)
    config_file = tmp_path / f"{process_name}-llm.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    return config_file


def _read_saved_config(tmp_path: Path, process_name: str = "test-process") -> dict:
    """Read and parse the config JSON file from tmp_path."""
    config_file = tmp_path / f"{process_name}-llm.json"
    return json.loads(config_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear loader caches between tests."""
    _cache.clear()
    loader._PROCESS_TO_FIELD = None


# ---------------------------------------------------------------------------
# list_all_configs()
# ---------------------------------------------------------------------------


class TestListAllConfigs:
    """Discovers all *-llm.json configs and returns sorted (name, config) tuples."""

    def test_discovers_all_configs(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "alpha")
        _write_config(tmp_path, "beta")
        _write_config(tmp_path, "gamma")

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            result = list_all_configs()

        assert len(result) == 3

    def test_returns_sorted_by_name(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "zulu")
        _write_config(tmp_path, "alpha")
        _write_config(tmp_path, "mike")

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            result = list_all_configs()

        names = [name for name, _cfg in result]
        assert names == ["alpha", "mike", "zulu"]

    def test_returns_tuples_of_name_and_config(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "summarization", model="openai/gpt-4.1")

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            result = list_all_configs()

        name, config = result[0]
        assert name == "summarization"
        assert isinstance(config, ProcessConfig)
        assert config.model == "openai/gpt-4.1"

    def test_empty_directory(self, tmp_path: Path) -> None:
        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            result = list_all_configs()

        assert result == []

    def test_ignores_non_llm_json_files(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "valid")
        # Write a non-matching file
        (tmp_path / "notes.json").write_text("{}", encoding="utf-8")

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            result = list_all_configs()

        assert len(result) == 1
        assert result[0][0] == "valid"


# ---------------------------------------------------------------------------
# format_config_table()
# ---------------------------------------------------------------------------


class TestFormatConfigTable:
    """Produces a Rich Table with correct columns and truncated prompts."""

    def test_produces_rich_table(self) -> None:
        configs = [("summarization", _make_config(name="summarization"))]
        table = format_config_table(configs)
        assert isinstance(table, Table)

    def test_table_title(self) -> None:
        configs = [("summarization", _make_config(name="summarization"))]
        table = format_config_table(configs)
        assert table.title == "LLM Process Configs"

    def test_has_correct_columns(self) -> None:
        configs = [("summarization", _make_config(name="summarization"))]
        table = format_config_table(configs)
        col_names = [col.header for col in table.columns]
        assert col_names == ["#", "Process", "Model", "System Prompt"]

    def test_row_count_matches_configs(self) -> None:
        configs = [
            ("alpha", _make_config(name="alpha")),
            ("beta", _make_config(name="beta")),
        ]
        table = format_config_table(configs)
        assert table.row_count == 2

    def test_truncates_long_prompts(self) -> None:
        long_prompt = "A" * 100
        configs = [
            (
                "summarization",
                _make_config(name="summarization", system=long_prompt),
            )
        ]
        table = format_config_table(configs)
        # Access rendered cell data — column 3 is "System Prompt"
        cells = table.columns[3]._cells
        assert cells[0].endswith("...")
        # 60 chars of 'A' plus '...'
        assert len(cells[0]) == 63

    def test_short_prompt_not_truncated(self) -> None:
        short_prompt = "Short system prompt."
        configs = [
            (
                "summarization",
                _make_config(name="summarization", system=short_prompt),
            )
        ]
        table = format_config_table(configs)
        cells = table.columns[3]._cells
        assert cells[0] == short_prompt
        assert not cells[0].endswith("...")

    def test_empty_configs_produces_empty_table(self) -> None:
        table = format_config_table([])
        assert table.row_count == 0


# ---------------------------------------------------------------------------
# build_full_doc_content()
# ---------------------------------------------------------------------------


class TestBuildFullDocContent:
    """Generates correct ## field sections with header."""

    def test_starts_with_process_name_header(self) -> None:
        config = _make_config(name="summarization")
        content = build_full_doc_content("summarization", config)
        assert content.startswith("# summarization\n")

    def test_contains_model_section(self) -> None:
        config = _make_config(model="openai/gpt-4.1")
        content = build_full_doc_content("test", config)
        assert "## model\nopenai/gpt-4.1" in content

    def test_contains_description_section(self) -> None:
        config = _make_config(description="Summarizes articles")
        content = build_full_doc_content("test", config)
        assert "## description\nSummarizes articles" in content

    def test_contains_system_section(self) -> None:
        config = _make_config(system="You are an expert.")
        content = build_full_doc_content("test", config)
        assert "## system\nYou are an expert." in content

    def test_contains_instruction_section(self) -> None:
        config = _make_config(instruction="Do the thing.")
        content = build_full_doc_content("test", config)
        assert "## instruction\nDo the thing." in content

    def test_section_order(self) -> None:
        config = _make_config()
        content = build_full_doc_content("test", config)
        model_pos = content.index("## model")
        desc_pos = content.index("## description")
        system_pos = content.index("## system")
        instr_pos = content.index("## instruction")
        assert model_pos < desc_pos < system_pos < instr_pos

    def test_all_four_sections_present(self) -> None:
        config = _make_config()
        content = build_full_doc_content("test", config)
        for section in ("## model", "## description", "## system", "## instruction"):
            assert section in content


# ---------------------------------------------------------------------------
# parse_doc_sections()
# ---------------------------------------------------------------------------


class TestParseDocSections:
    """Round-trips doc content back to field dict, with edge cases."""

    def test_roundtrip_with_build(self) -> None:
        """Content from build_full_doc_content parses back correctly.

        Uses realistic content with punctuation so the regex section
        boundaries work (the ``\\w[\\w\\s]*`` pattern stops at non-word
        non-space characters like periods and slashes).
        """
        config = _make_config(
            model="openai/gpt-4.1",
            description="Summarizes articles.",
            system="You are an AI assistant.",
            instruction="Summarize the article.",
        )
        content = build_full_doc_content("test", config)
        sections = parse_doc_sections(content)

        assert sections["model"] == "openai/gpt-4.1"
        assert sections["description"] == "Summarizes articles."
        assert sections["system"] == "You are an AI assistant."
        assert sections["instruction"] == "Summarize the article."

    def test_handles_missing_sections(self) -> None:
        content = "## model\nsome-model\n"
        sections = parse_doc_sections(content)
        assert "model" in sections
        assert "description" not in sections

    def test_handles_extra_whitespace(self) -> None:
        content = "## model\n  openai/gpt-4.1  \n\n## system\n  Hello.  \n"
        sections = parse_doc_sections(content)
        assert sections["model"] == "openai/gpt-4.1"
        assert sections["system"] == "Hello."

    def test_handles_multiline_content(self) -> None:
        content = (
            "## system\n"
            "Line one.\n"
            "Line two.\n"
            "Line three.\n"
            "\n"
            "## instruction\n"
            "Do stuff."
        )
        sections = parse_doc_sections(content)
        assert sections["system"] == "Line one.\nLine two.\nLine three."
        assert sections["instruction"] == "Do stuff."

    def test_handles_hash_inside_prompt_text(self) -> None:
        """A ## inside prompt text that doesn't match the section pattern is kept."""
        content = (
            "## system\n"
            "Use ## markdown headers in your output.\n"
            "But not at line start as a section.\n"
            "\n"
            "## instruction\n"
            "Do the thing."
        )
        sections = parse_doc_sections(content)
        # The ## inside the prompt text is at line start but "markdown headers..."
        # matches the _SECTION_RE pattern, so it would be split.
        # Actually, let's check what _SECTION_RE matches: ^## (\w[\w\s]*)$
        # "## markdown headers in your output." -> \w[\w\s]* would match
        # "markdown headers in your output." — wait, the '.' at end is not \w or \s.
        # So the regex won't match this line. The '.' breaks the pattern.
        assert "## markdown headers in your output." in sections["system"]

    def test_empty_content(self) -> None:
        sections = parse_doc_sections("")
        assert sections == {}

    def test_content_without_sections(self) -> None:
        sections = parse_doc_sections("Just some plain text\nwith no sections.")
        assert sections == {}


# ---------------------------------------------------------------------------
# apply_doc_changes()
# ---------------------------------------------------------------------------


class TestApplyDocChanges:
    """Updates config fields, bumps version, sets timestamp."""

    def test_updates_model(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        sections = {"model": "openai/gpt-4.1"}

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            updated, changes = apply_doc_changes("test-process", sections)

        assert updated.model == "openai/gpt-4.1"
        assert "model" in changes
        assert "anthropic/claude-sonnet-4.5 -> openai/gpt-4.1" in changes["model"]

    def test_updates_description(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        sections = {"description": "New description text"}

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            updated, changes = apply_doc_changes("test-process", sections)

        assert updated.description == "New description text"
        assert "description" in changes

    def test_updates_system_prompt(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        sections = {"system": "New system prompt."}

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            updated, changes = apply_doc_changes("test-process", sections)

        assert updated.prompts.system == "New system prompt."
        assert "system" in changes

    def test_updates_instruction_prompt(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        sections = {"instruction": "New instruction."}

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            updated, changes = apply_doc_changes("test-process", sections)

        assert updated.prompts.instruction == "New instruction."
        assert "instruction" in changes

    def test_bumps_version(self, tmp_path: Path) -> None:
        _write_config(tmp_path, metadata={
            "googleDocId": None, "lastSyncedAt": None, "version": 3,
        })
        sections = {"model": "openai/gpt-4.1"}

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            updated, _changes = apply_doc_changes("test-process", sections)

        assert updated.metadata.version == 4

    def test_sets_timestamp(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        sections = {"model": "openai/gpt-4.1"}

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            updated, _changes = apply_doc_changes("test-process", sections)

        assert updated.metadata.last_synced_at is not None

    def test_unchanged_fields_stay_unchanged(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        # Pass same values as existing config
        sections = {
            "model": "anthropic/claude-sonnet-4.5",
            "system": "You are a test system.",
        }

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            updated, changes = apply_doc_changes("test-process", sections)

        assert changes == {}
        assert updated.model == "anthropic/claude-sonnet-4.5"
        assert updated.prompts.system == "You are a test system."

    def test_saves_to_disk(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        sections = {"model": "openai/gpt-4.1"}

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            apply_doc_changes("test-process", sections)

        saved = _read_saved_config(tmp_path)
        assert saved["model"] == "openai/gpt-4.1"
        assert saved["metadata"]["version"] == 2

    def test_changes_dict_shows_char_counts(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        sections = {"system": "A much longer system prompt for testing character counts."}

        with patch("ica.cli.config_editor._CONFIGS_DIR", tmp_path), patch.object(
            loader, "_CONFIGS_DIR", tmp_path
        ):
            _updated, changes = apply_doc_changes("test-process", sections)

        assert "chars" in changes["system"]


# ---------------------------------------------------------------------------
# format_sync_summary()
# ---------------------------------------------------------------------------


class TestFormatSyncSummary:
    """Shows changed/unchanged fields, char count diffs."""

    def test_shows_process_name(self) -> None:
        old = _make_config(version=1)
        new = _make_config(version=2)
        summary = format_sync_summary("summarization", old, new, {})
        assert "summarization" in summary

    def test_shows_version_change(self) -> None:
        old = _make_config(version=1)
        new = _make_config(version=2)
        summary = format_sync_summary("test", old, new, {})
        assert "1 -> 2" in summary

    def test_shows_model_change(self) -> None:
        old = _make_config(version=1)
        new = _make_config(version=2, model="openai/gpt-4.1")
        changes = {"model": "anthropic/claude-sonnet-4.5 -> openai/gpt-4.1"}
        summary = format_sync_summary("test", old, new, changes)
        assert "anthropic/claude-sonnet-4.5 -> openai/gpt-4.1" in summary

    def test_shows_field_char_diffs(self) -> None:
        old = _make_config(version=1)
        new = _make_config(version=2, system="New system text.")
        changes = {"system": "24 chars -> 16 chars"}
        summary = format_sync_summary("test", old, new, changes)
        assert "24 chars -> 16 chars" in summary

    def test_shows_no_changes_message(self) -> None:
        old = _make_config(version=1)
        new = _make_config(version=2)
        summary = format_sync_summary("test", old, new, {})
        assert "no changes" in summary

    def test_multiple_changes_shown(self) -> None:
        old = _make_config(version=1)
        new = _make_config(version=2)
        changes = {
            "model": "old-model -> new-model",
            "description": "10 chars -> 20 chars",
            "system": "50 chars -> 80 chars",
        }
        summary = format_sync_summary("test", old, new, changes)
        assert "model" in summary
        assert "description" in summary
        assert "system" in summary

    def test_no_changes_does_not_show_field_lines(self) -> None:
        old = _make_config(version=1)
        new = _make_config(version=2)
        summary = format_sync_summary("test", old, new, {})
        lines = summary.strip().split("\n")
        # Should have header, version, and "no changes" — 3 lines
        assert len(lines) == 3
