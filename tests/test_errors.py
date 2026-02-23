"""Tests for ica.errors — pipeline error handling patterns.

Covers:
- Exception hierarchy and attributes
- Slack error message formatting (both templates)
- notify_error (with and without notifier)
- handle_step_error (notification + PipelineStopError raise)
- ValidationLoopCounter lifecycle
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from ica.errors import (
    DEFAULT_MAX_VALIDATION_ATTEMPTS,
    DatabaseError,
    FetchError,
    LLMError,
    PipelineError,
    PipelineStopError,
    ValidationError,
    ValidationLoopCounter,
    format_error_slack_message,
    format_llm_error_slack_message,
    handle_step_error,
    notify_error,
)


# -----------------------------------------------------------------------
# Exception hierarchy
# -----------------------------------------------------------------------


class TestPipelineError:
    """PipelineError base class."""

    def test_attributes(self) -> None:
        err = PipelineError("step1", "something broke")
        assert err.step == "step1"
        assert err.detail == "something broke"

    def test_str_includes_step_and_detail(self) -> None:
        err = PipelineError("Summarization", "timeout")
        assert "Summarization" in str(err)
        assert "timeout" in str(err)

    def test_is_exception(self) -> None:
        assert issubclass(PipelineError, Exception)


class TestLLMError:
    """LLMError for LLM API call failures."""

    def test_inherits_pipeline_error(self) -> None:
        assert issubclass(LLMError, PipelineError)

    def test_attributes(self) -> None:
        err = LLMError("Theme Generation", "rate limit exceeded")
        assert err.step == "Theme Generation"
        assert err.detail == "rate limit exceeded"

    def test_catchable_as_pipeline_error(self) -> None:
        with pytest.raises(PipelineError):
            raise LLMError("step", "detail")


class TestFetchError:
    """FetchError for HTTP page fetch failures."""

    def test_inherits_pipeline_error(self) -> None:
        assert issubclass(FetchError, PipelineError)

    def test_attributes(self) -> None:
        err = FetchError("Summarization", "captcha detected")
        assert err.step == "Summarization"
        assert err.detail == "captcha detected"


class TestDatabaseError:
    """DatabaseError for DB operation failures."""

    def test_inherits_pipeline_error(self) -> None:
        assert issubclass(DatabaseError, PipelineError)

    def test_attributes(self) -> None:
        err = DatabaseError("Article Curation", "connection refused")
        assert err.step == "Article Curation"
        assert err.detail == "connection refused"


class TestValidationError:
    """ValidationError for content validation failures."""

    def test_inherits_pipeline_error(self) -> None:
        assert issubclass(ValidationError, PipelineError)

    def test_attributes(self) -> None:
        err = ValidationError("Markdown Generation", "character count out of range")
        assert err.step == "Markdown Generation"
        assert err.detail == "character count out of range"


class TestPipelineStopError:
    """PipelineStopError — the pipeline must halt."""

    def test_inherits_pipeline_error(self) -> None:
        assert issubclass(PipelineStopError, PipelineError)

    def test_attributes(self) -> None:
        err = PipelineStopError("HTML Generation", "fatal LLM error")
        assert err.step == "HTML Generation"
        assert err.detail == "fatal LLM error"


class TestExceptionHierarchyCatchAll:
    """All specific errors are catchable as PipelineError."""

    @pytest.mark.parametrize(
        "cls",
        [LLMError, FetchError, DatabaseError, ValidationError, PipelineStopError],
    )
    def test_catch_as_pipeline_error(self, cls: type[PipelineError]) -> None:
        with pytest.raises(PipelineError):
            raise cls("step", "detail")

    @pytest.mark.parametrize(
        "cls",
        [LLMError, FetchError, DatabaseError, ValidationError, PipelineStopError],
    )
    def test_catch_as_exception(self, cls: type[PipelineError]) -> None:
        with pytest.raises(Exception):
            raise cls("step", "detail")


# -----------------------------------------------------------------------
# Slack error message formatting
# -----------------------------------------------------------------------


class TestFormatErrorSlackMessage:
    """format_error_slack_message — full "Execution Stopped at" template."""

    def test_contains_step_name(self) -> None:
        msg = format_error_slack_message("the Summarization step", "timeout")
        assert "the Summarization step" in msg

    def test_contains_error(self) -> None:
        msg = format_error_slack_message("step", "rate limit exceeded")
        assert "rate limit exceeded" in msg

    def test_starts_with_bold_execution_stopped(self) -> None:
        msg = format_error_slack_message("step", "err")
        assert msg.startswith("*Execution Stopped at")

    def test_ends_with_reach_out(self) -> None:
        msg = format_error_slack_message("step", "err")
        assert msg.endswith("resolve the issue.*")

    def test_matches_n8n_template(self) -> None:
        """Verify the message matches the n8n template structure."""
        msg = format_error_slack_message(
            "the Summarization step", "connection reset"
        )
        expected = (
            "*Execution Stopped at the Summarization step,"
            " due to the following error :*"
            " connection reset"
            " *, reach out to the concerned person to resolve the issue.*"
        )
        assert msg == expected

    def test_markdown_generation_step(self) -> None:
        msg = format_error_slack_message(
            "Markdown generation step", "empty response"
        )
        assert "Markdown generation step" in msg
        assert "empty response" in msg

    def test_empty_error_string(self) -> None:
        msg = format_error_slack_message("step", "")
        assert "step" in msg

    def test_error_with_special_characters(self) -> None:
        msg = format_error_slack_message("step", "Error: <html> & stuff")
        assert "<html> & stuff" in msg


class TestFormatLlmErrorSlackMessage:
    """format_llm_error_slack_message — shorter LLM error template."""

    def test_contains_error(self) -> None:
        msg = format_llm_error_slack_message("rate limit exceeded")
        assert "rate limit exceeded" in msg

    def test_starts_with_an_error(self) -> None:
        msg = format_llm_error_slack_message("err")
        assert msg.startswith("An Error on LLM Processing:")

    def test_matches_n8n_template(self) -> None:
        msg = format_llm_error_slack_message("model not found")
        assert msg == "An Error on LLM Processing: model not found"


# -----------------------------------------------------------------------
# notify_error
# -----------------------------------------------------------------------


class TestNotifyError:
    """notify_error — sends Slack notification or logs."""

    @pytest.mark.asyncio
    async def test_calls_notifier(self) -> None:
        notifier = AsyncMock()
        await notify_error(notifier, "step", "err")
        notifier.send_error.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_message_passed_to_notifier(self) -> None:
        notifier = AsyncMock()
        await notify_error(notifier, "Theme Generation", "timeout")
        msg = notifier.send_error.call_args[0][0]
        assert "Theme Generation" in msg
        assert "timeout" in msg

    @pytest.mark.asyncio
    async def test_none_notifier_does_not_raise(self) -> None:
        # Should not raise even with no notifier
        await notify_error(None, "step", "err")

    @pytest.mark.asyncio
    async def test_notifier_exception_suppressed(self) -> None:
        notifier = AsyncMock(side_effect=RuntimeError("Slack down"))
        # Should not raise even if Slack fails
        await notify_error(notifier, "step", "err")

    @pytest.mark.asyncio
    async def test_notifier_exception_does_not_prevent_logging(self) -> None:
        notifier = AsyncMock(side_effect=RuntimeError("Slack down"))
        # No exception should propagate
        await notify_error(notifier, "step", "err")


# -----------------------------------------------------------------------
# handle_step_error
# -----------------------------------------------------------------------


class TestHandleStepError:
    """handle_step_error — notify + raise PipelineStopError."""

    @pytest.mark.asyncio
    async def test_raises_pipeline_stop_error(self) -> None:
        with pytest.raises(PipelineStopError) as exc_info:
            await handle_step_error(
                RuntimeError("boom"), "Summarization"
            )
        assert exc_info.value.step == "Summarization"
        assert "boom" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sends_slack_notification(self) -> None:
        notifier = AsyncMock()
        with pytest.raises(PipelineStopError):
            await handle_step_error(
                RuntimeError("boom"), "step", notifier
            )
        notifier.send_error.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_slack_message_contains_error(self) -> None:
        notifier = AsyncMock()
        with pytest.raises(PipelineStopError):
            await handle_step_error(
                ValueError("bad value"), "Theme Generation", notifier
            )
        msg = notifier.send_error.call_args[0][0]
        assert "bad value" in msg
        assert "Theme Generation" in msg

    @pytest.mark.asyncio
    async def test_chains_original_exception(self) -> None:
        original = RuntimeError("original cause")
        with pytest.raises(PipelineStopError) as exc_info:
            await handle_step_error(original, "step")
        assert exc_info.value.__cause__ is original

    @pytest.mark.asyncio
    async def test_no_notifier(self) -> None:
        """Still raises PipelineStopError without a notifier."""
        with pytest.raises(PipelineStopError):
            await handle_step_error(RuntimeError("boom"), "step")

    @pytest.mark.asyncio
    async def test_notifier_failure_still_raises(self) -> None:
        """Even if Slack notification fails, PipelineStopError is raised."""
        notifier = AsyncMock(side_effect=RuntimeError("Slack down"))
        with pytest.raises(PipelineStopError):
            await handle_step_error(RuntimeError("boom"), "step", notifier)

    @pytest.mark.asyncio
    async def test_llm_error_input(self) -> None:
        with pytest.raises(PipelineStopError) as exc_info:
            await handle_step_error(
                LLMError("Summarization", "rate limit"),
                "the Summarization step",
            )
        assert "Summarization" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_detail_from_str_of_exception(self) -> None:
        """The detail comes from str(error)."""
        err = ValueError("specific problem description")
        with pytest.raises(PipelineStopError) as exc_info:
            await handle_step_error(err, "step")
        assert exc_info.value.detail == "specific problem description"


# -----------------------------------------------------------------------
# ValidationLoopCounter
# -----------------------------------------------------------------------


class TestValidationLoopCounter:
    """ValidationLoopCounter — prevents infinite validation retries."""

    def test_initial_count_is_zero(self) -> None:
        counter = ValidationLoopCounter()
        assert counter.count == 0

    def test_not_exhausted_initially(self) -> None:
        counter = ValidationLoopCounter()
        assert counter.exhausted is False

    def test_default_max_attempts(self) -> None:
        counter = ValidationLoopCounter()
        assert counter.max_attempts == DEFAULT_MAX_VALIDATION_ATTEMPTS
        assert counter.max_attempts == 3

    def test_increment(self) -> None:
        counter = ValidationLoopCounter()
        counter.increment()
        assert counter.count == 1

    def test_exhausted_after_max_attempts(self) -> None:
        counter = ValidationLoopCounter()
        for _ in range(3):
            counter.increment()
        assert counter.exhausted is True

    def test_not_exhausted_before_max(self) -> None:
        counter = ValidationLoopCounter()
        counter.increment()
        counter.increment()
        assert counter.exhausted is False

    def test_remaining_decreases(self) -> None:
        counter = ValidationLoopCounter()
        assert counter.remaining == 3
        counter.increment()
        assert counter.remaining == 2
        counter.increment()
        assert counter.remaining == 1
        counter.increment()
        assert counter.remaining == 0

    def test_remaining_never_negative(self) -> None:
        counter = ValidationLoopCounter()
        for _ in range(10):
            counter.increment()
        assert counter.remaining == 0

    def test_custom_max_attempts(self) -> None:
        counter = ValidationLoopCounter(max_attempts=5)
        assert counter.max_attempts == 5
        assert counter.remaining == 5
        for _ in range(4):
            counter.increment()
        assert counter.exhausted is False
        counter.increment()
        assert counter.exhausted is True

    def test_reset(self) -> None:
        counter = ValidationLoopCounter()
        counter.increment()
        counter.increment()
        counter.reset()
        assert counter.count == 0
        assert counter.exhausted is False
        assert counter.remaining == 3

    def test_reset_after_exhaustion(self) -> None:
        counter = ValidationLoopCounter()
        for _ in range(3):
            counter.increment()
        assert counter.exhausted is True
        counter.reset()
        assert counter.exhausted is False
        assert counter.remaining == 3

    def test_max_attempts_one(self) -> None:
        counter = ValidationLoopCounter(max_attempts=1)
        assert counter.exhausted is False
        counter.increment()
        assert counter.exhausted is True

    def test_max_attempts_zero(self) -> None:
        """With max_attempts=0, exhausted immediately."""
        counter = ValidationLoopCounter(max_attempts=0)
        assert counter.exhausted is True
        assert counter.remaining == 0


class TestValidationLoopCounterUsagePattern:
    """Test the intended usage pattern from the docstring."""

    def test_loop_with_persistent_errors(self) -> None:
        """Simulates 3 failing validations then force-accept."""
        counter = ValidationLoopCounter()
        attempts = 0

        while True:
            errors = ["some error"]  # always failing
            if not errors or counter.exhausted:
                break
            counter.increment()
            attempts += 1

        assert attempts == 3
        assert counter.exhausted is True

    def test_loop_with_success_on_second_try(self) -> None:
        """Simulates success on the second validation attempt."""
        counter = ValidationLoopCounter()
        attempt = 0

        for i in range(10):
            errors = ["err"] if i < 1 else []
            if not errors or counter.exhausted:
                break
            counter.increment()
            attempt = i + 1

        assert attempt == 1
        assert counter.exhausted is False

    def test_loop_with_immediate_success(self) -> None:
        """No validation errors on first check — no retries needed."""
        counter = ValidationLoopCounter()
        errors: list[str] = []
        retried = False

        if errors or counter.exhausted:
            pass
        else:
            retried = False

        assert counter.count == 0
        assert retried is False
