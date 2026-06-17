"""Authority guards for chat routes now owned by the TypeScript control plane."""

from __future__ import annotations

from fastapi import HTTPException


def chat_turn_owned_by_ts() -> bool:
    return True


def reject_python_chat_turn_when_ts_authority() -> None:
    raise HTTPException(
        status_code=410,
        detail=(
            "Python no longer owns agents.chat; this command is served by the "
            "TypeScript control plane."
        ),
    )


def context_assembly_owned_by_ts() -> bool:
    """Chat-path context assembly is fixed TS-owned."""
    return True


def reject_python_chat_context_build_when_ts_authority() -> None:
    """Guard the Python chat context-build + snapshot-persist path.

    The TS chat turn owns candidate collection, `ChatContextBuilder` selection,
    run creation, and `context_snapshots` persistence. The combined Python
    `prepare-run` port must fail closed so context build never has two
    authorities.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "Python no longer owns chat context assembly; the TypeScript control "
            "plane builds chat context and persists the snapshot."
        ),
    )
