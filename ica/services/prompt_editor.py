"""Prompt editor service for editing LLM config prompts via Google Docs.

Provides :class:`PromptEditorService` with seven operations:

* :meth:`start_edit` — open a Google Doc for editing a single prompt field
* :meth:`sync_from_doc` — pull single-field edits from the Doc back into JSON
* :meth:`start_full_edit` — open a Google Doc for editing all config fields
* :meth:`sync_full_from_doc` — pull all-field edits from the Doc back into JSON
* :meth:`start_system_edit` — open a Google Doc for editing the shared system prompt
* :meth:`sync_system_from_doc` — pull the shared system prompt from the Doc back into JSON
* :meth:`get_config_summary` — format config info for Slack display

Usage::

    from ica.services.google_docs import GoogleDocsService
    from ica.services.prompt_editor import PromptEditorService

    docs = GoogleDocsService(credentials_path="/path/to/creds.json")
    editor = PromptEditorService(docs)

    url = await editor.start_edit("summarization", "instruction")
    # ... user edits the doc ...
    config = await editor.sync_from_doc("summarization")
"""

from __future__ import annotations

from datetime import UTC, datetime

from ica.cli.config_editor import (
    apply_doc_changes,
    build_full_doc_content,
    parse_doc_sections,
)
from ica.llm_configs.loader import (
    get_process_model,
    load_process_config,
    load_system_prompt_config,
    save_process_config,
    save_system_prompt,
)
from ica.llm_configs.schema import ProcessConfig
from ica.logging import get_logger
from ica.services.google_docs import GoogleDocsService

logger = get_logger(__name__)

_VALID_FIELDS = ("instruction",)
_HEADER_END = "--- END HEADER ---"
_DOC_URL_TEMPLATE = "https://docs.google.com/document/d/{doc_id}/edit"


def _build_edit_header(process_name: str, field: str, version: int) -> str:
    """Build the header block inserted at the top of the Google Doc."""
    return (
        "--- ICA PROMPT EDITOR ---\n"
        f"Process: {process_name}\n"
        f"Field: {field}\n"
        f"Version: {version}\n"
        "\n"
        "Edit the prompt content below. Do not modify this header.\n"
        f"{_HEADER_END}\n\n"
    )


def _build_system_edit_header(version: int) -> str:
    """Build the header block for shared system prompt editing."""
    return (
        "--- ICA SYSTEM PROMPT EDITOR ---\n"
        f"Version: {version}\n"
        "\n"
        "Edit the system prompt below. Do not modify this header.\n"
        f"{_HEADER_END}\n\n"
    )


def _parse_doc_content(content: str) -> tuple[str, str]:
    """Extract the field name and prompt text from a Google Doc.

    Returns:
        Tuple of ``(field, prompt_text)``.

    Raises:
        ValueError: If the header separator or ``Field:`` line is missing.
    """
    idx = content.find(_HEADER_END)
    if idx == -1:
        raise ValueError(
            f"Doc content is missing the header separator ({_HEADER_END!r}). "
            "Was the header section removed?"
        )

    header = content[:idx]
    prompt_text = content[idx + len(_HEADER_END) :].strip()

    for line in header.splitlines():
        stripped = line.strip()
        if stripped.startswith("Field:"):
            field = stripped.split(":", 1)[1].strip().lower()
            if field not in _VALID_FIELDS:
                raise ValueError(
                    f"Unknown field {field!r} in doc header. Expected one of: {_VALID_FIELDS}"
                )
            return field, prompt_text

    raise ValueError("Doc header is missing the 'Field:' line")


def _parse_system_doc_content(content: str) -> str:
    """Extract the system prompt text from a Google Doc.

    Returns:
        The edited system prompt text.

    Raises:
        ValueError: If the header separator is missing.
    """
    idx = content.find(_HEADER_END)
    if idx == -1:
        raise ValueError(
            f"Doc content is missing the header separator ({_HEADER_END!r}). "
            "Was the header section removed?"
        )
    return content[idx + len(_HEADER_END) :].strip()


class PromptEditorService:
    """Async service for editing LLM process prompts via Google Docs.

    Args:
        docs_service: A configured :class:`GoogleDocsService` instance.
    """

    def __init__(self, docs_service: GoogleDocsService) -> None:
        self._docs = docs_service

    async def start_edit(self, process_name: str, field: str) -> str:
        """Open a Google Doc for editing a prompt field.

        Creates a new Google Doc, populates it with the current prompt
        content and a header section, then updates the config metadata
        with the new document ID.

        Args:
            process_name: Process identifier (e.g. ``"summarization"``).
            field: Prompt field to edit — ``"instruction"``.

        Returns:
            The Google Doc URL for editing.

        Raises:
            ValueError: If *field* is not ``"instruction"``.
            FileNotFoundError: If the process config JSON does not exist.
        """
        if field not in _VALID_FIELDS:
            raise ValueError(f"Invalid field {field!r}. Expected one of: {_VALID_FIELDS}")

        config = load_process_config(process_name)

        if config.metadata.google_doc_id is not None:
            logger.warning(
                "Replacing existing edit session",
                extra={
                    "process_name": process_name,
                    "old_doc_id": config.metadata.google_doc_id,
                },
            )

        title = f"[ICA Prompt] {process_name} — {field}"
        doc_id = await self._docs.create_document(title)

        prompt_content = getattr(config.prompts, field)
        header = _build_edit_header(process_name, field, config.metadata.version)
        await self._docs.insert_content(doc_id, header + prompt_content)

        config.metadata.google_doc_id = doc_id
        save_process_config(process_name, config)

        url = _DOC_URL_TEMPLATE.format(doc_id=doc_id)
        logger.info(
            "Edit session started",
            extra={"process_name": process_name, "field": field, "doc_url": url},
        )
        return url

    async def sync_from_doc(self, process_name: str) -> ProcessConfig:
        """Pull edited prompt content from Google Doc back to JSON config.

        Reads the document, extracts the field name and prompt text from the
        header, updates the config, bumps the version, and writes to disk.

        Args:
            process_name: Process identifier (e.g. ``"summarization"``).

        Returns:
            The updated :class:`ProcessConfig`.

        Raises:
            ValueError: If no Google Doc is linked or the doc content is
                malformed.
        """
        config = load_process_config(process_name)

        if config.metadata.google_doc_id is None:
            raise ValueError(
                f"No Google Doc linked for process {process_name!r}. Call start_edit() first."
            )

        content = await self._docs.get_content(config.metadata.google_doc_id)
        field, prompt_text = _parse_doc_content(content)

        setattr(config.prompts, field, prompt_text)
        config.metadata.version += 1
        config.metadata.last_synced_at = datetime.now(UTC).isoformat()
        config.metadata.google_doc_id = None

        save_process_config(process_name, config)

        logger.info(
            "Synced prompt from doc",
            extra={
                "process_name": process_name,
                "field": field,
                "version": config.metadata.version,
            },
        )
        return config

    async def start_full_edit(self, process_name: str) -> str:
        """Open a Google Doc for editing all config fields.

        Creates a new Google Doc populated with every editable field
        (model, description, instruction prompt) using ``## section``
        markers. Updates config metadata with the doc ID.

        Args:
            process_name: Process identifier (e.g. ``"summarization"``).

        Returns:
            The Google Doc URL for editing.

        Raises:
            FileNotFoundError: If the process config JSON does not exist.
        """
        config = load_process_config(process_name)

        if config.metadata.google_doc_id is not None:
            logger.warning(
                "Replacing existing edit session",
                extra={
                    "process_name": process_name,
                    "old_doc_id": config.metadata.google_doc_id,
                },
            )

        title = f"[ICA Config] {process_name} — full edit"
        doc_id = await self._docs.create_document(title)

        doc_content = build_full_doc_content(process_name, config)
        await self._docs.insert_content(doc_id, doc_content)

        config.metadata.google_doc_id = doc_id
        save_process_config(process_name, config)

        url = _DOC_URL_TEMPLATE.format(doc_id=doc_id)
        logger.info(
            "Full edit session started",
            extra={"process_name": process_name, "doc_url": url},
        )
        return url

    async def sync_full_from_doc(self, process_name: str) -> ProcessConfig:
        """Pull all edited fields from Google Doc back to JSON config.

        Reads the document, parses ``## section`` markers to extract
        field values, applies changes via :func:`apply_doc_changes`,
        clears the linked doc ID, and saves the config.

        Args:
            process_name: Process identifier (e.g. ``"summarization"``).

        Returns:
            The updated :class:`ProcessConfig`.

        Raises:
            ValueError: If no Google Doc is linked.
        """
        config = load_process_config(process_name)

        if config.metadata.google_doc_id is None:
            raise ValueError(
                f"No Google Doc linked for process {process_name!r}. "
                "Call start_full_edit() first."
            )

        content = await self._docs.get_content(config.metadata.google_doc_id)
        sections = parse_doc_sections(content)

        updated, changes = apply_doc_changes(process_name, sections)

        updated.metadata.google_doc_id = None
        save_process_config(process_name, updated)

        logger.info(
            "Synced full config from doc",
            extra={
                "process_name": process_name,
                "version": updated.metadata.version,
                "changed_fields": list(changes.keys()),
            },
        )
        return updated

    async def start_system_edit(self) -> str:
        """Open a Google Doc for editing the shared system prompt.

        Creates a new Google Doc populated with the current system prompt
        and a header section, then stores the doc ID in the system prompt
        metadata.

        Returns:
            The Google Doc URL for editing.

        Raises:
            FileNotFoundError: If ``system-prompt.json`` does not exist.
        """
        config = load_system_prompt_config()

        if config.metadata.google_doc_id is not None:
            logger.warning(
                "Replacing existing system prompt edit session",
                extra={"old_doc_id": config.metadata.google_doc_id},
            )

        title = "[ICA] Shared System Prompt"
        doc_id = await self._docs.create_document(title)

        header = _build_system_edit_header(config.metadata.version)
        await self._docs.insert_content(doc_id, header + config.prompt)

        config.metadata.google_doc_id = doc_id
        save_system_prompt(config)

        url = _DOC_URL_TEMPLATE.format(doc_id=doc_id)
        logger.info("System prompt edit session started", extra={"doc_url": url})
        return url

    async def sync_system_from_doc(self) -> str:
        """Pull the shared system prompt from Google Doc back to JSON.

        Reads the document, extracts the prompt text, updates the config,
        bumps the version, and writes to disk.

        Returns:
            The updated system prompt string.

        Raises:
            ValueError: If no Google Doc is linked.
        """
        config = load_system_prompt_config()

        if config.metadata.google_doc_id is None:
            raise ValueError(
                "No Google Doc linked for the system prompt. "
                "Call start_system_edit() first."
            )

        content = await self._docs.get_content(config.metadata.google_doc_id)
        prompt_text = _parse_system_doc_content(content)

        config.prompt = prompt_text
        config.metadata.version += 1
        config.metadata.last_synced_at = datetime.now(UTC).isoformat()
        config.metadata.google_doc_id = None

        save_system_prompt(config)

        logger.info(
            "Synced system prompt from doc",
            extra={"version": config.metadata.version},
        )
        return prompt_text

    def update_model(self, process_name: str, new_model: str) -> ProcessConfig:
        """Update the model for a process config directly (no Google Docs).

        Loads the config, replaces the model, bumps the version, sets
        the sync timestamp, and writes to disk.

        Args:
            process_name: Process identifier (e.g. ``"summarization"``).
            new_model: New model identifier in OpenRouter ``provider/model`` format.

        Returns:
            The updated :class:`ProcessConfig`.

        Raises:
            ValueError: If *new_model* is empty.
            FileNotFoundError: If the process config JSON does not exist.
        """
        if not new_model or not new_model.strip():
            raise ValueError("Model ID must not be empty")

        new_model = new_model.strip()
        config = load_process_config(process_name)
        old_model = config.model

        config.model = new_model
        config.metadata.version += 1
        config.metadata.last_synced_at = datetime.now(UTC).isoformat()

        save_process_config(process_name, config)

        logger.info(
            "Updated model",
            extra={
                "process_name": process_name,
                "old_model": old_model,
                "new_model": new_model,
                "version": config.metadata.version,
            },
        )
        return config

    def get_config_summary(self, process_name: str) -> str:
        """Format a process config for Slack display.

        Args:
            process_name: Process identifier (e.g. ``"summarization"``).

        Returns:
            Slack-formatted summary string.
        """
        config = load_process_config(process_name)
        model = get_process_model(process_name)

        inst_len = len(config.prompts.instruction)
        last_sync = config.metadata.last_synced_at or "Never"
        active_edit = "Yes" if config.metadata.google_doc_id else "No"

        return (
            f"*{process_name}*\n"
            f"Model: `{model}`\n"
            f"Instruction prompt: {inst_len:,} chars\n"
            f"Version: {config.metadata.version}\n"
            f"Last synced: {last_sync}\n"
            f"Active edit: {active_edit}"
        )
