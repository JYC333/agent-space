"""Unit tests for LocalExecutor environment-variable allowlist hardening.

Invariants verified:
  1.  Unrelated SECRET_*, TOKEN_*, API_KEY_* env vars from the host are NOT
      inherited by CLI subprocesses.
  2.  Allowed host vars (PATH, LANG, LC_*, TERM, SHELL) ARE forwarded.
  3.  Credential env vars (HOME, ANTHROPIC_API_KEY) supplied via the `env`
      kwarg (CredentialBroker grant.env) ARE injected.
  4.  Credential env vars NOT in `env` are NOT inherited from os.environ.
  5.  Process-group SIGKILL is sent on timeout (whole group, not just parent).
  6.  LANG_TOKEN / LANG_SECRET are NOT forwarded (LANG is exact match only).
  7.  Disallowed extras in the `env` kwarg are silently dropped.
  8.  Only broker-documented keys (HOME, *_API_KEY) are accepted in extras.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from unittest.mock import MagicMock, call, patch

import pytest

from app.runtimes.local_executor import LocalExecutor, build_subprocess_env as _build_subprocess_env


# ---------------------------------------------------------------------------
# _build_subprocess_env unit tests (pure function, no subprocess)
# ---------------------------------------------------------------------------


def test_build_env_excludes_secret_vars(monkeypatch):
    """SECRET_*, TOKEN_*, API_KEY_* from os.environ must not appear in output."""
    monkeypatch.setenv("SECRET_DB_PASSWORD", "hunter2")
    monkeypatch.setenv("MY_TOKEN", "tok123")
    monkeypatch.setenv("SOME_API_KEY", "key456")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    result = _build_subprocess_env(None)

    assert "SECRET_DB_PASSWORD" not in result
    assert "MY_TOKEN" not in result
    assert "SOME_API_KEY" not in result


def test_build_env_allows_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    result = _build_subprocess_env(None)
    assert result.get("PATH") == "/usr/local/bin:/usr/bin"


def test_build_env_allows_lang_and_lc(monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    monkeypatch.setenv("LC_CTYPE", "UTF-8")
    result = _build_subprocess_env(None)
    assert result.get("LANG") == "en_US.UTF-8"
    assert result.get("LC_ALL") == "en_US.UTF-8"
    assert result.get("LC_CTYPE") == "UTF-8"


def test_build_env_allows_term_and_shell(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("SHELL", "/bin/bash")
    result = _build_subprocess_env(None)
    assert result.get("TERM") == "xterm-256color"
    assert result.get("SHELL") == "/bin/bash"


def test_build_env_extra_injected_over_allowlist(monkeypatch):
    """Extras from CredentialBroker grant.env (HOME, ANTHROPIC_API_KEY) are injected."""
    monkeypatch.setenv("PATH", "/usr/bin")
    extra = {"HOME": "/tmp/run-home", "ANTHROPIC_API_KEY": "sk-test"}
    result = _build_subprocess_env(extra)
    assert result["HOME"] == "/tmp/run-home"
    assert result["ANTHROPIC_API_KEY"] == "sk-test"
    assert result["PATH"] == "/usr/bin"  # still present


def test_build_env_api_key_not_inherited_without_extra(monkeypatch):
    """ANTHROPIC_API_KEY from host env must NOT appear when not in extra."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "host-secret-key")
    result = _build_subprocess_env(None)
    assert "ANTHROPIC_API_KEY" not in result


def test_build_env_home_not_inherited_without_extra(monkeypatch):
    """HOME from host env must NOT appear when not in extra."""
    monkeypatch.setenv("HOME", "/root")
    result = _build_subprocess_env(None)
    assert "HOME" not in result


def test_build_env_openai_key_not_inherited(monkeypatch):
    """OPENAI_API_KEY from host env must NOT appear when not in extra."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-host")
    result = _build_subprocess_env(None)
    assert "OPENAI_API_KEY" not in result


# ---------------------------------------------------------------------------
# Integration: LocalExecutor.run_command actual subprocess env
# ---------------------------------------------------------------------------


def test_executor_subprocess_cannot_see_host_secret(tmp_path, monkeypatch):
    """Subprocess spawned by LocalExecutor cannot read SECRET_* from host env."""
    monkeypatch.setenv("SECRET_SHOULD_NOT_LEAK", "supersecret")
    exe = LocalExecutor()
    # Ask the subprocess to print the env var; if it's absent it prints nothing.
    result = exe.run_command(
        ["python3", "-c",
         "import os; print(os.environ.get('SECRET_SHOULD_NOT_LEAK', 'NOT_SET'))"],
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    assert "supersecret" not in result.stdout
    assert "NOT_SET" in result.stdout


def test_executor_subprocess_cannot_see_host_api_key(tmp_path, monkeypatch):
    """ANTHROPIC_API_KEY from host env must not reach subprocess without explicit grant."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "host-api-key-should-not-leak")
    exe = LocalExecutor()
    result = exe.run_command(
        ["python3", "-c",
         "import os; print(os.environ.get('ANTHROPIC_API_KEY', 'NOT_SET'))"],
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    assert "host-api-key-should-not-leak" not in result.stdout
    assert "NOT_SET" in result.stdout


def test_executor_subprocess_receives_explicit_api_key(tmp_path):
    """ANTHROPIC_API_KEY injected via env kwarg IS available to subprocess."""
    exe = LocalExecutor()
    result = exe.run_command(
        ["python3", "-c",
         "import os; print(os.environ.get('ANTHROPIC_API_KEY', 'NOT_SET'))"],
        cwd=str(tmp_path),
        timeout=10,
        env={"ANTHROPIC_API_KEY": "grant-provided-key"},
    )
    assert result.returncode == 0
    assert "grant-provided-key" in result.stdout


def test_executor_subprocess_sees_path_from_host(tmp_path, monkeypatch):
    """PATH (allowlisted) is forwarded to the subprocess."""
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/bin")
    exe = LocalExecutor()
    result = exe.run_command(
        ["python3", "-c", "import os; print(os.environ.get('PATH', ''))"],
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    assert "/usr/bin" in result.stdout


# ---------------------------------------------------------------------------
# Timeout: SIGKILL sent to process group
# ---------------------------------------------------------------------------


def test_timeout_kills_process_group(tmp_path):
    """On timeout, LocalExecutor kills the entire process group (not just parent)."""
    exe = LocalExecutor()
    # Script that sleeps for a long time — will be killed by timeout.
    result = exe.run_command(
        ["python3", "-c", "import time; time.sleep(60)"],
        cwd=str(tmp_path),
        timeout=1,
    )
    assert result.timed_out is True
    assert result.returncode == -1


def test_timeout_uses_killpg_on_process_group(tmp_path, monkeypatch):
    """Verify os.killpg is called with SIGKILL on timeout."""
    import signal as _signal

    killed_pgids: list[int] = []

    def mock_killpg(pgid: int, sig: int) -> None:
        if sig == _signal.SIGKILL:
            killed_pgids.append(pgid)

    # First communicate() raises TimeoutExpired; second (after kill) returns ("", "").
    communicate_calls = [subprocess.TimeoutExpired("cmd", 1), ("", "")]

    def _communicate_side_effect(*args, **kwargs):
        val = communicate_calls.pop(0)
        if isinstance(val, Exception):
            raise val
        return val

    with patch.object(subprocess.Popen, "communicate", side_effect=_communicate_side_effect):
        with patch("os.killpg", side_effect=mock_killpg):
            with patch("os.getpgid", return_value=99999):
                exe = LocalExecutor()
                result = exe.run_command(
                    ["python3", "-c", "import time; time.sleep(10)"],
                    cwd=str(tmp_path),
                    timeout=1,
                )

    # killpg should have been called with the mocked pgid and SIGKILL
    assert 99999 in killed_pgids, "Expected os.killpg(pgid, SIGKILL) to be called on timeout"
    assert result.timed_out is True


# ---------------------------------------------------------------------------
# Task 5: LANG is exact match only — LANG_* must not leak
# ---------------------------------------------------------------------------


def test_build_env_lang_exact_match_only(monkeypatch):
    """LANG is allowed as an exact key; LANG_TOKEN and LANG_SECRET are not."""
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LANG_TOKEN", "secret_lang_token")
    monkeypatch.setenv("LANG_SECRET", "supersecret")
    monkeypatch.setenv("LANGUAGE", "en_US:en")   # also should not leak

    result = _build_subprocess_env(None)

    assert result.get("LANG") == "en_US.UTF-8"       # exact LANG key allowed
    assert "LANG_TOKEN" not in result                 # LANG_* not allowed
    assert "LANG_SECRET" not in result
    assert "LANGUAGE" not in result                   # LANGUAGE not in allowlist


def test_build_env_lc_prefix_still_works(monkeypatch):
    """LC_ALL and LC_CTYPE are still forwarded via the LC_ prefix."""
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    monkeypatch.setenv("LC_CTYPE", "UTF-8")
    monkeypatch.setenv("LC_MESSAGES", "en_US")

    result = _build_subprocess_env(None)

    assert result.get("LC_ALL") == "en_US.UTF-8"
    assert result.get("LC_CTYPE") == "UTF-8"
    assert result.get("LC_MESSAGES") == "en_US"


def test_build_env_disallowed_extra_keys_are_dropped():
    """Keys not in _BROKER_INJECTED_EXTRA_KEYS are silently dropped from extra."""
    extra = {
        "HOME": "/run/home",             # allowed
        "ANTHROPIC_API_KEY": "sk-test",  # allowed
        "SOME_SECRET": "leaked_value",   # NOT allowed
        "CUSTOM_VAR": "should_drop",     # NOT allowed
    }
    result = _build_subprocess_env(extra)

    assert result["HOME"] == "/run/home"
    assert result["ANTHROPIC_API_KEY"] == "sk-test"
    assert "SOME_SECRET" not in result
    assert "CUSTOM_VAR" not in result


def test_build_env_gemini_api_key_allowed_in_extra():
    """GEMINI_API_KEY (documented broker key) is allowed in extras."""
    extra = {"GEMINI_API_KEY": "gemini-key"}
    result = _build_subprocess_env(extra)
    assert result["GEMINI_API_KEY"] == "gemini-key"


def test_executor_subprocess_cannot_see_lang_token(tmp_path, monkeypatch):
    """LANG_TOKEN from host env must not reach subprocess."""
    monkeypatch.setenv("LANG_TOKEN", "lang-token-secret")
    exe = LocalExecutor()
    result = exe.run_command(
        ["python3", "-c",
         "import os; print(os.environ.get('LANG_TOKEN', 'NOT_SET'))"],
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    assert "lang-token-secret" not in result.stdout
    assert "NOT_SET" in result.stdout
