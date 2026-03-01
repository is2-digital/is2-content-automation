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


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


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

    def __init__(self, inner: Any, *, run_id: str) -> None:
        self._inner = inner
        self._run_id = run_id
        self._current_step: str = ""
        self._interactions: list[SlackInteraction] = []

    # --- Step tracking ---

    def set_step(self, step_name: str) -> None:
        """Set the current pipeline step name for interaction correlation."""
        self._current_step = step_name

    @property
    def current_step(self) -> str:
        """The currently active step name."""
        return self._current_step

    # --- Interaction log ---

    @property
    def interactions(self) -> list[SlackInteraction]:
        """All recorded interactions (copy)."""
        return list(self._interactions)

    def step_interactions(self, step_name: str) -> list[SlackInteraction]:
        """Return interactions recorded for a specific step."""
        return [i for i in self._interactions if i.step == step_name]

    def drain_step_interactions(self, step_name: str) -> list[dict[str, Any]]:
        """Return serialised interactions for *step_name* (for artifact storage)."""
        return [asdict(i) for i in self.step_interactions(step_name)]

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
        )
        self._interactions.append(interaction)
        logger.debug(
            "Recorded Slack interaction: step=%s method=%s",
            self._current_step,
            method,
        )
        return interaction

    def _tag(self, text: str) -> str:
        """Prepend run/step metadata to message text."""
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
        await self._inner.send_and_wait(channel, tagged, approve_label=approve_label)
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
        result = await self._inner.send_and_wait_form(
            tagged,
            form_fields=form_fields,
            button_label=button_label,
            form_title=form_title,
            form_description=form_description,
        )
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
        result = await self._inner.send_and_wait_freetext(
            tagged,
            button_label=button_label,
            form_title=form_title,
            form_description=form_description,
        )
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
