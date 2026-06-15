"""Stage 6 temporary internal ports for memory + sessions migration.

These routes are service-to-service boundaries only. They let TypeScript prep
code call explicit Python-owned seams while Stage 6 is being split. They do not
move authority: Python remains the sessions/memory authority until a later
route flip guarded by the roadmap gates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hmac import compare_digest
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .authority import sessions_commands_owned_by_ts
from .ports import get_session_summary_port


router = APIRouter(prefix="/internal/stage6-context", tags=["internal-stage6-context"])

_INTERNAL_TOKEN_HEADER = "x-agent-space-internal-token"

Stage6PortOperation = Literal[
    "session_summary.get_latest",
    "context.build",
    "memory.read",
    "memory.proposal_create",
]
Stage6PortOwner = Literal["sessions", "memory_context", "memory"]
Stage6PortErrorCode = Literal[
    "unauthorized_internal_port",
    "stage6_port_not_implemented",
    "stage6_port_invalid_request",
    "session_summary_not_found",
    "context_build_failed",
    "memory_read_failed",
    "memory_proposal_create_failed",
]


class Stage6PortDescriptor(BaseModel):
    operation: Stage6PortOperation
    owner: Stage6PortOwner
    implemented: bool
    auth: Literal["internal_service_token"] = "internal_service_token"
    error_codes: list[Stage6PortErrorCode]
    writes: list[str] = Field(default_factory=list)
    notes: str | None = None


class Stage6PortsManifest(BaseModel):
    service: Literal["python_stage6_context_ports"] = "python_stage6_context_ports"
    ports: list[Stage6PortDescriptor]
    generated_at: datetime


class Stage6PortRequest(BaseModel):
    operation: Stage6PortOperation
    space_id: str
    user_id: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)


class Stage6PortResponse(BaseModel):
    operation: Stage6PortOperation
    owner: Stage6PortOwner
    status: Literal["succeeded", "failed", "not_implemented"]
    error_code: Stage6PortErrorCode | None = None
    message: str | None = None
    result_json: dict[str, Any] = Field(default_factory=dict)


_PORTS: tuple[Stage6PortDescriptor, ...] = (
    Stage6PortDescriptor(
        operation="session_summary.get_latest",
        owner="sessions",
        implemented=True,
        error_codes=["session_summary_not_found", "stage6_port_invalid_request"],
        writes=[],
        notes=(
            "Uses the sessions-owned SessionSummaryPort. This is the first Stage 6 "
            "prep seam consumed by memory/context code."
        ),
    ),
    Stage6PortDescriptor(
        operation="context.build",
        owner="memory_context",
        implemented=False,
        error_codes=["stage6_port_not_implemented", "context_build_failed"],
        writes=["context_snapshots", "memory_access_logs"],
        notes="Declared for Stage 6 planning only; current TS runs still use the Stage 4 runs-context port.",
    ),
    Stage6PortDescriptor(
        operation="memory.read",
        owner="memory",
        implemented=False,
        error_codes=["stage6_port_not_implemented", "memory_read_failed"],
        writes=[],
        notes="Declared for Stage 6 planning only; memory read authority remains Python public routes.",
    ),
    Stage6PortDescriptor(
        operation="memory.proposal_create",
        owner="memory",
        implemented=False,
        error_codes=["stage6_port_not_implemented", "memory_proposal_create_failed"],
        writes=["proposals"],
        notes="Declared for Stage 6 planning only; public memory write routes still create proposals in Python.",
    ),
)


def _ports() -> tuple[Stage6PortDescriptor, ...]:
    if not sessions_commands_owned_by_ts():
        return _PORTS

    ports: list[Stage6PortDescriptor] = []
    for port in _PORTS:
        if port.operation != "session_summary.get_latest":
            ports.append(port)
            continue
        ports.append(
            Stage6PortDescriptor(
                operation=port.operation,
                owner=port.owner,
                implemented=False,
                error_codes=["stage6_port_not_implemented", "stage6_port_invalid_request"],
                writes=[],
                notes=(
                    "Retired under CONTROL_PLANE_SESSIONS_AUTHORITY=ts; "
                    "session_summary.get_latest is served by the TypeScript control plane."
                ),
            )
        )
    return tuple(ports)


def _descriptor(operation: Stage6PortOperation) -> Stage6PortDescriptor:
    for port in _ports():
        if port.operation == operation:
            return port
    raise HTTPException(status_code=400, detail="Unknown Stage 6 port operation")


def _require_internal_token(
    token: str | None = Header(default=None, alias=_INTERNAL_TOKEN_HEADER),
) -> None:
    configured = (settings.control_plane_internal_token or "").strip()
    presented = (token or "").strip()
    if not configured or not presented:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not compare_digest(presented, configured):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/ports", response_model=Stage6PortsManifest)
def describe_stage6_context_ports(
    _: None = Depends(_require_internal_token),
) -> Stage6PortsManifest:
    return Stage6PortsManifest(
        ports=list(_ports()),
        generated_at=datetime.now(UTC),
    )


@router.post("/operations", response_model=Stage6PortResponse)
def run_stage6_context_port_operation(
    body: Stage6PortRequest,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
) -> Stage6PortResponse:
    descriptor = _descriptor(body.operation)
    if not descriptor.implemented:
        return Stage6PortResponse(
            operation=descriptor.operation,
            owner=descriptor.owner,
            status="not_implemented",
            error_code="stage6_port_not_implemented",
            message=f"Stage 6 port {body.operation!r} is declared but not implemented yet.",
        )

    if body.operation == "session_summary.get_latest":
        session_id = body.payload_json.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return Stage6PortResponse(
                operation=body.operation,
                owner=descriptor.owner,
                status="failed",
                error_code="stage6_port_invalid_request",
                message="payload_json.session_id is required",
            )

        summary = get_session_summary_port(db).get_latest_for_context(
            session_id=session_id,
            space_id=body.space_id,
        )
        if summary is None:
            return Stage6PortResponse(
                operation=body.operation,
                owner=descriptor.owner,
                status="failed",
                error_code="session_summary_not_found",
                message="No active session summary found for this session in this space.",
            )
        return Stage6PortResponse(
            operation=body.operation,
            owner=descriptor.owner,
            status="succeeded",
            result_json={
                "summary": {
                    "id": summary.id,
                    "session_id": summary.session_id,
                    "version": summary.version,
                    "summary_text": summary.summary_text,
                    "condenser_version": summary.condenser_version,
                },
            },
        )

    return Stage6PortResponse(
        operation=descriptor.operation,
        owner=descriptor.owner,
        status="not_implemented",
        error_code="stage6_port_not_implemented",
    )
