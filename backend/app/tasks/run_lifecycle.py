"""Tasks-owned run-finalized lifecycle hooks.

``tasks`` owns the RunEvaluation → TaskEvaluation bridge. It registers this
hook with the runs-owned :class:`~app.runs.RunFinalizedHookRegistry` through
the backend module registry (``Module(..., run_finalized_hooks="run_lifecycle")``),
so ``runs`` finalization never imports ``tasks`` — dependency direction stays
``tasks -> runs`` only.

The hook runs inside the finalization transaction. It writes its outcome back
through the context's result slots: ``task_evaluation_id`` when a bridge
evaluation exists or was created, or a ``no_task_run_link`` skipped reason when
the run has no ``TaskRun`` linkage. A repeat finalization attempt reuses the
existing bridge evaluation rather than creating a duplicate. Any other failure
propagates so finalization records a failed stage named after this hook
(``task_evaluation_bridge``) — identical to the pre-hook inline behavior.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .evaluation_errors import TaskEvaluationNotFoundError
from .evaluation_service import TaskEvaluationService

if TYPE_CHECKING:
    from app.runs import RunFinalizedContext, RunFinalizedHookRegistry

_HOOK_NAME = "task_evaluation_bridge"
_SKIP_NO_TASK_RUN_LINK = "no_task_run_link"


def _bridge_task_evaluation(context: "RunFinalizedContext") -> None:
    """Bridge the run's RunEvaluation to a TaskEvaluation when TaskRun linkage exists."""
    service = TaskEvaluationService(context.db)
    existing = service.list_for_run_evaluation(context.run_evaluation_id, context.space_id)
    if existing:
        context.task_evaluation_id = existing[0].id
        return
    try:
        row = service.create_from_run_evaluation(
            context.run_evaluation_id, space_id=context.space_id
        )
    except TaskEvaluationNotFoundError:
        context.skipped_reasons.append(_SKIP_NO_TASK_RUN_LINK)
        return
    context.task_evaluation_id = row.id


def register_run_finalized_hooks(registry: "RunFinalizedHookRegistry") -> None:
    """Register tasks-owned run-finalized hooks (module registry entry point)."""
    registry.register(_HOOK_NAME, _bridge_task_evaluation, order=100)
