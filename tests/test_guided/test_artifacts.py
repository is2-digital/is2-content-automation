"""Tests for ica.guided.artifacts — artifact ledger data model."""

from __future__ import annotations

from unittest.mock import patch

from ica.guided.artifacts import (
    ArtifactEntry,
    ArtifactLedger,
    ArtifactType,
    deserialize_ledger,
    serialize_ledger,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_TS = "2026-03-01T12:00:00+00:00"


def _entry(
    *,
    step: str = "curation",
    atype: ArtifactType = ArtifactType.GOOGLE_SHEET,
    key: str = "spreadsheet_id",
    value: str = "abc-123",
    attempt: int = 1,
) -> ArtifactEntry:
    return ArtifactEntry(
        run_id="run-001",
        step_name=step,
        artifact_type=atype,
        key=key,
        value=value,
        timestamp=FIXED_TS,
        attempt_number=attempt,
    )


def _populated_ledger() -> ArtifactLedger:
    """Ledger with varied entries for query testing."""
    ledger = ArtifactLedger()
    ledger.add(_entry(step="curation", atype=ArtifactType.GOOGLE_SHEET, key="sheet_id"))
    ledger.add(_entry(step="curation", atype=ArtifactType.SLACK_DECISION, key="approval"))
    ledger.add(_entry(step="summarization", atype=ArtifactType.LLM_OUTPUT, key="summaries"))
    ledger.add(
        _entry(
            step="summarization",
            atype=ArtifactType.LLM_OUTPUT,
            key="summaries_v2",
            attempt=2,
        )
    )
    ledger.add(
        _entry(
            step="markdown_generation",
            atype=ArtifactType.VALIDATION_RESULT,
            key="char_counts",
        )
    )
    return ledger


# ---------------------------------------------------------------------------
# ArtifactType
# ---------------------------------------------------------------------------


class TestArtifactType:
    def test_all_six_values(self):
        assert len(ArtifactType) == 6

    def test_string_values(self):
        assert ArtifactType.SLACK_DECISION == "slack_decision"
        assert ArtifactType.GOOGLE_DOC == "google_doc"
        assert ArtifactType.GOOGLE_SHEET == "google_sheet"
        assert ArtifactType.LLM_OUTPUT == "llm_output"
        assert ArtifactType.VALIDATION_RESULT == "validation_result"
        assert ArtifactType.FIXTURE_DATA == "fixture_data"

    def test_round_trip_from_string(self):
        for t in ArtifactType:
            assert ArtifactType(t.value) is t


# ---------------------------------------------------------------------------
# ArtifactEntry
# ---------------------------------------------------------------------------


class TestArtifactEntry:
    def test_required_fields(self):
        e = _entry()
        assert e.run_id == "run-001"
        assert e.step_name == "curation"
        assert e.artifact_type == ArtifactType.GOOGLE_SHEET
        assert e.key == "spreadsheet_id"
        assert e.value == "abc-123"

    def test_defaults(self):
        e = ArtifactEntry(
            run_id="r1",
            step_name="curation",
            artifact_type=ArtifactType.LLM_OUTPUT,
            key="k",
            value="v",
        )
        assert e.attempt_number == 1
        assert e.metadata == {}
        assert e.timestamp  # auto-populated

    def test_auto_timestamp(self):
        with patch(
            "ica.guided.artifacts._now_iso", return_value="2026-01-01T00:00:00+00:00"
        ):
            e = ArtifactEntry(
                run_id="r1",
                step_name="s",
                artifact_type=ArtifactType.FIXTURE_DATA,
                key="k",
                value=42,
            )
        assert e.timestamp == "2026-01-01T00:00:00+00:00"

    def test_explicit_timestamp_preserved(self):
        e = _entry()
        assert e.timestamp == FIXED_TS

    def test_metadata_isolation(self):
        e1 = _entry()
        e2 = _entry()
        e1.metadata["extra"] = True
        assert "extra" not in e2.metadata

    def test_json_serializable_value(self):
        e = _entry(value={"nested": [1, 2, 3]})
        assert e.value == {"nested": [1, 2, 3]}


# ---------------------------------------------------------------------------
# ArtifactLedger
# ---------------------------------------------------------------------------


class TestArtifactLedger:
    def test_empty_ledger(self):
        ledger = ArtifactLedger()
        assert ledger.entries == []

    def test_add_appends(self):
        ledger = ArtifactLedger()
        e = _entry()
        ledger.add(e)
        assert len(ledger.entries) == 1
        assert ledger.entries[0] is e

    def test_add_preserves_order(self):
        ledger = ArtifactLedger()
        e1 = _entry(key="first")
        e2 = _entry(key="second")
        ledger.add(e1)
        ledger.add(e2)
        assert [e.key for e in ledger.entries] == ["first", "second"]


class TestLedgerByStep:
    def test_filters_by_step_name(self):
        ledger = _populated_ledger()
        result = ledger.by_step("curation")
        assert len(result) == 2
        assert all(e.step_name == "curation" for e in result)

    def test_returns_empty_for_unknown_step(self):
        ledger = _populated_ledger()
        assert ledger.by_step("nonexistent") == []

    def test_returns_new_list(self):
        ledger = _populated_ledger()
        result = ledger.by_step("curation")
        result.clear()
        assert len(ledger.by_step("curation")) == 2


class TestLedgerByType:
    def test_filters_by_artifact_type(self):
        ledger = _populated_ledger()
        result = ledger.by_type(ArtifactType.LLM_OUTPUT)
        assert len(result) == 2
        assert all(e.artifact_type == ArtifactType.LLM_OUTPUT for e in result)

    def test_returns_empty_for_unused_type(self):
        ledger = _populated_ledger()
        assert ledger.by_type(ArtifactType.GOOGLE_DOC) == []


class TestLedgerByAttempt:
    def test_filters_by_attempt_number(self):
        ledger = _populated_ledger()
        result = ledger.by_attempt(2)
        assert len(result) == 1
        assert result[0].key == "summaries_v2"

    def test_attempt_1_returns_default_entries(self):
        ledger = _populated_ledger()
        result = ledger.by_attempt(1)
        assert len(result) == 4

    def test_returns_empty_for_nonexistent_attempt(self):
        ledger = _populated_ledger()
        assert ledger.by_attempt(99) == []


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_round_trip(self):
        ledger = _populated_ledger()
        data = serialize_ledger(ledger)
        restored = deserialize_ledger(data)
        assert len(restored.entries) == len(ledger.entries)
        for orig, rest in zip(ledger.entries, restored.entries, strict=True):
            assert rest.run_id == orig.run_id
            assert rest.step_name == orig.step_name
            assert rest.artifact_type == orig.artifact_type
            assert rest.key == orig.key
            assert rest.value == orig.value
            assert rest.timestamp == orig.timestamp
            assert rest.attempt_number == orig.attempt_number
            assert rest.metadata == orig.metadata

    def test_serialize_produces_plain_dicts(self):
        ledger = ArtifactLedger()
        ledger.add(_entry())
        data = serialize_ledger(ledger)
        assert isinstance(data, list)
        assert isinstance(data[0], dict)
        assert data[0]["artifact_type"] == "google_sheet"

    def test_deserialize_empty_list(self):
        ledger = deserialize_ledger([])
        assert ledger.entries == []

    def test_deserialize_missing_optional_fields(self):
        data = [
            {
                "run_id": "r1",
                "step_name": "curation",
                "artifact_type": "slack_decision",
                "key": "approval",
                "value": True,
            }
        ]
        ledger = deserialize_ledger(data)
        e = ledger.entries[0]
        assert e.attempt_number == 1
        assert e.metadata == {}
        assert e.timestamp  # auto-filled by __post_init__ when missing

    def test_round_trip_with_metadata(self):
        ledger = ArtifactLedger()
        entry = _entry()
        entry.metadata = {"source": "test", "count": 42}
        ledger.add(entry)
        restored = deserialize_ledger(serialize_ledger(ledger))
        assert restored.entries[0].metadata == {"source": "test", "count": 42}
