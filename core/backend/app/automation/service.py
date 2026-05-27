"""AutomationService — create, update, and manually fire automations.

Invariants:
  - automation.create: PolicyGateway check required; PreflightService must pass.
  - automation.update: PolicyGateway check required.
  - automation.fire:   PolicyGateway check required; PreflightService reruns; creates queued Run only.

This service must NOT:
  - Write MemoryEntry, Policy, Workspace files, Capability, or Credentials directly.
  - Execute a Run (only queues it via RunService.create_run).
  - Implement a cron scheduler or external event triggers.
  - Grant credential allowances.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Automation, AutomationRun
from ..policy.gateway import PolicyGateway, PolicyCheckRequest
from ..policy.roles import get_space_role_normalized
from ..runs.preflight import PreflightRequest, PreflightService
from ..runs.run_service import RunService
from ..schemas import RunCreate
from .policy_preflight import AutomationPolicyPreflightService
from .schemas import AutomationCreate, AutomationFireResult, AutomationUpdate

log = logging.getLogger(__name__)

_VALID_TRIGGER_TYPES = frozenset({"manual"})
_VALID_STATUSES = frozenset({"active", "paused", "archived"})


class AutomationService:
    """CRUD and fire for Automation, with full PolicyGateway enforcement."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        space_id: str,
        owner_user_id: str,
        data: AutomationCreate,
        automation_id: Optional[str] = None,
    ) -> Automation:
        """Create an Automation.

        Steps:
          1. Validate cheap schema fields (trigger_type).
          2. PolicyGateway.enforce(automation.create); deny if not allowed.
             Unauthorized actors must not receive preflight diagnostics.
          3. Run PreflightService; deny if not executable.
          4. Run AutomationPolicyPreflightService; deny if not executable.
          5. Persist Automation with runtime preflight + policy preflight snapshots.
        """
        if data.trigger_type not in _VALID_TRIGGER_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported trigger_type {data.trigger_type!r}. Must be one of: {sorted(_VALID_TRIGGER_TYPES)}",
            )

        membership_role = get_space_role_normalized(self.db, owner_user_id, space_id) or "guest"
        PolicyGateway(self.db).enforce(PolicyCheckRequest(
            action="automation.create",
            actor_type="user",
            actor_id=owner_user_id,
            space_id=space_id,
            resource_type="automation",
            context={
                "agent_id": data.agent_id,
                "trigger_type": data.trigger_type,
                "membership_role": membership_role,
            },
            metadata_json={"automation_name": data.name},
        ))

        preflight_result = PreflightService(self.db).check(
            PreflightRequest(
                agent_id=data.agent_id,
                workspace_id=data.workspace_id,
                trigger_origin="automation",
            ),
            space_id=space_id,
        )
        if not preflight_result.executable:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "preflight_failed",
                    "message": "Preflight checks failed; Automation cannot be created.",
                    "errors": preflight_result.errors,
                    "warnings": preflight_result.warnings,
                },
            )

        policy_preflight = AutomationPolicyPreflightService(self.db).check(
            space_id=space_id,
            agent_id=data.agent_id,
            workspace_id=data.workspace_id,
            trigger_origin="automation",
        )
        if not policy_preflight.executable:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "policy_preflight_failed",
                    "message": (
                        "Policy preflight checks failed; Automation cannot be created."
                    ),
                    "errors": policy_preflight.errors,
                    "warnings": policy_preflight.warnings,
                    "checks": [c.model_dump() for c in policy_preflight.checks],
                },
            )

        auto = Automation(
            space_id=space_id,
            owner_user_id=owner_user_id,
            agent_id=data.agent_id,
            workspace_id=data.workspace_id,
            name=data.name,
            description=data.description,
            trigger_type=data.trigger_type,
            status="active",
            preflight_snapshot_json=self._preflight_snapshot(
                runtime_preflight=preflight_result.model_dump(),
                policy_preflight=policy_preflight.model_dump(),
            ),
            config_json=data.config_json,
        )
        if automation_id:
            auto.id = automation_id
        self.db.add(auto)
        self.db.flush()
        return auto

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        automation_id: str,
        space_id: str,
        actor_user_id: str,
        data: AutomationUpdate,
    ) -> Automation:
        """Update an Automation.

        Steps:
          1. Load and space-scope the Automation.
          2. Validate incoming status if provided.
          3. PolicyGateway.enforce(automation.update).
          4. Apply changes.
        """
        auto = self._get_or_404(automation_id, space_id)

        if data.status is not None and data.status not in _VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status {data.status!r}. Must be one of: {sorted(_VALID_STATUSES)}",
            )

        membership_role = get_space_role_normalized(self.db, actor_user_id, space_id) or "guest"
        PolicyGateway(self.db).enforce(PolicyCheckRequest(
            action="automation.update",
            actor_type="user",
            actor_id=actor_user_id,
            space_id=space_id,
            resource_type="automation",
            resource_id=automation_id,
            context={"agent_id": auto.agent_id, "membership_role": membership_role},
            metadata_json={"automation_name": auto.name},
        ))

        if data.name is not None:
            auto.name = data.name
        if data.description is not None:
            auto.description = data.description
        if data.status is not None:
            auto.status = data.status
        if data.config_json is not None:
            auto.config_json = data.config_json
        self.db.flush()
        return auto

    # ------------------------------------------------------------------
    # Fire (manual trigger)
    # ------------------------------------------------------------------

    def fire(
        self,
        automation_id: str,
        space_id: str,
        actor_user_id: str,
        prompt: Optional[str] = None,
        instruction: Optional[str] = None,
    ) -> AutomationFireResult:
        """Manually trigger an Automation — creates a queued Run only.

        Steps:
          1. Load and space-scope the Automation.
          2. Verify status == "active".
          3. PolicyGateway.enforce(automation.fire).
          4. Rerun PreflightService; deny if not executable.
          5. Rerun AutomationPolicyPreflightService; deny if not executable.
          6. RunService.create_run with trigger_origin="automation" (no commit).
          7. Persist AutomationRun link.
          Run and AutomationRun are committed together by the caller.

        Does NOT execute the run. The run worker picks it up separately.
        """
        auto = self._get_or_404(automation_id, space_id)

        if auto.status != "active":
            raise HTTPException(
                status_code=409,
                detail=f"Automation is not active (status={auto.status!r}). Cannot fire.",
            )

        membership_role = get_space_role_normalized(self.db, actor_user_id, space_id) or "guest"
        PolicyGateway(self.db).enforce(PolicyCheckRequest(
            action="automation.fire",
            actor_type="user",
            actor_id=actor_user_id,
            space_id=space_id,
            resource_type="automation",
            resource_id=automation_id,
            context={
                "agent_id": auto.agent_id,
                "trigger_type": "manual",
                "trigger_origin": "automation",
                "membership_role": membership_role,
            },
            metadata_json={"automation_name": auto.name},
        ))

        preflight_result = PreflightService(self.db).check(
            PreflightRequest(
                agent_id=auto.agent_id,
                workspace_id=auto.workspace_id,
                trigger_origin="automation",
            ),
            space_id=space_id,
        )
        if not preflight_result.executable:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "preflight_failed",
                    "message": "Preflight checks failed; Automation cannot fire.",
                    "errors": preflight_result.errors,
                    "warnings": preflight_result.warnings,
                },
            )

        policy_preflight = AutomationPolicyPreflightService(self.db).check(
            space_id=space_id,
            agent_id=auto.agent_id,
            workspace_id=auto.workspace_id,
            trigger_origin="automation",
        )
        if not policy_preflight.executable:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "policy_preflight_failed",
                    "message": "Policy preflight checks failed; Automation cannot fire.",
                    "errors": policy_preflight.errors,
                    "warnings": policy_preflight.warnings,
                    "checks": [c.model_dump() for c in policy_preflight.checks],
                },
            )

        run = RunService(self.db).create_run(
            agent_id=auto.agent_id,
            data=RunCreate(
                trigger_origin="automation",
                workspace_id=auto.workspace_id,
                prompt=prompt,
                instruction=instruction,
            ),
            space_id=space_id,
            user_id=actor_user_id,
            commit=False,
        )

        auto_run = AutomationRun(
            automation_id=auto.id,
            run_id=run.id,
            triggered_by_user_id=actor_user_id,
            trigger_type="manual",
            preflight_snapshot_json=self._preflight_snapshot(
                runtime_preflight=preflight_result.model_dump(),
                policy_preflight=policy_preflight.model_dump(),
            ),
        )
        self.db.add(auto_run)
        self.db.flush()

        return AutomationFireResult(
            run_id=run.id,
            automation_run_id=auto_run.id,
            trigger_origin="automation",
            preflight_executable=True,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, automation_id: str, space_id: str) -> Automation:
        return self._get_or_404(automation_id, space_id)

    def list(self, space_id: str) -> list[Automation]:
        return (
            self.db.query(Automation)
            .filter(Automation.space_id == space_id)
            .order_by(Automation.created_at.desc())
            .all()
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_404(self, automation_id: str, space_id: str) -> Automation:
        auto = (
            self.db.query(Automation)
            .filter(Automation.id == automation_id, Automation.space_id == space_id)
            .first()
        )
        if auto is None:
            raise HTTPException(status_code=404, detail=f"Automation '{automation_id}' not found in space '{space_id}'")
        return auto

    def _preflight_snapshot(
        self,
        *,
        runtime_preflight: dict[str, Any],
        policy_preflight: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_ok = bool(runtime_preflight.get("executable"))
        policy_ok = bool(policy_preflight.get("executable"))
        return {
            "executable": runtime_ok and policy_ok,
            "runtime_preflight": runtime_preflight,
            "policy_preflight": policy_preflight,
        }
