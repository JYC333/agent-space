from __future__ import annotations

"""Metadata sanitizer for PolicyDecisionRecord.

Redacts or rejects known dangerous keys before any sensitive policy decision
metadata is persisted. Bounds size and depth to prevent large-blob storage.

Dangerous keys are checked recursively (case-insensitive substring match for
known key names) to catch nested structures like {"ctx": {"password": "x"}}.
"""

from typing import Any

_DANGEROUS_KEYS: frozenset[str] = frozenset({
    "password",
    "token",
    "api_key",
    "secret",
    "credential",
    "personal_context_block",
    "raw_memory",
    "memory_content",
    "prompt",
    "rendered_context",
    "stdout",
    "stderr",
    "patch",
    "diff",
    "file_content",
})

_MAX_DEPTH = 4
_MAX_KEYS = 32
_MAX_STR_LEN = 512
_MAX_TOTAL_KEYS = 128

_REDACTED = "[REDACTED]"


def _is_dangerous_key(key: str) -> bool:
    """Return True if the key matches any known dangerous name (case-insensitive)."""
    lower = key.lower()
    return any(dk in lower for dk in _DANGEROUS_KEYS)


def _sanitize_value(value: Any, *, depth: int, key_budget: list[int]) -> Any:
    if depth > _MAX_DEPTH:
        return _REDACTED
    if key_budget[0] <= 0:
        return _REDACTED

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if key_budget[0] <= 0:
                break
            key_budget[0] -= 1
            if _is_dangerous_key(str(k)):
                out[str(k)] = _REDACTED
            else:
                out[str(k)] = _sanitize_value(v, depth=depth + 1, key_budget=key_budget)
        return out

    if isinstance(value, list):
        return [
            _sanitize_value(item, depth=depth + 1, key_budget=key_budget)
            for item in value[:_MAX_KEYS]
        ]

    if isinstance(value, str):
        return value[:_MAX_STR_LEN] if len(value) > _MAX_STR_LEN else value

    return value


def sanitize_policy_metadata(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a sanitized copy of metadata suitable for PolicyDecisionRecord persistence.

    - Redacts values under known dangerous keys recursively.
    - Truncates strings to _MAX_STR_LEN characters.
    - Stops processing after _MAX_TOTAL_KEYS total keys across all depths.
    - Returns None for None input.

    Never raises — if sanitization itself fails, returns a safe error marker.
    """
    if data is None:
        return None
    try:
        key_budget = [_MAX_TOTAL_KEYS]
        return _sanitize_value(data, depth=0, key_budget=key_budget)
    except Exception:
        return {"_sanitizer_error": True}
