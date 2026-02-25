"""Tests for ica.logging — structured logging module."""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from ica.logging import (
    ContextFilter,
    JsonFormatter,
    TextFormatter,
    bind_context,
    configure_logging,
    get_logger,
    run_id_var,
    step_var,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    name: str = "test",
    level: int = logging.INFO,
    msg: str = "hello",
    args: tuple[object, ...] | None = None,
) -> logging.LogRecord:
    """Create a minimal LogRecord for formatter tests."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )
    return record


# ---------------------------------------------------------------------------
# ContextFilter
# ---------------------------------------------------------------------------


class TestContextFilter:
    """Tests for ContextFilter."""

    def test_always_returns_true(self) -> None:
        f = ContextFilter()
        record = _make_record()
        assert f.filter(record) is True

    def test_injects_none_by_default(self) -> None:
        f = ContextFilter()
        record = _make_record()
        f.filter(record)
        assert record.run_id is None  # type: ignore[attr-defined]
        assert record.step is None  # type: ignore[attr-defined]

    def test_injects_run_id_from_context_var(self) -> None:
        f = ContextFilter()
        record = _make_record()
        token = run_id_var.set("test-run-123")
        try:
            f.filter(record)
            assert record.run_id == "test-run-123"  # type: ignore[attr-defined]
        finally:
            run_id_var.reset(token)

    def test_injects_step_from_context_var(self) -> None:
        f = ContextFilter()
        record = _make_record()
        token = step_var.set("summarization")
        try:
            f.filter(record)
            assert record.step == "summarization"  # type: ignore[attr-defined]
        finally:
            step_var.reset(token)

    def test_injects_both_context_vars(self) -> None:
        f = ContextFilter()
        record = _make_record()
        t1 = run_id_var.set("run-99")
        t2 = step_var.set("curation")
        try:
            f.filter(record)
            assert record.run_id == "run-99"  # type: ignore[attr-defined]
            assert record.step == "curation"  # type: ignore[attr-defined]
        finally:
            step_var.reset(t2)
            run_id_var.reset(t1)


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    """Tests for JsonFormatter."""

    def _format(self, record: logging.LogRecord) -> dict:
        fmt = JsonFormatter()
        ContextFilter().filter(record)  # Inject context attrs
        raw = fmt.format(record)
        return json.loads(raw)

    def test_output_is_valid_json(self) -> None:
        record = _make_record(msg="test message")
        result = self._format(record)
        assert isinstance(result, dict)

    def test_basic_fields(self) -> None:
        record = _make_record(name="ica.pipeline", msg="hello world")
        result = self._format(record)
        assert result["level"] == "INFO"
        assert result["logger"] == "ica.pipeline"
        assert result["message"] == "hello world"
        assert "timestamp" in result

    def test_timestamp_is_iso_format(self) -> None:
        record = _make_record()
        result = self._format(record)
        # Should end with +00:00 (UTC)
        assert result["timestamp"].endswith("+00:00")

    def test_no_context_omits_run_id_and_step(self) -> None:
        record = _make_record()
        result = self._format(record)
        assert "run_id" not in result
        assert "step" not in result

    def test_includes_run_id_when_set(self) -> None:
        record = _make_record()
        t = run_id_var.set("json-run-1")
        try:
            result = self._format(record)
            assert result["run_id"] == "json-run-1"
        finally:
            run_id_var.reset(t)

    def test_includes_step_when_set(self) -> None:
        record = _make_record()
        t = step_var.set("theme_generation")
        try:
            result = self._format(record)
            assert result["step"] == "theme_generation"
        finally:
            step_var.reset(t)

    def test_includes_both_context_vars(self) -> None:
        record = _make_record()
        t1 = run_id_var.set("r1")
        t2 = step_var.set("s1")
        try:
            result = self._format(record)
            assert result["run_id"] == "r1"
            assert result["step"] == "s1"
        finally:
            step_var.reset(t2)
            run_id_var.reset(t1)

    def test_message_with_args(self) -> None:
        record = _make_record(msg="count=%d", args=(42,))
        result = self._format(record)
        assert result["message"] == "count=42"

    def test_exception_info_included(self) -> None:
        record = _make_record(msg="oops")
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            record.exc_info = sys.exc_info()
        result = self._format(record)
        assert "exception" in result
        assert "ValueError: test error" in result["exception"]

    def test_exception_omitted_when_none(self) -> None:
        record = _make_record()
        result = self._format(record)
        assert "exception" not in result

    def test_level_names(self) -> None:
        for level, name in [
            (logging.DEBUG, "DEBUG"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]:
            record = _make_record(level=level)
            result = self._format(record)
            assert result["level"] == name

    def test_single_line_output(self) -> None:
        """JSON output should be a single line (no embedded newlines)."""
        record = _make_record(msg="line1\nline2")
        fmt = JsonFormatter()
        ContextFilter().filter(record)
        raw = fmt.format(record)
        # json.dumps escapes newlines, so output should be one line
        assert "\n" not in raw


# ---------------------------------------------------------------------------
# TextFormatter
# ---------------------------------------------------------------------------


class TestTextFormatter:
    """Tests for TextFormatter."""

    def _format(self, record: logging.LogRecord) -> str:
        fmt = TextFormatter()
        ContextFilter().filter(record)
        return fmt.format(record)

    def test_basic_format(self) -> None:
        record = _make_record(name="ica.app", msg="started")
        result = self._format(record)
        assert "INFO" in result
        assert "[ica.app]" in result
        assert "started" in result

    def test_no_context_no_brackets(self) -> None:
        record = _make_record(msg="plain")
        result = self._format(record)
        assert "[run=" not in result
        assert "[step=" not in result

    def test_run_id_context_shown(self) -> None:
        record = _make_record(msg="working")
        t = run_id_var.set("txt-run-1")
        try:
            result = self._format(record)
            assert "[run=txt-run-1]" in result
            assert "working" in result
        finally:
            run_id_var.reset(t)

    def test_step_context_shown(self) -> None:
        record = _make_record(msg="processing")
        t = step_var.set("html_gen")
        try:
            result = self._format(record)
            assert "[step=html_gen]" in result
        finally:
            step_var.reset(t)

    def test_both_context_vars_shown(self) -> None:
        record = _make_record(msg="both")
        t1 = run_id_var.set("r2")
        t2 = step_var.set("s2")
        try:
            result = self._format(record)
            assert "[run=r2 step=s2]" in result
        finally:
            step_var.reset(t2)
            run_id_var.reset(t1)

    def test_message_args_interpolated(self) -> None:
        record = _make_record(msg="articles=%d", args=(5,))
        result = self._format(record)
        assert "articles=5" in result

    def test_does_not_modify_original_record(self) -> None:
        """TextFormatter should not permanently alter record.msg."""
        record = _make_record(msg="original")
        t = run_id_var.set("tmp")
        try:
            self._format(record)
            assert record.msg == "original"
        finally:
            run_id_var.reset(t)


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    """Tests for configure_logging."""

    def setup_method(self) -> None:
        """Stash root logger state before each test."""
        root = logging.getLogger()
        self._original_handlers = root.handlers[:]
        self._original_level = root.level

    def teardown_method(self) -> None:
        """Restore root logger state after each test."""
        root = logging.getLogger()
        root.handlers = self._original_handlers
        root.level = self._original_level

    def test_sets_root_level(self) -> None:
        configure_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_sets_root_level_case_insensitive(self) -> None:
        configure_logging(level="warning")
        assert logging.getLogger().level == logging.WARNING

    def test_default_level_is_info(self) -> None:
        configure_logging()
        assert logging.getLogger().level == logging.INFO

    def test_text_format_uses_text_formatter(self) -> None:
        configure_logging(log_format="text")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, TextFormatter)

    def test_json_format_uses_json_formatter(self) -> None:
        configure_logging(log_format="json")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_default_format_is_text(self) -> None:
        configure_logging()
        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, TextFormatter)

    def test_clears_previous_handlers(self) -> None:
        """Re-calling configure_logging should not duplicate handlers."""
        configure_logging()
        configure_logging()
        root = logging.getLogger()
        assert len(root.handlers) == 1

    def test_handler_has_context_filter(self) -> None:
        configure_logging()
        root = logging.getLogger()
        handler = root.handlers[0]
        assert any(isinstance(f, ContextFilter) for f in handler.filters)

    def test_handler_writes_to_stderr(self) -> None:
        import sys

        configure_logging()
        root = logging.getLogger()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr

    def test_invalid_level_defaults_to_info(self) -> None:
        configure_logging(level="NONEXISTENT")
        assert logging.getLogger().level == logging.INFO


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    """Tests for get_logger."""

    def test_returns_logger_with_given_name(self) -> None:
        lgr = get_logger("ica.test.module")
        assert lgr.name == "ica.test.module"

    def test_has_context_filter(self) -> None:
        lgr = get_logger("ica.test.filter")
        assert any(isinstance(f, ContextFilter) for f in lgr.filters)

    def test_idempotent(self) -> None:
        """Multiple calls with same name should not duplicate filters."""
        lgr1 = get_logger("ica.test.idem")
        lgr2 = get_logger("ica.test.idem")
        assert lgr1 is lgr2
        context_filters = [f for f in lgr1.filters if isinstance(f, ContextFilter)]
        assert len(context_filters) == 1

    def test_different_names_return_different_loggers(self) -> None:
        lgr1 = get_logger("ica.a")
        lgr2 = get_logger("ica.b")
        assert lgr1 is not lgr2


# ---------------------------------------------------------------------------
# bind_context — sync
# ---------------------------------------------------------------------------


class TestBindContextSync:
    """Tests for bind_context as a sync context manager."""

    def test_sets_run_id(self) -> None:
        assert run_id_var.get() is None
        with bind_context(run_id="sync-run"):
            assert run_id_var.get() == "sync-run"
        assert run_id_var.get() is None

    def test_sets_step(self) -> None:
        assert step_var.get() is None
        with bind_context(step="curation"):
            assert step_var.get() == "curation"
        assert step_var.get() is None

    def test_sets_both(self) -> None:
        with bind_context(run_id="r1", step="s1"):
            assert run_id_var.get() == "r1"
            assert step_var.get() == "s1"
        assert run_id_var.get() is None
        assert step_var.get() is None

    def test_nesting_preserves_outer(self) -> None:
        with bind_context(run_id="outer"):
            with bind_context(step="inner-step"):
                assert run_id_var.get() == "outer"
                assert step_var.get() == "inner-step"
            assert run_id_var.get() == "outer"
            assert step_var.get() is None
        assert run_id_var.get() is None

    def test_nesting_overrides_run_id(self) -> None:
        with bind_context(run_id="outer"):
            assert run_id_var.get() == "outer"
            with bind_context(run_id="inner"):
                assert run_id_var.get() == "inner"
            assert run_id_var.get() == "outer"

    def test_restores_on_exception(self) -> None:
        with pytest.raises(RuntimeError):
            with bind_context(run_id="err-run", step="err-step"):
                raise RuntimeError("boom")
        assert run_id_var.get() is None
        assert step_var.get() is None

    def test_no_args_is_noop(self) -> None:
        """bind_context() with no args doesn't change anything."""
        original_run = run_id_var.get()
        original_step = step_var.get()
        with bind_context():
            assert run_id_var.get() is original_run
            assert step_var.get() is original_step

    def test_returns_self(self) -> None:
        with bind_context(run_id="x") as ctx:
            assert isinstance(ctx, bind_context)


# ---------------------------------------------------------------------------
# bind_context — async
# ---------------------------------------------------------------------------


class TestBindContextAsync:
    """Tests for bind_context as an async context manager."""

    @pytest.mark.asyncio
    async def test_sets_run_id(self) -> None:
        assert run_id_var.get() is None
        async with bind_context(run_id="async-run"):
            assert run_id_var.get() == "async-run"
        assert run_id_var.get() is None

    @pytest.mark.asyncio
    async def test_sets_step(self) -> None:
        async with bind_context(step="async-step"):
            assert step_var.get() == "async-step"
        assert step_var.get() is None

    @pytest.mark.asyncio
    async def test_sets_both(self) -> None:
        async with bind_context(run_id="ar", step="as"):
            assert run_id_var.get() == "ar"
            assert step_var.get() == "as"
        assert run_id_var.get() is None
        assert step_var.get() is None

    @pytest.mark.asyncio
    async def test_nesting(self) -> None:
        async with bind_context(run_id="outer"):
            async with bind_context(step="inner"):
                assert run_id_var.get() == "outer"
                assert step_var.get() == "inner"
            assert step_var.get() is None

    @pytest.mark.asyncio
    async def test_restores_on_exception(self) -> None:
        with pytest.raises(ValueError):
            async with bind_context(run_id="exc-run"):
                raise ValueError("async boom")
        assert run_id_var.get() is None


# ---------------------------------------------------------------------------
# Integration: logger + context + formatter
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end tests: logger output includes bound context."""

    def setup_method(self) -> None:
        root = logging.getLogger()
        self._original_handlers = root.handlers[:]
        self._original_level = root.level

    def teardown_method(self) -> None:
        root = logging.getLogger()
        root.handlers = self._original_handlers
        root.level = self._original_level

    def test_json_output_with_context(self) -> None:
        """A logger emitting JSON should include bound context."""
        configure_logging(log_format="json")
        lgr = get_logger("ica.integration.json")
        import io

        buf = io.StringIO()
        # Replace stderr handler stream for capture
        root = logging.getLogger()
        root.handlers[0].stream = buf

        with bind_context(run_id="int-run", step="int-step"):
            lgr.info("test message")

        output = buf.getvalue().strip()
        data = json.loads(output)
        assert data["run_id"] == "int-run"
        assert data["step"] == "int-step"
        assert data["message"] == "test message"
        assert data["logger"] == "ica.integration.json"

    def test_text_output_with_context(self) -> None:
        """A logger emitting text should include bound context."""
        configure_logging(log_format="text")
        lgr = get_logger("ica.integration.text")
        import io

        buf = io.StringIO()
        root = logging.getLogger()
        root.handlers[0].stream = buf

        with bind_context(run_id="tr1", step="ts1"):
            lgr.info("text test")

        output = buf.getvalue()
        assert "[run=tr1 step=ts1]" in output
        assert "text test" in output

    def test_text_output_without_context(self) -> None:
        """Without context, text output should not have context brackets."""
        configure_logging(log_format="text")
        lgr = get_logger("ica.integration.plain")
        import io

        buf = io.StringIO()
        root = logging.getLogger()
        root.handlers[0].stream = buf

        lgr.info("no context")

        output = buf.getvalue()
        assert "no context" in output
        assert "[run=" not in output

    def test_json_output_without_context(self) -> None:
        """Without context, JSON output should omit run_id/step keys."""
        configure_logging(log_format="json")
        lgr = get_logger("ica.integration.noctx")
        import io

        buf = io.StringIO()
        root = logging.getLogger()
        root.handlers[0].stream = buf

        lgr.info("bare")

        data = json.loads(buf.getvalue().strip())
        assert "run_id" not in data
        assert "step" not in data

    def test_context_does_not_leak_across_messages(self) -> None:
        """After exiting bind_context, subsequent logs should lack context."""
        configure_logging(log_format="json")
        lgr = get_logger("ica.integration.leak")
        import io

        buf = io.StringIO()
        root = logging.getLogger()
        root.handlers[0].stream = buf

        with bind_context(run_id="leak-run"):
            lgr.info("inside")
        lgr.info("outside")

        lines = [json.loads(line) for line in buf.getvalue().strip().split("\n")]
        assert lines[0]["run_id"] == "leak-run"
        assert "run_id" not in lines[1]
