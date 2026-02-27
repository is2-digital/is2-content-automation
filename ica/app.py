"""FastAPI application for the ica newsletter pipeline.

Provides REST API endpoints for triggering and monitoring pipeline runs,
plus Slack Bolt integration for interactive message callbacks.

PRD Section 11.1: Long-running service (FastAPI) with built-in scheduler,
background task workers, and REST API for triggering/monitoring pipeline runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, Response

from ica.logging import bind_context, configure_logging, get_logger
from ica.pipeline.orchestrator import (
    PipelineContext,
    build_default_steps,
    run_pipeline,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pipeline run tracking
# ---------------------------------------------------------------------------


class RunStatus(StrEnum):
    """Status of a pipeline run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PipelineRun:
    """Tracks the state of a single pipeline execution."""

    run_id: str
    status: RunStatus = RunStatus.PENDING
    trigger: str = "manual"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    current_step: str | None = None
    error: str | None = None


# In-memory run store. Keyed by run_id.
_runs: dict[str, PipelineRun] = {}

# Active pipeline tasks — tracked for graceful shutdown.
_active_tasks: set[asyncio.Task[None]] = set()

# Seconds to wait for in-flight pipelines during shutdown.
_SHUTDOWN_TIMEOUT: int = 60


def get_runs() -> dict[str, PipelineRun]:
    """Return the run store (exposed for testing)."""
    return _runs


def get_active_tasks() -> set[asyncio.Task[None]]:
    """Return the active tasks set (exposed for testing)."""
    return _active_tasks


# ---------------------------------------------------------------------------
# Slack Bolt integration
# ---------------------------------------------------------------------------


def _create_slack_app() -> Any:
    """Create the Slack Bolt async app with interaction handlers registered.

    Returns ``(bolt_app, handler, slack_service)`` when Slack env vars are
    available, or ``(None, None, None)`` otherwise (e.g. in tests).

    The Bolt app is mounted as an ASGI sub-application on ``/slack/events``.
    A shared :class:`~ica.services.slack.SlackService` is created and its
    interaction handlers (approval buttons, form/freetext modals) are
    registered on the Bolt app so that ``send_and_wait`` callbacks resolve.
    """
    try:
        from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
        from slack_bolt.async_app import AsyncApp

        from ica.config.settings import get_settings
        from ica.services.slack import SlackService, set_shared_service

        settings = get_settings()
        bolt_app = AsyncApp(
            token=settings.slack_bot_token,
            signing_secret=None,  # Socket mode uses app-level token, not signing secret
        )
        handler = AsyncSlackRequestHandler(bolt_app)

        # Create the shared SlackService and register interaction handlers
        slack_service = SlackService(
            token=settings.slack_bot_token,
            channel=settings.slack_channel,
        )
        slack_service.register_handlers(bolt_app)
        set_shared_service(slack_service)

        # Register config editing handlers (prompt editor via Google Docs)
        try:
            from ica.services.google_docs import GoogleDocsService
            from ica.services.prompt_editor import PromptEditorService
            from ica.services.slack_config_handlers import register_config_handlers

            docs_service = GoogleDocsService(
                credentials_path=settings.google_service_account_credentials_path,
                drive_id=settings.google_shared_drive_id,
            )
            editor = PromptEditorService(docs_service)
            register_config_handlers(bolt_app, editor, settings.slack_channel)
        except Exception:
            logger.info("Config editing handlers not registered — Google Docs not configured")

        return bolt_app, handler, slack_service
    except Exception:
        logger.info("Slack Bolt not configured — Slack integration disabled")
        return None, None, None


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup/shutdown lifecycle."""
    try:
        from ica.config.settings import get_settings

        settings = get_settings()
        configure_logging(level=settings.log_level, log_format=settings.log_format)
    except Exception:
        # Settings may not be available (e.g. missing env vars in tests).
        # Fall back to defaults so the app still starts.
        configure_logging()

    # --- Start scheduler if enabled ---
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.start()
        logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

    logger.info("ica application starting")
    yield

    # --- Wait for in-flight pipeline runs ---
    if _active_tasks:
        logger.info(
            "Waiting up to %ds for %d in-flight pipeline run(s) to finish",
            _SHUTDOWN_TIMEOUT,
            len(_active_tasks),
        )
        _done, pending = await asyncio.wait(
            _active_tasks, timeout=_SHUTDOWN_TIMEOUT
        )
        if pending:
            logger.warning(
                "Cancelling %d pipeline run(s) that did not finish in time",
                len(pending),
            )
            for task in pending:
                task.cancel()

    # --- Shut down scheduler ---
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")

    logger.info("ica application shutting down")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    include_slack: bool = True,
    include_scheduler: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        include_slack: Mount the Slack Bolt handler. Set to ``False`` in
            tests that don't need Slack integration.
        include_scheduler: Attach the APScheduler instance. Set to ``False``
            in tests that don't need scheduled jobs.
    """
    app = FastAPI(
        title="ica",
        description="AI newsletter generation pipeline",
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Scheduler setup ---
    if include_scheduler:
        try:
            from ica.config.settings import get_settings
            from ica.scheduler import create_scheduler

            settings = get_settings()
            app.state.scheduler = create_scheduler(timezone=settings.timezone)
        except Exception:
            logger.info("Scheduler not configured — scheduled jobs disabled")
            app.state.scheduler = None
    else:
        app.state.scheduler = None

    # --- Slack Bolt mount ---
    bolt_app: Any = None
    slack_handler: Any = None
    if include_slack:
        bolt_app, slack_handler, slack_service = _create_slack_app()
        if bolt_app is not None:
            app.state.slack_bolt = bolt_app
            app.state.slack_service = slack_service

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Health check endpoint.

        Returns a simple JSON payload indicating the service is running.
        Used by Docker health checks and load balancers.
        """
        return {"status": "ok"}

    @app.post("/trigger")
    async def trigger(request: Request) -> dict[str, str]:
        """Trigger a new pipeline run.

        Accepts an optional JSON body with ``trigger`` (string label for
        what initiated the run, defaults to ``"api"``).

        The pipeline runs as a background task — the endpoint returns
        immediately with the ``run_id`` so callers can poll ``/status``.
        """
        body: dict[str, Any] = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            with contextlib.suppress(Exception):
                body = await request.json()

        trigger_label = body.get("trigger", "api")
        run_id = uuid.uuid4().hex[:12]
        run = PipelineRun(run_id=run_id, trigger=str(trigger_label))
        _runs[run_id] = run

        # Launch pipeline in background and track for graceful shutdown
        task = asyncio.create_task(_run_pipeline(run))
        _active_tasks.add(task)
        task.add_done_callback(_active_tasks.discard)

        return {"run_id": run_id, "status": run.status.value}

    @app.get("/status")
    async def status_all() -> dict[str, Any]:
        """Return status of all pipeline runs."""
        return {
            "runs": [_serialize_run(r) for r in _runs.values()],
        }

    @app.get("/status/{run_id}", response_model=None)
    async def status_by_id(run_id: str) -> dict[str, Any] | Response:
        """Return status of a specific pipeline run."""
        run = _runs.get(run_id)
        if run is None:
            return Response(
                content='{"detail":"Run not found"}',
                status_code=404,
                media_type="application/json",
            )
        return _serialize_run(run)

    @app.get("/scheduler")
    async def scheduler_status() -> dict[str, Any]:
        """Return status of scheduled jobs."""
        sched = getattr(app.state, "scheduler", None)
        if sched is None or not sched.running:
            return {"enabled": False, "jobs": []}
        from ica.scheduler import get_scheduled_jobs

        return {"enabled": True, "jobs": get_scheduled_jobs(sched)}

    # --- Slack events route ---
    if slack_handler is not None:

        @app.post("/slack/events")
        async def slack_events(req: Request) -> Response:
            """Forward Slack events to the Bolt handler."""
            return await slack_handler.handle(req)  # type: ignore[no-any-return]

    return app


# ---------------------------------------------------------------------------
# Pipeline execution (placeholder)
# ---------------------------------------------------------------------------


async def _run_pipeline(run: PipelineRun) -> None:
    """Execute the newsletter pipeline for *run*.

    Builds the default step lists, creates a :class:`PipelineContext`, and
    delegates to :func:`~ica.pipeline.orchestrator.run_pipeline`.  Updates
    the :class:`PipelineRun` status throughout so ``/status`` reflects
    real-time progress.

    See PRD Section 11.6.
    """
    run.status = RunStatus.RUNNING
    run.current_step = "starting"
    logger.info("Pipeline run %s started (trigger=%s)", run.run_id, run.trigger)

    ctx = PipelineContext(run_id=run.run_id, trigger=run.trigger)
    sequential, parallel = build_default_steps()

    try:
        async with bind_context(run_id=run.run_id):
            ctx = await run_pipeline(
                ctx,
                sequential_steps=sequential,
                parallel_steps=parallel,
            )
        run.current_step = "completed"
        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        logger.info("Pipeline run %s completed", run.run_id)
    except Exception as exc:
        run.status = RunStatus.FAILED
        run.error = str(exc)
        run.completed_at = datetime.now(UTC)
        logger.exception("Pipeline run %s failed", run.run_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_run(run: PipelineRun) -> dict[str, Any]:
    """Convert a PipelineRun to a JSON-serialisable dict."""
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "trigger": run.trigger,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "current_step": run.current_step,
        "error": run.error,
    }
