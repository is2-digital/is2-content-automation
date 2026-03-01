"""Tests for ica.guided.templates — template storage model and persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from ica.guided.templates import (
    DuplicateTemplateError,
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


def _make_record(
    name: str = "weekly",
    version: str = "1.0.0",
    html: str = SAMPLE_HTML,
    description: str = "Test template",
) -> TemplateRecord:
    return TemplateRecord(
        name=name,
        version=version,
        template_html=html,
        description=description,
    )


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
            name="t", version="1.0.0", template_html="<p>x</p>", created_at="2026-01-01T00:00:00"
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
# TemplateStore — save / load
# ---------------------------------------------------------------------------


class TestTemplateStoreSaveLoad:
    def test_save_creates_file(self, tmp_path: Path):
        store = _make_store(tmp_path)
        record = _make_record()
        path = store.save(record)
        assert path.exists()
        assert path.name == "1.0.0.json"

    def test_round_trip(self, tmp_path: Path):
        store = _make_store(tmp_path)
        original = _make_record()
        store.save(original)
        loaded = store.load("weekly", "1.0.0")
        assert loaded.name == original.name
        assert loaded.version == original.version
        assert loaded.template_html == original.template_html
        assert loaded.description == original.description
        assert loaded.content_hash == original.content_hash
        assert loaded.created_at == original.created_at

    def test_load_nonexistent_raises(self, tmp_path: Path):
        store = _make_store(tmp_path)
        with pytest.raises(TemplateNotFoundError, match="not found"):
            store.load("nope", "1.0.0")

    def test_overwrite_same_version(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record(html="<p>v1</p>"))
        store.save(_make_record(html="<p>v1-updated</p>"))
        loaded = store.load("weekly", "1.0.0")
        assert loaded.template_html == "<p>v1-updated</p>"

    def test_duplicate_content_different_version_raises(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record(version="1.0.0", html=SAMPLE_HTML))
        with pytest.raises(DuplicateTemplateError, match="identical content"):
            store.save(_make_record(version="2.0.0", html=SAMPLE_HTML))

    def test_same_content_same_version_overwrites(self, tmp_path: Path):
        """Re-saving the same version with same content is an overwrite, not a dup."""
        store = _make_store(tmp_path)
        store.save(_make_record(version="1.0.0", html=SAMPLE_HTML))
        store.save(_make_record(version="1.0.0", html=SAMPLE_HTML))  # no error
        loaded = store.load("weekly", "1.0.0")
        assert loaded.template_html == SAMPLE_HTML


# ---------------------------------------------------------------------------
# TemplateStore — load_latest
# ---------------------------------------------------------------------------


class TestTemplateStoreLoadLatest:
    def test_returns_most_recent(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(
            TemplateRecord(
                name="weekly",
                version="1.0.0",
                template_html="<p>old</p>",
                created_at="2026-01-01T00:00:00",
            )
        )
        store.save(
            TemplateRecord(
                name="weekly",
                version="2.0.0",
                template_html="<p>new</p>",
                created_at="2026-02-01T00:00:00",
            )
        )
        latest = store.load_latest("weekly")
        assert latest.version == "2.0.0"

    def test_no_versions_raises(self, tmp_path: Path):
        store = _make_store(tmp_path)
        with pytest.raises(TemplateNotFoundError, match="No versions found"):
            store.load_latest("weekly")


# ---------------------------------------------------------------------------
# TemplateStore — listing
# ---------------------------------------------------------------------------


class TestTemplateStoreListing:
    def test_list_templates_empty(self, tmp_path: Path):
        store = _make_store(tmp_path)
        assert store.list_templates() == []

    def test_list_templates(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record(name="weekly"))
        store.save(_make_record(name="daily", html=SAMPLE_HTML_V2))
        assert store.list_templates() == ["daily", "weekly"]

    def test_list_versions(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record(version="1.0.0"))
        store.save(_make_record(version="2.0.0", html=SAMPLE_HTML_V2))
        assert store.list_versions("weekly") == ["1.0.0", "2.0.0"]

    def test_list_versions_nonexistent_raises(self, tmp_path: Path):
        store = _make_store(tmp_path)
        with pytest.raises(TemplateNotFoundError, match="not found"):
            store.list_versions("nope")


# ---------------------------------------------------------------------------
# TemplateStore — delete / exists
# ---------------------------------------------------------------------------


class TestTemplateStoreDeleteExists:
    def test_delete_removes_file(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record())
        store.delete("weekly", "1.0.0")
        assert not store.exists("weekly", "1.0.0")

    def test_delete_cleans_empty_directory(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record())
        store.delete("weekly", "1.0.0")
        assert not (store.base_dir / "weekly").exists()

    def test_delete_nonexistent_noop(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.delete("nope", "1.0.0")  # no error

    def test_exists_with_version(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record())
        assert store.exists("weekly", "1.0.0")
        assert not store.exists("weekly", "9.9.9")

    def test_exists_without_version(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record())
        assert store.exists("weekly")
        assert not store.exists("nope")

    def test_exists_false_after_all_versions_deleted(self, tmp_path: Path):
        store = _make_store(tmp_path)
        store.save(_make_record())
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
