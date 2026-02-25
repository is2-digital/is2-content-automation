"""Tests for ica.services.llm — unified LLM service wrapper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.config.llm_config import LLMPurpose
from ica.errors import LLMError
from ica.services.llm import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_MAX_DELAY,
    LLMResponse,
    completion,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(content: str | None = "Hello world", usage: dict | None = None) -> SimpleNamespace:
    """Build a mock litellm response object."""
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    usage_ns = None
    if usage is not None:
        usage_ns = SimpleNamespace(**usage)
    return SimpleNamespace(choices=[choice], usage=usage_ns)


SYSTEM = "You are a helpful assistant."
USER = "Say hello."


# Sentinel exception classes — each maps to exactly one retryable error type.
class _RateLimitSentinel(Exception):
    pass


class _ServiceUnavailableSentinel(Exception):
    pass


class _TimeoutSentinel(Exception):
    pass


class _InternalServerSentinel(Exception):
    pass


class _APIConnectionSentinel(Exception):
    pass


class _NonRetryableError(Exception):
    """An error that should NOT be retried."""


def _set_retryable_types(mock_litellm: MagicMock) -> None:
    """Configure mock litellm with unique sentinel exception classes."""
    mock_litellm.RateLimitError = _RateLimitSentinel
    mock_litellm.ServiceUnavailableError = _ServiceUnavailableSentinel
    mock_litellm.Timeout = _TimeoutSentinel
    mock_litellm.InternalServerError = _InternalServerSentinel
    mock_litellm.APIConnectionError = _APIConnectionSentinel


def _patch_litellm():
    """Context manager that patches litellm module."""
    return patch("ica.services.llm.litellm")


# ---------------------------------------------------------------------------
# LLMResponse dataclass
# ---------------------------------------------------------------------------


class TestLLMResponse:
    """Tests for the LLMResponse frozen dataclass."""

    def test_basic_fields(self) -> None:
        r = LLMResponse(text="hi", model="m1")
        assert r.text == "hi"
        assert r.model == "m1"
        assert r.purpose is None
        assert r.usage is None

    def test_all_fields(self) -> None:
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        r = LLMResponse(
            text="hi",
            model="m1",
            purpose=LLMPurpose.SUMMARY,
            usage=usage,
        )
        assert r.purpose == LLMPurpose.SUMMARY
        assert r.usage == usage

    def test_frozen(self) -> None:
        r = LLMResponse(text="hi", model="m1")
        with pytest.raises(AttributeError):
            r.text = "bye"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = LLMResponse(text="hi", model="m1")
        b = LLMResponse(text="hi", model="m1")
        assert a == b

    def test_inequality(self) -> None:
        a = LLMResponse(text="hi", model="m1")
        b = LLMResponse(text="bye", model="m1")
        assert a != b


# ---------------------------------------------------------------------------
# completion() — basic behaviour
# ---------------------------------------------------------------------------


class TestCompletionBasic:
    """Tests for the happy-path completion() behaviour."""

    @pytest.mark.asyncio
    async def test_returns_llm_response(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("Hello!"))

            result = await completion(
                purpose=LLMPurpose.SUMMARY,
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        assert isinstance(result, LLMResponse)
        assert result.text == "Hello!"
        assert result.purpose == LLMPurpose.SUMMARY

    @pytest.mark.asyncio
    async def test_strips_whitespace(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_response("  padded text  \n")
            )

            result = await completion(
                purpose=LLMPurpose.SUMMARY,
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        assert result.text == "padded text"

    @pytest.mark.asyncio
    async def test_uses_purpose_model(self) -> None:
        with (
            _patch_litellm() as mock_litellm,
            patch("ica.services.llm.get_model", return_value="anthropic/claude-sonnet-4.5") as mock_get,
            patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False),
        ):
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            result = await completion(
                purpose=LLMPurpose.THEME,
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        mock_get.assert_called_once_with(LLMPurpose.THEME)
        assert result.model == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_explicit_model_overrides_purpose(self) -> None:
        with (
            _patch_litellm() as mock_litellm,
            patch("ica.services.llm.get_model") as mock_get,
            patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False),
        ):
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            result = await completion(
                purpose=LLMPurpose.THEME,
                model="openai/gpt-4.1",
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        mock_get.assert_not_called()
        assert result.model == "openai/gpt-4.1"

    @pytest.mark.asyncio
    async def test_model_only_no_purpose(self) -> None:
        with (
            _patch_litellm() as mock_litellm,
            patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False),
        ):
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            result = await completion(
                model="google/gemini-2.5-flash",
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        assert result.model == "google/gemini-2.5-flash"
        assert result.purpose is None

    @pytest.mark.asyncio
    async def test_openrouter_prefix_added_when_key_set(self) -> None:
        with (
            _patch_litellm() as mock_litellm,
            patch("ica.services.llm.get_model", return_value="anthropic/claude-sonnet-4.5"),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}, clear=False),
        ):
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            result = await completion(
                purpose=LLMPurpose.THEME,
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        assert result.model == "openrouter/anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_openrouter_prefix_not_doubled(self) -> None:
        with (
            _patch_litellm() as mock_litellm,
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}, clear=False),
        ):
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            result = await completion(
                model="openrouter/anthropic/claude-sonnet-4.5",
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        assert result.model == "openrouter/anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_neither_purpose_nor_model_raises(self) -> None:
        with pytest.raises(ValueError, match="Either 'purpose' or 'model'"):
            await completion(system_prompt=SYSTEM, user_prompt=USER)


# ---------------------------------------------------------------------------
# completion() — message construction
# ---------------------------------------------------------------------------


class TestCompletionMessages:
    """Tests for how completion() builds the messages list."""

    @pytest.mark.asyncio
    async def test_messages_structure(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            await completion(
                model="test-model",
                system_prompt="sys",
                user_prompt="usr",
            )

        call_kwargs = mock_litellm.acompletion.call_args
        messages = call_kwargs.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "sys"}
        assert messages[1] == {"role": "user", "content": "usr"}

    @pytest.mark.asyncio
    async def test_model_passed_to_litellm(self) -> None:
        with (
            _patch_litellm() as mock_litellm,
            patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False),
        ):
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            await completion(
                model="my-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "my-model"

    @pytest.mark.asyncio
    async def test_extra_kwargs_forwarded(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
                temperature=0.7,
                max_tokens=1000,
            )

        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["temperature"] == 0.7
        assert call_kwargs.kwargs["max_tokens"] == 1000


# ---------------------------------------------------------------------------
# completion() — usage extraction
# ---------------------------------------------------------------------------


class TestCompletionUsage:
    """Tests for token usage extraction."""

    @pytest.mark.asyncio
    async def test_usage_extracted(self) -> None:
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_response("ok", usage=usage)
            )

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        assert result.usage == usage

    @pytest.mark.asyncio
    async def test_no_usage_returns_none(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        assert result.usage is None


# ---------------------------------------------------------------------------
# completion() — empty response handling
# ---------------------------------------------------------------------------


class TestCompletionEmptyResponse:
    """Tests for empty/null response detection."""

    @pytest.mark.asyncio
    async def test_empty_string_raises(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response(""))

            with pytest.raises(LLMError, match="empty response"):
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                )

    @pytest.mark.asyncio
    async def test_whitespace_only_raises(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("   \n\t  "))

            with pytest.raises(LLMError, match="empty response"):
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                )

    @pytest.mark.asyncio
    async def test_none_content_raises(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response(None))

            with pytest.raises(LLMError, match="empty response"):
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                )

    @pytest.mark.asyncio
    async def test_empty_response_includes_model_in_message(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response(""))

            with pytest.raises(LLMError, match="test-model"):
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                )

    @pytest.mark.asyncio
    async def test_empty_response_is_llm_error(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response(""))

            with pytest.raises(LLMError) as exc_info:
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                    step="Summarization",
                )
            assert exc_info.value.step == "Summarization"

    @pytest.mark.asyncio
    async def test_empty_response_not_retried(self) -> None:
        """Empty responses are a content error, not a transient error."""
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response(""))

            with pytest.raises(LLMError):
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                )

            # Should be called exactly once — no retries.
            assert mock_litellm.acompletion.await_count == 1


# ---------------------------------------------------------------------------
# completion() — retry behaviour
# ---------------------------------------------------------------------------


class TestCompletionRetry:
    """Tests for retry logic with transient errors."""

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=[_RateLimitSentinel("rate limited"), _make_response("ok")]
            )

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
                retry_base_delay=0.01,
            )

        assert result.text == "ok"
        assert mock_litellm.acompletion.await_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_service_unavailable(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=[_ServiceUnavailableSentinel("unavailable"), _make_response("ok")]
            )

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
                retry_base_delay=0.01,
            )

        assert result.text == "ok"
        assert mock_litellm.acompletion.await_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=[_TimeoutSentinel("timed out"), _make_response("ok")]
            )

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
                retry_base_delay=0.01,
            )

        assert result.text == "ok"

    @pytest.mark.asyncio
    async def test_retries_on_internal_server_error(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=[_InternalServerSentinel("500"), _make_response("ok")]
            )

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
                retry_base_delay=0.01,
            )

        assert result.text == "ok"

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=[_APIConnectionSentinel("refused"), _make_response("ok")]
            )

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
                retry_base_delay=0.01,
            )

        assert result.text == "ok"

    @pytest.mark.asyncio
    async def test_exhausts_retries(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=_RateLimitSentinel("rate limited")
            )

            with pytest.raises(LLMError, match="failed after"):
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                    max_retries=2,
                    retry_base_delay=0.01,
                )

            # initial attempt + 2 retries = 3 total
            assert mock_litellm.acompletion.await_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=_NonRetryableError("auth failed")
            )

            with pytest.raises(LLMError, match="auth failed"):
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                )

            assert mock_litellm.acompletion.await_count == 1

    @pytest.mark.asyncio
    async def test_non_retryable_wraps_as_llm_error(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            original = _NonRetryableError("bad request")
            mock_litellm.acompletion = AsyncMock(side_effect=original)

            with pytest.raises(LLMError) as exc_info:
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                    step="Theme Generation",
                )

            assert exc_info.value.__cause__ is original
            assert exc_info.value.step == "Theme Generation"

    @pytest.mark.asyncio
    async def test_max_retries_zero(self) -> None:
        """max_retries=0 means only 1 attempt, no retries."""
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=_RateLimitSentinel("rate limited")
            )

            with pytest.raises(LLMError, match="failed after 1 attempts"):
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                    max_retries=0,
                    retry_base_delay=0.01,
                )

            assert mock_litellm.acompletion.await_count == 1

    @pytest.mark.asyncio
    async def test_succeeds_on_last_retry(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            err = _RateLimitSentinel("rate limited")
            mock_litellm.acompletion = AsyncMock(
                side_effect=[err, err, _make_response("finally")]
            )

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
                max_retries=2,
                retry_base_delay=0.01,
            )

        assert result.text == "finally"
        assert mock_litellm.acompletion.await_count == 3

    @pytest.mark.asyncio
    async def test_retryable_error_preserves_cause(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            original = _RateLimitSentinel("rate limited")
            mock_litellm.acompletion = AsyncMock(side_effect=original)

            with pytest.raises(LLMError) as exc_info:
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                    max_retries=0,
                    retry_base_delay=0.01,
                )

            assert exc_info.value.__cause__ is original

    @pytest.mark.asyncio
    async def test_multiple_retryable_types_in_sequence(self) -> None:
        """Different retryable error types across retries."""
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _RateLimitSentinel("rate limit"),
                    _TimeoutSentinel("timeout"),
                    _make_response("ok"),
                ]
            )

            result = await completion(
                model="test-model",
                system_prompt=SYSTEM,
                user_prompt=USER,
                retry_base_delay=0.01,
            )

        assert result.text == "ok"
        assert mock_litellm.acompletion.await_count == 3


# ---------------------------------------------------------------------------
# completion() — step name in errors
# ---------------------------------------------------------------------------


class TestCompletionStepName:
    """Tests for step name propagation in errors."""

    @pytest.mark.asyncio
    async def test_default_step_name(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response(""))

            with pytest.raises(LLMError) as exc_info:
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                )
            assert exc_info.value.step == "LLM"

    @pytest.mark.asyncio
    async def test_custom_step_name(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response(""))

            with pytest.raises(LLMError) as exc_info:
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                    step="HTML Generation",
                )
            assert exc_info.value.step == "HTML Generation"

    @pytest.mark.asyncio
    async def test_step_in_retry_exhausted_error(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=_RateLimitSentinel("limit")
            )

            with pytest.raises(LLMError) as exc_info:
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                    step="Markdown Validation",
                    max_retries=0,
                    retry_base_delay=0.01,
                )
            assert exc_info.value.step == "Markdown Validation"

    @pytest.mark.asyncio
    async def test_step_in_non_retryable_error(self) -> None:
        with _patch_litellm() as mock_litellm:
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(
                side_effect=_NonRetryableError("forbidden")
            )

            with pytest.raises(LLMError) as exc_info:
                await completion(
                    model="test-model",
                    system_prompt=SYSTEM,
                    user_prompt=USER,
                    step="Social Media",
                )
            assert exc_info.value.step == "Social Media"


# ---------------------------------------------------------------------------
# completion() — all LLMPurpose values
# ---------------------------------------------------------------------------


class TestCompletionAllPurposes:
    """Ensure completion works with every LLMPurpose enum member."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    async def test_each_purpose(self, purpose: LLMPurpose) -> None:
        with (
            _patch_litellm() as mock_litellm,
            patch("ica.services.llm.get_model", return_value=f"test/{purpose.name.lower()}"),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False),
        ):
            _set_retryable_types(mock_litellm)
            mock_litellm.acompletion = AsyncMock(return_value=_make_response("ok"))

            result = await completion(
                purpose=purpose,
                system_prompt=SYSTEM,
                user_prompt=USER,
            )

        assert result.purpose == purpose
        assert result.model == f"test/{purpose.name.lower()}"


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Tests for module-level defaults."""

    def test_default_max_retries(self) -> None:
        assert DEFAULT_MAX_RETRIES == 3

    def test_default_retry_base_delay(self) -> None:
        assert DEFAULT_RETRY_BASE_DELAY == 1.0

    def test_default_retry_max_delay(self) -> None:
        assert DEFAULT_RETRY_MAX_DELAY == 30.0
