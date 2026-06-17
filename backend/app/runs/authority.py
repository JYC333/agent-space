"""Authority guard for run command ownership during TS migration."""

from __future__ import annotations

from fastapi import HTTPException


def runs_commands_owned_by_ts() -> bool:
    return True


def reject_python_run_command_when_ts_authority(command: str) -> None:
    raise HTTPException(
        status_code=410,
        detail=(
            f"Python no longer owns runs.{command}; route this command through "
            "the TypeScript control plane."
        ),
    )
