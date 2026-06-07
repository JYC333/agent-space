from __future__ import annotations
"""
ProposalApplyService — the single durable write boundary for accepted proposals.

All normal durable writes to MemoryEntry (create, version, archive), Policy,
and Task must flow through this service after proposal acceptance.

Supported proposal types
------------------------
  memory_create   — create a new active MemoryEntry
  memory_update   — append-only version: create new row, mark old as superseded
  memory_archive  — mark MemoryEntry status=archived (no hard delete)
  policy_change   — create a new Policy version (optionally superseding an old one)
  code_patch      — delegated back to CodePatchProposalApplier (file writes, not memory)
  egress_review   — metadata-only grant egress review marker
  follow_up_task  — create a Task row from an accepted follow-up task proposal
  agent_config_update — create a new AgentVersion and advance the Agent pointer
  knowledge_create — create an active KnowledgeItem
  knowledge_update — append-only KnowledgeItem version update
  knowledge_archive — archive a KnowledgeItem
  knowledge_relation_create — create a same-space KnowledgeItemRelation
  knowledge_relation_delete — archive a KnowledgeItemRelation

Callers
-------
  ProposalService.accept() is the only entry point from the public API surface.
  Tests may call ProposalApplyService.apply() directly with a persisted Proposal.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..models import (
    ActivityRecord,
    AgentVersion,
    CapabilityOverlay,
    CapabilityVersion,
    KnowledgeItem,
    KnowledgeItemRelation,
    MemoryEntry,
    Policy,
    Proposal,
    ProvenanceLink,
    Task,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProposalApplyError(Exception):
    """Raised when a well-formed proposal cannot be applied (e.g. missing target)."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MemoryApplyResult:
    memory: MemoryEntry
    superseded_memory_id: Optional[str] = None


@dataclass
class PolicyApplyResult:
    policy: Policy
    superseded_policy_id: Optional[str] = None


@dataclass
class ApplyResult:
    """Unified result from ProposalApplyService.apply()."""

    proposal: Proposal
    memory: Optional[MemoryEntry] = None
    policy: Optional[Policy] = None
    updated_paths: Optional[list[str]] = None
    code_patch_files: Optional[list[dict[str, Any]]] = None
    code_patch_transaction: Optional[Any] = None
    egress_review: bool = False
    task: Optional[Task] = None
    agent_version: Optional[AgentVersion] = None
    capability_version: Optional[CapabilityVersion] = None
    capability_overlay: Optional[CapabilityOverlay] = None
    knowledge_item: Optional[KnowledgeItem] = None
    knowledge_relation: Optional[KnowledgeItemRelation] = None


def _validate_grant_egress_approval_or_raise(db: Session, proposal: Proposal) -> None:
    from ..proposals.approvals import (
        PersonalMemoryEgressApprovalError,
        validate_egress_granting_user_approval,
    )

    try:
        validate_egress_granting_user_approval(db, proposal=proposal)
    except PersonalMemoryEgressApprovalError as exc:
        raise ProposalApplyError(str(exc)) from exc


def _has_grant_egress_approval(db: Session, proposal: Proposal) -> bool:
    from ..proposals.approvals import (
        PersonalMemoryEgressApprovalError,
        validate_egress_granting_user_approval,
    )

    try:
        validate_egress_granting_user_approval(db, proposal=proposal)
    except PersonalMemoryEgressApprovalError:
        return False
    return True


def _prov_row_key(pl: ProvenanceLink) -> tuple[str, str, str | None]:
    return (pl.source_type, pl.source_id, pl.source_trust)


def _prov_dict_key(e: dict[str, Any]) -> tuple[str, str, str | None] | None:
    st = e.get("source_type")
    sid = e.get("source_id")
    if not isinstance(st, str) or not isinstance(sid, str):
        return None
    tr = e.get("source_trust") if isinstance(e.get("source_trust"), str) else None
    return (st, sid, tr)


# ---------------------------------------------------------------------------
# MemoryProposalApplier
# ---------------------------------------------------------------------------


class MemoryProposalApplier:
    """Apply memory_create / memory_update / memory_archive proposals.

    All writes go through MemoryInternalWriter — never through public API paths.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def apply_create(self, proposal: Proposal, *, user_id: str) -> MemoryApplyResult:
        from ..schemas import MemoryCreate
        from .internal_writer import MemoryInternalWriter
        from .proposal_payload import (
            dominant_source_trust,
            first_activity_id,
            proposal_provenance_entry,
            provenance_entries_from_payload,
        )
        from .provenance_apply import TARGET_MEMORY, write_provenance_links

        # Defense-in-depth: if the source run has personal grant context,
        # block direct apply of memory proposals targeting non-personal spaces.
        source_run_id = (proposal.payload_json or {}).get("source_run_id") or proposal.created_by_run_id
        if source_run_id:
            from ..models import Run
            from ..personal_memory_grants.egress_guard import (
                EgressDecision,
                PersonalMemoryEgressError,
                check_personal_memory_egress,
            )
            source_run = self._db.query(Run).filter(Run.id == source_run_id).first()
            if source_run is not None:
                egress = check_personal_memory_egress(
                    self._db,
                    run=source_run,
                    target_space_id=proposal.space_id,
                    target_object_type="memory",
                    operation="proposal_apply_create",
                )
                if egress.decision == EgressDecision.BLOCK and not _has_grant_egress_approval(self._db, proposal):
                    raise PersonalMemoryEgressError(egress.reason, grant_id=egress.grant_id)

        payload = proposal.payload_json or {}
        vis = (payload.get("target_visibility") or payload.get("visibility") or "space_shared").lower()
        sens = (payload.get("sensitivity_level") or "normal").lower()
        content = payload.get("proposed_content") or payload.get("content") or ""
        mem_type = payload.get("memory_type") or "semantic"
        scope = payload.get("target_scope") or payload.get("scope_type") or "user"
        namespace = payload.get("target_namespace") or payload.get("namespace") or "user.default"

        entries = provenance_entries_from_payload(payload)
        dom_trust = dominant_source_trust(entries)
        act_id = first_activity_id(entries)

        mem_data = MemoryCreate(
            title=proposal.title or "",
            content=content,
            type=mem_type,
            scope=scope,
            namespace=namespace,
            space_id=proposal.space_id,
            visibility=vis,
            sensitivity_level=sens,
            owner_user_id=payload.get("owner_user_id"),
            subject_user_id=payload.get("subject_user_id"),
            selected_user_ids=payload.get("selected_user_ids"),
            workspace_id=proposal.workspace_id,
            source_proposal_id=proposal.id,
            memory_layer=payload.get("target_layer") or payload.get("memory_layer"),
            memory_kind=payload.get("memory_kind"),
        )

        writer = MemoryInternalWriter(self._db)
        mem = writer.create_from_approved_proposal(
            proposal,
            mem_data,
            acting_user_id=user_id,
            created_by=str(proposal.created_by_user_id or user_id),
            approved_by=str(user_id),
            source_trust=dom_trust,
            source_activity_id=act_id,
        )

        link_entries: list[dict[str, Any]] = list(entries)
        link_entries.append(
            proposal_provenance_entry(
                proposal_id=proposal.id,
                evidence={"proposal_type": proposal.proposal_type},
            )
        )
        write_provenance_links(
            self._db,
            space_id=proposal.space_id,
            target_type=TARGET_MEMORY,
            target_id=mem.id,
            entries=link_entries,
        )
        self._db.flush()
        return MemoryApplyResult(memory=mem)

    def apply_update(self, proposal: Proposal, *, user_id: str) -> MemoryApplyResult:
        """Create a new versioned MemoryEntry; mark old row status='superseded'."""
        from ..schemas import MemoryCreate
        from .internal_writer import MemoryInternalWriter
        from .proposal_payload import (
            dominant_source_trust,
            first_activity_id,
            proposal_provenance_entry,
            provenance_entries_from_payload,
        )
        from .provenance_apply import (
            TARGET_MEMORY,
            copy_provenance_to_memory,
            record_memory_supersedes_relation,
            write_provenance_links,
        )

        # Defense-in-depth: if the source run has personal grant context,
        # block direct apply of memory update proposals targeting non-personal spaces.
        source_run_id = (proposal.payload_json or {}).get("source_run_id") or proposal.created_by_run_id
        if source_run_id:
            from ..models import Run
            from ..personal_memory_grants.egress_guard import (
                EgressDecision,
                PersonalMemoryEgressError,
                check_personal_memory_egress,
            )
            source_run = self._db.query(Run).filter(Run.id == source_run_id).first()
            if source_run is not None:
                egress = check_personal_memory_egress(
                    self._db,
                    run=source_run,
                    target_space_id=proposal.space_id,
                    target_object_type="memory",
                    operation="proposal_apply_update",
                )
                if egress.decision == EgressDecision.BLOCK and not _has_grant_egress_approval(self._db, proposal):
                    raise PersonalMemoryEgressError(egress.reason, grant_id=egress.grant_id)

        payload = proposal.payload_json or {}
        target_id = payload.get("target_memory_id")
        if not target_id:
            raise ProposalApplyError(
                "memory_update proposal is missing target_memory_id in payload"
            )

        writer = MemoryInternalWriter(self._db)
        old_mem = writer.get_active(target_id, proposal.space_id)
        if old_mem is None:
            raise ProposalApplyError(
                f"target memory {target_id!r} not found or not active in space {proposal.space_id!r}"
            )

        vis = (
            payload.get("target_visibility")
            or payload.get("visibility")
            or old_mem.visibility
        ).lower()
        sens = (payload.get("sensitivity_level") or old_mem.sensitivity_level or "normal").lower()
        new_content = (
            payload.get("proposed_content")
            or payload.get("content")
            or old_mem.content
        )
        new_title = (
            payload.get("proposed_title")
            or payload.get("title")
            or old_mem.title
            or ""
        )
        scope = payload.get("target_scope") or old_mem.scope_type
        namespace = payload.get("target_namespace") or old_mem.namespace or "user.default"
        mem_type = payload.get("memory_type") or old_mem.memory_type

        mem_data = MemoryCreate(
            title=new_title,
            content=new_content,
            type=mem_type,
            scope=scope,
            namespace=namespace,
            space_id=proposal.space_id,
            visibility=vis,
            sensitivity_level=sens,
            owner_user_id=payload.get("owner_user_id") or old_mem.owner_user_id,
            subject_user_id=payload.get("subject_user_id") or old_mem.subject_user_id,
            selected_user_ids=payload.get("selected_user_ids") or old_mem.selected_user_ids,
            workspace_id=proposal.workspace_id or old_mem.workspace_id,
            source_proposal_id=proposal.id,
            memory_layer=payload.get("target_layer") or payload.get("memory_layer") or old_mem.memory_layer,
            memory_kind=payload.get("memory_kind") or old_mem.memory_kind,
        )

        root_id = old_mem.root_memory_id or old_mem.id

        entries = provenance_entries_from_payload(payload)

        dom_trust = dominant_source_trust(entries) or old_mem.source_trust
        act_id = first_activity_id(entries) or old_mem.source_activity_id

        new_mem = writer.create_from_approved_proposal(
            proposal,
            mem_data,
            acting_user_id=user_id,
            created_by=str(proposal.created_by_user_id or user_id),
            approved_by=str(user_id),
            root_memory_id=root_id,
            supersedes_memory_id=old_mem.id,
            source_trust=dom_trust,
            source_activity_id=act_id,
        )

        writer.mark_status_from_approved_proposal(proposal, old_mem.id, "superseded")

        copy_provenance_to_memory(
            self._db,
            space_id=proposal.space_id,
            from_memory_id=old_mem.id,
            to_memory_id=new_mem.id,
        )

        existing = {
            _prov_row_key(pl)
            for pl in self._db.query(ProvenanceLink)
            .filter(
                ProvenanceLink.space_id == proposal.space_id,
                ProvenanceLink.target_type == TARGET_MEMORY,
                ProvenanceLink.target_id == new_mem.id,
            )
            .all()
        }
        to_add: list[dict[str, Any]] = []
        for e in provenance_entries_from_payload(payload):
            k = _prov_dict_key(e)
            if k and k not in existing:
                to_add.append(e)
                existing.add(k)
        prop_e = proposal_provenance_entry(
            proposal_id=proposal.id,
            evidence={"proposal_type": "memory_update"},
        )
        pk = _prov_dict_key(prop_e)
        if pk and pk not in existing:
            to_add.append(prop_e)
        if to_add:
            write_provenance_links(
                self._db,
                space_id=proposal.space_id,
                target_type=TARGET_MEMORY,
                target_id=new_mem.id,
                entries=to_add,
            )

        record_memory_supersedes_relation(
            self._db,
            space_id=proposal.space_id,
            new_memory_id=new_mem.id,
            old_memory_id=old_mem.id,
            proposal_id=proposal.id,
        )
        self._db.flush()
        return MemoryApplyResult(memory=new_mem, superseded_memory_id=old_mem.id)

    def apply_archive(self, proposal: Proposal, *, user_id: str) -> MemoryApplyResult:
        """Mark the target MemoryEntry status='archived'.  Never hard-deletes."""
        from .internal_writer import MemoryInternalWriter
        from .proposal_payload import merge_distinct_provenance_entries, proposal_provenance_entry
        from .proposal_payload import provenance_entries_from_payload
        from .provenance_apply import TARGET_MEMORY, write_provenance_links

        payload = proposal.payload_json or {}
        target_id = payload.get("target_memory_id")
        if not target_id:
            raise ProposalApplyError(
                "memory_archive proposal is missing target_memory_id in payload"
            )

        writer = MemoryInternalWriter(self._db)
        mem = writer.get_active(target_id, proposal.space_id)
        if mem is None:
            raise ProposalApplyError(
                f"target memory {target_id!r} not found or not active in space {proposal.space_id!r}"
            )

        writer.mark_status_from_approved_proposal(proposal, mem.id, "archived")
        self._db.refresh(mem)

        entries = merge_distinct_provenance_entries(
            provenance_entries_from_payload(payload),
            [
                proposal_provenance_entry(
                    proposal_id=proposal.id,
                    evidence={"action": "memory_archive", "proposal_type": "memory_archive"},
                )
            ],
        )
        if entries:
            write_provenance_links(
                self._db,
                space_id=proposal.space_id,
                target_type=TARGET_MEMORY,
                target_id=mem.id,
                entries=entries,
            )
            self._db.flush()
        return MemoryApplyResult(memory=mem)


# ---------------------------------------------------------------------------
# PolicyProposalApplier
# ---------------------------------------------------------------------------


class PolicyProposalApplier:
    """Apply policy_change proposals.

    Always creates a new Policy row.  When target_policy_id is provided the old
    row is marked 'superseded'.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def apply(self, proposal: Proposal, *, user_id: str) -> PolicyApplyResult:
        from .internal_writer import PolicyInternalWriter
        from .proposal_payload import merge_distinct_provenance_entries, proposal_provenance_entry
        from .proposal_payload import provenance_entries_from_payload
        from .provenance_apply import TARGET_POLICY, write_provenance_links
        from ..policy.roles import get_space_role_normalized

        # policy.change is WIRED_VIA_PROPOSAL: enforcement is via proposal.apply gate only.
        # The role check below is the proposal-type authority guard.
        _role = get_space_role_normalized(self._db, user_id=user_id, space_id=proposal.space_id)
        if _role not in ("admin", "owner"):
            raise ProposalApplyError(
                f"policy.change requires admin or owner authority; "
                f"user {user_id!r} has role {_role!r} in space {proposal.space_id!r}"
            )

        payload = proposal.payload_json or {}
        from ..policy.effects import PolicyEffectValidationError, validate_policy_change_payload

        try:
            normalized_payload = validate_policy_change_payload(payload)
        except PolicyEffectValidationError as exc:
            raise ProposalApplyError(str(exc)) from exc

        writer = PolicyInternalWriter(self._db)
        superseded_id: Optional[str] = None

        target_id = payload.get("target_policy_id")
        if target_id:
            old = writer.mark_superseded(target_id, proposal.space_id, commit=False)
            if old is not None:
                superseded_id = old.id

        rule_json: Optional[dict] = normalized_payload.rule_json
        if rule_json is None and proposal.proposed_content:
            rule_json = {"content": proposal.proposed_content}

        domain = normalized_payload.domain
        name = proposal.title or "Policy from proposal"

        new_policy = writer.create(
            space_id=proposal.space_id,
            name=name,
            domain=domain,
            policy_key=payload.get("policy_key"),
            policy_version=payload.get("policy_version") or 1,
            status="active",
            enforcement_mode=normalized_payload.enforcement_mode,
            priority=payload.get("priority") or 0,
            rule_json=rule_json,
            applies_to_json=normalized_payload.applies_to_json,
            supersedes_policy_id=superseded_id or payload.get("supersedes_policy_id"),
            created_from_proposal_id=proposal.id,
            commit=False,
        )

        entries = merge_distinct_provenance_entries(
            provenance_entries_from_payload(payload),
            [
                proposal_provenance_entry(
                    proposal_id=proposal.id,
                    evidence={"proposal_type": "policy_change"},
                )
            ],
        )
        write_provenance_links(
            self._db,
            space_id=proposal.space_id,
            target_type=TARGET_POLICY,
            target_id=new_policy.id,
            entries=entries,
        )
        self._db.flush()
        return PolicyApplyResult(policy=new_policy, superseded_policy_id=superseded_id)


# ---------------------------------------------------------------------------
# FollowUpTaskProposalApplier
# ---------------------------------------------------------------------------


class FollowUpTaskProposalApplier:
    """Apply follow_up_task proposals by creating exactly one Task row.

    Never writes MemoryEntry, Policy, RunReflection, or any other learning object.
    Workspace cross-space safety is verified before any write.
    """

    # Allowed top-level payload keys; anything else is rejected.
    # "reflection_id" and "provenance_entries" are provenance fields set by
    # ReflectionProposalBuilder and the general proposal system respectively.
    _ALLOWED_TOPLEVEL: frozenset[str] = frozenset({"task", "reflection_id", "provenance_entries"})

    _ALLOWED_TASK_FIELDS: frozenset[str] = frozenset({
        "title",
        "description",
        "task_type",
        "priority",
        "risk_level",
        "acceptance_criteria_json",
        "required_outputs_json",
        "tags",
        "metadata_json",
    })

    _VALID_PRIORITIES: frozenset[str] = frozenset({"low", "normal", "high", "urgent"})
    _VALID_RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high", "critical"})
    _VALID_VISIBILITIES: frozenset[str] = frozenset({
        "private", "space_shared", "workspace_shared", "restricted", "public_template"
    })

    def __init__(self, db: Session) -> None:
        self._db = db

    def apply(self, proposal: Proposal, *, user_id: str) -> Task:
        """Validate payload and create exactly one Task row.  Returns the Task ORM object."""
        from ..models import Workspace

        payload = proposal.payload_json or {}

        if not isinstance(payload, dict):
            raise ProposalApplyError("follow_up_task payload_json must be a dict")

        unknown_toplevel = set(payload.keys()) - self._ALLOWED_TOPLEVEL
        if unknown_toplevel:
            raise ProposalApplyError(
                f"follow_up_task payload has unknown top-level fields: {sorted(unknown_toplevel)}"
            )

        task_data = payload.get("task")
        if task_data is None:
            raise ProposalApplyError("follow_up_task payload_json is missing required 'task' field")
        if not isinstance(task_data, dict):
            raise ProposalApplyError("follow_up_task payload_json['task'] must be a dict")

        unknown_task = set(task_data.keys()) - self._ALLOWED_TASK_FIELDS
        if unknown_task:
            raise ProposalApplyError(
                f"follow_up_task task has unknown fields: {sorted(unknown_task)}"
            )

        title = task_data.get("title")
        if title is None:
            raise ProposalApplyError("follow_up_task task.title is required")
        if not isinstance(title, str):
            raise ProposalApplyError("follow_up_task task.title must be a string")
        title = title.strip()
        if not title:
            raise ProposalApplyError("follow_up_task task.title must not be blank")

        description = task_data.get("description")
        if description is not None and not isinstance(description, str):
            raise ProposalApplyError("follow_up_task task.description must be a string if provided")

        task_type = task_data.get("task_type")
        if task_type is not None:
            if not isinstance(task_type, str) or not task_type.strip():
                raise ProposalApplyError(
                    "follow_up_task task.task_type must be a non-empty string if provided"
                )
            task_type = task_type.strip()
        task_type = task_type or "general"

        priority = task_data.get("priority")
        if priority is not None and priority not in self._VALID_PRIORITIES:
            raise ProposalApplyError(
                f"follow_up_task task.priority must be one of {sorted(self._VALID_PRIORITIES)}, "
                f"got {priority!r}"
            )
        priority = priority or "normal"

        risk_level = task_data.get("risk_level")
        if risk_level is not None and risk_level not in self._VALID_RISK_LEVELS:
            raise ProposalApplyError(
                f"follow_up_task task.risk_level must be one of {sorted(self._VALID_RISK_LEVELS)}, "
                f"got {risk_level!r}"
            )
        risk_level = risk_level or "low"

        acceptance_criteria = task_data.get("acceptance_criteria_json")
        if acceptance_criteria is not None and not isinstance(acceptance_criteria, dict):
            raise ProposalApplyError(
                "follow_up_task task.acceptance_criteria_json must be a dict if provided"
            )

        required_outputs = task_data.get("required_outputs_json")
        if required_outputs is not None and not isinstance(required_outputs, list):
            raise ProposalApplyError(
                "follow_up_task task.required_outputs_json must be a list if provided"
            )

        tags = task_data.get("tags")
        if tags is not None:
            if not isinstance(tags, list):
                raise ProposalApplyError("follow_up_task task.tags must be a list if provided")
            if not all(isinstance(t, str) for t in tags):
                raise ProposalApplyError("follow_up_task task.tags must be a list of strings")

        extra_metadata = task_data.get("metadata_json")
        if extra_metadata is not None and not isinstance(extra_metadata, dict):
            raise ProposalApplyError(
                "follow_up_task task.metadata_json must be a dict if provided"
            )

        # Workspace cross-space safety: verify the workspace belongs to this space.
        workspace_id = proposal.workspace_id
        if workspace_id:
            ws = (
                self._db.query(Workspace)
                .filter(
                    Workspace.id == workspace_id,
                    Workspace.space_id == proposal.space_id,
                )
                .first()
            )
            if ws is None:
                raise ProposalApplyError(
                    f"workspace {workspace_id!r} not found in space {proposal.space_id!r}"
                )

        # Visibility inherits from the proposal when valid; otherwise defaults to space_shared.
        proposal_vis = getattr(proposal, "visibility", None) or "space_shared"
        visibility = proposal_vis if proposal_vis in self._VALID_VISIBILITIES else "space_shared"

        # Merge caller metadata under standardised provenance keys.
        reflection_id = payload.get("reflection_id")
        merged_meta: dict[str, Any] = dict(extra_metadata or {})
        merged_meta.update({
            "source": "follow_up_task_proposal",
            "proposal_id": proposal.id,
            "created_from_proposal_type": "follow_up_task",
        })
        if reflection_id:
            merged_meta["reflection_id"] = reflection_id

        task_row = Task(
            space_id=proposal.space_id,
            workspace_id=workspace_id,
            title=title,
            description=description,
            task_type=task_type,
            status="inbox",
            priority=priority,
            risk_level=risk_level,
            visibility=visibility,
            created_by_user_id=user_id,
            source_proposal_id=proposal.id,
            source_run_id=proposal.created_by_run_id,
            acceptance_criteria_json=acceptance_criteria,
            required_outputs_json=required_outputs,
            tags=tags,
            metadata_json=merged_meta,
        )
        self._db.add(task_row)
        self._db.flush()
        return task_row


# ---------------------------------------------------------------------------
# ProposalApplyService — central dispatch
# ---------------------------------------------------------------------------


from ..policy.proposal_apply import SUPPORTED_PROPOSAL_TYPES as _SUPPORTED_TYPES


class ProposalApplyService:
    """Single durable write boundary for accepted proposals.

    Callers must validate proposal state (pending, not preview, correct space/user)
    *before* calling apply().  This service assumes the proposal is already
    validated and ready to be applied.

    **Source monitoring parameters** — ``bypass_source_monitoring`` and
    ``accept_context`` are *not* part of any public REST contract. They are only
    set by trusted in-process code (``ProposalService.accept`` sets
    ``accept_context="explicit_user_accept"``; tests/seeds may pass
    ``internal_seed`` or ``bypass_source_monitoring=True``). No route handler or
    agent tool should forward client-controlled values into ``apply``.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._memory_applier = MemoryProposalApplier(db)
        self._policy_applier = PolicyProposalApplier(db)
        self._follow_up_task_applier = FollowUpTaskProposalApplier(db)
        from ..knowledge.service import KnowledgeProposalApplier
        self._knowledge_applier = KnowledgeProposalApplier(db)

    @staticmethod
    def supported_types() -> frozenset[str]:
        return _SUPPORTED_TYPES

    def _apply_agent_config_update(self, proposal: Proposal, *, user_id: str) -> AgentVersion:
        from ..agents.version_service import AgentVersionService
        from ..models import Agent, ModelProvider, RuntimeAdapter
        from ..schemas import AgentVersionCreate, DEFAULT_MEMORY_POLICY, DEFAULT_MODEL_CONFIG, DEFAULT_RUNTIME_POLICY

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
            self._db.query(Agent)
            .filter(Agent.id == agent_id, Agent.space_id == proposal.space_id)
            .first()
        )
        if agent is None:
            raise ProposalApplyError("agent not found for config proposal")
        if agent.current_version_id != base_version_id:
            raise ProposalApplyError("stale agent_config_update proposal: base_version_id is not current")

        base = AgentVersionService(self._db).get_version_for_agent(
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
                self._db.query(ModelProvider)
                .filter(ModelProvider.id == provider_id, ModelProvider.space_id == proposal.space_id)
                .first()
            )
            if provider is None:
                raise ProposalApplyError("model_provider_id does not belong to this space")

        runtime_adapter_id = version_dict.get("runtime_adapter_id")
        if runtime_adapter_id:
            adapter = (
                self._db.query(RuntimeAdapter)
                .filter(RuntimeAdapter.id == runtime_adapter_id, RuntimeAdapter.space_id == proposal.space_id)
                .first()
            )
            if adapter is None:
                raise ProposalApplyError("runtime_adapter_id does not belong to this space")

        existing_labels = [
            row[0]
            for row in (
                self._db.query(AgentVersion.version_label)
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
        self._db.add(new_version)
        self._db.flush()
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
        self._db.add(activity)
        self._db.flush()
        new_version.source_activity_id = activity.id
        payload_with_result = dict(proposal.payload_json or {})
        payload_with_result["resulting_agent_version_id"] = new_version.id
        payload_with_result["source_activity_id"] = activity.id
        proposal.payload_json = payload_with_result
        flag_modified(proposal, "payload_json")
        agent.current_version_id = new_version.id
        agent.updated_at = datetime.now(UTC)
        return new_version

    def _enforce_source_monitoring(
        self,
        proposal: Proposal,
        *,
        accept_context: str,
        bypass_source_monitoring: bool,
    ) -> None:
        if bypass_source_monitoring:
            return
        from .source_monitoring import SourceMonitoringService, monitoring_snapshot

        monitor = SourceMonitoringService()
        payload = proposal.payload_json or {}
        ptype = proposal.proposal_type
        if ptype == "policy_change":
            out = monitor.evaluate_policy_proposal(payload=payload, accept_context=accept_context)  # type: ignore[arg-type]
        elif ptype in ("memory_create", "memory_update", "memory_archive"):
            out = monitor.evaluate_memory_proposal(
                proposal_type=ptype,
                payload=payload,
                accept_context=accept_context,  # type: ignore[arg-type]
            )
        elif ptype in {
            "knowledge_create",
            "knowledge_update",
            "knowledge_archive",
            "knowledge_relation_create",
            "knowledge_relation_delete",
        }:
            # TODO: Knowledge source monitoring. External or otherwise
            # untrusted Activity/Artifact-derived Knowledge still needs a
            # dedicated review evaluator. This branch documents the boundary;
            # returning here does not mean those sources are intrinsically safe.
            return
        else:
            return

        if out.action == "reject":
            raise ProposalApplyError(out.message)

        if out.action == "require_review":
            if accept_context != "explicit_user_accept":
                raise ProposalApplyError(out.message)
            merged = dict(payload)
            merged["source_monitoring_result"] = {
                **monitoring_snapshot(out),
                "explicit_approval_context": accept_context,
            }
            proposal.payload_json = merged
            flag_modified(proposal, "payload_json")
            self._db.flush()

    def _enforce_personal_memory_egress_approval(self, proposal: Proposal) -> None:
        from ..models import Space
        from ..proposals.approvals import (
            PersonalMemoryEgressApprovalError,
            is_grant_derived_proposal,
            validate_egress_granting_user_approval,
        )

        if not is_grant_derived_proposal(self._db, proposal):
            return

        target = self._db.query(Space).filter(Space.id == proposal.space_id).first()
        target_is_non_personal = target is None or target.type != "personal"
        if proposal.proposal_type != "egress_review" and not target_is_non_personal:
            return

        try:
            validate_egress_granting_user_approval(self._db, proposal=proposal)
        except PersonalMemoryEgressApprovalError as exc:
            raise ProposalApplyError(str(exc)) from exc

    # Valid accept contexts that confirm the proposal went through an explicit policy gate.
    _VALID_ACCEPT_CONTEXTS: frozenset[str] = frozenset({
        "explicit_user_accept",
        "internal_seed",
    })

    def apply(
        self,
        proposal: Proposal,
        *,
        user_id: str,
        bypass_source_monitoring: bool = False,
        accept_context: str = "direct_apply",
    ) -> ApplyResult:
        """Apply a validated accepted proposal.  Raises ProposalApplyError on failure.

        Defense-in-depth: reject apply attempts that bypass the explicit policy gate.
        ProposalService.accept() always passes accept_context="explicit_user_accept".
        Tests/seeds may pass "internal_seed". All other callers are rejected.
        """
        ptype = proposal.proposal_type

        if ptype not in _SUPPORTED_TYPES:
            raise ProposalApplyError(f"unsupported proposal type: {ptype!r}")

        if accept_context not in self._VALID_ACCEPT_CONTEXTS and not bypass_source_monitoring:
            raise ProposalApplyError(
                f"ProposalApplyService.apply() called with unrecognized accept_context="
                f"{accept_context!r}. "
                "Proposals must be applied through ProposalService.accept() which enforces "
                "the policy gate. Pass bypass_source_monitoring=True only for trusted internal "
                "seed paths."
            )

        self._enforce_personal_memory_egress_approval(proposal)

        if ptype != "code_patch":
            self._enforce_source_monitoring(
                proposal,
                accept_context=accept_context,
                bypass_source_monitoring=bypass_source_monitoring,
            )

        if ptype == "egress_review":
            return ApplyResult(proposal=proposal, egress_review=True)

        if ptype == "memory_create":
            r = self._memory_applier.apply_create(proposal, user_id=user_id)
            result = ApplyResult(proposal=proposal, memory=r.memory)
            self._mark_affected_digests_dirty(proposal, result)
            return result

        if ptype == "memory_update":
            r = self._memory_applier.apply_update(proposal, user_id=user_id)
            result = ApplyResult(proposal=proposal, memory=r.memory)
            self._mark_affected_digests_dirty(proposal, result)
            return result

        if ptype == "memory_archive":
            r = self._memory_applier.apply_archive(proposal, user_id=user_id)
            result = ApplyResult(proposal=proposal, memory=r.memory)
            self._mark_affected_digests_dirty(proposal, result)
            return result

        if ptype == "policy_change":
            r = self._policy_applier.apply(proposal, user_id=user_id)
            result = ApplyResult(proposal=proposal, policy=r.policy)
            self._mark_affected_digests_dirty(proposal, result)
            return result

        if ptype == "agent_config_update":
            version = self._apply_agent_config_update(proposal, user_id=user_id)
            result = ApplyResult(proposal=proposal, agent_version=version)
            self._mark_affected_digests_dirty(proposal, result)
            return result

        if ptype == "prompt_update":
            try:
                from ..evolution.services import CapabilityVersioningService

                applied = CapabilityVersioningService(self._db).apply_prompt_update(proposal)
            except Exception as exc:  # noqa: BLE001
                raise ProposalApplyError(str(exc)) from exc
            return ApplyResult(
                proposal=proposal,
                capability_version=applied.version,
                capability_overlay=applied.overlay,
            )

        if ptype == "knowledge_create":
            try:
                item = self._knowledge_applier.apply_create(proposal, user_id=user_id)
            except Exception as exc:  # noqa: BLE001
                raise ProposalApplyError(str(exc)) from exc
            return ApplyResult(proposal=proposal, knowledge_item=item)

        if ptype == "knowledge_update":
            try:
                item = self._knowledge_applier.apply_update(proposal, user_id=user_id)
            except Exception as exc:  # noqa: BLE001
                raise ProposalApplyError(str(exc)) from exc
            return ApplyResult(proposal=proposal, knowledge_item=item)

        if ptype == "knowledge_archive":
            try:
                item = self._knowledge_applier.apply_archive(proposal, user_id=user_id)
            except Exception as exc:  # noqa: BLE001
                raise ProposalApplyError(str(exc)) from exc
            return ApplyResult(proposal=proposal, knowledge_item=item)

        if ptype == "knowledge_relation_create":
            try:
                relation = self._knowledge_applier.apply_relation_create(proposal, user_id=user_id)
            except Exception as exc:  # noqa: BLE001
                raise ProposalApplyError(str(exc)) from exc
            return ApplyResult(proposal=proposal, knowledge_relation=relation)

        if ptype == "knowledge_relation_delete":
            try:
                relation = self._knowledge_applier.apply_relation_delete(proposal, user_id=user_id)
            except Exception as exc:  # noqa: BLE001
                raise ProposalApplyError(str(exc)) from exc
            return ApplyResult(proposal=proposal, knowledge_relation=relation)

        if ptype == "code_patch":
            from .code_patch_apply import CodePatchApplyError, apply_code_patch_payload
            from ..models import Workspace

            if not proposal.workspace_id:
                raise ProposalApplyError("code_patch proposal missing workspace_id")
            ws = (
                self._db.query(Workspace)
                .filter(
                    Workspace.id == proposal.workspace_id,
                    Workspace.space_id == proposal.space_id,
                )
                .first()
            )
            if not ws:
                raise ProposalApplyError("workspace not found for proposal")

            payload = proposal.payload_json or {}
            patch = payload.get("patch")
            if not isinstance(patch, dict):
                raise ProposalApplyError("invalid patch payload")

            try:
                patch_result = apply_code_patch_payload(
                    self._db,
                    workspace=ws,
                    patch=patch,
                    space_id=proposal.space_id,
                    user_id=user_id,
                    source_run_id=payload.get("source_run_id") or proposal.created_by_run_id,
                    proposal_id=proposal.id,
                )
            except CodePatchApplyError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ProposalApplyError(str(exc)) from exc

            files = [
                {
                    "path": f.path,
                    "existed_before": f.existed_before,
                    "preimage_sha256": f.preimage_sha256,
                    "postimage_sha256": f.postimage_sha256,
                }
                for f in patch_result.files
            ]
            return ApplyResult(
                proposal=proposal,
                updated_paths=patch_result.paths,
                code_patch_files=files,
                code_patch_transaction=patch_result.transaction,
            )

        if ptype == "follow_up_task":
            task = self._follow_up_task_applier.apply(proposal, user_id=user_id)
            return ApplyResult(proposal=proposal, task=task)

        raise ProposalApplyError(f"unhandled proposal type: {ptype!r}")

    def _mark_affected_digests_dirty(self, proposal: Proposal, result: ApplyResult) -> None:
        """Mark relevant cached digests dirty after an accepted proposal."""
        try:
            from .digest_service import ContextDigestService
        except ImportError:
            return

        svc = ContextDigestService(self._db)
        ptype = proposal.proposal_type
        space_id = proposal.space_id

        if ptype in ("memory_create", "memory_update", "memory_archive"):
            mem = result.memory
            if mem is not None:
                if mem.scope_type == "workspace" and mem.workspace_id:
                    svc.mark_digest_dirty(
                        space_id, "workspace", mem.workspace_id, "workspace",
                        reason=f"{ptype}:{mem.id}",
                    )
                if mem.scope_type == "agent" and mem.agent_id:
                    svc.mark_digest_dirty(
                        space_id, "agent", mem.agent_id, "agent",
                        reason=f"{ptype}:{mem.id}",
                    )

        elif ptype == "policy_change":
            pol = result.policy
            reason = f"policy_change:{pol.id if pol else 'unknown'}"
            svc.mark_digest_dirty(space_id, "space", None, "policy_bundle", reason=reason)
            if pol is not None:
                applies = pol.applies_to_json or {}
                scope_ids = applies.get("scope_ids") or []
                scope_types = applies.get("scope_types") or applies.get("scopes") or []
                if "workspace" in scope_types:
                    for sid in scope_ids:
                        svc.mark_digest_dirty(space_id, "workspace", sid, "workspace", reason=reason)
                if "agent" in scope_types:
                    for sid in scope_ids:
                        svc.mark_digest_dirty(space_id, "agent", sid, "agent", reason=reason)

        elif ptype == "agent_config_update":
            version = result.agent_version
            if version is not None:
                svc.mark_digest_dirty(
                    space_id,
                    "agent",
                    version.agent_id,
                    "agent",
                    reason=f"agent_config_update:{version.id}",
                )
