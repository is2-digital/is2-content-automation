"""Structured artifact ledger for guided pipeline test runs.

Provides rich provenance tracking for every output and external interaction
produced during a guided test run, replacing the lightweight dict in
``StepRecord.artifacts`` with queryable, typed entries.

Persistence uses the same JSON-file pattern as ``state.py`` — serialization
helpers at the bottom of this module keep the format round-trippable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ArtifactType(StrEnum):
    """Categories of artifacts produced during a guided test run."""

    SLACK_DECISION = "slack_decision"
    GOOGLE_DOC = "google_doc"
    GOOGLE_SHEET = "google_sheet"
    LLM_OUTPUT = "llm_output"
    VALIDATION_RESULT = "validation_result"
    FIXTURE_DATA = "fixture_data"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ArtifactEntry:
    """A single artifact produced by a pipeline step.

    Attributes:
        run_id: Test run that produced this artifact.
        step_name: Pipeline step that emitted the artifact.
        artifact_type: Category of the artifact.
        key: Short identifier (e.g. ``"markdown_doc_id"``).
        value: JSON-serializable payload.
        timestamp: UTC time the artifact was recorded.
        attempt_number: Which attempt of the step produced this (1-based).
        metadata: Extensible dict for additional context.
    """

    run_id: str
    step_name: str
    artifact_type: ArtifactType
    key: str
    value: Any
    timestamp: str = ""
    attempt_number: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _now_iso()


@dataclass
class ArtifactLedger:
    """Ordered collection of :class:`ArtifactEntry` items with query helpers.

    The ledger is append-only during a run.  Query methods return new lists
    (never mutate the internal store).
    """

    entries: list[ArtifactEntry] = field(default_factory=list)

    def add(self, entry: ArtifactEntry) -> None:
        """Append an artifact entry to the ledger."""
        self.entries.append(entry)

    def by_step(self, step_name: str) -> list[ArtifactEntry]:
        """Return entries for a given pipeline step."""
        return [e for e in self.entries if e.step_name == step_name]

    def by_type(self, artifact_type: ArtifactType) -> list[ArtifactEntry]:
        """Return entries matching *artifact_type*."""
        return [e for e in self.entries if e.artifact_type == artifact_type]

    def by_attempt(self, attempt_number: int) -> list[ArtifactEntry]:
        """Return entries from a specific attempt number."""
        return [e for e in self.entries if e.attempt_number == attempt_number]


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def serialize_ledger(ledger: ArtifactLedger) -> list[dict[str, Any]]:
    """Convert a ledger to a JSON-compatible list of dicts."""
    return [asdict(e) for e in ledger.entries]


def deserialize_ledger(data: list[dict[str, Any]]) -> ArtifactLedger:
    """Reconstruct a ledger from a list of dicts (as loaded from JSON)."""
    entries = [
        ArtifactEntry(
            run_id=d["run_id"],
            step_name=d["step_name"],
            artifact_type=ArtifactType(d["artifact_type"]),
            key=d["key"],
            value=d["value"],
            timestamp=d.get("timestamp", ""),
            attempt_number=d.get("attempt_number", 1),
            metadata=d.get("metadata", {}),
        )
        for d in data
    ]
    return ArtifactLedger(entries=entries)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class ArtifactStore:
    """JSON-file-based persistence for artifact ledgers.

    Each test run's artifacts are stored in a ``{run_id}-artifacts.json``
    file alongside the ``{run_id}.json`` state file managed by
    :class:`~ica.guided.state.TestRunStore`.  The file is append-only
    during a run — each call to :meth:`append_artifact` reads, appends,
    and rewrites the full list.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def append_artifact(self, run_id: str, entry: ArtifactEntry) -> None:
        """Append *entry* to the ledger file for *run_id*."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        path = self._ledger_path(run_id)
        data: list[dict[str, Any]] = []
        if path.exists():
            data = json.loads(path.read_text())
        data.append(asdict(entry))
        path.write_text(json.dumps(data, indent=2))

    def get_ledger(self, run_id: str) -> ArtifactLedger:
        """Load the full artifact ledger for *run_id*.

        Returns an empty ledger if no artifact file exists yet.
        """
        path = self._ledger_path(run_id)
        if not path.exists():
            return ArtifactLedger()
        data = json.loads(path.read_text())
        return deserialize_ledger(data)

    def get_artifacts_for_step(
        self, run_id: str, step: str
    ) -> list[ArtifactEntry]:
        """Return artifact entries for a specific pipeline *step*."""
        return self.get_ledger(run_id).by_step(step)

    def delete(self, run_id: str) -> None:
        """Delete the artifact file for *run_id*.  No-op if absent."""
        path = self._ledger_path(run_id)
        if path.exists():
            path.unlink()

    def _ledger_path(self, run_id: str) -> Path:
        return self._base_dir / f"{run_id}-artifacts.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()
