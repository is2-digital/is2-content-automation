"""Unified LLM service wrapping LiteLLM.

Provides a single ``completion()`` async function that all pipeline steps use
instead of calling ``litellm.acompletion`` directly.  Handles:

* Model routing via :class:`~ica.config.llm_config.LLMPurpose`
* Message construction from system/user prompts
* Response content extraction and empty-response validation
* Retry with exponential back-off for transient / rate-limit errors
* Structured logging with model and purpose context
* Error mapping to :class:`~ica.errors.LLMError`

Usage::

    from ica.services.llm import completion
    from ica.config.llm_config import LLMPurpose

    text = await completion(
        purpose=LLMPurpose.SUMMARY,
        system_prompt="You are ...",
        user_prompt="Summarize ...",
    )
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import litellm

from ica.config.llm_config import LLMPurpose, get_model
from ica.errors import LLMError
from ica.logging import get_logger

logger = get_logger(__name__)

# Retry defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds
DEFAULT_RETRY_MAX_DELAY = 30.0  # seconds

def _retryable_errors() -> tuple[type[Exception], ...]:
    """Return LiteLLM exception types that are safe to retry.

    Resolved at call time so the reference tracks the current
    ``litellm`` module (important for test patching).
    """
    return (
        litellm.RateLimitError,
        litellm.ServiceUnavailableError,
        litellm.Timeout,
        litellm.InternalServerError,
        litellm.APIConnectionError,
    )


@dataclass(frozen=True)
class LLMResponse:
    """Result of an LLM completion call.

    Attributes:
        text: The extracted response text (stripped).
        model: The model identifier that was used.
        purpose: The LLM purpose key, if provided.
        usage: Token usage dict from the API response, if available.
    """

    text: str
    model: str
    purpose: LLMPurpose | None = None
    usage: dict[str, int] | None = None


async def completion(
    *,
    purpose: LLMPurpose | None = None,
    model: str | None = None,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    step: str = "LLM",
    **litellm_kwargs: Any,
) -> LLMResponse:
    """Run an LLM completion and return the extracted text.

    Either *purpose* or *model* must be provided.  If both are given,
    *model* takes precedence.

    Args:
        purpose: LLM purpose key for automatic model selection via
            :func:`~ica.config.llm_config.get_model`.
        model: Explicit model identifier (e.g. ``"anthropic/claude-sonnet-4.5"``).
            Overrides *purpose* if both are given.
        system_prompt: System prompt text.
        user_prompt: User prompt text.
        max_retries: Maximum number of retry attempts for transient errors.
        retry_base_delay: Base delay in seconds for exponential back-off.
        retry_max_delay: Maximum delay in seconds between retries.
        step: Pipeline step name used in error messages.
        **litellm_kwargs: Extra keyword arguments forwarded to
            ``litellm.acompletion`` (e.g. ``temperature``, ``max_tokens``).

    Returns:
        An :class:`LLMResponse` with the extracted text, model used,
        and optional usage data.

    Raises:
        ValueError: If neither *purpose* nor *model* is provided.
        LLMError: If the LLM call fails after all retries or returns
            an empty response.
    """
    if model is None and purpose is None:
        raise ValueError("Either 'purpose' or 'model' must be provided")

    model_id = model or get_model(purpose)  # type: ignore[arg-type]

    # Prepend "openrouter/" so LiteLLM routes through OpenRouter when the
    # key is configured and the model isn't already prefixed.
    if (
        os.environ.get("OPENROUTER_API_KEY")
        and not model_id.startswith("openrouter/")
    ):
        model_id = f"openrouter/{model_id}"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    logger.info(
        "LLM call: model=%s purpose=%s step=%s",
        model_id,
        purpose.value if purpose else "custom",
        step,
    )

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await litellm.acompletion(
                model=model_id,
                messages=messages,
                **litellm_kwargs,
            )

            content = response.choices[0].message.content  # type: ignore[union-attr]
            if not content or not content.strip():
                raise LLMError(step, f"LLM returned an empty response (model={model_id})")

            # Extract usage if available.
            usage: dict[str, int] | None = None
            if hasattr(response, "usage") and response.usage is not None:
                usage = {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                }

            logger.info(
                "LLM response: model=%s tokens=%s",
                model_id,
                usage.get("total_tokens") if usage else "unknown",
            )

            return LLMResponse(
                text=content.strip(),
                model=model_id,
                purpose=purpose,
                usage=usage,
            )

        except LLMError:
            raise
        except _retryable_errors() as exc:
            last_error = exc
            if attempt < max_retries:
                delay = min(
                    retry_base_delay * (2**attempt),
                    retry_max_delay,
                )
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "LLM call failed after %d attempts: %s",
                    max_retries + 1,
                    exc,
                )
        except Exception as exc:
            logger.error("LLM call failed with non-retryable error: %s", exc)
            raise LLMError(step, str(exc)) from exc

    raise LLMError(step, f"LLM call failed after {max_retries + 1} attempts: {last_error}") from last_error
