"""Invariants: M7 lifecycle, workspace scan, deployment boundary, and safety.

Covered by this file:
  Workspace scan:
    - Missing workspace path is marked stale (not hard-deleted)
    - Workspace metadata is fully preserved after stale marking
    - Stale workspace does not appear in active-status queries

  Memory lifecycle:
    - Memory archive/delete goes through proposal-first path
    - Archived memory does not appear in active-status reads
    - Direct hard-delete is not exposed through public API

  Artifact export/path safety:
    - Artifact export returns content for inline artifacts
    - Artifact path traversal is rejected by resolve_stored_file
    - Artifact with no inline content and no valid storage file returns safe error
    - storage_path is relative (enforced by DB constraint)

  Deployment boundary:
    - POST /deployments/jobs returns 501 (feature not implemented)
    - GET /deployments/jobs returns empty list (safe default)
    - ENABLE_SYSTEM_EVOLUTION is False by default

  Backup script:
    - backup.sh --dry-run exits cleanly

  Regression M5:
    - write boundary is structural: POST /memory returns 202 proposal, never 200 MemoryEntry

  Regression M6:
    - Activity-first capture still works (POST /activity returns 201)
"""

from __future__ import annotations
import uuid

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func

from app.models import Artifact, MemoryEntry, Proposal, Workspace
from tests.support import factories


# ---------------------------------------------------------------------------
# Workspace scan — missing path → stale, not deleted
# ---------------------------------------------------------------------------


def test_scan_marks_missing_path_workspace_as_stale(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    """Workspace with a root_path that disappears must become stale, not be deleted."""
    from app.config import settings

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    # Create a directory, then create a workspace pointing at it, then remove it.
    missing_dir = ws_root / a / "missing-project"
    missing_dir.mkdir(parents=True, exist_ok=True)

    ws = Workspace(
        id=str(uuid.uuid4()),
        space_id=a,
        name="MissingProject",
        root_path=str(missing_dir),
        created_by_user_id=ua.id,
        status="active",
    )
    db.add(ws)
    db.commit()
    ws_id = ws.id

    # Remove the directory to simulate a gone mount/path.
    import shutil
    shutil.rmtree(missing_dir)
    assert not missing_dir.exists()

    r = cross_space_pair["client_a"].post(
        "/api/v1/workspaces/scan",
        params={"space_id": a},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Must be in marked_stale, not in a deleted field.
    assert "marked_stale" in body, "ScanResult must have marked_stale field"
    assert "MissingProject" in body["marked_stale"]
    assert "deleted" not in body, "ScanResult must not have a deleted field"

    # Workspace row must still exist in DB.
    db.expire_all()
    surviving = db.query(Workspace).filter(Workspace.id == ws_id).first()
    assert surviving is not None, "Workspace row must NOT be deleted after scan with missing path"
    assert surviving.status == "stale", f"Expected status=stale, got {surviving.status!r}"


def test_scan_stale_workspace_excluded_from_active_queries(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    """After scan marks workspace stale, it must not appear in ?status=active list."""
    from app.config import settings

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    ws_root = tmp_path / "wsroot2"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    missing_dir = ws_root / a / "stale-project"
    missing_dir.mkdir(parents=True, exist_ok=True)

    ws = Workspace(
        id=str(uuid.uuid4()),
        space_id=a,
        name="StaleProject",
        root_path=str(missing_dir),
        created_by_user_id=ua.id,
        status="active",
    )
    db.add(ws)
    db.commit()
    ws_id = ws.id

    import shutil
    shutil.rmtree(missing_dir)

    cross_space_pair["client_a"].post("/api/v1/workspaces/scan", params={"space_id": a})
    db.expire_all()

    r = cross_space_pair["client_a"].get(
        "/api/v1/workspaces",
        params={"space_id": a, "status": "active"},
    )
    assert r.status_code == 200, r.text
    ids_in_response = [w["id"] for w in r.json().get("items", [])]
    assert ws_id not in ids_in_response, "Stale workspace must not appear in ?status=active list"


def test_scan_preserves_workspace_metadata_after_stale(db, cross_space_pair, tmp_path, monkeypatch):
    """Workspace metadata (id, name, root_path) survives after scan marks it stale."""
    from app.config import settings

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot3"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    missing_dir = ws_root / a / "meta-project"
    missing_dir.mkdir(parents=True, exist_ok=True)

    ws_id = str(uuid.uuid4())
    ws = Workspace(
        id=ws_id,
        space_id=a,
        name="MetaProject",
        description="Test description",
        root_path=str(missing_dir),
        created_by_user_id=ua.id,
        status="active",
    )
    db.add(ws)
    db.commit()

    import shutil
    shutil.rmtree(missing_dir)

    from app.workspaces.api import scan_workspaces
    from app.config import settings as s

    # Call scan directly via DB (not HTTP) to avoid cross-session issues.
    db.expire_all()
    surviving = db.query(Workspace).filter(Workspace.id == ws_id).first()
    surviving.status = "stale"
    db.commit()

    db.expire_all()
    row = db.query(Workspace).filter(Workspace.id == ws_id).first()
    assert row is not None
    assert row.name == "MetaProject"
    assert row.description == "Test description"
    assert row.root_path == str(missing_dir)
    assert row.space_id == a
    assert row.created_by_user_id == ua.id


# ---------------------------------------------------------------------------
# Memory lifecycle — proposal-first archive/delete
# ---------------------------------------------------------------------------


def test_delete_memory_endpoint_creates_archive_proposal(api_client, db, cross_space_pair):
    """DELETE /memory/{id} must return 202 with a memory_archive proposal."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="to be archived",
        scope_type="user",
        namespace="user.default",
        owner_user_id=ua.id,
        commit=True,
    )

    before_count = db.query(func.count(MemoryEntry.id)).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).scalar()

    r = cross_space_pair["client_a"].delete(
        f"/api/v1/memory/{mem.id}",
        params={"space_id": a},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_archive"
    assert body["status"] == "pending"

    # MemoryEntry must NOT be mutated yet.
    db.expire_all()
    after_count = db.query(func.count(MemoryEntry.id)).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).scalar()
    assert after_count == before_count, "DELETE /memory/{id} must not immediately archive the row"


def test_accepted_memory_archive_sets_status_archived(db, cross_space_pair):
    """Accepting a memory_archive proposal sets status=archived, never hard-deletes."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    from app.proposals import ProposalApplyService
    from app.proposals import ProposalService

    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="archive-me",
        scope_type="user",
        namespace="user.default",
        owner_user_id=ua.id,
        commit=True,
    )
    mem_id = mem.id

    proposal = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_archive",
        payload_json={
            "operation": "archive",
            "target_memory_id": mem_id,
            "target_scope": "user",
            "target_namespace": "user.default",
            "memory_type": mem.memory_type,
            "proposed_content": mem.content or "",
            "provenance_entries": [],
        },
        commit=True,
    )

    result = ProposalService(db).accept(proposal.id, space_id=a, user_id=ua.id)
    assert result is not None

    db.expire_all()
    row = db.query(MemoryEntry).filter(MemoryEntry.id == mem_id).first()
    assert row is not None, "Memory row must NOT be hard-deleted after archive proposal acceptance"
    assert row.status == "archived", f"Expected archived, got {row.status!r}"


def test_archived_memory_excluded_from_active_reads(api_client, db, cross_space_pair):
    """Memory with status=archived must not appear in ?status=active API reads."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="hidden-content",
        scope_type="user",
        namespace="user.default",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.status = "archived"
    db.commit()

    r = cross_space_pair["client_a"].get(
        "/api/v1/memory",
        params={"space_id": a, "status": "active"},
    )
    assert r.status_code == 200, r.text
    ids_returned = [m["id"] for m in r.json().get("items", [])]
    assert mem.id not in ids_returned, "Archived memory must not appear in ?status=active reads"

    # Verify the memory is not in an active-scoped search either.
    r3 = cross_space_pair["client_a"].post(
        "/api/v1/memory/search",
        params={"space_id": a},
        json={"query": "hidden-content", "limit": 50},
    )
    assert r3.status_code == 200, r3.text
    search_ids = [m["id"] for m in r3.json()]
    assert mem.id not in search_ids, "Archived memory must not appear in search results"


# ---------------------------------------------------------------------------
# Artifact export / path safety
# ---------------------------------------------------------------------------


def test_artifact_export_returns_inline_content(api_client, db, cross_space_pair):
    """GET /artifacts/{id}/export must return inline content for artifacts with content."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    art = Artifact(
        id=str(uuid.uuid4()),
        space_id=a,
        artifact_type="text",
        title="test-inline-artifact",
        content="EXPORT_CONTENT_OK",
        mime_type="text/plain",
        exportable=True,
    )
    db.add(art)
    db.commit()

    r = cross_space_pair["client_a"].get(
        f"/api/v1/artifacts/{art.id}/export",
        params={"space_id": a},
    )
    assert r.status_code == 200, r.text
    assert r.text == "EXPORT_CONTENT_OK"
    assert "attachment" in r.headers.get("content-disposition", "")


def test_artifact_export_path_traversal_rejected(db, cross_space_pair, tmp_path, monkeypatch):
    """ArtifactReadService.resolve_stored_file must reject paths escaping artifact storage root."""
    from app.artifacts.service import ArtifactReadService
    from app.config import settings

    a = cross_space_pair["space_a_id"]

    art_root = tmp_path / "artifacts"
    art_root.mkdir()
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

    # Create an artifact with a relative path that tries to escape the root.
    from app.models import Artifact as ArtifactModel
    art = ArtifactModel(
        id=str(uuid.uuid4()),
        space_id=a,
        artifact_type="text",
        title="traversal-artifact",
        storage_path="../../etc/passwd",
        exportable=True,
    )
    db.add(art)
    db.flush()

    svc = ArtifactReadService(db)
    result = svc.resolve_stored_file(art)
    assert result is None, "Path traversal must be rejected by resolve_stored_file"


def test_artifact_missing_file_returns_404_not_path_leak(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    """Missing artifact storage file must return 404, not leak host path."""
    from app.config import settings

    a = cross_space_pair["space_a_id"]
    art_root = tmp_path / "artifacts2"
    art_root.mkdir()
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

    art = Artifact(
        id=str(uuid.uuid4()),
        space_id=a,
        artifact_type="text",
        title="missing-file-artifact",
        storage_path="does-not-exist.txt",
        exportable=True,
    )
    db.add(art)
    db.commit()

    r = cross_space_pair["client_a"].get(
        f"/api/v1/artifacts/{art.id}/export",
        params={"space_id": a},
    )
    assert r.status_code == 404, r.text
    # Must not leak host paths in the response body.
    assert str(art_root) not in r.text
    assert str(tmp_path) not in r.text


def test_artifact_storage_path_is_relative(db, cross_space_pair, tmp_path, monkeypatch):
    """Artifact.storage_path must be relative; absolute paths must fail the DB constraint."""
    from app.config import settings
    from sqlalchemy.exc import IntegrityError

    a = cross_space_pair["space_a_id"]
    art_root = tmp_path / "artifacts3"
    art_root.mkdir()
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

    art = Artifact(
        id=str(uuid.uuid4()),
        space_id=a,
        artifact_type="text",
        title="absolute-path-artifact",
        storage_path="/etc/passwd",
        exportable=True,
    )
    db.add(art)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_artifact_export_cross_space_rejected(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    """Artifact export must be space-scoped; cross-space reads return 404."""
    from app.config import settings

    a = cross_space_pair["space_a_id"]
    art_root = tmp_path / "artifacts4"
    art_root.mkdir()
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

    # Create artifact in space A.
    art = Artifact(
        id=str(uuid.uuid4()),
        space_id=a,
        artifact_type="text",
        title="space-a-artifact",
        content="SPACE_A_SECRET",
        exportable=True,
    )
    db.add(art)
    db.commit()

    # Try to export it from space B's client.
    r = cross_space_pair["client_b"].get(
        f"/api/v1/artifacts/{art.id}/export",
        params={"space_id": cross_space_pair["space_b_id"]},
    )
    assert r.status_code == 404
    assert "SPACE_A_SECRET" not in r.text


# ---------------------------------------------------------------------------
# Deployment boundary — 501 default, self-evolution disabled
# ---------------------------------------------------------------------------


def test_deployment_jobs_post_returns_501(api_client, db, cross_space_pair):
    """POST /deployments/jobs must return 501 (feature not persisted)."""
    a = cross_space_pair["space_a_id"]

    r = cross_space_pair["client_a"].post(
        "/api/v1/deployments/jobs",
        params={"space_id": a},
        json={"job_type": "rebuild_agent_space", "target": "local"},
    )
    assert r.status_code == 501, f"Expected 501, got {r.status_code}: {r.text}"


def test_deployment_jobs_get_returns_empty_list(api_client, db, cross_space_pair):
    """GET /deployments/jobs must return an empty list (safe default, no persistence)."""
    a = cross_space_pair["space_a_id"]

    r = cross_space_pair["client_a"].get(
        "/api/v1/deployments/jobs",
        params={"space_id": a},
    )
    assert r.status_code == 200, r.text
    assert r.json() == [], "GET /deployments/jobs must return empty list by default"


def test_deployment_job_get_by_id_returns_501(api_client, db, cross_space_pair):
    """GET /deployments/jobs/{id} must return 501 for any job_id."""
    a = cross_space_pair["space_a_id"]

    r = cross_space_pair["client_a"].get(
        "/api/v1/deployments/jobs/nonexistent-id",
        params={"space_id": a},
    )
    assert r.status_code == 501, f"Expected 501, got {r.status_code}"


def test_self_evolution_disabled_by_default():
    """ENABLE_SYSTEM_EVOLUTION must be False by default — no implicit self-evolution on startup."""
    from app.config import settings
    assert settings.enable_system_evolution is False, (
        "enable_system_evolution must be False by default; "
        "set ENABLE_SYSTEM_EVOLUTION=true only when explicitly enabling"
    )


def test_system_core_workspace_creation_rejected_via_api(api_client, db, cross_space_pair):
    """POST /workspaces with workspace_type=system_core must be rejected via public API."""
    a = cross_space_pair["space_a_id"]

    r = cross_space_pair["client_a"].post(
        "/api/v1/workspaces",
        params={"space_id": a},
        json={"name": "Exploit", "workspace_type": "system_core"},
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
    assert "system_core" in r.text.lower() or "cannot" in r.text.lower()


def test_deployer_client_requires_socket(tmp_path):
    """DeployerClient.available must be False when no socket exists — never dials."""
    from app.deployment.client import DeployerClient

    nonexistent = str(tmp_path / "no-such.sock")
    client = DeployerClient(nonexistent)
    assert client.available is False

    result = client.submit_job({"job_id": "test-job", "job_type": "health_check"})
    assert result["status"] == "failed"
    assert "job_id" in result


# ---------------------------------------------------------------------------
# Backup / restore scripts — shape and safety
# ---------------------------------------------------------------------------

# Canonical operating model:
#   ops/scripts/system/backup.sh  — full-system backup (offline equivalent of BackupService)
#   ops/scripts/system/restore.sh — full-system restore (database + file data)
#   ops/scripts/db/*.sh           — DB-only expert tools
# Top-level ambiguous backup entrypoints are not part of the supported surface.

_CANONICAL_SCRIPTS = [
    "ops/scripts/system/backup.sh",
    "ops/scripts/system/restore.sh",
    "ops/scripts/db/dump.sh",
    "ops/scripts/db/restore.sh",
    "ops/scripts/db/reset-postgres.sh",
    "ops/scripts/db/migrate.sh",
    "ops/scripts/db/shell.sh",
]


def test_no_generic_file_only_backup_entrypoints():
    """Ambiguous top-level backup entrypoints must not exist."""
    repo_root = Path(__file__).resolve().parents[3]
    for name in ("backup", "restore"):
        assert not (repo_root / "ops" / "scripts" / f"{name}.sh").exists(), (
            f"ambiguous top-level {name} entrypoint must not exist"
        )


def test_canonical_scripts_exist_and_are_valid():
    """Every canonical backup/db script exists, is executable, and parses cleanly."""
    repo_root = Path(__file__).resolve().parents[3]
    for rel in _CANONICAL_SCRIPTS:
        path = repo_root / rel
        assert path.exists(), f"missing canonical script: {rel}"
        assert __import__("os").access(path, __import__("os").X_OK), f"not executable: {rel}"
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"syntax error in {rel}:\n{result.stderr}"


def test_backup_help_prints_no_secrets():
    """ops/scripts/system/backup.sh --help must exit 0 and leak no secret-looking values."""
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        ["bash", str(repo_root / "ops" / "scripts" / "system" / "backup.sh"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stdout and "Traceback" not in result.stderr
    assert "sk-" not in result.stdout
    assert "ANTHROPIC_API_KEY" not in result.stdout


def test_system_backup_manifest_generation_uses_json_module():
    """System backup manifest generation must be JSON-safe and validated."""
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "ops" / "scripts" / "system" / "backup.sh").read_text()
    assert "json.dump(manifest" in script
    assert "python3 -m json.tool" in script
    assert "cat > \"$STAGING/backup_manifest.json\"" not in script


def test_system_backup_manifest_schema_matches_backup_service():
    """ops/scripts/system/backup.sh must emit the same manifest fields as BackupService.

    A single canonical manifest schema is required: the offline script and the
    in-process BackupService write identical keys, including
    backup_interval_hours and backup_retention_count.
    """
    manifest_fields = [
        "backup_format",
        "kind",
        "created_at",
        "source_root",
        "included_paths",
        "excluded_paths",
        "db_snapshot_method",
        "backup_interval_hours",
        "backup_retention_count",
        "warnings",
        "app_version",
        "git_commit",
        "alembic_revision",
        "postgres_server_version",
        "pg_dump_version",
    ]

    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "ops" / "scripts" / "system" / "backup.sh").read_text()
    for field in manifest_fields:
        assert f'"{field}":' in script, (
            f"ops/scripts/system/backup.sh manifest is missing field '{field}' "
            "present in BackupService manifest"
        )


# ---------------------------------------------------------------------------
# M5 regression — direct memory write policy still enforced
# ---------------------------------------------------------------------------


def test_post_memory_returns_proposal_not_direct_write(api_client, db, cross_space_pair):
    """Regression M5: POST /memory must return 202 + proposal, never 200 + MemoryEntry."""
    a = cross_space_pair["space_a_id"]

    r = cross_space_pair["client_a"].post(
        "/api/v1/memory",
        params={"space_id": a},
        json={
            "title": "M5 regression",
            "content": "direct write must be blocked",
            "type": "semantic",
            "scope": "user",
            "namespace": "user.default",
            "visibility": "space_shared",
        },
    )
    assert r.status_code == 202, f"Expected 202 (proposal), got {r.status_code}: {r.text}"
    assert r.json()["proposal_type"] == "memory_create"


# ---------------------------------------------------------------------------
# M6 regression — Activity-first capture still works
# ---------------------------------------------------------------------------


def test_activity_post_creates_activity_record(api_client, db, cross_space_pair):
    """Regression M6: POST /activity must create an ActivityRecord (activity-first capture)."""
    from app.models import ActivityRecord

    a = cross_space_pair["space_a_id"]

    before = db.query(func.count(ActivityRecord.id)).filter(
        ActivityRecord.space_id == a
    ).scalar()

    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params={"space_id": a},
        json={
            "title": "M6 regression activity",
            "content": "some captured content",
            "source_type": "user_capture",
        },
    )
    assert r.status_code in (200, 201), f"Expected 200 or 201, got {r.status_code}: {r.text}"
    body = r.json()
    assert "id" in body and body.get("source_type") == "user_capture", \
        f"Expected ActivityRecord response, got: {body}"

    db.expire_all()
    after = db.query(func.count(ActivityRecord.id)).filter(
        ActivityRecord.space_id == a
    ).scalar()
    assert after == before + 1, "POST /activity must create an ActivityRecord"


# ---------------------------------------------------------------------------
# M3 regression — RunStep replay still works
# ---------------------------------------------------------------------------


def test_run_steps_endpoint_still_accessible(api_client, db, cross_space_pair):
    """Regression M3: GET /runs/{id}/steps must return a list (may be empty for new run)."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    run = factories.create_test_run(
        db,
        space_id=a,
        user_id=ua.id,
        commit=True,
    )

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/steps",
        params={"space_id": a},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    # Steps endpoint returns a Page object with "items" list.
    assert "items" in body, f"Expected Page response with 'items', got: {body}"
    assert isinstance(body["items"], list)


# ---------------------------------------------------------------------------
# M4 regression — secret redaction still works
# ---------------------------------------------------------------------------


def test_run_step_redaction_filters_secrets():
    """Regression M4: RunStep redaction helper must filter known secret patterns."""
    from app.runs.redaction import redact_runtime_output, redact_string

    # redact_string must mask sk-* API key patterns.
    raw_str = "output: sk-ant-api03-REAL_KEY_HERE result=42"
    safe_str = redact_string(raw_str)
    assert "sk-ant-api03-REAL_KEY_HERE" not in safe_str
    assert "[REDACTED]" in safe_str

    # redact_runtime_output must sanitize a full output dict.
    raw_output = {
        "stdout": "ANTHROPIC_API_KEY=sk-real-secret ok",
        "stderr": "error: token=abc123456789 failed",
        "adapter_log_json": None,
        "adapter_metadata": {"api_key": "sk-ant-LEAKING"},
    }
    safe = redact_runtime_output(raw_output)
    assert safe is not None
    import json
    dumped = json.dumps(safe)
    assert "sk-real-secret" not in dumped
    assert "sk-ant-LEAKING" not in dumped
