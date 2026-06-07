import os
import stat
from pathlib import Path
from typing import Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

# Convenience default for dev/test only. Production must set DATABASE_URL
# explicitly — the after-validator below rejects this default when
# AGENT_SPACE_ENV=prod so prod never silently runs on a development database.
_DEV_DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://agent_space:agent_space_dev_password@localhost:5432/agent_space"
)


def normalize_database_url(v: str) -> str:
    stripped = v.strip()
    if not stripped:
        raise ValueError(
            "DATABASE_URL must be a PostgreSQL connection string. "
            "Use postgresql+psycopg:// as the canonical form. "
            "Example: postgresql+psycopg://agent_space:<password>@localhost:5432/agent_space"
        )
    if stripped.startswith("postgresql+psycopg://"):
        return stripped
    if stripped.startswith("postgresql://"):
        return "postgresql+psycopg://" + stripped.removeprefix("postgresql://")
    raise ValueError(
        "DATABASE_URL must be a PostgreSQL connection string. "
        "Use postgresql+psycopg:// as the canonical form. "
        "Example: postgresql+psycopg://agent_space:<password>@localhost:5432/agent_space"
    )

# Agent Space instance data root for the currently running environment.
# AGENT_SPACE_HOME is the single instance root — NOT the parent that contains
# dev/, test/, prod/ mode dirs (that host-side parent is ASPACE_ROOT, used only
# by scripts/). In the Docker backend container it is the bind mount /aspace;
# for a direct local backend run it is a concrete mode root such as
# $HOME/.aspace/dev. Defaults to ~/.aspace when unset.
_ASPACE_HOME = Path(
    os.getenv("AGENT_SPACE_HOME", str(Path.home() / ".aspace"))
).expanduser().resolve()


class AppPaths:
    """Central path resolver — all runtime data lives under AGENT_SPACE_HOME."""

    def __init__(self, home: Path | None = None):
        self.home           = (home or _ASPACE_HOME).resolve()
        self.config_dir     = self.home / "config"
        self.secrets_dir    = self.home / "secrets"
        self.db_dir         = self.home / "db"
        self.storage_dir    = self.home / "storage"
        self.logs_dir       = self.home / "logs"
        self.cache_dir      = self.home / "cache"
        self.runtime_dir    = self.home / "runtime"
        self.workspaces_dir = self.home / "workspaces"
        self.sandboxes_dir  = self.home / "sandboxes"
        self.artifacts_dir  = self.home / "artifacts"
        self.backups_dir    = self.home / "backups"
        # Captured file/voice uploads (Activity Inbox attachments). Lives under storage/
        # alongside artifacts; never inside the source repo.
        self.uploads_dir    = self.storage_dir / "uploads"

    @property
    def artifact_storage_root(self) -> Path:
        """Root for persisted artifact files (``Artifact.storage_path`` is relative to this)."""
        p = os.getenv("ARTIFACT_STORAGE_ROOT")
        if p:
            return Path(p).expanduser().resolve()
        return (self.storage_dir / "artifacts").resolve()

    @property
    def db_dumps_dir(self) -> Path:
        """Directory for pg_dump backups and database dumps (not the live DB data)."""
        return self.db_dir / "dumps"

    @property
    def cli_credentials_dir(self) -> Path:
        return self.secrets_dir / "cli-credentials"

    @property
    def cli_credentials_config(self) -> Path:
        return self.config_dir / "cli-credentials.yaml"

    @property
    def instance_settings_config(self) -> Path:
        return self.config_dir / "settings.yaml"

    @property
    def provider_keys_key(self) -> Path:
        """AES-256-GCM master key for encrypting provider API keys at rest."""
        return self.secrets_dir / "provider_keys.key"

    def system_core_workspace_dir_for_space(self, space_id: str) -> Path:
        """Git worktree root for agent-space self-evolution in a specific space."""
        return self.workspaces_dir / space_id / "agent-space"

    def init_dirs(self) -> None:
        """Create all required directories with correct permissions (idempotent)."""
        import os

        def _skip_path(p: Path) -> bool:
            """Skip if path is a mount point or not writable by current user."""
            try:
                if os.path.ismount(p):
                    return True
                stat_info = p.stat()
                # Skip if we don't own it (and we're not root)
                if stat_info.st_uid != 0 and stat_info.st_uid != os.getuid():
                    # Check if we can actually write
                    if not os.access(p, os.W_OK):
                        return True
            except (OSError, PermissionError):
                pass
            return False

        def safe_mkdir(p: Path, mode: int) -> None:
            """Create directory and apply its mode, skipping mounts/unowned paths.

            ``mkdir`` is subject to the process umask, so the restrictive mode is
            applied explicitly afterwards. We only chmod directories we own and
            that are not bind-mount points — host bind mounts are the operator's
            responsibility and must not be chmod'ed implicitly.
            """
            try:
                if _skip_path(p):
                    return
                p.mkdir(parents=True, exist_ok=True)
                try:
                    if not os.path.ismount(p) and p.stat().st_uid == os.getuid():
                        os.chmod(p, mode)
                except (OSError, PermissionError):
                    pass
            except (OSError, PermissionError):
                pass

        entries = [
            (self.home,           0o700),
            (self.config_dir,     0o700),
            (self.secrets_dir,    0o700),
            (self.db_dir,         0o700),
            (self.runtime_dir,    0o700),
            (self.storage_dir,    0o700),
            (self.logs_dir,       0o700),
            (self.cache_dir,      0o700),
            (self.workspaces_dir, 0o700),
            (self.sandboxes_dir,  0o700),
            (self.artifacts_dir,  0o700),
            (self.artifact_storage_root, 0o700),
            (self.uploads_dir,    0o700),
            (self.backups_dir,    0o700),
        ]
        for path, mode in entries:
            safe_mkdir(path, mode)

    # Sensitive directories that must never be world-accessible and must be
    # writable by the running process — checked in both host (direct local run)
    # and container (/aspace bind mount) modes.
    SENSITIVE_DIR_ATTRS = ("home", "config_dir", "secrets_dir", "db_dir", "runtime_dir")

    def validate(self) -> None:
        """Fail fast on insecure or unusable sensitive directories.

        Runs identically for host runs and inside the Docker backend container
        (where ``AGENT_SPACE_HOME=/aspace`` is a bind mount). For ``home``,
        ``config``, ``secrets``, ``db`` and ``runtime`` this enforces:

        - the directory is not world-accessible (no ``other`` rwx bits), and
        - the current process can write to it.

        This never chmods anything: host bind-mount permissions are the
        operator's responsibility (``scripts/start.sh`` creates mode-700 trees).
        We refuse to start rather than silently relax checks for non-root
        users, so an insecure or unwritable data root is caught immediately.
        """
        import os

        sensitive = [getattr(self, attr) for attr in self.SENSITIVE_DIR_ATTRS]
        for path in sensitive:
            if not path.exists():
                continue
            try:
                mode = path.stat().st_mode
            except (OSError, PermissionError) as exc:
                raise RuntimeError(
                    f"Cannot stat sensitive directory {path}: {exc}"
                ) from exc
            if mode & stat.S_IRWXO:
                raise RuntimeError(
                    f"Security: {path} is world-accessible (mode "
                    f"{oct(stat.S_IMODE(mode))}). Fix with: chmod 700 {path}"
                )
            if not os.access(path, os.W_OK):
                raise RuntimeError(
                    f"Cannot write to required directory {path}. "
                    f"Check ownership and permissions of the data root."
                )


paths = AppPaths()


class Settings(BaseSettings):
    app_name: str = "agent-space"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database — PostgreSQL is the server database.
    # Set DATABASE_URL to a postgresql+psycopg:// connection string.
    # postgresql:// inputs are accepted and normalized to postgresql+psycopg://.
    # Example: postgresql+psycopg://agent_space:password@localhost:5432/agent_space
    # The default is a dev/test convenience; prod must set DATABASE_URL explicitly.
    database_url: str = _DEV_DEFAULT_DATABASE_URL

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @model_validator(mode="after")
    def require_explicit_prod_database_url(self):
        """Prod must configure DATABASE_URL explicitly, never the dev/test default.

        dev and test may rely on the convenience default. In prod the development
        default database is rejected so the instance never silently connects to a
        development PostgreSQL database.
        """
        if (self.agent_space_env or "").strip().lower() == "prod":
            if self.database_url == _DEV_DEFAULT_DATABASE_URL:
                raise ValueError(
                    "AGENT_SPACE_ENV=prod requires an explicit DATABASE_URL. "
                    "Set DATABASE_URL to the production PostgreSQL connection string, "
                    "e.g. postgresql+psycopg://agent_space:<password>@<host>:5432/agent_space"
                )
        return self

    # Bootstrap owner for single-user mode. There is no default *space* id: the
    # default space is this owner's personal space (a generated UUID created by
    # bootstrap_instance and resolved via app.spaces.defaults), never a magic
    # "personal" string.
    default_user_id: str = "default_user"

    # LLM configuration. Provider API keys are NOT stored here: users enter them in the
    # app (Providers page) and they are persisted as encrypted ModelProvider Credentials
    # (secret_ref), resolved at runtime via resolve_provider_api_key. Never put an LLM API
    # key in settings or env — ADR 0010 (credential channel isolation). default_model is a
    # non-secret default model name only.
    default_model: str = ""

    # AGENT_SPACE_HOME — single local data root (all runtime data lives here)
    agent_space_home: str = str(_ASPACE_HOME)

    # PostgreSQL connection components — informational/operator tooling only.
    # DATABASE_URL is always the authoritative connection string; these fields
    # are not used to construct it automatically. Docker Compose sets DATABASE_URL
    # explicitly. Scripts such as scripts/db/migrate.sh may read these as fallback
    # when DATABASE_URL is not in the environment.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "agent_space"
    postgres_user: str = "agent_space"
    postgres_password: str = "agent_space_dev_password"

    # Runtime paths — all overridable via env vars; derive from AGENT_SPACE_HOME by default.
    # instance_root mirrors agent_space_home for kernel helpers that still read this field.
    instance_root: str = str(_ASPACE_HOME)
    instance_storage_root: str = str(paths.storage_dir)
    artifact_storage_root: str = Field(
        default=str(paths.artifact_storage_root),
        description="Directory where artifact files are stored; ARTIFACT_STORAGE_ROOT env overrides.",
    )
    workspace_root: str = str(Path(os.getenv("WORKSPACE_ROOT", str(paths.workspaces_dir))))
    sandbox_root: str = str(Path(os.getenv("SANDBOX_ROOT", str(paths.sandboxes_dir))))
    capabilities_dir: str = str(Path(__file__).parent.parent.parent / "capabilities")
    memory_dir: str = str(Path(__file__).parent.parent.parent / "memory")

    # Memory reflector
    reflector_mode: str = "pattern"  # "pattern" (deterministic) | "llm"
    # LLM reflector model provider — must reference a configured ModelProvider row.
    # Set REFLECTOR_MODEL_PROVIDER_ID to the provider's UUID/ULID.
    # Set REFLECTOR_MODEL to override the provider's default_model (optional).
    # The provider's API key comes from its encrypted ModelProvider Credential, never
    # from an ambient env var. The reflector may use any provider incl Anthropic (ADR 0010).
    reflector_model_provider_id: Optional[str] = None
    reflector_model: Optional[str] = None

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    # Redirect URI registered in Google Console — must go through Vite proxy in dev
    google_redirect_uri: str = "http://localhost:5173/api/v1/auth/google/callback"
    # Frontend base URL — used for post-OAuth redirects
    frontend_url: str = "http://localhost:5173"

    # Session config
    session_expire_days: int = 30
    # Allowed CORS origins (restrict in production)
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Sandbox concurrency — max Docker containers running simultaneously
    # Runs beyond this limit queue and wait rather than all firing at once
    max_concurrent_docker_runs: int = 3
    # Default sandbox level: dry_run | worktree | one_shot_docker
    default_sandbox_level: str = "worktree"

    # Deployer Unix socket path (host deployer process, outside the app container)
    deployer_socket_path: str = "/aspace/run/deployer.sock"

    # CLI credential management
    # Root directory for CLI login state profiles (one subdir per runtime/profile)
    cli_credentials_dir: str = str(paths.cli_credentials_dir)
    # Path to the credential profile config file
    cli_credentials_config: str = str(paths.cli_credentials_config)

    # Claude Code local data — override in Docker via CLAUDE_HOME env var
    claude_home: str = str(Path.home() / ".claude")

    # HOME directory to use when running `claude` in a PTY (quota fetch, etc.).
    # Set this to the directory that contains .claude/ and .claude.json so the
    # subprocess finds credentials without going through the credential broker.
    # Example: CLAUDE_PTY_HOME=/home/yuchuan   (host user home, bind-mounted)
    claude_pty_home: str = ""

    # Context builder limits
    context_max_memories: int = 20
    context_max_episodes: int = 5

    # System evolution — registers the agent-space worktree as a system_core workspace
    # in the owner user's personal space on backend startup.
    enable_system_evolution: bool = False
    system_core_owner_email: str = ""
    system_core_base_branch: str = "master"

    # Agent Space environment (dev, test, prod)
    agent_space_env: str = "dev"

    # ── Daily Capture Report scheduler ───────────────────────────────────────
    # Set daily_report_scheduler_enabled=false to disable the background scheduler
    # (e.g., in environments where a separate cron process drives report generation).
    # Minimum interval is 30 seconds; values below 30 are rejected at startup.
    daily_report_scheduler_enabled: bool = True
    daily_report_scheduler_interval_seconds: int = 60

    @field_validator("daily_report_scheduler_interval_seconds")
    @classmethod
    def validate_daily_report_scheduler_interval(cls, v: int) -> int:
        if v < 30:
            raise ValueError(
                f"daily_report_scheduler_interval_seconds must be at least 30, got {v}"
            )
        return v

    # ── Automation scheduler ─────────────────────────────────────────────────
    # Fires schedule-trigger automations whose next_run_at is due. Disable to run
    # without in-app scheduling. Minimum scan interval is 30 seconds.
    automation_scheduler_enabled: bool = True
    automation_scheduler_interval_seconds: int = 60

    @field_validator("automation_scheduler_interval_seconds")
    @classmethod
    def validate_automation_scheduler_interval(cls, v: int) -> int:
        if v < 30:
            raise ValueError(
                f"automation_scheduler_interval_seconds must be at least 30, got {v}"
            )
        return v

    # ── Backup ────────────────────────────────────────────────────────────────
    # BackupService is the canonical full-system backup (automatic, scheduled,
    # and via API). scripts/system/backup.sh and scripts/system/restore.sh are
    # the offline full-system equivalents (same archive format) for when the
    # backend is not running. scripts/db/ holds DB-only expert tools.
    #
    # Two-person dogfooding MUST set BACKUP_ENABLED=true.
    # Default is False (safe for tests and unattended CI).
    backup_enabled: bool = False
    backup_interval_hours: int = 24
    backup_retention_count: int = 7
    backup_include_logs: bool = False
    backup_on_startup: bool = True
    backup_root: str = str(_ASPACE_HOME / "backups")
    # Safety guard for prod-like environments: when AGENT_SPACE_ENV=prod and
    # BACKUP_ENABLED is false, startup fails fast unless this is explicitly set
    # true to acknowledge running without automatic backups. Non-prod envs only
    # emit a warning. See app.backups.guard.enforce_backup_policy.
    backup_accept_no_backup: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
