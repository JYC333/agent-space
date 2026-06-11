"""Automation CRUD and manual-fire API.

Routes:
  POST   /api/v1/spaces/{space_id}/automations          — create
  GET    /api/v1/spaces/{space_id}/automations          — list
  GET    /api/v1/spaces/{space_id}/automations/{id}     — get
  PATCH  /api/v1/spaces/{space_id}/automations/{id}     — update
  POST   /api/v1/spaces/{space_id}/automations/{id}/fire — manual fire

Policy enforcement (via AutomationService):
  automation.create — checked on creation; RESERVED actions fail closed until wired
  automation.update — checked on update
  automation.fire   — checked on manual fire
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_use_space, require_view_space
from ..auth import get_current_user
from ..db import get_db
from ..models import User
from .schemas import AutomationCreate, AutomationFireRequest, AutomationOut, AutomationFireResult, AutomationUpdate
from .service import AutomationService

router = APIRouter(prefix="/spaces/{space_id}/automations", tags=["automations"])


def _out(auto) -> AutomationOut:
    return AutomationOut(
        id=auto.id,
        space_id=auto.space_id,
        owner_user_id=auto.owner_user_id,
        agent_id=auto.agent_id,
        workspace_id=auto.workspace_id,
        name=auto.name,
        description=auto.description,
        trigger_type=auto.trigger_type,
        status=auto.status,
        preflight_snapshot_json=auto.preflight_snapshot_json,
        config_json=auto.config_json,
        next_run_at=auto.next_run_at,
        last_fired_at=auto.last_fired_at,
        created_at=auto.created_at,
        updated_at=auto.updated_at,
    )


@router.post("", status_code=201, response_model=AutomationOut)
def create_automation(
    space_id: str,
    data: AutomationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_use_space(db, user.id, space_id)
    auto = AutomationService(db).create(
        space_id=space_id,
        owner_user_id=user.id,
        data=data,
    )
    db.commit()
    db.refresh(auto)
    return _out(auto)


@router.get("", response_model=list[AutomationOut])
def list_automations(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_view_space(db, user.id, space_id)
    autos = AutomationService(db).list(space_id=space_id)
    return [_out(a) for a in autos]


@router.get("/{automation_id}", response_model=AutomationOut)
def get_automation(
    space_id: str,
    automation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_view_space(db, user.id, space_id)
    auto = AutomationService(db).get(automation_id=automation_id, space_id=space_id)
    return _out(auto)


@router.patch("/{automation_id}", response_model=AutomationOut)
def update_automation(
    space_id: str,
    automation_id: str,
    data: AutomationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_use_space(db, user.id, space_id)
    auto = AutomationService(db).update(
        automation_id=automation_id,
        space_id=space_id,
        actor_user_id=user.id,
        data=data,
    )
    db.commit()
    db.refresh(auto)
    return _out(auto)


@router.post("/{automation_id}/fire", response_model=AutomationFireResult)
def fire_automation(
    space_id: str,
    automation_id: str,
    data: AutomationFireRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_use_space(db, user.id, space_id)
    result = AutomationService(db).fire(
        automation_id=automation_id,
        space_id=space_id,
        actor_user_id=user.id,
        prompt=data.prompt,
        instruction=data.instruction,
    )
    db.commit()
    return result
