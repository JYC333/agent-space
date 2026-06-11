"""Explicit feature gates for capabilities not backed by the canonical schema.

Persistence flags are plain booleans — never derived from stub ORM types.
"""

from __future__ import annotations

from fastapi import HTTPException

# Until matching tables exist in the canonical initial migration:
API_KEYS_DB_PERSISTED = False

_MESSAGES: dict[str, str] = {
    "api_keys": (
        "API key storage is not in the canonical schema (ApiKey is deferred)."
    ),
    "workspace_console_sessions": (
        "Workspace console sessions are not persisted in the current canonical schema. "
        "The sessions list is empty until persistence ships; file tree, git, and runtimes stay available."
    ),
    "deployment_jobs": (
        "Deployment jobs are not persisted in the current canonical schema "
        "(DeploymentJob is deferred)."
    ),
}


def feature_not_implemented(feature_id: str) -> None:
    """Raise HTTP 501 for a feature that has no canonical persistence layer yet."""
    detail = _MESSAGES.get(feature_id, f"Feature {feature_id!r} is not implemented.")
    raise HTTPException(status_code=501, detail=detail)
