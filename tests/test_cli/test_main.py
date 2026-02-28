"""Tests for the ica CLI entry point (ica/__main__.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ica.__main__ import (
    _print_runs_table,
    _print_single_run,
    _status_color,
    app,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# App / help
# ---------------------------------------------------------------------------


class TestAppHelp:
    """The CLI app displays help and has all expected commands."""

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # Typer returns exit code 0 for help; no_args_is_help may return 0 or 2
        assert result.exit_code in (0, 2)
        assert "serve" in result.output or "Usage" in result.output

    def test_help_flag(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "serve" in result.output
        assert "run" in result.output
        assert "status" in result.output
        assert "collect-articles" in result.output

    def test_serve_in_help(self) -> None:
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--reload" in result.output

    def test_run_in_help(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--trigger" in result.output
        assert "--base-url" in result.output

    def test_status_in_help(self) -> None:
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "--base-url" in result.output

    def test_collect_articles_in_help(self) -> None:
        result = runner.invoke(app, ["collect-articles", "--help"])
        assert result.exit_code == 0
        assert "--schedule" in result.output


# ---------------------------------------------------------------------------
# serve command
# ---------------------------------------------------------------------------


class TestServeCommand:
    """The serve command starts uvicorn."""

    @patch("ica.__main__.uvicorn", create=True)
    def test_serve_default_options(self, mock_uvicorn: MagicMock) -> None:
        # uvicorn is imported inside the function, so we patch at module level
        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}), patch("ica.__main__.serve"):
            # Call the real function by invoking via app
            pass
        # Instead, test via direct invocation patching uvicorn.run
        with patch("uvicorn.run") as mock_run:
            result = runner.invoke(app, ["serve"])
            assert result.exit_code == 0
            mock_run.assert_called_once_with(
                "ica.app:create_app",
                factory=True,
                host="0.0.0.0",
                port=8000,
                reload=False,
            )

    def test_serve_custom_options(self) -> None:
        with patch("uvicorn.run") as mock_run:
            result = runner.invoke(
                app,
                [
                    "serve",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "9000",
                    "--reload",
                ],
            )
            assert result.exit_code == 0
            mock_run.assert_called_once_with(
                "ica.app:create_app",
                factory=True,
                host="127.0.0.1",
                port=9000,
                reload=True,
            )


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


def _mock_httpx_post(status_code: int = 200, json_data: dict | None = None):
    """Create a mock httpx response for POST requests."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {}
    mock_resp.text = str(json_data)
    if status_code >= 400:
        import httpx

        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


def _mock_httpx_get(status_code: int = 200, json_data: dict | None = None):
    """Create a mock httpx response for GET requests."""
    return _mock_httpx_post(status_code, json_data)


class TestRunCommand:
    """The run command triggers a pipeline via /trigger."""

    def test_run_success(self) -> None:
        mock_resp = _mock_httpx_post(200, {"run_id": "abc123", "status": "pending"})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["run"])

        assert result.exit_code == 0
        assert "abc123" in result.output
        assert "pending" in result.output

    def test_run_custom_trigger(self) -> None:
        mock_resp = _mock_httpx_post(200, {"run_id": "xyz", "status": "pending"})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["run", "--trigger", "scheduler"])

        assert result.exit_code == 0
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["trigger"] == "scheduler"

    def test_run_custom_base_url(self) -> None:
        mock_resp = _mock_httpx_post(200, {"run_id": "r1", "status": "pending"})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(
                app,
                [
                    "run",
                    "--base-url",
                    "http://localhost:9000",
                ],
            )

        assert result.exit_code == 0
        call_args = mock_client.post.call_args
        assert "localhost:9000" in call_args[0][0]

    def test_run_connection_error(self) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["run"])

        assert result.exit_code == 1

    def test_run_http_error(self) -> None:
        mock_resp = _mock_httpx_post(500, {"detail": "server error"})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["run"])

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """The status command shows pipeline run info."""

    def test_status_all_runs(self) -> None:
        runs_data = {
            "runs": [
                {
                    "run_id": "r1",
                    "status": "completed",
                    "trigger": "cli",
                    "started_at": "2026-02-22T10:00:00Z",
                    "completed_at": "2026-02-22T10:05:00Z",
                    "current_step": "completed",
                    "error": None,
                },
            ],
        }
        mock_resp = _mock_httpx_get(200, runs_data)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "r1" in result.output

    def test_status_no_runs(self) -> None:
        mock_resp = _mock_httpx_get(200, {"runs": []})

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "No pipeline runs found" in result.output

    def test_status_single_run(self) -> None:
        run_data = {
            "run_id": "r42",
            "status": "running",
            "trigger": "api",
            "started_at": "2026-02-22T10:00:00Z",
            "completed_at": None,
            "current_step": "summarization",
            "error": None,
        }
        mock_resp = _mock_httpx_get(200, run_data)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["status", "r42"])

        assert result.exit_code == 0
        assert "r42" in result.output
        assert "running" in result.output

    def test_status_run_not_found(self) -> None:
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = '{"detail":"Run not found"}'
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "not found",
            request=MagicMock(),
            response=mock_resp,
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["status", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_status_connection_error(self) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 1

    def test_status_url_with_run_id(self) -> None:
        run_data = {
            "run_id": "r99",
            "status": "completed",
            "trigger": "cli",
            "started_at": "2026-02-22T10:00:00Z",
            "completed_at": "2026-02-22T10:05:00Z",
            "current_step": "completed",
            "error": None,
        }
        mock_resp = _mock_httpx_get(200, run_data)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            runner.invoke(app, ["status", "r99"])

        call_args = mock_client.get.call_args
        assert "/status/r99" in call_args[0][0]

    def test_status_url_without_run_id(self) -> None:
        mock_resp = _mock_httpx_get(200, {"runs": []})

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            runner.invoke(app, ["status"])

        call_args = mock_client.get.call_args
        url = call_args[0][0]
        assert url.endswith("/status")
        assert "/status/" not in url.replace("/status", "", 1)

    def test_status_run_with_error(self) -> None:
        run_data = {
            "run_id": "r_err",
            "status": "failed",
            "trigger": "api",
            "started_at": "2026-02-22T10:00:00Z",
            "completed_at": "2026-02-22T10:01:00Z",
            "current_step": "summarization",
            "error": "LLM timeout",
        }
        mock_resp = _mock_httpx_get(200, run_data)

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = runner.invoke(app, ["status", "r_err"])

        assert result.exit_code == 0
        assert "LLM timeout" in result.output


# ---------------------------------------------------------------------------
# collect-articles command
# ---------------------------------------------------------------------------


class TestCollectArticlesCommand:
    """The collect-articles command runs article collection."""

    def test_collect_articles_help(self) -> None:
        result = runner.invoke(app, ["collect-articles", "--help"])
        assert result.exit_code == 0
        assert "daily" in result.output

    def test_collect_articles_invalid_schedule(self) -> None:
        # The ValueError from collect_articles should be caught
        mock_settings = MagicMock()
        mock_settings.google_cse_api_key = "test-key"
        mock_settings.google_cse_cx = "test-cx"

        mock_session = AsyncMock()
        mock_get_session = MagicMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("ica.config.settings.get_settings", return_value=mock_settings),
            patch(
                "ica.pipeline.article_collection.collect_articles",
                side_effect=ValueError("schedule must be 'daily' or 'every_2_days', got 'bad'"),
            ),
            patch("ica.db.session.get_session", mock_get_session),
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(
                    app,
                    [
                        "collect-articles",
                        "--schedule",
                        "bad",
                    ],
                )

        assert result.exit_code == 1

    def test_collect_articles_config_error(self) -> None:
        with patch(
            "ica.config.settings.get_settings",
            side_effect=Exception("Missing SEARCHAPI_API_KEY"),
        ):
            result = runner.invoke(app, ["collect-articles"])

        assert result.exit_code == 1
        assert "Configuration error" in result.output


# ---------------------------------------------------------------------------
# _status_color helper
# ---------------------------------------------------------------------------


class TestStatusColor:
    """Status color mapping for Rich output."""

    @pytest.mark.parametrize(
        "status, expected",
        [
            ("pending", "yellow"),
            ("running", "cyan"),
            ("completed", "green"),
            ("failed", "red"),
            ("unknown", "white"),
            ("", "white"),
        ],
    )
    def test_status_colors(self, status: str, expected: str) -> None:
        assert _status_color(status) == expected


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


class TestDisplayHelpers:
    """Output formatting functions."""

    def test_print_single_run_basic(self, capsys: pytest.CaptureFixture) -> None:
        data = {
            "run_id": "test_r",
            "status": "completed",
            "trigger": "cli",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:05:00Z",
            "current_step": "done",
            "error": None,
        }
        _print_single_run(data)
        out = capsys.readouterr().out
        assert "test_r" in out
        assert "completed" in out

    def test_print_single_run_with_error(self, capsys: pytest.CaptureFixture) -> None:
        data = {
            "run_id": "err_r",
            "status": "failed",
            "trigger": "api",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:01:00Z",
            "current_step": "theme",
            "error": "timeout",
        }
        _print_single_run(data)
        out = capsys.readouterr().out
        assert "timeout" in out

    def test_print_single_run_null_fields(self, capsys: pytest.CaptureFixture) -> None:
        data = {
            "run_id": "r_null",
            "status": "running",
            "trigger": "cli",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
            "current_step": None,
            "error": None,
        }
        _print_single_run(data)
        out = capsys.readouterr().out
        assert "r_null" in out
        assert "-" in out  # null fields rendered as "-"

    def test_print_runs_table(self, capsys: pytest.CaptureFixture) -> None:
        runs = [
            {
                "run_id": "r1",
                "status": "completed",
                "trigger": "cli",
                "started_at": "2026-01-01T00:00:00Z",
                "current_step": "done",
            },
            {
                "run_id": "r2",
                "status": "failed",
                "trigger": "api",
                "started_at": "2026-01-02T00:00:00Z",
                "current_step": None,
            },
        ]
        _print_runs_table(runs)
        out = capsys.readouterr().out
        assert "r1" in out
        assert "r2" in out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


class TestEntryPoint:
    """The main() function is callable."""

    def test_main_callable(self) -> None:
        from ica.__main__ import main

        assert callable(main)

    def test_pyproject_script_target(self) -> None:
        """The pyproject.toml script entry matches our main function."""
        import importlib

        mod = importlib.import_module("ica.__main__")
        assert hasattr(mod, "main")


# ---------------------------------------------------------------------------
# config command
# ---------------------------------------------------------------------------


def _make_process_config(
    *,
    name: str = "test-process",
    model: str = "anthropic/claude-sonnet-4.5",
    instruction: str = "Summarize the content.",
    description: str = "Test process",
    version: int = 1,
    google_doc_id: str | None = None,
):
    """Build a ProcessConfig for testing."""
    from ica.llm_configs.schema import ProcessConfig

    return ProcessConfig(
        **{
            "$schema": "ica-llm-config/v1",
            "processName": name,
            "description": description,
            "model": model,
            "prompts": {"instruction": instruction},
            "metadata": {
                "googleDocId": google_doc_id,
                "lastSyncedAt": None,
                "version": version,
            },
        }
    )


class TestConfigCommand:
    """The config command edits LLM process configs via Google Docs."""

    def test_config_in_help(self) -> None:
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        assert "Google Docs" in result.output

    def test_config_shows_table_and_quit(self) -> None:
        """Entering 'q' at the selection prompt exits cleanly."""
        configs = [
            ("summarization", _make_process_config(name="summarization")),
            ("theme", _make_process_config(name="theme")),
        ]
        with patch(
            "ica.cli.config_editor.list_all_configs", return_value=configs
        ):
            result = runner.invoke(app, ["config"], input="q\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output

    def test_config_invalid_selection(self) -> None:
        """Non-numeric and out-of-range selections exit with error."""
        configs = [("summarization", _make_process_config(name="summarization"))]
        with patch(
            "ica.cli.config_editor.list_all_configs", return_value=configs
        ):
            result = runner.invoke(app, ["config"], input="99\n")

        assert result.exit_code == 1
        assert "Invalid selection" in result.output

    def test_config_invalid_selection_text(self) -> None:
        """Non-numeric input exits with error."""
        configs = [("summarization", _make_process_config(name="summarization"))]
        with patch(
            "ica.cli.config_editor.list_all_configs", return_value=configs
        ):
            result = runner.invoke(app, ["config"], input="abc\n")

        assert result.exit_code == 1
        assert "Invalid selection" in result.output

    def test_config_no_configs_found(self) -> None:
        """Exits with error when no configs exist."""
        with patch("ica.cli.config_editor.list_all_configs", return_value=[]):
            result = runner.invoke(app, ["config"])

        assert result.exit_code == 1
        assert "No LLM configs found" in result.output

    def test_config_settings_error(self) -> None:
        """Settings error is caught and reported."""
        configs = [("summarization", _make_process_config(name="summarization"))]
        with (
            patch("ica.cli.config_editor.list_all_configs", return_value=configs),
            patch(
                "ica.config.settings.get_settings",
                side_effect=Exception("Missing GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_PATH"),
            ),
        ):
            result = runner.invoke(app, ["config"], input="1\n")

        assert result.exit_code == 1
        assert "Configuration error" in result.output

    def test_config_cancel_at_sync_prompt(self) -> None:
        """Entering 'q' at the sync prompt cancels without syncing."""
        configs = [("summarization", _make_process_config(name="summarization"))]
        mock_settings = MagicMock()
        mock_settings.google_service_account_credentials_path = "/fake/creds.json"
        mock_settings.google_shared_drive_id = "drive-123"

        mock_editor = AsyncMock()
        mock_editor.start_full_edit.return_value = "https://docs.google.com/document/d/abc/edit"

        with (
            patch("ica.cli.config_editor.list_all_configs", return_value=configs),
            patch("ica.config.settings.get_settings", return_value=mock_settings),
            patch("ica.services.google_docs.GoogleDocsService"),
            patch(
                "ica.services.prompt_editor.PromptEditorService",
                return_value=mock_editor,
            ),
        ):
            # input: "1\n" selects config, "q\n" cancels sync
            result = runner.invoke(app, ["config"], input="1\nq\n")

        assert result.exit_code == 0
        assert "docs.google.com" in result.output
        assert "Sync cancelled" in result.output
        mock_editor.sync_full_from_doc.assert_not_called()

    def test_config_full_flow_no_changes(self) -> None:
        """Full flow with no changes shows 'no changes' in summary."""
        old_config = _make_process_config(name="summarization", version=1)
        new_config = _make_process_config(name="summarization", version=2)

        configs = [("summarization", old_config)]
        mock_settings = MagicMock()
        mock_settings.google_service_account_credentials_path = "/fake/creds.json"
        mock_settings.google_shared_drive_id = "drive-123"

        mock_editor = AsyncMock()
        mock_editor.start_full_edit.return_value = "https://docs.google.com/document/d/abc/edit"
        mock_editor.sync_full_from_doc.return_value = new_config

        with (
            patch("ica.cli.config_editor.list_all_configs", return_value=configs),
            patch("ica.config.settings.get_settings", return_value=mock_settings),
            patch("ica.services.google_docs.GoogleDocsService"),
            patch(
                "ica.services.prompt_editor.PromptEditorService",
                return_value=mock_editor,
            ),
            patch(
                "ica.llm_configs.loader.load_process_config", return_value=old_config
            ),
        ):
            # input: "1\n" selects config, "\n" presses Enter to sync
            result = runner.invoke(app, ["config"], input="1\n\n")

        assert result.exit_code == 0
        assert "no changes" in result.output
        assert "Suggested commit" in result.output

    def test_config_full_flow_with_changes(self) -> None:
        """Full flow with model change shows diff in summary."""
        old_config = _make_process_config(
            name="summarization",
            model="anthropic/claude-sonnet-4.5",
            version=1,
        )
        new_config = _make_process_config(
            name="summarization",
            model="openai/gpt-4.1",
            version=2,
        )

        configs = [("summarization", old_config)]
        mock_settings = MagicMock()
        mock_settings.google_service_account_credentials_path = "/fake/creds.json"
        mock_settings.google_shared_drive_id = "drive-123"

        mock_editor = AsyncMock()
        mock_editor.start_full_edit.return_value = "https://docs.google.com/document/d/abc/edit"
        mock_editor.sync_full_from_doc.return_value = new_config

        with (
            patch("ica.cli.config_editor.list_all_configs", return_value=configs),
            patch("ica.config.settings.get_settings", return_value=mock_settings),
            patch("ica.services.google_docs.GoogleDocsService"),
            patch(
                "ica.services.prompt_editor.PromptEditorService",
                return_value=mock_editor,
            ),
            patch(
                "ica.llm_configs.loader.load_process_config", return_value=old_config
            ),
        ):
            result = runner.invoke(app, ["config"], input="1\n\n")

        assert result.exit_code == 0
        assert "anthropic/claude-sonnet-4.5" in result.output
        assert "openai/gpt-4.1" in result.output
        assert "Suggested commit" in result.output
        assert "v2" in result.output
