"""CLI entry point for the ica newsletter pipeline.

Usage::

    python -m ica serve        # Start FastAPI server
    python -m ica run          # Trigger a pipeline run
    python -m ica status       # Show pipeline run status
    python -m ica guided       # Guided step-by-step pipeline test flow
    python -m ica collect-articles  # Manual article collection
    python -m ica config        # Edit LLM process configs via Google Docs
    python -m ica config system # Edit the shared system prompt via Google Docs

PRD Section 11.1: Secondary CLI interface for on-demand interaction and debugging.
"""

from __future__ import annotations

import asyncio
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="ica",
    help="AI newsletter generation pipeline.",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int = typer.Option(8000, help="Bind port."),
    reload: bool = typer.Option(False, help="Enable auto-reload for development."),
) -> None:
    """Start the FastAPI server."""
    import uvicorn

    uvicorn.run(
        "ica.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def run(
    trigger: str = typer.Option("cli", help="Label for what initiated this run."),
    base_url: str = typer.Option("http://localhost:8000", help="FastAPI server base URL."),
) -> None:
    """Trigger a pipeline run via the /trigger API endpoint."""
    asyncio.run(_trigger_run(trigger, base_url))


async def _trigger_run(trigger: str, base_url: str) -> None:
    """POST to /trigger and display the result."""
    import httpx

    url = f"{base_url.rstrip('/')}/trigger"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"trigger": trigger})
            resp.raise_for_status()
            data = resp.json()
            console.print("[green]Pipeline run started[/green]")
            console.print(f"  run_id: {data['run_id']}")
            console.print(f"  status: {data['status']}")
    except httpx.ConnectError:
        err_console.print(f"[red]Error:[/red] Cannot connect to {base_url}")
        err_console.print("Is the server running? Start it with: ica serve")
        raise typer.Exit(code=1) from None
    except httpx.HTTPStatusError as exc:
        err_console.print(f"[red]Error:[/red] {exc.response.status_code} {exc.response.text}")
        raise typer.Exit(code=1) from None


@app.command()
def status(
    run_id: str | None = typer.Argument(None, help="Specific run ID to check."),
    base_url: str = typer.Option("http://localhost:8000", help="FastAPI server base URL."),
) -> None:
    """Show pipeline run status from the /status API endpoint."""
    asyncio.run(_show_status(run_id, base_url))


async def _show_status(run_id: str | None, base_url: str) -> None:
    """GET /status or /status/{run_id} and display the result."""
    import httpx

    base = base_url.rstrip("/")
    url = f"{base}/status/{run_id}" if run_id else f"{base}/status"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        err_console.print(f"[red]Error:[/red] Cannot connect to {base_url}")
        err_console.print("Is the server running? Start it with: ica serve")
        raise typer.Exit(code=1) from None
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            err_console.print(f"[yellow]Run not found:[/yellow] {run_id}")
            raise typer.Exit(code=1) from None
        err_console.print(f"[red]Error:[/red] {exc.response.status_code} {exc.response.text}")
        raise typer.Exit(code=1) from None

    if run_id:
        # Single run display
        _print_single_run(data)
    else:
        # All runs table
        runs = data.get("runs", [])
        if not runs:
            console.print("[dim]No pipeline runs found.[/dim]")
            return
        _print_runs_table(runs)


def _print_single_run(data: dict[str, Any]) -> None:
    """Pretty-print a single pipeline run."""
    status_color = _status_color(data.get("status", ""))
    console.print(f"[bold]Run {data['run_id']}[/bold]")
    console.print(f"  status:       [{status_color}]{data['status']}[/{status_color}]")
    console.print(f"  trigger:      {data.get('trigger', '-')}")
    console.print(f"  started_at:   {data.get('started_at', '-')}")
    console.print(f"  completed_at: {data.get('completed_at') or '-'}")
    console.print(f"  current_step: {data.get('current_step') or '-'}")
    if data.get("error"):
        console.print(f"  [red]error: {data['error']}[/red]")


def _print_runs_table(runs: list[dict[str, Any]]) -> None:
    """Render pipeline runs as a Rich table."""
    table = Table(title="Pipeline Runs")
    table.add_column("Run ID", style="bold")
    table.add_column("Status")
    table.add_column("Trigger")
    table.add_column("Started")
    table.add_column("Step")

    for r in runs:
        color = _status_color(r.get("status", ""))
        table.add_row(
            r.get("run_id", ""),
            f"[{color}]{r.get('status', '')}[/{color}]",
            r.get("trigger", ""),
            r.get("started_at", ""),
            r.get("current_step") or "-",
        )
    console.print(table)


def _status_color(status: str) -> str:
    """Map a run status to a Rich color name."""
    return {
        "pending": "yellow",
        "running": "cyan",
        "completed": "green",
        "failed": "red",
    }.get(status, "white")


@app.command()
def guided(
    run_id: str | None = typer.Option(None, "--run-id", "-r", help="Resume an existing run."),
    store_dir: str = typer.Option(
        ".guided-runs", "--store-dir", help="Directory for persisted run state."
    ),
    list_runs: bool = typer.Option(False, "--list", "-l", help="List existing guided runs."),
) -> None:
    """Run the pipeline in guided mode — step-by-step with operator checkpoints.

    Each step pauses for approval before proceeding. You can continue, redo the
    current step, or stop. State is persisted to disk so you can resume after
    interruptions.
    """
    from pathlib import Path

    from ica.guided.state import TestRunStore

    store_path = Path(store_dir)

    if list_runs:
        store = TestRunStore(store_path)
        runs = store.list_runs()
        if not runs:
            console.print("[dim]No guided runs found.[/dim]")
        else:
            for rid in runs:
                state = store.load(rid)
                phase_str = state.phase.value
                step_info = f"step {state.current_step_index + 1}/{len(state.steps)}"
                console.print(f"  {rid}  {phase_str:<12}  {step_info}")
        return

    asyncio.run(_run_guided(run_id, store_path))


async def _run_guided(run_id: str | None, store_dir: Any) -> None:
    """Execute the guided pipeline flow."""
    from ica.guided.runner import run_guided

    try:
        state = await run_guided(
            run_id=run_id,
            store_dir=store_dir,
            console=console,
        )
        if state.phase.value == "completed":
            console.print("[green]Guided run completed successfully.[/green]")
        elif state.phase.value == "aborted":
            console.print("[yellow]Guided run stopped.[/yellow]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Run state has been saved.[/yellow]")
        console.print("Resume with: ica guided --run-id <run-id>")
    except Exception as exc:
        err_console.print(f"[red]Guided run failed:[/red] {exc}")
        raise typer.Exit(code=1) from None


@app.command(name="collect-articles")
def collect_articles(
    schedule: str = typer.Option(
        "daily",
        help="Schedule type: 'daily' (3 keywords) or 'every_2_days' (5 keywords).",
    ),
) -> None:
    """Run article collection manually.

    Searches via Brave Web Search, runs LLM relevance filtering,
    deduplicates by URL, and upserts into the articles table.
    Requires BRAVE_API_KEY and database credentials.
    """
    asyncio.run(_collect_articles(schedule))


async def _collect_articles(schedule: str) -> None:
    """Execute article collection and display results."""
    try:
        from ica.config.settings import get_settings
        from ica.pipeline.article_collection import collect_articles as _collect
        from ica.services.brave_search import BraveSearchClient

        settings = get_settings()
    except Exception as exc:
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        err_console.print("Ensure required environment variables are set (see .env.example).")
        raise typer.Exit(code=1) from None

    console.print(f"Collecting articles (schedule={schedule})...")

    try:
        import httpx

        from ica.db.repository import SqlArticleRepository
        from ica.db.session import get_session

        async with httpx.AsyncClient() as http_client:
            search_client = BraveSearchClient(
                api_key=settings.brave_api_key,
                http_client=http_client,  # type: ignore[arg-type]
            )
            async with get_session() as session:
                repository = SqlArticleRepository(session)
                result = await _collect(
                    client=search_client,
                    repository=repository,
                    schedule=schedule,
                )

        console.print("[green]Collection complete[/green]")
        console.print(f"  raw results:    {len(result.raw_results)}")
        console.print(f"  deduplicated:   {len(result.deduplicated)}")
        console.print(f"  articles:       {len(result.articles)}")
        console.print(f"  accepted:       {result.accepted_count}")
        console.print(f"  rejected:       {result.rejected_count}")
        console.print(f"  rows affected:  {result.rows_affected}")

        if result.articles:
            table = Table(title="Collected Articles")
            table.add_column("Title", max_width=60)
            table.add_column("Origin")
            table.add_column("Date")
            table.add_column("Status")
            for a in result.articles[:20]:
                table.add_row(
                    a.title, a.origin, str(a.publish_date), a.relevance_status or ""
                )
            if len(result.articles) > 20:
                console.print(f"  [dim]... and {len(result.articles) - 20} more[/dim]")
            console.print(table)

    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        err_console.print(f"[red]Collection failed:[/red] {exc}")
        raise typer.Exit(code=1) from None


@app.command(name="filter-logs")
def filter_logs(
    run_id: str | None = typer.Option(None, "--run-id", help="Filter by run_id."),
    step: str | None = typer.Option(None, "--step", help="Filter by step name."),
    level: str | None = typer.Option(
        None, "--level", help="Minimum log level (DEBUG/INFO/WARNING/ERROR/CRITICAL)."
    ),
    since: str | None = typer.Option(None, "--since", help="ISO datetime — entries at or after."),
    until: str | None = typer.Option(None, "--until", help="ISO datetime — entries before."),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON instead of formatted lines."),
) -> None:
    """Filter JSON pipeline logs from stdin.

    Reads JSON log lines from stdin and filters by run_id, step, level,
    and/or date range. Designed to be piped from ``docker compose logs``.
    """
    import sys

    from ica.cli.log_filter import filter_stream

    count = filter_stream(
        sys.stdin,
        sys.stdout,
        run_id=run_id,
        step=step,
        level=level,
        since=since,
        until=until,
        raw=raw,
    )
    if count == 0:
        err_console.print("No matching log entries found.")


config_app = typer.Typer(
    name="config",
    help="Edit LLM process configs via Google Docs.",
    invoke_without_command=True,
)
app.add_typer(config_app, name="config")


@config_app.callback(invoke_without_command=True)
def config_default(ctx: typer.Context) -> None:
    """Edit LLM process configs via Google Docs (default: list and edit)."""
    if ctx.invoked_subcommand is None:
        asyncio.run(_config_editor())


async def _config_editor() -> None:
    """Interactive config editor: list configs, open in Google Docs, sync back."""
    from ica.cli.config_editor import (
        format_config_table,
        format_sync_summary,
        list_all_configs,
    )
    from ica.config.settings import get_settings
    from ica.llm_configs.loader import load_process_config
    from ica.services.google_docs import GoogleDocsService
    from ica.services.prompt_editor import PromptEditorService

    # (1) Display numbered list of all configs.
    configs = list_all_configs()
    if not configs:
        err_console.print("[red]No LLM configs found.[/red]")
        raise typer.Exit(code=1)

    console.print(format_config_table(configs))

    # (2) Prompt for selection, validating 1-N or q.
    selection = typer.prompt(f"\nSelect a config to edit (1-{len(configs)} or q to quit)")
    if selection.strip().lower() == "q":
        console.print("[dim]Cancelled.[/dim]")
        return

    try:
        idx = int(selection) - 1
        if not (0 <= idx < len(configs)):
            raise ValueError
    except ValueError:
        err_console.print(f"[red]Invalid selection:[/red] {selection}")
        raise typer.Exit(code=1) from None

    process_name, _ = configs[idx]

    # (3) Instantiate services.
    try:
        settings = get_settings()
    except Exception as exc:
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        err_console.print("Ensure required environment variables are set (see .env.example).")
        raise typer.Exit(code=1) from None

    docs_service = GoogleDocsService(
        credentials_path=settings.google_service_account_credentials_path,
        drive_id=settings.google_shared_drive_id,
    )
    editor = PromptEditorService(docs_service)

    # (4) Start full edit and print Google Doc URL.
    url = await editor.start_full_edit(process_name)
    console.print(f"\n[bold]Edit in Google Docs:[/bold] {url}")

    # (5) Wait for user to finish editing.
    response = typer.prompt(
        "\nPress Enter to sync or q to cancel", default="", show_default=False
    )
    if response.strip().lower() == "q":
        console.print("[dim]Sync cancelled.[/dim]")
        return

    # (6) Sync from doc and display summary.
    old_config = load_process_config(process_name)
    new_config = await editor.sync_full_from_doc(process_name)

    changes: dict[str, str] = {}
    if old_config.model != new_config.model:
        changes["model"] = f"{old_config.model} -> {new_config.model}"
    if old_config.description != new_config.description:
        changes["description"] = (
            f"{len(old_config.description)} chars -> {len(new_config.description)} chars"
        )
    if old_config.prompts.instruction != new_config.prompts.instruction:
        changes["instruction"] = (
            f"{len(old_config.prompts.instruction)} chars"
            f" -> {len(new_config.prompts.instruction)} chars"
        )

    summary = format_sync_summary(process_name, old_config, new_config, changes)
    console.print(f"\n{summary}")

    # (7) Print git commit suggestion.
    console.print(
        f"\n[dim]Suggested commit:"
        f" git commit -m"
        f' "chore: update {process_name} LLM config v{new_config.metadata.version}"[/dim]'
    )


@config_app.command(name="system")
def config_system() -> None:
    """Edit the shared system prompt via Google Docs."""
    asyncio.run(_config_system_editor())


async def _config_system_editor() -> None:
    """Open the shared system prompt in Google Docs, then sync back."""
    from ica.config.settings import get_settings
    from ica.llm_configs.loader import load_system_prompt_config
    from ica.services.google_docs import GoogleDocsService
    from ica.services.prompt_editor import PromptEditorService

    try:
        settings = get_settings()
    except Exception as exc:
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        err_console.print("Ensure required environment variables are set (see .env.example).")
        raise typer.Exit(code=1) from None

    docs_service = GoogleDocsService(
        credentials_path=settings.google_service_account_credentials_path,
        drive_id=settings.google_shared_drive_id,
    )
    editor = PromptEditorService(docs_service)

    # Show current system prompt info.
    sp_config = load_system_prompt_config()
    console.print("[bold]Shared System Prompt[/bold]")
    console.print(f"  Length:  {len(sp_config.prompt):,} chars")
    console.print(f"  Version: {sp_config.metadata.version}")

    # Open in Google Docs.
    url = await editor.start_system_edit()
    console.print(f"\n[bold]Edit in Google Docs:[/bold] {url}")

    # Wait for user to finish editing.
    response = typer.prompt(
        "\nPress Enter to sync or q to cancel", default="", show_default=False
    )
    if response.strip().lower() == "q":
        console.print("[dim]Sync cancelled.[/dim]")
        return

    # Sync back.
    old_len = len(sp_config.prompt)
    prompt_text = await editor.sync_system_from_doc()

    updated = load_system_prompt_config()
    console.print("\n[bold]Sync complete[/bold]")
    console.print(f"  version: {sp_config.metadata.version} -> {updated.metadata.version}")
    console.print(f"  length:  {old_len:,} -> {len(prompt_text):,} chars")


def main() -> None:
    """Entry point for ``python -m ica`` and the ``ica`` console script."""
    app()


if __name__ == "__main__":
    main()
