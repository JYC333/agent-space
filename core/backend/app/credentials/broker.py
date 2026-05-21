from __future__ import annotations
"""
CredentialBroker — manages CLI login state for agent run sandboxes.

Design:
  User logs in once → agent-space stores or references that CLI login state
  → each run receives only the credential profile it is allowed to use
  → credential usage is recorded in cli_credential_events

Profile discovery (in priority order):
  1. Instance config: $AGENT_SPACE_HOME/config/cli-credentials.yaml
  2. Directory scan: $AGENT_SPACE_HOME/secrets/cli-credentials/<runtime>/<profile>/

Canonical runtime names (adapter_type strings):
  claude_code, codex_cli, gemini_cli, opencode
  Credential directories on disk must use these exact names.
  No aliases or legacy names (e.g. claude-code, codex) are accepted.

Worktree runs (medium-risk):
  Creates a per-run temp HOME directory with a symlink to the credential dir.
  The CLI subprocess inherits HOME pointing to the temp dir, so it finds its
  config at the expected path (e.g. HOME/.claude) without touching the full
  backend container HOME.

Docker runs (high-risk):
  Returns host-resolved source path + container target path for volume mount.
  Mounted read-only by default. If the CLI needs write access (token refresh),
  the caller must copy the credential dir before mounting.

If no profile is configured, returns None (adapter uses container default).
The CLI continues working as long as it was already logged in inside the
backend container — this is the Option A MVP path.
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

import yaml

from ..config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CredentialProfile:
    """A named CLI login-state directory registered with the broker."""
    id: str                  # e.g. "claude_code/default"
    runtime: str             # e.g. "claude_code"
    name: str                # e.g. "default"
    source_path: str         # abs path to the credential dir (e.g. /app/aspace/secrets/cli-credentials/claude_code/default)
    target_path: str         # where CLI expects it (e.g. /home/agent/.claude)
    readonly: bool = False   # Docker default; worktree ignores this (always writable via symlink)
    notes: str = ""


@dataclass
class CredentialGrant:
    """
    A resolved grant of a credential profile to one sandbox run.

    For worktree runs:
      temp_home — per-run directory with a symlink to source_path at ./<basename(target_path)>
      env       — {"HOME": temp_home, ...} to inject into the subprocess
      source_path, target_path, host_source_path — None (not needed for local)

    For Docker runs:
      host_source_path — host-resolved source path for docker volume mount
      target_path      — container path where the volume is mounted
      readonly         — whether the volume is mounted read-only
      temp_home        — None (Docker uses direct volume mount)
      env              — API key env vars (e.g. ANTHROPIC_API_KEY) if api_key.txt found
    """
    profile_id: str
    runtime: str
    executor_mode: str          # worktree | docker
    readonly: bool

    # Worktree-specific
    temp_home: str | None = None
    env: dict = field(default_factory=dict)

    # Docker-specific
    host_source_path: str | None = None
    target_path: str | None = None


# ---------------------------------------------------------------------------
# CredentialBroker
# ---------------------------------------------------------------------------

class CredentialBroker:
    """
    Manages CLI credential profiles and grants for agent run sandboxes.

    Usage:
        broker = CredentialBroker()
        grant = broker.grant_for_run(
            run_id="01J...",
            runtime="claude_code",
            risk_level="medium",
            executor_mode="worktree",
        )
        if grant:
            # inject into LocalExecutor / DockerExecutor
            broker.record_usage(db, run_id, space_id, grant)
    """

    def __init__(self, instance_root: str | None = None):
        self._instance_root = Path(instance_root or settings.instance_root).resolve()
        self._creds_root = self._instance_root / "secrets" / "cli-credentials"
        self._cache_root = self._instance_root / "cache" / "runtime-homes"
        self._config_path = self._instance_root / "config" / "cli-credentials.yaml"
        self._profiles: dict[str, CredentialProfile] | None = None

    # ------------------------------------------------------------------
    # Profile discovery
    # ------------------------------------------------------------------

    def _load_profiles(self) -> dict[str, CredentialProfile]:
        """Load profiles from config file + directory scan. Cached per process."""
        if self._profiles is not None:
            return self._profiles

        profiles: dict[str, CredentialProfile] = {}

        # 1. Config file takes precedence
        if self._config_path.exists():
            try:
                with open(self._config_path) as f:
                    cfg = yaml.safe_load(f) or {}
                for runtime, named_profiles in (cfg.get("profiles") or {}).items():
                    for name, spec in (named_profiles or {}).items():
                        pid = f"{runtime}/{name}"
                        profiles[pid] = CredentialProfile(
                            id=pid,
                            runtime=runtime,
                            name=name,
                            source_path=spec.get("source_path", ""),
                            target_path=spec.get("target_path", ""),
                            readonly=spec.get("readonly", False),
                            notes=spec.get("notes", ""),
                        )
            except Exception as exc:
                log.warning("cli-credentials.yaml parse error: %s", exc)

        # 2. Auto-discover directories not already in config
        if self._creds_root.exists():
            for runtime_dir in self._creds_root.iterdir():
                if not runtime_dir.is_dir():
                    continue
                runtime = runtime_dir.name
                for profile_dir in runtime_dir.iterdir():
                    if not profile_dir.is_dir():
                        continue
                    name = profile_dir.name
                    pid = f"{runtime}/{name}"
                    if pid not in profiles:
                        target = _default_target_path(runtime)
                        profiles[pid] = CredentialProfile(
                            id=pid,
                            runtime=runtime,
                            name=name,
                            source_path=str(profile_dir),
                            target_path=target,
                            readonly=False,
                        )

        self._profiles = profiles
        return profiles

    def _reload(self) -> None:
        self._profiles = None

    def list_profiles(self, runtime: str | None = None) -> list[CredentialProfile]:
        profiles = self._load_profiles()
        result = list(profiles.values())
        if runtime:
            result = [p for p in result if p.runtime == runtime]
        return result

    def get_profile(self, profile_id: str) -> CredentialProfile | None:
        return self._load_profiles().get(profile_id)

    def get_default_profile(self, runtime: str) -> CredentialProfile | None:
        """Return the 'default' profile for *runtime*, or the first available.

        Only the exact canonical adapter_type string is checked.
        Credential directories must use canonical names (e.g. claude_code, codex_cli).
        """
        profiles = self._load_profiles()

        pid = f"{runtime}/default"
        if pid in profiles and Path(profiles[pid].source_path).exists():
            return profiles[pid]

        for p in profiles.values():
            if p.runtime == runtime and Path(p.source_path).exists():
                return p

        return None

    # ------------------------------------------------------------------
    # Grant
    # ------------------------------------------------------------------

    def grant_for_run(
        self,
        run_id: str,
        runtime: str,
        risk_level: str,
        executor_mode: str,    # worktree | docker
        profile_id: str | None = None,
    ) -> CredentialGrant | None:
        """
        Return a CredentialGrant for the given run, or None if no profile exists.

        None means: use whatever credential state is already available in the
        execution environment (Option A — backend container already logged in).
        """
        profile = (
            self.get_profile(profile_id) if profile_id
            else self.get_default_profile(runtime)
        )

        if not profile:
            log.debug("no credential profile for runtime=%s — using container default", runtime)
            return None

        if not Path(profile.source_path).exists():
            log.warning(
                "credential profile %s source_path does not exist: %s",
                profile.id, profile.source_path,
            )
            return None

        # Check for an API key file inside the profile dir — takes priority over
        # OAuth session for runtimes that support env-var auth (e.g. ANTHROPIC_API_KEY).
        api_key_env = self._api_key_env(profile)

        if executor_mode == "docker":
            from ..workspace.sandbox_manager import _resolve_host_path
            host_path = _resolve_host_path(profile.source_path)
            return CredentialGrant(
                profile_id=profile.id,
                runtime=runtime,
                executor_mode="docker",
                readonly=profile.readonly,
                host_source_path=host_path,
                target_path=profile.target_path,
                env=api_key_env,
            )

        # worktree: create temp HOME with symlink + optional API key env var
        temp_home = self._create_temp_home(run_id, profile)
        env = {"HOME": temp_home, **api_key_env}
        return CredentialGrant(
            profile_id=profile.id,
            runtime=runtime,
            executor_mode="worktree",
            readonly=False,
            temp_home=temp_home,
            env=env,
        )

    def _api_key_env(self, profile: CredentialProfile) -> dict:
        """
        If the profile dir contains api_key.txt, return {ENV_VAR: key} so the
        adapter can authenticate without an OAuth session. Returns {} otherwise.
        """
        key_file = Path(profile.source_path) / "api_key.txt"
        if not key_file.exists():
            return {}
        env_var = _API_KEY_ENV_VARS.get(profile.runtime)
        if not env_var:
            return {}
        key = key_file.read_text(encoding="utf-8").strip()
        if not key:
            return {}
        return {env_var: key}

    def _create_temp_home(self, run_id: str, profile: CredentialProfile) -> str:
        """
        Create /instance/cache/runtime-homes/<run_id>/ and symlink the credential
        dir at the expected relative path inside it (e.g. .claude for claude_code).
        """
        temp_home = self._cache_root / run_id
        temp_home.mkdir(parents=True, exist_ok=True)

        # target_path e.g. "/home/agent/.claude" → basename ".claude"
        link_name = Path(profile.target_path).name if profile.target_path else f".{profile.runtime}"
        link_path = temp_home / link_name

        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        os.symlink(profile.source_path, link_path)
        log.debug("temp HOME %s → %s symlinked at %s", temp_home, profile.source_path, link_path)

        # Claude Code also reads HOME/.claude.json (not inside HOME/.claude/).
        # If it was saved into the profile dir during login, symlink it back.
        claude_json_src = Path(profile.source_path) / ".claude.json"
        if claude_json_src.exists():
            claude_json_link = temp_home / ".claude.json"
            if claude_json_link.is_symlink() or claude_json_link.exists():
                claude_json_link.unlink()
            os.symlink(str(claude_json_src), str(claude_json_link))

        return str(temp_home)

    def cleanup_temp_home(self, run_id: str) -> None:
        """Remove per-run temp HOME directory after the run completes."""
        temp_home = self._cache_root / run_id
        if temp_home.exists():
            shutil.rmtree(temp_home, ignore_errors=True)

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def record_usage(
        self,
        db,
        run_id: str,
        space_id: str,
        grant: "CredentialGrant | None",
        *,
        runtime_adapter_type: str | None = None,
        runtime_adapter_id: str | None = None,
        trigger_origin: str | None = None,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        broker_error: bool = False,
        cleanup_status: str = "not_needed",
        action: str = "grant",
    ) -> None:
        """Insert a CliCredentialEvent audit row.

        Records metadata only — never stores raw secrets, tokens, HOME paths,
        or credential file contents.  This is a best-effort write; failures are
        logged but never re-raised.
        """
        try:
            from ..models import CliCredentialEvent
            import uuid as _uuid_mod

            if grant is not None:
                credential_source = "profile"
                credential_profile_id = grant.profile_id
            elif broker_error:
                credential_source = "none"
                credential_profile_id = None
            else:
                credential_source = "container_default"
                credential_profile_id = None

            event = CliCredentialEvent(
                id=str(_uuid_mod.uuid4()),
                space_id=space_id,
                run_id=run_id or None,
                runtime_adapter_id=runtime_adapter_id,
                runtime_adapter_type=runtime_adapter_type,
                credential_profile_id=credential_profile_id,
                credential_source=credential_source,
                trigger_origin=trigger_origin,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                broker_error=broker_error,
                cleanup_status=cleanup_status,
                action=action,
            )
            db.add(event)
            db.flush()
            log.debug(
                "credential audit: action=%s run=%s adapter=%s source=%s fallback=%s",
                action, run_id, runtime_adapter_type, credential_source, fallback_used,
            )
        except Exception:
            log.warning(
                "CliCredentialEvent write failed (best-effort) run=%s", run_id, exc_info=True
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Canonical adapter_type → CLI config directory path inside the container HOME.
# Credential directories on disk must use these exact names.
_DEFAULT_TARGET_PATHS: dict[str, str] = {
    "claude_code": "/home/agent/.claude",
    "codex_cli":   "/home/agent/.codex",
    "opencode":    "/home/agent/.opencode",
    "gemini_cli":  "/home/agent/.gemini",
}

# Env var injected when api_key.txt is found in the profile dir.
_API_KEY_ENV_VARS: dict[str, str] = {
    "claude_code": "ANTHROPIC_API_KEY",
    "codex_cli":   "OPENAI_API_KEY",
    "gemini_cli":  "GEMINI_API_KEY",
}


def _default_target_path(runtime: str) -> str:
    return _DEFAULT_TARGET_PATHS.get(runtime, f"/home/agent/.{runtime}")
