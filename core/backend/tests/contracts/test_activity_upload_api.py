"""HTTP contract: POST /api/v1/activity/upload — file / voice capture (store-only).

Verifies the upload is streamed to the data root and recorded as a canonical
``file_import`` Activity Inbox record carrying the capture kind and file metadata.
No transcription is performed.
"""

from __future__ import annotations

import uuid

from app.auth.session import SESSION_COOKIE, UserSessionService
from app.config import paths
from app.main import app as _app
from app.models import ActivityRecord
from starlette.testclient import TestClient
from tests.support import factories


def _new_id() -> str:
    return str(uuid.uuid4())


def _authed_client(db, user_id: str) -> TestClient:
    _, raw = UserSessionService(db).create(user_id)
    db.commit()
    return TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)


def _space_user(db):
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="P", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    return space_id, user


def test_upload_file_capture_stores_and_records(api_client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "uploads_dir", tmp_path / "uploads")
    space_id, user = _space_user(db)
    c = _authed_client(db, user.id)

    r = c.post(
        "/api/v1/activity/upload",
        params={"space_id": space_id},
        files={"file": ("note.txt", b"hello world", "text/plain")},
        data={"kind": "file", "title": "My note"},
    )
    assert r.status_code == 200, r.text
    rec = r.json()
    # file_capture normalizes to the canonical file_import source type (no migration).
    assert rec["source_type"] == "file_import"
    assert rec["title"] == "My note"
    meta = rec["metadata_json"]
    assert meta["capture_kind"] == "file"
    assert meta["filename"] == "note.txt"
    assert meta["mime_type"] == "text/plain"
    assert meta["size_bytes"] == len(b"hello world")

    stored = tmp_path / "uploads" / meta["stored_path"]
    assert stored.is_file()
    assert stored.read_bytes() == b"hello world"

    # It is a real Activity Inbox row in this space.
    db.expire_all()
    rows = db.query(ActivityRecord).filter(ActivityRecord.space_id == space_id).all()
    assert any(a.id == rec["id"] for a in rows)


def test_upload_voice_capture_normalizes_to_file_import(api_client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "uploads_dir", tmp_path / "uploads")
    space_id, user = _space_user(db)
    c = _authed_client(db, user.id)

    r = c.post(
        "/api/v1/activity/upload",
        params={"space_id": space_id},
        files={"file": ("memo.webm", b"RIFFfakeaudiodata", "audio/webm")},
        data={"kind": "voice"},
    )
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["source_type"] == "file_import"
    assert rec["metadata_json"]["capture_kind"] == "voice"
    assert rec["metadata_json"]["mime_type"] == "audio/webm"


def test_upload_rejects_unsupported_mime(api_client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "uploads_dir", tmp_path / "uploads")
    space_id, user = _space_user(db)
    c = _authed_client(db, user.id)
    r = c.post(
        "/api/v1/activity/upload",
        params={"space_id": space_id},
        files={"file": ("x.exe", b"MZbinary", "application/x-msdownload")},
        data={"kind": "file"},
    )
    assert r.status_code == 415


def test_upload_rejects_empty_file(api_client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "uploads_dir", tmp_path / "uploads")
    space_id, user = _space_user(db)
    c = _authed_client(db, user.id)
    r = c.post(
        "/api/v1/activity/upload",
        params={"space_id": space_id},
        files={"file": ("empty.txt", b"", "text/plain")},
        data={"kind": "file"},
    )
    assert r.status_code == 422


def test_upload_voice_rejects_non_audio(api_client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "uploads_dir", tmp_path / "uploads")
    space_id, user = _space_user(db)
    c = _authed_client(db, user.id)
    r = c.post(
        "/api/v1/activity/upload",
        params={"space_id": space_id},
        files={"file": ("note.txt", b"not audio", "text/plain")},
        data={"kind": "voice"},
    )
    assert r.status_code == 422
