"""Pipeline orchestrator — wires all steps together.

Runs the newsletter pipeline as a sequence of async steps with parallel
output generation at the end:

    Curation → Summarization → Theme Generation → Markdown Generation
    → HTML Generation → [parallel] Alternates, Email Subject, Social Media,
                                    LinkedIn Carousel

Each step receives and returns a :class:`PipelineContext` that accumulates
state across the pipeline.  The orchestrator tracks per-step timing, manages
structured-logging context (``run_id`` / ``step``), and converts
:class:`~ica.errors.PipelineStopError` into a ``FAILED`` run status.

See PRD Section 11.6.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from ica.errors import PipelineStopError
from ica.logging import bind_context, get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Step names
# ---------------------------------------------------------------------------


class StepName(str, Enum):
    """Canonical names for each pipeline step."""

    CURATION = "curation"
    SUMMARIZATION = "summarization"
    THEME_GENERATION = "theme_generation"
    MARKDOWN_GENERATION = "markdown_generation"
    HTML_GENERATION = "html_generation"
    ALTERNATES_HTML = "alternates_html"
    EMAIL_SUBJECT = "email_subject"
    SOCIAL_MEDIA = "social_media"
    LINKEDIN_CAROUSEL = "linkedin_carousel"


# ---------------------------------------------------------------------------
# Pipeline context — accumulated state between steps
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    """Accumulated pipeline state passed between steps.

    Each sequential step reads data from previous steps and writes its own
    outputs into the context.  Parallel output steps (6a-6d) read from the
    context but do not propagate further.

    Attributes:
        run_id: Unique identifier for this pipeline execution.
        trigger: What initiated the run (e.g. ``"manual"``, ``"scheduler"``).
        newsletter_id: The newsletter edition ID, set during curation.
        articles: Approved articles from Step 1 (PRD Section 5.1).
        summaries: Summarised articles from Step 2 (PRD Section 5.2).
        summaries_json: JSON-serialised summaries for Step 3 LLM input.
        formatted_theme: Parsed theme structure from Step 3 (PRD Section 5.3).
        theme_name: Human-readable theme title.
        theme_body: Raw theme body text.
        theme_summary: Theme summary text.
        markdown_doc_id: Google Doc ID from Step 4 (PRD Section 5.4).
        html_doc_id: Google Doc ID from Step 5 (PRD Section 5.5).
        step_results: Timing and status for each completed step.
        extra: Arbitrary step-specific data that doesn't warrant a top-level field.
    """

    run_id: str = ""
    trigger: str = "manual"

    # Step 1: Curation
    newsletter_id: str | None = None
    articles: list[dict[str, Any]] = field(default_factory=list)

    # Step 2: Summarization
    summaries: list[dict[str, Any]] = field(default_factory=list)
    summaries_json: str = ""

    # Step 3: Theme Generation + Selection
    formatted_theme: dict[str, Any] = field(default_factory=dict)
    theme_name: str = ""
    theme_body: str = ""
    theme_summary: str | None = None

    # Step 4: Markdown Generation
    markdown_doc_id: str | None = None

    # Step 5: HTML Generation
    html_doc_id: str | None = None

    # Tracking
    step_results: list[StepResult] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    """Outcome of a single pipeline step."""

    step: str
    status: str  # "completed" or "failed"
    started_at: datetime
    completed_at: datetime
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        """Wall-clock seconds the step took."""
        return (self.completed_at - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# Step protocol — each pipeline step is an async callable
# ---------------------------------------------------------------------------


class PipelineStep(Protocol):
    """Protocol for a pipeline step function.

    Each step receives the current context, performs its work, and returns
    the (possibly mutated) context.
    """

    async def __call__(self, ctx: PipelineContext) -> PipelineContext: ...


# ---------------------------------------------------------------------------
# Step runner — executes a step with logging + timing + error recording
# ---------------------------------------------------------------------------


async def run_step(
    step_name: str,
    step_fn: PipelineStep,
    ctx: PipelineContext,
) -> PipelineContext:
    """Execute a single pipeline step with timing and logging.

    Args:
        step_name: Human-readable step identifier (from :class:`StepName`).
        step_fn: The async step function.
        ctx: Current pipeline context.

    Returns:
        The updated context (as returned by *step_fn*).

    Raises:
        PipelineStopError: Re-raised from the step if the pipeline must halt.
        Exception: Any unexpected error from the step.
    """
    started = datetime.now(timezone.utc)
    logger.info("Step %s starting", step_name)

    try:
        async with bind_context(step=step_name):
            ctx = await step_fn(ctx)
    except PipelineStopError:
        completed = datetime.now(timezone.utc)
        ctx.step_results.append(
            StepResult(
                step=step_name,
                status="failed",
                started_at=started,
                completed_at=completed,
                error="PipelineStopError",
            )
        )
        raise
    except Exception as exc:
        completed = datetime.now(timezone.utc)
        ctx.step_results.append(
            StepResult(
                step=step_name,
                status="failed",
                started_at=started,
                completed_at=completed,
                error=str(exc),
            )
        )
        raise

    completed = datetime.now(timezone.utc)
    result = StepResult(
        step=step_name,
        status="completed",
        started_at=started,
        completed_at=completed,
    )
    ctx.step_results.append(result)
    logger.info(
        "Step %s completed in %.2fs",
        step_name,
        result.duration_seconds,
    )
    return ctx


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


async def run_pipeline(
    ctx: PipelineContext,
    *,
    sequential_steps: list[tuple[str, PipelineStep]] | None = None,
    parallel_steps: list[tuple[str, PipelineStep]] | None = None,
) -> PipelineContext:
    """Execute the full newsletter pipeline.

    Runs *sequential_steps* one-by-one (each receives and updates the
    context), then launches *parallel_steps* concurrently via
    :func:`asyncio.gather`.

    If any sequential step raises :class:`PipelineStopError`, the pipeline
    halts immediately.  Parallel step failures are collected and logged but
    do not prevent other parallel steps from completing.

    Args:
        ctx: Initial pipeline context (must have ``run_id`` set).
        sequential_steps: Ordered list of ``(name, step_fn)`` pairs for the
            main pipeline.  Defaults to an empty list (useful for testing).
        parallel_steps: List of ``(name, step_fn)`` pairs to run concurrently
            after all sequential steps complete.  Defaults to an empty list.

    Returns:
        The final pipeline context with all step results recorded.
    """
    if sequential_steps is None:
        sequential_steps = []
    if parallel_steps is None:
        parallel_steps = []

    async with bind_context(run_id=ctx.run_id):
        # --- Sequential steps ---
        for step_name, step_fn in sequential_steps:
            ctx = await run_step(step_name, step_fn, ctx)

        # --- Parallel steps ---
        if parallel_steps:
            logger.info(
                "Launching %d parallel output steps",
                len(parallel_steps),
            )
            errors = await _run_parallel_steps(ctx, parallel_steps)
            if errors:
                logger.warning(
                    "%d of %d parallel steps failed",
                    len(errors),
                    len(parallel_steps),
                )

    return ctx


async def _run_parallel_steps(
    ctx: PipelineContext,
    steps: list[tuple[str, PipelineStep]],
) -> list[tuple[str, Exception]]:
    """Run steps concurrently, collecting failures.

    Each parallel step receives the *same* context snapshot.  Failures are
    logged but do not cancel sibling steps.

    Returns:
        A list of ``(step_name, exception)`` for any steps that failed.
    """
    errors: list[tuple[str, Exception]] = []

    async def _safe_run(name: str, fn: PipelineStep) -> None:
        started = datetime.now(timezone.utc)
        try:
            async with bind_context(step=name):
                await fn(ctx)
            completed = datetime.now(timezone.utc)
            ctx.step_results.append(
                StepResult(
                    step=name,
                    status="completed",
                    started_at=started,
                    completed_at=completed,
                )
            )
            logger.info(
                "Parallel step %s completed in %.2fs",
                name,
                (completed - started).total_seconds(),
            )
        except Exception as exc:
            completed = datetime.now(timezone.utc)
            ctx.step_results.append(
                StepResult(
                    step=name,
                    status="failed",
                    started_at=started,
                    completed_at=completed,
                    error=str(exc),
                )
            )
            errors.append((name, exc))
            logger.exception("Parallel step %s failed", name)

    await asyncio.gather(*[_safe_run(n, f) for n, f in steps])
    return errors


# ---------------------------------------------------------------------------
# Default step stubs — no-op implementations for steps not yet wired
# ---------------------------------------------------------------------------


async def _noop_step(ctx: PipelineContext) -> PipelineContext:
    """Placeholder step that does nothing."""
    return ctx


def build_default_steps() -> (
    tuple[list[tuple[str, PipelineStep]], list[tuple[str, PipelineStep]]]
):
    """Return the default sequential and parallel step lists.

    All steps start as no-ops.  As each pipeline module is completed, its
    real implementation replaces the corresponding stub here.

    Returns:
        ``(sequential_steps, parallel_steps)`` ready for :func:`run_pipeline`.
    """
    sequential: list[tuple[str, PipelineStep]] = [
        (StepName.CURATION, _noop_step),
        (StepName.SUMMARIZATION, _noop_step),
        (StepName.THEME_GENERATION, _noop_step),
        (StepName.MARKDOWN_GENERATION, _noop_step),
        (StepName.HTML_GENERATION, _noop_step),
    ]
    parallel: list[tuple[str, PipelineStep]] = [
        (StepName.ALTERNATES_HTML, _noop_step),
        (StepName.EMAIL_SUBJECT, _noop_step),
        (StepName.SOCIAL_MEDIA, _noop_step),
        (StepName.LINKEDIN_CAROUSEL, _noop_step),
    ]
    return sequential, parallel
