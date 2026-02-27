"""Error handling patterns for the ica newsletter pipeline.

Ports the n8n error-handling architecture:

* Each LLM-dependent node uses ``onError: "continueErrorOutput"`` to route
  errors to a dedicated **Error Output** Slack node, followed by a
  **Stop and Error** node that halts execution.
* The Slack error message template is:
  ``*Execution Stopped at [step], due to the following error :* <error>
  *, reach out to the concerned person to resolve the issue.*``

This module provides:

1. **Exception hierarchy** — typed exceptions for LLM, HTTP fetch, database,
   and validation errors, all inheriting from :class:`PipelineError`.
2. :func:`format_error_slack_message` — builds the Slack mrkdwn error message.
3. :func:`notify_error` — sends the error notification to Slack.
4. :func:`handle_step_error` — wraps a pipeline step coroutine with
   error capture, Slack notification, and ``PipelineStopError`` re-raise.
5. :class:`ValidationLoopCounter` — tracks validation attempts with a
   configurable max (default 3) to prevent infinite retry loops.

See PRD Section 7.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ica.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class PipelineError(Exception):
    """Base exception for all pipeline errors.

    Attributes:
        step: The pipeline step name where the error occurred.
        detail: A human-readable description of what went wrong.
    """

    def __init__(self, step: str, detail: str) -> None:
        self.step = step
        self.detail = detail
        super().__init__(f"[{step}] {detail}")


class LLMError(PipelineError):
    """An LLM API call failed.

    Raised when litellm.acompletion (or similar) throws or returns an
    empty/invalid response.  Matches n8n's ``onError: continueErrorOutput``
    on Generate/Re-Generate LLM nodes.
    """


class FetchError(PipelineError):
    """An HTTP page fetch failed.

    Raised when the article content fetch returns an error, captcha page,
    or an un-fetchable URL (e.g. YouTube).  Matches n8n's fetch failure
    branch (PRD Section 7.2).
    """


class DatabaseError(PipelineError):
    """A database operation failed.

    Raised when an INSERT/UPDATE/SELECT fails despite the upsert pattern.
    Matches n8n's ``onError: continueErrorOutput`` on Postgres nodes.
    """


class ValidationError(PipelineError):
    """A content validation check failed.

    Raised when markdown validation (character count, structural, or voice)
    fails and the retry budget is exhausted.  See PRD Section 7.4.
    """


class PipelineStopError(PipelineError):
    """The pipeline must stop execution.

    Equivalent to n8n's ``stopAndError`` node.  Raised after the Slack
    error notification has been sent.  The pipeline orchestrator should
    catch this at the top level to mark the run as ``FAILED``.
    """


# ---------------------------------------------------------------------------
# Slack error notification
# ---------------------------------------------------------------------------

# The two templates match the n8n workflows:
#
# Summarization / Markdown / HTML subworkflows:
#   "*Execution Stopped at <step>, due to the following error :*
#    <error> *, reach out to the concerned person to resolve the issue.*"
#
# Theme / Email subworkflows (shorter form):
#   "An Error on LLM Processing: <error>"

_ERROR_MESSAGE_TEMPLATE = (
    "*Execution Stopped at {step}, due to the following error :*"
    " {error}"
    " *, reach out to the concerned person to resolve the issue.*"
)

_LLM_ERROR_SHORT_TEMPLATE = "An Error on LLM Processing: {error}"


def format_error_slack_message(step: str, error: str) -> str:
    """Build the Slack mrkdwn error notification message.

    Uses the longer "Execution Stopped at ..." template that appears in
    the summarization, markdown-generation, and HTML-generation
    subworkflows.

    Args:
        step: Human-readable pipeline step name (e.g. "the Summarization step").
        error: The error description string.

    Returns:
        A Slack mrkdwn-formatted error message.
    """
    return _ERROR_MESSAGE_TEMPLATE.format(step=step, error=error)


def format_llm_error_slack_message(error: str) -> str:
    """Build the shorter LLM error notification message.

    Used by the theme-generation and email-subject subworkflows which
    use the simpler "An Error on LLM Processing: ..." format.

    Args:
        error: The error description string.

    Returns:
        A Slack mrkdwn-formatted error message.
    """
    return _LLM_ERROR_SHORT_TEMPLATE.format(error=error)


# ---------------------------------------------------------------------------
# Error notifier protocol + notify helper
# ---------------------------------------------------------------------------


class ErrorNotifier(Protocol):
    """Protocol for sending error notifications.

    Implementations may post to Slack, send email, or use any other channel.
    """

    async def send_error(self, message: str) -> None:
        """Send an error notification message."""
        ...


# Backward-compatible alias
SlackErrorNotifier = ErrorNotifier


class CompositeErrorNotifier:
    """Fans out error notifications to multiple notifiers.

    If one notifier fails, the others still receive the message.
    """

    def __init__(self, notifiers: list[ErrorNotifier]) -> None:
        self._notifiers = notifiers

    async def send_error(self, message: str) -> None:
        """Send *message* to all registered notifiers."""
        for notifier in self._notifiers:
            try:
                await notifier.send_error(message)
            except Exception:
                logger.exception("Error notifier %s failed", type(notifier).__name__)


async def notify_error(
    notifier: ErrorNotifier | None,
    step: str,
    error: str,
) -> None:
    """Send a pipeline error notification.

    If *notifier* is ``None`` (e.g. in tests or when notifications are not
    configured), the notification is logged but not sent.

    Args:
        notifier: Error notifier implementation, or ``None``.
        step: Human-readable pipeline step name.
        error: The error description string.
    """
    message = format_error_slack_message(step, error)
    logger.error("Pipeline error: %s", message)

    if notifier is not None:
        try:
            await notifier.send_error(message)
        except Exception:
            logger.exception("Failed to send error notification")


# ---------------------------------------------------------------------------
# Step-level error handler
# ---------------------------------------------------------------------------


async def handle_step_error(
    error: Exception,
    step: str,
    notifier: ErrorNotifier | None = None,
) -> None:
    """Handle an error from a pipeline step.

    1. Logs the error.
    2. Sends a Slack notification (if *notifier* is available).
    3. Raises :class:`PipelineStopError` to halt execution.

    This matches the n8n pattern of:
    ``[LLM node error] → Error Output (Slack) → Stop and Error``

    Args:
        error: The caught exception.
        step: Human-readable pipeline step name.
        notifier: Slack notifier implementation, or ``None``.

    Raises:
        PipelineStopError: Always raised after notification.
    """
    detail = str(error)

    await notify_error(notifier, step, detail)

    raise PipelineStopError(step, detail) from error


# ---------------------------------------------------------------------------
# Validation loop breaker (PRD Section 7.4)
# ---------------------------------------------------------------------------

DEFAULT_MAX_VALIDATION_ATTEMPTS = 3


@dataclass
class ValidationLoopCounter:
    """Tracks validation attempts to prevent infinite retry loops.

    The markdown validation step uses a 3-layer approach (character count,
    structural LLM, voice LLM).  If all three layers keep finding errors,
    the pipeline should force-accept the output after ``max_attempts``
    retries rather than looping forever.

    This mirrors n8n's static data counter tracked per execution.

    Usage::

        counter = ValidationLoopCounter()
        while True:
            errors = validate(content)
            if not errors or counter.exhausted:
                break
            counter.increment()
            content = regenerate(content, errors)
    """

    max_attempts: int = DEFAULT_MAX_VALIDATION_ATTEMPTS
    _count: int = field(default=0, init=False, repr=False)

    @property
    def count(self) -> int:
        """Current attempt number (0-based)."""
        return self._count

    @property
    def exhausted(self) -> bool:
        """``True`` when the maximum number of attempts has been reached."""
        return self._count >= self.max_attempts

    @property
    def remaining(self) -> int:
        """Number of attempts remaining."""
        return max(0, self.max_attempts - self._count)

    def increment(self) -> None:
        """Record one validation attempt."""
        self._count += 1

    def reset(self) -> None:
        """Reset the counter (e.g. after a fresh user edit)."""
        self._count = 0
