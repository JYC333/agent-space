from datetime import datetime
from typing import Generic, Optional, TypeVar
from pydantic import BaseModel, Field

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
    # adapter_ids this agent may use; matches CLIAdapterConfig.adapter_id or adapter_type
    "allowed_adapter_types": ["echo", "claude_code", "codex_cli", "opencode", "gemini_cli"],
}


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
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
    kind: str
    repo_url: Optional[str]
    root_path: Optional[str]
    default_branch: Optional[str]
    visibility: str
    status: str
    metadata_json: Optional[dict]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    created_by_user_id: Optional[str] = None  # defaults to the requesting user if omitted
    visibility: str = "private"
    role_instruction: Optional[str] = None
    model_config_json: dict = Field(default_factory=lambda: dict(DEFAULT_MODEL_CONFIG))
    memory_policy_json: dict = Field(default_factory=lambda: dict(DEFAULT_MEMORY_POLICY))
    capabilities_json: list[str] = Field(default_factory=list)
    tool_policy_json: list[str] = Field(default_factory=list)
    runtime_policy_json: dict = Field(default_factory=lambda: dict(DEFAULT_RUNTIME_POLICY))
    space_id: Optional[str] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[str] = None
    role_instruction: Optional[str] = None
    model_config_json: Optional[dict] = None
    memory_policy_json: Optional[dict] = None
    capabilities_json: Optional[list[str]] = None
    tool_policy_json: Optional[list[str]] = None
    runtime_policy_json: Optional[dict] = None
    status: Optional[str] = None


class AgentOut(BaseModel):
    id: str
    space_id: str
    created_by_user_id: str
    name: str
    description: Optional[str]
    visibility: str
    role_instruction: Optional[str]
    model_config_json: dict
    memory_policy_json: dict
    capabilities_json: list
    tool_policy_json: list
    runtime_policy_json: dict
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentRunRequest(BaseModel):
    """Used by both user→agent and agent→agent calls."""
    prompt: str
    workspace_id: Optional[str] = None
    workspace_path: Optional[str] = None
    # Prefer cli_adapter_config_id. adapter_type is the legacy fallback.
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
    task_type: Optional[str] = None  # e.g. summarize | classify | code_modify | refactor
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
    # private | space_shared | workspace_shared | restricted | public_template
    visibility: str = "private"
    confidence: float = 1.0
    importance: float = 0.5
    tags: Optional[list[str]] = None
    source_id: Optional[str] = None
    space_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    workspace_id: Optional[str] = None


class MemoryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    visibility: Optional[str] = None
    confidence: Optional[float] = None
    importance: Optional[float] = None
    tags: Optional[list[str]] = None


class MemoryOut(BaseModel):
    id: str
    space_id: str
    owner_user_id: str
    workspace_id: Optional[str]
    scope: str
    namespace: str
    type: str
    title: str
    content: str
    status: str
    visibility: str
    confidence: float
    importance: float
    source_id: Optional[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    version: int
    tags: Optional[list]

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
    target_scope: str
    target_namespace: str
    memory_type: str
    proposed_title: str
    proposed_content: str
    rationale: str
    status: str
    created_at: datetime
    decided_at: Optional[datetime]
    resulting_memory_id: Optional[str]

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
    user_memory: list[MemoryOut] = []
    workspace_memory: list[MemoryOut] = []
    capability_memory: list[MemoryOut] = []
    agent_memory: list[MemoryOut] = []
    system_policy: list[MemoryOut] = []
    recent_session_summary: list[dict] = []
    relevant_episodes: list[MemoryOut] = []
    # Resolved context attachments (file, git_diff, memory_entry, etc.)
    attachments: list[dict] = []


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
# Tasks
# ---------------------------------------------------------------------------

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    capability_id: Optional[str] = None
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    space_id: Optional[str] = None
    user_id: Optional[str] = None


class TaskOut(BaseModel):
    id: str
    space_id: str
    user_id: str
    workspace_id: Optional[str]
    session_id: Optional[str]
    title: str
    description: Optional[str]
    capability_id: Optional[str]
    status: str
    result: Optional[str]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentRunOut(BaseModel):
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
