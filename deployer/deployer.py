#!/usr/bin/env python3
"""
agent-space host deployer — Unix domain socket server.

Runs on the HOST (outside the main app container) and handles deployment
requests from the backend. The backend cannot restart itself; this process can.

Start:
    python deployer/deployer.py

Or via systemd — see deployer/README.md.

Socket path: $DEPLOYER_SOCKET or /var/run/agent-space/deployer.sock
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from datetime import datetime, UTC
from pathlib import Path

from protocol import ALLOWED_JOB_TYPES

log = logging.getLogger("deployer")

SCRIPT_DIR = Path(__file__).parent / "scripts"

JOB_SCRIPTS: dict[str, Path] = {
    "rebuild_agent_space": SCRIPT_DIR / "rebuild.sh",
    "restart_agent_space": SCRIPT_DIR / "restart.sh",
    "health_check":        SCRIPT_DIR / "health_check.sh",
}


async def _run_script(script: Path, timeout: int = 300) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        str(script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(), stderr.decode()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername", "unknown")
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=10)
        request: dict = json.loads(raw)

        job_id   = request.get("job_id", "unknown")
        job_type = request.get("job_type", "")
        proposal = request.get("proposal_id", "")
        user     = request.get("requested_by_user_id", "unknown")

        log.info("job %s type=%s proposal=%s user=%s", job_id, job_type, proposal, user)

        if job_type not in ALLOWED_JOB_TYPES:
            result = {"job_id": job_id, "status": "failed",
                      "error": f"Unknown job_type '{job_type}'. Allowed: {sorted(ALLOWED_JOB_TYPES)}"}
            _write(writer, result)
            return

        script = JOB_SCRIPTS[job_type]
        if not script.exists():
            result = {"job_id": job_id, "status": "failed",
                      "error": f"Script not found: {script}"}
            _write(writer, result)
            return

        started_at = datetime.now(UTC).isoformat()
        try:
            exit_code, stdout, stderr = await _run_script(script)
        except asyncio.TimeoutError:
            result = {"job_id": job_id, "status": "failed", "error": "Script timed out",
                      "started_at": started_at, "completed_at": datetime.now(UTC).isoformat()}
            _write(writer, result)
            return

        status = "succeeded" if exit_code == 0 else "failed"
        log.info("job %s finished status=%s exit_code=%d", job_id, status, exit_code)

        result = {
            "job_id":       job_id,
            "status":       status,
            "exit_code":    exit_code,
            "stdout":       stdout,
            "stderr":       stderr,
            "started_at":   started_at,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        _write(writer, result)

    except json.JSONDecodeError as exc:
        _write(writer, {"status": "failed", "error": f"Invalid JSON: {exc}"})
    except Exception as exc:
        log.exception("unhandled error for job from %s", peer)
        try:
            _write(writer, {"status": "failed", "error": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await writer.drain()
            writer.close()
        except Exception:
            pass


def _write(writer: asyncio.StreamWriter, obj: dict) -> None:
    writer.write(json.dumps(obj).encode() + b"\n")


async def main() -> None:
    socket_path = os.environ.get(
        "DEPLOYER_SOCKET",
        "/var/run/agent-space/deployer.sock",
    )
    sock_file = Path(socket_path)
    sock_file.parent.mkdir(parents=True, exist_ok=True)

    if sock_file.exists():
        sock_file.unlink()

    server = await asyncio.start_unix_server(handle_client, path=socket_path)
    # Owner read/write only — the backend user must be in the same group or run as the same user
    os.chmod(socket_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)

    log.info("deployer listening on %s", socket_path)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
