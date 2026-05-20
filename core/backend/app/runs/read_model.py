"""Run API read model — enriches ORM Run rows for RunOut responses."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import ModelProvider, Run
from ..runtimes.adapter_metadata import get_adapter_model_config_metadata
from ..schemas import RunOut, RunResolvedModelOut


def build_run_resolved_model(db: Session, run: Run) -> RunResolvedModelOut:
    override = dict(run.model_override_json or {})
    source = override.get("source") or "none"
    if source not in ("request", "agent_default", "space_default", "none"):
        source = "none"

    model_name = override.get("model")
    provider_id = run.model_provider_id
    provider_name: str | None = None
    provider_type: str | None = None

    if provider_id:
        provider = (
            db.query(ModelProvider)
            .filter(
                ModelProvider.id == provider_id,
                ModelProvider.space_id == run.space_id,
            )
            .first()
        )
        if provider is not None:
            provider_name = provider.name
            provider_type = provider.provider_type

    adapter_type = run.adapter_type
    meta = get_adapter_model_config_metadata(adapter_type)
    has_recorded_model = bool(provider_id or model_name)
    used_by_adapter = meta.uses_model_config and has_recorded_model

    disclosure_note: str | None = None
    if has_recorded_model and not used_by_adapter and meta.model_config_note:
        disclosure_note = meta.model_config_note

    return RunResolvedModelOut(
        provider_id=provider_id,
        provider_name=provider_name,
        provider_type=provider_type,
        model=model_name,
        source=source,
        used_by_adapter=used_by_adapter,
        adapter_model_support=meta.model_config_behavior,
        disclosure_note=disclosure_note,
    )


def run_to_out(db: Session, run: Run) -> RunOut:
    payload = RunOut.model_validate(run)
    payload.resolved_model = build_run_resolved_model(db, run)
    return payload
