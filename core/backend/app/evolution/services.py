from __future__ import annotations

"""Service layer for the system-level evolution substrate foundation."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..capabilities.registry import CapabilityRegistry
from ..models import (
    Agent,
    AgentVersion,
    Artifact,
    CapabilityOverlay,
    CapabilityVersion,
    EvolutionSignal,
    EvolutionTarget,
    Proposal,
    Run,
)
from ..providers.service import ModelService
from ..schemas import DEFAULT_MEMORY_POLICY, DEFAULT_MODEL_CONFIG, DEFAULT_RUNTIME_POLICY
from .constants import (
    CAPABILITY_SCOPE_ORDER,
    DEFAULT_CAPTURE_CAPABILITY_KEY,
    DEFAULT_CAPTURE_TARGET_TYPE,
    EVOLUTION_ENGINE_NAMES,
    EVOLUTION_SIGNAL_SEVERITIES,
    EVOLUTION_SIGNAL_TYPES,
    EVOLUTION_TARGET_TYPES,
)
from .engines import EvolutionEngineOutput, get_engine
from .validation import evaluate_target_validation


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _json_dump(data: dict) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)


def _hash_json(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_scope_match(column, value: str | None):
    return column.is_(None) if value is None else column == value


def _target_identity(target: EvolutionTarget) -> tuple[str, str | None, str | None]:
    return (target.target_type, target.target_ref_id, target.capability_key)


def _metadata_origin_type(metadata_json: dict | None) -> str | None:
    origin = (metadata_json or {}).get("origin")
    if not isinstance(origin, dict):
        return None
    origin_type = origin.get("type")
    return origin_type if isinstance(origin_type, str) else None


def _is_system_override_target(target: EvolutionTarget) -> bool:
    return _metadata_origin_type(target.metadata_json) == "system_override"


def _default_capture_target_metadata() -> dict:
    return {
        "purpose": "capture_memory_extraction",
        "validation": {
            "window": "14d",
            "metrics": [
                {
                    "id": "memory_candidate_reject_rate",
                    "label": "Memory candidate reject rate",
                    "evaluator": "rate",
                    "numerator": {
                        "source": "signals",
                        "signal_type": "memory_candidate_rejected",
                    },
                    "denominator": {
                        "source": "signals",
                        "signal_type": "memory_candidate_proposed",
                    },
                    "goal": {
                        "direction": "decrease",
                        "threshold": 0.2,
                    },
                },
                {
                    "id": "memory_candidate_edit_rate",
                    "label": "Memory candidate edit rate",
                    "evaluator": "rate",
                    "numerator": {
                        "source": "signals",
                        "signal_type": "memory_candidate_edited",
                    },
                    "denominator": {
                        "source": "signals",
                        "signal_type": "memory_candidate_proposed",
                    },
                    "goal": {
                        "direction": "decrease",
                        "threshold": 0.3,
                    },
                },
                {
                    "id": "exploration_misclassified_as_decision_count",
                    "label": "Exploration misclassified as decision",
                    "evaluator": "count_signals",
                    "source": "signals",
                    "signal_type": "exploration_misclassified_as_decision",
                    "goal": {
                        "direction": "decrease",
                        "threshold": 0,
                    },
                },
                {
                    "id": "stable_preference_missed_count",
                    "label": "Stable preference missed",
                    "evaluator": "count_signals",
                    "source": "signals",
                    "signal_type": "stable_preference_missed",
                    "goal": {
                        "direction": "decrease",
                        "threshold": 0,
                    },
                },
            ],
        },
        "constraints": [
            "raw capture is Activity first, not active Memory",
            "memory update must be proposal-first",
            "distinguish exploration, accepted_decision, stable_preference, rejected_option, unresolved_question",
            "do not turn one-off questions into long-term memory",
            "do not bake individual personal preferences into core capability",
            "conflicting or uncertain items should be marked unresolved",
            "only repeated confirmation or accepted proposal outcomes can promote content to stable memory",
        ],
    }


def _ensure_system_evolution_agent(db: Session, space_id: str) -> tuple[str, str]:
    name = "evolution-substrate"
    existing = (
        db.query(Agent)
        .filter(Agent.space_id == space_id, Agent.name == name)
        .first()
    )
    if existing is not None:
        version_id = existing.current_version_id
        if version_id is None:
            version = db.query(AgentVersion).filter(AgentVersion.agent_id == existing.id).first()
            if version is not None:
                existing.current_version_id = version.id
                db.flush()
                version_id = version.id
        if version_id is not None:
            return existing.id, version_id

    agent_id = _new_id()
    version_id = _new_id()
    agent = Agent(
        id=agent_id,
        space_id=space_id,
        name=name,
        description="System agent for evolution substrate runs.",
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


class EvolutionTargetRegistry:
    def __init__(self, db: Session) -> None:
        self._db = db

    def register(
        self,
        *,
        target_type: str,
        space_id: str | None = None,
        target_ref_type: str | None = None,
        target_ref_id: str | None = None,
        capability_key: str | None = None,
        current_version_id: str | None = None,
        risk_level: str = "medium",
        enabled: bool = True,
        engine_policy_json: dict | None = None,
        metadata_json: dict | None = None,
        status: str = "active",
        upsert: bool = True,
    ) -> EvolutionTarget:
        if target_type not in EVOLUTION_TARGET_TYPES:
            raise ValueError(f"Unsupported evolution target_type {target_type!r}")

        if upsert:
            candidates = (
                self._db.query(EvolutionTarget)
                .filter(
                    _is_scope_match(EvolutionTarget.space_id, space_id),
                    EvolutionTarget.target_type == target_type,
                    _is_scope_match(EvolutionTarget.target_ref_id, target_ref_id),
                    _is_scope_match(EvolutionTarget.capability_key, capability_key),
                )
                .order_by(EvolutionTarget.created_at.asc())
                .all()
            )
            requested_origin_type = _metadata_origin_type(metadata_json)
            existing = None
            for candidate in candidates:
                if requested_origin_type == "system_override":
                    if _is_system_override_target(candidate):
                        existing = candidate
                        break
                elif not _is_system_override_target(candidate):
                    existing = candidate
                    break
            if existing is not None:
                changed = False
                if current_version_id and existing.current_version_id != current_version_id:
                    existing.current_version_id = current_version_id
                    changed = True
                if engine_policy_json and existing.engine_policy_json != dict(engine_policy_json):
                    existing.engine_policy_json = dict(engine_policy_json)
                    changed = True
                if not existing.metadata_json and metadata_json:
                    existing.metadata_json = dict(metadata_json)
                    changed = True
                if changed:
                    self._db.flush()
                return existing

        row = EvolutionTarget(
            id=_new_id(),
            space_id=space_id,
            target_type=target_type,
            target_ref_type=target_ref_type,
            target_ref_id=target_ref_id,
            capability_key=capability_key,
            current_version_id=current_version_id,
            risk_level=risk_level,
            enabled=enabled,
            status=status,
            engine_policy_json=dict(engine_policy_json or {}),
            metadata_json=dict(metadata_json or {}),
        )
        self._db.add(row)
        self._db.flush()
        return row

    def ensure_default_target_for_capture_memory_extraction(self) -> EvolutionTarget:
        metadata_json = _default_capture_target_metadata()
        target = self.register(
            target_type=DEFAULT_CAPTURE_TARGET_TYPE,
            space_id=None,
            target_ref_type="capability",
            target_ref_id=DEFAULT_CAPTURE_CAPABILITY_KEY,
            capability_key=DEFAULT_CAPTURE_CAPABILITY_KEY,
            risk_level="medium",
            engine_policy_json={
                "allowed_engines": ["llm_prompt_review"],
                "allowed_proposal_types": ["prompt_update"],
            },
            metadata_json=metadata_json,
        )
        if target.metadata_json != metadata_json:
            target.metadata_json = metadata_json
            self._db.flush()
        return target

    def list_targets(self, *, space_id: str | None = None, include_system: bool = True) -> list[EvolutionTarget]:
        self.ensure_default_target_for_capture_memory_extraction()
        q = self._db.query(EvolutionTarget)
        if space_id is not None:
            if include_system:
                q = q.filter(or_(EvolutionTarget.space_id == space_id, EvolutionTarget.space_id.is_(None)))
            else:
                q = q.filter(EvolutionTarget.space_id == space_id)
        rows = q.order_by(EvolutionTarget.created_at.asc()).all()
        if space_id is None or not include_system:
            return rows
        overridden_system_keys = {
            _target_identity(row)
            for row in rows
            if row.space_id == space_id and _is_system_override_target(row)
        }
        return [
            row for row in rows
            if row.space_id == space_id or _target_identity(row) not in overridden_system_keys
        ]

    def get_target(
        self,
        target_id: str,
        *,
        space_id: str | None = None,
        include_system: bool = True,
    ) -> EvolutionTarget | None:
        q = self._db.query(EvolutionTarget).filter(EvolutionTarget.id == target_id)
        if space_id is not None:
            if include_system:
                q = q.filter(or_(EvolutionTarget.space_id == space_id, EvolutionTarget.space_id.is_(None)))
            else:
                q = q.filter(EvolutionTarget.space_id == space_id)
        return q.first()

    def resolve_target_current_version(self, target: EvolutionTarget) -> CapabilityVersion | None:
        if not target.current_version_id:
            return None
        return (
            self._db.query(CapabilityVersion)
            .filter(CapabilityVersion.id == target.current_version_id)
            .first()
        )


class EvolutionSignalService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_signal(
        self,
        *,
        space_id: str | None,
        target_id: str,
        signal_type: str,
        source_type: str,
        source_id: str | None = None,
        severity: str = "medium",
        summary: str | None = None,
        payload_json: dict | None = None,
    ) -> EvolutionSignal:
        if signal_type not in EVOLUTION_SIGNAL_TYPES:
            raise ValueError(f"Unsupported evolution signal_type {signal_type!r}")
        if severity not in EVOLUTION_SIGNAL_SEVERITIES:
            raise ValueError(f"Unsupported evolution signal severity {severity!r}")
        target = self._db.query(EvolutionTarget).filter(EvolutionTarget.id == target_id).first()
        if target is None:
            raise ValueError("Evolution target not found")
        if target.space_id is not None and target.space_id != space_id:
            raise ValueError("Evolution target belongs to a different space")

        row = EvolutionSignal(
            id=_new_id(),
            space_id=space_id,
            target_id=target_id,
            signal_type=signal_type,
            source_type=source_type,
            source_id=source_id,
            severity=severity,
            summary=summary,
            payload_json=dict(payload_json or {}),
        )
        self._db.add(row)
        self._db.flush()
        return row

    def create_from_proposal_outcome(
        self,
        *,
        proposal: Proposal,
        target_id: str,
        user_id: str | None = None,
    ) -> EvolutionSignal:
        signal_type = "proposal_rejected" if proposal.status == "rejected" else "memory_candidate_edited"
        return self.create_signal(
            space_id=proposal.space_id,
            target_id=target_id,
            signal_type=signal_type,
            source_type="proposal",
            source_id=proposal.id,
            severity="medium",
            summary=proposal.summary or proposal.title,
            payload_json={
                "proposal_type": proposal.proposal_type,
                "proposal_status": proposal.status,
                "user_id": user_id,
            },
        )

    def create_from_run_failure(
        self,
        *,
        run: Run,
        target_id: str,
        summary: str | None = None,
    ) -> EvolutionSignal:
        return self.create_signal(
            space_id=run.space_id,
            target_id=target_id,
            signal_type="run_validation_failed",
            source_type="run",
            source_id=run.id,
            severity="high",
            summary=summary or run.error_message,
            payload_json={"run_type": run.run_type, "error_json": run.error_json or {}},
        )

    def list_signals(
        self,
        *,
        target_id: str,
        space_id: str | None = None,
        signal_type: str | None = None,
        severity: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EvolutionSignal]:
        q = self._db.query(EvolutionSignal).filter(EvolutionSignal.target_id == target_id)
        if space_id is not None:
            q = q.filter(EvolutionSignal.space_id == space_id)
        if signal_type:
            q = q.filter(EvolutionSignal.signal_type == signal_type)
        if severity:
            q = q.filter(EvolutionSignal.severity == severity)
        if created_after:
            q = q.filter(EvolutionSignal.created_at >= created_after)
        if created_before:
            q = q.filter(EvolutionSignal.created_at <= created_before)
        return q.order_by(EvolutionSignal.created_at.desc()).offset(offset).limit(limit).all()


@dataclass
class EvolutionContextResult:
    artifact: Artifact
    payload: dict


class EvolutionContextBuilder:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _capability_payload(self, capability_key: str | None, *, space_id: str) -> dict:
        if not capability_key:
            return {}
        registry = CapabilityRegistry(self._db)
        registry.reload(space_id=space_id)
        cap = registry.get(capability_key)
        if cap is None:
            return {"capability_key": capability_key, "found": False}

        prompt = None
        prompt_truncated = False
        prompt_path = Path(cap.manifest_dir) / "prompts" / "main.md"
        if prompt_path.exists() and prompt_path.is_file():
            prompt_text = prompt_path.read_text(encoding="utf-8")
            prompt = prompt_text[:20000]
            prompt_truncated = len(prompt_text) > len(prompt)

        return {
            "capability_key": cap.id,
            "found": True,
            "name": cap.name,
            "version": cap.version,
            "source": cap.source,
            "manifest_path": cap.manifest_path,
            "manifest_json": cap.manifest_json,
            "prompt": prompt,
            "prompt_truncated": prompt_truncated,
        }

    def build(
        self,
        *,
        target: EvolutionTarget,
        space_id: str,
        user_id: str | None = None,
        run_id: str | None = None,
        signal_limit: int = 50,
        constraints: list[str] | None = None,
        validation_goals: list[dict] | None = None,
    ) -> EvolutionContextResult:
        current_version = EvolutionTargetRegistry(self._db).resolve_target_current_version(target)
        signals = EvolutionSignalService(self._db).list_signals(
            target_id=target.id,
            space_id=space_id,
            limit=signal_limit,
        )
        target_meta = dict(target.metadata_json or {})
        context_constraints = list(constraints or target_meta.get("constraints") or [])
        validation = target_meta.get("validation") if isinstance(target_meta.get("validation"), dict) else {}
        goals = list(validation_goals or validation.get("metrics") or [])
        validation_results = [
            {
                "metric_id": result.metric_id,
                "label": result.label,
                "evaluator": result.evaluator,
                "value": result.value,
                "status": result.status,
                "window": result.window,
                "goal": result.goal,
                "sample_size": result.sample_size,
                "numerator_count": result.numerator_count,
                "denominator_count": result.denominator_count,
                "updated_at": result.updated_at.isoformat() if result.updated_at else None,
                "metadata_json": result.metadata_json,
            }
            for result in evaluate_target_validation(self._db, target, space_id=space_id)
        ]
        payload = {
            "schema": "evolution_context.v1",
            "built_at": _utcnow().isoformat(),
            "space_id": space_id,
            "user_id": user_id,
            "target": {
                "id": target.id,
                "space_id": target.space_id,
                "target_type": target.target_type,
                "target_ref_type": target.target_ref_type,
                "target_ref_id": target.target_ref_id,
                "capability_key": target.capability_key,
                "risk_level": target.risk_level,
                "metadata_json": target_meta,
            },
            "current_version": (
                {
                    "id": current_version.id,
                    "version": current_version.version,
                    "scope_type": current_version.scope_type,
                    "scope_id": current_version.scope_id,
                    "source": current_version.source,
                    "artifact_uri": current_version.artifact_uri,
                    "content_ref": current_version.content_ref,
                    "content_hash": current_version.content_hash,
                    "status": current_version.status,
                }
                if current_version is not None
                else None
            ),
            "capability": self._capability_payload(target.capability_key, space_id=space_id),
            "recent_signals": [
                {
                    "id": s.id,
                    "space_id": s.space_id,
                    "signal_type": s.signal_type,
                    "source_type": s.source_type,
                    "source_id": s.source_id,
                    "severity": s.severity,
                    "summary": s.summary,
                    "payload_json": s.payload_json or {},
                    "created_at": s.created_at.isoformat(),
                }
                for s in signals
            ],
            "constraints": context_constraints,
            "validation": validation,
            "validation_goals": goals,
            "validation_results": validation_results,
        }
        artifact = Artifact(
            id=_new_id(),
            space_id=space_id,
            run_id=run_id,
            artifact_type="evolution_context",
            title=f"Evolution context: {target.capability_key or target.target_type}",
            content=_json_dump(payload),
            mime_type="application/json",
            metadata_json={
                "target_id": target.id,
                "capability_key": target.capability_key,
                "signal_count": len(signals),
                "schema": payload["schema"],
            },
        )
        self._db.add(artifact)
        self._db.flush()
        return EvolutionContextResult(artifact=artifact, payload=payload)


class EvolutionProposalService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_prompt_update_proposal(
        self,
        *,
        target: EvolutionTarget,
        space_id: str,
        user_id: str,
        run_id: str,
        engine_output: EvolutionEngineOutput,
        context_artifact: Artifact,
        report_artifact: Artifact,
        revision_artifact: Artifact,
    ) -> Proposal:
        payload = {
            "operation": "prompt_revision",
            "proposal_schema": "prompt_update.v2",
            "target_id": target.id,
            "target_type": target.target_type,
            "capability_key": target.capability_key,
            "scope_type": "space",
            "scope_id": space_id,
            "base_version_id": target.current_version_id,
            "overlay_type": "prompt_revision",
            "revision": engine_output.prompt_revision,
            "engine": engine_output.engine,
            "engine_metadata": dict(engine_output.metadata or {}),
            "artifacts": {
                "evolution_context": context_artifact.id,
                "evolution_report": report_artifact.id,
                "prompt_revision": revision_artifact.id,
            },
            "non_mutating_engine_output": True,
        }
        proposal = Proposal(
            id=_new_id(),
            space_id=space_id,
            created_by_run_id=run_id,
            proposal_type="prompt_update",
            status="pending",
            risk_level=target.risk_level or "medium",
            urgency="normal",
            title=f"Prompt update: {target.capability_key or target.target_type}",
            summary="Evolution engine proposed a scoped prompt revision. Approval creates a scoped overlay; core defaults are not overwritten.",
            payload_json=payload,
            rationale="Created from evolution signals and compact evolution context.",
            created_by_user_id=user_id,
        )
        self._db.add(proposal)
        self._db.flush()
        for artifact in (report_artifact, revision_artifact):
            artifact.proposal_id = proposal.id
        self._db.flush()
        return proposal


@dataclass
class CapabilityResolution:
    capability_key: str
    source_scope_type: str
    source_scope_id: str | None
    version: CapabilityVersion | None
    overlays: list[CapabilityOverlay]
    core_manifest: dict | None = None


@dataclass
class CapabilityApplyResult:
    version: CapabilityVersion
    overlay: CapabilityOverlay


class CapabilityVersioningService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _next_version_label(self, capability_key: str, scope_type: str, scope_id: str | None) -> str:
        count = (
            self._db.query(CapabilityVersion)
            .filter(
                CapabilityVersion.capability_key == capability_key,
                CapabilityVersion.scope_type == scope_type,
                _is_scope_match(CapabilityVersion.scope_id, scope_id),
            )
            .count()
        )
        return f"v{count + 1}"

    def _validate_prompt_revision(self, revision: Any) -> dict:
        if not isinstance(revision, dict):
            raise ValueError("prompt_update payload revision must be an object")
        prompt = revision.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt_update revision.prompt must be a non-empty string")
        normalized = dict(revision)
        normalized["revision_format"] = normalized.get("revision_format") or "prompt_revision.v1"
        normalized["prompt"] = prompt.strip()
        return normalized

    def apply_prompt_update(self, proposal: Proposal) -> CapabilityApplyResult:
        payload = proposal.payload_json or {}
        capability_key = payload.get("capability_key")
        if not isinstance(capability_key, str) or not capability_key:
            raise ValueError("prompt_update missing capability_key")
        scope_type = payload.get("scope_type") or "space"
        if not isinstance(scope_type, str) or scope_type not in CAPABILITY_SCOPE_ORDER:
            raise ValueError("prompt_update has invalid scope_type")
        scope_id = payload.get("scope_id")
        if scope_type in {"agent", "user", "space"} and not isinstance(scope_id, str):
            raise ValueError(f"prompt_update scope_type {scope_type!r} requires scope_id")
        if scope_type in {"instance", "core"}:
            scope_id = None

        revision = self._validate_prompt_revision(payload.get("revision"))
        overlay_type = payload.get("overlay_type") or "prompt_revision"
        if overlay_type != "prompt_revision":
            raise ValueError("prompt_update only supports prompt_revision overlays")

        old_versions = (
            self._db.query(CapabilityVersion)
            .filter(
                CapabilityVersion.capability_key == capability_key,
                CapabilityVersion.scope_type == scope_type,
                _is_scope_match(CapabilityVersion.scope_id, scope_id),
                CapabilityVersion.status == "active",
            )
            .all()
        )
        for row in old_versions:
            row.status = "archived"

        old_overlays = (
            self._db.query(CapabilityOverlay)
            .filter(
                CapabilityOverlay.capability_key == capability_key,
                CapabilityOverlay.scope_type == scope_type,
                _is_scope_match(CapabilityOverlay.scope_id, scope_id),
                CapabilityOverlay.status == "active",
            )
            .all()
        )
        for row in old_overlays:
            row.status = "archived"

        artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
        revision_artifact_id = artifacts.get("prompt_revision")
        revision_hash = _hash_json(revision)
        version = CapabilityVersion(
            id=_new_id(),
            capability_key=capability_key,
            scope_type=scope_type,
            scope_id=scope_id,
            parent_version_id=payload.get("base_version_id"),
            version=self._next_version_label(capability_key, scope_type, scope_id),
            source="evolution",
            artifact_uri=f"artifact:{revision_artifact_id}" if revision_artifact_id else None,
            content_ref=f"proposal:{proposal.id}",
            content_hash=revision_hash,
            status="active",
            proposal_id=proposal.id,
            metadata_json={
                "target_id": payload.get("target_id"),
                "engine": payload.get("engine"),
                "proposal_type": proposal.proposal_type,
                "artifact_ids": artifacts,
            },
        )
        self._db.add(version)
        self._db.flush()

        overlay = CapabilityOverlay(
            id=_new_id(),
            capability_key=capability_key,
            scope_type=scope_type,
            scope_id=scope_id,
            base_version_id=payload.get("base_version_id"),
            overlay_type=overlay_type,
            patch_json=revision,
            status="active",
            proposal_id=proposal.id,
            metadata_json={
                "capability_version_id": version.id,
                "revision_hash": revision_hash,
                "engine": payload.get("engine"),
                "target_id": payload.get("target_id"),
            },
        )
        self._db.add(overlay)
        self._db.flush()

        updated_payload = dict(payload)
        updated_payload["resulting_capability_version_id"] = version.id
        updated_payload["resulting_capability_overlay_id"] = overlay.id
        proposal.payload_json = updated_payload
        flag_modified(proposal, "payload_json")
        return CapabilityApplyResult(version=version, overlay=overlay)

    def resolve(
        self,
        capability_key: str,
        *,
        space_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> CapabilityResolution:
        scope_candidates: list[tuple[str, str | None]] = [
            ("agent", agent_id),
            ("user", user_id),
            ("space", space_id),
            ("instance", None),
        ]
        for scope_type, scope_id in scope_candidates:
            if scope_type in {"agent", "user", "space"} and not scope_id:
                continue
            filters = [
                CapabilityVersion.capability_key == capability_key,
                CapabilityVersion.scope_type == scope_type,
                _is_scope_match(CapabilityVersion.scope_id, scope_id),
                CapabilityVersion.status == "active",
            ]
            version = (
                self._db.query(CapabilityVersion)
                .filter(and_(*filters))
                .order_by(CapabilityVersion.created_at.desc())
                .first()
            )
            overlay_filters = [
                CapabilityOverlay.capability_key == capability_key,
                CapabilityOverlay.scope_type == scope_type,
                _is_scope_match(CapabilityOverlay.scope_id, scope_id),
                CapabilityOverlay.status == "active",
            ]
            overlays = (
                self._db.query(CapabilityOverlay)
                .filter(and_(*overlay_filters))
                .order_by(CapabilityOverlay.created_at.desc())
                .all()
            )
            if version is not None or overlays:
                return CapabilityResolution(
                    capability_key=capability_key,
                    source_scope_type=scope_type,
                    source_scope_id=scope_id,
                    version=version,
                    overlays=overlays,
                )

        core_manifest = None
        registry = CapabilityRegistry(self._db)
        registry.reload(space_id=space_id)
        cap = registry.get(capability_key)
        if cap is not None:
            core_manifest = cap.manifest_json
        return CapabilityResolution(
            capability_key=capability_key,
            source_scope_type="core",
            source_scope_id=None,
            version=None,
            overlays=[],
            core_manifest=core_manifest,
        )


@dataclass
class EvolutionRunResult:
    run: Run
    context_artifact: Artifact
    report_artifact: Artifact
    revision_artifact: Artifact
    proposal: Proposal


class EvolutionRunService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _create_artifact(
        self,
        *,
        space_id: str,
        run_id: str,
        artifact_type: str,
        title: str,
        payload: dict,
        metadata_json: dict | None = None,
    ) -> Artifact:
        artifact = Artifact(
            id=_new_id(),
            space_id=space_id,
            run_id=run_id,
            artifact_type=artifact_type,
            title=title,
            content=_json_dump(payload),
            mime_type="application/json",
            metadata_json=dict(metadata_json or {}),
        )
        self._db.add(artifact)
        self._db.flush()
        return artifact

    def run(
        self,
        *,
        target_id: str,
        space_id: str,
        user_id: str,
        engine_name: str = "llm_prompt_review",
    ) -> EvolutionRunResult:
        if engine_name not in EVOLUTION_ENGINE_NAMES:
            raise ValueError(f"Unknown evolution engine {engine_name!r}")
        target = EvolutionTargetRegistry(self._db).get_target(target_id, space_id=space_id)
        if target is None:
            raise ValueError("Evolution target not found")
        if not target.enabled or target.status != "active":
            raise ValueError("Evolution target is not active")
        signal_count = (
            self._db.query(EvolutionSignal)
            .filter(EvolutionSignal.space_id == space_id, EvolutionSignal.target_id == target.id)
            .count()
        )
        if signal_count == 0:
            raise ValueError("Evolution review requires at least one signal for this target")

        allowed = (target.engine_policy_json or {}).get("allowed_engines") or ["llm_prompt_review"]
        if engine_name not in allowed:
            raise ValueError(f"Engine {engine_name!r} is not allowed for this target")
        try:
            provider = ModelService().resolve_default_config(self._db, space_id)
        except Exception as exc:
            raise ValueError(f"Default model provider unavailable: {exc}") from exc
        engine = get_engine(
            engine_name,
            self._db,
            provider_id=provider.id,
            model=provider.default_model,
            api_key=provider.api_key,
        )
        if not engine.supports(target.target_type):
            raise ValueError(f"Engine {engine_name!r} does not support target_type {target.target_type!r}")

        agent_id, agent_version_id = _ensure_system_evolution_agent(self._db, space_id)
        now = _utcnow()
        run = Run(
            id=_new_id(),
            space_id=space_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            run_type="evolution",
            trigger_origin="manual",
            source="managed",
            mode="live",
            status="running",
            instructed_by_user_id=user_id,
            prompt=f"Run {engine_name} for {target.capability_key or target.target_type}",
            started_at=now,
            capability_id=target.capability_key,
        )
        self._db.add(run)
        self._db.flush()

        context = EvolutionContextBuilder(self._db).build(
            target=target,
            space_id=space_id,
            user_id=user_id,
            run_id=run.id,
        )
        try:
            engine_output = engine.run(context.payload)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"LLM evolution provider call failed: {exc}") from exc
        revision_prompt = (engine_output.prompt_revision or {}).get("prompt")
        if not isinstance(revision_prompt, str) or not revision_prompt.strip():
            raise ValueError(
                "Evolution review produced no prompt revision; "
                "add at least one actionable signal before creating a proposal"
            )
        report_artifact = self._create_artifact(
            space_id=space_id,
            run_id=run.id,
            artifact_type="evolution_report",
            title=f"Evolution report: {target.capability_key or target.target_type}",
            payload=engine_output.report,
            metadata_json={
                "target_id": target.id,
                "engine": engine_output.engine,
                "engine_metadata": dict(engine_output.metadata or {}),
                "context_artifact_id": context.artifact.id,
            },
        )
        revision_artifact = self._create_artifact(
            space_id=space_id,
            run_id=run.id,
            artifact_type="prompt_revision",
            title=f"Prompt revision: {target.capability_key or target.target_type}",
            payload=engine_output.prompt_revision,
            metadata_json={
                "target_id": target.id,
                "engine": engine_output.engine,
                "engine_metadata": dict(engine_output.metadata or {}),
                "context_artifact_id": context.artifact.id,
                "report_artifact_id": report_artifact.id,
            },
        )
        proposal = EvolutionProposalService(self._db).create_prompt_update_proposal(
            target=target,
            space_id=space_id,
            user_id=user_id,
            run_id=run.id,
            engine_output=engine_output,
            context_artifact=context.artifact,
            report_artifact=report_artifact,
            revision_artifact=revision_artifact,
        )
        run.status = "succeeded"
        run.ended_at = _utcnow()
        run.output_json = {
            "target_id": target.id,
            "engine": engine_output.engine,
            "context_artifact_id": context.artifact.id,
            "report_artifact_id": report_artifact.id,
            "revision_artifact_id": revision_artifact.id,
            "proposal_id": proposal.id,
        }
        self._db.commit()
        for row in (run, context.artifact, report_artifact, revision_artifact, proposal):
            self._db.refresh(row)
        return EvolutionRunResult(
            run=run,
            context_artifact=context.artifact,
            report_artifact=report_artifact,
            revision_artifact=revision_artifact,
            proposal=proposal,
        )
