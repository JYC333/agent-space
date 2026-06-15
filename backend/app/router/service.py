from __future__ import annotations

"""Canonical router service for intent, task, and adapter decisions."""

from collections.abc import Callable
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import AgentVersion, Run
from ..runtimes import RuntimeAdapterSpec, get_runtime_adapter_spec
from .decisions import (
    AdapterDecision,
    AdapterResolutionError,
    ResolvedRuntimeAdapter,
    RoutingDecision,
    TaskClassification,
    TaskRouteDecision,
)

RuntimeSpecGetter = Callable[[str], RuntimeAdapterSpec]
ImplementationChecker = Callable[[str], bool]
# (adapter_type, effective adapter provider_id or None) -> None
AdapterPolicyValidator = Callable[[str], None]


class RouterService:
    """Single owner for router decisions.

    Callers may supply a policy validator when adapter routing needs
    caller-owned policy checks (for example, model-provider allowlists during
    run execution). The route selection and error ordering remain owned here.
    """

    def __init__(
        self,
        db: Session | None = None,
        *,
        spec_getter: RuntimeSpecGetter | None = None,
        implementation_checker: ImplementationChecker | None = None,
    ) -> None:
        self.db = db
        self._spec_getter = spec_getter or get_runtime_adapter_spec
        self._implementation_checker = (
            implementation_checker or self._is_adapter_type_implemented
        )

    # ------------------------------------------------------------------
    # Intent routing
    # ------------------------------------------------------------------

    def classify_intent(
        self,
        message: str,
        *,
        space_id: str,
        user_id: str,
        workspace_id: Optional[str] = None,
    ) -> Optional[RoutingDecision]:
        del user_id  # Reserved for future policy-aware intent classification.
        stripped = message.strip()
        if not stripped.startswith("/"):
            return None
        return self._parse_command(stripped, space_id, workspace_id)

    def _parse_command(
        self,
        command: str,
        space_id: str,
        workspace_id: Optional[str],
    ) -> Optional[RoutingDecision]:
        parts = command.lstrip("/").split()
        if not parts:
            return None

        match parts:
            case ["memory", "reflect", *_]:
                return RoutingDecision(
                    capability_id="memory.reflect",
                    space_id=space_id,
                    workspace_id=workspace_id,
                    action="memory.reflect",
                )
            case ["agent", "run", agent_name, *rest]:
                return RoutingDecision(
                    agent_id=agent_name,
                    space_id=space_id,
                    workspace_id=workspace_id,
                    action="runtime.execute",
                    params={"extra": rest},
                )
            case ["capabilities", "list"]:
                return RoutingDecision(
                    space_id=space_id,
                    action="capabilities.list",
                )

        return None

    # ------------------------------------------------------------------
    # Task routing
    # ------------------------------------------------------------------

    def classify_task(
        self,
        *,
        task_type: str | None,
        risk_level: str,
        requires_filesystem: bool,
        requires_terminal: bool,
        requires_git: bool,
        requires_long_reasoning: bool,
    ) -> TaskClassification:
        return TaskClassification(
            task_type=task_type or "generic",
            risk_level=risk_level,
            requires_filesystem=requires_filesystem,
            requires_terminal=requires_terminal,
            requires_git=requires_git,
            requires_long_reasoning=requires_long_reasoning,
        )

    def classify_needs_cli(self, classification: TaskClassification) -> bool:
        return classification.needs_cli

    def resolve_adapter(
        self,
        requested_adapter: str,
        classification: TaskClassification,
    ) -> str:
        del classification
        return requested_adapter

    def route_task(
        self,
        *,
        requested_adapter: str,
        task_type: str | None,
        risk_level: str,
        requires_filesystem: bool,
        requires_terminal: bool,
        requires_git: bool,
        requires_long_reasoning: bool,
    ) -> TaskRouteDecision:
        classification = self.classify_task(
            task_type=task_type,
            risk_level=risk_level,
            requires_filesystem=requires_filesystem,
            requires_terminal=requires_terminal,
            requires_git=requires_git,
            requires_long_reasoning=requires_long_reasoning,
        )
        adapter_type = self.resolve_adapter(requested_adapter, classification)
        return TaskRouteDecision(
            requested_adapter=requested_adapter,
            adapter_type=adapter_type,
            classification=classification,
            needs_cli=classification.needs_cli,
        )

    # ------------------------------------------------------------------
    # Runtime adapter routing
    # ------------------------------------------------------------------

    def preview_run_adapter_type(
        self,
        *,
        space_id: str,
        version: AgentVersion,
        requested_adapter_type: str | None = None,
    ) -> str | None:
        """Resolve the adapter type used by Run creation previews.

        Run creation needs the selected adapter type to decide whether model
        provider defaults apply, but it is not the execution enforcement point.
        Keep this lightweight: use the same selection priority as execution,
        while leaving catalog, enabled-state, and policy failures to the
        existing creation/execution checks.
        """
        del space_id
        runtime_config = dict(version.runtime_config_json or {})
        policy = dict(version.runtime_policy_json or {})
        return (
            (requested_adapter_type or "").strip()
            or (runtime_config.get("adapter_type") or "").strip()
            or (str(policy.get("default_adapter_type") or "").strip())
            or "model_api"
        )

    def resolve_runtime_adapter(
        self,
        *,
        run: Run,
        version: AgentVersion,
        policy: dict[str, Any],
        validate_policy: AdapterPolicyValidator | None = None,
    ) -> ResolvedRuntimeAdapter:
        """Resolve the concrete adapter for an executable Run.

        Resolution order:
          1. Run.adapter_type
          2. AgentVersion.runtime_config_json.adapter_type
          3. AgentVersion.runtime_policy_json.default_adapter_type
          4. system default model_api
        """
        runtime_config = dict(version.runtime_config_json or {})
        adapter_type = (
            (run.adapter_type or "").strip()
            or (runtime_config.get("adapter_type") or "").strip()
            or (str(policy.get("default_adapter_type") or "").strip())
            or "model_api"
        )
        merged = runtime_config

        self._validate_runtime_catalog(adapter_type)
        self._validate_allowed_adapter(adapter_type, policy)
        if validate_policy is not None:
            validate_policy(adapter_type)
        self._validate_implemented(adapter_type)
        if adapter_type == "capability" and run.capability_id:
            merged = self._merge_capability_config(run, merged)

        return ResolvedRuntimeAdapter(
            adapter_type=adapter_type,
            merged_config=merged,
        )

    def resolve_preflight_adapter(
        self,
        *,
        space_id: str,
        version: AgentVersion,
        requested_adapter_type: str | None = None,
    ) -> ResolvedRuntimeAdapter:
        """Resolve adapter type for Run preflight's visible inputs."""
        del space_id
        runtime_config = dict(version.runtime_config_json or {})
        adapter_type = (
            (requested_adapter_type or "").strip()
            or (runtime_config.get("adapter_type") or "").strip()
            or (str((version.runtime_policy_json or {}).get("default_adapter_type") or "").strip())
            or "model_api"
        )
        merged = runtime_config

        self._validate_runtime_catalog(adapter_type)
        self._validate_implemented(adapter_type)
        return ResolvedRuntimeAdapter(
            adapter_type=adapter_type,
            merged_config=merged,
        )

    def resolve_automation_adapter(
        self,
        *,
        version: AgentVersion,
        policy: dict[str, Any],
    ) -> AdapterDecision:
        """Resolve adapter metadata for automation policy simulation.

        Automation policy simulation resolves adapter type from AgentVersion
        config/policy only.
        """
        runtime_config = dict(version.runtime_config_json or {})
        adapter_type = (
            (runtime_config.get("adapter_type") or "").strip()
            or (str(policy.get("default_adapter_type") or "").strip())
        )
        merged = runtime_config

        return AdapterDecision(
            adapter_type=adapter_type,
            merged_config=merged,
        )

    def _validate_runtime_catalog(self, adapter_type: str) -> None:
        try:
            spec = self._spec_getter(adapter_type)
        except KeyError:
            raise AdapterResolutionError(
                "adapter_type_unknown",
                f"Runtime adapter type '{adapter_type}' is not in the RuntimeAdapterSpec catalog",
            )
        if spec.implementation_status == "planned":
            raise AdapterResolutionError(
                "adapter_planned_not_executable",
                f"Runtime adapter type '{adapter_type}' is planned and cannot execute",
            )
        if spec.implementation_status == "disabled":
            raise AdapterResolutionError(
                "adapter_disabled",
                f"Runtime adapter type '{adapter_type}' is disabled by spec",
            )

    def _validate_allowed_adapter(self, adapter_type: str, policy: dict[str, Any]) -> None:
        allowed = policy.get("allowed_adapter_types")
        if allowed is not None and isinstance(allowed, list) and len(allowed) > 0:
            if adapter_type not in allowed:
                raise AdapterResolutionError(
                    "adapter_type_disallowed",
                    f"adapter_type '{adapter_type}' is not allowed by runtime_policy_json.allowed_adapter_types",
                )

    def _validate_implemented(self, adapter_type: str) -> None:
        if not self._implementation_checker(adapter_type):
            raise AdapterResolutionError(
                "adapter_not_implemented",
                f"Runtime adapter type '{adapter_type}' is not implemented",
            )

    def _merge_capability_config(
        self,
        run: Run,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        from dataclasses import asdict

        from ..capabilities import CapabilityRegistry

        registry = CapabilityRegistry(self._require_db())
        registry.reload(space_id=run.space_id)
        cap = registry.get(run.capability_id)
        if cap is not None:
            if not cap.enabled:
                raise AdapterResolutionError(
                    "capability_disabled",
                    f"Capability '{run.capability_id}' is disabled",
                )
            return {**merged, "capability": asdict(cap)}
        return merged

    def _is_adapter_type_implemented(self, adapter_type: str) -> bool:
        try:
            return self._spec_getter(adapter_type).implementation_status == "implemented"
        except KeyError:
            return False

    def _require_db(self) -> Session:
        if self.db is None:
            raise RuntimeError("RouterService requires a database session for adapter routing")
        return self.db
