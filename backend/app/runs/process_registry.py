"""In-process subprocess handle registry for run cancellation.

Maps run_id → PID for CLI subprocesses in progress. Thread-safe for single-process
deployments. Cross-process termination is not yet implemented.

Usage:
    register(run_id, pid)    — subprocess start; reached via the
                               ``RuntimeProcessRegistry`` port
                               (``runtime_bridge.RunProcessRegistryAdapter``
                               injected into ``LocalExecutor``)
    deregister(run_id)       — subprocess exit; same injected port
    terminate(run_id)        — called by stop_run to signal the subprocess
    get_pid(run_id)          — used in tests and diagnostics

``runtimes`` never imports this module — registration flows through the
runs-owned bridge only (``runs -> runtimes`` dependency direction).
"""
from __future__ import annotations

import logging
import os
import signal
import threading

log = logging.getLogger(__name__)

_lock = threading.Lock()
_registry: dict[str, int] = {}


def register(run_id: str, pid: int) -> None:
    with _lock:
        _registry[run_id] = pid
    log.debug("process_registry: registered run=%s pid=%d", run_id, pid)


def deregister(run_id: str) -> None:
    with _lock:
        _registry.pop(run_id, None)
    log.debug("process_registry: deregistered run=%s", run_id)


def get_pid(run_id: str) -> int | None:
    with _lock:
        return _registry.get(run_id)


def terminate(run_id: str) -> bool:
    """Send SIGTERM to the process group of the registered subprocess for run_id.

    LocalExecutor starts subprocesses with start_new_session=True, making each
    subprocess the leader of its own process group.  Sending SIGTERM to the
    process group (-pgid) ensures child processes spawned by the CLI tool are
    also terminated, not just the top-level PID.

    Falls back to killing the PID directly if the process group cannot be
    determined (e.g. the process already exited before pgid lookup).

    Returns True if a signal was sent. Returns False if no process is registered
    (already exited or never started) or if termination failed.
    Cross-process termination is not supported — only works when the subprocess
    lives in the same OS process as the caller.
    """
    pid = get_pid(run_id)
    if pid is None:
        log.debug("process_registry.terminate: no process registered for run=%s", run_id)
        return False
    # Try to send SIGTERM to the entire process group first.
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        log.info(
            "process_registry: sent SIGTERM to process group pgid=%d (pid=%d) run=%s",
            pgid, pid, run_id,
        )
        return True
    except ProcessLookupError:
        log.debug("process_registry: pid=%d for run=%s already gone (pgid lookup)", pid, run_id)
        deregister(run_id)
        return False
    except (OSError, PermissionError):
        # pgid lookup or killpg failed — fall back to direct PID signal
        log.debug(
            "process_registry: killpg failed for pid=%d run=%s; falling back to kill(pid)",
            pid, run_id,
        )

    try:
        os.kill(pid, signal.SIGTERM)
        log.info("process_registry: sent SIGTERM to pid=%d run=%s (fallback)", pid, run_id)
        return True
    except ProcessLookupError:
        log.debug("process_registry: pid=%d for run=%s already gone", pid, run_id)
        deregister(run_id)
        return False
    except PermissionError:
        log.warning(
            "process_registry: permission denied terminating pid=%d run=%s",
            pid, run_id,
        )
        return False


def list_active() -> dict[str, int]:
    """Return a snapshot of the current registry. For diagnostics/tests only."""
    with _lock:
        return dict(_registry)
