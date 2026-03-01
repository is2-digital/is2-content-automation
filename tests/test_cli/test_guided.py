"""Tests for the ``ica guided`` CLI command."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from ica.__main__ import app
from ica.guided.state import RunPhase, TestRunState

runner = CliRunner()


# ---------------------------------------------------------------------------
# Help / listing
# ---------------------------------------------------------------------------


class TestGuidedHelp:
    """The guided command appears in help and has expected options."""

    def test_guided_in_app_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "guided" in result.output

    def test_guided_help_flag(self) -> None:
        result = runner.invoke(app, ["guided", "--help"])
        assert result.exit_code == 0
        assert "--run-id" in result.output
        assert "--store-dir" in result.output
        assert "--list" in result.output

    def test_guided_list_empty(self) -> None:
        with patch("ica.guided.state.TestRunStore") as mock_store:
            mock_store.return_value.list_runs.return_value = []
            result = runner.invoke(app, ["guided", "--list"])

        assert result.exit_code == 0
        assert "No guided runs" in result.output

    def test_guided_list_with_runs(self) -> None:
        state = TestRunState(run_id="abc123")
        state.phase = RunPhase.CHECKPOINT

        with patch("ica.guided.state.TestRunStore") as mock_store:
            store_inst = mock_store.return_value
            store_inst.list_runs.return_value = ["abc123"]
            store_inst.load.return_value = state
            result = runner.invoke(app, ["guided", "--list"])

        assert result.exit_code == 0
        assert "abc123" in result.output
        assert "checkpoint" in result.output


# ---------------------------------------------------------------------------
# Guided run
# ---------------------------------------------------------------------------


class TestGuidedRun:
    """The guided command delegates to run_guided."""

    def test_guided_completes(self) -> None:
        state = TestRunState(run_id="test-run")
        state.phase = RunPhase.COMPLETED

        with patch("ica.guided.runner.run_guided", AsyncMock(return_value=state)):
            result = runner.invoke(app, ["guided"])

        assert result.exit_code == 0

    def test_guided_aborted(self) -> None:
        state = TestRunState(run_id="test-run")
        state.phase = RunPhase.ABORTED

        with patch("ica.guided.runner.run_guided", AsyncMock(return_value=state)):
            result = runner.invoke(app, ["guided"])

        assert result.exit_code == 0

    def test_guided_with_run_id(self) -> None:
        state = TestRunState(run_id="existing")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(app, ["guided", "--run-id", "existing"])

        assert result.exit_code == 0
        # Verify run_id was passed through
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["run_id"] == "existing"

    def test_guided_with_custom_store_dir(self) -> None:
        state = TestRunState(run_id="test")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(
                app,
                ["guided", "--store-dir", "/tmp/claude-1000/my-runs"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert str(call_kwargs["store_dir"]) == "/tmp/claude-1000/my-runs"

    def test_guided_error_exits_with_code_1(self) -> None:
        with patch(
            "ica.guided.runner.run_guided",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            result = runner.invoke(app, ["guided"])

        assert result.exit_code == 1
        assert "Guided run failed" in result.output


# ---------------------------------------------------------------------------
# --slack-timeout flag
# ---------------------------------------------------------------------------


class TestGuidedSlackTimeout:
    """The --slack-timeout flag controls Slack send-and-wait timeout."""

    def test_default_timeout_300(self) -> None:
        """Default --slack-timeout is 300s, passed as slack_timeout to run_guided."""
        state = TestRunState(run_id="test")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(app, ["guided"])

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["slack_timeout"] == 300.0

    def test_custom_timeout(self) -> None:
        """Custom --slack-timeout value is forwarded."""
        state = TestRunState(run_id="test")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(app, ["guided", "--slack-timeout", "60"])

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["slack_timeout"] == 60.0

    def test_zero_timeout_means_no_timeout(self) -> None:
        """--slack-timeout 0 maps to None (no timeout)."""
        state = TestRunState(run_id="test")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(app, ["guided", "--slack-timeout", "0"])

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["slack_timeout"] is None

    def test_slack_timeout_in_help(self) -> None:
        """--slack-timeout appears in the guided command help."""
        result = runner.invoke(app, ["guided", "--help"])
        assert "--slack-timeout" in result.output


# ---------------------------------------------------------------------------
# --template-version / --template-name flags
# ---------------------------------------------------------------------------


class TestGuidedTemplateFlags:
    """The --template-version and --template-name flags control HTML template pinning."""

    def test_default_template_name(self) -> None:
        """Default --template-name is 'default'."""
        state = TestRunState(run_id="test")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(app, ["guided"])

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["template_name"] == "default"
        assert call_kwargs["template_version"] is None

    def test_custom_template_name(self) -> None:
        """Custom --template-name is forwarded."""
        state = TestRunState(run_id="test")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(
                app, ["guided", "--template-name", "weekly"]
            )

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["template_name"] == "weekly"

    def test_template_version_forwarded(self) -> None:
        """--template-version is forwarded to run_guided."""
        state = TestRunState(run_id="test")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(
                app, ["guided", "--template-version", "2.0.0"]
            )

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["template_version"] == "2.0.0"

    def test_both_flags_together(self) -> None:
        """--template-name and --template-version can be combined."""
        state = TestRunState(run_id="test")
        state.phase = RunPhase.COMPLETED

        mock_run = AsyncMock(return_value=state)
        with patch("ica.guided.runner.run_guided", mock_run):
            result = runner.invoke(
                app,
                ["guided", "--template-name", "weekly", "--template-version", "1.0.0"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["template_name"] == "weekly"
        assert call_kwargs["template_version"] == "1.0.0"

    def test_template_flags_in_help(self) -> None:
        """--template-version and --template-name appear in help."""
        result = runner.invoke(app, ["guided", "--help"])
        assert "--template-version" in result.output
        assert "--template-name" in result.output
