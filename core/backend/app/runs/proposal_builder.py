from __future__ import annotations
"""ReflectionProposalBuilder — create proposal candidates from a RunReflection.

Rules:
- Proposals are created ONLY for non-empty candidate lists in the reflection.
- No auto-apply. All proposals start as pending and require user review.
- External runtime output remains evidence, not truth — proposals are the
  gate through which reflection candidates become long-term changes.

Proposal types created here:
  memory_update             — candidate from reflection.memory_candidates
  workspace_profile_update  — candidate from reflection.workspace_facts / reusable_rules
  validation_recipe_update  — candidate from reflection.validation_candidates
  capability_update         — candidate from reflection.capability_candidates
  policy_update             — candidate from reflection.policy_candidates
  follow_up_task            — candidate from reflection.follow_up_tasks

Apply handlers for these types are not yet wired. Proposals appear in the
review inbox as pending; attempting to accept them will raise
UnsupportedProposalTypeError until apply handlers are registered.
"""

import logging
from ulid import ULID
from sqlalchemy.orm import Session

from ..models import Proposal, RunReflection

log = logging.getLogger(__name__)


def _new_id() -> str:
    return str(ULID())


def _build_proposal(
    *,
    space_id: str,
    run_id: str,
    reflection_id: str,
    workspace_id: str | None,
    proposal_type: str,
    title: str,
    summary: str,
    payload: dict,
) -> Proposal:
    return Proposal(
        id=_new_id(),
        space_id=space_id,
        created_by_run_id=run_id,
        proposal_type=proposal_type,
        status="pending",
        risk_level="low",
        urgency="normal",
        title=title,
        summary=summary,
        workspace_id=workspace_id,
        payload_json={
            "reflection_id": reflection_id,
            **payload,
        },
    )


class ReflectionProposalBuilder:
    """Build pending proposal candidates from a RunReflection.

    Only proposals for non-empty candidate lists are created. An empty
    reflection produces no proposals.
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_reflection(self, reflection_id: str, space_id: str) -> RunReflection:
        r = (
            self.db.query(RunReflection)
            .filter(RunReflection.id == reflection_id, RunReflection.space_id == space_id)
            .first()
        )
        if not r:
            raise ValueError(f"RunReflection '{reflection_id}' not found in space '{space_id}'")
        return r

    def create_learning_proposals_from_reflection(
        self,
        reflection_id: str,
        space_id: str,
        workspace_id: str | None = None,
    ) -> list[Proposal]:
        """Create pending proposals for every non-empty candidate list.

        Returns the list of created Proposal rows (may be empty).
        """
        refl = self._get_reflection(reflection_id, space_id)
        run_id = refl.run_id
        created: list[Proposal] = []

        # -- memory candidates ------------------------------------------------
        for i, candidate in enumerate(refl.memory_candidates_json or []):
            title = candidate.get("title") or f"Memory candidate {i+1} from run {run_id[:8]}"
            p = _build_proposal(
                space_id=space_id,
                run_id=run_id,
                reflection_id=reflection_id,
                workspace_id=workspace_id,
                proposal_type="memory_update",
                title=title,
                summary=candidate.get("rationale") or "Memory candidate extracted from run reflection.",
                payload={"candidate": candidate},
            )
            self.db.add(p)
            created.append(p)

        # -- workspace profile / reusable rules --------------------------------
        workspace_facts = refl.workspace_facts_json or {}
        reusable_rules = refl.reusable_rules_json or []
        if workspace_facts or reusable_rules:
            p = _build_proposal(
                space_id=space_id,
                run_id=run_id,
                reflection_id=reflection_id,
                workspace_id=workspace_id,
                proposal_type="workspace_profile_update",
                title=f"Workspace profile update from run {run_id[:8]}",
                summary="Structured workspace facts and reusable rules extracted from run reflection.",
                payload={
                    "workspace_facts": workspace_facts,
                    "reusable_rules": reusable_rules,
                    "reusable_commands": refl.reusable_commands_json or [],
                },
            )
            self.db.add(p)
            created.append(p)

        # -- validation recipe candidates -------------------------------------
        for i, candidate in enumerate(refl.validation_candidates_json or []):
            title = candidate.get("name") or f"Validation recipe candidate {i+1}"
            p = _build_proposal(
                space_id=space_id,
                run_id=run_id,
                reflection_id=reflection_id,
                workspace_id=workspace_id,
                proposal_type="validation_recipe_update",
                title=title,
                summary=candidate.get("rationale") or "Validation recipe candidate from run reflection.",
                payload={"candidate": candidate},
            )
            self.db.add(p)
            created.append(p)

        # -- capability candidates -------------------------------------------
        for i, candidate in enumerate(refl.capability_candidates_json or []):
            title = candidate.get("name") or f"Capability candidate {i+1}"
            p = _build_proposal(
                space_id=space_id,
                run_id=run_id,
                reflection_id=reflection_id,
                workspace_id=workspace_id,
                proposal_type="capability_update",
                title=title,
                summary=candidate.get("rationale") or "Capability candidate from run reflection.",
                payload={"candidate": candidate},
            )
            self.db.add(p)
            created.append(p)

        # -- policy candidates -----------------------------------------------
        for i, candidate in enumerate(refl.policy_candidates_json or []):
            title = candidate.get("name") or f"Policy candidate {i+1}"
            p = _build_proposal(
                space_id=space_id,
                run_id=run_id,
                reflection_id=reflection_id,
                workspace_id=workspace_id,
                proposal_type="policy_update",
                title=title,
                summary=candidate.get("rationale") or "Policy candidate from run reflection.",
                payload={"candidate": candidate},
            )
            self.db.add(p)
            created.append(p)

        # -- follow-up tasks -------------------------------------------------
        for i, task in enumerate(refl.follow_up_tasks_json or []):
            title = task.get("title") or f"Follow-up task {i+1} from run {run_id[:8]}"
            p = _build_proposal(
                space_id=space_id,
                run_id=run_id,
                reflection_id=reflection_id,
                workspace_id=workspace_id,
                proposal_type="follow_up_task",
                title=title,
                summary=task.get("description") or "Follow-up task from run reflection.",
                payload={"task": task},
            )
            self.db.add(p)
            created.append(p)

        if created:
            self.db.commit()
            for p in created:
                self.db.refresh(p)

        log.debug(
            "created %d proposals from reflection %s (run=%s)",
            len(created),
            reflection_id,
            run_id,
        )
        return created
