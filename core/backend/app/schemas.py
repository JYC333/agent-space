from datetime import datetime
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator

ItemT = TypeVar('ItemT')


class Page(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Agent defaults (used in AgentCreate and service layer)
# ---------------------------------------------------------------------------

DEFAULT_MODEL_CONFIG: dict = {
    "model": "claude-sonnet-4-6",
    "max_tokens": 8192,
}

DEFAULT_MEMORY_POLICY: dict = {
    # scopes this agent may read from context
    "readable_scopes": ["system", "space", "user", "workspace", "capability", "agent"],
    # scopes this agent may write to directly (without proposal); everything else requires proposal
    "writable_scopes": ["agent"],
    "readable_types": ["preference", "semantic", "episodic", "procedural", "project"],
}

DEFAULT_RUNTIME_POLICY: dict = {
    "risk_level": "medium",  # low | medium | high | critical — controls sandbox level
    "can_delegate": True,
    "max_delegation_depth": 3,
    "max_run_time_seconds": 300,
    # adapter_ids this agent may use; matches RuntimeAdapter.adapter_id or adapter_type
    "allowed_adapter_types": [
        "echo",
        "anthropic_messages",
        "claude_code",
        "codex_cli",
        "opencode",
        "gemini_cli",
    ],
    # Used when no RuntimeAdapter FK and no explicit adapter_type on Run / runtime_config_json.
    "default_adapter_type": "echo",
}


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_type: Optional[str] = None  # system_core blocked in create endpoint
    kind: str = "project"
    repo_url: Optional[str] = None
    root_path: Optional[str] = None
    default_branch: Optional[str] = None
    metadata_json: Optional[dict] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    kind: Optional[str] = None
    repo_url: Optional[str] = None
    root_path: Optional[str] = None
    default_branch: Optional[str] = None
    status: Optional[str] = None
    visibility: Optional[str] = None
    metadata_json: Optional[dict] = None


class WorkspaceOut(BaseModel):
    id: str
    owner_space_id: str
    created_by_user_id: str
    name: str
    slug: Optional[str]
    description: Optional[str]
    workspace_type: str
    kind: str
    repo_url: Optional[str]
    root_path: Optional[str]
    default_branch: Optional[str]
    visibility: str
    status: str
    protected: bool
    system_managed: bool
    registered_from: Optional[str]
    metadata_json: Optional[dict]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AgentVersionOut(BaseModel):
    id: str
    agent_id: str
    space_id: str
    version_label: str
    model_provider_id: Optional[str]
    model_name: Optional[str]
    runtime_adapter_id: Optional[str]
    system_prompt: Optional[str]
    model_config_json: dict
    runtime_config_json: dict
    context_policy_json: dict
    memory_policy_json: dict
    capabilities_json: list
    tool_permissions_json: dict
    runtime_policy_json: dict
    created_at: datetime
    published_at: Optional[datetime]
    archived_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AgentVersionCreate(BaseModel):
    version_label: Optional[str] = None
    model_provider_id: Optional[str] = None
    model_name: Optional[str] = None
    runtime_adapter_id: Optional[str] = None
    system_prompt: Optional[str] = None
    model_config_json: dict = Field(default_factory=lambda: dict(DEFAULT_MODEL_CONFIG))
    runtime_config_json: dict = Field(default_factory=lambda: dict(DEFAULT_RUNTIME_POLICY))
    context_policy_json: dict = Field(default_factory=dict)
    memory_policy_json: dict = Field(default_factory=lambda: dict(DEFAULT_MEMORY_POLICY))
    capabilities_json: list[str] = Field(default_factory=list)
    tool_permissions_json: dict = Field(default_factory=dict)
    runtime_policy_json: dict = Field(default_factory=lambda: dict(DEFAULT_RUNTIME_POLICY))


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    created_by_user_id: Optional[str] = None
    visibility: str = "private"
    role_instruction: Optional[str] = None
    space_id: Optional[str] = None
    # Optional v1 execution snapshot (stored on initial AgentVersion).
    model_config_json: Optional[dict] = None
    memory_policy_json: Optional[dict] = None
    capabilities_json: Optional[list[str]] = None
    tool_permissions_json: Optional[dict] = None
    runtime_policy_json: Optional[dict] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[str] = None
    role_instruction: Optional[str] = None
    status: Optional[str] = None
    # Execution config fields create a new AgentVersion when provided.
    model_config_json: Optional[dict] = None
    memory_policy_json: Optional[dict] = None
    capabilities_json: Optional[list[str]] = None
    tool_policy_json: Optional[list[str]] = None
    runtime_policy_json: Optional[dict] = None


class AgentOut(BaseModel):
    id: str
    space_id: str
    created_by_user_id: str
    name: str
    description: Optional[str]
    visibility: str
    role_instruction: Optional[str]
    status: str
    current_version_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RunRequest(BaseModel):
    """Used by both user→agent and agent→agent calls."""
    prompt: str
    workspace_id: Optional[str] = None
    workspace_path: Optional[str] = None
    # Prefer cli_adapter_config_id; adapter_type is used when no config id is supplied.
    cli_adapter_config_id: Optional[str] = None
    adapter_type: str = "echo"
    # cli_default | cli_model_override | agent_space_provider
    model_selection_mode: str = "cli_default"
    model_override_json: Optional[dict] = None
    risk_level: str = "medium"  # low | medium | high | critical
    # Set by the system when an agent delegates to another agent
    parent_run_id: Optional[str] = None
    instructed_by_agent_id: Optional[str] = None
    # Task routing signals — used by TaskRouter to choose the right adapter.
    # CLI adapters are only used when at least one of the requires_* flags is True
    # or the task_type maps to a heavy task. Lightweight tasks are redirected to
    # the direct Anthropic API adapter (no subprocess, no sandbox).
    task_type: Optional[str] = None  # e.g. summarize | classify | code_modify | maintenance
    requires_filesystem: bool = False
    requires_terminal: bool = False
    requires_git: bool = False
    requires_long_reasoning: bool = False


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class MemoryCreate(BaseModel):
    title: str
    content: str
    type: str  # preference | semantic | episodic | procedural | project
    scope: str = "user"
    namespace: str = "user.default"
    # private | space_shared | workspace_shared | selected_users | summary_only |
    # restricted | public_template
    visibility: str = "private"
    sensitivity_level: str = "normal"
    confidence: float = 1.0
    importance: float = 0.5
    tags: Optional[list[str]] = None
    source_id: Optional[str] = None
    space_id: Optional[str] = None
    subject_user_id: Optional[str] = None
    owner_user_id: Optional[str] = Field(
        default=None,
        description="Human who controls this memory for ACL; distinct from subject_user_id.",
    )
    selected_user_ids: Optional[list[str]] = None
    last_confirmed_at: Optional[datetime] = None
    source_proposal_id: Optional[str] = None
    workspace_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_memory_fields(self) -> "MemoryCreate":
        from app.memory.read_auth import SENSITIVITY_LEVELS, VISIBILITY_VALUES

        sl = (self.sensitivity_level or "normal").lower()
        if sl not in SENSITIVITY_LEVELS:
            raise ValueError(f"invalid sensitivity_level: {self.sensitivity_level!r}")
        object.__setattr__(self, "sensitivity_level", sl)

        vis = (self.visibility or "private").lower()
        if vis not in VISIBILITY_VALUES:
            raise ValueError(f"invalid visibility: {self.visibility!r}")
        object.__setattr__(self, "visibility", vis)

        if sl == "highly_restricted" and vis == "space_shared":
            raise ValueError("highly_restricted memories cannot use space_shared visibility for MVP")

        if self.selected_user_ids is not None and vis not in ("selected_users", "restricted"):
            raise ValueError("selected_user_ids is only valid when visibility is selected_users or restricted")

        if vis == "private" and self.owner_user_id is None:
            # Filled from acting user in MemoryStore.create when omitted
            pass

        if sl == "highly_restricted" and self.owner_user_id is None:
            raise ValueError("owner_user_id is required when sensitivity_level is highly_restricted")

        # TODO: validate subject_user_id / owner_user_id belong to the same space when membership service exists
        return self


class MemoryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    visibility: Optional[str] = None
    sensitivity_level: Optional[str] = None
    confidence: Optional[float] = None
    importance: Optional[float] = None
    tags: Optional[list[str]] = None
    subject_user_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    selected_user_ids: Optional[list[str]] = None
    last_confirmed_at: Optional[datetime] = None
    scope: Optional[str] = None
    namespace: Optional[str] = None
    type: Optional[str] = None
    workspace_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_memory_update(self) -> "MemoryUpdate":
        from app.memory.read_auth import SENSITIVITY_LEVELS, VISIBILITY_VALUES

        if self.sensitivity_level is not None:
            sl = self.sensitivity_level.lower()
            if sl not in SENSITIVITY_LEVELS:
                raise ValueError(f"invalid sensitivity_level: {self.sensitivity_level!r}")
            object.__setattr__(self, "sensitivity_level", sl)
        if self.visibility is not None:
            vis = self.visibility.lower()
            if vis not in VISIBILITY_VALUES:
                raise ValueError(f"invalid visibility: {self.visibility!r}")
            object.__setattr__(self, "visibility", vis)
        if self.selected_user_ids is not None and self.visibility is not None:
            if self.visibility not in ("selected_users", "restricted"):
                raise ValueError("selected_user_ids is only valid when visibility is selected_users or restricted")
        if self.sensitivity_level == "highly_restricted" and self.visibility == "space_shared":
            raise ValueError("highly_restricted memories cannot use space_shared visibility for MVP")
        return self


class MemoryOut(BaseModel):
    id: str
    space_id: str
    subject_user_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    workspace_id: Optional[str]
    scope: str
    namespace: Optional[str] = None
    type: str
    title: Optional[str] = None
    content: Optional[str] = None
    status: str
    visibility: str
    sensitivity_level: str = "normal"
    selected_user_ids: Optional[list[str]] = None
    last_confirmed_at: Optional[datetime] = None
    confidence: float
    importance: float
    source_id: Optional[str]
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    version: int
    tags: Optional[list]
    memory_layer: Optional[str] = None
    memory_kind: Optional[str] = None
    source_trust: Optional[str] = None
    created_from_proposal_id: Optional[str] = None
    root_memory_id: Optional[str] = None
    supersedes_memory_id: Optional[str] = None

    model_config = {"from_attributes": True}


class MemorySearchRequest(BaseModel):
    query: str
    scope: Optional[str] = None
    namespace: Optional[str] = None
    type: Optional[str] = None
    limit: int = 10
    space_id: Optional[str] = None
    user_id: Optional[str] = None
    workspace_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Memory Proposals
# ---------------------------------------------------------------------------

class ProposalOut(BaseModel):
    id: str
    space_id: str
    user_id: str
    workspace_id: Optional[str]
    source_session_id: Optional[str]
    source_task_id: Optional[str]
    source_run_id: Optional[str]
    created_by_run_id: Optional[str] = None
    proposal_type: str = "memory_create"
    # target_scope / target_namespace / memory_type / proposed_title / proposed_content
    # are populated from payload_json; they may be empty strings for non-memory proposal types.
    target_scope: str = ""
    target_namespace: str = ""
    memory_type: str = ""
    proposed_title: str = ""
    proposed_content: str = ""
    rationale: str = ""
    status: str
    risk_level: str = "low"
    urgency: str = "normal"
    preview: bool = False
    review_deadline: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    expired: bool = False
    created_at: datetime
    decided_at: Optional[datetime]
    resulting_memory_id: Optional[str]
    owner_user_id: Optional[str] = None
    subject_user_id: Optional[str] = None
    sensitivity_level: Optional[str] = None
    selected_user_ids: Optional[list] = None
    provenance_entries: Optional[list[dict]] = None
    source_activity_id: Optional[str] = None

    model_config = {"from_attributes": True}


class ProposalAcceptOut(BaseModel):
    """Body for ``POST /api/v1/proposals/{id}/accept`` — result varies by ``proposal_type``."""

    proposal: ProposalOut
    # memory_entry  — memory_create, memory_update, memory_archive accepted
    # code_patch_apply — code_patch accepted
    # policy_version   — policy_change accepted
    result_type: Literal["memory_entry", "code_patch_apply", "policy_version"]
    result: dict[str, Any]


class ActivityRecordOut(BaseModel):
    id: str
    space_id: str
    source_run_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    workspace_id: Optional[str] = None
    agent_id: Optional[str] = None
    source_task_id: Optional[str] = None
    source_url: Optional[str] = None
    activity_type: str
    title: Optional[str] = None
    content: Optional[str] = None
    payload_json: dict = Field(default_factory=dict)
    occurred_at: datetime
    created_at: datetime
    status: Optional[str] = None
    updated_at: Optional[datetime] = None
    source_kind: Optional[str] = None
    source_trust: Optional[str] = None
    subject_user_id: Optional[str] = None
    lifecycle_status: Optional[str] = None
    consolidation_status: Optional[str] = None

    model_config = {"from_attributes": True}


class ArtifactOut(BaseModel):
    id: str
    space_id: str
    run_id: Optional[str] = None
    proposal_id: Optional[str] = None
    artifact_type: str
    title: str
    mime_type: Optional[str] = None
    exportable: bool = True
    preview: bool = False
    storage_ref: Optional[str] = None
    storage_path: Optional[str] = None
    metadata_json: Optional[dict] = None
    has_inline_content: bool = False
    content: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class SessionCreate(BaseModel):
    title: Optional[str] = None
    workspace_id: Optional[str] = None
    metadata: Optional[dict] = None
    space_id: Optional[str] = None
    user_id: Optional[str] = None


class SessionOut(BaseModel):
    id: str
    space_id: str
    user_id: str
    workspace_id: Optional[str]
    title: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    role: str  # user | assistant | system | tool
    content: str
    metadata: Optional[dict] = None


class MessageOut(BaseModel):
    id: str
    session_id: str
    space_id: str
    user_id: str
    role: str
    content: str
    metadata_json: Optional[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReflectResponse(BaseModel):
    session_id: str
    proposals_created: int
    proposals: list[ProposalOut]


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

class ContextBuildRequest(BaseModel):
    workspace_id: Optional[str] = None
    task_type: Optional[str] = None
    capability_id: Optional[str] = None
    session_id: Optional[str] = None
    query: Optional[str] = None
    # If provided, restricts memory retrieval to the agent's memory_policy readable_scopes
    agent_id: Optional[str] = None


class ContextPackage(BaseModel):
    # Memory sections used by ContextCompiler for CLI file rendering.
    user_memory: list[MemoryOut] = []
    workspace_memory: list[MemoryOut] = []
    capability_memory: list[MemoryOut] = []
    agent_memory: list[MemoryOut] = []
    system_policy: list[MemoryOut] = []
    recent_session_summary: list[dict] = []
    relevant_episodes: list[MemoryOut] = []
    # Resolved context attachments (file, git_diff, memory_entry, etc.)
    attachments: list[dict] = []

    # Policy rows for stable prefix (raw dicts for serialisation).
    active_policies: list[dict] = []

    # Stable_prefix / dynamic_tail split (item lists, not rendered text).
    # These are lists of source_ref dicts that belong to each section.
    stable_prefix_refs: list[dict] = []
    dynamic_tail_refs: list[dict] = []

    # ContextSnapshot audit fields populated by ContextBuilder.
    source_refs: list[dict] = []
    retrieval_trace: dict = {}
    token_budget: dict = {}


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

class CapabilityOut(BaseModel):
    id: str
    name: str
    version: str
    description: Optional[str]
    entrypoint: Optional[str]
    manifest_json: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CapabilityReloadResponse(BaseModel):
    loaded: int
    failed: int
    details: list[dict]


# ---------------------------------------------------------------------------
# Task board (product-level tasks; not infrastructure jobs)
# ---------------------------------------------------------------------------


class BoardCreate(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_id: Optional[str] = None
    board_type: str = Field(default="workspace")
    status: str = Field(default="active")
    default_view: Optional[str] = None
    sort_order: Optional[int] = None
    metadata_json: Optional[dict] = None
    create_default_columns: bool = Field(default=True, description="Create standard workflow columns")


class BoardUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    board_type: Optional[str] = None
    status: Optional[str] = None
    default_view: Optional[str] = None
    sort_order: Optional[int] = None
    metadata_json: Optional[dict] = None
    deleted_at: Optional[datetime] = None


class BoardColumnOut(BaseModel):
    id: str
    space_id: str
    board_id: str
    name: str
    description: Optional[str]
    status_key: str
    position: int
    wip_limit: Optional[int]
    is_done_column: bool
    is_default_column: bool
    metadata_json: Optional[dict]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    model_config = {"from_attributes": True}


class BoardOut(BaseModel):
    id: str
    space_id: str
    workspace_id: Optional[str]
    name: str
    description: Optional[str]
    board_type: str
    status: str
    default_view: Optional[str]
    sort_order: Optional[int]
    metadata_json: Optional[dict]
    created_by_user_id: Optional[str]
    created_by_agent_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    workspace_id: Optional[str] = None
    board_id: Optional[str] = None
    column_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    task_type: str = Field(default="general")
    status: str = Field(default="inbox")
    priority: str = Field(default="normal")
    risk_level: str = Field(default="low")
    assigned_user_id: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    source_activity_id: Optional[str] = None
    source_run_id: Optional[str] = None
    source_proposal_id: Optional[str] = None
    source_artifact_id: Optional[str] = None
    acceptance_criteria_json: Optional[dict] = None
    definition_of_done: Optional[str] = None
    required_outputs_json: Optional[list] = None
    due_at: Optional[datetime] = None
    start_after: Optional[datetime] = None
    max_runs: Optional[int] = None
    max_cost: Optional[float] = None
    max_duration_seconds: Optional[int] = None
    policy_json: Optional[dict] = None
    metadata_json: Optional[dict] = None
    tags: Optional[list] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    workspace_id: Optional[str] = None
    board_id: Optional[str] = None
    column_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    task_type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    risk_level: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    claimed_by_user_id: Optional[str] = None
    claimed_by_agent_id: Optional[str] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    blocked_reason: Optional[str] = None
    due_at: Optional[datetime] = None
    start_after: Optional[datetime] = None
    estimated_effort: Optional[str] = None
    actual_effort: Optional[str] = None
    max_runs: Optional[int] = None
    max_cost: Optional[float] = None
    max_duration_seconds: Optional[int] = None
    policy_json: Optional[dict] = None
    metadata_json: Optional[dict] = None
    tags: Optional[list] = None
    deleted_at: Optional[datetime] = None


class TaskOut(BaseModel):
    id: str
    space_id: str
    workspace_id: Optional[str]
    board_id: Optional[str]
    column_id: Optional[str]
    parent_task_id: Optional[str]
    title: str
    description: Optional[str]
    task_type: str
    status: str
    priority: str
    risk_level: str
    created_by_user_id: Optional[str]
    created_by_agent_id: Optional[str]
    assigned_user_id: Optional[str]
    assigned_agent_id: Optional[str]
    claimed_by_user_id: Optional[str]
    claimed_by_agent_id: Optional[str]
    source_activity_id: Optional[str]
    source_run_id: Optional[str]
    source_proposal_id: Optional[str]
    source_artifact_id: Optional[str]
    due_at: Optional[datetime]
    start_after: Optional[datetime]
    completed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    blocked_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    model_config = {"from_attributes": True}


class TaskRunCreateBody(BaseModel):
    """POST /tasks/{id}/runs — optional overrides; agent_id falls back to task.assigned_agent_id."""

    agent_id: Optional[str] = None
    mode: str = Field(default="live")
    run_type: str = Field(default="agent")
    trigger_origin: str = Field(default="manual")
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    prompt: Optional[str] = None
    instruction: Optional[str] = None
    set_task_in_progress: bool = Field(default=True)
    parent_run_id: Optional[str] = None
    instructed_by_agent_id: Optional[str] = None
    adapter_type: Optional[str] = None


class TaskRunOut(BaseModel):
    id: str
    space_id: str
    task_id: str
    run_id: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ArtifactSummaryOut(BaseModel):
    id: str
    space_id: str
    run_id: Optional[str]
    proposal_id: Optional[str]
    artifact_type: str
    title: str
    mime_type: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ProposalSummaryOut(BaseModel):
    id: str
    space_id: str
    proposal_type: str
    status: str
    title: str
    created_at: datetime
    preview: bool = False
    urgency: str = "normal"
    review_deadline: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    expired: bool = False
    created_by_run_id: Optional[str] = None

    model_config = {"from_attributes": True}


class TaskArtifactOut(BaseModel):
    id: str
    space_id: str
    task_id: str
    artifact_id: str
    role: str
    created_at: datetime
    artifact: ArtifactSummaryOut

    model_config = {"from_attributes": True}


class TaskProposalOut(BaseModel):
    id: str
    space_id: str
    task_id: str
    proposal_id: str
    role: str
    created_at: datetime
    proposal: ProposalSummaryOut

    model_config = {"from_attributes": True}


class TaskEvaluationOut(BaseModel):
    id: str
    space_id: str
    task_id: str
    run_id: Optional[str]
    evaluator_type: str
    evaluator_user_id: Optional[str]
    evaluator_agent_id: Optional[str]
    score: Optional[float]
    confidence: Optional[float]
    summary: Optional[str]
    recommendation: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: str
    task_id: Optional[str]
    space_id: str
    user_id: str
    agent_id: Optional[str]
    cli_adapter_config_id: Optional[str]
    instructed_by_user_id: Optional[str]
    instructed_by_agent_id: Optional[str]
    parent_run_id: Optional[str]
    delegation_depth: int
    adapter_type: str
    capability_id: Optional[str]
    model_selection_mode: str
    model_override_json: Optional[dict]
    prompt: str
    status: str
    output: Optional[str]
    error: Optional[str]
    exit_code: Optional[int]
    sandbox_level: Optional[str]
    sandbox_path: Optional[str]
    executor_type: Optional[str]
    runtime_seconds: Optional[float]
    usage_accuracy: str
    estimated_input_tokens: Optional[int]
    estimated_output_tokens: Optional[int]
    estimated_cost: Optional[float]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Run Creation API
# ---------------------------------------------------------------------------

class RunCreate(BaseModel):
    """Input for POST /api/v1/agents/{id}/runs."""
    mode: str = Field(default="live")
    run_type: str = Field(default="agent")
    trigger_origin: str = Field(default="manual")
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    prompt: Optional[str] = None
    instruction: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    # Delegation (optional). Child runs require ``parent_run_id``;
    # ``delegation_depth`` is always derived server-side.
    parent_run_id: Optional[str] = None
    instructed_by_agent_id: Optional[str] = None
    adapter_type: Optional[str] = None


class RunOutV2(BaseModel):
    """Canonical Run output for the Run API."""
    id: str
    space_id: str
    agent_id: str
    agent_version_id: str
    context_snapshot_id: Optional[str]
    workspace_id: Optional[str]
    session_id: Optional[str]
    parent_run_id: Optional[str]
    delegation_depth: int = 0
    instructed_by_agent_id: Optional[str] = None
    run_type: str
    trigger_origin: str
    status: str
    mode: str
    prompt: Optional[str]
    instruction: Optional[str]
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str]
    error_json: Optional[dict]
    output_json: Optional[dict]
    usage_json: Optional[dict]
    adapter_type: Optional[str] = None
    model_provider_id: Optional[str] = None
    required_sandbox_level: str = "none"

    model_config = {"from_attributes": True}


class TaskRunListItem(BaseModel):
    """TaskRun association with full Run payload for task-scoped listing."""

    link: TaskRunOut
    run: RunOutV2


class RunStatusOut(BaseModel):
    """Lightweight status response for GET /runs/{id}/status."""
    id: str
    status: str
    mode: str
    run_type: str
    trigger_origin: str
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    error_message: Optional[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CLI Adapter Configs
# ---------------------------------------------------------------------------

class CLIAdapterConfigCreate(BaseModel):
    # claude_code | codex_cli | opencode | gemini_cli | custom | echo
    adapter_id: str
    display_name: str
    enabled: bool = True
    executable_path: Optional[str] = None
    default_mode: str = "headless"  # interactive | headless
    quota_status: str = "unknown"   # enough | medium | low | exhausted | unknown
    notes: Optional[str] = None
    space_id: Optional[str] = None


class CLIAdapterConfigUpdate(BaseModel):
    display_name: Optional[str] = None
    enabled: Optional[bool] = None
    executable_path: Optional[str] = None
    default_mode: Optional[str] = None
    quota_status: Optional[str] = None
    notes: Optional[str] = None


class CLIAdapterConfigOut(BaseModel):
    id: str
    space_id: str
    adapter_id: str
    display_name: str
    enabled: bool
    executable_path: Optional[str]
    default_mode: str
    quota_status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CLIStatusOut(BaseModel):
    """Detection result for a single CLI tool."""
    adapter_id: str
    available: bool
    version: Optional[str] = None
    executable_path: Optional[str] = None
    login_detected: Optional[bool] = None
    status_message: Optional[str] = None
    capabilities: Optional[dict] = None


class UsageEventOut(BaseModel):
    id: str
    run_id: str
    space_id: str
    user_id: str
    cli_adapter_config_id: Optional[str]
    event_type: str
    accuracy: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    estimated_cost: Optional[float]
    runtime_seconds: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

class ApiKeyCreate(BaseModel):
    name: str
    scope: str = "full"   # full | read_only | agent_only
    expires_at: Optional[datetime] = None


class ApiKeyOut(BaseModel):
    id: str
    space_id: str
    owner_user_id: str
    name: str
    scope: str
    status: str
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreatedOut(ApiKeyOut):
    """Returned once on creation — includes the raw key, never shown again."""
    raw_key: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Actor identity (M2 foundation)
# ---------------------------------------------------------------------------

ACTOR_TYPES = frozenset(
    {"user", "agent", "system", "automation", "connector", "integration", "service", "job"}
)


class ActorRef(BaseModel):
    """Stable serialized identity reference for any principal that acts in the system.

    Rules:
    - actor_type = user   → user_id required
    - actor_type = agent  → agent_id required
    - actor_type in (system, service, job, automation, connector, integration)
                          → user_id and agent_id must both be absent
    - actor_id is the persisted Actor.id when the actor row exists; optional
      for ad-hoc/ephemeral references (e.g. system events before actor row is created)
    - Do not use default_user_id from Settings as an ActorRef source for
      system/service/job actors — those must use actor_type=system/service/job

    Serialized shape is stable for RunStep, policy-decision, audit, and event JSON.
    """

    actor_type: str
    actor_id: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    space_id: Optional[str] = None
    service_name: Optional[str] = None
    display_name: Optional[str] = None

    @model_validator(mode="after")
    def validate_actor_identity(self) -> "ActorRef":
        if self.actor_type not in ACTOR_TYPES:
            raise ValueError(
                f"invalid actor_type: {self.actor_type!r}; "
                f"must be one of {sorted(ACTOR_TYPES)}"
            )
        if self.actor_type == "user":
            if not self.user_id:
                raise ValueError("user actor requires user_id")
            if self.agent_id:
                raise ValueError("user actor must not have agent_id")
        elif self.actor_type == "agent":
            if not self.agent_id:
                raise ValueError("agent actor requires agent_id")
            if self.user_id:
                raise ValueError("agent actor must not have user_id")
        else:
            if self.user_id:
                raise ValueError(
                    f"{self.actor_type} actor must not have user_id; "
                    "use actor_type=user for human actors"
                )
            if self.agent_id:
                raise ValueError(
                    f"{self.actor_type} actor must not have agent_id; "
                    "use actor_type=agent for agent actors"
                )
            if self.actor_type == "system":
                # system actors default service_name to "system" so that raw
                # ActorRef(actor_type="system") is unambiguous and resolvable.
                if not self.service_name:
                    self.service_name = "system"
            else:
                # service/job/automation/connector/integration all require an
                # explicit service_name per the actor kinds table.
                if not self.service_name:
                    raise ValueError(
                        f"{self.actor_type} actor requires service_name"
                    )
        return self


class ActorOut(BaseModel):
    """Serialized output for a persisted Actor row."""

    id: str
    space_id: Optional[str]
    actor_type: str
    user_id: Optional[str]
    agent_id: Optional[str]
    service_name: Optional[str]
    display_name: Optional[str]
    status: str
    metadata_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# RunStep execution replay (M3)
# ---------------------------------------------------------------------------

RUN_STEP_TYPES = frozenset({
    "run_created",
    "queued",
    "context_prepared",
    "runtime_selected",
    "adapter_started",
    "adapter_completed",
    "artifact_created",
    "proposal_created",
    "failed",
    "completed",
    "validation_started",
    "validation_completed",
    "cancelled",
})

RUN_STEP_STATUSES = frozenset({
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
})


class RunStepOut(BaseModel):
    """Serialized output for a single RunStep row."""

    id: str
    space_id: str
    run_id: str
    parent_step_id: Optional[str] = None
    actor_id: str
    step_index: int
    step_type: str
    status: str
    title: Optional[str] = None
    runtime_adapter_id: Optional[str] = None
    workspace_id: Optional[str] = None
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    artifact_id: Optional[str] = None
    proposal_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
