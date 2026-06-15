"""Authority guard for the Stage 6 chat-turn slice."""

from __future__ import annotations

import os

from fastapi import HTTPException


def chat_turn_owned_by_ts() -> bool:
    return (
        os.getenv("CONTROL_PLANE_CHAT_TURN_AUTHORITY", "python").strip().lower()
        == "ts"
    )


def reject_python_chat_turn_when_ts_authority() -> None:
    if not chat_turn_owned_by_ts():
        return
    raise HTTPException(
        status_code=410,
        detail=(
            "Python no longer owns agents.chat; this command is served by the "
            "TypeScript control plane."
        ),
    )


def context_assembly_owned_by_ts() -> bool:
    """Stage 6 slice 4: chat-path context assembly is TS-owned when flipped."""
    return (
        os.getenv("CONTROL_PLANE_CONTEXT_AUTHORITY", "python").strip().lower()
        == "ts"
    )


def reject_python_chat_context_build_when_ts_authority() -> None:
    """Guard the Python chat context-build + snapshot-persist path.

    When `CONTROL_PLANE_CONTEXT_AUTHORITY=ts`, the TS chat turn owns the
    `ChatContextBuilder` selection loop and `context_snapshots` persistence and
    sources candidates / run creation through the narrow read/run-create ports.
    The combined `prepare-run` port (which builds context *and* persists the
    snapshot) must fail closed so context build never has two authorities.
    """
    if not context_assembly_owned_by_ts():
        return
    raise HTTPException(
        status_code=410,
        detail=(
            "Python no longer owns chat context assembly; the TypeScript control "
            "plane builds chat context and persists the snapshot. Use the "
            "context-candidates and create-run ports instead."
        ),
    )
