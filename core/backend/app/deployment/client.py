from __future__ import annotations
"""
DeployerClient — sends deployment job requests to the host deployer via Unix socket.

The deployer runs outside the main app container. Communication is over a Unix
domain socket mounted into the backend container at `config.deployer_socket_path`.

If the socket is not present (deployer not running), submit_job() returns a failed
result with a clear message — it never raises.
"""

import json
import logging
import socket
from pathlib import Path

log = logging.getLogger(__name__)


class DeployerClient:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    @property
    def available(self) -> bool:
        return Path(self.socket_path).exists()

    def submit_job(self, job: dict) -> dict:
        """
        Send a deployment job request and return the result dict.
        Never raises — returns a failed result on any error.
        """
        if not self.available:
            msg = (
                f"Deployer socket not found at {self.socket_path}. "
                "Start the host deployer: python deployer/deployer.py"
            )
            log.warning(msg)
            return {"job_id": job.get("job_id"), "status": "failed", "error": msg}

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(310)
                sock.connect(self.socket_path)
                sock.sendall(json.dumps(job).encode() + b"\n")

                buf = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in buf:
                        break

            return json.loads(buf.strip())
        except Exception as exc:
            log.exception("deployer communication error for job %s", job.get("job_id"))
            return {"job_id": job.get("job_id"), "status": "failed", "error": str(exc)}
