"""Agents-owned proposal appliers — registration hook for the proposal registry.

The agents module owns the apply business logic for ``agent_config_update``:
create a new immutable AgentVersion from the proposal's base version plus
changes, record an ``agent_config_updated`` ActivityRecord, stamp the result
ids back onto the proposal payload, and advance the Agent's current-version
pointer. (Moved unchanged from the pre-registry central dispatch in
``app.proposals.apply_service``.)

Wired through ``app.modules.registry.register_proposal_appliers``. The applier
runs inside the accept transaction owned by ``ProposalService.accept`` and
must not commit; approval governance stays at the policy gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm.attributes import flag_modified

from ..proposals import (
    ProposalApplierRegistry,
    ProposalApplyContext,
    ProposalApplyError,
    ProposalApplyResult,
)


def _apply_agent_config_update(context: ProposalApplyContext) -> ProposalApplyResult:
    from ..models import ActivityRecord, Agent, AgentVersion, ModelProvider, RuntimeAdapter
    from ..schemas import (
        DEFAULT_MEMORY_POLICY,
        DEFAULT_MODEL_CONFIG,
        DEFAULT_RUNTIME_POLICY,
        AgentVersionCreate,
    )
    from .version_service import AgentVersionService

    db = context.db
    proposal = context.proposal
    user_id = context.user_id

    payload = proposal.payload_json or {}
    agent_id = payload.get("agent_id")
    base_version_id = payload.get("base_version_id")
    changes = payload.get("changes")
    if not isinstance(agent_id, str) or not agent_id:
        raise ProposalApplyError("agent_config_update missing agent_id")
    if not isinstance(base_version_id, str) or not base_version_id:
        raise ProposalApplyError("agent_config_update missing base_version_id")
    if not isinstance(changes, dict) or not changes:
        raise ProposalApplyError("agent_config_update missing changes")

    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.space_id == proposal.space_id)
        .first()
    )
    if agent is None:
        raise ProposalApplyError("agent not found for config proposal")
    if agent.current_version_id != base_version_id:
        raise ProposalApplyError("stale agent_config_update proposal: base_version_id is not current")

    base = AgentVersionService(db).get_version_for_agent(
        base_version_id,
        agent.id,
        proposal.space_id,
    )

    version_dict = {
        "model_provider_id": base.model_provider_id,
        "model_name": base.model_name,
        "runtime_adapter_id": base.runtime_adapter_id,
        "system_prompt": base.system_prompt,
        "model_config_json": base.model_config_json or dict(DEFAULT_MODEL_CONFIG),
        "runtime_config_json": base.runtime_config_json or dict(DEFAULT_RUNTIME_POLICY),
        "context_policy_json": base.context_policy_json or {},
        "memory_policy_json": base.memory_policy_json or dict(DEFAULT_MEMORY_POLICY),
        "capabilities_json": base.capabilities_json or [],
        "tool_permissions_json": base.tool_permissions_json or {},
        "runtime_policy_json": base.runtime_policy_json or dict(DEFAULT_RUNTIME_POLICY),
    }

    allowed_fields = set(version_dict)
    unknown = sorted(set(changes) - allowed_fields)
    if unknown:
        raise ProposalApplyError(f"agent_config_update contains unsupported field(s): {', '.join(unknown)}")
    version_dict.update(changes)

    provider_id = version_dict.get("model_provider_id")
    model_name = version_dict.get("model_name")
    if model_name and not provider_id:
        raise ProposalApplyError("model_provider_id is required when model_name is set")
    if provider_id:
        provider = (
            db.query(ModelProvider)
            .filter(ModelProvider.id == provider_id, ModelProvider.space_id == proposal.space_id)
            .first()
        )
        if provider is None:
            raise ProposalApplyError("model_provider_id does not belong to this space")

    runtime_adapter_id = version_dict.get("runtime_adapter_id")
    if runtime_adapter_id:
        adapter = (
            db.query(RuntimeAdapter)
            .filter(RuntimeAdapter.id == runtime_adapter_id, RuntimeAdapter.space_id == proposal.space_id)
            .first()
        )
        if adapter is None:
            raise ProposalApplyError("runtime_adapter_id does not belong to this space")

    existing_labels = [
        row[0]
        for row in (
            db.query(AgentVersion.version_label)
            .filter(AgentVersion.agent_id == agent.id, AgentVersion.space_id == proposal.space_id)
            .all()
        )
    ]
    max_n = 0
    for label in existing_labels:
        if isinstance(label, str) and label.startswith("v"):
            try:
                max_n = max(max_n, int(label[1:]))
            except ValueError:
                continue
    version_data = AgentVersionCreate(**version_dict)
    new_version = AgentVersion(
        agent_id=agent.id,
        space_id=proposal.space_id,
        version_label=f"v{max_n + 1}",
        model_provider_id=version_data.model_provider_id,
        model_name=version_data.model_name,
        runtime_adapter_id=version_data.runtime_adapter_id,
        system_prompt=version_data.system_prompt,
        model_config_json=version_data.model_config_json,
        runtime_config_json=version_data.runtime_config_json,
        context_policy_json=version_data.context_policy_json,
        memory_policy_json=version_data.memory_policy_json,
        capabilities_json=version_data.capabilities_json,
        tool_permissions_json=version_data.tool_permissions_json,
        runtime_policy_json=version_data.runtime_policy_json,
        source_proposal_id=proposal.id,
    )
    db.add(new_version)
    db.flush()
    activity = ActivityRecord(
        space_id=proposal.space_id,
        user_id=user_id,
        agent_id=agent.id,
        activity_type="agent_config_updated",
        title=f"Agent config updated: {agent.name}",
        content=None,
        payload_json={
            "proposal_id": proposal.id,
            "agent_id": agent.id,
            "base_version_id": base_version_id,
            "new_version_id": new_version.id,
            "changed_fields": sorted(changes),
        },
        status="processed",
        source_kind="system_event",
        source_trust="internal_system",
        consolidation_status="processed",
    )
    db.add(activity)
    db.flush()
    new_version.source_activity_id = activity.id
    payload_with_result = dict(proposal.payload_json or {})
    payload_with_result["resulting_agent_version_id"] = new_version.id
    payload_with_result["source_activity_id"] = activity.id
    proposal.payload_json = payload_with_result
    flag_modified(proposal, "payload_json")
    agent.current_version_id = new_version.id
    agent.updated_at = datetime.now(UTC)
    return ProposalApplyResult(proposal=proposal, agent_version=new_version)


def register_proposal_appliers(registry: ProposalApplierRegistry) -> None:
    """Register every agents-owned proposal applier."""
    registry.register("agent_config_update", _apply_agent_config_update)
