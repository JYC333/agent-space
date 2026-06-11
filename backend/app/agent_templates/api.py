from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..agents.agent_service import AgentService
from ..agents.template_service import AgentTemplateService
from ..auth import get_identity
from ..db import get_db
from ..schemas import (
    AgentOut,
    AgentTemplateCreate,
    AgentTemplateOut,
    AgentTemplateVersionCreate,
    AgentTemplateVersionOut,
    CreateAgentFromTemplate,
)

router = APIRouter(prefix="/agent-templates", tags=["agent-templates"])


@router.get("", response_model=list[AgentTemplateOut])
def list_templates(
    category: str | None = Query(None),
    status: str | None = Query("published"),
    limit: int = Query(100, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = AgentTemplateService(db)
    return svc.list_visible(
        space_id=space_id,
        user_id=user_id,
        category=category,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=AgentTemplateOut, status_code=201)
def create_template(
    data: AgentTemplateCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = AgentTemplateService(db)
    return svc.create_template(data, owner_user_id=user_id, request_space_id=space_id)


@router.get("/{template_id}", response_model=AgentTemplateOut)
def get_template(
    template_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    svc = AgentTemplateService(db)
    return svc.get_or_404(template_id)


@router.get("/{template_id}/versions", response_model=list[AgentTemplateVersionOut])
def list_template_versions(
    template_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    svc = AgentTemplateService(db)
    svc.get_or_404(template_id)
    return svc.list_versions(template_id)


@router.get("/{template_id}/versions/{version_id}", response_model=AgentTemplateVersionOut)
def get_template_version(
    template_id: str,
    version_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Return a single template version's full config snapshot."""
    svc = AgentTemplateService(db)
    svc.get_or_404(template_id)
    return svc.get_version_or_404(template_id, version_id)


@router.post("/{template_id}/versions", response_model=AgentTemplateVersionOut, status_code=201)
def create_template_version(
    template_id: str,
    data: AgentTemplateVersionCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    _, user_id = ids
    svc = AgentTemplateService(db)
    return svc.create_template_version(template_id, data, created_by_user_id=user_id)


@router.post(
    "/{template_id}/versions/{version_id}/publish",
    response_model=AgentTemplateVersionOut,
)
def publish_template_version(
    template_id: str,
    version_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    svc = AgentTemplateService(db)
    return svc.publish_template_version(template_id, version_id)


@router.post("/{template_id}/agents", response_model=AgentOut, status_code=201)
def create_agent_from_template(
    template_id: str,
    data: CreateAgentFromTemplate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Copy-on-create: instantiate an Agent from a template version."""
    space_id, user_id = ids
    tpl_svc = AgentTemplateService(db)
    tpl = tpl_svc.get_or_404(template_id)
    if tpl.visibility == "system_internal":
        # The system-managed default Assistant is not a user-instantiable template;
        # it is minted only by the SpaceAssistant seeder. Block duplicate creation.
        raise HTTPException(
            status_code=403,
            detail=(
                "This is a system-managed assistant and cannot be instantiated from "
                "the template library. Use the space's default Assistant instead."
            ),
        )
    agent = tpl_svc.create_agent_from_template(
        template_id,
        version_id=data.template_version_id,
        overrides=data,
        space_id=data.space_id or space_id,
        owner_user_id=user_id,
    )
    return AgentService(db).to_agent_out(agent)
