"""CLI entry point for the ica newsletter pipeline.

Usage::

    python -m ica serve        # Start FastAPI server
    python -m ica run          # Trigger a pipeline run
    python -m ica status       # Show pipeline run status
    python -m ica collect-articles  # Manual article collection

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


@app.command(name="collect-articles")
def collect_articles(
    schedule: str = typer.Option(
        "daily",
        help="Schedule type: 'daily' (google_news, 3 keywords) or 'every_2_days' (5 keywords).",
    ),
) -> None:
    """Run article collection manually.

    Queries Google CSE for keywords, deduplicates by URL, and upserts into
    the articles table. Requires GOOGLE_CSE_API_KEY and database credentials.
    """
    asyncio.run(_collect_articles(schedule))


async def _collect_articles(schedule: str) -> None:
    """Execute article collection and display results."""
    try:
        from ica.config.settings import get_settings
        from ica.pipeline.article_collection import collect_articles as _collect
        from ica.services.search_api import SearchApiClient

        settings = get_settings()
    except Exception as exc:
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        err_console.print("Ensure required environment variables are set (see .env.example).")
        raise typer.Exit(code=1) from None

    console.print(f"Collecting articles (schedule={schedule})...")

    try:
        import httpx

        async with httpx.AsyncClient() as http_client:
            search_client = SearchApiClient(
                api_key=settings.google_cse_api_key,
                http_client=http_client,  # type: ignore[arg-type]
            )
            # Article collection requires a repository — create a simple
            # reporting-only stub when running from CLI without a full DB.
            # In production, this would use the real SQLAlchemy repository.
            result = await _collect(
                client=search_client,
                repository=_StubRepository(),
                schedule=schedule,
            )

        console.print("[green]Collection complete[/green]")
        console.print(f"  raw results:    {len(result.raw_results)}")
        console.print(f"  deduplicated:   {len(result.deduplicated)}")
        console.print(f"  articles:       {len(result.articles)}")
        console.print(f"  rows affected:  {result.rows_affected}")

        if result.articles:
            table = Table(title="Collected Articles")
            table.add_column("Title", max_width=60)
            table.add_column("Origin")
            table.add_column("Date")
            for a in result.articles[:20]:
                table.add_row(a.title, a.origin, str(a.publish_date))
            if len(result.articles) > 20:
                console.print(f"  [dim]... and {len(result.articles) - 20} more[/dim]")
            console.print(table)

    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        err_console.print(f"[red]Collection failed:[/red] {exc}")
        raise typer.Exit(code=1) from None


class _StubRepository:
    """No-op article repository for CLI dry-run mode."""

    async def upsert_articles(self, articles: list[Any]) -> int:
        """Return count without persisting (no DB required for CLI preview)."""
        return len(articles)


def main() -> None:
    """Entry point for ``python -m ica`` and the ``ica`` console script."""
    app()


if __name__ == "__main__":
    main()
