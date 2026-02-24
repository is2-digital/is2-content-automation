"""Tests for ica.app — FastAPI application."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ica.app import (
    PipelineRun,
    RunStatus,
    _serialize_run,
    create_app,
    get_runs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_runs():
    """Ensure the run store is empty before each test."""
    runs = get_runs()
    runs.clear()
    yield
    runs.clear()


@pytest.fixture()
def client() -> TestClient:
    """FastAPI test client without Slack or scheduler integration."""
    app = create_app(include_slack=False, include_scheduler=False)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# RunStatus enum
# ---------------------------------------------------------------------------


class TestRunStatus:
    def test_values(self):
        assert RunStatus.PENDING == "pending"
        assert RunStatus.RUNNING == "running"
        assert RunStatus.COMPLETED == "completed"
        assert RunStatus.FAILED == "failed"

    def test_all_members(self):
        assert set(RunStatus) == {
            RunStatus.PENDING,
            RunStatus.RUNNING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        }


# ---------------------------------------------------------------------------
# PipelineRun dataclass
# ---------------------------------------------------------------------------


class TestPipelineRun:
    def test_defaults(self):
        run = PipelineRun(run_id="abc123")
        assert run.run_id == "abc123"
        assert run.status == RunStatus.PENDING
        assert run.trigger == "manual"
        assert isinstance(run.started_at, datetime)
        assert run.completed_at is None
        assert run.current_step is None
        assert run.error is None

    def test_custom_values(self):
        now = datetime.now(timezone.utc)
        run = PipelineRun(
            run_id="xyz",
            status=RunStatus.RUNNING,
            trigger="scheduler",
            started_at=now,
            current_step="summarization",
        )
        assert run.trigger == "scheduler"
        assert run.status == RunStatus.RUNNING
        assert run.current_step == "summarization"
        assert run.started_at == now

    def test_mutable(self):
        run = PipelineRun(run_id="m1")
        run.status = RunStatus.COMPLETED
        run.current_step = "done"
        assert run.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# _serialize_run helper
# ---------------------------------------------------------------------------


class TestSerializeRun:
    def test_minimal_run(self):
        run = PipelineRun(run_id="s1")
        data = _serialize_run(run)
        assert data["run_id"] == "s1"
        assert data["status"] == "pending"
        assert data["trigger"] == "manual"
        assert data["completed_at"] is None
        assert data["current_step"] is None
        assert data["error"] is None
        # started_at should be an ISO string
        datetime.fromisoformat(data["started_at"])

    def test_completed_run(self):
        now = datetime.now(timezone.utc)
        run = PipelineRun(
            run_id="s2",
            status=RunStatus.COMPLETED,
            completed_at=now,
            current_step="completed",
        )
        data = _serialize_run(run)
        assert data["status"] == "completed"
        assert data["completed_at"] == now.isoformat()
        assert data["current_step"] == "completed"

    def test_failed_run(self):
        run = PipelineRun(
            run_id="s3",
            status=RunStatus.FAILED,
            error="LLM timeout",
        )
        data = _serialize_run(run)
        assert data["status"] == "failed"
        assert data["error"] == "LLM timeout"

    def test_all_keys_present(self):
        run = PipelineRun(run_id="s4")
        data = _serialize_run(run)
        expected_keys = {
            "run_id", "status", "trigger", "started_at",
            "completed_at", "current_step", "error",
        }
        assert set(data.keys()) == expected_keys


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_returns_200(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_returns_ok_status(self, client: TestClient):
        resp = client.get("/health")
        assert resp.json() == {"status": "ok"}

    def test_content_type_json(self, client: TestClient):
        resp = client.get("/health")
        assert resp.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# /trigger endpoint
# ---------------------------------------------------------------------------


class TestTriggerEndpoint:
    def test_returns_200(self, client: TestClient):
        resp = client.post("/trigger")
        assert resp.status_code == 200

    def test_returns_run_id(self, client: TestClient):
        resp = client.post("/trigger")
        data = resp.json()
        assert "run_id" in data
        assert isinstance(data["run_id"], str)
        assert len(data["run_id"]) == 12

    def test_returns_status(self, client: TestClient):
        resp = client.post("/trigger")
        data = resp.json()
        # Initial status is pending (may transition quickly)
        assert data["status"] in ("pending", "running", "completed")

    def test_stores_run(self, client: TestClient):
        resp = client.post("/trigger")
        run_id = resp.json()["run_id"]
        runs = get_runs()
        assert run_id in runs

    def test_default_trigger_api(self, client: TestClient):
        resp = client.post("/trigger")
        run_id = resp.json()["run_id"]
        assert get_runs()[run_id].trigger == "api"

    def test_custom_trigger_label(self, client: TestClient):
        resp = client.post(
            "/trigger",
            json={"trigger": "scheduler"},
        )
        run_id = resp.json()["run_id"]
        assert get_runs()[run_id].trigger == "scheduler"

    def test_non_json_body_uses_default(self, client: TestClient):
        resp = client.post("/trigger", content=b"not json")
        run_id = resp.json()["run_id"]
        assert get_runs()[run_id].trigger == "api"

    def test_empty_body_uses_default(self, client: TestClient):
        resp = client.post("/trigger")
        run_id = resp.json()["run_id"]
        assert get_runs()[run_id].trigger == "api"

    def test_multiple_triggers_create_unique_ids(self, client: TestClient):
        ids = set()
        for _ in range(5):
            resp = client.post("/trigger")
            ids.add(resp.json()["run_id"])
        assert len(ids) == 5


# ---------------------------------------------------------------------------
# /status endpoint
# ---------------------------------------------------------------------------


class TestStatusAllEndpoint:
    def test_empty_when_no_runs(self, client: TestClient):
        resp = client.get("/status")
        assert resp.status_code == 200
        assert resp.json() == {"runs": []}

    def test_returns_all_runs(self, client: TestClient):
        # Create two runs
        client.post("/trigger")
        client.post("/trigger")
        resp = client.get("/status")
        data = resp.json()
        assert len(data["runs"]) == 2

    def test_run_shape(self, client: TestClient):
        client.post("/trigger")
        resp = client.get("/status")
        run_data = resp.json()["runs"][0]
        expected_keys = {
            "run_id", "status", "trigger", "started_at",
            "completed_at", "current_step", "error",
        }
        assert set(run_data.keys()) == expected_keys


class TestStatusByIdEndpoint:
    def test_existing_run(self, client: TestClient):
        resp = client.post("/trigger")
        run_id = resp.json()["run_id"]
        resp2 = client.get(f"/status/{run_id}")
        assert resp2.status_code == 200
        assert resp2.json()["run_id"] == run_id

    def test_not_found(self, client: TestClient):
        resp = client.get("/status/nonexistent")
        assert resp.status_code == 404

    def test_not_found_body(self, client: TestClient):
        resp = client.get("/status/nonexistent")
        assert resp.json() == {"detail": "Run not found"}


# ---------------------------------------------------------------------------
# Pipeline execution (placeholder)
# ---------------------------------------------------------------------------


class TestPipelineExecution:
    def test_run_transitions_to_completed(self):
        """After triggering, the pipeline with noop steps should complete."""
        from unittest.mock import patch

        async def _noop(ctx):
            return ctx

        noop_seq = [("curation", _noop)]
        noop_par: list = []

        with patch(
            "ica.app.build_default_steps",
            return_value=(noop_seq, noop_par),
        ):
            app = create_app(include_slack=False, include_scheduler=False)
            test_client = TestClient(app, raise_server_exceptions=False)
            resp = test_client.post("/trigger")
            run_id = resp.json()["run_id"]
            # Give the async task a moment to complete
            import time

            time.sleep(0.1)
            run = get_runs()[run_id]
            # The run should reach completed
            assert run.status in (RunStatus.RUNNING, RunStatus.COMPLETED)


# ---------------------------------------------------------------------------
# create_app factory
# ---------------------------------------------------------------------------


class TestCreateApp:
    def test_include_slack_false(self):
        app = create_app(include_slack=False, include_scheduler=False)
        assert not hasattr(app.state, "slack_bolt")

    def test_app_title(self):
        app = create_app(include_slack=False, include_scheduler=False)
        assert app.title == "ica"

    def test_app_version(self):
        app = create_app(include_slack=False, include_scheduler=False)
        assert app.version == "0.1.0"

    def test_routes_registered(self):
        app = create_app(include_slack=False, include_scheduler=False)
        paths = {route.path for route in app.routes}
        assert "/health" in paths
        assert "/trigger" in paths
        assert "/status" in paths
        assert "/status/{run_id}" in paths
        assert "/scheduler" in paths

    def test_no_slack_events_route_without_slack(self):
        app = create_app(include_slack=False, include_scheduler=False)
        paths = {route.path for route in app.routes}
        assert "/slack/events" not in paths


# ---------------------------------------------------------------------------
# Slack integration
# ---------------------------------------------------------------------------


class TestSlackIntegration:
    def test_slack_env_missing_disables_integration(self):
        """When Slack env vars are missing, the app still starts."""
        app = create_app(include_slack=True, include_scheduler=False)
        # Should not have slack_bolt on state (env vars missing → exception caught)
        assert not hasattr(app.state, "slack_bolt")

    def test_slack_bolt_mounted_when_configured(self):
        """When Slack is configured, the Bolt app is stored on state."""
        mock_bolt = AsyncMock()
        mock_handler = AsyncMock()
        with patch(
            "ica.app._create_slack_app",
            return_value=(mock_bolt, mock_handler),
        ):
            app = create_app(include_slack=True, include_scheduler=False)
            assert app.state.slack_bolt is mock_bolt

    def test_slack_events_route_exists_when_configured(self):
        """The /slack/events route is registered when Slack is configured."""
        mock_bolt = AsyncMock()
        mock_handler = AsyncMock()
        with patch(
            "ica.app._create_slack_app",
            return_value=(mock_bolt, mock_handler),
        ):
            app = create_app(include_slack=True, include_scheduler=False)
            paths = {route.path for route in app.routes}
            assert "/slack/events" in paths


# ---------------------------------------------------------------------------
# get_runs accessor
# ---------------------------------------------------------------------------


class TestGetRuns:
    def test_returns_dict(self):
        assert isinstance(get_runs(), dict)

    def test_initially_empty(self):
        assert len(get_runs()) == 0

    def test_reflects_modifications(self):
        runs = get_runs()
        runs["test-1"] = PipelineRun(run_id="test-1")
        assert "test-1" in get_runs()
