"""Guided Slack adapter — wraps SlackService with run/step correlation and interaction history.

Provides :class:`GuidedSlackAdapter`, a drop-in replacement for
:class:`~ica.services.slack.SlackService` that:

* Tags every outgoing message with ``[run_id/step_name]`` metadata.
* Records each Slack interaction (method, message, response) in a per-step log.
* Exposes :meth:`step_interactions` so the guided runner can merge interaction
  data into :attr:`~ica.guided.state.StepRecord.artifacts` and
  :attr:`~ica.guided.state.TestRunState.decisions`.

Usage::

    from ica.services.slack import SlackService
    from ica.guided.slack_adapter import GuidedSlackAdapter

    inner = SlackService(token="xoxb-...", channel="#test")
    adapter = GuidedSlackAdapter(inner, run_id="abc123")
    adapter.set_step("curation")
    # ... pass adapter to pipeline steps via set_shared_service(adapter)
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from ica.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Interaction record
# ---------------------------------------------------------------------------


@dataclass
class SlackInteraction:
    """Record of a single Slack interaction during a guided run."""

    step: str
    method: str
    timestamp: str
    message: str = ""
    response: dict[str, str] | str | None = None
    attempt: int = 1


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SlackTimeoutError(Exception):
    """Raised when a Slack send-and-wait call exceeds the configured timeout."""

    def __init__(self, method: str, timeout: float) -> None:
        self.method = method
        self.timeout = timeout
        super().__init__(
            f"Slack {method} timed out after {timeout:.0f}s waiting for operator response"
        )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class GuidedSlackAdapter:
    """Wraps a :class:`~ica.services.slack.SlackService` with guided-run metadata.

    Implements the same interface as ``SlackService`` so it can be injected via
    :func:`~ica.services.slack.set_shared_service`.  Every outgoing message is
    tagged with ``[run_id/step_name]`` and every interaction is recorded for
    post-step artifact extraction.

    Args:
        inner: The real ``SlackService`` to delegate calls to.
        run_id: Unique identifier for the current guided test run.
    """

    def __init__(self, inner: Any, *, run_id: str, timeout: float | None = None) -> None:
        self._inner = inner
        self._run_id = run_id
        self._timeout = timeout
        self._current_step: str = ""
        self._attempt: int = 1
        self._interactions: list[SlackInteraction] = []

    # --- Configuration ---

    @property
    def timeout(self) -> float | None:
        """Timeout in seconds for send-and-wait calls, or ``None`` for no timeout."""
        return self._timeout

    @timeout.setter
    def timeout(self, value: float | None) -> None:
        self._timeout = value

    # --- Step tracking ---

    def set_step(self, step_name: str, *, attempt: int = 1) -> None:
        """Set the current pipeline step name and attempt for interaction correlation.

        Args:
            step_name: Pipeline step name (e.g. ``"theme_generation"``).
            attempt: Current attempt number (1-based).  On redo the runner
                passes the incremented attempt so messages and interaction
                records carry the correct attempt tag.
        """
        self._current_step = step_name
        self._attempt = attempt

    @property
    def current_step(self) -> str:
        """The currently active step name."""
        return self._current_step

    @property
    def current_attempt(self) -> int:
        """The attempt number for the current step."""
        return self._attempt

    # --- Interaction log ---

    @property
    def interactions(self) -> list[SlackInteraction]:
        """All recorded interactions (copy)."""
        return list(self._interactions)

    def step_interactions(self, step_name: str) -> list[SlackInteraction]:
        """Return interactions recorded for a specific step."""
        return [i for i in self._interactions if i.step == step_name]

    def drain_step_interactions(self, step_name: str) -> list[dict[str, Any]]:
        """Remove and return serialised interactions for *step_name*.

        Interactions are removed from the internal list so that a subsequent
        redo of the same step does not re-return earlier attempt interactions.
        """
        kept: list[SlackInteraction] = []
        drained: list[SlackInteraction] = []
        for i in self._interactions:
            if i.step == step_name:
                drained.append(i)
            else:
                kept.append(i)
        self._interactions = kept
        return [asdict(i) for i in drained]

    # --- Redo support ---

    def invalidate_pending(self) -> int:
        """Remove any pending callbacks from the inner service.

        Call before starting a redo to prevent stale callbacks from a previous
        attempt being resolved when the operator clicks an outdated button.

        Returns:
            Number of invalidated callbacks.
        """
        pending = self._inner.pending
        count = len(pending)
        if count:
            pending.clear()
            logger.info("Invalidated %d pending Slack callback(s)", count)
        return count

    # --- Internal helpers ---

    def _record(
        self,
        method: str,
        message: str,
        response: dict[str, str] | str | None = None,
    ) -> SlackInteraction:
        interaction = SlackInteraction(
            step=self._current_step,
            method=method,
            timestamp=_now_iso(),
            message=message,
            response=response,
            attempt=self._attempt,
        )
        self._interactions.append(interaction)
        logger.debug(
            "Recorded Slack interaction: step=%s method=%s attempt=%d",
            self._current_step,
            method,
            self._attempt,
        )
        return interaction

    def _tag(self, text: str) -> str:
        """Prepend run/step metadata to message text.

        For attempt > 1, the attempt number is appended so the operator can
        distinguish a redo message from the original.
        """
        if self._attempt > 1:
            return f"[{self._run_id}/{self._current_step} (attempt {self._attempt})] {text}"
        return f"[{self._run_id}/{self._current_step}] {text}"

    # --- Delegated SlackService interface ---

    # SlackNotifier
    async def send_message(self, channel: str, text: str) -> None:
        """Post a plain-text message with run/step metadata."""
        tagged = self._tag(text)
        await self._inner.send_message(channel, tagged)
        self._record("send_message", text)

    # SlackSummaryReview.send_channel_message
    async def send_channel_message(
        self,
        text: str,
        *,
        blocks: list[dict[str, object]] | None = None,
    ) -> None:
        """Post a channel message with run/step metadata."""
        tagged = self._tag(text)
        await self._inner.send_channel_message(tagged, blocks=blocks)
        self._record("send_channel_message", text)

    # SlackErrorNotifier
    async def send_error(self, message: str) -> None:
        """Post an error notification with run/step metadata."""
        tagged = self._tag(message)
        await self._inner.send_error(tagged)
        self._record("send_error", message)

    # SlackApprovalSender
    async def send_and_wait(
        self,
        channel: str,
        text: str,
        *,
        approve_label: str = "Proceed to next steps",
    ) -> None:
        """Post an approval button (tagged) and block until clicked."""
        tagged = self._tag(text)
        try:
            async with asyncio.timeout(self._timeout):
                await self._inner.send_and_wait(channel, tagged, approve_label=approve_label)
        except TimeoutError:
            self._record("send_and_wait", text, response={"error": "timeout"})
            raise SlackTimeoutError("send_and_wait", self._timeout or 0) from None
        self._record("send_and_wait", text, response={"action": "approved"})

    # SlackSummaryReview.send_and_wait_form
    async def send_and_wait_form(
        self,
        message: str,
        *,
        form_fields: list[dict[str, object]],
        button_label: str = "Proceed to Next Steps",
        form_title: str = "Proceed to next step",
        form_description: str = "",
    ) -> dict[str, str]:
        """Post a form trigger (tagged) and block until the user submits."""
        tagged = self._tag(message)
        try:
            async with asyncio.timeout(self._timeout):
                result = await self._inner.send_and_wait_form(
                    tagged,
                    form_fields=form_fields,
                    button_label=button_label,
                    form_title=form_title,
                    form_description=form_description,
                )
        except TimeoutError:
            self._record("send_and_wait_form", message, response={"error": "timeout"})
            raise SlackTimeoutError("send_and_wait_form", self._timeout or 0) from None
        self._record("send_and_wait_form", message, response=result)
        return result

    # SlackManualFallback + SlackSummaryReview.send_and_wait_freetext
    async def send_and_wait_freetext(
        self,
        message: str,
        *,
        button_label: str = "Add feedback",
        form_title: str = "Feedback Form",
        form_description: str = "",
    ) -> str:
        """Post a freetext trigger (tagged) and block until the user submits."""
        tagged = self._tag(message)
        try:
            async with asyncio.timeout(self._timeout):
                result = await self._inner.send_and_wait_freetext(
                    tagged,
                    button_label=button_label,
                    form_title=form_title,
                    form_description=form_description,
                )
        except TimeoutError:
            self._record("send_and_wait_freetext", message, response={"error": "timeout"})
            raise SlackTimeoutError("send_and_wait_freetext", self._timeout or 0) from None
        self._record("send_and_wait_freetext", message, response=result)
        return result

    # Handler registration (delegate to inner)
    def register_handlers(self, bolt_app: Any) -> None:
        """Delegate handler registration to the wrapped service."""
        self._inner.register_handlers(bolt_app)

    # --- Properties (delegate to inner) ---

    @property
    def client(self) -> Any:
        """The underlying ``AsyncWebClient``."""
        return self._inner.client

    @property
    def channel(self) -> str:
        """The default Slack channel."""
        return self._inner.channel

    @property
    def pending(self) -> dict[str, Any]:
        """Pending interactions from the inner service."""
        return self._inner.pending
