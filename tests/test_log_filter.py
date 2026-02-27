"""Tests for ica.cli.log_filter — log filtering and formatting.

Covers:
- parse_line: plain JSON, Docker prefix, Docker timestamp prefix, non-JSON, empty
- matches_filters: no filters, run_id, step, level minimum, since/until, combined
- format_entry: basic format, context vars, exception display
"""

from __future__ import annotations

import io
import json

from ica.cli.log_filter import (
    filter_stream,
    format_entry,
    matches_filters,
    parse_line,
)

# -----------------------------------------------------------------------
# parse_line
# -----------------------------------------------------------------------


class TestParseLine:
    """parse_line — parse JSON log lines with optional Docker prefix."""

    def test_plain_json(self) -> None:
        line = '{"level": "INFO", "message": "hello"}'
        result = parse_line(line)
        assert result is not None
        assert result["level"] == "INFO"
        assert result["message"] == "hello"

    def test_docker_prefix(self) -> None:
        line = 'ica-app-1  | {"level": "ERROR", "message": "boom"}'
        result = parse_line(line)
        assert result is not None
        assert result["level"] == "ERROR"

    def test_docker_timestamp_prefix(self) -> None:
        line = 'ica-app-1  | 2026-02-27T10:00:00.000Z {"level": "INFO", "message": "hi"}'
        result = parse_line(line)
        assert result is not None
        assert result["message"] == "hi"

    def test_non_json_returns_none(self) -> None:
        assert parse_line("this is not JSON") is None

    def test_empty_line_returns_none(self) -> None:
        assert parse_line("") is None
        assert parse_line("  \n") is None

    def test_json_with_whitespace(self) -> None:
        line = '  {"level": "DEBUG"}  '
        result = parse_line(line)
        assert result is not None
        assert result["level"] == "DEBUG"


# -----------------------------------------------------------------------
# matches_filters
# -----------------------------------------------------------------------


class TestMatchesFilters:
    """matches_filters — check log entry against filter criteria."""

    def test_no_filters_matches_all(self) -> None:
        entry = {"level": "INFO", "message": "hello"}
        assert matches_filters(entry) is True

    def test_run_id_match(self) -> None:
        entry = {"run_id": "abc123", "level": "INFO"}
        assert matches_filters(entry, run_id="abc123") is True

    def test_run_id_mismatch(self) -> None:
        entry = {"run_id": "abc123", "level": "INFO"}
        assert matches_filters(entry, run_id="xyz789") is False

    def test_run_id_missing_from_entry(self) -> None:
        entry = {"level": "INFO"}
        assert matches_filters(entry, run_id="abc123") is False

    def test_step_match(self) -> None:
        entry = {"step": "summarization", "level": "INFO"}
        assert matches_filters(entry, step="summarization") is True

    def test_step_mismatch(self) -> None:
        entry = {"step": "summarization", "level": "INFO"}
        assert matches_filters(entry, step="html_generation") is False

    def test_level_minimum_error(self) -> None:
        assert matches_filters({"level": "ERROR"}, level="ERROR") is True
        assert matches_filters({"level": "CRITICAL"}, level="ERROR") is True
        assert matches_filters({"level": "WARNING"}, level="ERROR") is False
        assert matches_filters({"level": "INFO"}, level="ERROR") is False

    def test_level_minimum_warning(self) -> None:
        assert matches_filters({"level": "WARNING"}, level="WARNING") is True
        assert matches_filters({"level": "ERROR"}, level="WARNING") is True
        assert matches_filters({"level": "INFO"}, level="WARNING") is False

    def test_level_case_insensitive(self) -> None:
        assert matches_filters({"level": "error"}, level="ERROR") is True
        assert matches_filters({"level": "ERROR"}, level="error") is True

    def test_since_filter(self) -> None:
        entry = {"level": "INFO", "timestamp": "2026-02-27T12:00:00+00:00"}
        assert matches_filters(entry, since="2026-02-27T11:00:00+00:00") is True
        assert matches_filters(entry, since="2026-02-27T13:00:00+00:00") is False

    def test_until_filter(self) -> None:
        entry = {"level": "INFO", "timestamp": "2026-02-27T12:00:00+00:00"}
        assert matches_filters(entry, until="2026-02-27T13:00:00+00:00") is True
        assert matches_filters(entry, until="2026-02-27T11:00:00+00:00") is False

    def test_since_and_until_combined(self) -> None:
        entry = {"level": "INFO", "timestamp": "2026-02-27T12:00:00+00:00"}
        assert matches_filters(
            entry,
            since="2026-02-27T11:00:00+00:00",
            until="2026-02-27T13:00:00+00:00",
        ) is True
        assert matches_filters(
            entry,
            since="2026-02-27T13:00:00+00:00",
            until="2026-02-27T14:00:00+00:00",
        ) is False

    def test_combined_filters(self) -> None:
        entry = {
            "level": "ERROR",
            "run_id": "abc123",
            "step": "summarization",
            "timestamp": "2026-02-27T12:00:00+00:00",
        }
        assert matches_filters(
            entry,
            run_id="abc123",
            step="summarization",
            level="ERROR",
        ) is True
        # Wrong run_id makes it fail
        assert matches_filters(
            entry,
            run_id="wrong",
            step="summarization",
            level="ERROR",
        ) is False

    def test_no_timestamp_with_since_passes(self) -> None:
        """Entries without timestamp pass since/until filters."""
        entry = {"level": "INFO"}
        assert matches_filters(entry, since="2026-02-27T00:00:00+00:00") is True

    def test_z_suffix_timestamp(self) -> None:
        entry = {"level": "INFO", "timestamp": "2026-02-27T12:00:00Z"}
        assert matches_filters(entry, since="2026-02-27T11:00:00Z") is True


# -----------------------------------------------------------------------
# format_entry
# -----------------------------------------------------------------------


class TestFormatEntry:
    """format_entry — human-readable log line formatting."""

    def test_basic_format(self) -> None:
        entry = {"timestamp": "2026-02-27T10:00:00", "level": "INFO", "message": "hello"}
        result = format_entry(entry)
        assert "2026-02-27T10:00:00" in result
        assert "INFO" in result
        assert "hello" in result

    def test_context_vars(self) -> None:
        entry = {
            "timestamp": "t",
            "level": "ERROR",
            "message": "boom",
            "run_id": "abc123",
            "step": "summarization",
        }
        result = format_entry(entry)
        assert "[run=abc123 step=summarization]" in result

    def test_exception_display(self) -> None:
        entry = {
            "timestamp": "t",
            "level": "ERROR",
            "message": "failed",
            "exception": "Traceback...",
        }
        result = format_entry(entry)
        assert "EXC: Traceback..." in result

    def test_exc_info_field(self) -> None:
        entry = {
            "timestamp": "t",
            "level": "ERROR",
            "message": "failed",
            "exc_info": "ValueError: bad",
        }
        result = format_entry(entry)
        assert "EXC: ValueError: bad" in result

    def test_missing_fields_use_defaults(self) -> None:
        result = format_entry({})
        assert "-" in result  # default timestamp
        assert "INFO" in result  # default level

    def test_no_context_vars(self) -> None:
        entry = {"timestamp": "t", "level": "INFO", "message": "simple"}
        result = format_entry(entry)
        assert "[" not in result


# -----------------------------------------------------------------------
# filter_stream
# -----------------------------------------------------------------------


class TestFilterStream:
    """filter_stream — end-to-end stream filtering."""

    def test_filters_and_counts(self) -> None:
        lines = [
            json.dumps({"level": "INFO", "message": "a"}) + "\n",
            json.dumps({"level": "ERROR", "message": "b"}) + "\n",
            json.dumps({"level": "WARNING", "message": "c"}) + "\n",
        ]
        inp = io.StringIO("".join(lines))
        out = io.StringIO()
        count = filter_stream(inp, out, level="ERROR")
        assert count == 1
        assert "b" in out.getvalue()

    def test_raw_output(self) -> None:
        lines = [json.dumps({"level": "ERROR", "message": "boom"}) + "\n"]
        inp = io.StringIO("".join(lines))
        out = io.StringIO()
        filter_stream(inp, out, level="ERROR", raw=True)
        result = json.loads(out.getvalue().strip())
        assert result["message"] == "boom"

    def test_skips_non_json(self) -> None:
        inp = io.StringIO("not json\n{\"level\": \"INFO\", \"message\": \"ok\"}\n")
        out = io.StringIO()
        count = filter_stream(inp, out)
        assert count == 1

    def test_empty_input(self) -> None:
        inp = io.StringIO("")
        out = io.StringIO()
        count = filter_stream(inp, out)
        assert count == 0
        assert out.getvalue() == ""
