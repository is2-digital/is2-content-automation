"""Core config editor module for listing, viewing, and syncing LLM process configs.

Provides helpers used by the ``ica config`` CLI commands and the
:class:`~ica.services.prompt_editor.PromptEditorService` Google Docs workflow.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from rich.table import Table

from ica.llm_configs.loader import load_process_config, save_process_config
from ica.llm_configs.schema import ProcessConfig

# Directory containing JSON config files (same as ica/llm_configs/).
_CONFIGS_DIR = Path(__file__).resolve().parent.parent / "llm_configs"

# Section header pattern used in Google Docs content.
_SECTION_RE = re.compile(r"^##\s+(\w[\w\s]*)$", re.MULTILINE)


def list_all_configs() -> list[tuple[str, ProcessConfig]]:
    """Load every ``*-llm.json`` config and return sorted (name, config) tuples.

    Returns:
        Sorted list of ``(process_name, ProcessConfig)`` tuples.
    """
    configs: list[tuple[str, ProcessConfig]] = []
    for path in sorted(_CONFIGS_DIR.glob("*-llm.json")):
        process_name = path.stem.removesuffix("-llm")
        config = load_process_config(process_name)
        configs.append((process_name, config))
    return configs


def format_config_table(configs: list[tuple[str, ProcessConfig]]) -> Table:
    """Build a Rich :class:`Table` summarising all configs.

    Columns: ``#``, ``Process``, ``Model``, ``System Prompt`` (truncated to 60 chars).

    Args:
        configs: Output of :func:`list_all_configs`.

    Returns:
        A :class:`rich.table.Table` ready to print.
    """
    table = Table(title="LLM Process Configs")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Process", style="bold")
    table.add_column("Model")
    table.add_column("System Prompt", max_width=60)

    for idx, (name, cfg) in enumerate(configs, 1):
        prompt_preview = cfg.prompts.system[:60]
        if len(cfg.prompts.system) > 60:
            prompt_preview += "..."
        table.add_row(str(idx), name, cfg.model, prompt_preview)

    return table


def build_full_doc_content(process_name: str, config: ProcessConfig) -> str:
    """Render a config as plain-text document content for Google Docs editing.

    The format uses ``## Section`` markers so that :func:`parse_doc_sections`
    can round-trip the content back into config fields.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).
        config: The :class:`ProcessConfig` to render.

    Returns:
        Multi-line string with header and sections.
    """
    lines = [
        f"# {process_name}",
        "",
        "## model",
        config.model,
        "",
        "## description",
        config.description,
        "",
        "## system",
        config.prompts.system,
        "",
        "## instruction",
        config.prompts.instruction,
        "",
    ]
    return "\n".join(lines)


def parse_doc_sections(content: str) -> dict[str, str]:
    """Extract named sections from document content.

    Splits on ``## <name>`` markers and returns a mapping of
    lowercased section name to trimmed content between markers.

    Args:
        content: Full document text (as returned by Google Docs).

    Returns:
        Dict mapping section names (``"model"``, ``"description"``,
        ``"system"``, ``"instruction"``) to their text content.
    """
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(content))

    for i, match in enumerate(matches):
        name = match.group(1).strip().lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections[name] = content[start:end].strip()

    return sections


def apply_doc_changes(
    process_name: str, sections: dict[str, str]
) -> tuple[ProcessConfig, dict[str, str]]:
    """Apply edited sections back to a config, bump version, and save.

    Loads the current config, compares each section against the existing
    value, records changes, bumps ``metadata.version``, sets
    ``metadata.last_synced_at``, and writes the file.

    Args:
        process_name: The process identifier.
        sections: Output of :func:`parse_doc_sections`.

    Returns:
        Tuple of ``(updated_config, changes)`` where *changes* maps
        field names to short diff descriptions (e.g.
        ``{"model": "anthropic/claude-sonnet-4.5 -> openai/gpt-4.1"}``).
    """
    old = load_process_config(process_name)
    changes: dict[str, str] = {}

    # Start from existing values.
    model = old.model
    description = old.description
    system = old.prompts.system
    instruction = old.prompts.instruction

    if "model" in sections and sections["model"] != old.model:
        model = sections["model"]
        changes["model"] = f"{old.model} -> {model}"

    if "description" in sections and sections["description"] != old.description:
        description = sections["description"]
        changes["description"] = (
            f"{len(old.description)} chars -> {len(description)} chars"
        )

    if "system" in sections and sections["system"] != old.prompts.system:
        system = sections["system"]
        changes["system"] = (
            f"{len(old.prompts.system)} chars -> {len(system)} chars"
        )

    if "instruction" in sections and sections["instruction"] != old.prompts.instruction:
        instruction = sections["instruction"]
        changes["instruction"] = (
            f"{len(old.prompts.instruction)} chars -> {len(instruction)} chars"
        )

    new_version = old.metadata.version + 1
    now_iso = datetime.now(UTC).isoformat()

    updated = ProcessConfig(
        **{
            "$schema": old.schema_version,
            "processName": old.process_name,
            "description": description,
            "model": model,
            "prompts": {"system": system, "instruction": instruction},
            "metadata": {
                "googleDocId": old.metadata.google_doc_id,
                "lastSyncedAt": now_iso,
                "version": new_version,
            },
        }
    )

    save_process_config(process_name, updated)
    return updated, changes


def format_sync_summary(
    process_name: str,
    old_config: ProcessConfig,
    new_config: ProcessConfig,
    changes: dict[str, str],
) -> str:
    """Build a human-readable sync summary.

    Args:
        process_name: The process identifier.
        old_config: Config before the edit.
        new_config: Config after the edit (with bumped version).
        changes: Change descriptions from :func:`apply_doc_changes`.

    Returns:
        Formatted string suitable for Rich console output.
    """
    lines = [
        f"[bold]Sync: {process_name}[/bold]",
        f"  version: {old_config.metadata.version} -> {new_config.metadata.version}",
    ]

    if "model" in changes:
        lines.append(f"  model:   {changes['model']}")

    for field in ("description", "system", "instruction"):
        if field in changes:
            lines.append(f"  {field}: {changes[field]}")

    if not changes:
        lines.append("  [dim]no changes[/dim]")

    return "\n".join(lines)
