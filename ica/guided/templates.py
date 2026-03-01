"""Template storage model for HTML newsletter templates.

Provides file-based persistence for versioned HTML templates used in both
guided test runs and production flows.  Each named template can have
multiple versions stored as JSON files under a configurable directory
(default: ``.guided-templates/``).

File layout::

    <base_dir>/
        <name>/
            <version>.json   # TemplateRecord serialised to JSON

"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TemplateRecord:
    """A single versioned HTML newsletter template.

    Attributes:
        name: Human-readable template name (also the subdirectory key).
        version: Semantic version string (e.g. ``"1.0.0"``).
        template_html: The raw HTML content.
        description: Optional description of this template version.
        created_at: ISO-8601 timestamp when the record was created.
        content_hash: SHA-256 hex digest of *template_html* for dedup.
    """

    name: str
    version: str
    template_html: str
    description: str = ""
    created_at: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        if not self.content_hash:
            self.content_hash = _hash_content(self.template_html)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TemplateNotFoundError(Exception):
    """Raised when a requested template or version does not exist."""


class DuplicateTemplateError(Exception):
    """Raised when storing a template whose content hash already exists."""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TemplateStore:
    """JSON-file-based persistence for versioned HTML templates.

    Directory structure: ``<base_dir>/<name>/<version>.json``

    Each JSON file contains the full :class:`TemplateRecord` as a dict.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path(".guided-templates")

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def save(self, record: TemplateRecord) -> Path:
        """Persist a template record to disk.

        Args:
            record: The template record to store.

        Returns:
            The path to the written JSON file.

        Raises:
            DuplicateTemplateError: If another version of the same template
                has identical HTML content (matching content hash).
        """
        template_dir = self._template_dir(record.name)
        template_dir.mkdir(parents=True, exist_ok=True)

        # Check for duplicate content across versions of this template
        for existing in self._iter_records(record.name):
            if (
                existing.content_hash == record.content_hash
                and existing.version != record.version
            ):
                raise DuplicateTemplateError(
                    f"Template '{record.name}' version '{existing.version}' "
                    f"already has identical content (hash: {record.content_hash[:12]}...)"
                )

        path = self._version_path(record.name, record.version)
        path.write_text(json.dumps(_serialize(record), indent=2))
        return path

    def load(self, name: str, version: str) -> TemplateRecord:
        """Load a specific template version.

        Raises:
            TemplateNotFoundError: If the template or version does not exist.
        """
        path = self._version_path(name, version)
        if not path.exists():
            raise TemplateNotFoundError(
                f"Template '{name}' version '{version}' not found"
            )
        return _deserialize(json.loads(path.read_text()))

    def load_latest(self, name: str) -> TemplateRecord:
        """Load the most recently created version of a named template.

        Raises:
            TemplateNotFoundError: If no versions exist for *name*.
        """
        records = sorted(
            self._iter_records(name),
            key=lambda r: r.created_at,
            reverse=True,
        )
        if not records:
            raise TemplateNotFoundError(f"No versions found for template '{name}'")
        return records[0]

    def list_templates(self) -> list[str]:
        """Return sorted names of all stored templates."""
        if not self._base_dir.exists():
            return []
        return sorted(
            d.name for d in self._base_dir.iterdir() if d.is_dir()
        )

    def list_versions(self, name: str) -> list[str]:
        """Return sorted version strings for a named template.

        Raises:
            TemplateNotFoundError: If no template directory exists for *name*.
        """
        template_dir = self._template_dir(name)
        if not template_dir.exists():
            raise TemplateNotFoundError(f"Template '{name}' not found")
        return sorted(p.stem for p in template_dir.glob("*.json"))

    def delete(self, name: str, version: str) -> None:
        """Delete a specific template version. No-op if it doesn't exist."""
        path = self._version_path(name, version)
        if path.exists():
            path.unlink()
        # Remove the directory if empty
        template_dir = self._template_dir(name)
        if template_dir.exists() and not any(template_dir.iterdir()):
            template_dir.rmdir()

    def exists(self, name: str, version: str | None = None) -> bool:
        """Check whether a template (and optionally a specific version) exists."""
        if version is not None:
            return self._version_path(name, version).exists()
        template_dir = self._template_dir(name)
        return template_dir.exists() and any(template_dir.glob("*.json"))

    # --- Internal helpers ---

    def _template_dir(self, name: str) -> Path:
        return self._base_dir / name

    def _version_path(self, name: str, version: str) -> Path:
        return self._base_dir / name / f"{version}.json"

    def _iter_records(self, name: str) -> list[TemplateRecord]:
        """Load all version records for a named template."""
        template_dir = self._template_dir(name)
        if not template_dir.exists():
            return []
        records = []
        for path in template_dir.glob("*.json"):
            records.append(_deserialize(json.loads(path.read_text())))
        return records


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize(record: TemplateRecord) -> dict[str, Any]:
    """Convert a ``TemplateRecord`` to a JSON-compatible dict."""
    return asdict(record)


def _deserialize(data: dict[str, Any]) -> TemplateRecord:
    """Reconstruct a ``TemplateRecord`` from a dict."""
    return TemplateRecord(**data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_content(html: str) -> str:
    """Return the SHA-256 hex digest of *html*."""
    return hashlib.sha256(html.encode()).hexdigest()
