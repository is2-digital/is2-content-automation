"""Structured logging for the ica newsletter pipeline.

Provides:

1. **Context variables** — async-safe ``run_id`` and ``step`` context vars
   that propagate across ``await`` boundaries.
2. :class:`ContextFilter` — a :class:`logging.Filter` that injects context
   vars into every log record so formatters can include them.
3. :class:`JsonFormatter` — JSON-lines output for production.
4. :class:`TextFormatter` — human-readable output for development.
5. :func:`configure_logging` — one-call setup for the root logger.
6. :func:`get_logger` — returns a named logger with the context filter.
7. :class:`bind_context` — context manager to set ``run_id`` / ``step``.

Usage::

    from ica.logging import configure_logging, get_logger, bind_context

    configure_logging(level="INFO", log_format="json")
    logger = get_logger(__name__)

    with bind_context(run_id="abc123", step="summarization"):
        logger.info("Processing %d articles", len(articles))
        # JSON output includes "run_id": "abc123", "step": "summarization"
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Async-safe context variables
# ---------------------------------------------------------------------------

run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "run_id",
    default=None,
)
step_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "step",
    default=None,
)


# ---------------------------------------------------------------------------
# Context filter
# ---------------------------------------------------------------------------


class ContextFilter(logging.Filter):
    """Injects pipeline context variables into every log record.

    Adds ``run_id`` and ``step`` attributes sourced from the current
    :mod:`contextvars` values.  These are ``None`` when no context has
    been bound (e.g. during startup, outside a pipeline run).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        record.step = step_var.get()
        return True


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """Outputs each log record as a single JSON line.

    Fields: ``timestamp``, ``level``, ``logger``, ``message``, and
    optionally ``run_id``, ``step``, ``exception``.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=UTC,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        run_id = getattr(record, "run_id", None)
        if run_id is not None:
            entry["run_id"] = run_id

        step = getattr(record, "step", None)
        if step is not None:
            entry["step"] = step

        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable formatter that includes context when present.

    Base output::

        2026-02-22 14:30:00,123 INFO     [ica.pipeline] Starting pipeline

    With context bound::

        2026-02-22 14:30:00,123 INFO     [ica.pipeline] [run=abc123 step=summarization] Starting pipeline
    """  # noqa: E501

    _BASE_FMT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self._BASE_FMT)

    def format(self, record: logging.LogRecord) -> str:
        run_id = getattr(record, "run_id", None)
        step = getattr(record, "step", None)

        if run_id is not None or step is not None:
            parts: list[str] = []
            if run_id is not None:
                parts.append(f"run={run_id}")
            if step is not None:
                parts.append(f"step={step}")
            ctx_tag = f"[{' '.join(parts)}] "

            # Temporarily prepend context tag to the message.
            original_msg = record.msg
            original_args = record.args
            record.msg = f"{ctx_tag}{record.msg}"
            result = super().format(record)
            record.msg = original_msg
            record.args = original_args
            return result

        return super().format(record)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def configure_logging(
    *,
    level: str = "INFO",
    log_format: str = "text",
) -> None:
    """Configure the root logger for structured output.

    Should be called once at application startup (e.g. in the FastAPI
    lifespan or CLI entrypoint).

    Args:
        level: Log level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``,
            ``CRITICAL``).  Case-insensitive.
        log_format: ``"text"`` for human-readable, ``"json"`` for JSON lines.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate output on re-configure.
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(ContextFilter())

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------


def get_logger(name: str) -> logging.Logger:
    """Return a named logger with the :class:`ContextFilter` attached.

    This is a thin convenience wrapper around :func:`logging.getLogger`.
    The context filter is added directly to the logger so that context
    vars appear even when :func:`configure_logging` has not been called
    (e.g. in unit tests).

    Idempotent — calling multiple times with the same *name* returns the
    same logger and does not duplicate the filter.
    """
    lgr = logging.getLogger(name)
    if not any(isinstance(f, ContextFilter) for f in lgr.filters):
        lgr.addFilter(ContextFilter())
    return lgr


# ---------------------------------------------------------------------------
# Context binding
# ---------------------------------------------------------------------------


class bind_context:  # noqa: N801
    """Context manager that sets logging context variables.

    On entry, sets the specified context vars.  On exit, restores the
    previous values (supports nesting).

    Usage::

        with bind_context(run_id="abc123"):
            logger.info("outer")  # run_id=abc123
            with bind_context(step="summarization"):
                logger.info("inner")  # run_id=abc123, step=summarization
            logger.info("back")  # run_id=abc123, step=None

    Can also be used as an async context manager::

        async with bind_context(run_id="abc123", step="curation"):
            await some_coroutine()
    """

    def __init__(
        self,
        *,
        run_id: str | None = None,
        step: str | None = None,
    ) -> None:
        self._run_id = run_id
        self._step = step
        self._tokens: list[contextvars.Token[str | None]] = []

    def __enter__(self) -> bind_context:
        if self._run_id is not None:
            self._tokens.append(run_id_var.set(self._run_id))
        if self._step is not None:
            self._tokens.append(step_var.set(self._step))
        return self

    def __exit__(self, *exc: object) -> None:
        for token in reversed(self._tokens):
            token.var.reset(token)
        self._tokens.clear()

    async def __aenter__(self) -> bind_context:
        return self.__enter__()

    async def __aexit__(self, *exc: object) -> None:
        self.__exit__()
