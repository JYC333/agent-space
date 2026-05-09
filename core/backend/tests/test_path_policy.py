"""
Tests for PathPolicy — path traversal prevention and write restrictions.
"""
import pytest
from pathlib import Path

from app.workspace.path_policy import PathPolicy, PathPolicyError


@pytest.fixture
def policy(tmp_path):
    workspace_root = tmp_path / "workspaces"
    sandbox_root = tmp_path / "sandboxes"
    workspace_root.mkdir()
    sandbox_root.mkdir()
    return PathPolicy(workspace_root=workspace_root, sandbox_root=sandbox_root)


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspaces" / "my-project"
    ws.mkdir(parents=True)
    return ws


@pytest.fixture
def sandbox_dir(tmp_path):
    sd = tmp_path / "sandboxes" / "run-123"
    sd.mkdir(parents=True)
    return sd


# ---------------------------------------------------------------------------
# validate — within allowed root
# ---------------------------------------------------------------------------

def test_validate_allows_path_under_root(policy, tmp_path):
    root = tmp_path / "workspaces"
    target = root / "somefile.txt"
    target.touch()
    result = policy.validate(str(target), allowed_root=str(root))
    assert result == target.resolve()


def test_validate_allows_nested_path(policy, tmp_path):
    root = tmp_path / "workspaces"
    nested = root / "a" / "b" / "c.txt"
    nested.parent.mkdir(parents=True)
    nested.touch()
    result = policy.validate(str(nested), allowed_root=str(root))
    assert result == nested.resolve()


# ---------------------------------------------------------------------------
# validate — path traversal
# ---------------------------------------------------------------------------

def test_validate_blocks_dotdot_traversal(policy, tmp_path):
    root = tmp_path / "workspaces"
    traversal = str(root / ".." / "etc" / "passwd")
    with pytest.raises(PathPolicyError, match="traversal"):
        policy.validate(traversal, allowed_root=str(root))


def test_validate_blocks_absolute_escape(policy, tmp_path):
    root = tmp_path / "workspaces"
    with pytest.raises(PathPolicyError):
        policy.validate("/etc/passwd", allowed_root=str(root))


# ---------------------------------------------------------------------------
# validate — forbidden fragments
# ---------------------------------------------------------------------------

def test_validate_blocks_ssh_path(policy, tmp_path):
    root = tmp_path / "workspaces"
    (root / ".ssh").mkdir()
    with pytest.raises(PathPolicyError, match=".ssh"):
        policy.validate(str(root / ".ssh" / "id_rsa"), allowed_root=str(root))


def test_validate_blocks_env_file(policy, tmp_path):
    root = tmp_path / "workspaces"
    env_file = root / ".env"
    env_file.touch()
    with pytest.raises(PathPolicyError, match=".env"):
        policy.validate(str(env_file), allowed_root=str(root))


def test_validate_blocks_credentials_path(policy, tmp_path):
    root = tmp_path / "workspaces"
    cred_dir = root / "credentials"
    cred_dir.mkdir()
    with pytest.raises(PathPolicyError, match="credentials"):
        policy.validate(str(cred_dir / "token.json"), allowed_root=str(root))


# ---------------------------------------------------------------------------
# validate — write restrictions
# ---------------------------------------------------------------------------

def test_validate_write_blocks_python_files(policy, tmp_path):
    root = tmp_path / "workspaces"
    py_file = root / "script.py"
    py_file.touch()
    with pytest.raises(PathPolicyError, match=".py"):
        policy.validate(str(py_file), allowed_root=str(root), mode="write")


def test_validate_write_blocks_shell_scripts(policy, tmp_path):
    root = tmp_path / "workspaces"
    sh_file = root / "run.sh"
    sh_file.touch()
    with pytest.raises(PathPolicyError, match=".sh"):
        policy.validate(str(sh_file), allowed_root=str(root), mode="write")


def test_validate_read_allows_python_files(policy, tmp_path):
    root = tmp_path / "workspaces"
    py_file = root / "script.py"
    py_file.touch()
    # Read is fine — only writes are blocked
    result = policy.validate(str(py_file), allowed_root=str(root), mode="read")
    assert result.suffix == ".py"


def test_validate_write_allows_text_files(policy, tmp_path):
    root = tmp_path / "workspaces"
    txt = root / "notes.txt"
    txt.touch()
    result = policy.validate(str(txt), allowed_root=str(root), mode="write")
    assert result.suffix == ".txt"


# ---------------------------------------------------------------------------
# validate_workspace
# ---------------------------------------------------------------------------

def test_validate_workspace_allows_registered_workspace(policy, tmp_path):
    ws = tmp_path / "workspaces" / "project-x"
    ws.mkdir()
    (ws / "README.md").touch()
    result = policy.validate_workspace(str(ws / "README.md"), workspace_id="project-x")
    assert result.name == "README.md"


def test_validate_workspace_rejects_unregistered(policy):
    with pytest.raises(PathPolicyError, match="not registered"):
        policy.validate_workspace("/some/path", workspace_id="does-not-exist")


# ---------------------------------------------------------------------------
# validate_sandbox
# ---------------------------------------------------------------------------

def test_validate_sandbox_allows_registered_sandbox(policy, tmp_path):
    sb = tmp_path / "sandboxes" / "run-999"
    sb.mkdir()
    (sb / "output.txt").touch()
    result = policy.validate_sandbox(str(sb / "output.txt"), sandbox_id="run-999")
    assert result.name == "output.txt"


def test_validate_sandbox_rejects_unregistered(policy):
    with pytest.raises(PathPolicyError, match="not registered"):
        policy.validate_sandbox("/some/path", sandbox_id="ghost-run")


# ---------------------------------------------------------------------------
# is_safe — non-raising wrapper
# ---------------------------------------------------------------------------

def test_is_safe_returns_true_for_valid_path(policy, tmp_path):
    root = tmp_path / "workspaces"
    f = root / "ok.txt"
    f.touch()
    assert policy.is_safe(str(f), allowed_root=str(root)) is True


def test_is_safe_returns_false_for_traversal(policy, tmp_path):
    root = tmp_path / "workspaces"
    assert policy.is_safe("/etc/passwd", allowed_root=str(root)) is False


def test_is_safe_returns_false_for_write_to_py(policy, tmp_path):
    root = tmp_path / "workspaces"
    f = root / "app.py"
    f.touch()
    assert policy.is_safe(str(f), allowed_root=str(root), mode="write") is False
