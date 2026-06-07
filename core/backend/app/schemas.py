from datetime import datetime
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

ItemT = TypeVar('ItemT')

RuntimeHealthStatus = Literal["unknown", "ok", "warning", "error", "unimplemented", "disabled"]
RuntimeQuotaStatus = Literal["unknown", "enough", "medium", "low", "exhausted"]


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
    "max_run_time_seconds": 300,
    # adapter_ids this agent may use; matches RuntimeAdapter.adapter_id or adapter_type
    # model_api (ADR 0010) is the in-process, provider-agnostic, no-tools LLM adapter:
    # it selects any configured ModelProvider + model (Anthropic included) and passes the
    # key via litellm parameter, never env. claude_code stays the CLI path for tool-using /
    # filesystem Claude work.
    "allowed_adapter_types": [
        "echo",
        "capability",
        "model_api",
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
    owner_space_id: str = Field(validation_alias="space_id")
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
    tool_policy_json: dict = Field(default_factory=dict)
    output_policy_json: dict = Field(default_factory=dict)
    schedule_config_json: dict = Field(default_factory=dict)
    output_schema_json: dict = Field(default_factory=dict)
    source_proposal_id: Optional[str] = None
    source_activity_id: Optional[str] = None
    created_at: datetime
    published_at: Optional[datetime]
    archived_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AgentModelSummary(BaseModel):
    provider_id: Optional[str] = None
    provider_name: Optional[str] = None
    provider_type: Optional[str] = None
    model: Optional[str] = None


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
    tool_policy_json: dict = Field(default_factory=dict)
    output_policy_json: dict = Field(default_factory=dict)
    schedule_config_json: dict = Field(default_factory=dict)
    output_schema_json: dict = Field(default_factory=dict)


class AgentConfigProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version_id: str
    model_provider_id: Optional[str] = None
    model_name: Optional[str] = None
    runtime_adapter_id: Optional[str] = None
    system_prompt: Optional[str] = None
    model_config_json: Optional[dict] = None
    runtime_config_json: Optional[dict] = None
    context_policy_json: Optional[dict] = None
    memory_policy_json: Optional[dict] = None
    capabilities_json: Optional[list[str]] = None
    tool_permissions_json: Optional[dict] = None
    runtime_policy_json: Optional[dict] = None


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    created_by_user_id: Optional[str] = None
    visibility: str = "private"
    role_instruction: Optional[str] = None
    space_id: Optional[str] = None
    default_model_provider_id: Optional[str] = None
    default_model: Optional[str] = None
    # The agent's persistent system prompt (its role/identity), stored on the v1
    # AgentVersion and sent as the system message at run time.
    system_prompt: Optional[str] = None
    # Runtime adapter the agent runs on (e.g. "model_api", "claude_code"). Merged into
    # the v1 runtime_policy_json (default_adapter_type + allowed_adapter_types) without
    # dropping the other policy fields. When omitted, the default policy is used.
    adapter_type: Optional[str] = None
    # Optional v1 execution snapshot (stored on initial AgentVersion).
    model_config_json: Optional[dict] = None
    memory_policy_json: Optional[dict] = None
    capabilities_json: Optional[list[str]] = None
    tool_permissions_json: Optional[dict] = None
    runtime_policy_json: Optional[dict] = None


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[str] = None
    role_instruction: Optional[str] = None
    status: Optional[str] = None
    default_model_provider_id: Optional[str] = None
    default_model: Optional[str] = None
    model_provider_id: Optional[str] = None
    model_name: Optional[str] = None
    runtime_adapter_id: Optional[str] = None
    system_prompt: Optional[str] = None
    # Execution config fields require an agent_config_update proposal when provided.
    model_config_json: Optional[dict] = None
    runtime_config_json: Optional[dict] = None
    context_policy_json: Optional[dict] = None
    memory_policy_json: Optional[dict] = None
    capabilities_json: Optional[list[str]] = None
    tool_permissions_json: Optional[dict] = None
    tool_policy_json: Optional[dict] = None
    runtime_policy_json: Optional[dict] = None


class AgentConfigUpdate(BaseModel):
    """Owner edit of an Agent's behavior from the config UI.

    Applying this appends a NEW immutable AgentVersion built from the current one,
    then repoints Agent.current_version_id. The previous AgentVersion is never
    mutated. Only the fields below are editable; hard-safety snapshots
    (tool_policy_json, tool_permissions_json, capabilities_json, runtime_policy_json,
    runtime_config_json, runtime_adapter_id) are copied verbatim and can never be
    loosened here. Within memory/output policy the write-access and proposal-only
    guarantees are re-stamped from the source version so a frontend override cannot
    grant direct memory write or disable proposal-only outputs.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity (applied directly to the Agent row).
    name: Optional[str] = None
    description: Optional[str] = None
    # Versioned, safety-bounded execution config.
    system_prompt: Optional[str] = None
    model_provider_id: Optional[str] = None
    model_name: Optional[str] = None
    model_config_json: Optional[dict] = None
    context_policy_json: Optional[dict] = None
    memory_policy_json: Optional[dict] = None
    output_policy_json: Optional[dict] = None
    schedule_config_json: Optional[dict] = None
    output_schema_json: Optional[dict] = None


class AgentOut(BaseModel):
    id: str
    space_id: str
    # None for system-owned agents (e.g. the default Assistant); no default-user masking.
    created_by_user_id: Optional[str] = None
    name: str
    description: Optional[str]
    visibility: str
    role_instruction: Optional[str]
    status: str
    # "standard" | "system_assistant" — the latter is the space's system-managed
    # default Assistant (Chat identity), not an ordinary user agent.
    agent_kind: str = "standard"
    current_version_id: Optional[str]
    # Provenance only — never used to assemble runtime config.
    source_template_id: Optional[str] = None
    source_template_version_id: Optional[str] = None
    model: Optional[AgentModelSummary] = None
    system_prompt: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Agent templates — reusable factories (NOT runtime objects)
# ---------------------------------------------------------------------------

AgentTemplateScope = Literal["system", "space", "user"]
AgentTemplateVisibility = Literal["private", "space_shared", "system_public", "system_internal"]
AgentTemplateStatus = Literal["draft", "published", "archived"]


class AgentTemplateVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Optional[str] = None
    system_prompt: Optional[str] = None
    model_config_json: dict = Field(default_factory=dict)
    context_policy_json: dict = Field(default_factory=dict)
    memory_policy_json: dict = Field(default_factory=dict)
    tool_policy_json: dict = Field(default_factory=dict)
    runtime_policy_json: dict = Field(default_factory=dict)
    output_policy_json: dict = Field(default_factory=dict)
    schedule_defaults_json: dict = Field(default_factory=dict)
    output_schema_json: dict = Field(default_factory=dict)


class AgentTemplateVersionOut(BaseModel):
    id: str
    template_id: str
    version: str
    system_prompt: Optional[str]
    model_config_json: dict
    context_policy_json: dict
    memory_policy_json: dict
    tool_policy_json: dict
    runtime_policy_json: dict
    output_policy_json: dict
    schedule_defaults_json: dict
    output_schema_json: dict
    created_by_user_id: Optional[str]
    created_at: datetime
    published_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AgentTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    # Only space/user templates may be created via the API; system templates are seeded.
    scope: Literal["space", "user"] = "user"
    space_id: Optional[str] = None
    visibility: AgentTemplateVisibility = "private"
    # Optional initial draft version created alongside the template.
    initial_version: Optional[AgentTemplateVersionCreate] = None


class AgentTemplateOut(BaseModel):
    id: str
    key: str
    name: str
    description: Optional[str]
    category: Optional[str]
    scope: AgentTemplateScope
    space_id: Optional[str]
    owner_user_id: Optional[str]
    visibility: AgentTemplateVisibility
    status: AgentTemplateStatus
    current_version_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreateAgentFromTemplate(BaseModel):
    """Allowed user overrides when instantiating an Agent from a template.

    Overrides apply ONLY to the copied AgentVersion (never to the template), and
    cannot bypass hard policy defaults (tool/memory/context/runtime/output policy).
    """

    model_config = ConfigDict(extra="forbid")

    # Optional: select a specific template version; defaults to template.current_version_id.
    template_version_id: Optional[str] = None
    space_id: Optional[str] = None
    # Allowed initial overrides (applied to the copied AgentVersion only). Memory/output
    # policy overrides are safety re-stamped server-side; tool/runtime policy is never
    # overridable here.
    name: Optional[str] = None
    description: Optional[str] = None
    model_config_json: Optional[dict] = None
    schedule_config_json: Optional[dict] = None
    system_prompt: Optional[str] = None
    context_policy_json: Optional[dict] = None
    memory_policy_json: Optional[dict] = None
    output_policy_json: Optional[dict] = None
    output_schema_json: Optional[dict] = None


# ---------------------------------------------------------------------------
# Space Assistant preferences — a soft UI/context layer, never hard policy.
# ---------------------------------------------------------------------------

ResponseStyle = Literal["neutral", "friendly", "direct", "formal"]
Verbosity = Literal["concise", "balanced", "detailed"]
ProposalStyle = Literal["proactive", "balanced", "conservative"]


class SpaceAssistantSettingsOut(BaseModel):
    id: str
    space_id: str
    assistant_agent_id: Optional[str]
    response_style: Optional[ResponseStyle]
    verbosity: Optional[Verbosity]
    default_context_toggles_json: dict
    default_project_id: Optional[str]
    proposal_style: Optional[ProposalStyle]
    model_preferences_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SpaceAssistantSettingsUpdate(BaseModel):
    """Soft preferences only — cannot edit the core prompt or any hard policy."""

    model_config = ConfigDict(extra="forbid")

    response_style: Optional[ResponseStyle] = None
    verbosity: Optional[Verbosity] = None
    default_context_toggles_json: Optional[dict] = None
    default_project_id: Optional[str] = None
    proposal_style: Optional[ProposalStyle] = None
    model_preferences_json: Optional[dict] = None


class RunRequest(BaseModel):
    """Run creation request body for POST /agents/{agent_id}/run."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    workspace_id: Optional[str] = None
    workspace_path: Optional[str] = None
    runtime_adapter_id: Optional[str] = None
    adapter_type: str = "echo"
    # cli_default | cli_model_override | agent_space_provider
    model_selection_mode: str = "cli_default"
    model_override_json: Optional[dict] = None
    risk_level: str = "medium"  # low | medium | high | critical
    # Task routing signals — used by TaskRouter to choose the right adapter.
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
    # episodic | semantic — drives episodic-context filtering and symbol-match retrieval.
    memory_layer: Optional[str] = None
    memory_kind: Optional[str] = None

    @model_validator(mode="after")
    def validate_memory_fields(self) -> "MemoryCreate":
        from app.memory.read_auth import SENSITIVITY_LEVELS, VISIBILITY_VALUES

        if self.memory_layer is not None:
            ml = self.memory_layer.lower()
            if ml not in ("episodic", "semantic"):
                raise ValueError(f"invalid memory_layer: {self.memory_layer!r}")
            object.__setattr__(self, "memory_layer", ml)

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
    project_id: Optional[str] = None

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
    visibility: str = "space_shared"
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
    # Safe PersonalMemoryGrant egress metadata. These fields contain IDs/status
    # only; raw memory, generated summaries, and proposal payload content are
    # intentionally not exposed here.
    grant_id: Optional[str] = None
    required_approver_user_id: Optional[str] = None
    requires_approval_type: Optional[str] = None
    egress_approval_status: Optional[str] = None
    egress_approval_id: Optional[str] = None
    project_id: Optional[str] = None

    model_config = {"from_attributes": True}


class ProposalAcceptOut(BaseModel):
    """Body for ``POST /api/v1/proposals/{id}/accept`` — result varies by ``proposal_type``."""

    proposal: ProposalOut
    # memory_entry  — memory_create, memory_update, memory_archive accepted
    # code_patch_apply — code_patch accepted
    # policy_version   — policy_change accepted
    # egress_review    — metadata-only grant egress review accepted
    result_type: Literal[
        "memory_entry",
        "code_patch_apply",
        "policy_version",
        "egress_review",
        "follow_up_task",
        "agent_version",
        "capability_overlay",
        "knowledge_item",
        "knowledge_relation",
    ]
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
    consolidation_status: Optional[str] = None
    visibility: str = "space_shared"
    project_id: Optional[str] = None

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
    visibility: str = "space_shared"
    owner_user_id: Optional[str] = None
    content: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    project_id: Optional[str] = None

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
    evidence_items: list[dict] = []
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

    # Ephemeral personal summary from a valid PersonalMemoryGrant.
    # MUST NOT be persisted to compiled_prefix_text, compiled_tail_text,
    # source_refs_json, or any shared artifact.  Present only in the in-memory
    # ContextPackage returned to the caller; never written to the DB snapshot.
    personal_context_block: str = ""


class ContextRequest(BaseModel):
    """Input to ChatContextBuilder for the Personal Assistant / chat path.

    agent_version_id is used to load AgentVersion.context_policy_json, which defines
    the allowed context boundary for this request.  AgentVersion is never mutated for
    per-run context selection — all selection decisions live in this request and the
    resulting ContextBundle.
    """

    space_id: str
    user_id: str
    agent_version_id: Optional[str] = None
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    user_message: Optional[str] = None
    manual_context: list[dict] = []
    max_tokens: int = 4000
    max_items: int = 20


class ContextBundleItem(BaseModel):
    """A single context item selected for a model call."""

    item_type: str
    item_id: Optional[str] = None
    title: Optional[str] = None
    excerpt: Optional[str] = None
    score: Optional[float] = None
    reason: Optional[str] = None
    token_count: Optional[int] = None
    metadata: dict = {}


class ContextBundle(BaseModel):
    """Assembled context package for the Personal Assistant / chat model call.

    Built by ChatContextBuilder.build() from a ContextRequest.  snapshot_id is
    populated after ChatContextBuilder.persist_snapshot() runs; it references the
    ContextSnapshot row that makes this model call auditable.
    """

    items: list[ContextBundleItem] = []
    token_count: int = 0
    truncated: bool = False
    snapshot_id: Optional[str] = None
    retrieval_trace: dict = {}


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

class CapabilityOut(BaseModel):
    id: str
    name: str
    version: str
    description: Optional[str]
    entrypoint: Optional[Any]
    source: str = "builtin"
    workspace_id: Optional[str] = None
    root_path: Optional[str] = None
    manifest_path: Optional[str] = None
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
    visibility: str
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

    model_config = ConfigDict(extra="forbid")

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
    visibility: str = "space_shared"
    created_at: datetime

    model_config = {"from_attributes": True}


class ProposalSummaryOut(BaseModel):
    id: str
    space_id: str
    proposal_type: str
    status: str
    title: str
    visibility: str = "space_shared"
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


class TaskEvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluator_type: str
    score: Optional[float] = Field(default=None, ge=0, le=1)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    summary: Optional[str] = None
    checklist_json: Optional[dict] = None
    known_issues_json: Optional[list] = None
    evidence_artifact_ids: Optional[list] = None
    recommendation: Optional[str] = None
    run_id: Optional[str] = None


class TaskEvaluationOut(BaseModel):
    id: str
    space_id: str
    task_id: str
    run_id: Optional[str] = None
    run_evaluation_id: Optional[str] = None
    evaluator_type: str
    evaluator_user_id: Optional[str] = None
    evaluator_agent_id: Optional[str] = None
    score: Optional[float] = None
    confidence: Optional[float] = None
    summary: Optional[str] = None
    checklist_json: Optional[dict] = None
    known_issues_json: Optional[list] = None
    evidence_artifact_ids: Optional[list] = None
    recommendation: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Run Creation API
# ---------------------------------------------------------------------------

class RunCreate(BaseModel):
    """Input for POST /api/v1/agents/{id}/runs."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(default="live")
    run_type: str = Field(default="agent")
    trigger_origin: str = Field(default="manual")
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    prompt: Optional[str] = None
    instruction: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    # Run lineage: set parent_run_id for follow-up, retry, or manual continuation runs.
    parent_run_id: Optional[str] = None
    adapter_type: Optional[str] = None
    capability_id: Optional[str] = None
    # Execution plane hints — used by the service to resolve and snapshot plane metadata.
    # source is NOT accepted from the client; it is always set to "managed" by the service.
    execution_plane_id: Optional[str] = None
    runtime_adapter_id: Optional[str] = None
    model_provider_id: Optional[str] = None
    model: Optional[str] = None


class RunOut(BaseModel):
    """Canonical Run output for the Run API."""
    id: str
    space_id: str
    agent_id: str
    agent_version_id: str
    context_snapshot_id: Optional[str]
    workspace_id: Optional[str]
    session_id: Optional[str]
    parent_run_id: Optional[str]
    instructed_by_user_id: Optional[str] = None
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
    capability_id: Optional[str] = None
    model_provider_id: Optional[str] = None
    resolved_model: Optional["RunResolvedModelOut"] = None
    required_sandbox_level: str = "none"
    visibility: str = "space_shared"
    project_id: Optional[str] = None

    model_config = {"from_attributes": True}


class RunResolvedModelOut(BaseModel):
    """Safe public summary of model config resolved for a Run."""

    provider_id: Optional[str] = None
    provider_name: Optional[str] = None
    provider_type: Optional[str] = None
    model: Optional[str] = None
    source: Literal[
        "request", "agent_default", "runtime_default", "space_default", "none"
    ] = "none"
    used_by_adapter: bool = False
    adapter_model_support: Literal[
        "uses_model", "not_applicable", "unsupported", "unknown"
    ] = "unknown"
    disclosure_note: Optional[str] = None


class RunTraceAgentVersionOut(BaseModel):
    """Safe AgentVersion snapshot for run replay.

    The trace endpoint exposes immutable execution configuration without
    embedding raw system prompts. Prompt content can be inspected through
    proposal/version review flows; trace returns only presence/hash metadata.
    """

    id: str
    agent_id: str
    space_id: str
    version_label: str
    model_provider_id: Optional[str] = None
    model_name: Optional[str] = None
    runtime_adapter_id: Optional[str] = None
    system_prompt_present: bool = False
    system_prompt_sha256: Optional[str] = None
    model_config_json: dict = Field(default_factory=dict)
    runtime_config_json: dict = Field(default_factory=dict)
    context_policy_json: dict = Field(default_factory=dict)
    memory_policy_json: dict = Field(default_factory=dict)
    capabilities_json: list = Field(default_factory=list)
    tool_permissions_json: dict = Field(default_factory=dict)
    runtime_policy_json: dict = Field(default_factory=dict)
    source_proposal_id: Optional[str] = None
    source_activity_id: Optional[str] = None
    created_at: datetime
    published_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None


class RunTraceRuntimeAdapterOut(BaseModel):
    id: str
    space_id: str
    name: str
    adapter_type: str
    enabled: bool
    provider_id: Optional[str] = None
    credential_configured: bool = False
    health_status: RuntimeHealthStatus = "unknown"
    execution_plane_id: Optional[str] = None


class RunTraceModelProviderOut(BaseModel):
    id: str
    space_id: str
    name: str
    provider_type: str
    default_model: Optional[str] = None
    enabled: bool
    has_credential: bool = False


class RunTraceContextSnapshotOut(BaseModel):
    """ContextSnapshot replay metadata without raw rendered context text."""

    id: str
    space_id: str
    source_refs_json: list = Field(default_factory=list)
    token_estimate: Optional[int] = None
    relevant_period_start: Optional[datetime] = None
    relevant_period_end: Optional[datetime] = None
    prefix_hash: Optional[str] = None
    tail_hash: Optional[str] = None
    compiler_version: Optional[str] = None
    retrieval_trace_json: Optional[list] = None
    token_budget_json: Optional[dict] = None
    policy_bundle_version: Optional[str] = None
    memory_digest_version: Optional[str] = None
    workspace_digest_version: Optional[str] = None
    target_runtime_adapter_id: Optional[str] = None
    execution_plane_id: Optional[str] = None
    included_memory_refs_json: Optional[list] = None
    included_evidence_refs_json: Optional[list] = None
    included_file_refs_json: Optional[list] = None
    included_doc_refs_json: Optional[list] = None
    redactions_json: Optional[dict] = None
    data_exposure_level: Optional[str] = None
    rendered_context_uri: Optional[str] = None
    has_compiled_prefix_text: bool = False
    has_compiled_tail_text: bool = False
    has_rendered_context_text: bool = False
    created_at: datetime


class RunTraceLineageOut(BaseModel):
    id: str
    space_id: str
    agent_id: str
    agent_version_id: str
    parent_run_id: Optional[str] = None
    status: str
    run_type: str
    trigger_origin: str
    mode: str
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskRunListItem(BaseModel):
    """TaskRun association with full Run payload for task-scoped listing."""

    link: TaskRunOut
    run: RunOut


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
# Runtime Adapters
# ---------------------------------------------------------------------------

class RuntimeAdapterCreate(BaseModel):
    adapter_type: str
    name: str
    enabled: bool = True
    executable_path: Optional[str] = None
    default_mode: str = "headless"
    health_status: RuntimeHealthStatus = "unknown"
    quota_status: RuntimeQuotaStatus = "unknown"
    credential_id: Optional[str] = None
    credential_profile_id: Optional[str] = None
    provider_id: Optional[str] = None
    config_json: dict = Field(default_factory=dict)
    notes: Optional[str] = None


class RuntimeAdapterUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    executable_path: Optional[str] = None
    default_mode: Optional[str] = None
    health_status: Optional[RuntimeHealthStatus] = None
    quota_status: Optional[RuntimeQuotaStatus] = None
    credential_id: Optional[str] = None
    credential_profile_id: Optional[str] = None
    provider_id: Optional[str] = None
    config_json: Optional[dict] = None
    notes: Optional[str] = None
    permission_bypass: Optional[bool] = None


class RuntimeAdapterOut(BaseModel):
    id: str
    space_id: str
    adapter_type: str
    name: str
    enabled: bool
    provider_id: Optional[str] = None
    credential_id: Optional[str] = None
    credential_profile_id: Optional[str] = None
    config_json: dict
    executable_path: Optional[str]
    default_mode: str
    health_status: RuntimeHealthStatus
    quota_status: RuntimeQuotaStatus
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RuntimeAdapterStatusOut(BaseModel):
    runtime_adapter_id: Optional[str] = None
    adapter_type: str
    implementation_status: str
    configured_count: int = 0
    configured: bool = False
    enabled: bool = False
    installed: bool = False
    executable_path: Optional[str] = None
    version: Optional[str] = None
    credential_required: bool = False
    credential_profile_id: Optional[str] = None
    credential_ready: bool = False
    model_provider_required: bool = False
    model_provider_ready: bool = False
    supports_headless: bool = False
    supports_interactive: bool = False
    supports_model_override: bool = False
    supports_usage_probe: bool = False
    usage_accuracy: str = "unknown"
    minimum_sandbox_level: str = "none"
    last_run_status: Optional[str] = None
    last_error_code: Optional[str] = None
    health_status: RuntimeHealthStatus = "unknown"
    quota_status: RuntimeQuotaStatus = "unknown"
    warnings: list[str] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# RunEvent evidence spine
# ---------------------------------------------------------------------------


class RunEventOut(BaseModel):
    """Serialized output for a single RunEvent row (append-only evidence record)."""

    id: str
    space_id: str
    run_id: str
    step_id: Optional[str] = None
    actor_id: Optional[str] = None
    event_index: int
    event_type: str
    status: str
    summary: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    runtime_adapter_id: Optional[str] = None
    workspace_id: Optional[str] = None
    artifact_id: Optional[str] = None
    proposal_id: Optional[str] = None
    data_exposure_level: Optional[str] = None
    trust_level: Optional[str] = None
    metadata_json: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RunTraceOut(BaseModel):
    run: RunOut
    agent: Optional[AgentOut] = None
    agent_version: Optional[RunTraceAgentVersionOut] = None
    runtime_adapter: Optional[RunTraceRuntimeAdapterOut] = None
    model_provider: Optional[RunTraceModelProviderOut] = None
    context_snapshot: Optional[RunTraceContextSnapshotOut] = None
    steps: list[RunStepOut] = Field(default_factory=list)
    events: list[RunEventOut] = Field(default_factory=list)
    artifacts: list[ArtifactSummaryOut] = Field(default_factory=list)
    proposals: list[ProposalSummaryOut] = Field(default_factory=list)
    parent: Optional[RunTraceLineageOut] = None
    children: list[RunTraceLineageOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# RunEvaluation
# ---------------------------------------------------------------------------


class RunEvaluationOut(BaseModel):
    """Serialized output for a RunEvaluation row (append-only)."""

    id: str
    space_id: str
    run_id: str
    evaluator_type: str
    evaluator_version: str
    outcome_status: str
    failure_layer: Optional[str] = None
    failure_reason_code: Optional[str] = None
    trajectory_status: str
    evidence_json: Optional[dict] = None
    rule_trace_json: Optional[list] = None
    notes: Optional[str] = None
    evaluated_at: datetime

    model_config = {"from_attributes": True}


class RunFinalizationOut(BaseModel):
    """Serialized output for a RunFinalization row."""

    id: str
    space_id: str
    run_id: str
    finalizer_version: str
    status: str
    run_evaluation_id: Optional[str] = None
    task_evaluation_id: Optional[str] = None
    outcome_status: Optional[str] = None
    failure_layer: Optional[str] = None
    failure_reason_code: Optional[str] = None
    trajectory_status: Optional[str] = None
    skipped_reasons_json: Optional[list] = None
    error_json: Optional[dict] = None
    metadata_json: Optional[dict] = None
    finalized_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    owner_user_id: Optional[str] = None
    current_focus: Optional[str] = None
    settings_json: Optional[dict] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    current_focus: Optional[str] = None
    settings_json: Optional[dict] = None
    status: Optional[str] = None


class ProjectOut(BaseModel):
    id: str
    space_id: str
    owner_user_id: Optional[str]
    name: str
    description: Optional[str]
    status: str
    current_focus: Optional[str]
    settings_json: Optional[dict]
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ProjectWorkspaceLinkCreate(BaseModel):
    workspace_id: str
    role: str = "reference"


class ProjectWorkspaceLinkOut(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    role: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectSummaryOut(BaseModel):
    project_id: str
    activity_count: int
    artifact_count: int
    pending_proposal_count: int
    workspace_count: int
    active_run_count: int
    memory_entry_count: int
