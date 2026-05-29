"""Local subprocess executor for RuntimeAdapterSpec-driven CLI adapters."""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


_LOCAL_ENV_ALLOWED_KEYS: frozenset[str] = frozenset({"PATH", "TERM", "SHELL", "LANG"})
_LOCAL_ENV_ALLOWED_PREFIXES: tuple[str, ...] = ("LC_",)
_BROKER_INJECTED_EXTRA_KEYS: frozenset[str] = frozenset({
    "HOME",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
})


def build_subprocess_env(extra: dict | None) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, val in os.environ.items():
        if key in _LOCAL_ENV_ALLOWED_KEYS or key.startswith(_LOCAL_ENV_ALLOWED_PREFIXES):
            safe[key] = val
    if extra:
        for key, val in extra.items():
            if key in _BROKER_INJECTED_EXTRA_KEYS:
                safe[key] = val
    return safe


class LocalExecutor:
    def run_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: int = 60,
        env: dict | None = None,
        run_id: str | None = None,
        stdin: str | None = None,
    ) -> ExecutionResult:
        merged_env = build_subprocess_env(env)
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if stdin is not None else None,
                text=True,
                env=merged_env,
                start_new_session=True,
                shell=False,
            )
            if run_id is not None:
                from ..runs.process_registry import register as _reg_register
                _reg_register(run_id, proc.pid)
            try:
                stdout, stderr = proc.communicate(input=stdin, timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    proc.kill()
                stdout, stderr = proc.communicate()
                return ExecutionResult(-1, stdout or "", stderr or "Command timed out.", timed_out=True)
            finally:
                if run_id is not None:
                    from ..runs.process_registry import deregister as _reg_deregister
                    _reg_deregister(run_id)
            return ExecutionResult(proc.returncode, stdout or "", stderr or "")
        except Exception as exc:  # noqa: BLE001
            if run_id is not None:
                from ..runs.process_registry import deregister as _reg_deregister
                _reg_deregister(run_id)
            return ExecutionResult(-1, "", str(exc))
