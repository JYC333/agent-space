"""Internal Python-owned preparation port for TS chat-turn orchestration."""

from __future__ import annotations

from hmac import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..memory import get_chat_context_builder
from ..models import Agent
from ..runs import RunService
from ..schemas import ContextRequest, RunCreate
from .authority import reject_python_chat_context_build_when_ts_authority
from .chat_service import _render_context_preamble


router = APIRouter(prefix="/internal/agents-chat", tags=["internal-agents-chat"])

_INTERNAL_TOKEN_HEADER = "x-agent-space-internal-token"


class ChatTurnPrepareRunRequest(BaseModel):
    agent_id: str
    space_id: str
    user_id: str
    session_id: str
    message: str


class ChatTurnPrepareRunResult(BaseModel):
    session_id: str
    run_id: str


class ChatContextCandidatesRequest(BaseModel):
    agent_id: str
    space_id: str
    user_id: str
    session_id: str
    message: str


class ChatContextCandidateItem(BaseModel):
    item_type: str
    item_id: str | None = None
    title: str | None = None
    excerpt: str | None = None
    score: float | None = None
    reason: str | None = None
    token_count: int | None = None
    metadata: dict = {}


class ChatContextCandidatesResult(BaseModel):
    allowed_sources: list[str]
    max_tokens: int
    max_items: int
    context_policy_applied: bool
    items: list[ChatContextCandidateItem]


class ChatRunCreateRequest(BaseModel):
    agent_id: str
    space_id: str
    user_id: str
    session_id: str
    prompt: str


class ChatRunCreateResult(BaseModel):
    run_id: str
    context_snapshot_id: str | None = None


def _require_internal_token(
    token: str | None = Header(default=None, alias=_INTERNAL_TOKEN_HEADER),
) -> None:
    configured = (settings.control_plane_internal_token or "").strip()
    presented = (token or "").strip()
    if not configured or not presented:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not compare_digest(presented, configured):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/prepare-run", response_model=ChatTurnPrepareRunResult)
def prepare_chat_turn_run(
    body: ChatTurnPrepareRunRequest,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
) -> ChatTurnPrepareRunResult:
    """Build chat context and create the queued Run for a TS-owned chat turn.

    This is intentionally not the chat-turn authority: it does not create
    sessions or messages and it does not execute runs. It exposes the two
    still-Python-owned preparation steps so TS can own the outer command without
    prematurely moving the context engine.

    Fails closed because the TS chat turn builds context, creates the run, and
    persists the snapshot itself; the combined build-and-persist path must not
    also run.
    """

    reject_python_chat_context_build_when_ts_authority()

    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")

    agent = (
        db.query(Agent)
        .filter(Agent.id == body.agent_id, Agent.space_id == body.space_id)
        .first()
    )
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{body.agent_id}' not found in this space",
        )
    if not agent.current_version_id:
        raise HTTPException(
            status_code=400,
            detail=f"Agent '{body.agent_id}' has no current version",
        )

    builder = get_chat_context_builder(db)
    request = ContextRequest(
        space_id=body.space_id,
        user_id=body.user_id,
        agent_version_id=agent.current_version_id,
        session_id=body.session_id,
        user_message=message,
    )
    bundle = builder.build(request)
    preamble = _render_context_preamble(bundle.items)
    composed_prompt = f"{preamble}\n\n{message}" if preamble else message

    run = RunService(db).create_run(
        agent_id=body.agent_id,
        data=RunCreate(
            mode="live",
            run_type="agent",
            trigger_origin="manual",
            session_id=body.session_id,
            prompt=composed_prompt,
        ),
        space_id=body.space_id,
        user_id=body.user_id,
    )

    request.run_id = run.id
    builder.persist_snapshot(bundle, request, context_snapshot_id=run.context_snapshot_id)
    db.commit()

    return ChatTurnPrepareRunResult(session_id=body.session_id, run_id=run.id)


def _resolve_chat_agent(db: Session, agent_id: str, space_id: str) -> Agent:
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.space_id == space_id)
        .first()
    )
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found in this space",
        )
    if not agent.current_version_id:
        raise HTTPException(
            status_code=400,
            detail=f"Agent '{agent_id}' has no current version",
        )
    return agent


@router.post("/context-candidates", response_model=ChatContextCandidatesResult)
def chat_context_candidates(
    body: ChatContextCandidatesRequest,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
) -> ChatContextCandidatesResult:
    """Return unbudgeted chat context candidates for the TS context engine.

    Stage 6 slice 4 read port: the TS chat turn owns the budget/dedup loop and
    snapshot persistence, but the underlying source reads (memory, knowledge,
    sources, activity, workspace, project) belong to contexts that have not
    migrated yet. This wraps `ChatContextBuilder.collect_candidates` — selection
    by `context_policy_json` and the per-source selectors, with **no** cumulative
    budget and **no** persistence. Read-only.
    """

    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")

    agent = _resolve_chat_agent(db, body.agent_id, body.space_id)

    builder = get_chat_context_builder(db)
    request = ContextRequest(
        space_id=body.space_id,
        user_id=body.user_id,
        agent_version_id=agent.current_version_id,
        session_id=body.session_id,
        user_message=message,
    )
    candidates, allowed, max_tokens, max_items = builder.collect_candidates(request)

    return ChatContextCandidatesResult(
        allowed_sources=sorted(allowed),
        max_tokens=max_tokens,
        max_items=max_items,
        context_policy_applied=bool(request.agent_version_id),
        items=[
            ChatContextCandidateItem(
                item_type=item.item_type,
                item_id=item.item_id,
                title=item.title,
                excerpt=item.excerpt,
                score=item.score,
                reason=item.reason,
                token_count=item.token_count,
                metadata=item.metadata or {},
            )
            for item in candidates
        ],
    )


@router.post("/create-run", response_model=ChatRunCreateResult)
def chat_create_run(
    body: ChatRunCreateRequest,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
) -> ChatRunCreateResult:
    """Create the queued chat run for a TS-owned, TS-assembled chat turn.

    Stage 6 slice 4: run creation stays Python-owned (it is `runs` context, only
    execute/stop moved to TS in Stage 4). The TS chat turn composes the prompt
    from its own assembled context, then calls this port to create the run and
    its empty `ContextSnapshot`; TS then persists the snapshot rows directly. No
    context is built here.
    """

    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt must not be empty")

    _resolve_chat_agent(db, body.agent_id, body.space_id)

    run = RunService(db).create_run(
        agent_id=body.agent_id,
        data=RunCreate(
            mode="live",
            run_type="agent",
            trigger_origin="manual",
            session_id=body.session_id,
            prompt=prompt,
        ),
        space_id=body.space_id,
        user_id=body.user_id,
    )
    db.commit()

    return ChatRunCreateResult(
        run_id=run.id,
        context_snapshot_id=run.context_snapshot_id,
    )
