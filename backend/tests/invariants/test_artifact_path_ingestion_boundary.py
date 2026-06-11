"""Invariants: produced artifact path validation and storage boundaries."""

from __future__ import annotations
import uuid

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Artifact
from app.runs.produced_artifact_path_ingestion import ingest_produced_artifact_paths
from tests.support import factories


def _space_user(db: Session):
    sid = str(uuid.uuid4())
    factories.create_test_space(db, space_id=sid, name="inv", commit=False)
    u = factories.create_test_user(db, space_id=sid, commit=False)
    return sid, u.id


def test_produced_path_escape_root_rejected(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    root = tmp_path / "sb"
    root.mkdir()
    (root / "a.txt").write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET_BODY", encoding="utf-8")
    try:
        (root / "link").symlink_to(outside / "secret.txt")
    except OSError:
        pytest.skip("symlink creation not supported")

    sid, uid = _space_user(db)
    agent = factories.create_test_agent(db, space_id=sid, owner_user_id=uid, commit=False)
    run = factories.create_test_run(db, space_id=sid, user_id=uid, agent=agent, commit=False)
    db.commit()

    errs = ingest_produced_artifact_paths(
        db,
        run=run,
        source_root=str(root),
        entries=["link"],
    )
    assert errs
    assert db.query(Artifact).filter(Artifact.run_id == run.id).count() == 0
    joined = " ".join(errs)
    assert "SECRET_BODY" not in joined


def test_invalid_path_does_not_create_artifact_row(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    root = tmp_path / "sb"
    root.mkdir()
    sid, uid = _space_user(db)
    agent = factories.create_test_agent(db, space_id=sid, owner_user_id=uid, commit=False)
    run = factories.create_test_run(db, space_id=sid, user_id=uid, agent=agent, commit=False)
    db.commit()
    errs = ingest_produced_artifact_paths(
        db, run=run, source_root=str(root), entries=["../x"]
    )
    assert errs
    assert db.query(Artifact).filter(Artifact.run_id == run.id).count() == 0


def test_ingestion_does_not_mutate_workspace_files(db, tmp_path, monkeypatch):
    ws_disk = tmp_path / "workspaces" / "ws-1"
    ws_disk.mkdir(parents=True)
    marker = ws_disk / "marker.txt"
    marker.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    sb = tmp_path / "sandboxes" / "sb1"
    sb.mkdir(parents=True)
    (sb / "f.txt").write_text("from-sandbox", encoding="utf-8")

    sid, uid = _space_user(db)
    agent = factories.create_test_agent(db, space_id=sid, owner_user_id=uid, commit=False)
    run = factories.create_test_run(db, space_id=sid, user_id=uid, agent=agent, commit=False)
    db.commit()
    ingest_produced_artifact_paths(db, run=run, source_root=str(sb), entries=["f.txt"])
    assert marker.read_text(encoding="utf-8") == "ORIGINAL"


def test_artifact_row_has_no_absolute_sandbox_source_in_storage_fields(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    root = tmp_path / "sandboxes" / "wt" / "s1" / "r1"
    root.mkdir(parents=True)
    (root / "out.log").write_text("L", encoding="utf-8")

    sid, uid = _space_user(db)
    agent = factories.create_test_agent(db, space_id=sid, owner_user_id=uid, commit=False)
    run = factories.create_test_run(db, space_id=sid, user_id=uid, agent=agent, commit=False)
    db.commit()
    ingest_produced_artifact_paths(db, run=run, source_root=str(root), entries=["out.log"])
    art = db.query(Artifact).filter(Artifact.run_id == run.id).one()
    assert art.storage_path and not art.storage_path.startswith("/")
    blob = str(art.metadata_json) + (art.storage_ref or "") + (art.title or "")
    assert str(root) not in blob


def test_cross_space_run_access_unchanged(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    """Foreign space cannot list another space's run artifacts (regression guard)."""
    from app.models import AgentVersion

    db.commit()
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspaces").mkdir(parents=True, exist_ok=True)

    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    v.runtime_policy_json = {**dict(v.runtime_policy_json or {}), "risk_level": "high"}
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()
    r = cross_space_pair["client_b"].get(
        f"/api/v1/runs/{run.id}/artifacts",
        params={"space_id": b},
    )
    assert r.status_code == 404
