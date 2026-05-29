"""Canonical Intake and Evidence API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..policy.gateway import PolicyCheckRequest, PolicyGateway
from ..schemas import Page
from ..activity.input_summary_service import (
    InputSummaryProviderMissingError,
    InputSummaryProviderCallError,
    InputSummaryNoContentError,
    InputSummaryCrossSpaceError,
    InputSummaryService,
)
from .schemas import (
    EvidenceLinkCreate,
    EvidenceLinkOut,
    ExtractedEvidenceCreate,
    ExtractedEvidenceOut,
    ExtractedEvidenceUpdate,
    ExtractionJobOut,
    IntakeItemActionIn,
    IntakeItemOut,
    ManualURLCreate,
    SourceConnectionCreate,
    SourceConnectionOut,
    SourceConnectionUpdate,
    SourceConnectorOut,
    WorkspaceIntakeProfileCreate,
    WorkspaceIntakeProfileOut,
    WorkspaceSourceBindingCreate,
    WorkspaceSourceBindingOut,
)
from .service import (
    ExtractionJobNotFound,
    ExtractionJobStateError,
    IntakeDuplicateError,
    IntakeNotFound,
    IntakeService,
    IntakeValidationError,
)

router = APIRouter(prefix="/intake", tags=["intake"])


def _assert_space(requested: str, identity_space: str) -> None:
    if requested != identity_space:
        raise HTTPException(status_code=403, detail="Cross-space access denied")


def _enforce(
    db: Session,
    *,
    action: str,
    actor_id: str,
    space_id: str,
    resource_type: str,
    resource_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    PolicyGateway(db).enforce(
        PolicyCheckRequest(
            action=action,
            actor_type="user",
            actor_id=actor_id,
            space_id=space_id,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata or {},
        )
    )


def _raise_service_http(
    exc: Exception,
    *,
    intake_not_found_detail: str = "Resource not found",
    extraction_not_found_detail: str = "Extraction job not found",
) -> None:
    if isinstance(exc, IntakeDuplicateError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, IntakeValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, IntakeNotFound):
        raise HTTPException(status_code=404, detail=intake_not_found_detail) from exc
    if isinstance(exc, ExtractionJobNotFound):
        raise HTTPException(status_code=404, detail=extraction_not_found_detail) from exc
    if isinstance(exc, ExtractionJobStateError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.get("/connectors", response_model=list[SourceConnectorOut])
def list_connectors(
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    return IntakeService(db).list_connectors()


@router.post("/connections", response_model=SourceConnectionOut, status_code=201)
def create_connection(
    body: SourceConnectionCreate,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(db, action="intake.connection_manage", actor_id=user_id, space_id=space_id, resource_type="source_connection")
    try:
        row = IntakeService(db).create_connection(
            space_id=space_id,
            owner_user_id=user_id,
            connector_key=body.connector_key,
            name=body.name,
            endpoint_url=body.endpoint_url,
            credential_id=body.credential_id,
            fetch_frequency=body.fetch_frequency,
            capture_policy=body.capture_policy,
            trust_level=body.trust_level,
            topic_hints=body.topic_hints,
            consent=body.consent,
            policy=body.policy,
            config=body.config,
        )
        db.commit()
    except (IntakeNotFound, IntakeDuplicateError, IntakeValidationError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Credential not found")
    return row


@router.get("/connections", response_model=Page[SourceConnectionOut])
def list_connections(
    space_id: str = Query(...),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    total, rows = IntakeService(db).list_connections(space_id, status=status, limit=limit, offset=offset)
    return Page(total=total, items=rows, limit=limit, offset=offset)


@router.patch("/connections/{connection_id}", response_model=SourceConnectionOut)
def update_connection(
    connection_id: str,
    body: SourceConnectionUpdate,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(
        db,
        action="intake.connection_manage",
        actor_id=user_id,
        space_id=space_id,
        resource_type="source_connection",
        resource_id=connection_id,
    )
    try:
        row = IntakeService(db).update_connection(
            space_id,
            connection_id,
            name=body.name,
            status=body.status,
            credential_id=body.credential_id,
            fetch_frequency=body.fetch_frequency,
            capture_policy=body.capture_policy,
            trust_level=body.trust_level,
            topic_hints=body.topic_hints,
            consent=body.consent,
            policy=body.policy,
            config=body.config,
        )
        db.commit()
    except (IntakeNotFound, IntakeDuplicateError, IntakeValidationError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Connection not found")
    return row


@router.post("/connections/{connection_id}/scan", response_model=ExtractionJobOut)
def scan_connection(
    connection_id: str,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(
        db,
        action="intake.item_create",
        actor_id=user_id,
        space_id=space_id,
        resource_type="source_connection",
        resource_id=connection_id,
    )
    try:
        job = IntakeService(db).scan_connection(space_id, connection_id)
        db.commit()
    except (IntakeNotFound, IntakeValidationError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Connection not found")
    return job


@router.get("/items", response_model=Page[IntakeItemOut])
def list_items(
    space_id: str = Query(...),
    status: str | None = Query(None),
    read_status: str | None = Query(None),
    content_state: str | None = Query(None),
    connection_id: str | None = Query(None),
    source_domain: str | None = Query(None),
    created_after: datetime | None = Query(None),
    occurred_after: datetime | None = Query(None),
    include_ignored: bool = Query(False),
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    total, rows = IntakeService(db).list_items(
        space_id,
        status=status,
        read_status=read_status,
        content_state=content_state,
        connection_id=connection_id,
        source_domain=source_domain,
        created_after=created_after,
        occurred_after=occurred_after,
        include_ignored=include_ignored,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return Page(total=total, items=rows, limit=limit, offset=offset)


@router.get("/items/{item_id}", response_model=IntakeItemOut)
def get_item(
    item_id: str,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    try:
        return IntakeService(db).get_item(space_id, item_id)
    except IntakeNotFound as exc:
        _raise_service_http(exc, intake_not_found_detail="Intake item not found")


@router.post("/items/manual-url", response_model=IntakeItemOut, status_code=201)
def create_manual_url(
    body: ManualURLCreate,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(db, action="intake.item_create", actor_id=user_id, space_id=space_id, resource_type="intake_item")
    try:
        item, _job = IntakeService(db).fetch_manual_url(
            space_id=space_id,
            url=body.url,
            title=body.title,
            connection_id=body.connection_id,
            queue_content=body.queue_content,
        )
        db.commit()
    except (IntakeNotFound, IntakeValidationError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Connection not found")
    return item


@router.post("/items/{item_id}/actions", response_model=IntakeItemOut)
def item_action(
    item_id: str,
    body: IntakeItemActionIn,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    svc = IntakeService(db)
    try:
        if body.action == "queue_content":
            _enforce(db, action="intake.item_create", actor_id=user_id, space_id=space_id, resource_type="extraction_job")
            svc.create_pending_extract_text(space_id, item_id)
        elif body.action == "archive_snapshot":
            _enforce(db, action="intake.item_create", actor_id=user_id, space_id=space_id, resource_type="extraction_job")
            svc.create_pending_snapshot(space_id, item_id)
        elif body.action == "read_later":
            _enforce(db, action="intake.item_update", actor_id=user_id, space_id=space_id, resource_type="intake_item", resource_id=item_id)
            svc.mark_read_later(space_id, item_id)
        elif body.action == "mark_selected":
            _enforce(db, action="intake.item_update", actor_id=user_id, space_id=space_id, resource_type="intake_item", resource_id=item_id)
            svc.mark_selected(space_id, item_id)
        elif body.action == "mark_ignored":
            _enforce(db, action="intake.item_update", actor_id=user_id, space_id=space_id, resource_type="intake_item", resource_id=item_id)
            svc.mark_ignored(space_id, item_id)
        elif body.action == "mark_discussed":
            _enforce(db, action="intake.item_update", actor_id=user_id, space_id=space_id, resource_type="intake_item", resource_id=item_id)
            svc.mark_discussed(space_id, item_id)
        elif body.action == "extract_evidence":
            _enforce(db, action="evidence.create", actor_id=user_id, space_id=space_id, resource_type="evidence")
            svc.create_evidence_from_item(space_id, item_id, created_by_user_id=user_id)
        db.commit()
        return svc.get_item(space_id, item_id)
    except (IntakeNotFound, IntakeValidationError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Intake item not found")


@router.get("/jobs", response_model=Page[ExtractionJobOut])
def list_jobs(
    space_id: str = Query(...),
    status: str | None = Query(None),
    intake_item_id: str | None = Query(None),
    connection_id: str | None = Query(None),
    job_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    total, rows = IntakeService(db).list_jobs(
        space_id,
        status=status,
        intake_item_id=intake_item_id,
        connection_id=connection_id,
        job_type=job_type,
        limit=limit,
        offset=offset,
    )
    return Page(total=total, items=rows, limit=limit, offset=offset)


@router.post("/jobs/{job_id}/run", response_model=ExtractionJobOut)
def run_job(
    job_id: str,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(db, action="evidence.create", actor_id=user_id, space_id=space_id, resource_type="extraction_job", resource_id=job_id)
    try:
        job = IntakeService(db).run_pending_job(job_id, space_id)
        db.commit()
    except (ExtractionJobNotFound, ExtractionJobStateError, IntakeValidationError) as exc:
        _raise_service_http(exc)
    return job


@router.get("/evidence", response_model=Page[ExtractedEvidenceOut])
def list_evidence(
    space_id: str = Query(...),
    status: str | None = Query(None),
    evidence_type: str | None = Query(None),
    intake_item_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    total, rows = IntakeService(db).list_evidence(
        space_id,
        status=status,
        evidence_type=evidence_type,
        intake_item_id=intake_item_id,
        limit=limit,
        offset=offset,
    )
    return Page(total=total, items=rows, limit=limit, offset=offset)


@router.post("/evidence", response_model=ExtractedEvidenceOut, status_code=201)
def create_evidence(
    body: ExtractedEvidenceCreate,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(db, action="evidence.create", actor_id=user_id, space_id=space_id, resource_type="evidence")
    try:
        row = IntakeService(db).create_evidence(
            space_id=space_id,
            intake_item_id=body.intake_item_id,
            source_object_type=body.source_object_type,
            source_object_id=body.source_object_id,
            evidence_type=body.evidence_type,
            title=body.title,
            content_excerpt=body.content_excerpt,
            artifact_id=body.artifact_id,
            source_uri=body.source_uri,
            trust_level=body.trust_level,
            extraction_method=body.extraction_method,
            confidence=body.confidence,
            status=body.status,
            metadata=body.metadata,
            created_by_user_id=user_id,
        )
        db.commit()
    except (IntakeDuplicateError, IntakeValidationError, IntakeNotFound) as exc:
        _raise_service_http(exc, intake_not_found_detail="Referenced intake/evidence source not found")
    return row


@router.patch("/evidence/{evidence_id}", response_model=ExtractedEvidenceOut)
def update_evidence(
    evidence_id: str,
    body: ExtractedEvidenceUpdate,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(db, action="evidence.update", actor_id=user_id, space_id=space_id, resource_type="evidence", resource_id=evidence_id)
    try:
        row = IntakeService(db).update_evidence(
            space_id,
            evidence_id,
            status=body.status,
            confidence=body.confidence,
            metadata=body.metadata,
        )
        db.commit()
    except (IntakeNotFound, IntakeValidationError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Evidence not found")
    return row


@router.get("/evidence-links", response_model=Page[EvidenceLinkOut])
def list_evidence_links(
    space_id: str = Query(...),
    evidence_id: str | None = Query(None),
    target_type: str | None = Query(None),
    target_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    total, rows = IntakeService(db).list_evidence_links(
        space_id,
        evidence_id=evidence_id,
        target_type=target_type,
        target_id=target_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return Page(total=total, items=rows, limit=limit, offset=offset)


@router.post("/evidence-links", response_model=EvidenceLinkOut, status_code=201)
def create_evidence_link(
    body: EvidenceLinkCreate,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(db, action="evidence.link", actor_id=user_id, space_id=space_id, resource_type="evidence", resource_id=body.evidence_id)
    try:
        row = IntakeService(db).create_evidence_link(
            space_id=space_id,
            evidence_id=body.evidence_id,
            target_type=body.target_type,
            target_id=body.target_id,
            link_type=body.link_type,
            status=body.status,
            confidence=body.confidence,
            reason=body.reason,
            created_by_user_id=user_id,
        )
        db.commit()
    except (IntakeNotFound, IntakeValidationError, IntakeDuplicateError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Evidence target not found")
    return row


@router.get("/workspace-profiles", response_model=list[WorkspaceIntakeProfileOut])
def list_workspace_profiles(
    space_id: str = Query(...),
    workspace_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    return IntakeService(db).list_workspace_profiles(space_id, workspace_id=workspace_id)


@router.post("/workspace-profiles", response_model=WorkspaceIntakeProfileOut, status_code=201)
def create_workspace_profile(
    body: WorkspaceIntakeProfileCreate,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(db, action="workspace_intake.configure", actor_id=user_id, space_id=space_id, resource_type="workspace_intake_profile")
    try:
        row = IntakeService(db).create_workspace_profile(
            space_id=space_id,
            workspace_id=body.workspace_id,
            name=body.name,
            observation_policy=body.observation_policy,
            routing_policy=body.routing_policy,
            filters=body.filters,
            extraction_policy=body.extraction_policy,
            context_policy=body.context_policy,
            created_by_user_id=user_id,
        )
        db.commit()
    except (IntakeDuplicateError, IntakeNotFound, IntakeValidationError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Workspace not found")
    return row


@router.get("/workspace-source-bindings", response_model=list[WorkspaceSourceBindingOut])
def list_workspace_bindings(
    space_id: str = Query(...),
    workspace_id: str | None = Query(None),
    source_connection_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, _user_id = ids
    _assert_space(space_id, identity_space)
    return IntakeService(db).list_workspace_bindings(
        space_id,
        workspace_id=workspace_id,
        source_connection_id=source_connection_id,
    )


@router.post("/workspace-source-bindings", response_model=WorkspaceSourceBindingOut, status_code=201)
def create_workspace_binding(
    body: WorkspaceSourceBindingCreate,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(db, action="workspace_intake.configure", actor_id=user_id, space_id=space_id, resource_type="workspace_source_binding")
    try:
        row = IntakeService(db).create_workspace_binding(
            space_id=space_id,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            source_connection_id=body.source_connection_id,
            binding_key=body.binding_key,
            priority=body.priority,
            filters=body.filters,
            routing_policy=body.routing_policy,
            extraction_policy=body.extraction_policy,
            created_by_user_id=user_id,
        )
        db.commit()
    except (IntakeDuplicateError, IntakeNotFound, IntakeValidationError) as exc:
        _raise_service_http(exc, intake_not_found_detail="Workspace, project, or connection not found")
    return row


# ---------------------------------------------------------------------------
# Summary-runs: LLM-powered summarization into Artifact + optional proposals
# ---------------------------------------------------------------------------

class IntakeSummaryRunRequest(BaseModel):
    evidence_ids: list[str] = Field(default_factory=list)
    intake_item_ids: list[str] = Field(default_factory=list)
    activity_ids: list[str] = Field(default_factory=list)
    summary_goal: Optional[str] = None
    create_memory_proposal: bool = False
    create_knowledge_proposal: bool = False


class IntakeSummaryRunOut(BaseModel):
    run_id: str
    artifact_id: str
    proposal_ids: list[str]
    status: str
    summary_preview: str


@router.post("/summary-runs", response_model=IntakeSummaryRunOut, status_code=201)
def create_intake_summary_run(
    body: IntakeSummaryRunRequest,
    space_id: str = Query(...),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Summarize selected evidence/intake items (and optional activity records) into an Artifact.

    The summary is stored as an Artifact with artifact_type=summary. Optional proposals
    are created for review; no Memory or Knowledge is written directly.
    """
    identity_space, user_id = ids
    _assert_space(space_id, identity_space)
    _enforce(
        db,
        action="evidence.create",
        actor_id=user_id,
        space_id=space_id,
        resource_type="evidence",
    )
    if not body.evidence_ids and not body.intake_item_ids and not body.activity_ids:
        raise HTTPException(
            status_code=422,
            detail="At least one of evidence_ids, intake_item_ids, or activity_ids is required.",
        )
    svc = InputSummaryService(db)
    try:
        result = svc.run(
            space_id=space_id,
            user_id=user_id,
            activity_ids=body.activity_ids,
            evidence_ids=body.evidence_ids,
            intake_item_ids=body.intake_item_ids,
            summary_goal=body.summary_goal,
            create_memory_proposal=body.create_memory_proposal,
            create_knowledge_proposal=body.create_knowledge_proposal,
        )
    except InputSummaryProviderMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InputSummaryProviderCallError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except InputSummaryNoContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InputSummaryCrossSpaceError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return IntakeSummaryRunOut(
        run_id=result.run_id,
        artifact_id=result.artifact_id,
        proposal_ids=result.proposal_ids,
        status=result.status,
        summary_preview=result.summary_preview,
    )
