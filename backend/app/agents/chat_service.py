from __future__ import annotations

"""Synchronous Personal Assistant chat turn.

Turns a user message into a real model reply by orchestrating the pieces that
already exist — no new execution path:

  1. persist the raw user turn to a ``Session`` (this is what the chat UI shows),
  2. assemble space-aware context with :class:`ChatContextBuilder`,
  3. create a queued ``Run`` through ``RunService`` and execute it in-process via
     ``RunExecutionService`` (exactly like ``POST /runs/{id}/execute``), and
  4. return the reply, persisting it as the assistant turn.

The dynamic chat context rides inside ``Run.prompt`` because the execution service
feeds the model ``version.system_prompt`` + ``run.prompt``; the system prompt stays
the Assistant's persona. The Assistant resolves to the no-tools ``model_api`` adapter
(see ``catalog/agent_templates/personal_assistant/template.yaml``), so the turn is a
single provider call with no filesystem or sandbox.

If no usable ModelProvider is configured for the space the run fails cleanly with
``error_code == "model_provider_required"`` and we return ``ok=False`` so the UI can
point the user at ``/providers`` rather than fabricating a reply.
"""

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from ..memory import ChatContextBuilder
from ..models import Agent
from ..runs import RunExecutionService
from ..runs import RunService
from ..schemas import ContextBundleItem, ContextRequest, MessageCreate, RunCreate, SessionCreate
from ..sessions.service import SessionService

_MAX_MESSAGE_CHARS = 8000


class ChatTurnRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatTurnOut(BaseModel):
    session_id: str
    run_id: str
    ok: bool
    reply: str | None = None
    error: str | None = None
    error_code: str | None = None


def _render_context_preamble(items: list[ContextBundleItem]) -> str:
    """Render selected context items as a compact preamble for the model input."""
    if not items:
        return ""
    lines = [
        "[Context from your space — use it if relevant; do not repeat it verbatim.]",
    ]
    for it in items:
        title = (it.title or it.item_type or "item").strip()
        excerpt = (it.excerpt or "").strip()
        lines.append(f"- ({it.item_type}) {title}: {excerpt}" if excerpt else f"- ({it.item_type}) {title}")
    return "\n".join(lines)


def run_chat_turn(
    db: DBSession,
    *,
    agent_id: str,
    space_id: str,
    user_id: str,
    req: ChatTurnRequest,
) -> ChatTurnOut:
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")
    if len(message) > _MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"message exceeds {_MAX_MESSAGE_CHARS} characters",
        )

    # 1. Resolve the agent in this space (current version drives the context policy).
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.space_id == space_id)
        .first()
    )
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in this space")
    if not agent.current_version_id:
        raise HTTPException(status_code=400, detail=f"Agent '{agent_id}' has no current version")

    sessions = SessionService(db)

    # 2. Get-or-create the conversation Session (scoped to this space + user).
    if req.session_id:
        session = sessions.get_session(req.session_id, space_id=space_id, user_id=user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found in this space")
    else:
        session = sessions.create_session(
            SessionCreate(
                space_id=space_id,
                user_id=user_id,
                title=f"{agent.name or 'Assistant'} chat",
            )
        )

    # 3. Persist the raw user turn — this is what the chat UI renders.
    sessions.add_message(
        session.id,
        MessageCreate(role="user", content=message),
        space_id=space_id,
        user_id=user_id,
    )

    # 4. Assemble space-aware context. It rides in Run.prompt (the model input),
    #    leaving the Session message clean for display.
    builder = ChatContextBuilder(db)
    request = ContextRequest(
        space_id=space_id,
        user_id=user_id,
        agent_version_id=agent.current_version_id,
        session_id=session.id,
        user_message=message,
    )
    bundle = builder.build(request)
    preamble = _render_context_preamble(bundle.items)
    composed_prompt = f"{preamble}\n\n{message}" if preamble else message

    # 5. Create the queued Run through the canonical path. run_type="agent" is the
    #    Assistant's normal type and already satisfies ck_runs_run_type (no migration).
    run = RunService(db).create_run(
        agent_id=agent_id,
        data=RunCreate(
            mode="live",
            run_type="agent",
            trigger_origin="manual",
            session_id=session.id,
            prompt=composed_prompt,
        ),
        space_id=space_id,
        user_id=user_id,
    )

    # 6. Enrich the run's ContextSnapshot with the selected items for audit.
    request.run_id = run.id
    builder.persist_snapshot(bundle, request, context_snapshot_id=run.context_snapshot_id)
    db.commit()

    # 7. Execute synchronously — same call as POST /runs/{id}/execute.
    result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

    if not result.success:
        return ChatTurnOut(
            session_id=session.id,
            run_id=run.id,
            ok=False,
            error=result.error or "The assistant run did not complete.",
            error_code=result.error_code,
        )

    reply = (result.output or "").strip()

    # 8. Persist the assistant turn (links the run for traceability).
    sessions.add_message(
        session.id,
        MessageCreate(role="assistant", content=reply, metadata={"run_id": run.id}),
        space_id=space_id,
        user_id=user_id,
    )
    return ChatTurnOut(session_id=session.id, run_id=run.id, ok=True, reply=reply)
