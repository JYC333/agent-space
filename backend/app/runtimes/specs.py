"""Canonical RuntimeAdapterSpec catalog.

RuntimeAdapterSpec is the source of truth for adapter detection, invocation,
credentials, model behavior, context rendering, permission bypass, usage, and
frontend catalog display.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

RuntimeKind = Literal["native", "local_cli", "remote_cli", "managed_api", "custom"]
ImplementationStatus = Literal["implemented", "planned", "disabled"]
ContextFileType = Literal["CLAUDE.md", "AGENTS.md", "prompt.md", "custom"]
CredentialMode = Literal["none", "cli_profile", "model_provider_api_key"]
SandboxLevel = Literal["none", "dry_run", "worktree", "one_shot_docker"]
ModelProviderMode = Literal["none", "optional", "required"]
UsageAccuracy = Literal["precise", "estimated", "unknown"]


class ExecutableSpec(BaseModel):
    command: str | None = None
    version_command: list[str] | None = None
    detect_command: list[str] | None = None
    allow_path_override: bool = False

    @field_validator("command")
    @classmethod
    def _command_is_name(cls, value: str | None) -> str | None:
        if value and any(ch in value for ch in ("/", "\\", "\x00")):
            raise ValueError("executable.command must be a command name, not a path")
        return value


class InvocationSpec(BaseModel):
    headless_command_template: list[str] = Field(default_factory=list)
    interactive_command_template: list[str] | None = None
    argument_rendering_strategy: Literal["argv_template", "stdin"] = "argv_template"
    forbid_shell: bool = True
    prompt_variable: str = "{prompt}"

    @model_validator(mode="after")
    def _no_shell(self) -> "InvocationSpec":
        if not self.forbid_shell:
            raise ValueError("Runtime adapter command invocation must forbid shell execution")
        return self


class ContextSpec(BaseModel):
    context_file_type: ContextFileType = "custom"
    context_target_format: str = "generic"
    writes_vendor_context_file: bool = False


class CredentialsSpec(BaseModel):
    credential_mode: CredentialMode = "none"
    credential_runtime_name: str | None = None
    default_target_path: str | None = None
    env_auth_var: str | None = None
    supports_api_key_file: bool = False
    supports_oauth_login_state: bool = False


class SandboxSpec(BaseModel):
    requires_file_access: bool = False
    minimum_sandbox_level: SandboxLevel = "none"
    supports_worktree: bool = False
    supports_one_shot_docker: bool = False
    requires_workspace_for_execution: bool = False


class ModelSpec(BaseModel):
    model_provider_mode: ModelProviderMode = "none"
    supports_model_override: bool = False
    model_arg_template: list[str] | None = None
    model_config_behavior: Literal["uses_model", "not_applicable", "unsupported"] = "not_applicable"

    @model_validator(mode="after")
    def _override_requires_template(self) -> "ModelSpec":
        if self.supports_model_override and not self.model_arg_template:
            raise ValueError("model_arg_template is required when model override is supported")
        return self


class PermissionSpec(BaseModel):
    supports_permission_bypass: bool = False
    permission_bypass_arg_template: list[str] | None = None
    permission_bypass_policy_key: str | None = None


class UsageSpec(BaseModel):
    usage_accuracy: UsageAccuracy = "unknown"
    supports_usage_probe: bool = False
    usage_probe_kind: str | None = None
    usage_parser_type: str = "generic"


class OutputSpec(BaseModel):
    output_parser_type: Literal["plain_text", "generic"] = "generic"
    patch_strategy: str = "git_diff"
    artifact_path_strategy: str = "none"


class LimitsSpec(BaseModel):
    default_timeout_seconds: int = 300
    max_timeout_seconds: int = 3600

    @model_validator(mode="after")
    def _timeout_order(self) -> "LimitsSpec":
        if self.default_timeout_seconds <= 0 or self.max_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("default timeout cannot exceed max timeout")
        return self


class MetadataSpec(BaseModel):
    docs_url: HttpUrl | None = None
    notes: str | None = None


class RuntimeAdapterSpec(BaseModel):
    adapter_type: str
    display_name: str
    runtime_kind: RuntimeKind
    implementation_status: ImplementationStatus
    enabled_by_default: bool = True
    executable: ExecutableSpec = Field(default_factory=ExecutableSpec)
    invocation: InvocationSpec = Field(default_factory=InvocationSpec)
    context: ContextSpec = Field(default_factory=ContextSpec)
    credentials: CredentialsSpec = Field(default_factory=CredentialsSpec)
    sandbox: SandboxSpec = Field(default_factory=SandboxSpec)
    model: ModelSpec = Field(default_factory=ModelSpec)
    permissions: PermissionSpec = Field(default_factory=PermissionSpec)
    usage: UsageSpec = Field(default_factory=UsageSpec)
    output: OutputSpec = Field(default_factory=OutputSpec)
    limits: LimitsSpec = Field(default_factory=LimitsSpec)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)

    @field_validator("adapter_type")
    @classmethod
    def _adapter_type_slug(cls, value: str) -> str:
        if not value or not value.replace("_", "").isalnum() or value != value.lower():
            raise ValueError("adapter_type must be a lowercase slug")
        return value

    @model_validator(mode="after")
    def _planned_disabled(self) -> "RuntimeAdapterSpec":
        if self.implementation_status != "implemented" and self.enabled_by_default:
            raise ValueError("planned/disabled adapters cannot be enabled by default")
        if self.runtime_kind.endswith("cli") and not self.executable.command:
            raise ValueError("CLI adapters require an executable command")
        if self.credentials.credential_mode == "cli_profile" and not self.credentials.credential_runtime_name:
            raise ValueError("cli_profile adapters require credential_runtime_name")
        return self

    def catalog_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class RuntimeAdapterSpecCatalog:
    def __init__(self, specs: list[RuntimeAdapterSpec] | None = None):
        self._specs = specs or _build_builtin_specs()
        seen: set[str] = set()
        for spec in self._specs:
            if spec.adapter_type in seen:
                raise ValueError(f"duplicate runtime adapter spec: {spec.adapter_type}")
            seen.add(spec.adapter_type)
        self._by_type = {spec.adapter_type: spec for spec in self._specs}

    def all(self) -> list[RuntimeAdapterSpec]:
        return list(self._specs)

    def get(self, adapter_type: str) -> RuntimeAdapterSpec:
        try:
            return self._by_type[adapter_type]
        except KeyError as exc:
            raise KeyError(adapter_type) from exc

    def has(self, adapter_type: str) -> bool:
        return adapter_type in self._by_type

    def implemented(self) -> list[RuntimeAdapterSpec]:
        return [s for s in self._specs if s.implementation_status == "implemented"]


def get_runtime_adapter_spec(adapter_type: str) -> RuntimeAdapterSpec:
    return BUILTIN_RUNTIME_ADAPTER_SPECS.get(adapter_type)


def list_runtime_adapter_specs() -> list[RuntimeAdapterSpec]:
    return BUILTIN_RUNTIME_ADAPTER_SPECS.all()


def _build_builtin_specs() -> list[RuntimeAdapterSpec]:
    none_creds = CredentialsSpec(credential_mode="none")
    no_files = SandboxSpec(requires_file_access=False, minimum_sandbox_level="none")
    return [
        RuntimeAdapterSpec(
            adapter_type="echo",
            display_name="Echo",
            runtime_kind="native",
            implementation_status="implemented",
            credentials=none_creds,
            sandbox=no_files,
            output=OutputSpec(output_parser_type="plain_text", patch_strategy="none"),
            metadata=MetadataSpec(notes="Deterministic in-process test adapter."),
        ),
        RuntimeAdapterSpec(
            adapter_type="capability",
            display_name="Capability",
            runtime_kind="native",
            implementation_status="implemented",
            credentials=none_creds,
            sandbox=no_files,
            output=OutputSpec(output_parser_type="generic", patch_strategy="none"),
            metadata=MetadataSpec(notes="Executes enabled local capability manifests."),
        ),
        RuntimeAdapterSpec(
            adapter_type="model_api",
            display_name="Model API",
            runtime_kind="managed_api",
            implementation_status="implemented",
            credentials=CredentialsSpec(credential_mode="model_provider_api_key"),
            sandbox=no_files,
            model=ModelSpec(
                model_provider_mode="required",
                supports_model_override=False,
                model_config_behavior="uses_model",
            ),
            usage=UsageSpec(usage_accuracy="estimated", supports_usage_probe=False),
            output=OutputSpec(output_parser_type="plain_text", patch_strategy="none"),
            metadata=MetadataSpec(
                notes=(
                    "In-process, provider-agnostic LLM call (no tools, no filesystem). Selects a "
                    "configured ModelProvider + model and calls the shared invocation primitive. "
                    "Serves any provider including Anthropic (ADR 0010)."
                ),
            ),
        ),
        RuntimeAdapterSpec(
            adapter_type="claude_code",
            display_name="Claude Code",
            runtime_kind="local_cli",
            implementation_status="implemented",
            executable=ExecutableSpec(
                command="claude",
                version_command=["{executable}", "--version"],
                detect_command=["{executable}", "--version"],
                allow_path_override=True,
            ),
            invocation=InvocationSpec(
                headless_command_template=["{executable}", "--print", "{prompt}"],
                interactive_command_template=["{executable}"],
                argument_rendering_strategy="argv_template",
            ),
            context=ContextSpec(
                context_file_type="CLAUDE.md",
                context_target_format="claude",
                writes_vendor_context_file=True,
            ),
            credentials=CredentialsSpec(
                credential_mode="cli_profile",
                credential_runtime_name="claude_code",
                default_target_path="/home/agent/.claude",
                env_auth_var="ANTHROPIC_API_KEY",
                supports_api_key_file=True,
                supports_oauth_login_state=True,
            ),
            sandbox=SandboxSpec(
                requires_file_access=True,
                minimum_sandbox_level="worktree",
                supports_worktree=True,
                supports_one_shot_docker=False,
                requires_workspace_for_execution=True,
            ),
            model=ModelSpec(
                model_provider_mode="none",
                supports_model_override=True,
                model_arg_template=["--model", "{model}"],
                model_config_behavior="uses_model",
            ),
            permissions=PermissionSpec(
                supports_permission_bypass=True,
                permission_bypass_arg_template=["--dangerously-skip-permissions"],
                permission_bypass_policy_key="allow_permission_bypass",
            ),
            usage=UsageSpec(
                usage_accuracy="unknown",
                supports_usage_probe=False,
                usage_probe_kind="cached_claude_quota",
                usage_parser_type="generic",
            ),
            output=OutputSpec(output_parser_type="generic"),
        ),
        RuntimeAdapterSpec(
            adapter_type="codex_cli",
            display_name="Codex CLI",
            runtime_kind="local_cli",
            implementation_status="implemented",
            executable=ExecutableSpec(
                command="codex",
                version_command=["{executable}", "--version"],
                detect_command=["{executable}", "--version"],
                allow_path_override=True,
            ),
            invocation=InvocationSpec(
                headless_command_template=["{executable}", "{prompt}"],
                argument_rendering_strategy="argv_template",
            ),
            context=ContextSpec(
                context_file_type="AGENTS.md",
                context_target_format="codex_cli",
                writes_vendor_context_file=True,
            ),
            credentials=CredentialsSpec(
                credential_mode="cli_profile",
                credential_runtime_name="codex_cli",
                default_target_path="/home/agent/.codex",
                env_auth_var="OPENAI_API_KEY",
                supports_api_key_file=True,
                supports_oauth_login_state=True,
            ),
            sandbox=SandboxSpec(
                requires_file_access=True,
                minimum_sandbox_level="worktree",
                supports_worktree=True,
                supports_one_shot_docker=False,
                requires_workspace_for_execution=True,
            ),
            model=ModelSpec(model_provider_mode="none", supports_model_override=False),
            usage=UsageSpec(usage_accuracy="unknown", supports_usage_probe=False),
            output=OutputSpec(output_parser_type="generic"),
        ),
        RuntimeAdapterSpec(
            adapter_type="opencode",
            display_name="OpenCode",
            runtime_kind="local_cli",
            implementation_status="planned",
            enabled_by_default=False,
            executable=ExecutableSpec(command="opencode", allow_path_override=True),
            sandbox=SandboxSpec(requires_file_access=True, minimum_sandbox_level="worktree", supports_worktree=True),
            metadata=MetadataSpec(notes="Spec placeholder; invocation is not implemented."),
        ),
        RuntimeAdapterSpec(
            adapter_type="gemini_cli",
            display_name="Gemini CLI",
            runtime_kind="local_cli",
            implementation_status="planned",
            enabled_by_default=False,
            executable=ExecutableSpec(command="gemini", allow_path_override=True),
            sandbox=SandboxSpec(requires_file_access=True, minimum_sandbox_level="worktree", supports_worktree=True),
            metadata=MetadataSpec(notes="Spec placeholder; invocation is not implemented."),
        ),
        RuntimeAdapterSpec(
            adapter_type="custom",
            display_name="Custom Runtime Adapter",
            runtime_kind="custom",
            implementation_status="planned",
            enabled_by_default=False,
            metadata=MetadataSpec(notes="Disabled unless a validated custom spec is provided."),
        ),
    ]


BUILTIN_RUNTIME_ADAPTER_SPECS = RuntimeAdapterSpecCatalog()
