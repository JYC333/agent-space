from __future__ import annotations
"""RuntimeToolBinding HTTP API — read-only listing of authorized external tools."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from .service import RuntimeToolBindingService

router = APIRouter(prefix="/runtime-tool-bindings", tags=["runtime_tool_bindings"])


class RuntimeToolBindingOut(BaseModel):
    id: str
    space_id: str
    workspace_id: Optional[str] = None
    agent_id: Optional[str] = None
    runtime_adapter_id: str
    execution_plane_id: Optional[str] = None
    external_type: str  # mcp_server|codex_plugin|claude_skill|claude_hook|app_integration|cli_tool
    external_ref: str
    display_name: str
    data_exposure_level: str
    observability_level: str
    side_effect_level: str
    approval_required: bool
    enabled: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[RuntimeToolBindingOut])
def list_runtime_tool_bindings(
    workspace_id: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    runtime_adapter_id: Optional[str] = Query(None),
    include_disabled: bool = Query(False),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return RuntimeToolBindingService(db).list_runtime_tool_bindings(
        space_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        runtime_adapter_id=runtime_adapter_id,
        enabled_only=not include_disabled,
    )


@router.get("/{binding_id}", response_model=RuntimeToolBindingOut)
def get_runtime_tool_binding(
    binding_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    binding = RuntimeToolBindingService(db).get_runtime_tool_binding(binding_id, space_id)
    if not binding:
        raise HTTPException(status_code=404, detail="Runtime tool binding not found")
    return binding
