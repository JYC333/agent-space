"""Authority guard for run command ownership during TS migration."""

from __future__ import annotations

import os

from fastapi import HTTPException


def runs_commands_owned_by_ts() -> bool:
    return os.getenv("CONTROL_PLANE_RUNS_AUTHORITY", "python").strip().lower() == "ts"


def reject_python_run_command_when_ts_authority(command: str) -> None:
    if not runs_commands_owned_by_ts():
        return
    raise HTTPException(
        status_code=410,
        detail=(
            f"Python no longer owns runs.{command}; route this command through "
            "the TypeScript control plane."
        ),
    )
