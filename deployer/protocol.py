"""
Shared protocol definitions for the deployer Unix socket interface.

The same file is importable by both the deployer process and the backend client.
Wire format: one JSON object per line (newline-delimited JSON).
"""
from __future__ import annotations
from typing import Literal

JobType = Literal[
    "rebuild_agent_space",   # docker compose build + up -d backend frontend
    "restart_agent_space",   # docker compose restart backend frontend
    "health_check",          # curl /health on backend
]

ALLOWED_JOB_TYPES: set[str] = set(JobType.__args__)  # type: ignore[attr-defined]
