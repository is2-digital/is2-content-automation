"""Log filter for JSON-formatted pipeline logs.

Parses Docker Compose log output (with optional container prefix) and
filters by run_id, step, level, and date range. Uses only stdlib modules.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from typing import IO, Any

# Docker Compose prefix pattern: "container  | " or "container  | 2026-02-27T10:00:00.000Z "
_DOCKER_PREFIX_RE = re.compile(r"^[\w._-]+\s+\|\s+(?:\d{4}-\d{2}-\d{2}T[\d:.]+Z?\s+)?")

# Log level ordering for minimum-level filtering
_LEVEL_ORDER = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}


def parse_line(line: str) -> dict[str, Any] | None:
    """Parse a single log line into a dict.

    Strips Docker Compose container prefixes, then attempts JSON parsing.
    Returns ``None`` for non-JSON lines.
    """
    stripped = line.strip()
    if not stripped:
        return None

    # Try parsing as-is first
    try:
        return json.loads(stripped)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError):
        pass

    # Strip Docker Compose prefix and try again
    cleaned = _DOCKER_PREFIX_RE.sub("", stripped)
    if cleaned != stripped:
        try:
            return json.loads(cleaned)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def matches_filters(
    entry: dict[str, Any],
    *,
    run_id: str | None = None,
    step: str | None = None,
    level: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> bool:
    """Check whether a log entry matches all specified filters.

    Args:
        entry: Parsed JSON log entry.
        run_id: Filter by run_id (exact match).
        step: Filter by step name (exact match).
        level: Minimum log level (e.g., "ERROR" matches ERROR and CRITICAL).
        since: ISO datetime string — only entries at or after this time.
        until: ISO datetime string — only entries before this time.
    """
    if run_id is not None:
        entry_run_id = entry.get("run_id", "")
        if entry_run_id != run_id:
            return False

    if step is not None:
        entry_step = entry.get("step", "")
        if entry_step != step:
            return False

    if level is not None:
        entry_level = entry.get("level", "INFO").upper()
        min_order = _LEVEL_ORDER.get(level.upper(), 0)
        entry_order = _LEVEL_ORDER.get(entry_level, 0)
        if entry_order < min_order:
            return False

    timestamp_str = entry.get("timestamp", "")
    if timestamp_str and (since is not None or until is not None):
        try:
            # Handle both "Z" suffix and "+00:00" offset
            ts = timestamp_str.replace("Z", "+00:00")
            entry_dt = datetime.fromisoformat(ts)
        except ValueError:
            return False

        if since is not None:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if entry_dt < since_dt:
                return False

        if until is not None:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if entry_dt >= until_dt:
                return False

    return True


def format_entry(entry: dict[str, Any]) -> str:
    """Format a log entry as a human-readable one-line string.

    Format: ``timestamp  LEVEL  message  [run=x step=y]``
    """
    timestamp = entry.get("timestamp", "-")
    level = entry.get("level", "INFO")
    message = entry.get("message", "")

    parts = [timestamp, f"{level:<8}", message]

    # Add context vars if present
    ctx_parts = []
    if entry.get("run_id"):
        ctx_parts.append(f"run={entry['run_id']}")
    if entry.get("step"):
        ctx_parts.append(f"step={entry['step']}")
    if ctx_parts:
        parts.append(f"[{' '.join(ctx_parts)}]")

    # Add exception info if present
    exc = entry.get("exception") or entry.get("exc_info")
    if exc:
        parts.append(f"  EXC: {exc}")

    return "  ".join(parts)


def filter_stream(
    input_stream: IO[str],
    output_stream: IO[str],
    *,
    run_id: str | None = None,
    step: str | None = None,
    level: str | None = None,
    since: str | None = None,
    until: str | None = None,
    raw: bool = False,
) -> int:
    """Read log lines from *input_stream*, filter, and write to *output_stream*.

    Args:
        input_stream: Readable text stream (e.g. ``sys.stdin``).
        output_stream: Writable text stream (e.g. ``sys.stdout``).
        run_id: Filter by run_id.
        step: Filter by step name.
        level: Minimum log level.
        since: ISO datetime — entries at or after.
        until: ISO datetime — entries before.
        raw: If True, output raw JSON instead of formatted lines.

    Returns:
        Number of matching entries.
    """
    count = 0
    for line in input_stream:
        entry = parse_line(line)
        if entry is None:
            continue
        if not matches_filters(
            entry, run_id=run_id, step=step, level=level, since=since, until=until
        ):
            continue
        if raw:
            output_stream.write(json.dumps(entry) + "\n")
        else:
            output_stream.write(format_entry(entry) + "\n")
        count += 1
    return count


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for standalone usage."""
    import argparse

    parser = argparse.ArgumentParser(description="Filter ica JSON logs")
    parser.add_argument("--run-id", help="Filter by run_id")
    parser.add_argument("--step", help="Filter by step name")
    parser.add_argument(
        "--level", help="Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    parser.add_argument("--since", help="ISO datetime — entries at or after")
    parser.add_argument("--until", help="ISO datetime — entries before")
    parser.add_argument("--raw", action="store_true", help="Output raw JSON")
    args = parser.parse_args(argv)

    count = filter_stream(
        sys.stdin,
        sys.stdout,
        run_id=args.run_id,
        step=args.step,
        level=args.level,
        since=args.since,
        until=args.until,
        raw=args.raw,
    )
    if count == 0:
        sys.stderr.write("No matching log entries found.\n")


if __name__ == "__main__":
    main()
