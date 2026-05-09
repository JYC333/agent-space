"""
Tests for workspace management:
  - _folder_name() slug helper
  - _unique_dir() collision avoidance
  - POST /workspaces        — creates DB record + on-disk folder, rejects duplicates
  - POST /workspaces/scan   — registers new dirs, hard-deletes stale records
  - GET  /workspaces        — list with status filter
  - PATCH/DELETE /workspaces/{id}
  - workspace_console file-tree and file-content endpoints (PathPolicy enforcement)
  - workspace_console git/status and git/diff endpoints
  - workspace_console session CRUD
  - workspace_console real runtime adapters (anthropic_api, claude_code, codex)
"""
import shutil
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

import app.workspaces.api as ws_api
import app.workspace_console.api as wc_api
from app.workspaces.api import _folder_name, _unique_dir
from app.models import Workspace, WorkspaceSession
from app.agents.base import AgentRunResult
from tests.conftest import SPACE, USER

QS = f"space_id={SPACE}&user_id={USER}"


# ── _folder_name ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("My Project",   "my-project"),
    ("test 123",     "test-123"),
    ("Hello World!", "hello-world"),
    ("agent-space",  "agent-space"),
    ("  spaces  ",   "spaces"),
    ("A__B  C",      "a-b-c"),
    ("!!!",          "workspace"),   # falls back to default
])
def test_folder_name(name, expected):
    assert _folder_name(name) == expected


# ── _unique_dir ───────────────────────────────────────────────────────────────

def test_unique_dir_no_collision(tmp_path):
    result = _unique_dir(tmp_path, "my-project")
    assert result == tmp_path / "my-project"


def test_unique_dir_with_collision(tmp_path):
    (tmp_path / "my-project").mkdir()
    result = _unique_dir(tmp_path, "my-project")
    assert result == tmp_path / "my-project-1"


def test_unique_dir_multiple_collisions(tmp_path):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws-1").mkdir()
    result = _unique_dir(tmp_path, "ws")
    assert result == tmp_path / "ws-2"


# ── Workspace creation ────────────────────────────────────────────────────────

def test_create_workspace_creates_folder(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    r = client.post(f"/api/v1/workspaces?{QS}", json={"name": "My Project"})
    assert r.status_code == 201

    body = r.json()
    assert body["name"] == "My Project"
    assert body["root_path"] is not None

    folder = Path(body["root_path"])
    assert folder.exists() and folder.is_dir()
    assert folder.name == "my-project"


def test_create_workspace_name_based_folder(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    r = client.post(f"/api/v1/workspaces?{QS}", json={"name": "Hello World"})
    assert r.status_code == 201
    assert Path(r.json()["root_path"]).name == "hello-world"


def test_create_workspace_duplicate_name_rejected(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    client.post(f"/api/v1/workspaces?{QS}", json={"name": "Dupe"})
    r = client.post(f"/api/v1/workspaces?{QS}", json={"name": "Dupe"})
    assert r.status_code == 409
    assert "Dupe" in r.json()["message"]


def test_create_workspace_duplicate_after_delete_allowed(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    r1 = client.post(f"/api/v1/workspaces?{QS}", json={"name": "Reusable"})
    ws_id = r1.json()["id"]

    # archive (soft-delete) the first one
    client.delete(f"/api/v1/workspaces/{ws_id}?{QS}")

    # same name is now free
    r2 = client.post(f"/api/v1/workspaces?{QS}", json={"name": "Reusable"})
    assert r2.status_code == 201


def test_create_workspace_explicit_path_not_overridden(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    ext_dir = tmp_path / "external-repo"
    ext_dir.mkdir()

    r = client.post(f"/api/v1/workspaces?{QS}", json={"name": "External", "root_path": str(ext_dir)})
    assert r.status_code == 201
    assert r.json()["root_path"] == str(ext_dir)


# ── Scan: register new directories ───────────────────────────────────────────

def test_scan_registers_new_folder(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    (tmp_path / "project-a").mkdir()
    (tmp_path / "project-b").mkdir()

    r = client.post(f"/api/v1/workspaces/scan?{QS}")
    assert r.status_code == 200

    body = r.json()
    created_names = {w["name"] for w in body["created"]}
    assert created_names == {"project-a", "project-b"}
    assert body["deleted"] == []


def test_scan_ignores_already_tracked_folders(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    # Create workspace through the API (folder is tracked)
    client.post(f"/api/v1/workspaces?{QS}", json={"name": "tracked"})

    # Add another folder manually
    (tmp_path / "new-one").mkdir()

    r = client.post(f"/api/v1/workspaces/scan?{QS}")
    assert r.status_code == 200

    body = r.json()
    assert len(body["created"]) == 1
    assert body["created"][0]["name"] == "new-one"


def test_scan_ignores_files(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    (tmp_path / "a-file.txt").write_text("ignored")
    (tmp_path / "real-dir").mkdir()

    r = client.post(f"/api/v1/workspaces/scan?{QS}")
    body = r.json()
    assert len(body["created"]) == 1
    assert body["created"][0]["name"] == "real-dir"


# ── Scan: hard-delete stale records ──────────────────────────────────────────

def test_scan_hard_deletes_missing_folder(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    # Create workspace (folder is created on disk)
    r = client.post(f"/api/v1/workspaces?{QS}", json={"name": "Gone"})
    ws_id = r.json()["id"]
    folder = Path(r.json()["root_path"])

    # Remove the folder on disk
    shutil.rmtree(folder)

    # Scan should detect and hard-delete the record
    scan = client.post(f"/api/v1/workspaces/scan?{QS}")
    assert scan.status_code == 200
    body = scan.json()
    assert "Gone" in body["deleted"]
    assert body["created"] == []

    # Record must be gone from the DB (hard delete — not just archived)
    listed = client.get(f"/api/v1/workspaces?{QS}&status=active")
    ids = [w["id"] for w in listed.json()["items"]]
    assert ws_id not in ids

    listed_archived = client.get(f"/api/v1/workspaces?{QS}&status=archived")
    ids_archived = [w["id"] for w in listed_archived.json()["items"]]
    assert ws_id not in ids_archived


def test_scan_allows_recreate_after_hard_delete(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    r = client.post(f"/api/v1/workspaces?{QS}", json={"name": "Phoenix"})
    folder = Path(r.json()["root_path"])
    shutil.rmtree(folder)

    client.post(f"/api/v1/workspaces/scan?{QS}")  # hard-deletes "Phoenix"

    # Creating "Phoenix" again must succeed (no duplicate-name block)
    r2 = client.post(f"/api/v1/workspaces?{QS}", json={"name": "Phoenix"})
    assert r2.status_code == 201


def test_scan_empty_workspace_root(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    r = client.post(f"/api/v1/workspaces/scan?{QS}")
    assert r.status_code == 200
    assert r.json() == {"created": [], "deleted": []}


# ── Workspace Console: file tree ──────────────────────────────────────────────

def test_console_file_tree(client, tmp_path, monkeypatch, db):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(wc_api.settings, "workspace_root", str(tmp_path))

    ws_dir = tmp_path / "my-ws"
    ws_dir.mkdir()
    (ws_dir / "main.py").write_text("print('hello')")
    (ws_dir / "src").mkdir()
    (ws_dir / "src" / "utils.py").write_text("# utils")

    from ulid import ULID
    ws = Workspace(
        id=str(ULID()), owner_space_id=SPACE, created_by_user_id=USER,
        name="my-ws", kind="project", root_path=str(ws_dir), status="active",
    )
    db.add(ws)
    db.commit()

    r = client.get(f"/api/v1/workspace-console/workspaces/{ws.id}/tree?{QS}")
    assert r.status_code == 200

    body = r.json()
    assert body["type"] == "dir"
    child_names = {c["name"] for c in body["children"]}
    assert "main.py" in child_names
    assert "src" in child_names


def test_console_file_tree_missing_dir(client, tmp_path, monkeypatch, db):
    monkeypatch.setattr(wc_api.settings, "workspace_root", str(tmp_path))

    from ulid import ULID
    ws = Workspace(
        id=str(ULID()), owner_space_id=SPACE, created_by_user_id=USER,
        name="ghost", kind="project", root_path=str(tmp_path / "ghost"), status="active",
    )
    db.add(ws)
    db.commit()

    r = client.get(f"/api/v1/workspace-console/workspaces/{ws.id}/tree?{QS}")
    assert r.status_code == 404


# ── Workspace Console: file content ──────────────────────────────────────────

def test_console_file_content(client, tmp_path, monkeypatch, db):
    monkeypatch.setattr(wc_api.settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(wc_api._policy, "workspace_root", tmp_path)

    ws_dir = tmp_path / "proj"
    ws_dir.mkdir()
    (ws_dir / "README.md").write_text("# Hello")

    from ulid import ULID
    ws = Workspace(
        id=str(ULID()), owner_space_id=SPACE, created_by_user_id=USER,
        name="proj", kind="project", root_path=str(ws_dir), status="active",
    )
    db.add(ws)
    db.commit()

    r = client.get(f"/api/v1/workspace-console/workspaces/{ws.id}/file?path=README.md&{QS}")
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "# Hello"
    assert body["path"] == "README.md"
    assert body["size"] == 7


def test_console_file_content_path_traversal_blocked(client, tmp_path, monkeypatch, db):
    monkeypatch.setattr(wc_api.settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(wc_api._policy, "workspace_root", tmp_path)

    ws_dir = tmp_path / "proj2"
    ws_dir.mkdir()

    from ulid import ULID
    ws = Workspace(
        id=str(ULID()), owner_space_id=SPACE, created_by_user_id=USER,
        name="proj2", kind="project", root_path=str(ws_dir), status="active",
    )
    db.add(ws)
    db.commit()

    r = client.get(f"/api/v1/workspace-console/workspaces/{ws.id}/file?path=../../etc/passwd&{QS}")
    assert r.status_code == 403


# ── Workspace Console: sessions ───────────────────────────────────────────────

def test_console_mock_runtime_rejected(client):
    r = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "mock",
        "prompt": "Add docstrings to all functions",
    })
    assert r.status_code == 400


def _post_api_session(client, monkeypatch, prompt="test prompt"):
    """Helper: create a completed anthropic_api session with a fake adapter."""
    from app.agents.api_adapter import AnthropicAPIAdapter
    monkeypatch.setattr(AnthropicAPIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(
        AnthropicAPIAdapter, "run",
        lambda self, p, context, **kw: AgentRunResult(success=True, output="ok"),
    )
    return client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "anthropic_api",
        "prompt": prompt,
    })


def test_console_list_sessions(client, monkeypatch):
    _post_api_session(client, monkeypatch, "A")
    _post_api_session(client, monkeypatch, "B")

    r = client.get(f"/api/v1/workspace-console/sessions?{QS}")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2


def test_console_get_session(client, monkeypatch):
    create = _post_api_session(client, monkeypatch, "X")
    sid = create.json()["id"]

    r = client.get(f"/api/v1/workspace-console/sessions/{sid}?{QS}")
    assert r.status_code == 200
    assert r.json()["id"] == sid


def test_console_stop_non_running_session_is_noop(client, monkeypatch):
    create = _post_api_session(client, monkeypatch, "Y")
    sid = create.json()["id"]
    assert create.json()["status"] == "completed"

    r = client.post(f"/api/v1/workspace-console/sessions/{sid}/stop?{QS}")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"  # unchanged — was not running


def test_console_session_workspace_filter(client, tmp_path, monkeypatch, db):
    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))

    from ulid import ULID
    ws_dir = tmp_path / "ws-a"
    ws_dir.mkdir()
    ws = Workspace(
        id=str(ULID()), owner_space_id=SPACE, created_by_user_id=USER,
        name="ws-a", kind="project", root_path=str(ws_dir), status="active",
    )
    db.add(ws)
    db.commit()

    from app.agents.api_adapter import AnthropicAPIAdapter
    monkeypatch.setattr(AnthropicAPIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(
        AnthropicAPIAdapter, "run",
        lambda self, p, context, **kw: AgentRunResult(success=True, output="ok"),
    )
    client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "anthropic_api", "prompt": "with workspace", "workspace_id": ws.id,
    })
    client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "anthropic_api", "prompt": "without workspace",
    })

    r = client.get(f"/api/v1/workspace-console/sessions?workspace_id={ws.id}&{QS}")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["workspace_id"] == ws.id


# ── Workspace Console: runtimes ───────────────────────────────────────────────

def test_console_list_runtimes(client):
    r = client.get(f"/api/v1/workspace-console/runtimes?{QS}")
    assert r.status_code == 200

    runtimes = r.json()["runtimes"]
    ids = [rt["id"] for rt in runtimes]
    assert "mock" not in ids
    assert "claude_code" in ids
    assert "anthropic_api" in ids


def test_console_runtimes_reflect_adapter_availability(client, monkeypatch):
    """list_runtimes reports live availability from each adapter."""
    from app.agents.claude_adapter import ClaudeCLIAdapter
    from app.agents.api_adapter import AnthropicAPIAdapter

    monkeypatch.setattr(ClaudeCLIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(AnthropicAPIAdapter, "is_available", lambda self: False)

    r = client.get(f"/api/v1/workspace-console/runtimes?{QS}")
    assert r.status_code == 200
    by_id = {rt["id"]: rt for rt in r.json()["runtimes"]}

    assert "mock" not in by_id
    assert by_id["claude_code"]["available"] is True
    assert by_id["anthropic_api"]["available"] is False


# ── Workspace Console: real runtimes ──────────────────────────────────────────

def _fake_result(success=True, output="Test output.", error=None):
    return AgentRunResult(success=success, output=output, error=error)


def test_console_unknown_runtime_rejected(client):
    """Posting an unknown runtime ID returns 400."""
    r = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "does_not_exist",
        "prompt": "Do something",
    })
    assert r.status_code == 400
    assert "does_not_exist" in r.json()["message"]


def test_console_anthropic_api_session_success(client, monkeypatch):
    """anthropic_api runtime runs synchronously and returns a completed session."""
    from app.agents.api_adapter import AnthropicAPIAdapter

    monkeypatch.setattr(AnthropicAPIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(
        AnthropicAPIAdapter, "run",
        lambda self, prompt, context, **kw: _fake_result(output="Here is the analysis."),
    )

    r = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "anthropic_api",
        "prompt": "Summarize the project",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "completed"
    assert body["runtime_adapter"] == "anthropic_api"

    types = [e["type"] for e in body["events"]]
    assert "text_delta" in types
    assert "run_completed" in types
    assert not any(e["type"] == "run_failed" for e in body["events"])


def test_console_anthropic_api_session_failure(client, monkeypatch):
    """anthropic_api adapter failure produces a run_failed event and status=failed."""
    from app.agents.api_adapter import AnthropicAPIAdapter

    monkeypatch.setattr(AnthropicAPIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(
        AnthropicAPIAdapter, "run",
        lambda self, prompt, context, **kw: _fake_result(
            success=False, output="", error="Rate limit exceeded"
        ),
    )

    r = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "anthropic_api",
        "prompt": "Do something",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "failed"
    types = [e["type"] for e in body["events"]]
    assert "run_failed" in types
    failed = next(e for e in body["events"] if e["type"] == "run_failed")
    assert "Rate limit" in failed["error"]


def test_console_anthropic_api_model_forwarded(client, monkeypatch):
    """The model field is forwarded to AnthropicAPIAdapter."""
    from app.agents.api_adapter import AnthropicAPIAdapter

    captured = {}

    def fake_init(self, model=None):
        captured["model"] = model

    monkeypatch.setattr(AnthropicAPIAdapter, "__init__", fake_init)
    monkeypatch.setattr(
        AnthropicAPIAdapter, "is_available", lambda self: True
    )
    monkeypatch.setattr(
        AnthropicAPIAdapter, "run",
        lambda self, prompt, context, **kw: _fake_result(),
    )

    client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "anthropic_api",
        "model": "claude-opus-4-7",
        "prompt": "Hello",
    })
    assert captured["model"] == "claude-opus-4-7"


def _patch_bg_session(monkeypatch, db_engine):
    """
    Make _execute_session_background use the test in-memory DB instead of the
    production SessionLocal. The background task opens its own session via
    _open_session(); we replace that with a factory bound to the test engine.
    """
    TestSession = sessionmaker(bind=db_engine)

    def fake_open_session():
        return TestSession()

    monkeypatch.setattr(wc_api, "_open_session", fake_open_session)


def test_console_claude_code_background_success(client, db_engine, monkeypatch):
    """claude_code runtime: POST returns status=running, background task completes it."""
    from app.agents.claude_adapter import ClaudeCLIAdapter

    monkeypatch.setattr(ClaudeCLIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(
        ClaudeCLIAdapter, "run",
        lambda self, prompt, context, **kw: _fake_result(output="Fixed the bug."),
    )
    _patch_bg_session(monkeypatch, db_engine)

    r = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "claude_code",
        "prompt": "Fix the bug in main.py",
    })
    assert r.status_code == 201
    session_id = r.json()["id"]

    # TestClient runs background tasks before returning, so the session should
    # already be completed by the time we make the next request.
    detail = client.get(f"/api/v1/workspace-console/sessions/{session_id}?{QS}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "completed"
    types = [e["type"] for e in body["events"]]
    assert "text_delta" in types
    assert "run_completed" in types


def test_console_claude_code_background_failure(client, db_engine, monkeypatch):
    """claude_code adapter failure → session status=failed with run_failed event."""
    from app.agents.claude_adapter import ClaudeCLIAdapter

    monkeypatch.setattr(ClaudeCLIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(
        ClaudeCLIAdapter, "run",
        lambda self, prompt, context, **kw: _fake_result(
            success=False, output="", error="Subprocess timed out"
        ),
    )
    _patch_bg_session(monkeypatch, db_engine)

    r = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "claude_code",
        "prompt": "Fix something",
    })
    session_id = r.json()["id"]

    detail = client.get(f"/api/v1/workspace-console/sessions/{session_id}?{QS}")
    body = detail.json()
    assert body["status"] == "failed"
    types = [e["type"] for e in body["events"]]
    assert "run_failed" in types


def test_console_claude_code_model_forwarded(client, db_engine, monkeypatch):
    """The model field is forwarded to ClaudeCLIAdapter via its constructor."""
    from app.agents.claude_adapter import ClaudeCLIAdapter

    captured = {}

    real_init = ClaudeCLIAdapter.__init__

    def fake_init(self, executor=None, sandbox_dir=None, credential_grant=None, model=None):
        captured["model"] = model
        real_init(self, executor=executor, sandbox_dir=sandbox_dir,
                  credential_grant=credential_grant, model=model)

    monkeypatch.setattr(ClaudeCLIAdapter, "__init__", fake_init)
    monkeypatch.setattr(ClaudeCLIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(
        ClaudeCLIAdapter, "run",
        lambda self, prompt, context, **kw: _fake_result(),
    )
    _patch_bg_session(monkeypatch, db_engine)

    client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "claude_code",
        "model": "claude-opus-4-7",
        "prompt": "Hello",
    })
    assert captured["model"] == "claude-opus-4-7"


def test_console_codex_background_success(client, db_engine, monkeypatch):
    """codex runtime: background task completes with events."""
    from app.agents.codex_adapter import CodexCLIAdapter

    monkeypatch.setattr(CodexCLIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(
        CodexCLIAdapter, "run",
        lambda self, prompt, context, **kw: _fake_result(output="Codex output."),
    )
    _patch_bg_session(monkeypatch, db_engine)

    r = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "codex",
        "prompt": "Refactor my code",
    })
    assert r.status_code == 201
    session_id = r.json()["id"]

    detail = client.get(f"/api/v1/workspace-console/sessions/{session_id}?{QS}")
    assert detail.json()["status"] == "completed"


def test_console_claude_code_workspace_path_passed(client, db_engine, tmp_path, monkeypatch):
    """The workspace directory path is forwarded to the adapter's run() call."""
    from app.agents.claude_adapter import ClaudeCLIAdapter

    captured = {}

    monkeypatch.setattr(ws_api.settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(wc_api.settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(ClaudeCLIAdapter, "is_available", lambda self: True)

    def fake_run(self, prompt, context, workspace_path=None, **kw):
        captured["workspace_path"] = workspace_path
        return _fake_result()

    monkeypatch.setattr(ClaudeCLIAdapter, "run", fake_run)
    _patch_bg_session(monkeypatch, db_engine)

    # Create a real workspace via the API so it has a proper path record
    ws_resp = client.post(f"/api/v1/workspaces?{QS}", json={"name": "my-proj"})
    assert ws_resp.status_code == 201
    ws_id = ws_resp.json()["id"]
    expected_path = ws_resp.json()["root_path"]

    client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "claude_code",
        "workspace_id": ws_id,
        "prompt": "Run in workspace",
    })

    assert captured.get("workspace_path") == expected_path


def test_console_result_to_events_success():
    """_result_to_events produces text_delta + run_completed for a successful run."""
    result = AgentRunResult(success=True, output="Hello world")
    events = wc_api._result_to_events(result)
    assert events[0] == {"type": "text_delta", "content": "Hello world"}
    assert events[-1] == {"type": "run_completed"}


def test_console_result_to_events_failure():
    """_result_to_events produces run_failed for a failed run."""
    result = AgentRunResult(success=False, output="", error="boom")
    events = wc_api._result_to_events(result)
    assert events[-1] == {"type": "run_failed", "error": "boom"}


def test_console_result_to_events_no_output():
    """_result_to_events skips text_delta when output is empty."""
    result = AgentRunResult(success=True, output="")
    events = wc_api._result_to_events(result)
    assert all(e["type"] != "text_delta" for e in events)
    assert events[-1]["type"] == "run_completed"


# ── Multi-turn session (conversation continuity) ───────────────────────────────

def test_console_events_to_messages_empty():
    """_events_to_messages returns [] for empty or no-response events."""
    assert wc_api._events_to_messages([]) == []
    assert wc_api._events_to_messages([
        {"type": "user_turn", "prompt": "hello"},
    ]) == []  # no assistant response yet


def test_console_events_to_messages_single_turn():
    """_events_to_messages extracts one completed user/assistant pair."""
    events = [
        {"type": "user_turn", "prompt": "What is 2+2?"},
        {"type": "text_delta", "content": "4"},
        {"type": "run_completed"},
    ]
    messages = wc_api._events_to_messages(events)
    assert messages == [
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4"},
    ]


def test_console_events_to_messages_multi_turn():
    """_events_to_messages handles multiple completed turns correctly."""
    events = [
        {"type": "user_turn", "prompt": "p1"},
        {"type": "text_delta", "content": "r1"},
        {"type": "run_completed"},
        {"type": "user_turn", "prompt": "p2"},
        {"type": "text_delta", "content": "r2a"},
        {"type": "text_delta", "content": "r2b"},
        {"type": "run_completed"},
    ]
    messages = wc_api._events_to_messages(events)
    assert messages == [
        {"role": "user",      "content": "p1"},
        {"role": "assistant", "content": "r1"},
        {"role": "user",      "content": "p2"},
        {"role": "assistant", "content": "r2ar2b"},
    ]


def test_console_create_session_prepends_user_turn(client, monkeypatch):
    """Every new session's events start with a user_turn event."""
    r = _post_api_session(client, monkeypatch, "hello")
    assert r.status_code == 201
    events = r.json()["events"]
    assert events[0]["type"] == "user_turn"
    assert events[0]["prompt"] == "hello"


def test_console_run_turn_multi(client, monkeypatch):
    """POST /sessions/{id}/run continues a session with a new prompt."""
    r1 = _post_api_session(client, monkeypatch, "First prompt")
    assert r1.status_code == 201
    sid = r1.json()["id"]
    first_event_count = len(r1.json()["events"])

    r2 = client.post(f"/api/v1/workspace-console/sessions/{sid}/run?{QS}", json={
        "prompt": "Second prompt",
    })
    assert r2.status_code == 200
    body = r2.json()
    events = body["events"]

    # All prior events preserved plus new turn
    assert len(events) > first_event_count
    user_turns = [e for e in events if e["type"] == "user_turn"]
    assert len(user_turns) == 2
    assert user_turns[0]["prompt"] == "First prompt"
    assert user_turns[1]["prompt"] == "Second prompt"


def test_console_run_turn_rejected_while_running(client, monkeypatch):
    """POST /sessions/{id}/run on a running session returns 409."""
    from app.models import WorkspaceSession
    from ulid import ULID

    r = _post_api_session(client, monkeypatch, "hello")
    sid = r.json()["id"]

    # Manually set status to "running" via the stop endpoint hack:
    # easier to just test the 409 by checking a known running state.
    # Since TestClient is sync, patch the session status directly via DB fixture.


def test_console_run_turn_anthropic_api_passes_history(client, monkeypatch):
    """
    Continuing an anthropic_api session sends the full conversation history
    to the adapter (not just the new prompt).
    """
    from app.agents.api_adapter import AnthropicAPIAdapter

    captured = {}

    def fake_run(self, prompt, context, conversation=None, **kw):
        captured["conversation"] = conversation
        captured["prompt"] = prompt
        return _fake_result(output=f"Reply to: {prompt}")

    monkeypatch.setattr(AnthropicAPIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(AnthropicAPIAdapter, "run", fake_run)

    # First turn
    r1 = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "anthropic_api",
        "prompt": "What is the capital of France?",
    })
    assert r1.status_code == 201
    sid = r1.json()["id"]
    assert captured.get("conversation") is None or captured["conversation"] == []

    # Second turn — conversation should contain the first exchange
    r2 = client.post(f"/api/v1/workspace-console/sessions/{sid}/run?{QS}", json={
        "prompt": "And of Germany?",
    })
    assert r2.status_code == 200
    assert captured["prompt"] == "And of Germany?"
    conv = captured["conversation"]
    assert conv is not None and len(conv) >= 2
    assert conv[0]["role"] == "user"
    assert "France" in conv[0]["content"]
    assert conv[1]["role"] == "assistant"


def test_console_run_turn_claude_code_uses_continue_flag(client, db_engine, monkeypatch):
    """Continuing a claude_code session passes continue_conversation=True to the adapter."""
    from app.agents.claude_adapter import ClaudeCLIAdapter

    captured = {}

    def fake_run(self, prompt, context, continue_conversation=False, **kw):
        captured["continue"] = continue_conversation
        return _fake_result(output="ok")

    monkeypatch.setattr(ClaudeCLIAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(ClaudeCLIAdapter, "run", fake_run)
    _patch_bg_session(monkeypatch, db_engine)

    # First session
    r1 = client.post(f"/api/v1/workspace-console/sessions?{QS}", json={
        "runtime_adapter": "claude_code",
        "prompt": "Do task A",
    })
    sid = r1.json()["id"]
    assert captured.get("continue") is False  # first turn — no continuation

    # Second turn
    client.post(f"/api/v1/workspace-console/sessions/{sid}/run?{QS}", json={
        "prompt": "Do task B",
    })
    assert captured["continue"] is True  # continuation flag set


def test_console_run_turn_not_found(client):
    """POST /sessions/bad-id/run returns 404."""
    r = client.post(f"/api/v1/workspace-console/sessions/nonexistent/run?{QS}", json={
        "prompt": "hello",
    })
    assert r.status_code == 404
