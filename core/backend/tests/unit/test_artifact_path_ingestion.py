"""Unit tests: produced artifact path parsing and safety checks."""

from __future__ import annotations

import pytest

from app.config import settings
from app.runs.produced_artifact_path_ingestion import (
    assert_safe_produced_relative_path,
    ingest_produced_artifact_paths,
    parse_produced_artifact_entry,
)
from tests.support import factories
from ulid import ULID


def _sid_uid(db):
    sid = str(ULID())
    factories.create_test_space(db, space_id=sid, name="u", commit=False)
    u = factories.create_test_user(db, space_id=sid, commit=False)
    return sid, u.id


def test_assert_safe_accepts_plain_relative():
    assert_safe_produced_relative_path("out/report.md")


def test_assert_safe_rejects_traversal():
    with pytest.raises(ValueError, match="traversal"):
        assert_safe_produced_relative_path("../secret.txt")


def test_assert_safe_rejects_absolute_string():
    with pytest.raises(ValueError, match="absolute"):
        assert_safe_produced_relative_path("/etc/passwd")


def test_parse_string_entry():
    rel, extra = parse_produced_artifact_entry("  logs/run.log  ")
    assert rel == "logs/run.log"
    assert extra == {}


def test_parse_dict_entry():
    rel, extra = parse_produced_artifact_entry(
        {"path": "x/a.md", "artifact_type": "report", "title": "T", "mime_type": "text/markdown"}
    )
    assert rel == "x/a.md"
    assert extra["artifact_type"] == "report"
    assert extra["title"] == "T"
    assert extra["mime_type"] == "text/markdown"


def test_parse_dict_requires_path():
    with pytest.raises(ValueError, match="path"):
        parse_produced_artifact_entry({"artifact_type": "x"})


def test_parse_rejects_non_string_object():
    with pytest.raises(TypeError):
        parse_produced_artifact_entry(42)


def test_ingest_missing_file_returns_error(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    root = tmp_path / "sb"
    root.mkdir()
    sid, uid = _sid_uid(db)
    agent = factories.create_test_agent(db, space_id=sid, owner_user_id=uid, commit=False)
    run = factories.create_test_run(db, space_id=sid, user_id=uid, agent=agent, commit=False)
    db.commit()
    errs = ingest_produced_artifact_paths(
        db, run=run, source_root=str(root), entries=["ghost.bin"]
    )
    assert len(errs) == 1
    assert "missing" in errs[0].lower()
