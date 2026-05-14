from __future__ import annotations
"""
ProposalApplyService — the single durable write boundary for accepted proposals.

All normal durable writes to MemoryEntry (create, version, archive) and Policy
must flow through this service after proposal acceptance.

Supported proposal types
------------------------
  memory_create   — create a new active MemoryEntry
  memory_update   — append-only version: create new row, mark old as superseded
  memory_archive  — mark MemoryEntry status=archived (no hard delete)
  policy_change   — create a new Policy version (optionally superseding an old one)
  code_patch      — delegated back to CodePatchProposalApplier (file writes, not memory)

Callers
-------
  ProposalService.accept() is the only entry point from the public API surface.
  Tests may call ProposalApplyService.apply() directly with a persisted Proposal.
"""

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..models import MemoryEntry, Policy, Proposal, ProvenanceLink


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

        payload = proposal.payload_json or {}
        vis = (payload.get("target_visibility") or payload.get("visibility") or "private").lower()
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
        )

        writer = MemoryInternalWriter(self._db)
        mem = writer.create(
            mem_data,
            acting_user_id=user_id,
            created_by=str(proposal.created_by_user_id or user_id),
            approved_by=str(user_id),
            created_from_proposal_id=proposal.id,
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
        )

        root_id = old_mem.root_memory_id or old_mem.id

        entries = provenance_entries_from_payload(payload)

        dom_trust = dominant_source_trust(entries) or old_mem.source_trust
        act_id = first_activity_id(entries) or old_mem.source_activity_id

        new_mem = writer.create(
            mem_data,
            acting_user_id=user_id,
            created_by=str(proposal.created_by_user_id or user_id),
            approved_by=str(user_id),
            created_from_proposal_id=proposal.id,
            root_memory_id=root_id,
            supersedes_memory_id=old_mem.id,
            source_trust=dom_trust,
            source_activity_id=act_id,
        )

        writer.mark_status(old_mem.id, proposal.space_id, "superseded")

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

        writer.mark_status(mem.id, proposal.space_id, "archived")
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

        payload = proposal.payload_json or {}
        writer = PolicyInternalWriter(self._db)
        superseded_id: Optional[str] = None

        target_id = payload.get("target_policy_id")
        if target_id:
            old = writer.mark_superseded(target_id, proposal.space_id)
            if old is not None:
                superseded_id = old.id

        rule_json: Optional[dict] = payload.get("rule_json")
        if rule_json is None and proposal.proposed_content:
            rule_json = {"content": proposal.proposed_content}

        domain = payload.get("domain") or "memory"
        name = proposal.title or "Policy from proposal"

        new_policy = writer.create(
            space_id=proposal.space_id,
            name=name,
            domain=domain,
            policy_key=payload.get("policy_key"),
            policy_version=payload.get("policy_version") or 1,
            status="active",
            enforcement_mode=payload.get("enforcement_mode"),
            priority=payload.get("priority") or 0,
            rule_json=rule_json,
            applies_to_json=payload.get("applies_to_json"),
            supersedes_policy_id=superseded_id or payload.get("supersedes_policy_id"),
            created_from_proposal_id=proposal.id,
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
# ProposalApplyService — central dispatch
# ---------------------------------------------------------------------------


_SUPPORTED_TYPES = frozenset({"memory_create", "memory_update", "memory_archive", "policy_change", "code_patch"})


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

    @staticmethod
    def supported_types() -> frozenset[str]:
        return _SUPPORTED_TYPES

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

    def apply(
        self,
        proposal: Proposal,
        *,
        user_id: str,
        bypass_source_monitoring: bool = False,
        accept_context: str = "direct_apply",
    ) -> ApplyResult:
        """Apply a validated accepted proposal.  Raises ProposalApplyError on failure."""
        ptype = proposal.proposal_type

        if ptype not in _SUPPORTED_TYPES:
            raise ProposalApplyError(f"unsupported proposal type: {ptype!r}")

        if ptype != "code_patch":
            self._enforce_source_monitoring(
                proposal,
                accept_context=accept_context,
                bypass_source_monitoring=bypass_source_monitoring,
            )

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
                paths = apply_code_patch_payload(
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

            return ApplyResult(proposal=proposal, updated_paths=paths)

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
