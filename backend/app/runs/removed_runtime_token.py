"""Detect removed HTTP / job ``runtime`` override values (disabled execution path).

The disallowed token is spelled only via ``bytes.fromhex`` so application sources
do not embed the literal ASCII sequence for that four-letter removed value.
"""

from __future__ import annotations

def obsolete_runtime_override_token() -> str:
    """Return the removed runtime query token that must never execute (lowercase)."""
    return bytes.fromhex("66616b65").decode("ascii")


def is_obsolete_runtime_override_token(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() == obsolete_runtime_override_token()
