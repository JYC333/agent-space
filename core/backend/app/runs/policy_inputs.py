from __future__ import annotations

"""Shared policy input construction for runtime execution and simulation."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..models import AgentVersion, Credential, ModelProvider, Run
from ..policy.gateway import PolicyCheckRequest
from ..runtimes.requirements import RuntimeRequirements
from .adapter_resolution import ResolvedRuntimeAdapter
from .runtime_policy import RuntimePolicyDecision


class CredentialPolicyMetadataError(Exception):
    """Fail-closed credential metadata resolution error."""

    def __init__(self, message: str, *, error_code: str = "credential_metadata_missing"):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class CredentialPolicySubject:
    credential_id: str
    credential_space_id: str
    resolution_source: str
    has_model_provider: bool


def build_runtime_execute_policy_request(
    run: Run,
    agent_version: AgentVersion,
    resolved_adapter: ResolvedRuntimeAdapter,
    runtime_policy_decision: RuntimePolicyDecision,
    agent_status: str | None,
) -> PolicyCheckRequest:
    trigger_origin = getattr(run, "trigger_origin", "manual") or "manual"
    raw_tool_permissions = getattr(agent_version, "tool_permissions_json", None)
    agent_tool_permissions = raw_tool_permissions if isinstance(raw_tool_permissions, list) else None
    instructed_by = getattr(run, "instructed_by_user_id", None)

    if instructed_by and trigger_origin == "manual":
        actor_type = "user"
        actor_id = str(instructed_by)
        actor_ref = None
    else:
        actor_type = "run"
        actor_id = str(run.id)
        actor_ref = {
            "run_id": str(run.id),
            "trigger_origin": trigger_origin,
        }

    return PolicyCheckRequest(
        action="runtime.execute",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_ref=actor_ref,
        space_id=run.space_id,
        resource_type="run",
        resource_id=str(run.id),
        run_id=str(run.id),
        context={
            "agent_status": agent_status,
            "agent_tool_permissions": agent_tool_permissions,
            "tool_name": resolved_adapter.adapter_type,
            "adapter_type": resolved_adapter.adapter_type,
            "trigger_origin": trigger_origin,
            "risk_level": runtime_policy_decision.risk_level,
            "required_sandbox_level": runtime_policy_decision.required_sandbox_level,
            "data_exposure_level": getattr(run, "data_exposure_level", None),
            "trust_level": getattr(run, "trust_level", None),
            "observability_level": getattr(run, "observability_level", None),
        },
        metadata_json={
            "agent_id": str(run.agent_id) if getattr(run, "agent_id", None) else None,
            "agent_version_id": (
                str(run.agent_version_id) if getattr(run, "agent_version_id", None) else None
            ),
            "runtime_adapter_id": (
                str(resolved_adapter.runtime_adapter_row.id)
                if resolved_adapter.runtime_adapter_row else None
            ),
            "adapter_type": resolved_adapter.adapter_type,
            "workspace_id": str(run.workspace_id) if getattr(run, "workspace_id", None) else None,
            "trigger_origin": trigger_origin,
            "risk_level": runtime_policy_decision.risk_level,
            "required_sandbox_level": runtime_policy_decision.required_sandbox_level,
            "data_exposure_level": getattr(run, "data_exposure_level", None),
            "trust_level": getattr(run, "trust_level", None),
            "observability_level": getattr(run, "observability_level", None),
            "agent_status": agent_status,
        },
    )


def _provider_subject(
    db: Session,
    *,
    run: Run,
    provider_id: str,
    source: str,
) -> CredentialPolicySubject:
    provider = db.query(ModelProvider).filter(ModelProvider.id == provider_id).first()
    if provider is None:
        raise CredentialPolicyMetadataError(
            f"ModelProvider metadata missing for provider_id={provider_id!r} "
            f"(via {source}); failing closed before secret resolution."
        )
    if provider.space_id != run.space_id:
        raise CredentialPolicyMetadataError(
            f"credential_metadata_cross_space: ModelProvider {provider_id!r} is in space {provider.space_id!r}, "
            f"not run space {run.space_id!r} (via {source}); failing closed before secret resolution.",
        )
    if not provider.enabled:
        raise CredentialPolicyMetadataError(
            f"ModelProvider {provider_id!r} is disabled (via {source}); "
            "failing closed before secret resolution.",
            error_code="credential_metadata_disabled_provider",
        )
    if not provider.credential_id:
        raise CredentialPolicyMetadataError(
            f"ModelProvider metadata missing for provider_id={provider_id!r} "
            f"(via {source}); failing closed before secret resolution."
        )
    credential = db.query(Credential).filter(Credential.id == provider.credential_id).first()
    if credential is None:
        raise CredentialPolicyMetadataError(
            f"Credential row missing for provider_id={provider_id!r} "
            f"(via {source}); failing closed before secret resolution."
        )
    return CredentialPolicySubject(
        credential_id=str(provider.credential_id),
        credential_space_id=credential.space_id,
        resolution_source=source,
        has_model_provider=True,
    )


def _credential_subject(
    db: Session,
    *,
    run: Run,
    credential_id: str,
    source: str,
) -> CredentialPolicySubject:
    credential = db.query(Credential).filter(Credential.id == credential_id).first()
    if credential is None:
        raise CredentialPolicyMetadataError(
            f"Credential row missing for credential_id={credential_id!r} "
            f"(via {source}); failing closed before secret resolution."
        )
    return CredentialPolicySubject(
        credential_id=credential_id,
        credential_space_id=credential.space_id,
        resolution_source=source,
        has_model_provider=False,
    )


def resolve_runtime_credential_policy_metadata(
    db: Session,
    run: Run,
    agent_version: AgentVersion,
    resolved_adapter: ResolvedRuntimeAdapter,
    runtime_requirements: RuntimeRequirements,
) -> CredentialPolicySubject | None:
    """Resolve credential metadata for policy only, without decrypting secrets."""
    if runtime_requirements.credential_mode != "model_provider_api_key":
        return None

    if getattr(run, "model_provider_id", None):
        return _provider_subject(
            db,
            run=run,
            provider_id=run.model_provider_id,
            source="run.model_provider_id",
        )

    row = resolved_adapter.runtime_adapter_row
    if row is not None and getattr(row, "provider_id", None):
        return _provider_subject(
            db,
            run=run,
            provider_id=row.provider_id,
            source="runtime_adapter.provider_id",
        )

    if getattr(agent_version, "model_provider_id", None):
        return _provider_subject(
            db,
            run=run,
            provider_id=agent_version.model_provider_id,
            source="agent_version.model_provider_id",
        )

    if row is not None and getattr(row, "credential_id", None):
        return _credential_subject(
            db,
            run=run,
            credential_id=str(row.credential_id),
            source="runtime_adapter.credential_id",
        )

    return None


def build_runtime_use_credential_policy_request(
    run: Run,
    credential_policy_subject: CredentialPolicySubject,
    runtime_policy_decision: RuntimePolicyDecision,
    adapter_type: str | None,
) -> PolicyCheckRequest:
    trigger_origin = getattr(run, "trigger_origin", "manual") or "manual"
    return PolicyCheckRequest(
        action="runtime.use_credential",
        actor_type="run",
        actor_id=str(run.id),
        space_id=run.space_id,
        resource_type="credential",
        resource_id=credential_policy_subject.credential_id,
        resource_space_id=credential_policy_subject.credential_space_id,
        run_id=str(run.id),
        context={
            "trigger_origin": trigger_origin,
            "instructed_by_user_id": (
                str(run.instructed_by_user_id)
                if getattr(run, "instructed_by_user_id", None) else None
            ),
        },
        metadata_json={
            "resolution_source": credential_policy_subject.resolution_source,
            "adapter_type": adapter_type,
            "has_model_provider": credential_policy_subject.has_model_provider,
            "trigger_origin": trigger_origin,
            "credential_space_id": credential_policy_subject.credential_space_id,
            "risk_level": runtime_policy_decision.risk_level,
            "data_exposure_level": getattr(run, "data_exposure_level", None),
        },
    )
