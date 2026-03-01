"""Tests for ica.guided.slack_adapter — GuidedSlackAdapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.guided.runner import _classify_step_error, _merge_slack_interactions, run_guided
from ica.guided.slack_adapter import GuidedSlackAdapter, SlackTimeoutError
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

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

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

        with (
            self._patch_steps(),
            patch("ica.services.slack.set_shared_service") as mock_set,
            patch("ica.services.slack.get_shared_service", return_value=None),
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
        steps_seen: list[tuple[str, int]] = []
        original_set_step = adapter.set_step

        def tracking_set_step(name: str, *, attempt: int = 1) -> None:
            steps_seen.append((name, attempt))
            original_set_step(name, attempt=attempt)

        adapter.set_step = tracking_set_step  # type: ignore[method-assign]

        with self._patch_steps():
            await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
            )

        assert steps_seen == [("curation", 1)]

    async def test_no_override_no_side_effects(self, store_dir: Path) -> None:
        """Without slack_override, no shared service manipulation occurs."""
        console = MagicMock()

        with self._patch_steps(), patch("ica.services.slack.set_shared_service") as mock_set:
            await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
            )

        mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------


class TestSlackTimeoutError:
    """SlackTimeoutError carries method and timeout metadata."""

    def test_message_includes_method_and_timeout(self) -> None:
        err = SlackTimeoutError("send_and_wait", 300)
        assert "send_and_wait" in str(err)
        assert "300" in str(err)
        assert err.method == "send_and_wait"
        assert err.timeout == 300


class TestAdapterTimeout:
    """GuidedSlackAdapter enforces timeout on send-and-wait methods."""

    def test_default_timeout_is_none(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        assert adapter.timeout is None

    def test_timeout_set_via_constructor(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1", timeout=60.0)
        assert adapter.timeout == 60.0

    def test_timeout_set_via_property(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.timeout = 120.0
        assert adapter.timeout == 120.0

    async def test_send_and_wait_timeout(self) -> None:
        inner = _make_inner()

        async def hang(*_a: object, **_kw: object) -> None:
            await asyncio.sleep(999)

        inner.send_and_wait = hang
        adapter = GuidedSlackAdapter(inner, run_id="r1", timeout=0.01)
        adapter.set_step("curation")

        with pytest.raises(SlackTimeoutError) as exc_info:
            await adapter.send_and_wait("#ch", "Ready?")

        assert exc_info.value.method == "send_and_wait"
        assert exc_info.value.timeout == 0.01
        # Timeout interaction should be recorded
        assert len(adapter.interactions) == 1
        assert adapter.interactions[0].response == {"error": "timeout"}

    async def test_send_and_wait_form_timeout(self) -> None:
        inner = _make_inner()

        async def hang(*_a: object, **_kw: object) -> dict[str, str]:
            await asyncio.sleep(999)
            return {}

        inner.send_and_wait_form = hang
        adapter = GuidedSlackAdapter(inner, run_id="r1", timeout=0.01)
        adapter.set_step("theme_generation")

        with pytest.raises(SlackTimeoutError) as exc_info:
            await adapter.send_and_wait_form("Pick", form_fields=[])

        assert exc_info.value.method == "send_and_wait_form"
        assert len(adapter.interactions) == 1
        assert adapter.interactions[0].response == {"error": "timeout"}

    async def test_send_and_wait_freetext_timeout(self) -> None:
        inner = _make_inner()

        async def hang(*_a: object, **_kw: object) -> str:
            await asyncio.sleep(999)
            return ""

        inner.send_and_wait_freetext = hang
        adapter = GuidedSlackAdapter(inner, run_id="r1", timeout=0.01)
        adapter.set_step("summarization")

        with pytest.raises(SlackTimeoutError) as exc_info:
            await adapter.send_and_wait_freetext("Feedback?")

        assert exc_info.value.method == "send_and_wait_freetext"
        assert len(adapter.interactions) == 1
        assert adapter.interactions[0].response == {"error": "timeout"}

    async def test_no_timeout_when_none(self) -> None:
        """With timeout=None, send_and_wait completes normally."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="r1", timeout=None)
        adapter.set_step("curation")

        await adapter.send_and_wait("#ch", "Ready?")

        assert len(adapter.interactions) == 1
        assert adapter.interactions[0].response == {"action": "approved"}

    async def test_successful_call_within_timeout(self) -> None:
        """Fast responses complete without timeout."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="r1", timeout=10.0)
        adapter.set_step("curation")

        await adapter.send_and_wait("#ch", "Ready?")

        assert len(adapter.interactions) == 1
        assert adapter.interactions[0].response == {"action": "approved"}


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class TestClassifyStepError:
    """_classify_step_error maps exceptions to descriptive messages."""

    def test_slack_timeout_error(self) -> None:
        err = SlackTimeoutError("send_and_wait", 300)
        msg = _classify_step_error(err)
        assert msg.startswith("Slack timeout:")
        assert "send_and_wait" in msg

    def test_generic_exception(self) -> None:
        err = ValueError("bad value")
        msg = _classify_step_error(err)
        assert msg == "ValueError: bad value"

    def test_slack_api_error_by_class_name(self) -> None:
        """Exceptions with 'Slack' in the class name get Slack API prefix."""

        class SlackApiError(Exception):
            pass

        err = SlackApiError("channel_not_found")
        msg = _classify_step_error(err)
        assert msg.startswith("Slack API error:")

    def test_runtime_error(self) -> None:
        err = RuntimeError("something broke")
        msg = _classify_step_error(err)
        assert msg == "RuntimeError: something broke"


# ---------------------------------------------------------------------------
# Timeout in run_guided integration
# ---------------------------------------------------------------------------


class TestRunGuidedWithTimeout:
    """Integration: slack_timeout applies to the adapter during guided runs."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    def _patch_steps(self):
        def _get_step(name: StepName) -> AsyncMock:
            async def step_fn(ctx: PipelineContext) -> PipelineContext:
                return ctx

            return AsyncMock(side_effect=step_fn)

        return patch("ica.guided.runner.get_step_fn", side_effect=_get_step)

    async def test_slack_timeout_applied_to_adapter(self, store_dir: Path) -> None:
        """slack_timeout is applied to the adapter's timeout property."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="timeout-test")
        console = MagicMock()
        assert adapter.timeout is None

        with (
            self._patch_steps(),
            patch("ica.services.slack.set_shared_service"),
            patch("ica.services.slack.get_shared_service", return_value=None),
        ):
            await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
                slack_timeout=120.0,
            )

        assert adapter.timeout == 120.0

    async def test_no_timeout_when_not_specified(self, store_dir: Path) -> None:
        """Without slack_timeout, adapter timeout remains None."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="no-timeout")
        console = MagicMock()

        with (
            self._patch_steps(),
            patch("ica.services.slack.set_shared_service"),
            patch("ica.services.slack.get_shared_service", return_value=None),
        ):
            await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
            )

        assert adapter.timeout is None

    async def test_timeout_step_failure_records_error(self, store_dir: Path) -> None:
        """SlackTimeoutError transitions step to FAILED with timeout message."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="timeout-fail", timeout=0.01)
        console = MagicMock()

        async def hanging_step(ctx: PipelineContext) -> PipelineContext:
            raise SlackTimeoutError("send_and_wait", 0.01)

        with (
            patch(
                "ica.guided.runner.get_step_fn",
                return_value=AsyncMock(side_effect=hanging_step),
            ),
            patch("ica.services.slack.set_shared_service"),
            patch("ica.services.slack.get_shared_service", return_value=None),
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
            )

        # First step should have failed with a timeout error
        assert state.steps[0].status == StepStatus.FAILED
        assert "timeout" in state.steps[0].error.lower()
        assert state.phase == RunPhase.ABORTED


# ---------------------------------------------------------------------------
# Redo replay-safety
# ---------------------------------------------------------------------------


class TestAttemptTracking:
    """Attempt number is tracked on interactions and message tags."""

    def test_default_attempt_is_one(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        assert adapter.current_attempt == 1

    def test_set_step_with_attempt(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation", attempt=3)
        assert adapter.current_step == "curation"
        assert adapter.current_attempt == 3

    def test_set_step_resets_attempt_default(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation", attempt=2)
        adapter.set_step("summarization")
        assert adapter.current_attempt == 1

    async def test_interaction_records_attempt(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation", attempt=2)

        await adapter.send_message("#ch", "Hello")

        assert adapter.interactions[0].attempt == 2

    async def test_tag_includes_attempt_when_gt_one(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="abc")
        adapter.set_step("theme_generation", attempt=2)

        await adapter.send_message("#ch", "Pick theme")

        inner.send_message.assert_awaited_once_with(
            "#ch", "[abc/theme_generation (attempt 2)] Pick theme"
        )

    async def test_tag_omits_attempt_when_one(self) -> None:
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="abc")
        adapter.set_step("curation", attempt=1)

        await adapter.send_message("#ch", "Hello")

        inner.send_message.assert_awaited_once_with("#ch", "[abc/curation] Hello")

    async def test_drain_includes_attempt_field(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation", attempt=2)
        await adapter.send_and_wait("#ch", "Go?")

        result = adapter.drain_step_interactions("curation")

        assert len(result) == 1
        assert result[0]["attempt"] == 2


class TestDrainActuallyDrains:
    """drain_step_interactions removes returned interactions from internal list."""

    async def test_drain_removes_interactions(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation")
        await adapter.send_message("#ch", "Hello")

        result = adapter.drain_step_interactions("curation")
        assert len(result) == 1

        # Second drain returns empty — already consumed
        result2 = adapter.drain_step_interactions("curation")
        assert result2 == []

    async def test_drain_preserves_other_steps(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        adapter.set_step("curation")
        await adapter.send_message("#ch", "Cur msg")
        adapter.set_step("summarization")
        await adapter.send_message("#ch", "Sum msg")

        # Drain only curation
        adapter.drain_step_interactions("curation")

        # Summarization interactions are still present
        assert len(adapter.step_interactions("summarization")) == 1
        assert len(adapter.interactions) == 1

    async def test_drain_across_redo_attempts(self) -> None:
        """Simulate redo: drain attempt 1, then record attempt 2, drain again."""
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")

        # Attempt 1
        adapter.set_step("curation", attempt=1)
        await adapter.send_and_wait("#ch", "Go?")
        first = adapter.drain_step_interactions("curation")
        assert len(first) == 1
        assert first[0]["attempt"] == 1

        # Attempt 2
        adapter.set_step("curation", attempt=2)
        await adapter.send_and_wait("#ch", "Go again?")
        second = adapter.drain_step_interactions("curation")
        assert len(second) == 1
        assert second[0]["attempt"] == 2


class TestInvalidatePending:
    """invalidate_pending clears stale callbacks from the inner service."""

    def test_clears_pending_dict(self) -> None:
        inner = _make_inner()
        inner.pending = {"cb-123": MagicMock(), "cb-456": MagicMock()}
        adapter = GuidedSlackAdapter(inner, run_id="r1")

        count = adapter.invalidate_pending()

        assert count == 2
        assert inner.pending == {}

    def test_noop_when_no_pending(self) -> None:
        inner = _make_inner()
        inner.pending = {}
        adapter = GuidedSlackAdapter(inner, run_id="r1")

        count = adapter.invalidate_pending()

        assert count == 0


class TestMergeAccumulatesAcrossRedo:
    """_merge_slack_interactions accumulates interactions across redo attempts."""

    def _make_state_at_step(self, step_index: int = 0) -> TestRunState:
        state = TestRunState(run_id="r1")
        state.current_step_index = step_index
        state.steps[step_index].status = StepStatus.COMPLETED
        return state

    async def test_merge_accumulates_on_redo(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        state = self._make_state_at_step(0)

        # Attempt 1
        adapter.set_step("curation", attempt=1)
        await adapter.send_and_wait("#ch", "Ready?")
        _merge_slack_interactions(adapter, StepName.CURATION, state)
        assert len(state.steps[0].artifacts["slack_interactions"]) == 1

        # Attempt 2
        adapter.set_step("curation", attempt=2)
        await adapter.send_and_wait("#ch", "Ready again?")
        _merge_slack_interactions(adapter, StepName.CURATION, state)

        # Both attempts' interactions should be present
        interactions = state.steps[0].artifacts["slack_interactions"]
        assert len(interactions) == 2
        assert interactions[0]["attempt"] == 1
        assert interactions[1]["attempt"] == 2

    async def test_decisions_accumulate_across_redo(self) -> None:
        adapter = GuidedSlackAdapter(_make_inner(), run_id="r1")
        state = self._make_state_at_step(0)

        # Attempt 1
        adapter.set_step("curation", attempt=1)
        await adapter.send_and_wait("#ch", "Ready?")
        _merge_slack_interactions(adapter, StepName.CURATION, state)
        assert len(state.decisions) == 1

        # Attempt 2
        adapter.set_step("curation", attempt=2)
        await adapter.send_and_wait("#ch", "Ready again?")
        _merge_slack_interactions(adapter, StepName.CURATION, state)

        # Both decisions preserved
        assert len(state.decisions) == 2
        assert state.decisions[0].action == "slack:send_and_wait"
        assert state.decisions[1].action == "slack:send_and_wait"


class TestRedoReplayIntegration:
    """Integration: redo sends new message with attempt tag and preserves history."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with patch("ica.guided.runner.validate_google_settings"):
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    def _patch_steps(self):
        def _get_step(name: StepName) -> AsyncMock:
            async def step_fn(ctx: PipelineContext) -> PipelineContext:
                return ctx

            return AsyncMock(side_effect=step_fn)

        return patch("ica.guided.runner.get_step_fn", side_effect=_get_step)

    async def test_redo_passes_incremented_attempt(self, store_dir: Path) -> None:
        """On redo, set_step receives attempt=2."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="redo-test")
        console = MagicMock()
        attempts_seen: list[int] = []
        original_set_step = adapter.set_step

        def tracking_set_step(name: str, *, attempt: int = 1) -> None:
            attempts_seen.append(attempt)
            original_set_step(name, attempt=attempt)

        adapter.set_step = tracking_set_step  # type: ignore[method-assign]

        # Redo first step, then stop
        inputs = iter(["r", "s"])

        with (
            self._patch_steps(),
            patch("ica.services.slack.set_shared_service"),
            patch("ica.services.slack.get_shared_service", return_value=None),
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
                slack_override=adapter,
            )

        assert state.steps[0].attempt == 2
        assert attempts_seen == [1, 2]

    async def test_redo_invalidates_pending_callbacks(self, store_dir: Path) -> None:
        """On redo, invalidate_pending is called to clear stale callbacks."""
        inner = _make_inner()
        adapter = GuidedSlackAdapter(inner, run_id="inv-test")
        console = MagicMock()
        invalidate_calls: list[bool] = []
        original_invalidate = adapter.invalidate_pending

        def tracking_invalidate() -> int:
            invalidate_calls.append(True)
            return original_invalidate()

        adapter.invalidate_pending = tracking_invalidate  # type: ignore[method-assign]

        # Redo first step, then stop
        inputs = iter(["r", "s"])

        with (
            self._patch_steps(),
            patch("ica.services.slack.set_shared_service"),
            patch("ica.services.slack.get_shared_service", return_value=None),
        ):
            await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
                slack_override=adapter,
            )

        # invalidate_pending should have been called on the redo (attempt 2)
        assert len(invalidate_calls) == 1
