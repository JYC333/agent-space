"""Interface-only seam over the concrete context builder.

``ContextBuilderPort`` is a structural (``typing.Protocol``) contract describing
the one method cross-module callers (``runs``, ``agents``, ``memory.context_api``)
use to assemble an agent context package. The concrete
:class:`app.memory.context_builder.ContextBuilder` remains the authority and the
sole production implementation — it already satisfies this protocol structurally,
so no change to it is required.

The port exists so that:

* callers can type-annotate against the seam (``ContextBuilderPort``) instead of
  importing the concrete class, decoupling them from ``memory`` internals; and
* tests can substitute a lightweight fake (see
  ``tests/support/fake_context_builder.py``) without a database.

This is a migration seam only — it introduces no new behavior and does not move
authority out of ``ContextBuilder``. See
``.agent/architecture/TS_MIGRATION_STRATEGY.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

    from ..models import ContextSnapshot
    from ..schemas import ContextBundle, ContextPackage, ContextRequest


@runtime_checkable
class ContextBuilderPort(Protocol):
    """The context-assembly contract.

    Mirrors :meth:`app.memory.context_builder.ContextBuilder.build`. ``space_id``
    and ``user_id`` are required — context assembly is a space boundary (B5) and
    requires an explicit acting user.
    """

    def build(
        self,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        project_id: str | None = None,
        task_type: str | None = None,
        capability_id: str | None = None,
        session_id: str | None = None,
        query: str | None = None,
        agent_memory_policy: dict | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        context_reason: str | None = None,
        attachments: list[dict] | None = None,
        workspace_path: str | None = None,
    ) -> "ContextPackage":
        ...


@runtime_checkable
class ChatContextBuilderPort(Protocol):
    """The Personal Assistant chat-turn context-assembly contract.

    Mirrors the two methods :class:`app.memory.chat_context.ChatContextBuilder`
    exposes to the chat-turn caller (``agents.chat_service``): assemble a bundle
    for a session turn, then persist the audit snapshot for the created run. The
    caller owns the transaction boundary (``persist_snapshot`` flushes but does
    not commit).
    """

    def build(self, request: "ContextRequest") -> "ContextBundle":
        ...

    def persist_snapshot(
        self,
        bundle: "ContextBundle",
        request: "ContextRequest",
        context_snapshot_id: Optional[str] = None,
    ) -> "ContextSnapshot":
        ...


def get_context_builder(db: "DBSession") -> ContextBuilderPort:
    """Resolve the active context-assembly authority.

    Python's :class:`~app.memory.context_builder.ContextBuilder` remains
    authoritative until Stage 6 flips the context slice. Resolving through this
    facade function — instead of constructing the concrete class at the call
    site — gives the migration one place to route cross-context context builds to
    the TS context engine later. Mirrors ``sessions.get_session_summary_port``.
    """

    from .context_builder import ContextBuilder

    return ContextBuilder(db)


def get_chat_context_builder(db: "DBSession") -> ChatContextBuilderPort:
    """Resolve the active chat-turn context-assembly authority.

    Same rationale as :func:`get_context_builder`, for the Personal Assistant
    chat path's :class:`~app.memory.chat_context.ChatContextBuilder`.
    """

    from .chat_context import ChatContextBuilder

    return ChatContextBuilder(db)


__all__ = [
    "ChatContextBuilderPort",
    "ContextBuilderPort",
    "get_chat_context_builder",
    "get_context_builder",
]
