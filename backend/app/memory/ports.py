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

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..schemas import ContextPackage


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


__all__ = ["ContextBuilderPort"]
