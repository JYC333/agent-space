from __future__ import annotations
import uuid
"""
AgentService — CRUD for Agent configurations and multi-agent run orchestration.

Separation of concerns:
  - AgentService   — manages Agent records + AgentVersion lifecycle + policy checks
  - RunService     — owns Run creation and lifecycle
  - Runner module  — adapter registry + post-run hooks

Agent identity fields (name, description, visibility, status) live on Agent.
Execution configuration lives on AgentVersion (append-only).
PATCH only changes identity fields; post-create execution configuration changes
must be accepted through an agent_config_update proposal.
Run execution reads runtime_policy from the current AgentVersion.

run() and submit() create Runs via RunService (status=queued).
Adapter execution, Artifact/Proposal/MemoryEntry materialization, and sandbox
work happen in RunExecutionService — not in AgentService.
"""

from datetime import datetime, UTC
from sqlalchemy.orm import Session as DBSession
from fastapi import HTTPException

from ..models import Agent, Run, AgentVersion, ModelProvider
from ..schemas import (
    AgentCreate, AgentUpdate, RunRequest,
    AgentConfigProposalCreate,
    AgentVersionCreate,
    RunCreate,
    AgentOut, AgentModelSummary,
    DEFAULT_MODEL_CONFIG, DEFAULT_MEMORY_POLICY, DEFAULT_RUNTIME_POLICY,
)
from ..spaces.defaults import resolve_default_space_id

import logging

log = logging.getLogger(__name__)

_router_service = None


def _new_id() -> str:
    return str(uuid.uuid4())


def _get_router_service():
    global _router_service
    if _router_service is None:
        from ..router import RouterService

        _router_service = RouterService()
    return _router_service


class AgentService:
    def __init__(self, db: DBSession):
        self.db = db

    def _validate_model_provider(self, provider_id: str | None, space_id: str) -> None:
        if not provider_id:
            return
        from ..providers import ModelService
        try:
            ModelService().assert_selectable(self.db, provider_id, space_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _model_summary_for_agent(self, agent: Agent) -> AgentModelSummary | None:
        if not agent.current_version_id:
            return None
        version = self.db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).first()
        if not version or not version.model_provider_id:
            if version and version.model_name:
                return AgentModelSummary(model=version.model_name)
            return None
        provider = self.db.query(ModelProvider).filter(
            ModelProvider.id == version.model_provider_id
        ).first()
        return AgentModelSummary(
            provider_id=version.model_provider_id,
            provider_name=provider.name if provider else None,
            provider_type=provider.provider_type if provider else None,
            model=version.model_name,
        )

    def _system_prompt_for_agent(self, agent: Agent) -> str | None:
        if not agent.current_version_id:
            return None
        version = self.db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).first()
        return version.system_prompt if version else None

    def to_agent_out(self, agent: Agent) -> AgentOut:
        return AgentOut(
            id=agent.id,
            space_id=agent.space_id,
            created_by_user_id=agent.owner_user_id,
            name=agent.name,
            description=agent.description,
            visibility=agent.visibility,
            role_instruction=agent.role_instruction,
            status=agent.status,
            agent_kind=agent.agent_kind,
            current_version_id=agent.current_version_id,
            source_template_id=agent.source_template_id,
            source_template_version_id=agent.source_template_version_id,
            model=self._model_summary_for_agent(agent),
            system_prompt=self._system_prompt_for_agent(agent),
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    def _version_fields_from_current(self, agent: Agent) -> dict:
        base = {
            "model_provider_id": None,
            "model_name": None,
            "model_config_json": DEFAULT_MODEL_CONFIG.copy(),
            "memory_policy_json": DEFAULT_MEMORY_POLICY.copy(),
            "capabilities_json": [],
            "tool_permissions_json": {},
            "runtime_policy_json": DEFAULT_RUNTIME_POLICY.copy(),
        }
        if not agent.current_version_id:
            return base
        from .version_service import AgentVersionService
        current = AgentVersionService(self.db).get_or_404(agent.current_version_id)
        base.update({
            "model_provider_id": current.model_provider_id,
            "model_name": current.model_name,
            "model_config_json": current.model_config_json,
            "memory_policy_json": current.memory_policy_json,
            "capabilities_json": current.capabilities_json,
            "tool_permissions_json": current.tool_permissions_json,
            "runtime_policy_json": current.runtime_policy_json,
        })
        return base

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, data: AgentCreate, requesting_user_id: str | None = None) -> Agent:
        from .version_service import AgentVersionService
        space_id = data.space_id or resolve_default_space_id(self.db)
        owner_user_id = data.created_by_user_id or requesting_user_id
        if owner_user_id is None:
            raise HTTPException(
                status_code=400,
                detail="agent creation requires an owner (created_by_user_id or an authenticated user)",
            )

        version_svc = AgentVersionService(self.db)

        self._validate_model_provider(data.default_model_provider_id, space_id)
        if data.default_model and not data.default_model_provider_id:
            raise HTTPException(
                status_code=400,
                detail="default_model_provider_id is required when default_model is set",
            )

        # Resolve the runtime adapter into the v1 policy (merge, don't replace).
        runtime_policy = dict(data.runtime_policy_json or DEFAULT_RUNTIME_POLICY)
        if data.adapter_type:
            from ..runtimes.requirements import get_runtime_requirements
            try:
                requirements = get_runtime_requirements(data.adapter_type)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Unknown adapter_type {data.adapter_type!r}")
            runtime_policy["default_adapter_type"] = data.adapter_type
            allowed = list(runtime_policy.get("allowed_adapter_types") or [])
            if data.adapter_type not in allowed:
                allowed.append(data.adapter_type)
            runtime_policy["allowed_adapter_types"] = allowed
            if requirements.model_provider_mode == "required" and not data.default_model_provider_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"adapter_type {data.adapter_type!r} requires a model provider; set default_model_provider_id.",
                )

        agent = Agent(
            id=_new_id(),
            space_id=space_id,
            owner_user_id=owner_user_id,
            name=data.name,
            description=data.description,
            visibility=data.visibility,
            role_instruction=data.role_instruction,
            status="active",
        )
        self.db.add(agent)
        self.db.flush()

        version_data = AgentVersionCreate(
            model_provider_id=data.default_model_provider_id,
            model_name=data.default_model,
            system_prompt=data.system_prompt,
            model_config_json=dict(data.model_config_json or DEFAULT_MODEL_CONFIG),
            memory_policy_json=dict(data.memory_policy_json or DEFAULT_MEMORY_POLICY),
            capabilities_json=list(data.capabilities_json or []),
            tool_permissions_json=dict(data.tool_permissions_json or {}),
            runtime_policy_json=runtime_policy,
        )
        version = version_svc.create(
            agent_id=agent.id,
            space_id=space_id,
            data=version_data,
            label="v1",
        )
        agent.current_version_id = version.id

        self.db.commit()
        self.db.refresh(agent)
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return self.db.query(Agent).filter(Agent.id == agent_id).first()

    def get_or_404(self, agent_id: str) -> Agent:
        agent = self.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        return agent

    def list(
        self,
        space_id: str,
        created_by_user_id: str | None = None,
        visibility: str | None = None,
        status: str | None = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Agent]:
        q = self.db.query(Agent).filter(Agent.space_id == space_id)
        if created_by_user_id:
            q = q.filter(Agent.owner_user_id == created_by_user_id)
        if visibility:
            q = q.filter(Agent.visibility == visibility)
        if status:
            q = q.filter(Agent.status == status)
        return q.order_by(Agent.created_at.desc()).offset(offset).limit(limit).all()

    # Agent-level metadata fields edited directly on the Agent row.
    _AGENT_LEVEL_FIELDS = ("name", "description", "visibility", "role_instruction", "status")

    # AgentUpdate field → versioned AgentVersion field. An owner's direct edit of these
    # appends a new immutable AgentVersion + records an Activity (no proposal needed).
    _EXEC_FIELD_MAP = {
        "system_prompt": "system_prompt",
        "default_model_provider_id": "model_provider_id",
        "model_provider_id": "model_provider_id",
        "default_model": "model_name",
        "model_name": "model_name",
        "runtime_adapter_id": "runtime_adapter_id",
        "model_config_json": "model_config_json",
        "runtime_config_json": "runtime_config_json",
        "context_policy_json": "context_policy_json",
        "memory_policy_json": "memory_policy_json",
        "capabilities_json": "capabilities_json",
        "tool_permissions_json": "tool_permissions_json",
        "runtime_policy_json": "runtime_policy_json",
    }

    def update(self, agent_id: str, data: AgentUpdate, *, user_id: str | None = None) -> Agent | None:
        agent = self.get(agent_id)
        if not agent:
            return None

        update_dict = data.model_dump(exclude_none=True)

        for field in self._AGENT_LEVEL_FIELDS:
            if field in update_dict:
                setattr(agent, field, update_dict[field])

        # Execution config is versioned: the owner edits it directly (no proposal —
        # the owner is the authority and there is no second party to review). The
        # immutable-version mechanism preserves history; an Activity records the edit.
        # The agent_config_update proposal flow remains for *proposed* changes (e.g. an
        # agent learning loop or automation suggesting config), which need human review.
        changes = {tgt: update_dict[src] for src, tgt in self._EXEC_FIELD_MAP.items() if src in update_dict}
        if changes:
            self._apply_config_update_direct(agent, changes, user_id=user_id)

        agent.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def _apply_config_update_direct(self, agent: Agent, changes: dict, *, user_id: str | None) -> AgentVersion:
        """Append a new AgentVersion with `changes` over the current one + record an Activity."""
        from .version_service import AgentVersionService
        from ..activity import ActivityService
        from ..models import RuntimeAdapter

        base = AgentVersionService(self.db).get_or_404(agent.current_version_id)
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
        version_dict.update(changes)

        provider_id = version_dict.get("model_provider_id")
        if version_dict.get("model_name") and not provider_id:
            raise HTTPException(status_code=400, detail="model_provider_id is required when model_name is set")
        if provider_id:
            self._validate_model_provider(provider_id, agent.space_id)
        runtime_adapter_id = version_dict.get("runtime_adapter_id")
        if runtime_adapter_id and not self.db.query(RuntimeAdapter).filter(
            RuntimeAdapter.id == runtime_adapter_id, RuntimeAdapter.space_id == agent.space_id
        ).first():
            raise HTTPException(status_code=400, detail="runtime_adapter_id does not belong to this space")

        new_version = AgentVersionService(self.db).create(
            agent_id=agent.id, space_id=agent.space_id, data=AgentVersionCreate(**version_dict),
        )
        agent.current_version_id = new_version.id

        # Lightweight audit record (not a proposal).
        try:
            ActivityService(self.db).create(
                space_id=agent.space_id,
                source_type="system_event",
                content=f"Agent '{agent.name}' configuration updated: {', '.join(sorted(changes))}.",
                user_id=user_id,
                agent_id=agent.id,
                title="Agent configuration updated",
                metadata_json={
                    "kind": "agent_config_updated",
                    "agent_id": agent.id,
                    "changed_fields": sorted(changes.keys()),
                    "base_version_id": base.id,
                    "new_version_id": new_version.id,
                },
            )
        except Exception:
            log.warning("agent config update activity record failed for agent=%s", agent.id, exc_info=True)
        return new_version

    # ------------------------------------------------------------------
    # Owner-driven config edit from the agent config UI.
    # Copy-on-write: build a NEW AgentVersion from the current one, apply
    # only the allowed fields, re-stamp hard-safety guarantees, then repoint
    # current_version_id. The old AgentVersion is never mutated.
    # ------------------------------------------------------------------

    # Snapshots that the config UI may never edit; copied verbatim from the
    # source version so a frontend override cannot bypass hard safety defaults.
    _LOCKED_SAFETY_FIELDS = (
        "tool_policy_json",
        "tool_permissions_json",
        "capabilities_json",
        "runtime_policy_json",
        "runtime_config_json",
        "runtime_adapter_id",
    )

    def update_config(self, agent_id: str, data, *, user_id: str | None = None) -> Agent:
        from .version_service import AgentVersionService

        agent = self.get_or_404(agent_id)
        if not agent.current_version_id:
            raise HTTPException(status_code=400, detail="Agent has no current version to edit")
        base = AgentVersionService(self.db).get_or_404(agent.current_version_id)

        payload = data.model_dump(exclude_unset=True)

        # Identity fields applied directly to the Agent row.
        if payload.get("name"):
            agent.name = payload["name"]
        if "description" in payload:
            agent.description = payload["description"]

        # Full copy of the current version as the new version baseline.
        new = {
            "model_provider_id": base.model_provider_id,
            "model_name": base.model_name,
            "runtime_adapter_id": base.runtime_adapter_id,
            "system_prompt": base.system_prompt,
            "model_config_json": dict(base.model_config_json or DEFAULT_MODEL_CONFIG),
            "runtime_config_json": dict(base.runtime_config_json or DEFAULT_RUNTIME_POLICY),
            "context_policy_json": dict(base.context_policy_json or {}),
            "memory_policy_json": dict(base.memory_policy_json or DEFAULT_MEMORY_POLICY),
            "capabilities_json": list(base.capabilities_json or []),
            "tool_permissions_json": dict(base.tool_permissions_json or {}),
            "runtime_policy_json": dict(base.runtime_policy_json or DEFAULT_RUNTIME_POLICY),
            "tool_policy_json": dict(base.tool_policy_json or {}),
            "output_policy_json": dict(base.output_policy_json or {}),
            "schedule_config_json": dict(base.schedule_config_json or {}),
            "output_schema_json": dict(base.output_schema_json or {}),
        }

        changed: list[str] = []
        if "system_prompt" in payload:
            new["system_prompt"] = payload["system_prompt"]
            changed.append("system_prompt")
        if "model_provider_id" in payload:
            new["model_provider_id"] = payload["model_provider_id"]
            changed.append("model_provider_id")
        if "model_name" in payload:
            new["model_name"] = payload["model_name"]
            changed.append("model_name")
        if payload.get("model_config_json") is not None:
            new["model_config_json"] = {**new["model_config_json"], **payload["model_config_json"]}
            changed.append("model_config_json")
        if payload.get("context_policy_json") is not None:
            from .policy_safety import merge_context_policy_safe
            new["context_policy_json"] = merge_context_policy_safe(base.context_policy_json, payload["context_policy_json"])
            changed.append("context_policy_json")
        if payload.get("memory_policy_json") is not None:
            from .policy_safety import merge_memory_policy_safe
            new["memory_policy_json"] = merge_memory_policy_safe(base.memory_policy_json, payload["memory_policy_json"])
            changed.append("memory_policy_json")
        if payload.get("output_policy_json") is not None:
            from .policy_safety import merge_output_policy_safe
            new["output_policy_json"] = merge_output_policy_safe(base.output_policy_json, payload["output_policy_json"])
            changed.append("output_policy_json")
        if payload.get("schedule_config_json") is not None:
            new["schedule_config_json"] = {**new["schedule_config_json"], **payload["schedule_config_json"]}
            changed.append("schedule_config_json")
        if payload.get("output_schema_json") is not None:
            new["output_schema_json"] = dict(payload["output_schema_json"])
            changed.append("output_schema_json")

        if new.get("model_name") and not new.get("model_provider_id"):
            raise HTTPException(status_code=400, detail="model_provider_id is required when model_name is set")
        if new.get("model_provider_id"):
            self._validate_model_provider(new["model_provider_id"], agent.space_id)

        if changed:
            version = AgentVersionService(self.db).create(
                agent_id=agent.id, space_id=agent.space_id, data=AgentVersionCreate(**new),
            )
            agent.current_version_id = version.id
            self._record_config_activity(agent, changed, base.id, version.id, user_id=user_id)

        agent.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def restore_version(self, agent_id: str, version_id: str, *, user_id: str | None = None) -> Agent:
        """Create a NEW AgentVersion that copies a prior version's config, then set it current.

        The selected old version is never mutated or reactivated; a fresh immutable
        version is appended (preserving full history), satisfying the append-only model.
        """
        from .version_service import AgentVersionService

        agent = self.get_or_404(agent_id)
        version_svc = AgentVersionService(self.db)
        source = version_svc.get_version_for_agent(version_id, agent.id, agent.space_id)

        new = {
            "model_provider_id": source.model_provider_id,
            "model_name": source.model_name,
            "runtime_adapter_id": source.runtime_adapter_id,
            "system_prompt": source.system_prompt,
            "model_config_json": dict(source.model_config_json or DEFAULT_MODEL_CONFIG),
            "runtime_config_json": dict(source.runtime_config_json or DEFAULT_RUNTIME_POLICY),
            "context_policy_json": dict(source.context_policy_json or {}),
            "memory_policy_json": dict(source.memory_policy_json or DEFAULT_MEMORY_POLICY),
            "capabilities_json": list(source.capabilities_json or []),
            "tool_permissions_json": dict(source.tool_permissions_json or {}),
            "runtime_policy_json": dict(source.runtime_policy_json or DEFAULT_RUNTIME_POLICY),
            "tool_policy_json": dict(source.tool_policy_json or {}),
            "output_policy_json": dict(source.output_policy_json or {}),
            "schedule_config_json": dict(source.schedule_config_json or {}),
            "output_schema_json": dict(source.output_schema_json or {}),
        }
        version = version_svc.create(
            agent_id=agent.id, space_id=agent.space_id, data=AgentVersionCreate(**new),
        )
        agent.current_version_id = version.id
        self._record_config_activity(
            agent, [f"restore_from:{source.version_label}"], source.id, version.id, user_id=user_id
        )
        agent.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def _record_config_activity(
        self, agent: Agent, changed: list[str], base_version_id: str, new_version_id: str, *, user_id: str | None
    ) -> None:
        from ..activity import ActivityService

        try:
            ActivityService(self.db).create(
                space_id=agent.space_id,
                source_type="system_event",
                content=f"Agent '{agent.name}' configuration updated: {', '.join(sorted(changed))}.",
                user_id=user_id,
                agent_id=agent.id,
                title="Agent configuration updated",
                metadata_json={
                    "kind": "agent_config_updated",
                    "agent_id": agent.id,
                    "changed_fields": sorted(changed),
                    "base_version_id": base_version_id,
                    "new_version_id": new_version_id,
                },
            )
        except Exception:
            log.warning("agent config update activity record failed for agent=%s", agent.id, exc_info=True)

    def create_config_update_proposal(
        self,
        agent_id: str,
        data: AgentConfigProposalCreate,
        *,
        user_id: str,
    ):
        from ..proposals import ProposalService

        agent = self.get_or_404(agent_id)
        base = self.db.query(AgentVersion).filter(
            AgentVersion.id == data.base_version_id,
            AgentVersion.agent_id == agent.id,
            AgentVersion.space_id == agent.space_id,
        ).first()
        if base is None:
            raise HTTPException(status_code=404, detail="base AgentVersion not found for this agent")

        raw = data.model_dump(exclude_unset=True)
        raw.pop("base_version_id", None)
        changes = {k: v for k, v in raw.items()}
        if not changes:
            raise HTTPException(status_code=422, detail="No agent configuration changes provided")

        provider_id = changes.get("model_provider_id", base.model_provider_id)
        model_name = changes.get("model_name", base.model_name)
        if model_name and not provider_id:
            raise HTTPException(status_code=400, detail="model_provider_id is required when model_name is set")
        if provider_id:
            self._validate_model_provider(provider_id, agent.space_id)

        runtime_adapter_id = changes.get("runtime_adapter_id")
        if runtime_adapter_id:
            from ..models import RuntimeAdapter

            adapter = self.db.query(RuntimeAdapter).filter(
                RuntimeAdapter.id == runtime_adapter_id,
                RuntimeAdapter.space_id == agent.space_id,
            ).first()
            if adapter is None:
                raise HTTPException(status_code=400, detail="runtime_adapter_id does not belong to this space")

        payload = {
            "agent_id": agent.id,
            "base_version_id": data.base_version_id,
            "changes": changes,
        }
        changed_fields = sorted(changes)
        return ProposalService(self.db).create_user_proposal(
            space_id=agent.space_id,
            user_id=user_id,
            proposal_type="agent_config_update",
            title=f"Update agent config: {agent.name}",
            payload_json=payload,
            rationale="Agent configuration update requested via public API.",
            risk_level="high",
            urgency="normal",
            policy_action="agent.config_update",
            policy_resource_type="agent",
            policy_resource_id=agent.id,
            policy_context={
                "agent_id": agent.id,
                "agent_status": agent.status,
                "base_version_id": data.base_version_id,
                "changed_fields": changed_fields,
            },
            policy_metadata_json={
                "agent_id": agent.id,
                "base_version_id": data.base_version_id,
                "changed_fields": changed_fields,
                "model_provider_id": provider_id,
                "runtime_adapter_id": changes.get("runtime_adapter_id"),
            },
        )

    def delete(self, agent_id: str) -> bool:
        agent = self.get(agent_id)
        if not agent:
            return False
        agent.status = "archived"
        self.db.commit()
        return True

    def get_current_version(self, agent_id: str) -> AgentVersion | None:
        from .version_service import AgentVersionService
        agent = self.get_or_404(agent_id)
        if not agent.current_version_id:
            return None
        return AgentVersionService(self.db).get_or_404(agent.current_version_id)

    def create_version(
        self, agent_id: str, data: AgentVersionCreate, label: str | None = None
    ) -> AgentVersion:
        from .version_service import AgentVersionService
        agent = self.get_or_404(agent_id)
        version_svc = AgentVersionService(self.db)
        version = version_svc.create(
            agent_id=agent.id,
            space_id=agent.space_id,
            data=data,
            label=label,
        )
        agent.current_version_id = version.id
        agent.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(agent)
        return version

    # ------------------------------------------------------------------
    # Policy checks
    # ------------------------------------------------------------------

    def _get_policy_fields(self, agent: Agent) -> tuple[dict, dict]:
        memory_policy = DEFAULT_MEMORY_POLICY.copy()
        runtime_policy = DEFAULT_RUNTIME_POLICY.copy()

        if agent.current_version_id:
            version = self.db.query(AgentVersion).filter(
                AgentVersion.id == agent.current_version_id
            ).first()
            if version:
                memory_policy = version.memory_policy_json or memory_policy
                runtime_policy = version.runtime_policy_json or runtime_policy

        return memory_policy, runtime_policy

    def _check_run(self, agent: Agent, adapter_type: str, space_id: str) -> tuple:
        """Non-mutating preflight checks before creating a queued run.

        Uses PolicyEngine directly (no PolicyDecisionRecord persisted here).
        Real enforcement with PolicyGateway.enforce runs in RunExecutionService.
        """
        from ..policy import PolicyEngine

        engine = PolicyEngine()

        d = engine.check({
            "action": "runtime.execute",
            "space_id": space_id,
            "resource_space_id": agent.space_id,
            "agent_status": agent.status,
        })
        if d.denied:
            raise HTTPException(status_code=409, detail=d.message)

        _, runtime_policy = self._get_policy_fields(agent)
        allowed = runtime_policy.get("allowed_adapter_types")
        d = engine.check({
            "action": "runtime.execute",
            "space_id": space_id,
            "tool_name": adapter_type,
            "agent_tool_permissions": allowed,
        })
        if d.denied:
            raise HTTPException(status_code=403, detail=d.message)

        memory_policy, _ = self._get_policy_fields(agent)
        return d, memory_policy, runtime_policy

    # ------------------------------------------------------------------
    # Task routing
    # ------------------------------------------------------------------

    def _resolve_adapter_type(self, req: RunRequest) -> str:
        decision = _get_router_service().route_task(
            requested_adapter=req.adapter_type,
            task_type=req.task_type,
            risk_level=req.risk_level,
            requires_filesystem=req.requires_filesystem,
            requires_terminal=req.requires_terminal,
            requires_git=req.requires_git,
            requires_long_reasoning=req.requires_long_reasoning,
        )
        return decision.adapter_type

    # ------------------------------------------------------------------
    # Run creation via RunService (canonical path)
    # No adapter execution here (handled by RunExecutionService)
    # ------------------------------------------------------------------

    def run(
        self,
        agent_id: str,
        req: RunRequest,
        space_id: str,
        instructed_by_user_id: str | None = None,
    ) -> Run:
        """
        Create a Run for a user→agent request.
        Returns a queued Run via RunService. No adapter execution here.
        """
        from app.runs import RunService

        adapter_type = self._resolve_adapter_type(req)
        agent = self.get_or_404(agent_id)
        self._check_run(agent, adapter_type, space_id)

        if instructed_by_user_id is None:
            raise HTTPException(
                status_code=400,
                detail="run dispatch requires instructed_by_user_id (the authenticated user)",
            )
        user_id = instructed_by_user_id

        run_svc = RunService(self.db)
        run = run_svc.create_run(
            agent_id=agent_id,
            data=RunCreate(
                mode="live",
                run_type="agent",
                trigger_origin="manual",
                workspace_id=req.workspace_id,
                adapter_type=adapter_type,
                prompt=req.prompt,
            ),
            space_id=space_id,
            user_id=user_id,
        )

        # instructed_by_user_id must be set explicitly; RunCreate.user_id is the canonical source.
        run.instructed_by_user_id = user_id
        self.db.commit()
        return run

    # ------------------------------------------------------------------
    # Async submit — creates a queued Run for BackgroundTask dispatch
    # ------------------------------------------------------------------

    def submit(
        self,
        agent_id: str,
        req: RunRequest,
        space_id: str,
        instructed_by_user_id: str | None = None,
    ) -> Run:
        """
        Create a Run for an async HTTP request.
        Returns a queued Run via RunService. No adapter execution here.
        """
        from app.runs import RunService

        adapter_type = self._resolve_adapter_type(req)
        agent = self.get_or_404(agent_id)
        self._check_run(agent, adapter_type, space_id)

        if instructed_by_user_id is None:
            raise HTTPException(
                status_code=400,
                detail="run dispatch requires instructed_by_user_id (the authenticated user)",
            )
        user_id = instructed_by_user_id

        run_svc = RunService(self.db)
        run = run_svc.create_run(
            agent_id=agent_id,
            data=RunCreate(
                mode="live",
                run_type="agent",
                trigger_origin="manual",
                workspace_id=req.workspace_id,
                adapter_type=adapter_type,
                prompt=req.prompt,
            ),
            space_id=space_id,
            user_id=user_id,
        )

        run.instructed_by_user_id = user_id
        self.db.commit()
        return run
