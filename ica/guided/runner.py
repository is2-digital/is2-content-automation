"""Guided pipeline runner — executes the pipeline step-by-step with operator checkpoints.

Wraps the :class:`~ica.guided.state.TestRunStateMachine` to drive each pipeline
step, display progress via Rich console output, and prompt the operator at
checkpoints (continue / redo / stop).

All 9 pipeline steps run sequentially in guided mode (the 4 normally-parallel
output steps are flattened into the sequence).
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ica.guided.state import (
    InvalidTransitionError,
    OperatorAction,
    OperatorDecision,
    RunPhase,
    StepStatus,
    TestRunNotFoundError,
    TestRunState,
    TestRunStateMachine,
    TestRunStore,
)
from ica.logging import get_logger
from ica.pipeline.orchestrator import PipelineContext, PipelineStep, StepName, run_step

logger = get_logger(__name__)

DEFAULT_STORE_DIR = Path(".guided-runs")

# Maps StepName → (step_name_str, PipelineStep callable) built lazily
_step_registry: dict[str, PipelineStep] | None = None


def _build_step_registry() -> dict[str, PipelineStep]:
    """Build a flat map of step name → step function for all 9 pipeline steps."""
    from ica.pipeline.orchestrator import build_default_steps

    sequential, parallel = build_default_steps()
    registry: dict[str, PipelineStep] = {}
    for name, fn in [*sequential, *parallel]:
        registry[name] = fn
    return registry


def get_step_fn(step_name: StepName) -> PipelineStep:
    """Look up the pipeline step function for a given step name."""
    global _step_registry
    if _step_registry is None:
        _step_registry = _build_step_registry()
    return _step_registry[step_name.value]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_STEP_STATUS_STYLE = {
    StepStatus.PENDING: "dim",
    StepStatus.RUNNING: "cyan bold",
    StepStatus.COMPLETED: "green",
    StepStatus.FAILED: "red",
}

_PHASE_STYLE = {
    RunPhase.NOT_STARTED: "dim",
    RunPhase.RUNNING: "cyan",
    RunPhase.CHECKPOINT: "yellow",
    RunPhase.COMPLETED: "green bold",
    RunPhase.ABORTED: "red",
}


def render_run_header(state: TestRunState, console: Console) -> None:
    """Print a summary header for the current guided run."""
    phase_style = _PHASE_STYLE.get(state.phase, "white")
    console.print(
        Panel(
            f"[bold]Guided Run[/bold]  {state.run_id}\n"
            f"Phase: [{phase_style}]{state.phase.value}[/{phase_style}]  "
            f"Step: {state.current_step_index + 1}/{len(state.steps)}",
            title="ica guided",
            border_style="blue",
        )
    )


def render_step_table(state: TestRunState, console: Console) -> None:
    """Render a table of all steps with their current status."""
    table = Table(title="Pipeline Steps", show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Step", min_width=20)
    table.add_column("Status", min_width=12)
    table.add_column("Attempt", justify="right", width=7)
    table.add_column("Artifacts", min_width=20)

    for i, step in enumerate(state.steps):
        style = _STEP_STATUS_STYLE.get(step.status, "white")
        is_current = i == state.current_step_index
        marker = ">" if is_current else " "
        artifacts_str = ", ".join(f"{k}={v}" for k, v in step.artifacts.items()) or "-"
        table.add_row(
            f"{marker}{i + 1}",
            step.name,
            f"[{style}]{step.status.value}[/{style}]",
            str(step.attempt),
            artifacts_str if step.status != StepStatus.PENDING else "-",
        )

    console.print(table)


def render_checkpoint(state: TestRunState, console: Console) -> None:
    """Display checkpoint information after a step completes or fails."""
    step = state.current_step
    if step.status == StepStatus.COMPLETED:
        console.print(f"\n[green]Step '{step.name}' completed[/green] (attempt {step.attempt})")
        if step.artifacts:
            for key, val in step.artifacts.items():
                console.print(f"  {key}: {val}")
    elif step.status == StepStatus.FAILED:
        console.print(f"\n[red]Step '{step.name}' failed[/red] (attempt {step.attempt})")
        if step.error:
            console.print(f"  Error: {step.error}")


# ---------------------------------------------------------------------------
# Operator prompt
# ---------------------------------------------------------------------------

# Valid action inputs — map user shorthand to OperatorAction
_ACTION_MAP: dict[str, OperatorAction] = {
    "c": OperatorAction.CONTINUE,
    "continue": OperatorAction.CONTINUE,
    "r": OperatorAction.REDO,
    "redo": OperatorAction.REDO,
    "s": OperatorAction.STOP,
    "stop": OperatorAction.STOP,
}


def parse_operator_input(raw: str) -> OperatorAction | None:
    """Parse operator keyboard input into an action. Returns None if invalid."""
    return _ACTION_MAP.get(raw.strip().lower())


def prompt_operator(
    state: TestRunState,
    console: Console,
    *,
    prompt_fn: Any = None,
) -> OperatorAction:
    """Prompt the operator for a decision at a checkpoint.

    Args:
        state: Current test run state.
        console: Rich console for output.
        prompt_fn: Optional callable for input (default: ``input``). Accepts
            a prompt string and returns user input. Used for testing.

    Returns:
        The chosen operator action.
    """
    if prompt_fn is None:
        prompt_fn = input

    step = state.current_step
    can_continue = step.status == StepStatus.COMPLETED

    options = []
    if can_continue:
        if state.is_last_step:
            options.append("[C]omplete")
        else:
            options.append("[C]ontinue")
    options.append("[R]edo")
    options.append("[S]top")

    options_str = " / ".join(options)

    while True:
        try:
            raw = prompt_fn(f"\n{options_str}: ")
        except (EOFError, KeyboardInterrupt):
            return OperatorAction.STOP

        action = parse_operator_input(raw)
        if action is None:
            console.print("[yellow]Invalid choice.[/yellow] Enter c, r, or s.")
            continue
        if action == OperatorAction.CONTINUE and not can_continue:
            console.print(
                "[yellow]Cannot continue — step failed.[/yellow] Choose [R]edo or [S]top."
            )
            continue
        return action


# ---------------------------------------------------------------------------
# Context snapshot helpers
# ---------------------------------------------------------------------------


def snapshot_context(ctx: PipelineContext) -> dict[str, Any]:
    """Serialize a PipelineContext to a JSON-safe dict for persistence."""
    data = asdict(ctx)
    # StepResult contains datetime objects — convert to ISO strings
    for sr in data.get("step_results", []):
        for key in ("started_at", "completed_at"):
            val = sr.get(key)
            if val is not None and not isinstance(val, str):
                sr[key] = val.isoformat()
    return data


def restore_context(snapshot: dict[str, Any]) -> PipelineContext:
    """Rebuild a PipelineContext from a persisted snapshot."""
    # Drop step_results — they can't be easily reconstructed to frozen dataclasses
    # and aren't needed for resuming pipeline execution (the guided state tracks this)
    snapshot.pop("step_results", None)
    return PipelineContext(**snapshot)


# ---------------------------------------------------------------------------
# Guided runner
# ---------------------------------------------------------------------------


async def run_guided(
    *,
    run_id: str | None = None,
    store_dir: Path = DEFAULT_STORE_DIR,
    console: Console | None = None,
    prompt_fn: Any = None,
    seed: int | None = None,
    start_step: str | None = None,
    slack_override: Any = None,
) -> TestRunState:
    """Execute the guided pipeline flow.

    Creates or resumes a test run, executing each step and pausing at
    checkpoints for operator decisions.

    Args:
        run_id: Existing run ID to resume. If ``None``, starts a new run.
        store_dir: Directory for persisted run state files.
        console: Rich console for output (default: new Console).
        prompt_fn: Optional callable for operator input (for testing).
        seed: If provided, auto-provision fixture data for the run using
            :class:`~ica.guided.fixtures.FixtureProvider`.  When combined
            with *start_step*, provisions prerequisite data so the step
            can run without prior steps having executed.
        start_step: Step name to begin from (e.g. ``"theme_generation"``).
            Requires *seed* to provision prerequisite data.
        slack_override: Optional :class:`~ica.guided.slack_adapter.GuidedSlackAdapter`
            (or any object implementing the ``SlackService`` interface).  When
            provided, it is installed as the shared Slack service so all
            pipeline steps use it instead of creating a new ``SlackService``.

    Returns:
        The final :class:`TestRunState` after the run completes or is stopped.
    """
    if console is None:
        console = Console()

    store = TestRunStore(store_dir)

    # --- Create or resume ---
    if run_id:
        try:
            state = store.load(run_id)
        except TestRunNotFoundError:
            console.print(f"[red]Run not found:[/red] {run_id}")
            console.print(f"Available runs: {', '.join(store.list_runs()) or 'none'}")
            return TestRunState(run_id=run_id, phase=RunPhase.ABORTED)

        sm = TestRunStateMachine(state, store)

        if state.phase == RunPhase.RUNNING:
            console.print(f"[yellow]Resuming interrupted run {run_id}[/yellow]")
            sm.resume()
        elif state.phase == RunPhase.CHECKPOINT:
            console.print(f"[yellow]Resuming run {run_id} at checkpoint[/yellow]")
        elif state.phase in (RunPhase.COMPLETED, RunPhase.ABORTED):
            console.print(f"[dim]Run {run_id} is already {state.phase.value}.[/dim]")
            return state
        elif state.phase == RunPhase.NOT_STARTED:
            pass  # Will start below
        ctx = (
            restore_context(state.context_snapshot)
            if state.context_snapshot
            else PipelineContext()
        )
    else:
        run_id = str(uuid.uuid4())[:8]
        state = TestRunState(run_id=run_id)
        sm = TestRunStateMachine(state, store)

        # --- Fixture provisioning ---
        if seed is not None:
            from ica.guided.fixtures import FixtureProvider

            provider = FixtureProvider(seed=seed)
            if start_step:
                ctx = provider.for_step(start_step)
                console.print(
                    f"[cyan]Provisioned fixture data for step '{start_step}' (seed={seed})[/cyan]"
                )
            else:
                ctx = provider.for_full_run()
                console.print(f"[cyan]Using fixture seed={seed}[/cyan]")
        else:
            ctx = PipelineContext()

    ctx.run_id = run_id
    console.print(f"[bold]Run ID:[/bold] {run_id}")
    console.print(f"[bold]State dir:[/bold] {store_dir.resolve()}")

    # --- Install Slack override ---
    _prev_shared: Any = None
    if slack_override is not None:
        from ica.services.slack import get_shared_service, set_shared_service

        _prev_shared = get_shared_service()
        set_shared_service(slack_override)  # type: ignore[arg-type]
        console.print("[cyan]Using Slack override adapter[/cyan]")

    # --- Main loop ---
    while True:
        render_run_header(state, console)
        render_step_table(state, console)

        # Start if not started
        if state.phase == RunPhase.NOT_STARTED:
            sm.start()

        # Execute step if running
        if state.phase == RunPhase.RUNNING:
            step_name = state.current_step_name
            step_fn = get_step_fn(step_name)
            console.print(f"\n[cyan]Running step: {step_name.value}[/cyan]")

            # Tell the Slack adapter which step is about to run
            if slack_override is not None and hasattr(slack_override, "set_step"):
                slack_override.set_step(step_name.value)

            try:
                ctx = await run_step(step_name.value, step_fn, ctx)
                # Extract artifacts from context for this step
                artifacts = _extract_artifacts(step_name, ctx)
                sm.complete_step(artifacts=artifacts)
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted.[/yellow] State saved.")
                sm.save_context(snapshot_context(ctx))
                _restore_shared_service(_prev_shared, slack_override)
                return state
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                console.print(f"\n[red]Step failed:[/red] {error_msg}")
                with contextlib.suppress(InvalidTransitionError):
                    sm.fail_step(error_msg)
            finally:
                sm.save_context(snapshot_context(ctx))
                # Merge Slack interactions into step artifacts and decisions
                if slack_override is not None and hasattr(
                    slack_override, "drain_step_interactions"
                ):
                    _merge_slack_interactions(slack_override, step_name, state)

        # Checkpoint — show results and prompt
        if state.phase == RunPhase.CHECKPOINT:
            render_checkpoint(state, console)
            action = prompt_operator(state, console, prompt_fn=prompt_fn)
            sm.apply_decision(action)

            if state.phase == RunPhase.COMPLETED:
                console.print("\n[green bold]All steps completed![/green bold]")
                render_step_table(state, console)
                _restore_shared_service(_prev_shared, slack_override)
                return state

            if state.phase == RunPhase.ABORTED:
                console.print("\n[yellow]Run stopped by operator.[/yellow]")
                _restore_shared_service(_prev_shared, slack_override)
                return state

            if state.phase == RunPhase.NOT_STARTED:
                # Restart — reset context
                ctx = PipelineContext(run_id=run_id)
                continue

            # RUNNING (continue or redo) — loop back
            continue

        # Completed or aborted (shouldn't reach here normally)
        if state.phase in (RunPhase.COMPLETED, RunPhase.ABORTED):
            _restore_shared_service(_prev_shared, slack_override)
            return state


def _restore_shared_service(prev: Any, slack_override: Any) -> None:
    """Restore the previous shared Slack service after a guided run."""
    if slack_override is not None:
        from ica.services.slack import set_shared_service

        set_shared_service(prev)  # type: ignore[arg-type]


def _merge_slack_interactions(
    adapter: Any,
    step_name: StepName,
    state: TestRunState,
) -> None:
    """Merge adapter interaction records into step artifacts and decision history."""
    interactions = adapter.drain_step_interactions(step_name.value)
    if not interactions:
        return

    step_record = state.current_step
    step_record.artifacts["slack_interactions"] = interactions

    for interaction in interactions:
        method = interaction.get("method", "")
        if method in ("send_and_wait", "send_and_wait_form", "send_and_wait_freetext"):
            response = interaction.get("response")
            state.decisions.append(
                OperatorDecision(
                    step=step_name.value,
                    action=f"slack:{method}",
                    timestamp=interaction.get("timestamp", ""),
                    note=str(response) if response else None,
                )
            )


def _extract_artifacts(step_name: StepName, ctx: PipelineContext) -> dict[str, Any]:
    """Pull notable artifacts from context after a step completes."""
    artifacts: dict[str, Any] = {}

    if step_name == StepName.CURATION:
        artifacts["article_count"] = len(ctx.articles)
        if ctx.newsletter_id:
            artifacts["newsletter_id"] = ctx.newsletter_id

    elif step_name == StepName.SUMMARIZATION:
        artifacts["summary_count"] = len(ctx.summaries)

    elif step_name == StepName.THEME_GENERATION:
        if ctx.theme_name:
            artifacts["theme_name"] = ctx.theme_name

    elif step_name == StepName.MARKDOWN_GENERATION:
        if ctx.markdown_doc_id:
            artifacts["markdown_doc_id"] = ctx.markdown_doc_id

    elif step_name == StepName.HTML_GENERATION:
        if ctx.html_doc_id:
            artifacts["html_doc_id"] = ctx.html_doc_id

    elif step_name == StepName.EMAIL_SUBJECT:
        subject = ctx.extra.get("email_subject")
        if subject:
            artifacts["email_subject"] = subject[:60]

    elif step_name == StepName.SOCIAL_MEDIA:
        doc_id = ctx.extra.get("social_media_doc_id")
        if doc_id:
            artifacts["social_media_doc_id"] = doc_id

    elif step_name == StepName.LINKEDIN_CAROUSEL:
        doc_id = ctx.extra.get("linkedin_carousel_doc_id")
        if doc_id:
            artifacts["linkedin_carousel_doc_id"] = doc_id

    elif step_name == StepName.ALTERNATES_HTML:
        unused = ctx.extra.get("alternates_unused_summaries", [])
        artifacts["unused_article_count"] = len(unused)

    return artifacts
