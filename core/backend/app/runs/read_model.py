"""Run API read models — RunOut enrichment and trace aggregation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..models import Agent, AgentVersion, Artifact, ContextSnapshot, ModelProvider, Proposal, Run, RuntimeAdapter
from ..proposals.read_model import proposal_to_summary_out
from ..runtimes.adapter_metadata import get_adapter_model_config_metadata
from ..schemas import (
    AgentModelSummary,
    AgentOut,
    ArtifactSummaryOut,
    RunOut,
    RunResolvedModelOut,
    RunEventOut,
    RunStepOut,
    RunTraceAgentVersionOut,
    RunTraceContextSnapshotOut,
    RunTraceLineageOut,
    RunTraceModelProviderOut,
    RunTraceOut,
    RunTraceRuntimeAdapterOut,
)


def build_run_resolved_model(db: Session, run: Run) -> RunResolvedModelOut:
    override = dict(run.model_override_json or {})
    source = override.get("source") or "none"
    if source not in ("request", "agent_default", "runtime_default", "space_default", "none"):
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


def _sha256_text(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _agent_to_out(db: Session, agent: Agent | None) -> AgentOut | None:
    if agent is None:
        return None
    model: AgentModelSummary | None = None
    if agent.current_version_id:
        version = (
            db.query(AgentVersion)
            .filter(
                AgentVersion.id == agent.current_version_id,
                AgentVersion.space_id == agent.space_id,
            )
            .first()
        )
        if version is not None:
            provider_name = None
            provider_type = None
            if version.model_provider_id:
                provider = (
                    db.query(ModelProvider)
                    .filter(
                        ModelProvider.id == version.model_provider_id,
                        ModelProvider.space_id == agent.space_id,
                    )
                    .first()
                )
                provider_name = provider.name if provider else None
                provider_type = provider.provider_type if provider else None
            if version.model_provider_id or version.model_name:
                model = AgentModelSummary(
                    provider_id=version.model_provider_id,
                    provider_name=provider_name,
                    provider_type=provider_type,
                    model=version.model_name,
                )
    return AgentOut(
        id=agent.id,
        space_id=agent.space_id,
        created_by_user_id=agent.owner_user_id or "",
        name=agent.name,
        description=agent.description,
        visibility=agent.visibility,
        role_instruction=None,
        status=agent.status,
        current_version_id=agent.current_version_id,
        model=model,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _agent_version_to_trace(version: AgentVersion | None) -> RunTraceAgentVersionOut | None:
    if version is None:
        return None
    prompt = version.system_prompt
    return RunTraceAgentVersionOut(
        id=version.id,
        agent_id=version.agent_id,
        space_id=version.space_id,
        version_label=version.version_label,
        model_provider_id=version.model_provider_id,
        model_name=version.model_name,
        runtime_adapter_id=version.runtime_adapter_id,
        system_prompt_present=bool(prompt),
        system_prompt_sha256=_sha256_text(prompt),
        model_config_json=dict(version.model_config_json or {}),
        runtime_config_json=dict(version.runtime_config_json or {}),
        context_policy_json=dict(version.context_policy_json or {}),
        memory_policy_json=dict(version.memory_policy_json or {}),
        capabilities_json=list(version.capabilities_json or []),
        tool_permissions_json=dict(version.tool_permissions_json or {}),
        runtime_policy_json=dict(version.runtime_policy_json or {}),
        source_proposal_id=getattr(version, "source_proposal_id", None),
        source_activity_id=getattr(version, "source_activity_id", None),
        created_at=version.created_at,
        published_at=version.published_at,
        archived_at=version.archived_at,
    )


def _runtime_adapter_to_trace(adapter: RuntimeAdapter | None) -> RunTraceRuntimeAdapterOut | None:
    if adapter is None:
        return None
    return RunTraceRuntimeAdapterOut(
        id=adapter.id,
        space_id=adapter.space_id,
        name=adapter.name,
        adapter_type=adapter.adapter_type,
        enabled=bool(adapter.enabled),
        provider_id=adapter.provider_id,
        credential_configured=bool(adapter.credential_id),
        health_status=adapter.health_status,
        execution_plane_id=adapter.execution_plane_id,
    )


def _model_provider_to_trace(provider: ModelProvider | None) -> RunTraceModelProviderOut | None:
    if provider is None:
        return None
    return RunTraceModelProviderOut(
        id=provider.id,
        space_id=provider.space_id,
        name=provider.name,
        provider_type=provider.provider_type,
        default_model=provider.default_model,
        enabled=bool(provider.enabled),
        has_credential=bool(provider.credential_id),
    )


def _context_snapshot_to_trace(snapshot: ContextSnapshot | None) -> RunTraceContextSnapshotOut | None:
    if snapshot is None:
        return None
    return RunTraceContextSnapshotOut(
        id=snapshot.id,
        space_id=snapshot.space_id,
        source_refs_json=list(snapshot.source_refs_json or []),
        token_estimate=snapshot.token_estimate,
        relevant_period_start=snapshot.relevant_period_start,
        relevant_period_end=snapshot.relevant_period_end,
        prefix_hash=snapshot.prefix_hash,
        tail_hash=snapshot.tail_hash,
        compiler_version=snapshot.compiler_version,
        retrieval_trace_json=snapshot.retrieval_trace_json,
        token_budget_json=snapshot.token_budget_json,
        policy_bundle_version=snapshot.policy_bundle_version,
        memory_digest_version=snapshot.memory_digest_version,
        workspace_digest_version=snapshot.workspace_digest_version,
        target_runtime_adapter_id=snapshot.target_runtime_adapter_id,
        execution_plane_id=snapshot.execution_plane_id,
        included_memory_refs_json=snapshot.included_memory_refs_json,
        included_file_refs_json=snapshot.included_file_refs_json,
        included_doc_refs_json=snapshot.included_doc_refs_json,
        redactions_json=snapshot.redactions_json,
        data_exposure_level=snapshot.data_exposure_level,
        rendered_context_uri=snapshot.rendered_context_uri,
        has_compiled_prefix_text=bool(snapshot.compiled_prefix_text),
        has_compiled_tail_text=bool(snapshot.compiled_tail_text),
        has_rendered_context_text=bool(snapshot.rendered_context_text),
        created_at=snapshot.created_at,
    )


def _lineage_to_trace(run: Run | None) -> RunTraceLineageOut | None:
    return RunTraceLineageOut.model_validate(run) if run is not None else None


def build_run_trace(db: Session, run: Run) -> RunTraceOut:
    """Aggregate the safe replay spine for a run in one read model."""
    version = (
        db.query(AgentVersion)
        .filter(AgentVersion.id == run.agent_version_id, AgentVersion.space_id == run.space_id)
        .first()
    )
    adapter_id = run.runtime_adapter_id or (version.runtime_adapter_id if version else None)
    provider_id = run.model_provider_id or (version.model_provider_id if version else None)
    adapter = (
        db.query(RuntimeAdapter)
        .filter(RuntimeAdapter.id == adapter_id, RuntimeAdapter.space_id == run.space_id)
        .first()
        if adapter_id
        else None
    )
    provider = (
        db.query(ModelProvider)
        .filter(ModelProvider.id == provider_id, ModelProvider.space_id == run.space_id)
        .first()
        if provider_id
        else None
    )
    artifacts = (
        db.query(Artifact)
        .filter(Artifact.run_id == run.id, Artifact.space_id == run.space_id)
        .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        .all()
    )
    proposals = (
        db.query(Proposal)
        .filter(Proposal.created_by_run_id == run.id, Proposal.space_id == run.space_id)
        .order_by(Proposal.created_at.asc(), Proposal.id.asc())
        .all()
    )
    children = (
        db.query(Run)
        .filter(Run.parent_run_id == run.id, Run.space_id == run.space_id)
        .order_by(Run.created_at.asc(), Run.id.asc())
        .all()
    )

    now = datetime.now(UTC)
    return RunTraceOut(
        run=run_to_out(db, run),
        agent=_agent_to_out(db, run.agent),
        agent_version=_agent_version_to_trace(version),
        runtime_adapter=_runtime_adapter_to_trace(adapter),
        model_provider=_model_provider_to_trace(provider),
        context_snapshot=_context_snapshot_to_trace(run.context_snapshot),
        steps=[RunStepOut.model_validate(step) for step in run.steps],
        events=[RunEventOut.model_validate(event) for event in run.events],
        artifacts=[ArtifactSummaryOut.model_validate(artifact) for artifact in artifacts],
        proposals=[proposal_to_summary_out(proposal, now=now) for proposal in proposals],
        parent=_lineage_to_trace(run.parent_run),
        children=[RunTraceLineageOut.model_validate(child) for child in children],
    )
