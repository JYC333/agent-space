from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..models import Artifact, EvolutionSignal, EvolutionTarget, Proposal, Run
from .constants import EVOLUTION_TARGET_TYPES
from .services import EvolutionRunService, EvolutionSignalService, EvolutionTargetRegistry
from .validation import ValidationResult, evaluate_target_validation

router = APIRouter(prefix="/evolution", tags=["evolution"])

EVOLUTION_PROPOSAL_TYPES = frozenset({
    "prompt_update",
    "capability_update",
    "agent_config_update",
    "workflow_update",
    "policy_update",
})


class EvolutionSummaryOut(BaseModel):
    active_targets: int
    signals_collected: int
    pending_proposals: int
    recent_runs: int


class EvolutionTargetOut(BaseModel):
    id: str
    space_id: str | None = None
    target_name: str | None = None
    target_type: str
    target_ref_type: str | None = None
    target_ref_id: str | None = None
    capability_key: str | None = None
    current_version_id: str | None = None
    current_version: str | None = None
    scope: str | None = None
    purpose: str | None = None
    risk_level: str
    status: str
    enabled: bool
    recent_signal_count: int = 0
    last_run_at: datetime | None = None
    engine_policy_json: dict[str, Any] = Field(default_factory=dict)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EvolutionTargetCreate(BaseModel):
    target_type: str
    target_ref_type: str | None = None
    target_ref_id: str | None = None
    capability_key: str | None = None
    current_version_id: str | None = None
    risk_level: str = "medium"
    enabled: bool = True
    status: str = "active"
    target_name: str | None = None
    purpose: str | None = None
    engine_policy_json: dict[str, Any] = Field(default_factory=lambda: {
        "allowed_engines": ["llm_prompt_review"],
        "allowed_proposal_types": ["prompt_update"],
    })
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class EvolutionTargetUpdate(BaseModel):
    target_type: str | None = None
    target_ref_type: str | None = None
    target_ref_id: str | None = None
    capability_key: str | None = None
    current_version_id: str | None = None
    risk_level: str | None = None
    enabled: bool | None = None
    status: str | None = None
    target_name: str | None = None
    purpose: str | None = None
    engine_policy_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None


class EvolutionSignalCreate(BaseModel):
    signal_type: str
    source_type: str
    source_id: str | None = None
    severity: str = "medium"
    summary: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)


class EvolutionSignalOut(BaseModel):
    id: str
    space_id: str | None = None
    target_id: str
    target_name: str | None = None
    target_type: str | None = None
    capability_key: str | None = None
    signal_type: str
    source_type: str
    source_id: str | None = None
    severity: str
    summary: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class EvolutionRunCreate(BaseModel):
    engine: str = "llm_prompt_review"


class EvolutionRunOut(BaseModel):
    run_id: str
    target_id: str
    context_artifact_id: str
    report_artifact_id: str
    revision_artifact_id: str
    proposal_id: str
    proposal_type: str
    run_status: str


class EvolutionRunListItem(BaseModel):
    run_id: str
    target_id: str | None = None
    target_name: str | None = None
    target_type: str | None = None
    capability_key: str | None = None
    engine: str | None = None
    status: str
    created_at: datetime
    started_at: datetime | None = None
    artifact_count: int = 0
    proposal_id: str | None = None


class EvolutionProposalOut(BaseModel):
    id: str
    proposal_type: str
    target_id: str | None = None
    target_name: str | None = None
    target_type: str | None = None
    capability_key: str | None = None
    status: str
    summary: str | None = None
    created_at: datetime
    created_by_run_id: str | None = None


class EvolutionValidationResultOut(BaseModel):
    metric_id: str
    label: str
    evaluator: str
    target_id: str
    target_name: str | None = None
    value: Any | None = None
    status: str
    window: str | None = None
    goal: dict[str, Any] = Field(default_factory=dict)
    sample_size: int = 0
    numerator_count: int | None = None
    denominator_count: int | None = None
    updated_at: datetime | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


def _display_name_for_target(target: EvolutionTarget) -> str:
    meta = target.metadata_json or {}
    explicit = meta.get("name") or meta.get("display_name")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if target.capability_key == "capture-memory-extraction":
        return "Capture Memory Extraction"
    raw = target.capability_key or target.target_ref_id or target.target_type
    return str(raw).replace("-", " ").replace("_", " ").title()


def _purpose_for_target(target: EvolutionTarget) -> str | None:
    meta = target.metadata_json or {}
    purpose = meta.get("purpose")
    if target.capability_key == "capture-memory-extraction":
        return "Improves how raw captures are classified into memory, wiki, task, or unresolved candidates."
    return purpose if isinstance(purpose, str) else None


def _scope_for_target(target: EvolutionTarget) -> str:
    return "system" if target.space_id is None else "space"


def _visible_targets(db: Session, space_id: str) -> list[EvolutionTarget]:
    svc = EvolutionTargetRegistry(db)
    rows = svc.list_targets(space_id=space_id, include_system=True)
    db.commit()
    return rows


def _target_maps(targets: list[EvolutionTarget]) -> tuple[dict[str, EvolutionTarget], dict[str, str]]:
    by_id = {target.id: target for target in targets}
    names = {target.id: _display_name_for_target(target) for target in targets}
    return by_id, names


def _signal_counts_by_target(db: Session, target_ids: list[str], space_id: str) -> dict[str, int]:
    if not target_ids:
        return {}
    rows = (
        db.query(EvolutionSignal.target_id, func.count(EvolutionSignal.id))
        .filter(EvolutionSignal.target_id.in_(target_ids), EvolutionSignal.space_id == space_id)
        .group_by(EvolutionSignal.target_id)
        .all()
    )
    return {target_id: int(count) for target_id, count in rows}


def _last_run_at_by_target(db: Session, space_id: str) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    rows = (
        db.query(Run)
        .filter(Run.space_id == space_id, Run.run_type == "evolution")
        .order_by(Run.created_at.desc())
        .all()
    )
    for run in rows:
        payload = run.output_json or {}
        target_id = payload.get("target_id")
        if isinstance(target_id, str) and target_id not in out:
            out[target_id] = run.started_at or run.created_at
    return out


def _target_out(
    target: EvolutionTarget,
    *,
    recent_signal_count: int = 0,
    last_run_at: datetime | None = None,
) -> EvolutionTargetOut:
    current_version = target.current_version.version if target.current_version is not None else None
    return EvolutionTargetOut(
        id=target.id,
        space_id=target.space_id,
        target_name=_display_name_for_target(target),
        target_type=target.target_type,
        target_ref_type=target.target_ref_type,
        target_ref_id=target.target_ref_id,
        capability_key=target.capability_key,
        current_version_id=target.current_version_id,
        current_version=current_version,
        scope=_scope_for_target(target),
        purpose=_purpose_for_target(target),
        risk_level=target.risk_level,
        status=target.status,
        enabled=target.enabled,
        recent_signal_count=recent_signal_count,
        last_run_at=last_run_at,
        engine_policy_json=dict(target.engine_policy_json or {}),
        metadata_json=dict(target.metadata_json or {}),
        created_at=target.created_at,
        updated_at=target.updated_at,
    )


def _metadata_with_display_fields(
    metadata_json: dict[str, Any],
    *,
    target_name: str | None = None,
    purpose: str | None = None,
) -> dict[str, Any]:
    meta = dict(metadata_json or {})
    if target_name is not None:
        if target_name.strip():
            meta["display_name"] = target_name.strip()
        else:
            meta.pop("display_name", None)
            meta.pop("name", None)
    if purpose is not None:
        if purpose.strip():
            meta["purpose"] = purpose.strip()
        else:
            meta.pop("purpose", None)
    return meta


def _metadata_with_origin(
    metadata_json: dict[str, Any],
    *,
    origin_type: str,
    source_target_id: str | None = None,
) -> dict[str, Any]:
    meta = dict(metadata_json or {})
    origin: dict[str, Any] = {"type": origin_type}
    if source_target_id:
        origin["source_target_id"] = source_target_id
    meta["origin"] = origin
    return meta


def _resolve_target_update_values(
    target: EvolutionTarget,
    body: EvolutionTargetUpdate,
) -> dict[str, Any]:
    fields_set = body.model_fields_set
    target_type = body.target_type or target.target_type
    if target_type not in EVOLUTION_TARGET_TYPES:
        raise ValueError(f"Unsupported evolution target_type {target_type!r}")
    metadata = (
        dict(body.metadata_json or {})
        if "metadata_json" in fields_set
        else dict(target.metadata_json or {})
    )
    return {
        "target_type": target_type,
        "target_ref_type": body.target_ref_type if "target_ref_type" in fields_set else target.target_ref_type,
        "target_ref_id": body.target_ref_id if "target_ref_id" in fields_set else target.target_ref_id,
        "capability_key": body.capability_key if "capability_key" in fields_set else target.capability_key,
        "current_version_id": body.current_version_id if "current_version_id" in fields_set else target.current_version_id,
        "risk_level": body.risk_level if body.risk_level is not None else target.risk_level,
        "enabled": body.enabled if body.enabled is not None else target.enabled,
        "status": body.status if body.status is not None else target.status,
        "engine_policy_json": (
            dict(body.engine_policy_json)
            if body.engine_policy_json is not None
            else dict(target.engine_policy_json or {})
        ),
        "metadata_json": _metadata_with_display_fields(
            metadata,
            target_name=body.target_name,
            purpose=body.purpose,
        ),
    }


def _apply_target_update_values(target: EvolutionTarget, values: dict[str, Any]) -> None:
    target.target_type = values["target_type"]
    target.target_ref_type = values["target_ref_type"] or None
    target.target_ref_id = values["target_ref_id"] or None
    target.capability_key = values["capability_key"] or None
    target.current_version_id = values["current_version_id"] or None
    target.risk_level = values["risk_level"]
    target.enabled = values["enabled"]
    target.status = values["status"]
    target.engine_policy_json = dict(values["engine_policy_json"] or {})
    target.metadata_json = dict(values["metadata_json"] or {})


def _signal_out(signal: EvolutionSignal, target: EvolutionTarget | None) -> EvolutionSignalOut:
    return EvolutionSignalOut(
        id=signal.id,
        space_id=signal.space_id,
        target_id=signal.target_id,
        target_name=_display_name_for_target(target) if target is not None else None,
        target_type=target.target_type if target is not None else None,
        capability_key=target.capability_key if target is not None else None,
        signal_type=signal.signal_type,
        source_type=signal.source_type,
        source_id=signal.source_id,
        severity=signal.severity,
        summary=signal.summary,
        payload_json=dict(signal.payload_json or {}),
        created_at=signal.created_at,
    )


def _artifact_counts_by_run(db: Session, run_ids: list[str]) -> dict[str, int]:
    if not run_ids:
        return {}
    rows = (
        db.query(Artifact.run_id, func.count(Artifact.id))
        .filter(Artifact.run_id.in_(run_ids))
        .group_by(Artifact.run_id)
        .all()
    )
    return {run_id: int(count) for run_id, count in rows if run_id is not None}


def _run_list_item(
    run: Run,
    *,
    target: EvolutionTarget | None,
    artifact_count: int,
) -> EvolutionRunListItem:
    payload = run.output_json or {}
    target_id = payload.get("target_id")
    return EvolutionRunListItem(
        run_id=run.id,
        target_id=target_id if isinstance(target_id, str) else None,
        target_name=_display_name_for_target(target) if target is not None else None,
        target_type=target.target_type if target is not None else None,
        capability_key=target.capability_key if target is not None else None,
        engine=payload.get("engine") if isinstance(payload.get("engine"), str) else None,
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        artifact_count=artifact_count,
        proposal_id=payload.get("proposal_id") if isinstance(payload.get("proposal_id"), str) else None,
    )


def _target_id_for_proposal(proposal: Proposal, run_by_id: dict[str, Run]) -> str | None:
    payload = proposal.payload_json or {}
    target_id = payload.get("target_id")
    if isinstance(target_id, str):
        return target_id
    if proposal.created_by_run_id:
        run = run_by_id.get(proposal.created_by_run_id)
        run_target = (run.output_json or {}).get("target_id") if run is not None else None
        if isinstance(run_target, str):
            return run_target
    return None


def _evolution_proposals(db: Session, space_id: str, *, limit: int = 100) -> list[Proposal]:
    run_rows = (
        db.query(Run)
        .filter(Run.space_id == space_id, Run.run_type == "evolution")
        .order_by(Run.created_at.desc())
        .limit(500)
        .all()
    )
    run_ids = {run.id for run in run_rows}
    rows = (
        db.query(Proposal)
        .filter(Proposal.space_id == space_id, Proposal.proposal_type.in_(EVOLUTION_PROPOSAL_TYPES))
        .order_by(Proposal.created_at.desc())
        .limit(max(limit, 100))
        .all()
    )
    out = []
    for proposal in rows:
        payload = proposal.payload_json or {}
        if isinstance(payload.get("target_id"), str) or proposal.created_by_run_id in run_ids:
            out.append(proposal)
        if len(out) >= limit:
            break
    return out


@router.get("/summary", response_model=EvolutionSummaryOut)
def get_summary(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    targets = _visible_targets(db, space_id)
    target_ids = [target.id for target in targets]
    active_targets = sum(1 for target in targets if target.enabled and target.status == "active")
    signals_collected = (
        db.query(func.count(EvolutionSignal.id))
        .filter(EvolutionSignal.space_id == space_id, EvolutionSignal.target_id.in_(target_ids))
        .scalar()
        if target_ids
        else 0
    )
    pending_proposals = sum(1 for p in _evolution_proposals(db, space_id, limit=500) if p.status == "pending")
    recent_runs = (
        db.query(func.count(Run.id))
        .filter(Run.space_id == space_id, Run.run_type == "evolution")
        .scalar()
    )
    return EvolutionSummaryOut(
        active_targets=active_targets,
        signals_collected=int(signals_collected or 0),
        pending_proposals=pending_proposals,
        recent_runs=int(recent_runs or 0),
    )


@router.get("/targets", response_model=list[EvolutionTargetOut])
def list_targets(
    status: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    rows = _visible_targets(db, space_id)
    if status:
        rows = [row for row in rows if row.status == status]
    counts = _signal_counts_by_target(db, [row.id for row in rows], space_id)
    last_run_at = _last_run_at_by_target(db, space_id)
    return [
        _target_out(row, recent_signal_count=counts.get(row.id, 0), last_run_at=last_run_at.get(row.id))
        for row in rows
    ]


@router.post("/targets", response_model=EvolutionTargetOut, status_code=201)
def create_target(
    body: EvolutionTargetCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    metadata_json = _metadata_with_display_fields(
        body.metadata_json,
        target_name=body.target_name,
        purpose=body.purpose,
    )
    origin = metadata_json.get("origin")
    if not isinstance(origin, dict) or origin.get("type") != "clone":
        metadata_json = _metadata_with_origin(metadata_json, origin_type="clone")
    try:
        target = EvolutionTargetRegistry(db).register(
            target_type=body.target_type,
            space_id=space_id,
            target_ref_type=body.target_ref_type,
            target_ref_id=body.target_ref_id,
            capability_key=body.capability_key,
            current_version_id=body.current_version_id,
            risk_level=body.risk_level,
            enabled=body.enabled,
            engine_policy_json=body.engine_policy_json,
            metadata_json=metadata_json,
            status=body.status,
            upsert=False,
        )
        db.commit()
        db.refresh(target)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _target_out(target)


@router.get("/targets/{target_id}", response_model=EvolutionTargetOut)
def get_target(
    target_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    target = EvolutionTargetRegistry(db).get_target(target_id, space_id=space_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Evolution target not found")
    counts = _signal_counts_by_target(db, [target.id], space_id)
    last_run_at = _last_run_at_by_target(db, space_id)
    return _target_out(
        target,
        recent_signal_count=counts.get(target.id, 0),
        last_run_at=last_run_at.get(target.id),
    )


@router.patch("/targets/{target_id}", response_model=EvolutionTargetOut)
def update_target(
    target_id: str,
    body: EvolutionTargetUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    target = EvolutionTargetRegistry(db).get_target(target_id, space_id=space_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Evolution target not found")
    try:
        values = _resolve_target_update_values(target, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if target.space_id is None:
        values["metadata_json"] = _metadata_with_origin(
            values["metadata_json"],
            origin_type="system_override",
            source_target_id=target.id,
        )
        target = EvolutionTargetRegistry(db).register(
            target_type=values["target_type"],
            space_id=space_id,
            target_ref_type=values["target_ref_type"] or None,
            target_ref_id=values["target_ref_id"] or None,
            capability_key=values["capability_key"] or None,
            current_version_id=values["current_version_id"] or None,
            risk_level=values["risk_level"],
            enabled=values["enabled"],
            engine_policy_json=values["engine_policy_json"],
            metadata_json=values["metadata_json"],
            status=values["status"],
        )
    _apply_target_update_values(target, values)
    db.commit()
    db.refresh(target)
    counts = _signal_counts_by_target(db, [target.id], space_id)
    last_run_at = _last_run_at_by_target(db, space_id)
    return _target_out(
        target,
        recent_signal_count=counts.get(target.id, 0),
        last_run_at=last_run_at.get(target.id),
    )


@router.post("/targets/{target_id}/signals", response_model=EvolutionSignalOut, status_code=201)
def create_signal(
    target_id: str,
    body: EvolutionSignalCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    if EvolutionTargetRegistry(db).get_target(target_id, space_id=space_id) is None:
        raise HTTPException(status_code=404, detail="Evolution target not found")
    try:
        signal = EvolutionSignalService(db).create_signal(
            space_id=space_id,
            target_id=target_id,
            signal_type=body.signal_type,
            source_type=body.source_type,
            source_id=body.source_id,
            severity=body.severity,
            summary=body.summary,
            payload_json=body.payload_json,
        )
        db.commit()
        db.refresh(signal)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    target = EvolutionTargetRegistry(db).get_target(target_id, space_id=space_id)
    return _signal_out(signal, target)


@router.get("/targets/{target_id}/signals", response_model=list[EvolutionSignalOut])
def list_signals(
    target_id: str,
    signal_type: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    if EvolutionTargetRegistry(db).get_target(target_id, space_id=space_id) is None:
        raise HTTPException(status_code=404, detail="Evolution target not found")
    target = EvolutionTargetRegistry(db).get_target(target_id, space_id=space_id)
    rows = EvolutionSignalService(db).list_signals(
        target_id=target_id,
        space_id=space_id,
        signal_type=signal_type,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return [_signal_out(row, target) for row in rows]


@router.get("/signals", response_model=list[EvolutionSignalOut])
def list_all_signals(
    signal_type: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    targets = _visible_targets(db, space_id)
    by_id, _ = _target_maps(targets)
    target_ids = list(by_id)
    if not target_ids:
        return []
    q = db.query(EvolutionSignal).filter(
        EvolutionSignal.space_id == space_id,
        EvolutionSignal.target_id.in_(target_ids),
    )
    if signal_type:
        q = q.filter(EvolutionSignal.signal_type == signal_type)
    if severity:
        q = q.filter(EvolutionSignal.severity == severity)
    rows = q.order_by(EvolutionSignal.created_at.desc()).offset(offset).limit(limit).all()
    return [_signal_out(row, by_id.get(row.target_id)) for row in rows]


@router.get("/runs", response_model=list[EvolutionRunListItem])
def list_runs(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    targets = _visible_targets(db, space_id)
    by_id, _ = _target_maps(targets)
    rows = (
        db.query(Run)
        .filter(Run.space_id == space_id, Run.run_type == "evolution")
        .order_by(Run.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    counts = _artifact_counts_by_run(db, [row.id for row in rows])
    out: list[EvolutionRunListItem] = []
    for row in rows:
        target_id = (row.output_json or {}).get("target_id")
        target = by_id.get(target_id) if isinstance(target_id, str) else None
        out.append(_run_list_item(row, target=target, artifact_count=counts.get(row.id, 0)))
    return out


@router.get("/proposals", response_model=list[EvolutionProposalOut])
def list_proposals(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    targets = _visible_targets(db, space_id)
    by_id, _ = _target_maps(targets)
    run_rows = (
        db.query(Run)
        .filter(Run.space_id == space_id, Run.run_type == "evolution")
        .order_by(Run.created_at.desc())
        .limit(500)
        .all()
    )
    run_by_id = {run.id: run for run in run_rows}
    proposals = _evolution_proposals(db, space_id, limit=limit + offset)
    page = proposals[offset : offset + limit]
    out = []
    for proposal in page:
        target_id = _target_id_for_proposal(proposal, run_by_id)
        target = by_id.get(target_id) if target_id is not None else None
        out.append(EvolutionProposalOut(
            id=proposal.id,
            proposal_type=proposal.proposal_type,
            target_id=target_id,
            target_name=_display_name_for_target(target) if target is not None else None,
            target_type=target.target_type if target is not None else None,
            capability_key=target.capability_key if target is not None else None,
            status=proposal.status,
            summary=proposal.summary or proposal.title,
            created_at=proposal.created_at,
            created_by_run_id=proposal.created_by_run_id,
        ))
    return out


def _validation_result_out(
    result: ValidationResult,
    target: EvolutionTarget,
) -> EvolutionValidationResultOut:
    return EvolutionValidationResultOut(
        metric_id=result.metric_id,
        label=result.label,
        evaluator=result.evaluator,
        target_id=result.target_id,
        target_name=_display_name_for_target(target),
        value=result.value,
        status=result.status,
        window=result.window,
        goal=result.goal,
        sample_size=result.sample_size,
        numerator_count=result.numerator_count,
        denominator_count=result.denominator_count,
        updated_at=result.updated_at,
        metadata_json=result.metadata_json,
    )


@router.get("/validation", response_model=list[EvolutionValidationResultOut])
def list_validation_results(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    targets = _visible_targets(db, space_id)
    rows: list[EvolutionValidationResultOut] = []
    for target in targets:
        rows.extend(
            _validation_result_out(result, target)
            for result in evaluate_target_validation(db, target, space_id=space_id)
        )
    return rows


@router.post("/targets/{target_id}/run", response_model=EvolutionRunOut, status_code=201)
def run_evolution(
    target_id: str,
    body: EvolutionRunCreate | None = None,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    engine = body.engine if body else "llm_prompt_review"
    try:
        result = EvolutionRunService(db).run(
            target_id=target_id,
            space_id=space_id,
            user_id=user_id,
            engine_name=engine,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EvolutionRunOut(
        run_id=result.run.id,
        target_id=target_id,
        context_artifact_id=result.context_artifact.id,
        report_artifact_id=result.report_artifact.id,
        revision_artifact_id=result.revision_artifact.id,
        proposal_id=result.proposal.id,
        proposal_type=result.proposal.proposal_type,
        run_status=result.run.status,
    )
