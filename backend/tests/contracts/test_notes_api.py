"""Contract tests for the Knowledge module's Notes + EntityLink + summary API.

Notes are the *working knowledge* layer: direct CRUD (no proposal gate), unlike
the proposal-governed wiki KnowledgeItem covered by ``test_knowledge_api.py``.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Note, NoteCollectionItem
from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def _note_payload(**overrides):
    payload = {"title": "Design note", "plain_text": "exploring the knowledge module"}
    payload.update(overrides)
    return payload


def _rich_note_json(*parts: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": part}]}
            for part in parts
        ],
    }


def test_unauthenticated_notes_endpoint_returns_401(api_client):
    r = api_client.get("/api/v1/knowledge/notes")
    assert r.status_code == 401


def test_default_note_collections_seeded_for_space(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    r = client.get("/api/v1/notes/collections", params=_params(a))
    assert r.status_code == 200
    rows = r.json()
    names = [row["name"] for row in rows]
    assert names == ["Inbox", "Projects", "Areas", "Resources", "Archive"]
    assert [row["system_role"] for row in rows if row["name"] == "Inbox"] == ["inbox"]
    assert [row["system_role"] for row in rows if row["name"] == "Archive"] == ["archive"]


def test_user_created_collection_defaults_to_normal(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    r = client.post("/api/v1/notes/collections", params=_params(a), json={"name": "Clients"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Clients"
    assert body["system_role"] == "normal"
    assert body["is_system"] is False
    assert body["is_hidden"] is False


def test_system_collections_cannot_be_hard_deleted(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    inbox = next(
        row for row in client.get("/api/v1/notes/collections", params=_params(a)).json()
        if row["system_role"] == "inbox"
    )

    r = client.delete(f"/api/v1/notes/collections/{inbox['id']}", params=_params(a))
    assert r.status_code == 422


def test_normal_empty_collection_can_be_deleted(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    created = client.post("/api/v1/notes/collections", params=_params(a), json={"name": "Temporary"}).json()

    r = client.delete(f"/api/v1/notes/collections/{created['id']}", params=_params(a))
    assert r.status_code == 204
    rows = client.get("/api/v1/notes/collections", params=_params(a)).json()
    assert all(row["id"] != created["id"] for row in rows)


def test_note_create_and_list_by_collection(cross_space_pair, db):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    collection = client.post("/api/v1/notes/collections", params=_params(a), json={"name": "Research"}).json()
    note = client.post(
        "/api/v1/knowledge/notes",
        params=_params(a),
        json=_note_payload(title="Collected note", collection_id=collection["id"]),
    )
    assert note.status_code == 201, note.text
    note_id = note.json()["id"]

    assert (
        db.query(NoteCollectionItem)
        .filter(NoteCollectionItem.collection_id == collection["id"], NoteCollectionItem.note_id == note_id)
        .count()
        == 1
    )

    client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload(title="Inbox note"))
    listed = client.get(
        "/api/v1/knowledge/notes",
        params={**_params(a), "collection_id": collection["id"]},
    )
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == [note_id]

    delete_non_empty = client.delete(f"/api/v1/notes/collections/{collection['id']}", params=_params(a))
    assert delete_non_empty.status_code == 409


def test_note_create_without_collection_defaults_to_inbox(cross_space_pair, db):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    inbox = next(
        row for row in client.get("/api/v1/notes/collections", params=_params(a)).json()
        if row["system_role"] == "inbox"
    )

    note = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload()).json()

    assert (
        db.query(NoteCollectionItem)
        .filter(NoteCollectionItem.collection_id == inbox["id"], NoteCollectionItem.note_id == note["id"])
        .count()
        == 1
    )


def test_note_create_list_get_update_archive_and_delete_are_distinct(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    r = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload())
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["status"] == "active"
    assert note["title"] == "Design note"
    assert note["content_format"] == "markdown"
    assert note["excerpt"] == "exploring the knowledge module"
    note_id = note["id"]

    lst = client.get("/api/v1/knowledge/notes", params=_params(a))
    assert lst.status_code == 200
    assert any(n["id"] == note_id for n in lst.json()["items"])

    got = client.get(f"/api/v1/knowledge/notes/{note_id}", params=_params(a))
    assert got.status_code == 200
    assert got.json()["plain_text"] == "exploring the knowledge module"

    upd = client.patch(
        f"/api/v1/knowledge/notes/{note_id}",
        params=_params(a),
        json={"title": "Design note v2", "plain_text": "now with detail"},
    )
    assert upd.status_code == 200
    assert upd.json()["title"] == "Design note v2"
    assert upd.json()["excerpt"] == "now with detail"  # regenerated from new plain_text

    archived = client.patch(
        f"/api/v1/knowledge/notes/{note_id}",
        params=_params(a),
        json={"status": "archived"},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["archived_at"] is not None
    assert archived.json()["deleted_at"] is None

    deleted = client.delete(f"/api/v1/knowledge/notes/{note_id}", params=_params(a))
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["archived_at"] is None
    assert deleted.json()["deleted_at"] is not None

    active = client.get("/api/v1/knowledge/notes", params={**_params(a), "status": "active"})
    assert all(n["id"] != note_id for n in active.json()["items"])
    archived_list = client.get("/api/v1/knowledge/notes", params={**_params(a), "status": "archived"})
    assert all(n["id"] != note_id for n in archived_list.json()["items"])
    deleted_list = client.get("/api/v1/knowledge/notes", params={**_params(a), "status": "deleted"})
    assert [n["id"] for n in deleted_list.json()["items"]] == [note_id]
    default_list = client.get("/api/v1/knowledge/notes", params=_params(a))
    assert all(n["id"] != note_id for n in default_list.json()["items"])


def test_note_create_rejects_non_active_status(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    draft = client.post(
        "/api/v1/knowledge/notes",
        params=_params(a),
        json=_note_payload(status="draft"),
    )
    assert draft.status_code == 422

    archived = client.post(
        "/api/v1/knowledge/notes",
        params=_params(a),
        json=_note_payload(status="archived"),
    )
    assert archived.status_code == 422


def test_note_create_with_structured_json_projects_plain_text_excerpt_and_search(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    content_json = _rich_note_json("Structured note heading", "Findable body text")

    r = client.post(
        "/api/v1/knowledge/notes",
        params=_params(a),
        json={
            "title": "Rich note",
            "content_json": content_json,
            "content_format": "prosemirror_json",
            "content_schema_version": 1,
            "plain_text": "stale client projection",
        },
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content_json"] == content_json
    assert body["content_format"] == "prosemirror_json"
    assert body["content_schema_version"] == 1
    assert body["plain_text"] == "Structured note heading Findable body text"
    assert body["excerpt"] == "Structured note heading Findable body text"
    assert "stale client projection" not in body["plain_text"]

    search = client.get("/api/v1/knowledge/notes", params={**_params(a), "q": "Findable"})
    assert [row["id"] for row in search.json()["items"]] == [body["id"]]


def test_note_update_from_plain_text_to_structured_json_refreshes_projection(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    note = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload()).json()
    content_json = _rich_note_json("Updated rich text", "Projection refreshed")

    upd = client.patch(
        f"/api/v1/knowledge/notes/{note['id']}",
        params=_params(a),
        json={
            "content_json": content_json,
            "content_format": "prosemirror_json",
            "content_schema_version": 1,
            "plain_text": "old stale text",
        },
    )

    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["content_json"] == content_json
    assert body["plain_text"] == "Updated rich text Projection refreshed"
    assert body["excerpt"] == "Updated rich text Projection refreshed"
    assert "old stale text" not in body["plain_text"]


def test_deleted_notes_can_be_hard_purged_after_retention(cross_space_pair, db):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    note = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload()).json()
    deleted = client.delete(f"/api/v1/knowledge/notes/{note['id']}", params=_params(a))
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    row = db.get(Note, note["id"])
    assert row is not None
    row.deleted_at = datetime.now(UTC) - timedelta(days=31)
    db.commit()

    purge = client.post("/api/v1/knowledge/notes/deleted/purge", params=_params(a))
    assert purge.status_code == 200
    assert purge.json() == {"deleted": 1, "retention_days": 30}
    assert db.get(Note, note["id"]) is None

    missing = client.get(f"/api/v1/knowledge/notes/{note['id']}", params=_params(a))
    assert missing.status_code == 404


def test_notes_are_space_scoped(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    client_a = cross_space_pair["client_a"]
    client_b = cross_space_pair["client_b"]

    created = client_a.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload()).json()

    cross = client_b.get(f"/api/v1/knowledge/notes/{created['id']}", params=_params(b))
    assert cross.status_code == 404
    lst_b = client_b.get("/api/v1/knowledge/notes", params=_params(b))
    assert all(n["id"] != created["id"] for n in lst_b.json()["items"])


def test_note_create_with_project_and_filter(cross_space_pair, db):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    project = factories.create_test_project(db, space_id=a, name="kb", commit=True)

    r = client.post(
        "/api/v1/knowledge/notes",
        params=_params(a),
        json=_note_payload(primary_project_id=project.id),
    )
    assert r.status_code == 201
    assert r.json()["primary_project_id"] == project.id

    lst = client.get("/api/v1/knowledge/notes", params={**_params(a), "project_id": project.id})
    assert [n["id"] for n in lst.json()["items"]] == [r.json()["id"]]


def test_note_create_with_unknown_project_is_422(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    r = client.post(
        "/api/v1/knowledge/notes",
        params=_params(a),
        json=_note_payload(primary_project_id="does-not-exist"),
    )
    assert r.status_code == 422


def test_note_links_and_backlinks(cross_space_pair, db):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    wiki = factories.create_test_knowledge_item(db, space_id=a, title="Canonical X", commit=True)

    note1 = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload(title="N1")).json()
    note2 = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload(title="N2")).json()

    link = client.post(
        f"/api/v1/knowledge/notes/{note1['id']}/links",
        params=_params(a),
        json={"target_type": "knowledge_item", "target_id": wiki.id, "link_type": "references"},
    )
    assert link.status_code == 201, link.text
    assert link.json()["source_type"] == "note"
    assert link.json()["target_type"] == "knowledge_item"

    client.post(
        f"/api/v1/knowledge/notes/{note2['id']}/links",
        params=_params(a),
        json={"target_type": "note", "target_id": note1["id"], "link_type": "related_to"},
    )

    links = client.get(f"/api/v1/knowledge/notes/{note1['id']}/links", params=_params(a)).json()
    assert any(item["target_id"] == wiki.id for item in links)

    backlinks = client.get(f"/api/v1/knowledge/notes/{note1['id']}/backlinks", params=_params(a)).json()
    assert [bl["source_id"] for bl in backlinks] == [note2["id"]]

    link_id = link.json()["id"]
    dele = client.delete(f"/api/v1/knowledge/notes/{note1['id']}/links/{link_id}", params=_params(a))
    assert dele.status_code == 204
    remaining = client.get(f"/api/v1/knowledge/notes/{note1['id']}/links", params=_params(a)).json()
    assert all(item["id"] != link_id for item in remaining)


def test_note_self_link_rejected(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    note = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload()).json()
    r = client.post(
        f"/api/v1/knowledge/notes/{note['id']}/links",
        params=_params(a),
        json={"target_type": "note", "target_id": note["id"], "link_type": "related_to"},
    )
    assert r.status_code == 422


def test_note_link_unknown_target_is_404(cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    note = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload()).json()
    r = client.post(
        f"/api/v1/knowledge/notes/{note['id']}/links",
        params=_params(a),
        json={"target_type": "knowledge_item", "target_id": "does-not-exist", "link_type": "references"},
    )
    assert r.status_code == 404


def test_knowledge_summary_counts(cross_space_pair, db):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    factories.create_test_knowledge_item(db, space_id=a, title="W", status="active", commit=True)
    client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload(title="active note"))
    archived = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload(title="archived note")).json()
    deleted = client.post("/api/v1/knowledge/notes", params=_params(a), json=_note_payload(title="deleted note")).json()
    client.patch(f"/api/v1/knowledge/notes/{archived['id']}", params=_params(a), json={"status": "archived"})
    client.delete(f"/api/v1/knowledge/notes/{deleted['id']}", params=_params(a))

    s = client.get("/api/v1/knowledge/summary", params=_params(a)).json()
    assert s["notes"]["active"] == 1
    assert s["notes"]["archived"] == 1
    assert s["notes"]["deleted"] == 1
    assert s["notes"]["total"] == 2
    assert s["wiki"]["active"] == 1
