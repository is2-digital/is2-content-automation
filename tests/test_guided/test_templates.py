"""Tests for ica.guided.templates — template storage model and persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from ica.guided.templates import (
    DuplicateTemplateError,
    DuplicateVersionError,
    TemplateNotFoundError,
    TemplateRecord,
    TemplateStore,
    _hash_content,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_HTML = "<html><body><h1>Newsletter</h1></body></html>"
SAMPLE_HTML_V2 = "<html><body><h1>Newsletter v2</h1></body></html>"


def _make_store(tmp_path: Path) -> TemplateStore:
    return TemplateStore(tmp_path / "templates")


# ---------------------------------------------------------------------------
# TemplateRecord
# ---------------------------------------------------------------------------


class TestTemplateRecord:
    def test_defaults(self):
        record = TemplateRecord(name="t", version="1.0.0", template_html="<p>hi</p>")
        assert record.name == "t"
        assert record.version == "1.0.0"
        assert record.template_html == "<p>hi</p>"
        assert record.description == ""
        assert record.created_at  # auto-populated
        assert record.content_hash  # auto-populated

    def test_content_hash_auto_computed(self):
        record = TemplateRecord(name="t", version="1.0.0", template_html=SAMPLE_HTML)
        assert record.content_hash == _hash_content(SAMPLE_HTML)

    def test_content_hash_preserved_if_provided(self):
        record = TemplateRecord(
            name="t", version="1.0.0", template_html="<p>x</p>", content_hash="custom"
        )
        assert record.content_hash == "custom"

    def test_created_at_preserved_if_provided(self):
        record = TemplateRecord(
            name="t",
            version="1.0.0",
            template_html="<p>x</p>",
            created_at="2026-01-01T00:00:00",
        )
        assert record.created_at == "2026-01-01T00:00:00"

    def test_different_html_different_hash(self):
        r1 = TemplateRecord(name="t", version="1.0.0", template_html="<p>a</p>")
        r2 = TemplateRecord(name="t", version="1.0.0", template_html="<p>b</p>")
        assert r1.content_hash != r2.content_hash

    def test_same_html_same_hash(self):
        r1 = TemplateRecord(name="t", version="1.0.0", template_html=SAMPLE_HTML)
        r2 = TemplateRecord(name="t", version="2.0.0", template_html=SAMPLE_HTML)
        assert r1.content_hash == r2.content_hash


# ---------------------------------------------------------------------------
# TemplateStore — save
# ---------------------------------------------------------------------------


class TestTemplateStoreSave:
    def test_save_creates_file(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        path = store.base_dir / "weekly" / "1.0.0.json"
        assert path.exists()

    def test_save_returns_record(self, tmp_path: Path):
        store = _make_store(tmp_path)
        record = store.save("weekly", SAMPLE_HTML, "1.0.0", description="First version")
        assert isinstance(record, TemplateRecord)
        assert record.name == "weekly"
        assert record.version == "1.0.0"
        assert record.template_html == SAMPLE_HTML
        assert record.description == "First version"
        assert record.content_hash == _hash_content(SAMPLE_HTML)
        assert record.created_at

    def test_save_duplicate_version_raises(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        with pytest.raises(DuplicateVersionError, match="already exists"):
            store.save("weekly", SAMPLE_HTML_V2, "1.0.0")

    def test_save_duplicate_content_different_version_raises(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        with pytest.raises(DuplicateTemplateError, match="identical content"):
            store.save("weekly", SAMPLE_HTML, "2.0.0")

    def test_save_different_names_same_content_ok(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        record = store.save("daily", SAMPLE_HTML, "1.0.0")
        assert record.name == "daily"

    def test_save_different_versions_different_content_ok(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        record = store.save("weekly", SAMPLE_HTML_V2, "2.0.0")
        assert record.version == "2.0.0"


# ---------------------------------------------------------------------------
# TemplateStore — get
# ---------------------------------------------------------------------------


class TestTemplateStoreGet:
    def test_get_specific_version(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        record = store.get("weekly", version="1.0.0")
        assert record.version == "1.0.0"
        assert record.template_html == SAMPLE_HTML

    def test_get_latest_when_no_version(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        store.save("weekly", SAMPLE_HTML_V2, "2.0.0")
        record = store.get("weekly")
        assert record.version == "2.0.0"

    def test_get_nonexistent_version_shows_alternatives(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        with pytest.raises(TemplateNotFoundError, match=r"Available versions: 1\.0\.0"):
            store.get("weekly", version="9.9.9")

    def test_get_nonexistent_template_shows_alternatives(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        with pytest.raises(TemplateNotFoundError, match="Available templates: weekly"):
            store.get("nope")

    def test_get_nonexistent_template_empty_store(self, tmp_path: Path):
        store = _make_store(tmp_path)
        with pytest.raises(TemplateNotFoundError, match="No versions found"):
            store.get("nope")

    def test_get_round_trip(self, tmp_path: Path):
        store = _make_store(tmp_path)
        original = store.save("weekly", SAMPLE_HTML, "1.0.0", description="Test")
        loaded = store.get("weekly", "1.0.0")
        assert loaded.name == original.name
        assert loaded.version == original.version
        assert loaded.template_html == original.template_html
        assert loaded.description == original.description
        assert loaded.content_hash == original.content_hash
        assert loaded.created_at == original.created_at


# ---------------------------------------------------------------------------
# TemplateStore — listing
# ---------------------------------------------------------------------------


class TestTemplateStoreListing:
    def test_list_templates_empty(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.list_templates() == []

    def test_list_templates(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        store.save("daily", SAMPLE_HTML_V2, "1.0.0")
        assert store.list_templates() == ["daily", "weekly"]

    def test_list_versions_returns_records(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        store.save("weekly", SAMPLE_HTML_V2, "2.0.0")
        records = store.list_versions("weekly")
        assert len(records) == 2
        assert all(isinstance(r, TemplateRecord) for r in records)
        assert records[0].version == "1.0.0"
        assert records[1].version == "2.0.0"

    def test_list_versions_sorted_by_version(self, tmp_path: Path):
        store = _make_store(tmp_path)
        # Save in reverse order to verify sorting
        store.save("weekly", SAMPLE_HTML_V2, "2.0.0")
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        records = store.list_versions("weekly")
        assert [r.version for r in records] == ["1.0.0", "2.0.0"]

    def test_list_versions_nonexistent_raises(self, tmp_path: Path):
        store = _make_store(tmp_path)
        with pytest.raises(TemplateNotFoundError, match="not found"):
            store.list_versions("nope")

    def test_list_versions_nonexistent_shows_alternatives(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        with pytest.raises(TemplateNotFoundError, match="Available templates: weekly"):
            store.list_versions("nope")


# ---------------------------------------------------------------------------
# TemplateStore — delete / exists
# ---------------------------------------------------------------------------


class TestTemplateStoreDeleteExists:
    def test_delete_removes_file(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        store.delete("weekly", "1.0.0")
        assert not store.exists("weekly", "1.0.0")

    def test_delete_cleans_empty_directory(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        store.delete("weekly", "1.0.0")
        assert not (store.base_dir / "weekly").exists()

    def test_delete_nonexistent_noop(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.delete("nope", "1.0.0")  # no error

    def test_delete_then_save_same_version(self, tmp_path: Path):
        """Deleting a version allows re-saving it."""
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        store.delete("weekly", "1.0.0")
        record = store.save("weekly", SAMPLE_HTML_V2, "1.0.0")
        assert record.template_html == SAMPLE_HTML_V2

    def test_exists_with_version(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        assert store.exists("weekly", "1.0.0")
        assert not store.exists("weekly", "9.9.9")

    def test_exists_without_version(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        assert store.exists("weekly")
        assert not store.exists("nope")

    def test_exists_false_after_all_versions_deleted(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save("weekly", SAMPLE_HTML, "1.0.0")
        store.delete("weekly", "1.0.0")
        assert not store.exists("weekly")


# ---------------------------------------------------------------------------
# TemplateStore — default base_dir
# ---------------------------------------------------------------------------


class TestTemplateStoreDefaults:
    def test_default_base_dir(self):
        store = TemplateStore()
        assert store.base_dir == Path(".guided-templates")

    def test_custom_base_dir(self, tmp_path: Path):
        store = TemplateStore(tmp_path / "custom")
        assert store.base_dir == tmp_path / "custom"
