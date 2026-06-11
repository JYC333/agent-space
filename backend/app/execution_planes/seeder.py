from __future__ import annotations
"""Seed canonical default execution planes.

Default planes represent the execution environments agent-space knows about
at installation time. They are system-level records scoped to each space and
are idempotent: re-seeding never duplicates them.
"""

from sqlalchemy.orm import Session

from ..models import ExecutionPlane

_DEFAULT_PLANES: list[dict] = [
    {
        "name": "agent_space_native_local",
        "type": "native",
        "provider": "agent_space",
        "execution_location": "local",
        "runtime_origin": "native",
        "trust_level": "high",
        "observability_level": "full_trace",
        "data_exposure_level": "local_only",
        "credential_mode": "agent_space_vault",
        "config_json": {},
        "enabled": True,
    },
    {
        "name": "managed_model_api",
        "type": "hybrid",
        "provider": "agent_space",
        "execution_location": "local",
        "runtime_origin": "native",
        "trust_level": "high",
        "observability_level": "full_trace",
        "data_exposure_level": "model_provider",
        "credential_mode": "agent_space_vault",
        "config_json": {},
        "enabled": True,
    },
    {
        "name": "local_codex_cli",
        "type": "local",
        "provider": "openai",
        "execution_location": "local",
        "runtime_origin": "open_source_external",
        "trust_level": "medium",
        "observability_level": "artifacts_only",
        "data_exposure_level": "local_only",
        "credential_mode": "user_local",
        "config_json": {},
        "enabled": True,
    },
    {
        "name": "local_claude_code_cli",
        "type": "local",
        "provider": "anthropic",
        "execution_location": "local",
        "runtime_origin": "open_source_external",
        "trust_level": "medium",
        "observability_level": "artifacts_only",
        "data_exposure_level": "local_only",
        "credential_mode": "user_local",
        "config_json": {},
        "enabled": True,
    },
    {
        "name": "local_opencode",
        "type": "local",
        "provider": "opencode",
        "execution_location": "local",
        "runtime_origin": "open_source_external",
        "trust_level": "medium",
        "observability_level": "artifacts_only",
        "data_exposure_level": "local_only",
        "credential_mode": "user_local",
        "config_json": {},
        "enabled": True,
    },
    {
        "name": "remote_codex",
        "type": "remote_vendor",
        "provider": "openai",
        "execution_location": "remote",
        "runtime_origin": "external_vendor",
        "trust_level": "low",
        "observability_level": "final_output_only",
        "data_exposure_level": "vendor_platform",
        "credential_mode": "vendor_account",
        "config_json": {},
        "enabled": False,
    },
    {
        "name": "remote_claude",
        "type": "remote_vendor",
        "provider": "anthropic",
        "execution_location": "remote",
        "runtime_origin": "external_vendor",
        "trust_level": "low",
        "observability_level": "final_output_only",
        "data_exposure_level": "vendor_platform",
        "credential_mode": "vendor_account",
        "config_json": {},
        "enabled": False,
    },
    {
        "name": "manual_import",
        "type": "manual",
        "provider": "other",
        "execution_location": "manual",
        "runtime_origin": "manual",
        "trust_level": "unknown",
        "observability_level": "black_box",
        "data_exposure_level": "unknown",
        "credential_mode": "none",
        "config_json": {},
        "enabled": True,
    },
]


def seed_default_execution_planes(db: Session, space_id: str, *, commit: bool = True) -> int:
    """Idempotently ensure all default execution planes exist for the given space.

    Returns the number of plane rows actually inserted on this call (0 when every
    default plane already existed). Existing rows are never modified.

    ``commit`` controls transaction ownership: standalone callers (bootstrap,
    tests) keep the default and this commits; callers inside a larger transaction
    (e.g. the space-created hook) pass ``commit=False`` so the rows flush but the
    surrounding caller owns the single commit, keeping space creation atomic.
    """
    inserted = 0
    for spec in _DEFAULT_PLANES:
        existing = (
            db.query(ExecutionPlane)
            .filter(ExecutionPlane.space_id == space_id, ExecutionPlane.name == spec["name"])
            .first()
        )
        if not existing:
            plane = ExecutionPlane(space_id=space_id, **spec)
            db.add(plane)
            inserted += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return inserted
