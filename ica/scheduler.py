"""APScheduler integration for timed pipeline triggers and article collection.

Configures two independent schedules (PRD Section 10.1):

- **Article collection (daily)**: google_news engine, 3 keywords, every day
- **Article collection (every 2 days)**: default engine, 5 keywords
- **Pipeline trigger**: manual or every 5 days (optional, off by default)

The scheduler integrates with FastAPI's lifespan so it starts/stops with the
application.  Uses APScheduler's :class:`AsyncIOScheduler` for non-blocking
execution inside the existing event loop.

PRD Section 11.4: ``ica/scheduler.py`` — APScheduler for timed triggers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ica.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------


def create_scheduler(
    *,
    timezone: str = "America/Los_Angeles",
    enable_article_collection: bool = True,
    enable_pipeline_trigger: bool = False,
    pipeline_interval_days: int = 5,
    article_daily_hour: int = 6,
    article_daily_minute: int = 0,
    article_every2d_hour: int = 7,
    article_every2d_minute: int = 0,
    pipeline_hour: int = 8,
    pipeline_minute: int = 0,
) -> AsyncIOScheduler:
    """Create and configure the APScheduler instance.

    The scheduler is *not* started — call :meth:`scheduler.start()` during
    application startup (e.g. in the FastAPI lifespan).

    Args:
        timezone: IANA timezone for all cron triggers.
        enable_article_collection: Add the daily + every-2-days article
            collection jobs.  Defaults to ``True``.
        enable_pipeline_trigger: Add the recurring pipeline trigger job.
            Defaults to ``False`` (manual-only).
        pipeline_interval_days: Interval in days for the pipeline trigger
            job.  Only used when *enable_pipeline_trigger* is ``True``.
        article_daily_hour: Hour (in *timezone*) for the daily article
            collection job.
        article_daily_minute: Minute for the daily article collection job.
        article_every2d_hour: Hour for the every-2-days article collection job.
        article_every2d_minute: Minute for the every-2-days job.
        pipeline_hour: Hour for the pipeline trigger job.
        pipeline_minute: Minute for the pipeline trigger job.

    Returns:
        A configured :class:`AsyncIOScheduler` ready to be started.
    """
    scheduler = AsyncIOScheduler(timezone=timezone)

    if enable_article_collection:
        # Daily: google_news engine (PRD Section 1.3)
        scheduler.add_job(
            run_article_collection,
            trigger=CronTrigger(hour=article_daily_hour, minute=article_daily_minute),
            kwargs={"schedule": "daily"},
            id="article_collection_daily",
            name="Article collection (daily / google_news)",
            replace_existing=True,
        )

        # Every 2 days: default engine (PRD Section 1.3)
        scheduler.add_job(
            run_article_collection,
            trigger=IntervalTrigger(days=2),
            kwargs={"schedule": "every_2_days"},
            id="article_collection_every_2_days",
            name="Article collection (every 2 days / default)",
            replace_existing=True,
        )

    if enable_pipeline_trigger:
        # Pipeline trigger every N days (PRD Section 10.1)
        scheduler.add_job(
            run_pipeline_trigger,
            trigger=IntervalTrigger(days=pipeline_interval_days),
            id="pipeline_trigger",
            name=f"Pipeline trigger (every {pipeline_interval_days} days)",
            replace_existing=True,
        )

    return scheduler


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------


async def run_article_collection(*, schedule: str = "daily") -> dict[str, Any]:
    """Execute article collection as a scheduled job.

    Loads settings, creates an HTTP client and SearchApi client, and runs
    the full collection pipeline.  Failures are logged but not re-raised
    (APScheduler handles job exceptions gracefully).

    Args:
        schedule: Either ``"daily"`` or ``"every_2_days"``.

    Returns:
        A summary dict with counts (for logging/monitoring).
    """
    logger.info("Scheduled article collection starting (schedule=%s)", schedule)

    try:
        import httpx

        from ica.config.settings import get_settings
        from ica.services.search_api import SearchApiClient
        from ica.pipeline.article_collection import collect_articles

        settings = get_settings()

        async with httpx.AsyncClient() as http_client:
            search_client = SearchApiClient(
                api_key=settings.searchapi_api_key,
                http_client=http_client,
            )
            # Use the stub repository for now — real DB integration will use
            # the SQLAlchemy repository once service integration tasks land.
            result = await collect_articles(
                client=search_client,
                repository=_SchedulerStubRepository(),
                schedule=schedule,
            )

        summary = {
            "schedule": schedule,
            "raw_results": len(result.raw_results),
            "deduplicated": len(result.deduplicated),
            "articles": len(result.articles),
            "rows_affected": result.rows_affected,
        }
        logger.info(
            "Article collection complete (schedule=%s): %d articles, %d rows",
            schedule,
            len(result.articles),
            result.rows_affected,
        )
        return summary

    except Exception:
        logger.exception("Article collection failed (schedule=%s)", schedule)
        return {"schedule": schedule, "error": True}


async def run_pipeline_trigger() -> dict[str, Any]:
    """Trigger a pipeline run as a scheduled job.

    Creates a new pipeline run via the same internal path as the
    ``/trigger`` API endpoint, using ``"scheduler"`` as the trigger label.

    Returns:
        A summary dict with the run_id.
    """
    logger.info("Scheduled pipeline trigger starting")

    try:
        from ica.app import PipelineRun, RunStatus, get_runs, _run_pipeline
        import uuid

        run_id = uuid.uuid4().hex[:12]
        run = PipelineRun(run_id=run_id, trigger="scheduler")
        runs = get_runs()
        runs[run_id] = run

        import asyncio

        asyncio.create_task(_run_pipeline(run))  # noqa: RUF006

        logger.info("Scheduled pipeline run created: %s", run_id)
        return {"run_id": run_id, "trigger": "scheduler"}

    except Exception:
        logger.exception("Scheduled pipeline trigger failed")
        return {"error": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_scheduled_jobs(scheduler: AsyncIOScheduler) -> list[dict[str, Any]]:
    """Return a summary of all configured jobs.

    Useful for the ``/health`` or status endpoints.

    Args:
        scheduler: The running scheduler instance.

    Returns:
        List of dicts with job id, name, next_run_time, and trigger info.
    """
    jobs = []
    for job in scheduler.get_jobs():
        next_run = getattr(job, "next_run_time", None)
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run.isoformat() if next_run else None,
                "trigger": str(job.trigger),
            }
        )
    return jobs


class _SchedulerStubRepository:
    """No-op article repository for scheduler jobs.

    Replaced by real SQLAlchemy repository once DB service integration
    is complete.
    """

    async def upsert_articles(self, articles: list) -> int:
        """Return count without persisting."""
        return len(articles)
