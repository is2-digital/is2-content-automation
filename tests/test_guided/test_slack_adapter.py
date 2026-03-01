"""Tests for ica.guided.slack_adapter — GuidedSlackAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.guided.runner import _merge_slack_interactions, run_guided
from ica.guided.slack_adapter import GuidedSlackAdapter
from ica.guided.state import RunPhase, StepStatus, TestRunState
from ica.pipeline.orchestrator import PipelineContext, StepName

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inner() -> MagicMock:
    """Create a mock SlackService with all async methods."""
    inner = MagicMock()
    inner.send_message = AsyncMock()
    inner.send_channel_message = AsyncMock()
    inner.send_error = AsyncMock()
    inner.send_and_wait = AsyncMock()
    inner.send_and_wait_form = AsyncMock(return_value={"Theme": "AI Today"})
    inner.send_and_wait_freetext = AsyncMock(return_value="Looks good")
    inner.channel = "#test-channel"
    inner.client = MagicMock()
    inner.pending = {}
    return inner


# ---------------------------------------------------------------------------
# GuidedSlackAdapter — core behaviour
# ---------------------------------------------------------------------------


class TestGuidedSlackAdapterInit:
    """Adapter initialisation and step tracking."""

    def test_initial_state(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="run-1")
        assert adapter.current_step == ""
        assert adapter.interactions == []

    def test_set_step(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="run-1")
        adapter.set_step("curation")
        assert adapter.current_step == "curation"

    def test_property_delegation(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="run-1")
        assert adapter.channel == "#test-channel"
        assert adapter.client is inner.client
        assert adapter.pending is inner.pending


# ---------------------------------------------------------------------------
# Message tagging
# ---------------------------------------------------------------------------


class TestMessageTagging:
    """All outgoing messages include run/step metadata."""

    async def test_send_message_tagged(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="abc")
        adapter.set_step("curation")

        await adapter.send_message("#ch", "Hello")

        inner.send_message.assert_awaited_once_with("#ch", "[abc/curation] Hello")

    async def test_send_channel_message_tagged(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="abc")
        adapter.set_step("summarization")

        await adapter.send_channel_message("Summary ready", blocks=[{"type": "section"}])

        inner.send_channel_message.assert_awaited_once_with(
            "[abc/summarization] Summary ready",
            blocks=[{"type": "section"}],
        )

    async def test_send_error_tagged(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="abc")
        adapter.set_step("html_generation")

        await adapter.send_error("Something broke")

        inner.send_error.assert_awaited_once_with("[abc/html_generation] Something broke")

    async def test_send_and_wait_tagged(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="abc")
        adapter.set_step("curation")

        await adapter.send_and_wait("#ch", "Ready?", approve_label="Go")

        inner.send_and_wait.assert_awaited_once_with(
            "#ch", "[abc/curation] Ready?", approve_label="Go"
        )

    async def test_send_and_wait_form_tagged(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="abc")
        adapter.set_step("theme_generation")
        fields = [{"fieldLabel": "Theme", "fieldType": "dropdown"}]

        result = await adapter.send_and_wait_form(
            "Pick theme",
            form_fields=fields,
            button_label="Select",
            form_title="Theme",
        )

        inner.send_and_wait_form.assert_awaited_once_with(
            "[abc/theme_generation] Pick theme",
            form_fields=fields,
            button_label="Select",
            form_title="Theme",
            form_description="",
        )
        assert result == {"Theme": "AI Today"}

    async def test_send_and_wait_freetext_tagged(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="abc")
        adapter.set_step("summarization")

        result = await adapter.send_and_wait_freetext(
            "Any feedback?",
            button_label="Feedback",
            form_title="Review",
        )

        inner.send_and_wait_freetext.assert_awaited_once_with(
            "[abc/summarization] Any feedback?",
            button_label="Feedback",
            form_title="Review",
            form_description="",
        )
        assert result == "Looks good"


# ---------------------------------------------------------------------------
# Interaction recording
# ---------------------------------------------------------------------------


class TestInteractionRecording:
    """Each method call records a SlackInteraction."""

    async def test_send_message_recorded(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation")

        await adapter.send_message("#ch", "Hello")

        interactions = adapter.interactions
        assert len(interactions) == 1
        assert interactions[0].step == "curation"
        assert interactions[0].method == "send_message"
        assert interactions[0].message == "Hello"
        assert interactions[0].response is None

    async def test_send_and_wait_recorded(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation")

        await adapter.send_and_wait("#ch", "Ready?")

        interactions = adapter.interactions
        assert len(interactions) == 1
        assert interactions[0].method == "send_and_wait"
        assert interactions[0].response == {"action": "approved"}

    async def test_send_and_wait_form_recorded(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("theme_generation")

        await adapter.send_and_wait_form("Pick", form_fields=[])

        interactions = adapter.interactions
        assert len(interactions) == 1
        assert interactions[0].method == "send_and_wait_form"
        assert interactions[0].response == {"Theme": "AI Today"}

    async def test_send_and_wait_freetext_recorded(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("summarization")

        await adapter.send_and_wait_freetext("Feedback?")

        interactions = adapter.interactions
        assert len(interactions) == 1
        assert interactions[0].method == "send_and_wait_freetext"
        assert interactions[0].response == "Looks good"

    async def test_multiple_interactions_across_steps(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")

        adapter.set_step("curation")
        await adapter.send_message("#ch", "Step 1 msg")

        adapter.set_step("summarization")
        await adapter.send_message("#ch", "Step 2 msg")
        await adapter.send_and_wait_freetext("Feedback?")

        assert len(adapter.interactions) == 3
        assert len(adapter.step_interactions("curation")) == 1
        assert len(adapter.step_interactions("summarization")) == 2


# ---------------------------------------------------------------------------
# drain_step_interactions
# ---------------------------------------------------------------------------


class TestDrainStepInteractions:
    """drain_step_interactions returns serialised dicts for artifact storage."""

    async def test_drain_returns_dicts(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation")
        await adapter.send_and_wait("#ch", "Go?")

        result = adapter.drain_step_interactions("curation")

        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0]["step"] == "curation"
        assert result[0]["method"] == "send_and_wait"

    async def test_drain_empty_for_unknown_step(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        assert adapter.drain_step_interactions("nonexistent") == []


# ---------------------------------------------------------------------------
# register_handlers delegation
# ---------------------------------------------------------------------------


class TestRegisterHandlers:
    """register_handlers delegates to the inner service."""

    def test_delegates_to_inner(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="r1")
        bolt_app = MagicMock()

        adapter.register_handlers(bolt_app)

        inner.register_handlers.assert_called_once_with(bolt_app)


# ---------------------------------------------------------------------------
# _merge_slack_interactions
# ---------------------------------------------------------------------------


class TestMergeSlackInteractions:
    """Runner helper merges interaction data into state."""

    def _make_state_at_step(self, step_index: int = 0) -> TestRunState:
        state = TestRunState(run_id="r1")
        state.current_step_index = step_index
        state.steps[step_index].status = StepStatus.COMPLETED
        return state

    async def test_merge_adds_artifacts_and_decisions(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation")
        await adapter.send_and_wait("#ch", "Ready?")

        state = self._make_state_at_step(0)
        _merge_slack_interactions(adapter, StepName.CURATION, state)

        # Artifacts should have slack_interactions
        assert "slack_interactions" in state.steps[0].artifacts
        interactions = state.steps[0].artifacts["slack_interactions"]
        assert len(interactions) == 1
        assert interactions[0]["method"] == "send_and_wait"

        # Decisions should include the Slack interaction
        assert len(state.decisions) == 1
        assert state.decisions[0].step == "curation"
        assert state.decisions[0].action == "slack:send_and_wait"

    async def test_merge_skips_non_interactive_methods(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation")
        await adapter.send_message("#ch", "Just a notification")

        state = self._make_state_at_step(0)
        _merge_slack_interactions(adapter, StepName.CURATION, state)

        # Artifacts should be recorded
        assert "slack_interactions" in state.steps[0].artifacts
        # But no decisions (send_message is not interactive)
        assert len(state.decisions) == 0

    async def test_merge_noop_when_no_interactions(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")

        state = self._make_state_at_step(0)
        _merge_slack_interactions(adapter, StepName.CURATION, state)

        assert "slack_interactions" not in state.steps[0].artifacts
        assert len(state.decisions) == 0


# ---------------------------------------------------------------------------
# run_guided with slack_override — integration
# ---------------------------------------------------------------------------


class TestRunGuidedWithSlackOverride:
    """Integration: slack_override wires adapter into the guided runner."""

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    def _patch_steps(self):
        """Patch get_step_fn to return a mock step for all steps."""

        def _get_step(name: StepName) -> AsyncMock:
            async def step_fn(ctx: PipelineContext) -> PipelineContext:
                return ctx

            return AsyncMock(side_effect=step_fn)

        return patch("ica.guided.runner.get_step_fn", side_effect=_get_step)

    async def test_adapter_installed_and_restored(self, store_dir: Path) -> None:
        """Shared service is set during run and restored after."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="override-test")
        console = MagicMock()

        with self._patch_steps(), patch(
            "ica.services.slack.set_shared_service"
        ) as mock_set, patch(
            "ica.services.slack.get_shared_service", return_value=None
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
            )

        assert state.phase == RunPhase.ABORTED
        # set_shared_service called twice: once to install, once to restore
        assert mock_set.call_count == 2

    async def test_set_step_called_before_execution(self, store_dir: Path) -> None:
        """Adapter.set_step() is called with the step name before each step runs."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="step-track")
        console = MagicMock()
        steps_seen: list[str] = []
        original_set_step = adapter.set_step

        def tracking_set_step(name: str) -> None:
            steps_seen.append(name)
            original_set_step(name)

        adapter.set_step = tracking_set_step  # type: ignore[method-assign]

        with self._patch_steps():
            await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
            )

        assert steps_seen == ["curation"]

    async def test_no_override_no_side_effects(self, store_dir: Path) -> None:
        """Without slack_override, no shared service manipulation occurs."""
        console = MagicMock()

        with self._patch_steps(), patch(
            "ica.services.slack.set_shared_service"
        ) as mock_set:
            await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
            )

        mock_set.assert_not_called()
