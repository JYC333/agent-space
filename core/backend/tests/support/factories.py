"""Explicit DB factories for tests — minimal valid rows, no surprise side effects.

Persistence:
- By default each factory only ``add`` + ``flush`` so primary keys and FKs are
  available within the current transaction.
- Pass ``commit=True`` to ``commit()`` and ``refresh()`` the primary return value
  when a test needs data visible to another connection/session (e.g. ``TestClient``).

Rules:
- Call sites pass ``space_id`` (and ownership fields) explicitly when isolation matters.
- Proposals default to ``pending`` and never imply approval or active memory.
- No implicit second space or cross-tenant rows.

See ``# TODO: Capability`` at the bottom for registry-only capability objects.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy.orm import Session as DBSession
from ulid import ULID

from app.models import (
    Actor,
    ActivityRecord,
    Agent,
    AgentVersion,
    Artifact,
    ContextSnapshot,
    Credential,
    MemoryEntry,
    ModelProvider,
    Policy,
    Project,
    ProjectWorkspace,
    Proposal,
    Run,
    RunStep,
    RuntimeAdapter,
    Space,
    SpaceMembership,
    User,
    Workspace,
)
from app.schemas import (
    DEFAULT_MEMORY_POLICY,
    DEFAULT_MODEL_CONFIG,
    DEFAULT_RUNTIME_POLICY,
    RunCreate,
)

T = TypeVar("T")


def _new_id() -> str:
    return str(ULID())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _finish(db: DBSession, row: T, *, commit: bool) -> T:
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row


def create_test_space(
    db: DBSession,
    *,
    space_id: str,
    name: str | None = None,
    space_type: str = "personal",
    created_by_user_id: str | None = None,
    commit: bool = False,
) -> Space:
    row = Space(
        id=space_id,
        name=name or f"space-{space_id}",
        type=space_type,
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_user(
    db: DBSession,
    *,
    space_id: str,
    user_id: str | None = None,
    email: str | None = None,
    display_name: str | None = None,
    commit: bool = False,
) -> User:
    uid = user_id or _new_id()
    row = User(
        id=uid,
        space_id=space_id,
        email=email or f"{uid}@test.invalid",
        display_name=display_name or uid,
    )
    db.add(row)
    db.add(SpaceMembership(
        id=_new_id(),
        space_id=space_id,
        user_id=uid,
        role="owner",
        status="active",
    ))
    return _finish(db, row, commit=commit)


def create_test_agent(
    db: DBSession,
    *,
    space_id: str,
    owner_user_id: str,
    name: str = "test-agent",
    commit: bool = False,
) -> Agent:
    """Materialize ``Agent`` + initial ``AgentVersion`` (v1) like ``AgentService``, without committing."""
    agent_id = _new_id()
    version_id = _new_id()
    agent = Agent(
        id=agent_id,
        space_id=space_id,
        owner_user_id=owner_user_id,
        name=name,
        status="active",
        current_version_id=version_id,
    )
    version = AgentVersion(
        id=version_id,
        agent_id=agent_id,
        space_id=space_id,
        version_label="v1",
        model_config_json=dict(DEFAULT_MODEL_CONFIG),
        memory_policy_json=dict(DEFAULT_MEMORY_POLICY),
        capabilities_json=[],
        tool_permissions_json={},
        runtime_policy_json=dict(DEFAULT_RUNTIME_POLICY),
    )
    db.add(agent)
    db.add(version)
    return _finish(db, agent, commit=commit)


def create_test_model_provider(
    db: DBSession,
    *,
    space_id: str,
    name: str = "test-model-provider",
    provider_type: str = "openai",
    credential_id: str | None = None,
    default_model: str | None = "gpt-test",
    base_url: str | None = None,
    enabled: bool = True,
    with_api_key: bool = False,
    is_default: bool = False,
    available_models: list[str] | None = None,
    commit: bool = False,
) -> ModelProvider:
    cfg: dict = {"is_default": is_default}
    models = available_models if available_models is not None else ([default_model] if default_model else [])
    row = ModelProvider(
        id=_new_id(),
        space_id=space_id,
        name=name,
        provider_type=provider_type,
        credential_id=credential_id,
        default_model=default_model,
        base_url=base_url,
        enabled=enabled,
        capabilities_json={"models": models},
        config_json=cfg,
    )
    db.add(row)
    db.flush()
    if with_api_key:
        from app.crypto import encrypt_to_base64
        from app.secrets.secret_ref import encode_model_provider_api_key_secret_ref
        ek, kn = encrypt_to_base64("sk-test-factory-key")
        secret_ref = encode_model_provider_api_key_secret_ref(ek, kn)
        cred = Credential(
            id=_new_id(),
            space_id=space_id,
            name=f"{name} API key",
            credential_type="api_key",
            secret_ref=secret_ref,
            scopes_json=[],
        )
        db.add(cred)
        db.flush()
        row.credential_id = cred.id
    return _finish(db, row, commit=commit)


def create_test_runtime_adapter(
    db: DBSession,
    *,
    space_id: str,
    name: str = "test-runtime-adapter",
    adapter_type: str = "echo",
    provider_id: str | None = None,
    credential_id: str | None = None,
    enabled: bool = True,
    commit: bool = False,
) -> RuntimeAdapter:
    row = RuntimeAdapter(
        id=_new_id(),
        space_id=space_id,
        name=name,
        adapter_type=adapter_type,
        enabled=enabled,
        provider_id=provider_id,
        credential_id=credential_id,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_credential_stub(
    db: DBSession,
    *,
    space_id: str,
    name: str = "stub-credential",
    credential_type: str = "api_key",
    secret_ref: str = "stub://no-secret",
    commit: bool = False,
) -> Credential:
    row = Credential(
        id=_new_id(),
        space_id=space_id,
        name=name,
        credential_type=credential_type,
        secret_ref=secret_ref,
        scopes_json=[],
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_workspace(
    db: DBSession,
    *,
    space_id: str,
    root_path: str | None = None,
    name: str | None = None,
    created_by_user_id: str | None = None,
    workspace_type: str = "project",
    metadata_json: dict[str, Any] | None = None,
    allow_external_root: bool = False,
    commit: bool = False,
) -> Workspace:
    row = Workspace(
        id=_new_id(),
        space_id=space_id,
        name=name or "test-workspace",
        root_path=root_path,
        created_by_user_id=created_by_user_id,
        workspace_type=workspace_type,
        metadata_json=metadata_json,
        allow_external_root=allow_external_root,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_policy(
    db: DBSession,
    *,
    space_id: str,
    name: str = "test-policy",
    domain: str = "runtime",
    policy_key: str | None = None,
    status: str = "active",
    enforcement_mode: str | None = None,
    priority: int = 0,
    rule_json: dict[str, Any] | None = None,
    applies_to_json: dict[str, Any] | None = None,
    policy_json: dict[str, Any] | None = None,
    enabled: bool = True,
    commit: bool = False,
) -> Policy:
    row = Policy(
        id=_new_id(),
        space_id=space_id,
        name=name,
        domain=domain,
        policy_key=policy_key,
        status=status,
        enforcement_mode=enforcement_mode,
        priority=priority,
        rule_json=dict(rule_json) if rule_json is not None else None,
        applies_to_json=dict(applies_to_json) if applies_to_json is not None else None,
        policy_json=dict(policy_json or {}),
        enabled=enabled,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_run(
    db: DBSession,
    *,
    space_id: str,
    user_id: str,
    agent: Agent | None = None,
    owner_user_id: str | None = None,
    mode: str = "live",
    commit: bool = False,
) -> Run:
    """Queued ``Run`` + ``ContextSnapshot`` (same shape as ``RunService.create_run`` defaults)."""
    owner = owner_user_id or user_id
    ag = agent or create_test_agent(db, space_id=space_id, owner_user_id=owner, commit=False)
    data = RunCreate(mode=mode)

    snapshot = ContextSnapshot(
        id=_new_id(),
        space_id=space_id,
        source_refs_json=[],
        compiled_summary=None,
        token_estimate=None,
    )
    db.add(snapshot)

    run = Run(
        id=_new_id(),
        space_id=space_id,
        agent_id=ag.id,
        agent_version_id=ag.current_version_id,
        context_snapshot_id=snapshot.id,
        workspace_id=data.workspace_id,
        session_id=data.session_id,
        parent_run_id=None,
        instructed_by_user_id=user_id,
        instructed_by_agent_id=None,
        delegation_depth=0,
        run_type=data.run_type,
        trigger_origin=data.trigger_origin,
        status="queued",
        mode=data.mode,
        prompt=data.prompt,
        instruction=data.instruction,
        scheduled_at=data.scheduled_at,
        adapter_type=data.adapter_type,
        required_sandbox_level="none",
    )
    db.add(run)
    return _finish(db, run, commit=commit)


def create_test_activity(
    db: DBSession,
    *,
    space_id: str,
    actor_user_id: str | None = None,
    activity_type: str = "test.activity",
    title: str = "Test activity",
    content: str = "body",
    source_run_id: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    agent_id: str | None = None,
    payload_json: dict[str, Any] | None = None,
    source_kind: str | None = None,
    source_trust: str | None = None,
    consolidation_status: str = "pending",
    subject_user_id: str | None = None,
    commit: bool = False,
) -> ActivityRecord:
    now = _utcnow()
    row = ActivityRecord(
        id=_new_id(),
        space_id=space_id,
        source_run_id=source_run_id,
        session_id=session_id,
        user_id=actor_user_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        activity_type=activity_type,
        title=title,
        content=content,
        payload_json=dict(payload_json or {}),
        occurred_at=now,
        status="raw",
        updated_at=now,
        source_kind=source_kind,
        source_trust=source_trust,
        consolidation_status=consolidation_status,
        subject_user_id=subject_user_id,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_artifact(
    db: DBSession,
    *,
    space_id: str,
    run_id: str | None = None,
    artifact_type: str = "test_report",
    title: str = "Test artifact",
    content: str = "artifact body",
    preview: bool = False,
    commit: bool = False,
) -> Artifact:
    row = Artifact(
        id=_new_id(),
        space_id=space_id,
        run_id=run_id,
        artifact_type=artifact_type,
        title=title,
        content=content,
        mime_type="text/plain",
        preview=preview,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_proposal(
    db: DBSession,
    *,
    space_id: str,
    run_id: str | None = None,
    proposal_type: str = "memory_create",
    status: str = "pending",
    preview: bool = False,
    title: str = "Test proposal",
    created_by_user_id: str | None = None,
    created_by_agent_id: str | None = None,
    workspace_id: str | None = None,
    payload_json: dict[str, Any] | None = None,
    commit: bool = False,
) -> Proposal:
    now = _utcnow()
    uid = created_by_user_id or ""

    # Memory-specific base payload only applies to memory and policy proposal types.
    # Other proposal types (follow_up_task, code_patch, etc.) start from an empty base
    # so caller-supplied payload_json is not polluted with memory fields.
    if proposal_type in ("memory_create", "memory_update", "memory_archive", "policy_change"):
        base_payload: dict[str, Any] = {
            "operation": "create",
            "proposed_content": "proposed text",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "agent.test",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
        }
        merged = {**base_payload, **(payload_json or {})}
        if "provenance_entries" not in merged:
            merged["provenance_entries"] = [
                {
                    "source_type": "user_confirmation",
                    "source_id": uid,
                    "source_trust": "user_confirmed",
                    "evidence_json": {"origin": "test_factory"},
                }
            ]
    else:
        merged = dict(payload_json or {})
    row = Proposal(
        id=_new_id(),
        space_id=space_id,
        created_by_run_id=run_id,
        proposal_type=proposal_type,
        status=status,
        risk_level="low",
        urgency="normal",
        preview=preview,
        title=title,
        summary="factory proposal",
        payload_json=merged,
        rationale="test factory",
        workspace_id=workspace_id,
        created_by_user_id=created_by_user_id,
        created_by_agent_id=created_by_agent_id,
        review_deadline=now + timedelta(hours=48),
        expires_at=now + timedelta(days=14),
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_memory_entry(
    db: DBSession,
    *,
    space_id: str,
    content: str = "memory content",
    scope_type: str = "agent",
    scope_id: str | None = None,
    memory_type: str = "semantic",
    status: str = "active",
    source_proposal_id: str | None = None,
    owner_user_id: str | None = None,
    subject_user_id: str | None = None,
    agent_id: str | None = None,
    workspace_id: str | None = None,
    namespace: str | None = None,
    commit: bool = False,
) -> MemoryEntry:
    row = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type=scope_type,
        scope_id=scope_id,
        memory_type=memory_type,
        content=content,
        status=status,
        source_proposal_id=source_proposal_id,
        owner_user_id=owner_user_id,
        subject_user_id=subject_user_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        namespace=namespace,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_actor(
    db: DBSession,
    *,
    actor_type: str,
    space_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    service_name: str | None = None,
    display_name: str | None = None,
    status: str = "active",
    commit: bool = False,
) -> Actor:
    """Minimal Actor row.  Caller is responsible for satisfying actor_type invariants:
    - actor_type='user'  → user_id required, agent_id None
    - actor_type='agent' → agent_id required, user_id None
    - actor_type in (system/service/job/…) → user_id None, agent_id None
    """
    row = Actor(
        id=_new_id(),
        actor_type=actor_type,
        space_id=space_id,
        user_id=user_id,
        agent_id=agent_id,
        service_name=service_name,
        display_name=display_name or actor_type,
        status=status,
        metadata_json={},
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_run_step(
    db: DBSession,
    *,
    run: Run,
    actor_id: str,
    step_type: str = "queued",
    status: str = "succeeded",
    title: str | None = None,
    step_index: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    commit: bool = False,
) -> RunStep:
    """Minimal RunStep row for tests.  step_index auto-computed if omitted."""
    from sqlalchemy import func as _func

    if step_index is None:
        current_max = (
            db.query(_func.max(RunStep.step_index))
            .filter(RunStep.run_id == run.id)
            .scalar()
        )
        step_index = 0 if current_max is None else current_max + 1

    now = _utcnow()
    row = RunStep(
        id=_new_id(),
        space_id=run.space_id,
        run_id=run.id,
        actor_id=actor_id,
        step_index=step_index,
        step_type=step_type,
        status=status,
        title=title or step_type,
        started_at=now,
        ended_at=now if status in ("succeeded", "failed", "cancelled", "skipped") else None,
        error_type=error_type,
        error_message=error_message,
        metadata_json=dict(metadata_json or {}),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_project(
    db: DBSession,
    *,
    space_id: str,
    name: str = "test-project",
    owner_user_id: str | None = None,
    status: str = "active",
    description: str | None = None,
    commit: bool = False,
) -> Project:
    row = Project(
        id=_new_id(),
        space_id=space_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        status=status,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


def create_test_project_workspace_link(
    db: DBSession,
    *,
    project: Project,
    workspace: Workspace,
    role: str = "reference",
    commit: bool = False,
) -> ProjectWorkspace:
    row = ProjectWorkspace(
        id=_new_id(),
        project_id=project.id,
        workspace_id=workspace.id,
        role=role,
    )
    db.add(row)
    return _finish(db, row, commit=commit)


# ---------------------------------------------------------------------------
# TODO: Capability (no ORM / table)
# ---------------------------------------------------------------------------
#
# Capabilities are file-defined (``FileDefinedCapability``) and loaded via
# ``CapabilityRegistry`` — there is no ``capabilities`` SQL table. Tests that
# need a capability manifest should build an in-memory dict / temp YAML file
# instead of calling a DB factory here.
