"""Tests for ica.scheduler — APScheduler integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.scheduler import (
    create_scheduler,
    get_scheduled_jobs,
    run_article_collection,
    run_pipeline_trigger,
)

# ---------------------------------------------------------------------------
# create_scheduler — factory
# ---------------------------------------------------------------------------


class TestCreateScheduler:
    """Tests for the scheduler factory function."""

    def test_returns_scheduler(self):
        sched = create_scheduler()
        assert sched is not None

    def test_default_timezone(self):
        sched = create_scheduler()
        assert str(sched.timezone) == "America/Los_Angeles"

    def test_custom_timezone(self):
        sched = create_scheduler(timezone="Europe/London")
        assert str(sched.timezone) == "Europe/London"

    def test_article_collection_enabled_by_default(self):
        sched = create_scheduler()
        job_ids = {j.id for j in sched.get_jobs()}
        assert "article_collection_daily" in job_ids
        assert "article_collection_every_2_days" in job_ids

    def test_article_collection_disabled(self):
        sched = create_scheduler(enable_article_collection=False)
        job_ids = {j.id for j in sched.get_jobs()}
        assert "article_collection_daily" not in job_ids
        assert "article_collection_every_2_days" not in job_ids

    def test_pipeline_trigger_disabled_by_default(self):
        sched = create_scheduler()
        job_ids = {j.id for j in sched.get_jobs()}
        assert "pipeline_trigger" not in job_ids

    def test_pipeline_trigger_enabled(self):
        sched = create_scheduler(enable_pipeline_trigger=True)
        job_ids = {j.id for j in sched.get_jobs()}
        assert "pipeline_trigger" in job_ids

    def test_all_jobs_enabled(self):
        sched = create_scheduler(
            enable_article_collection=True,
            enable_pipeline_trigger=True,
        )
        job_ids = {j.id for j in sched.get_jobs()}
        assert len(job_ids) == 3
        assert "article_collection_daily" in job_ids
        assert "article_collection_every_2_days" in job_ids
        assert "pipeline_trigger" in job_ids

    def test_no_jobs_when_both_disabled(self):
        sched = create_scheduler(
            enable_article_collection=False,
            enable_pipeline_trigger=False,
        )
        assert len(sched.get_jobs()) == 0

    def test_default_has_two_jobs(self):
        sched = create_scheduler()
        assert len(sched.get_jobs()) == 2

    def test_not_running_before_start(self):
        sched = create_scheduler()
        assert not sched.running


# ---------------------------------------------------------------------------
# create_scheduler — job configuration
# ---------------------------------------------------------------------------


class TestSchedulerJobConfig:
    """Tests for job trigger configuration."""

    def test_daily_job_name(self):
        sched = create_scheduler()
        job = sched.get_job("article_collection_daily")
        assert job is not None
        assert "daily" in job.name.lower()

    def test_every_2_days_job_name(self):
        sched = create_scheduler()
        job = sched.get_job("article_collection_every_2_days")
        assert job is not None
        assert "every 2 days" in job.name.lower()

    def test_pipeline_trigger_job_name(self):
        sched = create_scheduler(enable_pipeline_trigger=True)
        job = sched.get_job("pipeline_trigger")
        assert job is not None
        assert "pipeline" in job.name.lower()

    def test_daily_job_kwargs(self):
        sched = create_scheduler()
        job = sched.get_job("article_collection_daily")
        assert job.kwargs == {"schedule": "daily"}

    def test_every_2_days_job_kwargs(self):
        sched = create_scheduler()
        job = sched.get_job("article_collection_every_2_days")
        assert job.kwargs == {"schedule": "every_2_days"}

    def test_daily_job_cron_trigger(self):
        sched = create_scheduler(article_daily_hour=9, article_daily_minute=30)
        job = sched.get_job("article_collection_daily")
        trigger_str = str(job.trigger)
        assert "9" in trigger_str
        assert "30" in trigger_str

    def test_pipeline_interval_days(self):
        sched = create_scheduler(
            enable_pipeline_trigger=True,
            pipeline_interval_days=7,
        )
        job = sched.get_job("pipeline_trigger")
        assert "7 days" in job.name or "7" in str(job.trigger)

    def test_multiple_creates_independent(self):
        """Creating multiple schedulers produces independent instances."""
        sched1 = create_scheduler()
        sched2 = create_scheduler(enable_article_collection=False)
        assert len(sched1.get_jobs()) == 2
        assert len(sched2.get_jobs()) == 0

    def test_custom_article_daily_time(self):
        sched = create_scheduler(article_daily_hour=14, article_daily_minute=45)
        job = sched.get_job("article_collection_daily")
        assert job is not None

    def test_custom_article_every2d_time(self):
        sched = create_scheduler(article_every2d_hour=15, article_every2d_minute=15)
        job = sched.get_job("article_collection_every_2_days")
        assert job is not None


# ---------------------------------------------------------------------------
# run_article_collection — scheduled job function
# ---------------------------------------------------------------------------


class TestRunArticleCollection:
    """Tests for the article collection job function."""

    @pytest.mark.asyncio
    async def test_daily_schedule(self):
        mock_result = MagicMock()
        mock_result.raw_results = [1, 2, 3]
        mock_result.deduplicated = [1, 2]
        mock_result.articles = [1, 2]
        mock_result.rows_affected = 2
        mock_result.accepted_count = 2
        mock_result.rejected_count = 0

        mock_collect = AsyncMock(return_value=mock_result)
        mock_session = AsyncMock()

        with (
            patch("ica.config.settings.get_settings") as mock_settings,
            patch("ica.services.brave_search.BraveSearchClient"),
            patch("ica.pipeline.article_collection.collect_articles", mock_collect),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("ica.db.session.get_session") as mock_get_session,
        ):
            mock_settings.return_value = MagicMock(
                brave_api_key="test-key"
            )
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await run_article_collection(schedule="daily")

        assert result["schedule"] == "daily"
        assert result["articles"] == 2
        assert result["rows_affected"] == 2

    @pytest.mark.asyncio
    async def test_every_2_days_schedule(self):
        mock_result = MagicMock()
        mock_result.raw_results = list(range(10))
        mock_result.deduplicated = list(range(8))
        mock_result.articles = list(range(8))
        mock_result.rows_affected = 8
        mock_result.accepted_count = 6
        mock_result.rejected_count = 2

        mock_collect = AsyncMock(return_value=mock_result)
        mock_session = AsyncMock()

        with (
            patch("ica.config.settings.get_settings") as mock_settings,
            patch("ica.services.brave_search.BraveSearchClient"),
            patch("ica.pipeline.article_collection.collect_articles", mock_collect),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("ica.db.session.get_session") as mock_get_session,
        ):
            mock_settings.return_value = MagicMock(
                brave_api_key="test-key"
            )
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await run_article_collection(schedule="every_2_days")

        assert result["schedule"] == "every_2_days"
        assert result["articles"] == 8

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self):
        with patch(
            "ica.config.settings.get_settings",
            side_effect=RuntimeError("missing env vars"),
        ):
            result = await run_article_collection(schedule="daily")

        assert result["error"] is True
        assert result["schedule"] == "daily"

    @pytest.mark.asyncio
    async def test_default_schedule_is_daily(self):
        mock_result = MagicMock()
        mock_result.raw_results = []
        mock_result.deduplicated = []
        mock_result.articles = []
        mock_result.rows_affected = 0
        mock_result.accepted_count = 0
        mock_result.rejected_count = 0

        mock_collect = AsyncMock(return_value=mock_result)
        mock_session = AsyncMock()

        with (
            patch("ica.config.settings.get_settings") as mock_settings,
            patch("ica.services.brave_search.BraveSearchClient"),
            patch("ica.pipeline.article_collection.collect_articles", mock_collect),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("ica.db.session.get_session") as mock_get_session,
        ):
            mock_settings.return_value = MagicMock(
                brave_api_key="test-key"
            )
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await run_article_collection()

        assert result["schedule"] == "daily"

    @pytest.mark.asyncio
    async def test_summary_dict_keys(self):
        mock_result = MagicMock()
        mock_result.raw_results = [1]
        mock_result.deduplicated = [1]
        mock_result.articles = [1]
        mock_result.rows_affected = 1
        mock_result.accepted_count = 1
        mock_result.rejected_count = 0

        mock_collect = AsyncMock(return_value=mock_result)
        mock_session = AsyncMock()

        with (
            patch("ica.config.settings.get_settings") as mock_settings,
            patch("ica.services.brave_search.BraveSearchClient"),
            patch("ica.pipeline.article_collection.collect_articles", mock_collect),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("ica.db.session.get_session") as mock_get_session,
        ):
            mock_settings.return_value = MagicMock(brave_api_key="test-key")
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await run_article_collection(schedule="daily")

        expected_keys = {
            "schedule", "raw_results", "deduplicated", "articles",
            "accepted", "rejected", "rows_affected",
        }
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# run_pipeline_trigger — scheduled job function
# ---------------------------------------------------------------------------


class TestRunPipelineTrigger:
    """Tests for the pipeline trigger job function."""

    @pytest.mark.asyncio
    async def test_creates_run(self):
        mock_runs: dict = {}
        mock_run_pipeline = AsyncMock()

        with (
            patch("ica.app.get_runs", return_value=mock_runs),
            patch("ica.app._run_pipeline", mock_run_pipeline),
            patch("asyncio.create_task"),
        ):
            result = await run_pipeline_trigger()

        assert "run_id" in result
        assert result["trigger"] == "scheduler"
        assert result["run_id"] in mock_runs

    @pytest.mark.asyncio
    async def test_run_has_scheduler_trigger(self):
        mock_runs: dict = {}
        mock_run_pipeline = AsyncMock()

        with (
            patch("ica.app.get_runs", return_value=mock_runs),
            patch("ica.app._run_pipeline", mock_run_pipeline),
            patch("asyncio.create_task"),
        ):
            result = await run_pipeline_trigger()

        run = mock_runs[result["run_id"]]
        assert run.trigger == "scheduler"

    @pytest.mark.asyncio
    async def test_run_id_format(self):
        mock_runs: dict = {}

        with (
            patch("ica.app.get_runs", return_value=mock_runs),
            patch("ica.app._run_pipeline", AsyncMock()),
            patch("asyncio.create_task"),
        ):
            result = await run_pipeline_trigger()

        assert len(result["run_id"]) == 12
        assert result["run_id"].isalnum()

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self):
        with patch(
            "ica.app.get_runs",
            side_effect=RuntimeError("import failed"),
        ):
            result = await run_pipeline_trigger()

        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_launches_background_task(self):
        mock_runs: dict = {}
        mock_run_pipeline = AsyncMock()

        with (
            patch("ica.app.get_runs", return_value=mock_runs),
            patch("ica.app._run_pipeline", mock_run_pipeline),
            patch("asyncio.create_task") as mock_task,
        ):
            await run_pipeline_trigger()

        mock_task.assert_called_once()


# ---------------------------------------------------------------------------
# get_scheduled_jobs — status helper
# ---------------------------------------------------------------------------


class TestGetScheduledJobs:
    """Tests for the job status helper."""

    def test_empty_scheduler(self):
        sched = create_scheduler(
            enable_article_collection=False,
            enable_pipeline_trigger=False,
        )
        jobs = get_scheduled_jobs(sched)
        assert jobs == []

    def test_returns_list(self):
        sched = create_scheduler()
        jobs = get_scheduled_jobs(sched)
        assert isinstance(jobs, list)

    def test_job_dict_keys(self):
        sched = create_scheduler()
        jobs = get_scheduled_jobs(sched)
        assert len(jobs) > 0
        for job_info in jobs:
            assert "id" in job_info
            assert "name" in job_info
            assert "next_run_time" in job_info
            assert "trigger" in job_info

    def test_job_ids_match(self):
        sched = create_scheduler()
        jobs = get_scheduled_jobs(sched)
        job_ids = {j["id"] for j in jobs}
        assert "article_collection_daily" in job_ids
        assert "article_collection_every_2_days" in job_ids

    def test_next_run_time_none_before_start(self):
        sched = create_scheduler()
        jobs = get_scheduled_jobs(sched)
        # Before starting, next_run_time is None
        for job_info in jobs:
            assert job_info["next_run_time"] is None

    def test_three_jobs_all_enabled(self):
        sched = create_scheduler(
            enable_article_collection=True,
            enable_pipeline_trigger=True,
        )
        jobs = get_scheduled_jobs(sched)
        assert len(jobs) == 3

    def test_trigger_is_string(self):
        sched = create_scheduler()
        jobs = get_scheduled_jobs(sched)
        for job_info in jobs:
            assert isinstance(job_info["trigger"], str)


# ---------------------------------------------------------------------------
# FastAPI integration — scheduler lifecycle
# ---------------------------------------------------------------------------


class TestSchedulerFastAPIIntegration:
    """Tests for scheduler integration with the FastAPI app."""

    def test_scheduler_disabled_via_create_app(self):
        from ica.app import create_app

        app = create_app(include_slack=False, include_scheduler=False)
        assert app.state.scheduler is None

    def test_scheduler_endpoint_disabled(self):
        from fastapi.testclient import TestClient

        from ica.app import create_app

        app = create_app(include_slack=False, include_scheduler=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/scheduler")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["jobs"] == []

    def test_scheduler_route_exists(self):
        from ica.app import create_app

        app = create_app(include_slack=False, include_scheduler=False)
        paths = {route.path for route in app.routes}
        assert "/scheduler" in paths

    def test_scheduler_enabled_fallback_on_missing_settings(self):
        """When settings are missing, scheduler gracefully degrades to None."""
        from ica.app import create_app

        # include_scheduler=True but get_settings raises → scheduler falls back to None
        with patch(
            "ica.config.settings.get_settings",
            side_effect=RuntimeError("missing env vars"),
        ):
            app = create_app(include_slack=False, include_scheduler=True)
            assert app.state.scheduler is None

    def test_scheduler_enabled_with_mocked_settings(self):
        """When settings are available, scheduler is created."""
        from ica.app import create_app

        mock_settings = MagicMock()
        mock_settings.timezone = "America/New_York"

        with patch("ica.config.settings.get_settings", return_value=mock_settings):
            app = create_app(include_slack=False, include_scheduler=True)

        assert app.state.scheduler is not None
        # Should have the 2 default article collection jobs
        assert len(app.state.scheduler.get_jobs()) == 2

    def test_scheduler_uses_settings_timezone(self):
        from ica.app import create_app

        mock_settings = MagicMock()
        mock_settings.timezone = "Asia/Tokyo"

        with patch("ica.config.settings.get_settings", return_value=mock_settings):
            app = create_app(include_slack=False, include_scheduler=True)

        assert str(app.state.scheduler.timezone) == "Asia/Tokyo"
