"""Tests for ica.pipeline.orchestrator — pipeline wiring and context propagation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from ica.errors import PipelineStopError
from ica.pipeline.orchestrator import (
    PipelineContext,
    StepName,
    StepResult,
    _run_parallel_steps,
    build_default_steps,
    run_pipeline,
    run_step,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _identity_step(ctx: PipelineContext) -> PipelineContext:
    """Step that returns the context unchanged."""
    return ctx


async def _failing_step(ctx: PipelineContext) -> PipelineContext:
    """Step that raises a generic exception."""
    raise RuntimeError("step exploded")


async def _pipeline_stop_step(ctx: PipelineContext) -> PipelineContext:
    """Step that raises PipelineStopError."""
    raise PipelineStopError("test_step", "intentional stop")


async def _mutating_step(ctx: PipelineContext) -> PipelineContext:
    """Step that sets newsletter_id."""
    ctx.newsletter_id = "NL-42"
    return ctx


async def _slow_step(ctx: PipelineContext) -> PipelineContext:
    """Step that takes a small delay."""
    await asyncio.sleep(0.01)
    return ctx


# ---------------------------------------------------------------------------
# StepName enum
# ---------------------------------------------------------------------------


class TestStepName:
    def test_sequential_steps(self):
        assert StepName.CURATION == "curation"
        assert StepName.SUMMARIZATION == "summarization"
        assert StepName.THEME_GENERATION == "theme_generation"
        assert StepName.MARKDOWN_GENERATION == "markdown_generation"
        assert StepName.HTML_GENERATION == "html_generation"

    def test_parallel_steps(self):
        assert StepName.ALTERNATES_HTML == "alternates_html"
        assert StepName.EMAIL_SUBJECT == "email_subject"
        assert StepName.SOCIAL_MEDIA == "social_media"
        assert StepName.LINKEDIN_CAROUSEL == "linkedin_carousel"

    def test_all_members(self):
        assert len(StepName) == 9


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------


class TestPipelineContext:
    def test_defaults(self):
        ctx = PipelineContext()
        assert ctx.run_id == ""
        assert ctx.trigger == "manual"
        assert ctx.newsletter_id is None
        assert ctx.articles == []
        assert ctx.summaries == []
        assert ctx.summaries_json == ""
        assert ctx.formatted_theme == {}
        assert ctx.theme_name == ""
        assert ctx.theme_body == ""
        assert ctx.theme_summary is None
        assert ctx.markdown_doc_id is None
        assert ctx.html_doc_id is None
        assert ctx.step_results == []
        assert ctx.extra == {}

    def test_custom_values(self):
        ctx = PipelineContext(
            run_id="abc123",
            trigger="scheduler",
            newsletter_id="NL-1",
        )
        assert ctx.run_id == "abc123"
        assert ctx.trigger == "scheduler"
        assert ctx.newsletter_id == "NL-1"

    def test_mutable_articles(self):
        ctx = PipelineContext()
        ctx.articles.append({"url": "https://example.com"})
        assert len(ctx.articles) == 1

    def test_mutable_summaries(self):
        ctx = PipelineContext()
        ctx.summaries.append({"URL": "https://x.com", "Title": "X"})
        assert len(ctx.summaries) == 1

    def test_mutable_formatted_theme(self):
        ctx = PipelineContext()
        ctx.formatted_theme["THEME"] = "AI in 2026"
        assert ctx.formatted_theme["THEME"] == "AI in 2026"

    def test_step_results_accumulate(self):
        ctx = PipelineContext()
        now = datetime.now(timezone.utc)
        ctx.step_results.append(
            StepResult(step="a", status="completed", started_at=now, completed_at=now)
        )
        ctx.step_results.append(
            StepResult(step="b", status="completed", started_at=now, completed_at=now)
        )
        assert len(ctx.step_results) == 2

    def test_extra_dict(self):
        ctx = PipelineContext()
        ctx.extra["model"] = "claude-sonnet"
        assert ctx.extra["model"] == "claude-sonnet"

    def test_independent_instances(self):
        """Each instance has its own mutable fields."""
        a = PipelineContext(run_id="a")
        b = PipelineContext(run_id="b")
        a.articles.append({"url": "only-in-a"})
        assert b.articles == []


# ---------------------------------------------------------------------------
# StepResult
# ---------------------------------------------------------------------------


class TestStepResult:
    def test_frozen(self):
        now = datetime.now(timezone.utc)
        r = StepResult(step="x", status="completed", started_at=now, completed_at=now)
        with pytest.raises(AttributeError):
            r.step = "y"  # type: ignore[misc]

    def test_duration_seconds(self):
        t1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
        r = StepResult(step="x", status="completed", started_at=t1, completed_at=t2)
        assert r.duration_seconds == 5.0

    def test_duration_zero(self):
        now = datetime.now(timezone.utc)
        r = StepResult(step="x", status="completed", started_at=now, completed_at=now)
        assert r.duration_seconds == 0.0

    def test_error_none_by_default(self):
        now = datetime.now(timezone.utc)
        r = StepResult(step="x", status="completed", started_at=now, completed_at=now)
        assert r.error is None

    def test_error_set(self):
        now = datetime.now(timezone.utc)
        r = StepResult(
            step="x", status="failed", started_at=now, completed_at=now, error="boom"
        )
        assert r.error == "boom"


# ---------------------------------------------------------------------------
# run_step
# ---------------------------------------------------------------------------


class TestRunStep:
    @pytest.mark.asyncio
    async def test_successful_step(self):
        ctx = PipelineContext(run_id="r1")
        result = await run_step("test", _identity_step, ctx)
        assert result is ctx
        assert len(ctx.step_results) == 1
        assert ctx.step_results[0].step == "test"
        assert ctx.step_results[0].status == "completed"
        assert ctx.step_results[0].error is None

    @pytest.mark.asyncio
    async def test_step_propagates_context_changes(self):
        ctx = PipelineContext(run_id="r2")
        result = await run_step("mutate", _mutating_step, ctx)
        assert result.newsletter_id == "NL-42"

    @pytest.mark.asyncio
    async def test_step_records_timing(self):
        ctx = PipelineContext(run_id="r3")
        await run_step("slow", _slow_step, ctx)
        r = ctx.step_results[0]
        assert r.duration_seconds >= 0
        assert r.started_at <= r.completed_at

    @pytest.mark.asyncio
    async def test_pipeline_stop_error_recorded_and_reraised(self):
        ctx = PipelineContext(run_id="r4")
        with pytest.raises(PipelineStopError):
            await run_step("stop", _pipeline_stop_step, ctx)
        assert len(ctx.step_results) == 1
        assert ctx.step_results[0].status == "failed"
        assert ctx.step_results[0].error == "PipelineStopError"

    @pytest.mark.asyncio
    async def test_generic_exception_recorded_and_reraised(self):
        ctx = PipelineContext(run_id="r5")
        with pytest.raises(RuntimeError, match="step exploded"):
            await run_step("fail", _failing_step, ctx)
        assert len(ctx.step_results) == 1
        assert ctx.step_results[0].status == "failed"
        assert ctx.step_results[0].error == "step exploded"

    @pytest.mark.asyncio
    async def test_multiple_steps_accumulate_results(self):
        ctx = PipelineContext(run_id="r6")
        await run_step("a", _identity_step, ctx)
        await run_step("b", _identity_step, ctx)
        assert len(ctx.step_results) == 2
        assert ctx.step_results[0].step == "a"
        assert ctx.step_results[1].step == "b"


# ---------------------------------------------------------------------------
# run_pipeline — sequential
# ---------------------------------------------------------------------------


class TestRunPipelineSequential:
    @pytest.mark.asyncio
    async def test_empty_steps(self):
        ctx = PipelineContext(run_id="p1")
        result = await run_pipeline(ctx, sequential_steps=[], parallel_steps=[])
        assert result is ctx
        assert result.step_results == []

    @pytest.mark.asyncio
    async def test_single_step(self):
        ctx = PipelineContext(run_id="p2")
        steps = [("only", _identity_step)]
        result = await run_pipeline(ctx, sequential_steps=steps)
        assert len(result.step_results) == 1
        assert result.step_results[0].step == "only"

    @pytest.mark.asyncio
    async def test_sequential_order(self):
        """Steps execute in the order given and results reflect that."""
        call_order: list[str] = []

        async def make_step(name: str):
            async def step(ctx: PipelineContext) -> PipelineContext:
                call_order.append(name)
                return ctx
            return step

        steps = [
            ("first", await make_step("first")),
            ("second", await make_step("second")),
            ("third", await make_step("third")),
        ]
        ctx = PipelineContext(run_id="p3")
        result = await run_pipeline(ctx, sequential_steps=steps)
        assert call_order == ["first", "second", "third"]
        assert [r.step for r in result.step_results] == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_context_propagation_between_steps(self):
        """Each step sees modifications from previous steps."""
        async def step_a(ctx: PipelineContext) -> PipelineContext:
            ctx.newsletter_id = "NL-100"
            return ctx

        async def step_b(ctx: PipelineContext) -> PipelineContext:
            assert ctx.newsletter_id == "NL-100"
            ctx.theme_name = "AI Revolution"
            return ctx

        steps = [("a", step_a), ("b", step_b)]
        ctx = PipelineContext(run_id="p4")
        result = await run_pipeline(ctx, sequential_steps=steps)
        assert result.newsletter_id == "NL-100"
        assert result.theme_name == "AI Revolution"

    @pytest.mark.asyncio
    async def test_pipeline_stop_halts_sequence(self):
        """PipelineStopError in a sequential step prevents later steps."""
        call_order: list[str] = []

        async def tracked(ctx: PipelineContext) -> PipelineContext:
            call_order.append("after")
            return ctx

        steps = [
            ("stop", _pipeline_stop_step),
            ("after", tracked),
        ]
        ctx = PipelineContext(run_id="p5")
        with pytest.raises(PipelineStopError):
            await run_pipeline(ctx, sequential_steps=steps)
        assert "after" not in call_order
        assert len(ctx.step_results) == 1

    @pytest.mark.asyncio
    async def test_generic_error_halts_sequence(self):
        call_order: list[str] = []

        async def tracked(ctx: PipelineContext) -> PipelineContext:
            call_order.append("after")
            return ctx

        steps = [
            ("fail", _failing_step),
            ("after", tracked),
        ]
        ctx = PipelineContext(run_id="p6")
        with pytest.raises(RuntimeError):
            await run_pipeline(ctx, sequential_steps=steps)
        assert "after" not in call_order

    @pytest.mark.asyncio
    async def test_none_defaults_to_empty(self):
        """Passing None for steps uses empty lists."""
        ctx = PipelineContext(run_id="p7")
        result = await run_pipeline(ctx)
        assert result.step_results == []


# ---------------------------------------------------------------------------
# run_pipeline — parallel
# ---------------------------------------------------------------------------


class TestRunPipelineParallel:
    @pytest.mark.asyncio
    async def test_parallel_steps_all_succeed(self):
        """All parallel steps execute and record results."""
        executed: list[str] = []

        async def make_parallel(name: str):
            async def step(ctx: PipelineContext) -> PipelineContext:
                executed.append(name)
                return ctx
            return step

        parallel = [
            ("p1", await make_parallel("p1")),
            ("p2", await make_parallel("p2")),
            ("p3", await make_parallel("p3")),
        ]
        ctx = PipelineContext(run_id="par1")
        result = await run_pipeline(ctx, parallel_steps=parallel)
        assert set(executed) == {"p1", "p2", "p3"}
        assert len(result.step_results) == 3
        assert all(r.status == "completed" for r in result.step_results)

    @pytest.mark.asyncio
    async def test_parallel_failure_does_not_cancel_siblings(self):
        """A failing parallel step doesn't prevent others from completing."""
        succeeded: list[str] = []

        async def good_step(ctx: PipelineContext) -> PipelineContext:
            succeeded.append("good")
            return ctx

        parallel = [
            ("good1", good_step),
            ("bad", _failing_step),
            ("good2", good_step),
        ]
        ctx = PipelineContext(run_id="par2")
        result = await run_pipeline(ctx, parallel_steps=parallel)

        # Both good steps should have completed
        assert succeeded.count("good") == 2
        # The bad step should be recorded as failed
        statuses = {r.step: r.status for r in result.step_results}
        assert statuses["bad"] == "failed"
        assert statuses["good1"] == "completed"
        assert statuses["good2"] == "completed"

    @pytest.mark.asyncio
    async def test_parallel_steps_run_after_sequential(self):
        """Parallel steps only run after all sequential steps complete."""
        order: list[str] = []

        async def seq_step(ctx: PipelineContext) -> PipelineContext:
            order.append("seq")
            await asyncio.sleep(0.01)
            return ctx

        async def par_step(ctx: PipelineContext) -> PipelineContext:
            order.append("par")
            return ctx

        ctx = PipelineContext(run_id="par3")
        await run_pipeline(
            ctx,
            sequential_steps=[("seq", seq_step)],
            parallel_steps=[("par", par_step)],
        )
        assert order == ["seq", "par"]

    @pytest.mark.asyncio
    async def test_parallel_steps_share_context(self):
        """Parallel steps see the same context state from sequential."""
        seen_ids: list[str | None] = []

        async def seq_step(ctx: PipelineContext) -> PipelineContext:
            ctx.newsletter_id = "NL-SHARED"
            return ctx

        async def par_check(ctx: PipelineContext) -> PipelineContext:
            seen_ids.append(ctx.newsletter_id)
            return ctx

        ctx = PipelineContext(run_id="par4")
        await run_pipeline(
            ctx,
            sequential_steps=[("seq", seq_step)],
            parallel_steps=[("par1", par_check), ("par2", par_check)],
        )
        assert all(nid == "NL-SHARED" for nid in seen_ids)


# ---------------------------------------------------------------------------
# _run_parallel_steps
# ---------------------------------------------------------------------------


class TestRunParallelSteps:
    @pytest.mark.asyncio
    async def test_returns_empty_on_success(self):
        ctx = PipelineContext(run_id="rp1")
        errors = await _run_parallel_steps(ctx, [("ok", _identity_step)])
        assert errors == []

    @pytest.mark.asyncio
    async def test_returns_errors_list(self):
        ctx = PipelineContext(run_id="rp2")
        errors = await _run_parallel_steps(ctx, [("bad", _failing_step)])
        assert len(errors) == 1
        assert errors[0][0] == "bad"
        assert isinstance(errors[0][1], RuntimeError)

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self):
        ctx = PipelineContext(run_id="rp3")
        steps = [
            ("ok1", _identity_step),
            ("bad", _failing_step),
            ("ok2", _identity_step),
        ]
        errors = await _run_parallel_steps(ctx, steps)
        assert len(errors) == 1
        assert errors[0][0] == "bad"
        # All three should have step_results
        assert len(ctx.step_results) == 3

    @pytest.mark.asyncio
    async def test_pipeline_stop_error_caught_in_parallel(self):
        """PipelineStopError in parallel is caught, not propagated."""
        ctx = PipelineContext(run_id="rp4")
        errors = await _run_parallel_steps(ctx, [("stop", _pipeline_stop_step)])
        assert len(errors) == 1
        assert isinstance(errors[0][1], PipelineStopError)


# ---------------------------------------------------------------------------
# build_default_steps
# ---------------------------------------------------------------------------


class TestBuildDefaultSteps:
    def test_returns_tuple_of_two_lists(self):
        seq, par = build_default_steps()
        assert isinstance(seq, list)
        assert isinstance(par, list)

    def test_sequential_step_count(self):
        seq, _ = build_default_steps()
        assert len(seq) == 5

    def test_parallel_step_count(self):
        _, par = build_default_steps()
        assert len(par) == 4

    def test_sequential_step_names(self):
        seq, _ = build_default_steps()
        names = [name for name, _ in seq]
        assert names == [
            StepName.CURATION,
            StepName.SUMMARIZATION,
            StepName.THEME_GENERATION,
            StepName.MARKDOWN_GENERATION,
            StepName.HTML_GENERATION,
        ]

    def test_parallel_step_names(self):
        _, par = build_default_steps()
        names = [name for name, _ in par]
        assert names == [
            StepName.ALTERNATES_HTML,
            StepName.EMAIL_SUBJECT,
            StepName.SOCIAL_MEDIA,
            StepName.LINKEDIN_CAROUSEL,
        ]

    def test_all_steps_are_callable(self):
        seq, par = build_default_steps()
        for _, fn in seq + par:
            assert callable(fn)

    def test_steps_are_real_implementations(self):
        """Default steps are wired to real pipeline modules, not noop stubs."""
        from ica.pipeline.steps import (
            run_alternates_html_step,
            run_curation_step,
            run_email_subject_step,
            run_html_generation_step,
            run_linkedin_carousel_step,
            run_markdown_generation_step,
            run_social_media_step,
            run_summarization_step,
            run_theme_generation_step,
        )

        seq, par = build_default_steps()

        # Sequential steps
        assert seq[0][1] is run_curation_step
        assert seq[1][1] is run_summarization_step
        assert seq[2][1] is run_theme_generation_step
        assert seq[3][1] is run_markdown_generation_step
        assert seq[4][1] is run_html_generation_step

        # Parallel steps
        assert par[0][1] is run_alternates_html_step
        assert par[1][1] is run_email_subject_step
        assert par[2][1] is run_social_media_step
        assert par[3][1] is run_linkedin_carousel_step


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_complete_pipeline_flow(self):
        """Simulate a realistic pipeline with data flowing through steps."""

        async def curation(ctx: PipelineContext) -> PipelineContext:
            ctx.newsletter_id = "NL-2026-08"
            ctx.articles = [
                {"url": "https://example.com/1", "title": "Article 1"},
                {"url": "https://example.com/2", "title": "Article 2"},
            ]
            return ctx

        async def summarization(ctx: PipelineContext) -> PipelineContext:
            ctx.summaries = [
                {"URL": a["url"], "Title": a["title"], "Summary": "..."}
                for a in ctx.articles
            ]
            ctx.summaries_json = '["summary1", "summary2"]'
            return ctx

        async def theme_gen(ctx: PipelineContext) -> PipelineContext:
            ctx.theme_name = "AI Revolution"
            ctx.theme_body = "The AI revolution..."
            ctx.formatted_theme = {"THEME": "AI Revolution"}
            return ctx

        async def markdown_gen(ctx: PipelineContext) -> PipelineContext:
            ctx.markdown_doc_id = "doc-md-123"
            return ctx

        async def html_gen(ctx: PipelineContext) -> PipelineContext:
            ctx.html_doc_id = "doc-html-456"
            return ctx

        parallel_ran: list[str] = []

        async def make_parallel(name: str):
            async def step(ctx: PipelineContext) -> PipelineContext:
                assert ctx.html_doc_id == "doc-html-456"
                parallel_ran.append(name)
                return ctx
            return step

        seq = [
            ("curation", curation),
            ("summarization", summarization),
            ("theme_generation", theme_gen),
            ("markdown_generation", markdown_gen),
            ("html_generation", html_gen),
        ]
        par = [
            ("alternates", await make_parallel("alternates")),
            ("email", await make_parallel("email")),
            ("social", await make_parallel("social")),
            ("linkedin", await make_parallel("linkedin")),
        ]

        ctx = PipelineContext(run_id="full1")
        result = await run_pipeline(ctx, sequential_steps=seq, parallel_steps=par)

        # Verify all data propagated
        assert result.newsletter_id == "NL-2026-08"
        assert len(result.articles) == 2
        assert len(result.summaries) == 2
        assert result.theme_name == "AI Revolution"
        assert result.markdown_doc_id == "doc-md-123"
        assert result.html_doc_id == "doc-html-456"

        # Verify all 9 steps ran
        assert len(result.step_results) == 9
        assert set(parallel_ran) == {"alternates", "email", "social", "linkedin"}

    @pytest.mark.asyncio
    async def test_mid_pipeline_failure_preserves_earlier_results(self):
        """When a step fails, earlier step results are still in context."""

        async def step_a(ctx: PipelineContext) -> PipelineContext:
            ctx.newsletter_id = "NL-PARTIAL"
            return ctx

        ctx = PipelineContext(run_id="fail1")
        with pytest.raises(RuntimeError):
            await run_pipeline(
                ctx,
                sequential_steps=[("a", step_a), ("b", _failing_step)],
            )
        # Step A's data should still be there
        assert ctx.newsletter_id == "NL-PARTIAL"
        # Step A should be completed, step B failed
        assert ctx.step_results[0].status == "completed"
        assert ctx.step_results[1].status == "failed"

    @pytest.mark.asyncio
    async def test_parallel_skipped_when_sequential_fails(self):
        """Parallel steps don't run if a sequential step fails."""
        parallel_called = False

        async def par_step(ctx: PipelineContext) -> PipelineContext:
            nonlocal parallel_called
            parallel_called = True
            return ctx

        ctx = PipelineContext(run_id="skip1")
        with pytest.raises(RuntimeError):
            await run_pipeline(
                ctx,
                sequential_steps=[("fail", _failing_step)],
                parallel_steps=[("par", par_step)],
            )
        assert not parallel_called

    @pytest.mark.asyncio
    async def test_all_parallel_failures_collected(self):
        """All parallel failures are recorded in step_results."""

        async def bad_a(ctx: PipelineContext) -> PipelineContext:
            raise ValueError("error A")

        async def bad_b(ctx: PipelineContext) -> PipelineContext:
            raise TypeError("error B")

        ctx = PipelineContext(run_id="allbad")
        result = await run_pipeline(ctx, parallel_steps=[("a", bad_a), ("b", bad_b)])
        failed = [r for r in result.step_results if r.status == "failed"]
        assert len(failed) == 2

    @pytest.mark.asyncio
    async def test_extra_dict_survives_pipeline(self):
        """The extra dict can carry step-specific data through the pipeline."""

        async def set_extra(ctx: PipelineContext) -> PipelineContext:
            ctx.extra["llm_model"] = "claude-sonnet"
            return ctx

        async def read_extra(ctx: PipelineContext) -> PipelineContext:
            assert ctx.extra["llm_model"] == "claude-sonnet"
            return ctx

        ctx = PipelineContext(run_id="extra1")
        result = await run_pipeline(
            ctx,
            sequential_steps=[("set", set_extra), ("read", read_extra)],
        )
        assert result.extra["llm_model"] == "claude-sonnet"
