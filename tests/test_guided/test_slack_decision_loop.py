"""Integration tests for a full Slack send-and-wait decision loop in guided mode.

Exercises the complete cycle: send prompt -> receive response -> record in
state -> checkpoint -> operator continues.  Covers redo with incremented
attempt, timeout triggering fail_step, and decision history completeness
after multiple interactions.

Ref: ica-476.3.4
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.guided.runner import run_guided
from ica.guided.slack_adapter import GuidedSlackAdapter
from ica.guided.state import StepStatus
from ica.pipeline.orchestrator import PipelineContext

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


def _make_adapter(
    inner: MagicMock | None = None,
    *,
    run_id: str = "loop-test",
    timeout: float | None = None,
) -> GuidedSlackAdapter:
    if inner is None:
        inner = _make_inner()
    return GuidedSlackAdapter(inner, run_id=run_id, timeout=timeout)


def _patch_google_validation():
    return patch("ica.guided.runner.validate_google_settings")


def _patch_shared_service():
    """Patch set/get shared service to avoid touching the real singleton."""
    return (
        patch("ica.services.slack.set_shared_service"),
        patch("ica.services.slack.get_shared_service", return_value=None),
    )


def _make_step_that_calls_slack(
    adapter: GuidedSlackAdapter,
    *,
    method: str = "send_and_wait",
    message: str = "Ready to proceed?",
    channel: str = "#test-channel",
) -> AsyncMock:
    """Create a pipeline step that uses the adapter for a Slack interaction.

    The step function calls the appropriate adapter method so interactions
    are recorded in the adapter's internal log — exactly as a real pipeline
    step would do via the shared service.
    """

    async def step_fn(ctx: PipelineContext) -> PipelineContext:
        if method == "send_and_wait":
            await adapter.send_and_wait(channel, message)
        elif method == "send_and_wait_form":
            await adapter.send_and_wait_form(message, form_fields=[])
        elif method == "send_and_wait_freetext":
            await adapter.send_and_wait_freetext(message)
        return ctx

    return AsyncMock(side_effect=step_fn)


# ---------------------------------------------------------------------------
# Full decision loop — send → response → artifacts → checkpoint → continue
# ---------------------------------------------------------------------------


class TestFullDecisionLoop:
    """End-to-end: step calls Slack, response lands in artifacts & decisions."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with _patch_google_validation():
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_send_and_wait_captured_in_artifacts(self, store_dir: Path) -> None:
        """A step that calls send_and_wait has its interaction merged into
        step artifacts and the run's decision history."""
        inner = _make_inner()
        adapter = _make_adapter(inner, run_id="full-loop")
        step_fn = _make_step_that_calls_slack(adapter, method="send_and_wait")
        console = MagicMock()

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",  # stop after first step
                slack_override=adapter,
            )

        # Step completed
        assert state.steps[0].status == StepStatus.COMPLETED

        # (1) Slack interactions are captured in artifacts
        interactions = state.steps[0].artifacts.get("slack_interactions", [])
        assert len(interactions) == 1
        assert interactions[0]["method"] == "send_and_wait"
        assert interactions[0]["response"] == {"action": "approved"}

        # (1) Message includes run_id/step metadata
        inner.send_and_wait.assert_awaited_once()
        tagged_msg = inner.send_and_wait.call_args[0][1]
        assert "[full-loop/curation]" in tagged_msg

        # (2) Decision history includes the Slack interaction
        slack_decisions = [d for d in state.decisions if d.action.startswith("slack:")]
        assert len(slack_decisions) == 1
        assert slack_decisions[0].step == "curation"
        assert slack_decisions[0].action == "slack:send_and_wait"

    async def test_form_response_captured_in_artifacts(self, store_dir: Path) -> None:
        """send_and_wait_form response (dict) lands in artifacts."""
        adapter = _make_adapter(run_id="form-loop")
        step_fn = _make_step_that_calls_slack(adapter, method="send_and_wait_form")
        console = MagicMock()

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
            )

        interactions = state.steps[0].artifacts.get("slack_interactions", [])
        assert len(interactions) == 1
        assert interactions[0]["method"] == "send_and_wait_form"
        assert interactions[0]["response"] == {"Theme": "AI Today"}

    async def test_freetext_response_captured_in_artifacts(
        self, store_dir: Path
    ) -> None:
        """send_and_wait_freetext response (str) lands in artifacts."""
        adapter = _make_adapter(run_id="freetext-loop")
        step_fn = _make_step_that_calls_slack(adapter, method="send_and_wait_freetext")
        console = MagicMock()

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
            )

        interactions = state.steps[0].artifacts.get("slack_interactions", [])
        assert len(interactions) == 1
        assert interactions[0]["method"] == "send_and_wait_freetext"
        assert interactions[0]["response"] == "Looks good"


# ---------------------------------------------------------------------------
# Redo sends a new message with incremented attempt
# ---------------------------------------------------------------------------


class TestRedoNewMessageWithAttempt:
    """On redo, the adapter sends a fresh message tagged with the new attempt."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with _patch_google_validation():
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_redo_sends_attempt_tagged_message(self, store_dir: Path) -> None:
        """Redo sends a new Slack message with (attempt 2) in the tag."""
        inner = _make_inner()
        adapter = _make_adapter(inner, run_id="redo-msg")
        step_fn = _make_step_that_calls_slack(
            adapter, method="send_and_wait", message="Continue?"
        )
        console = MagicMock()
        inputs = iter(["r", "s"])  # redo first step, then stop

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
                slack_override=adapter,
            )

        # Step was executed twice (attempt 1 + redo attempt 2)
        assert state.steps[0].attempt == 2

        # Inner service received two calls to send_and_wait
        assert inner.send_and_wait.await_count == 2

        # First call: no attempt tag
        first_msg = inner.send_and_wait.call_args_list[0][0][1]
        assert "[redo-msg/curation]" in first_msg
        assert "(attempt" not in first_msg

        # Second call: includes attempt 2 tag
        second_msg = inner.send_and_wait.call_args_list[1][0][1]
        assert "[redo-msg/curation (attempt 2)]" in second_msg

    async def test_redo_interactions_accumulated_in_artifacts(
        self, store_dir: Path
    ) -> None:
        """After redo, artifacts contain interactions from both attempts."""
        adapter = _make_adapter(run_id="redo-acc")
        step_fn = _make_step_that_calls_slack(adapter, method="send_and_wait")
        console = MagicMock()
        inputs = iter(["r", "s"])

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
                slack_override=adapter,
            )

        # Artifact history should contain attempt 1's artifacts
        assert len(state.steps[0].artifact_history) == 1
        assert state.steps[0].artifact_history[0]["attempt"] == 1

        # Current artifacts should have attempt 2 interactions
        interactions = state.steps[0].artifacts.get("slack_interactions", [])
        assert len(interactions) >= 1
        assert interactions[0]["attempt"] == 2


# ---------------------------------------------------------------------------
# Timeout triggers fail_step
# ---------------------------------------------------------------------------


class TestTimeoutTriggersFailStep:
    """A Slack timeout during a step marks it as FAILED."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with _patch_google_validation():
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_timeout_in_step_records_failure(self, store_dir: Path) -> None:
        """SlackTimeoutError from a step becomes fail_step with timeout error."""
        inner = _make_inner()

        async def hang(*_a: object, **_kw: object) -> None:
            await asyncio.sleep(999)

        inner.send_and_wait = hang
        adapter = _make_adapter(inner, run_id="timeout-flow", timeout=0.01)

        step_fn = _make_step_that_calls_slack(adapter, method="send_and_wait")
        console = MagicMock()

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",  # stop after failure
                slack_override=adapter,
            )

        assert state.steps[0].status == StepStatus.FAILED
        assert "timeout" in state.steps[0].error.lower()

        # Timeout interaction recorded with error response
        interactions = state.steps[0].artifacts.get("slack_interactions", [])
        assert len(interactions) == 1
        assert interactions[0]["response"] == {"error": "timeout"}

    async def test_timeout_then_redo_succeeds(self, store_dir: Path) -> None:
        """After a timeout-caused failure, redo with a working step succeeds."""
        inner = _make_inner()
        call_count = 0

        async def hang_then_succeed(*_a: object, **_kw: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(999)  # Will timeout

        inner.send_and_wait = hang_then_succeed
        adapter = _make_adapter(inner, run_id="timeout-redo", timeout=0.01)
        step_fn = _make_step_that_calls_slack(adapter, method="send_and_wait")
        console = MagicMock()
        inputs = iter(["r", "s"])  # redo after failure, then stop

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
                slack_override=adapter,
            )

        # Step should be completed on attempt 2
        assert state.steps[0].status == StepStatus.COMPLETED
        assert state.steps[0].attempt == 2

        # Artifact history contains the failed attempt 1
        assert len(state.steps[0].artifact_history) == 1
        history_arts = state.steps[0].artifact_history[0]["artifacts"]
        timeout_interactions = history_arts.get("slack_interactions", [])
        assert any(i["response"] == {"error": "timeout"} for i in timeout_interactions)


# ---------------------------------------------------------------------------
# Decision history completeness after multiple interactions
# ---------------------------------------------------------------------------


class TestDecisionHistoryCompleteness:
    """Decision history preserves all Slack interactions across steps and redos."""

    @pytest.fixture(autouse=True)
    def _skip_google_validation(self):
        with _patch_google_validation():
            yield

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "guided-runs"

    async def test_decisions_span_two_steps(self, store_dir: Path) -> None:
        """Decisions from Slack interactions in step 1 and step 2 are both recorded."""
        adapter = _make_adapter(run_id="multi-step")
        step_fn = _make_step_that_calls_slack(adapter, method="send_and_wait")
        console = MagicMock()
        inputs = iter(["c", "s"])  # continue past step 1, stop after step 2

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
                slack_override=adapter,
            )

        # Both steps completed
        assert state.steps[0].status == StepStatus.COMPLETED
        assert state.steps[1].status == StepStatus.COMPLETED

        # Decision history should have both Slack interactions
        slack_decisions = [d for d in state.decisions if d.action.startswith("slack:")]
        assert len(slack_decisions) == 2
        assert slack_decisions[0].step == "curation"
        assert slack_decisions[1].step == "summarization"

        # Plus the two operator checkpoint decisions (continue + stop)
        operator_decisions = [
            d for d in state.decisions if not d.action.startswith("slack:")
        ]
        assert len(operator_decisions) == 2

    async def test_decisions_after_redo_include_all_attempts(
        self, store_dir: Path
    ) -> None:
        """Redo produces decisions from both attempt 1 and attempt 2."""
        adapter = _make_adapter(run_id="redo-hist")
        step_fn = _make_step_that_calls_slack(adapter, method="send_and_wait")
        console = MagicMock()
        inputs = iter(["r", "s"])  # redo step 1, then stop

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
                slack_override=adapter,
            )

        # Slack decisions from both attempts
        slack_decisions = [d for d in state.decisions if d.action.startswith("slack:")]
        assert len(slack_decisions) == 2
        assert all(d.step == "curation" for d in slack_decisions)
        assert all(d.action == "slack:send_and_wait" for d in slack_decisions)

    async def test_mixed_interaction_types_in_decision_history(
        self, store_dir: Path
    ) -> None:
        """Steps using different Slack methods all generate decisions."""
        inner = _make_inner()
        adapter = _make_adapter(inner, run_id="mixed-methods")
        call_count = 0

        async def mixed_step(ctx: PipelineContext) -> PipelineContext:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await adapter.send_and_wait("#ch", "Approve?")
            elif call_count == 2:
                await adapter.send_and_wait_form("Pick theme", form_fields=[])
            return ctx

        step_fn = AsyncMock(side_effect=mixed_step)
        console = MagicMock()
        inputs = iter(["c", "s"])

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: next(inputs),
                slack_override=adapter,
            )

        slack_decisions = [d for d in state.decisions if d.action.startswith("slack:")]
        assert len(slack_decisions) == 2
        methods = {d.action for d in slack_decisions}
        assert methods == {"slack:send_and_wait", "slack:send_and_wait_form"}

    async def test_non_interactive_messages_excluded_from_decisions(
        self, store_dir: Path
    ) -> None:
        """send_message (non-interactive) is in artifacts but NOT in decisions."""
        inner = _make_inner()
        adapter = _make_adapter(inner, run_id="non-interactive")

        async def notification_step(ctx: PipelineContext) -> PipelineContext:
            await adapter.send_message("#ch", "Processing...")
            await adapter.send_and_wait("#ch", "Ready?")
            return ctx

        step_fn = AsyncMock(side_effect=notification_step)
        console = MagicMock()

        set_svc, get_svc = _patch_shared_service()
        with (
            patch("ica.guided.runner.get_step_fn", return_value=step_fn),
            set_svc,
            get_svc,
        ):
            state = await run_guided(
                store_dir=store_dir,
                console=console,
                prompt_fn=lambda _: "s",
                slack_override=adapter,
            )

        # Both interactions in artifacts
        interactions = state.steps[0].artifacts.get("slack_interactions", [])
        assert len(interactions) == 2

        # Only the interactive one generates a decision
        slack_decisions = [d for d in state.decisions if d.action.startswith("slack:")]
        assert len(slack_decisions) == 1
        assert slack_decisions[0].action == "slack:send_and_wait"
