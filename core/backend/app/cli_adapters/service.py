from __future__ import annotations
"""
CLIAdapterService — CRUD and detection for per-space CLI tool configurations.

Manages RuntimeAdapter records and delegates adapter detection to the
registered adapter classes. Detection is non-destructive (read-only probes).
"""

import json
import logging
import os
import re
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from ulid import ULID
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

from ..models import RuntimeAdapter
from ..schemas import CLIAdapterConfigCreate, CLIAdapterConfigUpdate, CLIStatusOut
from ..config import settings


def _new_id() -> str:
    return str(ULID())


# Known built-in adapter IDs and their human-readable names.
_BUILTIN_ADAPTERS: dict[str, str] = {
    "claude_code": "Claude Code",
    "codex_cli": "Codex CLI",
    "opencode": "OpenCode",
    "gemini_cli": "Gemini CLI",
    "echo": "Echo (test)",
}


class CLIAdapterService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list(self, space_id: str) -> list[RuntimeAdapter]:
        return (
            self.db.query(RuntimeAdapter)
            .filter(RuntimeAdapter.space_id == space_id)
            .order_by(RuntimeAdapter.created_at)
            .all()
        )

    def get(self, config_id: str, space_id: str) -> RuntimeAdapter | None:
        return (
            self.db.query(RuntimeAdapter)
            .filter(RuntimeAdapter.id == config_id, RuntimeAdapter.space_id == space_id)
            .first()
        )

    def create(self, data: CLIAdapterConfigCreate, space_id: str) -> RuntimeAdapter:
        config = RuntimeAdapter(
            id=_new_id(),
            space_id=space_id,
            adapter_id=data.adapter_id,
            display_name=data.display_name,
            enabled=data.enabled,
            health_status=data.quota_status,
        )
        config.executable_path = data.executable_path
        config.default_mode = data.default_mode
        config.notes = data.notes
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update(self, config_id: str, space_id: str, data: CLIAdapterConfigUpdate) -> RuntimeAdapter | None:
        config = self.get(config_id, space_id)
        if not config:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(config, field, value)
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete(self, config_id: str, space_id: str) -> bool:
        config = self.get(config_id, space_id)
        if not config:
            return False
        self.db.delete(config)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect_one(self, adapter_id: str) -> CLIStatusOut:
        """Run detection for a single adapter_id using the registered adapter class."""
        adapter = _get_adapter_instance(adapter_id)
        if adapter is None:
            return CLIStatusOut(
                adapter_id=adapter_id,
                available=False,
                status_message=f"No registered adapter for '{adapter_id}'",
            )
        status = adapter.detect()
        caps = adapter.get_capabilities()
        return CLIStatusOut(
            adapter_id=adapter_id,
            available=status.available,
            version=status.version,
            executable_path=status.executable_path,
            login_detected=status.login_detected,
            status_message=status.status_message,
            capabilities={
                "supportsHeadlessRun": caps.supports_headless_run,
                "supportsInteractiveRun": caps.supports_interactive_run,
                "supportsStreamingLogs": caps.supports_streaming_logs,
                "supportsModelOverride": caps.supports_model_override,
                "supportsUsageOutput": caps.supports_usage_output,
                "supportsPatchOutput": caps.supports_patch_output,
                "contextFileType": caps.context_file_type,
                "usageAccuracy": caps.usage_accuracy,
            },
        )

    def detect_all(self) -> list[CLIStatusOut]:
        """Detect all known built-in adapters."""
        return [self.detect_one(adapter_id) for adapter_id in _BUILTIN_ADAPTERS]

    def list_builtin_adapters(self) -> list[dict]:
        return [
            {"id": adapter_id, "display_name": name}
            for adapter_id, name in _BUILTIN_ADAPTERS.items()
        ]


_ANSI_RE = re.compile(rb'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _get_claude_profile_dir() -> Path | None:
    """Return the claude_code credential profile dir from the broker, or None."""
    try:
        from ..credentials.broker import CredentialBroker
        profile = CredentialBroker().get_default_profile("claude_code")
        if profile and Path(profile.source_path).exists():
            return Path(profile.source_path)
    except Exception:
        pass
    return None


def _quota_cache_path() -> Path:
    from ..config import settings
    return Path(settings.instance_root) / "cache" / "quota-cache.json"


def read_quota_cache() -> dict | None:
    """Return the last persisted quota result, or None if no cache exists."""
    path = _quota_cache_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def refresh_quota_cache() -> dict:
    """Fetch live quota, stamp it, and persist to instance/cache/quota-cache.json."""
    result = fetch_quota_via_pty()
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    try:
        path = _quota_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result), encoding="utf-8")
    except Exception as exc:
        log.warning("quota cache write failed: %s", exc)
    return result


def fetch_quota_via_pty() -> dict:
    """
    Run `claude` in a PTY (pty.fork), wait for the interactive prompt, inject
    `/usage`, and use pyte to render the screen.

    Credentials are copied to a throw-away temp dir so claude's cache writes
    never touch the real credential store (which would corrupt account state).

    Returns {"session_pct", "session_resets", "week_pct", "week_resets"} or
    {"error": ...} if claude isn't available or the output can't be parsed.
    """
    import pty, signal, tempfile, fcntl, termios, struct, select
    import pyte

    exe = shutil.which('claude')
    if not exe:
        return {"error": "claude not found in PATH"}

    COLS, ROWS = 220, 50
    env = dict(os.environ)
    env.setdefault('TERM', 'xterm-256color')
    # ANTHROPIC_API_KEY switches Claude Code to API-billing mode, hiding quota bars.
    env.pop('ANTHROPIC_API_KEY', None)

    # Use a copy of the credentials so claude never writes back to the live store.
    tmp_home: str | None = None
    if settings.claude_pty_home:
        env["HOME"] = settings.claude_pty_home
        log.info("quota pty: HOME override=%s", settings.claude_pty_home)
    else:
        try:
            from ..credentials.broker import CredentialBroker
            profile = CredentialBroker().get_default_profile("claude_code")
            if profile and Path(profile.source_path).exists():
                tmp_home = tempfile.mkdtemp(prefix="agent-quota-home-")
                shutil.copytree(profile.source_path, tmp_home, dirs_exist_ok=True)
                env["HOME"] = tmp_home
                log.info("quota pty: HOME=tmp copy of %s", profile.source_path)
        except Exception:
            pass

    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)

    def snapshot() -> str:
        return '\n'.join(screen.display)

    raw_all = b''
    child_pid: int | None = None
    master_fd: int | None = None

    try:
        child_pid, master_fd = pty.fork()

        if child_pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, 0, 0))
            except Exception:
                pass
            os.execvpe(exe, [exe], env)
            os._exit(1)

        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, 0, 0))

        # Step 1 — wait for the interactive prompt (❯).
        prompt_detected = False
        t0 = time.time()
        while time.time() - t0 < 15:
            r, _, _ = select.select([master_fd], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                raw_all += chunk
                stream.feed(chunk)
                if '❯' in snapshot() or 'Try "' in snapshot():
                    prompt_detected = True
                    break

        log.info("quota pty: prompt_detected=%s after %.1fs", prompt_detected, time.time() - t0)
        log.debug("quota pty startup:\n%s", snapshot())

        # Let TUI fully settle before injecting input.
        time.sleep(1.0 if prompt_detected else 2.0)
        os.write(master_fd, b'/usage\r')

        # Step 2 — snapshot until quota data appears or 90 s timeout.
        best_screen = ''
        deadline = time.time() + 90
        while time.time() < deadline:
            r, _, _ = select.select([master_fd], [], [], 0.3)
            if r:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                raw_all += chunk
                stream.feed(chunk)

            text = snapshot()
            text_lower = text.lower()

            if text_lower.count('resets') > best_screen.lower().count('resets'):
                best_screen = text
            if text_lower.count('%') > best_screen.lower().count('%'):
                best_screen = text

            if 'current week' in text_lower and text_lower.count('resets') >= 2:
                best_screen = text
                log.info("quota pty: found full quota data")
                break
            if 'loading' not in text_lower and '%' in text and 'used' in text_lower:
                best_screen = text
                time.sleep(1.0)
                best_screen = snapshot()
                log.info("quota pty: found partial quota data")
                break

        log.info("quota pty: done raw=%d best_pct_lines=%d",
                 len(raw_all), best_screen.lower().count('%'))
        log.debug("quota pty best screen:\n%s", best_screen)

        try:
            os.write(master_fd, b'/exit\r')
        except OSError:
            pass

        try:
            debug_path = _quota_cache_path().parent / "quota-pty-debug.txt"
            debug_path.write_text(best_screen, encoding="utf-8")
        except Exception:
            pass

    finally:
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                os.waitpid(child_pid, 0)
            except OSError:
                pass
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if tmp_home:
            shutil.rmtree(tmp_home, ignore_errors=True)

    return _parse_quota(best_screen)


def _parse_quota(raw: str) -> dict:
    clean = re.sub(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', raw)
    lines = [l.strip() for l in clean.splitlines()]

    # Detect API billing mode — quota bars are only available on claude.ai
    # Pro/Max subscriptions, not Anthropic API org accounts.
    if any('api usage billing' in l.lower() for l in lines):
        return {"error": "Claude Code is authenticated to an Anthropic API org account (API Usage Billing). Re-authenticate via claude.ai subscription to see quota bars."}

    result: dict = {
        "session_pct": None, "session_resets": None,
        "week_pct": None,    "week_resets": None,
    }
    section = None
    for line in lines:
        lower = line.lower()
        if 'current session' in lower:
            section = 'session'
        elif 'current week' in lower:
            section = 'week'
        elif 'used' in lower and '%' in line and section:
            m = re.search(r'(\d+)%\s*used', line)
            if m:
                result[f"{section}_pct"] = int(m.group(1))
        elif lower.startswith('resets') and section and not result.get(f"{section}_resets"):
            result[f"{section}_resets"] = line
    return result


def read_claude_stats() -> dict:
    """Read stats-cache.json and return structured usage data.

    Checks (in order):
      1. The managed credential profile dir (set up via frontend login)
      2. settings.claude_home (fallback / bare-metal path)
    """
    from ..config import settings
    profile_dir = _get_claude_profile_dir()
    candidates = [
        profile_dir / "stats-cache.json" if profile_dir else None,
        Path(settings.claude_home) / "stats-cache.json",
    ]
    stats_path = next((p for p in candidates if p and p.exists()), None)
    if stats_path is None:
        result = {
            "available": True,
            "stats_available": False,
            "total_sessions": 0, "total_messages": 0,
            "week_messages": 0, "week_sessions": 0, "week_tool_calls": 0,
            "daily": [], "models": [],
        }
        cached = read_quota_cache()
        if cached:
            result["quota"] = cached
        return result

    try:
        data = json.loads(stats_path.read_text())
    except Exception as exc:
        result = {"available": False, "error": str(exc)}
        cached = read_quota_cache()
        if cached:
            result["quota"] = cached
        return result

    # Last 14 days of activity, padded so gaps show as zero
    today = date.today()
    day_map: dict[str, dict] = {
        d["date"]: d for d in data.get("dailyActivity", [])
    }
    daily: list[dict] = []
    for i in range(13, -1, -1):
        day_str = (today - timedelta(days=i)).isoformat()
        entry = day_map.get(day_str, {})
        daily.append({
            "date": day_str,
            "messages": entry.get("messageCount", 0),
            "sessions": entry.get("sessionCount", 0),
            "tool_calls": entry.get("toolCallCount", 0),
        })

    # Week totals (last 7 days)
    week = daily[-7:]
    week_messages   = sum(d["messages"]   for d in week)
    week_sessions   = sum(d["sessions"]   for d in week)
    week_tool_calls = sum(d["tool_calls"] for d in week)

    # Model token usage
    models = []
    for model_id, u in data.get("modelUsage", {}).items():
        inp   = u.get("inputTokens", 0)
        out   = u.get("outputTokens", 0)
        cr    = u.get("cacheReadInputTokens", 0)
        cw    = u.get("cacheCreationInputTokens", 0)
        models.append({
            "model": model_id,
            "input_tokens":       inp,
            "output_tokens":      out,
            "cache_read_tokens":  cr,
            "cache_write_tokens": cw,
            "total_tokens":       inp + out + cr + cw,
            "cost_usd":           u.get("costUSD", 0),
        })
    models.sort(key=lambda m: m["total_tokens"], reverse=True)

    result = {
        "available": True,
        "last_computed": data.get("lastComputedDate"),
        "first_session_date": data.get("firstSessionDate"),
        "total_sessions": data.get("totalSessions", 0),
        "total_messages": data.get("totalMessages", 0),
        "week_messages":   week_messages,
        "week_sessions":   week_sessions,
        "week_tool_calls": week_tool_calls,
        "daily": daily,
        "models": models,
    }
    # Attach cached quota so the frontend gets it in one request
    cached = read_quota_cache()
    if cached:
        result["quota"] = cached
    return result


def _get_adapter_instance(adapter_id: str):
    """Return an instantiated adapter for the given adapter_id, or None."""
    from ..agents.cli_adapter import EchoAgentAdapter
    from ..agents.claude_adapter import ClaudeCLIAdapter
    from ..agents.codex_adapter import CodexCLIAdapter

    registry = {
        "echo": EchoAgentAdapter,
        "claude_code": ClaudeCLIAdapter,
        "claude_cli": ClaudeCLIAdapter,
        "codex_cli": CodexCLIAdapter,
    }
    cls = registry.get(adapter_id)
    return cls() if cls else None
