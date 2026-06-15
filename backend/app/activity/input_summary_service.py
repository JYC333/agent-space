"""InputSummaryService — summarize selected Activity records and/or Evidence into an Artifact.

Design constraints:
- Never writes Memory or Knowledge directly; proposals go through the proposal review flow.
- Uses the configured ModelProvider (via provider_client); Anthropic/direct API is not allowed.
- If no ModelProvider is configured, raises InputSummaryProviderMissingError.
- Prompt size is bounded; content is truncated deterministically before the call.
- Creates a real Run (run_type="reflection") before calling the provider.
- Creates an Artifact(artifact_type="summary") linked to the Run as primary output.
- Optionally creates canonical pending Proposal rows (memory_create / knowledge_create).
  Both proposal types can be accepted via POST /proposals/{id}/accept without modification.
- On provider failure: Run is marked failed; no Artifact or Proposals are created.

Intake item content priority:
  1. ExtractedEvidence linked to the item (status candidate/active), content_excerpt
  2. item.excerpt
  3. item.title only (recorded as metadata_only in source_refs)
"""

from __future__ import annotations
import uuid

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy.orm import Session

from ..config import settings
from ..memory import (
    ReflectorModelProviderMissingError,
    resolve_reflector_provider_id,
)
from ..providers import complete_text
from ..memory import SOURCE_TRUST_VALUES
from ..models import (
    ActivityRecord,
    Agent,
    AgentVersion,
    Artifact,
    ExtractedEvidence,
    IntakeItem,
    Proposal,
    Run,
)
from ..schemas import DEFAULT_MEMORY_POLICY, DEFAULT_MODEL_CONFIG, DEFAULT_RUNTIME_POLICY

log = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 8_000
_TRUNCATE_SUFFIX = "\n[… truncated]"

# Version tag embedded in Artifact.metadata_json for traceability.
_SERVICE_VERSION = "2"


class InputSummaryProviderMissingError(Exception):
    """No ModelProvider configured, or provider type is unsupported."""
    error_code = "input_summary_provider_missing"


class InputSummaryProviderCallError(Exception):
    """Provider was resolved but the LLM call itself failed (network, quota, etc.)."""
    error_code = "input_summary_provider_call_failed"


class InputSummaryNoContentError(Exception):
    """All referenced records were not found or yielded no content."""
    error_code = "input_summary_no_content"


class InputSummaryCrossSpaceError(Exception):
    """One or more referenced IDs belong to a different space."""
    error_code = "input_summary_cross_space"


@dataclass
class SummaryRunResult:
    run_id: str
    artifact_id: str
    proposal_ids: list[str] = field(default_factory=list)
    status: str = "succeeded"
    summary_preview: str = ""


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + _TRUNCATE_SUFFIX


def _build_content_block(label: str, text: str) -> str:
    return f"--- {label} ---\n{text.strip()}\n"


def _new_id() -> str:
    return str(uuid.uuid4())


def _source_trust_for_activity(row: ActivityRecord) -> str:
    """Map activity type to source_trust for provenance."""
    if row.activity_type in ("user_capture", "chat_message"):
        return "user_confirmed"
    if row.activity_type in ("run_event", "workspace_event", "system_event"):
        return "internal_system"
    return "untrusted_external"


def _source_trust_for_evidence(row: ExtractedEvidence) -> str:
    if row.trust_level == "trusted":
        return "trusted_external"
    if row.trust_level == "normal":
        return "untrusted_external"
    return "untrusted_external"


def _ensure_system_summarizer_agent(db: Session, space_id: str) -> tuple[str, str]:
    """Get or create the deterministic 'input-summarizer' system agent for this space.

    Returns (agent_id, agent_version_id). The agent is flushed but not committed;
    the caller's transaction controls the final commit.
    """
    _NAME = "input-summarizer"
    existing = (
        db.query(Agent)
        .filter(Agent.space_id == space_id, Agent.name == _NAME)
        .first()
    )
    if existing is not None:
        version_id = existing.current_version_id
        if version_id is None:
            v = db.query(AgentVersion).filter(AgentVersion.agent_id == existing.id).first()
            if v is not None:
                version_id = v.id
                existing.current_version_id = version_id
                db.flush()
        if version_id is not None:
            return existing.id, version_id

    agent_id = _new_id()
    version_id = _new_id()
    agent = Agent(
        id=agent_id,
        space_id=space_id,
        name=_NAME,
        description="System agent for input summarization runs.",
        status="active",
    )
    version = AgentVersion(
        id=version_id,
        agent_id=agent_id,
        space_id=space_id,
        version_label="v1",
        model_config_json=dict(DEFAULT_MODEL_CONFIG),
        memory_policy_json=dict(DEFAULT_MEMORY_POLICY),
        capabilities_json=[],
        tool_permissions_json={},
        runtime_policy_json=dict(DEFAULT_RUNTIME_POLICY),
    )
    db.add(agent)
    db.flush()
    db.add(version)
    db.flush()
    agent.current_version_id = version_id
    db.flush()
    return agent_id, version_id


class InputSummaryService:
    """Summarize selected Activity records and/or Evidence into an Artifact.

    Typical usage::

        svc = InputSummaryService(db)
        result = svc.run(
            space_id=space_id,
            user_id=user_id,
            activity_ids=["..."],
            create_memory_proposal=True,
        )
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def run(
        self,
        *,
        space_id: str,
        user_id: str,
        activity_ids: Sequence[str] | None = None,
        evidence_ids: Sequence[str] | None = None,
        intake_item_ids: Sequence[str] | None = None,
        summary_goal: str | None = None,
        create_memory_proposal: bool = False,
        create_knowledge_proposal: bool = False,
    ) -> SummaryRunResult:
        content_blocks: list[str] = []
        source_refs: list[dict] = []

        # ------------------------------------------------------------------
        # Collect Activity content
        # ------------------------------------------------------------------
        for aid in (activity_ids or []):
            row = (
                self._db.query(ActivityRecord)
                .filter(ActivityRecord.id == aid, ActivityRecord.space_id == space_id)
                .first()
            )
            if row is None:
                raise InputSummaryCrossSpaceError(
                    f"ActivityRecord {aid!r} not found in space {space_id!r}"
                )
            text = (row.content or "").strip()
            if text:
                label = row.title or f"Activity {aid[:8]}"
                content_blocks.append(_build_content_block(label, text))
                source_refs.append({
                    "type": "activity",
                    "id": aid,
                    "source_trust": _source_trust_for_activity(row),
                })

        # ------------------------------------------------------------------
        # Collect Evidence content
        # ------------------------------------------------------------------
        for eid in (evidence_ids or []):
            row = (
                self._db.query(ExtractedEvidence)
                .filter(ExtractedEvidence.id == eid, ExtractedEvidence.space_id == space_id)
                .first()
            )
            if row is None:
                raise InputSummaryCrossSpaceError(
                    f"ExtractedEvidence {eid!r} not found in space {space_id!r}"
                )
            text = (row.content_excerpt or "").strip()
            if text:
                label = row.title or f"Evidence {eid[:8]}"
                content_blocks.append(_build_content_block(label, text))
                source_refs.append({
                    "type": "evidence",
                    "id": eid,
                    "source_trust": _source_trust_for_evidence(row),
                })

        # ------------------------------------------------------------------
        # Collect IntakeItem content: evidence first, then excerpt, then title-only
        # ------------------------------------------------------------------
        for iid in (intake_item_ids or []):
            item = (
                self._db.query(IntakeItem)
                .filter(IntakeItem.id == iid, IntakeItem.space_id == space_id)
                .first()
            )
            if item is None:
                raise InputSummaryCrossSpaceError(
                    f"IntakeItem {iid!r} not found in space {space_id!r}"
                )
            label = item.title or f"Item {iid[:8]}"

            # Priority 1: ExtractedEvidence linked to this item
            ev_rows = (
                self._db.query(ExtractedEvidence)
                .filter(
                    ExtractedEvidence.intake_item_id == iid,
                    ExtractedEvidence.space_id == space_id,
                    ExtractedEvidence.status.in_(["active", "candidate"]),
                    ExtractedEvidence.deleted_at.is_(None),
                )
                .order_by(ExtractedEvidence.created_at.asc())
                .limit(3)
                .all()
            )
            ev_text = " ".join(
                (r.content_excerpt or "").strip()
                for r in ev_rows
                if (r.content_excerpt or "").strip()
            ).strip()

            if ev_text:
                content_blocks.append(_build_content_block(label, ev_text))
                source_refs.append({
                    "type": "intake_item",
                    "id": iid,
                    "source_trust": "untrusted_external",
                    "via": "evidence",
                })
                continue

            # Priority 2: excerpt
            excerpt = (item.excerpt or "").strip()
            if excerpt:
                content_blocks.append(_build_content_block(label, excerpt))
                source_refs.append({
                    "type": "intake_item",
                    "id": iid,
                    "source_trust": "untrusted_external",
                    "via": "excerpt",
                })
                continue

            # Priority 3: title-only fallback (metadata_only)
            title_text = (item.title or "").strip()
            if title_text:
                content_blocks.append(_build_content_block(label, f"[metadata only] {title_text}"))
                source_refs.append({
                    "type": "intake_item",
                    "id": iid,
                    "source_trust": "untrusted_external",
                    "via": "title_only",
                    "metadata_only": True,
                })

        if not content_blocks:
            raise InputSummaryNoContentError(
                "No content found in the referenced records."
            )

        # ------------------------------------------------------------------
        # Resolve provider before creating the Run
        # ------------------------------------------------------------------
        try:
            provider_id, model = resolve_reflector_provider_id(settings)
        except ReflectorModelProviderMissingError as exc:
            raise InputSummaryProviderMissingError(str(exc)) from exc

        # ------------------------------------------------------------------
        # Create system agent + Run (status=queued → running)
        # ------------------------------------------------------------------
        agent_id, agent_version_id = _ensure_system_summarizer_agent(self._db, space_id)
        now = datetime.now(UTC)
        goal_snippet = (summary_goal or "").strip()[:120]
        prompt = (
            f"Summarize {len(source_refs)} source(s)"
            + (f": {goal_snippet}" if goal_snippet else "")
        )
        run = Run(
            id=_new_id(),
            space_id=space_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            run_type="reflection",
            trigger_origin="manual",
            source="managed",
            mode="live",
            status="running",
            instructed_by_user_id=user_id,
            prompt=prompt,
            started_at=now,
        )
        self._db.add(run)
        self._db.flush()

        # ------------------------------------------------------------------
        # Build bounded prompt and call provider
        # ------------------------------------------------------------------
        raw_content = "\n".join(content_blocks)
        bounded_content = _truncate(raw_content, _MAX_CONTENT_CHARS)
        goal_line = f"\nSummary goal: {summary_goal.strip()}\n" if summary_goal else ""
        system_prompt = (
            "You are a concise knowledge summarizer. Given the following input records, "
            "produce a clear, factual summary. Focus on key insights, decisions, or "
            "patterns worth preserving. Use markdown. Keep under 400 words."
        )
        user_prompt = (
            f"{goal_line}\nInput records:\n\n{bounded_content}\n\n"
            "Write a concise summary of the above:"
        )

        log.info(
            "input_summary: calling LLM provider_id=%s model=%s source_count=%d space=%s run=%s",
            provider_id, model, len(source_refs), space_id, run.id,
        )

        try:
            summary_text = complete_text(
                self._db,
                provider_id=provider_id,
                model=model,
                system=system_prompt,
                user=user_prompt,
                task="input_summary",
            ).text
        except Exception as exc:
            log.warning("input_summary: provider call failed run=%s: %s", run.id, exc)
            run.status = "failed"
            run.error_message = str(exc)[:1000]
            run.ended_at = datetime.now(UTC)
            self._db.commit()
            raise InputSummaryProviderCallError(
                f"Summary provider call failed: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Create Artifact linked to Run
        # ------------------------------------------------------------------
        title = f"Summary — {now.strftime('%Y-%m-%d %H:%M')}"
        if summary_goal:
            title = f"Summary: {summary_goal[:80].strip()}"

        artifact = Artifact(
            id=_new_id(),
            space_id=space_id,
            run_id=run.id,
            artifact_type="summary",
            title=title,
            content=summary_text,
            mime_type="text/markdown",
            exportable=True,
            preview=False,
            owner_user_id=user_id,
            metadata_json={
                "source_refs": source_refs,
                "summary_goal": summary_goal,
                "provider_id": provider_id,
                "model": model,
                "generated_by": "input_summary_service",
                "input_summary_service_version": _SERVICE_VERSION,
            },
        )
        self._db.add(artifact)
        self._db.flush()

        # ------------------------------------------------------------------
        # Create proposals (canonical builders)
        # ------------------------------------------------------------------
        proposal_ids: list[str] = []

        if create_memory_proposal:
            from ..proposals import build_memory_create_proposal
            from ..memory import ProvenanceEntry

            # Build provenance from original source rows only.
            # Run and artifact refs go to payload metadata, NOT to provenance_entries,
            # so generated-summary trust cannot upgrade external/intake-derived sources.
            extra_prov: list[dict] = []
            for ref in source_refs:
                src_type = ref["type"]
                src_id = ref["id"]
                trust = ref.get("source_trust", "untrusted_external")
                prov_type = (
                    "activity" if src_type == "activity"
                    else "external_source"
                )
                entry = ProvenanceEntry(
                    source_type=prov_type,
                    source_id=src_id,
                    source_trust=trust if trust in SOURCE_TRUST_VALUES else "untrusted_external",
                )
                extra_prov.append(entry.to_row_dict())

            prop = build_memory_create_proposal(
                _new_id(),
                space_id,
                user_id,
                workspace_id=None,
                proposed_title=title,
                proposed_content=summary_text,
                rationale="Generated from input summary. Review before accepting.",
                memory_type="semantic",
                target_scope="user",
                target_namespace="user.default",
                source_run_id=None,       # do not let run_step/internal_system upgrade trust
                target_visibility="space_shared",
                risk_level="low",
                owner_user_id=user_id,
                created_by_run_id=run.id,
                extra_provenance_entries=extra_prov,
            )
            # Store run/artifact refs as source metadata (not trust-bearing provenance)
            from sqlalchemy.orm.attributes import flag_modified
            payload = dict(prop.payload_json or {})
            payload.setdefault("source_refs_metadata", {})
            payload["source_refs_metadata"]["summary_run_id"] = run.id
            payload["source_refs_metadata"]["summary_artifact_id"] = artifact.id
            prop.payload_json = payload
            flag_modified(prop, "payload_json")
            self._db.add(prop)
            self._db.flush()
            proposal_ids.append(prop.id)

        if create_knowledge_proposal:
            payload: dict = {
                "operation": "create",
                "item_type": "summary",
                "title": title,
                "content": summary_text,
                "content_format": "markdown",
                "visibility": "space_shared",
                "owner_user_id": user_id,
                "tags": [],
                "source_refs": source_refs,
                "source_artifact_id": artifact.id,
                "source_run_id": run.id,
                "verification_status": "unverified",
                "reflection_status": "unreviewed",
            }
            prop = Proposal(
                id=_new_id(),
                space_id=space_id,
                proposal_type="knowledge_create",
                status="pending",
                risk_level="low",
                urgency="normal",
                title=title,
                rationale="Generated from input summary. Review before accepting.",
                created_by_user_id=user_id,
                created_by_run_id=run.id,
                payload_json=payload,
            )
            self._db.add(prop)
            self._db.flush()
            proposal_ids.append(prop.id)

        # ------------------------------------------------------------------
        # Mark Run succeeded and commit
        # ------------------------------------------------------------------
        run.status = "succeeded"
        run.ended_at = datetime.now(UTC)
        self._db.commit()

        preview = summary_text[:200].strip()
        if len(summary_text) > 200:
            preview += "…"

        log.info(
            "input_summary: done run=%s artifact=%s proposals=%d space=%s",
            run.id, artifact.id, len(proposal_ids), space_id,
        )

        return SummaryRunResult(
            run_id=run.id,
            artifact_id=artifact.id,
            proposal_ids=proposal_ids,
            status="succeeded",
            summary_preview=preview,
        )
