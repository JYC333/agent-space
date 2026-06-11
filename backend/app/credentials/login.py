from __future__ import annotations
"""
CLI login helpers — two modes per runtime:

  cli     — runs the CLI tool's own login command (OAuth);
             streams stdout/stderr as SSE lines;
             if the CLI asks for a code ("Paste code here"), emits a
             {"type": "needs_input"} event and waits for the caller to POST
             the code to /credentials/cli/login/input.

  api_key — user provides an API key through the web UI;
             stored as api_key.txt inside the profile dir;
             injected as an env var (e.g. ANTHROPIC_API_KEY) at run time.

Some runtimes (claude_code) support BOTH — the UI shows both options.

PTY login (claude_code):
  Running bare `claude` shows an interactive auth-method menu (TUI).
  We open a PTY so the TUI renders, then automatically press Enter to
  select the first option (Claude.ai subscription). After that the flow
  is the same: URL → browser → paste code.  The PTY master fd is stored
  in _ACTIVE_LOGIN_PTYS so send_login_input() can write the code to it.
"""

import asyncio
import json
import logging
import os
import re
import select as _select_mod
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Active login subprocesses keyed by runtime name.
_ACTIVE_LOGINS: dict[str, asyncio.subprocess.Process] = {}
# PTY master fds for PTY-based logins (claude_code uses this path).
_ACTIVE_LOGIN_PTYS: dict[str, int] = {}
# State machine for PTY logins: "navigating" | "waiting_code" | "post_code"
_LOGIN_STATE: dict[str, str] = {}

_ANSI_RE = re.compile(rb'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


# ── Per-runtime login configuration ──────────────────────────────────────────

RUNTIME_LOGIN_CONFIG: dict[str, dict] = {
    # Claude Code: `claude /login` goes straight to the auth flow.
    # use_pty=True triggers the PTY code path in stream_cli_login.
    "claude_code": {
        "method": "cli",
        "command": ["claude", "/login"],
        "use_pty": True,
        "home_subdir": ".claude",
        "env_var": "ANTHROPIC_API_KEY",
        "key_filename": "api_key.txt",
        "label": "Claude Code",
        "hint_cli": "A browser URL will appear — open it to authorize your Claude.ai account.",
        "hint_api_key": "Paste your Anthropic API key from console.anthropic.com/keys (starts with sk-ant-…).",
    },
    "codex_cli": {
        "method": "api_key",
        "env_var": "OPENAI_API_KEY",
        "key_filename": "api_key.txt",
        "label": "Codex CLI",
        "hint_api_key": "Paste your OpenAI API key (starts with sk-…).",
    },
    "opencode": {
        "method": "cli",
        "command": ["opencode", "auth", "login"],
        "home_subdir": ".opencode",
        "label": "OpenCode",
        "hint_cli": "Follow the prompts to complete login.",
    },
    "gemini_cli": {
        "method": "cli",
        "command": ["gemini", "auth"],
        "home_subdir": ".gemini",
        "label": "Gemini CLI",
        "hint_cli": "A browser URL will appear — open it to authorize Gemini CLI.",
    },
}


def list_login_methods() -> list[dict]:
    return [
        {
            "runtime": runtime,
            "method": cfg["method"],
            "label": cfg.get("label", runtime),
            "hint_cli": cfg.get("hint_cli", ""),
            "hint_api_key": cfg.get("hint_api_key", ""),
            "env_var": cfg.get("env_var"),
            "supports_api_key": bool(cfg.get("env_var")),
            "supports_cli": bool(cfg.get("command")),
        }
        for runtime, cfg in RUNTIME_LOGIN_CONFIG.items()
    ]


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ── Prompt patterns ───────────────────────────────────────────────────────────

_URL_RE = re.compile(r'https?://\S+')


# ── PTY login (claude_code) ───────────────────────────────────────────────────

async def _stream_pty_login(runtime: str, cfg: dict, profile_dir: Path):
    """
    Run the CLI in a PTY so interactive TUI menus render correctly.

    Automated flow:
      1. Auto-press Enter every 1.5 s to advance through setup menus (theme, auth method).
      2. When a URL appears in the output, stop pressing and emit needs_input for the code.
      3. User pastes the code → send_login_input() delivers it and sets state to "post_code".
      4. Send /exit every 1.5 s until the process closes (handles the REPL drop-in after login).
    """
    import pty, fcntl, termios, struct

    cmd: list[str] = cfg["command"]
    exe = shutil.which(cmd[0])
    if not exe:
        yield _sse({"type": "error", "text": f"'{cmd[0]}' not found in PATH.\n"})
        return

    env = dict(os.environ)
    env.setdefault("TERM", "xterm-256color")
    # Don't let an API key override the subscription auth flow
    env.pop("ANTHROPIC_API_KEY", None)

    # Kill any stale PTY login for this runtime
    old_fd = _ACTIVE_LOGIN_PTYS.pop(runtime, None)
    if old_fd is not None:
        try:
            os.close(old_fd)
        except OSError:
            pass

    master_fd, slave_fd = pty.openpty()
    # 500 cols — Claude auth URLs are 300+ chars; must not wrap or the frontend regex misses them
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 500, 0, 0))

    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True,
        env=env,
    )
    os.close(slave_fd)
    _ACTIVE_LOGIN_PTYS[runtime] = master_fd
    _LOGIN_STATE[runtime] = "navigating"

    loop = asyncio.get_event_loop()
    raw = b""
    last_output_time = 0.0   # when we last received any output
    last_action_time = 0.0   # when we last sent a keystroke
    OUTPUT_SETTLE = 1.0      # wait this long after output stops before pressing Enter
    ACTION_COOLDOWN = 3.0    # min gap between consecutive Enter presses
    deadline = time.time() + 300  # 5-minute total timeout

    def _try_read() -> bytes | None:
        r, _, _ = _select_mod.select([master_fd], [], [], 0.2)
        if r:
            try:
                return os.read(master_fd, 4096)
            except OSError:
                return b""
        return None

    try:
        while time.time() < deadline:
            chunk = await loop.run_in_executor(None, _try_read)
            now = time.time()

            # No data this poll — check if output has settled and it's time to act
            if chunk is None:
                if proc.poll() is not None:
                    break

                state = _LOGIN_STATE.get(runtime, "navigating")

                if (state == "navigating"
                        and last_output_time > 0
                        and (now - last_output_time) > OUTPUT_SETTLE
                        and (now - last_action_time) > ACTION_COOLDOWN):
                    clean = _ANSI_RE.sub(b"", raw).decode("utf-8", errors="replace")
                    if _URL_RE.search(clean):
                        _LOGIN_STATE[runtime] = "waiting_code"
                        yield _sse({
                            "type": "needs_input",
                            "step": "code",
                            "prompt": "Open the URL above in your browser, then paste the authorization code here.",
                        })
                    else:
                        try:
                            os.write(master_fd, b"\r")
                            last_action_time = now
                        except OSError:
                            pass

                elif (state == "post_code"
                        and (now - last_action_time) > ACTION_COOLDOWN):
                    try:
                        os.write(master_fd, b"/exit\r")
                        last_action_time = now
                    except OSError:
                        pass

                await asyncio.sleep(0)
                continue

            if chunk == b"":
                break  # PTY closed

            raw += chunk
            last_output_time = now
            clean_chunk = _ANSI_RE.sub(b"", chunk).decode("utf-8", errors="replace")
            yield _sse({"type": "output", "text": clean_chunk})

    except Exception as exc:
        yield _sse({"type": "error", "text": f"PTY login error: {exc}\n"})
        log.exception("PTY login error runtime=%s", runtime)
    finally:
        _ACTIVE_LOGIN_PTYS.pop(runtime, None)
        _LOGIN_STATE.pop(runtime, None)
        try:
            os.close(master_fd)
        except OSError:
            pass

    # Collect exit code
    rc = proc.poll()
    if rc is None:
        try:
            proc.terminate()
            rc = await loop.run_in_executor(None, lambda: proc.wait(timeout=5))
        except Exception:
            rc = -1

    for event in _sync_credentials(rc, cfg, profile_dir, runtime):
        yield event
    yield _sse({"type": "done", "exit_code": rc})


# ── Pipe-based login (other runtimes) ─────────────────────────────────────────

async def stream_cli_login(runtime: str, profile_dir: Path):
    """
    Async generator yielding SSE strings.

    Routes to PTY login for runtimes with use_pty=True (e.g. claude_code),
    otherwise uses a pipe-based subprocess.
    """
    cfg = RUNTIME_LOGIN_CONFIG.get(runtime)
    if not cfg:
        yield _sse({"type": "error", "text": f"Unknown runtime: {runtime}\n"})
        return
    if not cfg.get("command"):
        yield _sse({"type": "error", "text": f"'{runtime}' does not support CLI login.\n"})
        return

    cmd: list[str] = cfg["command"]
    if not shutil.which(cmd[0]):
        yield _sse({
            "type": "error",
            "text": f"'{cmd[0]}' not found in PATH. Is {cfg['label']} installed?\n",
        })
        return

    yield _sse({"type": "output", "text": f"$ {' '.join(cmd)}\n"})
    hint = cfg.get("hint_cli", "")
    if hint:
        yield _sse({"type": "hint", "text": hint + "\n"})

    # PTY path for TUI-based CLIs
    if cfg.get("use_pty"):
        async for event in _stream_pty_login(runtime, cfg, profile_dir):
            yield event
        return

    # Pipe path for simple CLIs
    if runtime in _ACTIVE_LOGINS:
        try:
            _ACTIVE_LOGINS[runtime].kill()
        except Exception:
            pass

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        _ACTIVE_LOGINS[runtime] = proc
        assert proc.stdout is not None

        buf = ""
        while True:
            chunk = await proc.stdout.read(256)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            buf += text
            yield _sse({"type": "output", "text": text})
            if any(p in buf.lower() for p in _CODE_PROMPTS):
                yield _sse({"type": "needs_input", "prompt": buf.strip()})
                buf = ""

        rc = await proc.wait()
    except Exception as exc:
        yield _sse({"type": "error", "text": f"Failed to start login process: {exc}\n"})
        return
    finally:
        _ACTIVE_LOGINS.pop(runtime, None)

    for event in _sync_credentials(rc, cfg, profile_dir, runtime):
        yield event
    yield _sse({"type": "done", "exit_code": rc})


# ── Credential sync (shared) ──────────────────────────────────────────────────

def _sync_credentials(rc: int, cfg: dict, profile_dir: Path, runtime: str):
    """Yield SSE events while copying credentials to the managed profile dir."""
    if rc != 0:
        return

    home_subdir: str = cfg.get("home_subdir", "")
    if not home_subdir:
        return

    src = Path.home() / home_subdir
    if not src.exists():
        yield _sse({
            "type": "warning",
            "text": f"Login succeeded but {src} not found — credentials not synced.\n",
        })
        return

    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, profile_dir, dirs_exist_ok=True)
        # .claude.json lives at HOME root (not inside HOME/.claude/); copy it
        # so _create_temp_home can symlink it back at the right level.
        claude_json = Path.home() / ".claude.json"
        if claude_json.exists():
            shutil.copy2(claude_json, profile_dir / ".claude.json")
        yield _sse({
            "type": "synced",
            "text": "Credentials copied to managed profile.\n",
            "profile_id": f"{runtime}/default",
        })
    except Exception as exc:
        yield _sse({"type": "warning", "text": f"Login succeeded but copy failed: {exc}\n"})
        log.error("credential copy failed runtime=%s src=%s dst=%s: %s", runtime, src, profile_dir, exc)


# ── Send input to active login process ───────────────────────────────────────

async def send_login_input(runtime: str, text: str) -> bool:
    """
    Write user-provided text (e.g. an OAuth code) to an active login process.
    Tries the PTY path first, then the pipe path.
    Returns True if the input was delivered.
    """
    # PTY path (claude_code)
    master_fd = _ACTIVE_LOGIN_PTYS.get(runtime)
    if master_fd is not None:
        try:
            os.write(master_fd, (text.strip() + "\r").encode())
            # Transition to post_code so the loop starts sending /exit
            _LOGIN_STATE[runtime] = "post_code"
            return True
        except OSError as exc:
            log.warning("PTY write failed for runtime=%s: %s", runtime, exc)
            return False

    # Pipe path (other runtimes)
    proc = _ACTIVE_LOGINS.get(runtime)
    if not proc or proc.stdin is None:
        return False
    try:
        proc.stdin.write((text.strip() + "\n").encode())
        await proc.stdin.drain()
        return True
    except Exception as exc:
        log.warning("stdin write failed for runtime=%s: %s", runtime, exc)
        return False


# ── API key save ──────────────────────────────────────────────────────────────

def save_api_key(runtime: str, api_key: str, profile_dir: Path) -> None:
    """Write a user-provided API key into the managed credential profile dir."""
    cfg = RUNTIME_LOGIN_CONFIG.get(runtime)
    if not cfg or not cfg.get("env_var"):
        raise ValueError(f"Runtime '{runtime}' does not support API key authentication.")
    filename: str = cfg.get("key_filename", "api_key.txt")
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / filename).write_text(api_key.strip() + "\n", encoding="utf-8")
    log.info("API key saved: runtime=%s dir=%s", runtime, profile_dir)
