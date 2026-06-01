from __future__ import annotations
import uuid
"""ReflectionService — extract structured learning from a completed run.

A RunReflection is a structured record of what a run changed, what worked,
what failed, and what candidates exist for future learning. It NEVER directly
mutates memory, policy, capability, workspace profile, or validation recipes.

All long-term changes must flow through proposals (see ReflectionProposalBuilder).

Reflection sources:
  native        — run executed inside agent-space
  external_import — run imported via ExternalRunImportService
  manual        — user-supplied summary
  evaluator     — automated validation pass
"""

import logging
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from ..models import Run, ExternalRunRecord, Artifact, RunReflection

log = logging.getLogger(__name__)


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class ReflectionInput:
    """Caller-supplied context for one run reflection.

    Callers provide the structured fields they know; the service assembles
    them into a RunReflection. All list/dict fields default to empty so the
    service never fails on missing data.
    """
    # What changed in the run (human-readable summary)
    what_changed: str | None = None
    what_worked: str | None = None
    what_failed: str | None = None

    # Reusable learnings extracted by the caller
    reusable_rules: list[dict] = field(default_factory=list)
    reusable_commands: list[dict] = field(default_factory=list)
    workspace_facts: dict = field(default_factory=dict)

    # Candidate lists — each item is a dict describing one proposed change.
    # Format is intentionally open so reflection consumers can use any structure.
    memory_candidates: list[dict] = field(default_factory=list)
    capability_candidates: list[dict] = field(default_factory=list)
    policy_candidates: list[dict] = field(default_factory=list)
    validation_candidates: list[dict] = field(default_factory=list)
    follow_up_tasks: list[dict] = field(default_factory=list)

    confidence: float | None = None


class ReflectionService:
    """Create a RunReflection for a completed run.

    The reflection is purely additive: it adds a record to run_reflections
    and never modifies any other table.
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_run(self, run_id: str, space_id: str) -> Run:
        run = (
            self.db.query(Run)
            .filter(Run.id == run_id, Run.space_id == space_id)
            .first()
        )
        if not run:
            raise ValueError(f"Run '{run_id}' not found in space '{space_id}'")
        return run

    def _derive_source(self, run: Run) -> str:
        """Derive reflection source from how the run was created.

        Managed runs (including those that ran on local_external planes) are
        reflected as 'native' because the reflection is created within agent-space.
        Imported runs are 'external_import'.
        """
        if run.source in ("manual_import", "remote_import"):
            return "external_import"
        return "native"

    def reflect_run(
        self,
        run_id: str,
        space_id: str,
        inp: ReflectionInput | None = None,
    ) -> RunReflection:
        """Create a RunReflection for run_id.

        ``inp`` supplies all structured fields. When omitted, the reflection
        is created with empty candidates (a valid zero-candidate record).
        Multiple reflections on the same run are allowed (e.g. one per pass).
        """
        run = self._get_run(run_id, space_id)
        inp = inp or ReflectionInput()

        reflection = RunReflection(
            id=_new_id(),
            space_id=space_id,
            run_id=run.id,
            source=self._derive_source(run),
            what_changed=inp.what_changed,
            what_worked=inp.what_worked,
            what_failed=inp.what_failed,
            reusable_rules_json=inp.reusable_rules or None,
            reusable_commands_json=inp.reusable_commands or None,
            workspace_facts_json=inp.workspace_facts or None,
            memory_candidates_json=inp.memory_candidates or None,
            capability_candidates_json=inp.capability_candidates or None,
            policy_candidates_json=inp.policy_candidates or None,
            validation_candidates_json=inp.validation_candidates or None,
            follow_up_tasks_json=inp.follow_up_tasks or None,
            confidence=inp.confidence,
        )
        self.db.add(reflection)
        self.db.commit()
        self.db.refresh(reflection)
        log.debug(
            "created RunReflection %s for run %s (memory_candidates=%d)",
            reflection.id,
            run_id,
            len(inp.memory_candidates),
        )
        return reflection

    def list_reflections_for_run(self, run_id: str, space_id: str) -> list[RunReflection]:
        self._get_run(run_id, space_id)
        return (
            self.db.query(RunReflection)
            .filter(RunReflection.run_id == run_id, RunReflection.space_id == space_id)
            .order_by(RunReflection.created_at)
            .all()
        )
