export type RuntimeAdapterType =
  | "capability"
  | "model_api"
  | "ts_agent_host"
  | "claude_code"
  | "codex_cli"
  | "opencode"
  | "gemini_cli"
  | "custom";

export type RuntimeKind = "native" | "local_cli" | "managed_api" | "custom";
export type ImplementationStatus = "implemented" | "planned" | "disabled";
export type ContextFileType = "CLAUDE.md" | "AGENTS.md" | "prompt.md" | "custom";
export type CredentialMode = "none" | "cli_profile" | "model_provider_api_key";
export type CredentialReleaseChannel = "python_runtime" | "control_plane_runtime_host";

export interface RuntimeAdapterSpec {
  adapter_type: RuntimeAdapterType;
  display_name: string;
  runtime_kind: RuntimeKind;
  implementation_status: ImplementationStatus;
  enabled_by_default: boolean;
  executable?: {
    command?: string;
    allow_path_override?: boolean;
  };
  invocation?: {
    headless_command_template: string[];
    interactive_command_template?: string[];
    argument_rendering_strategy: "argv_template" | "stdin";
  };
  context: {
    context_file_type: ContextFileType;
    context_target_format: string;
    writes_vendor_context_file: boolean;
  };
  credentials: {
    credential_mode: CredentialMode;
    credential_release_channel?: CredentialReleaseChannel;
    credential_runtime_name?: string;
    default_target_path?: string;
    supports_oauth_login_state?: boolean;
  };
  sandbox: {
    requires_file_access: boolean;
    minimum_sandbox_level: "none" | "dry_run" | "ephemeral" | "worktree" | "one_shot_docker";
    supports_worktree: boolean;
    supports_one_shot_docker: boolean;
    requires_workspace_for_execution: boolean;
  };
  model: {
    model_provider_mode: "none" | "optional" | "required";
    supports_model_override: boolean;
    model_arg_template?: string[];
    model_config_behavior: "uses_model" | "not_applicable" | "unsupported";
  };
  permissions: {
    supports_permission_bypass: boolean;
    permission_bypass_arg_template?: string[];
    permission_bypass_policy_key?: string;
  };
  usage: {
    usage_accuracy: "precise" | "estimated" | "unknown";
    supports_usage_probe: boolean;
    usage_probe_kind?: string;
    usage_parser_type: string;
  };
  output: {
    output_parser_type: "plain_text" | "generic";
    patch_strategy: "none" | "git_diff";
    artifact_path_strategy: "none";
  };
  limits: {
    default_timeout_seconds: number;
    max_timeout_seconds: number;
  };
}

export interface LocalCliRuntimeAdapterSpec extends RuntimeAdapterSpec {
  runtime_kind: "local_cli";
  executable: {
    command: string;
    allow_path_override?: boolean;
  };
  invocation: {
    headless_command_template: string[];
    interactive_command_template?: string[];
    argument_rendering_strategy: "argv_template" | "stdin";
  };
  credentials: RuntimeAdapterSpec["credentials"] & {
    credential_mode: "cli_profile";
    credential_runtime_name: string;
  };
}

const noFiles: RuntimeAdapterSpec["sandbox"] = {
  requires_file_access: false,
  minimum_sandbox_level: "none",
  supports_worktree: false,
  supports_one_shot_docker: false,
  requires_workspace_for_execution: false,
};

const worktreeCli: RuntimeAdapterSpec["sandbox"] = {
  requires_file_access: true,
  minimum_sandbox_level: "worktree",
  supports_worktree: true,
  supports_one_shot_docker: false,
  requires_workspace_for_execution: false,
};

export const BUILTIN_RUNTIME_ADAPTER_SPECS: Readonly<Record<RuntimeAdapterType, RuntimeAdapterSpec>> = {
  capability: {
    adapter_type: "capability",
    display_name: "Capability",
    runtime_kind: "native",
    implementation_status: "implemented",
    enabled_by_default: true,
    context: {
      context_file_type: "custom",
      context_target_format: "generic",
      writes_vendor_context_file: false,
    },
    credentials: { credential_mode: "none" },
    sandbox: noFiles,
    model: {
      model_provider_mode: "none",
      supports_model_override: false,
      model_config_behavior: "not_applicable",
    },
    permissions: { supports_permission_bypass: false },
    usage: {
      usage_accuracy: "unknown",
      supports_usage_probe: false,
      usage_parser_type: "generic",
    },
    output: {
      output_parser_type: "generic",
      patch_strategy: "none",
      artifact_path_strategy: "none",
    },
    limits: { default_timeout_seconds: 300, max_timeout_seconds: 3600 },
  },
  model_api: {
    adapter_type: "model_api",
    display_name: "Model API",
    runtime_kind: "managed_api",
    implementation_status: "implemented",
    enabled_by_default: true,
    context: {
      context_file_type: "custom",
      context_target_format: "generic",
      writes_vendor_context_file: false,
    },
    credentials: { credential_mode: "model_provider_api_key" },
    sandbox: noFiles,
    model: {
      model_provider_mode: "required",
      supports_model_override: false,
      model_config_behavior: "uses_model",
    },
    permissions: { supports_permission_bypass: false },
    usage: {
      usage_accuracy: "estimated",
      supports_usage_probe: false,
      usage_parser_type: "generic",
    },
    output: {
      output_parser_type: "plain_text",
      patch_strategy: "none",
      artifact_path_strategy: "none",
    },
    limits: { default_timeout_seconds: 300, max_timeout_seconds: 3600 },
  },
  ts_agent_host: {
    adapter_type: "ts_agent_host",
    display_name: "TS Agent Host",
    runtime_kind: "managed_api",
    implementation_status: "implemented",
    enabled_by_default: false,
    context: {
      context_file_type: "custom",
      context_target_format: "host_request",
      writes_vendor_context_file: false,
    },
    credentials: {
      credential_mode: "model_provider_api_key",
      credential_release_channel: "control_plane_runtime_host",
    },
    sandbox: noFiles,
    model: {
      model_provider_mode: "required",
      supports_model_override: false,
      model_config_behavior: "uses_model",
    },
    permissions: { supports_permission_bypass: false },
    usage: {
      usage_accuracy: "estimated",
      supports_usage_probe: false,
      usage_parser_type: "generic",
    },
    output: {
      output_parser_type: "plain_text",
      patch_strategy: "none",
      artifact_path_strategy: "none",
    },
    limits: { default_timeout_seconds: 300, max_timeout_seconds: 3600 },
  },
  claude_code: {
    adapter_type: "claude_code",
    display_name: "Claude Code",
    runtime_kind: "local_cli",
    implementation_status: "implemented",
    enabled_by_default: true,
    executable: { command: "claude", allow_path_override: true },
    invocation: {
      headless_command_template: ["{executable}", "--print", "{prompt}"],
      interactive_command_template: ["{executable}"],
      argument_rendering_strategy: "argv_template",
    },
    context: {
      context_file_type: "CLAUDE.md",
      context_target_format: "claude",
      writes_vendor_context_file: true,
    },
    credentials: {
      credential_mode: "cli_profile",
      credential_runtime_name: "claude_code",
      default_target_path: "/home/agent/.claude",
      supports_oauth_login_state: true,
    },
    sandbox: worktreeCli,
    model: {
      model_provider_mode: "none",
      supports_model_override: true,
      model_arg_template: ["--model", "{model}"],
      model_config_behavior: "uses_model",
    },
    permissions: {
      supports_permission_bypass: true,
      permission_bypass_arg_template: ["--dangerously-skip-permissions"],
      permission_bypass_policy_key: "allow_permission_bypass",
    },
    usage: {
      usage_accuracy: "unknown",
      supports_usage_probe: false,
      usage_probe_kind: "cached_claude_quota",
      usage_parser_type: "generic",
    },
    output: {
      output_parser_type: "generic",
      patch_strategy: "git_diff",
      artifact_path_strategy: "none",
    },
    limits: { default_timeout_seconds: 300, max_timeout_seconds: 3600 },
  },
  codex_cli: {
    adapter_type: "codex_cli",
    display_name: "Codex CLI",
    runtime_kind: "local_cli",
    implementation_status: "implemented",
    enabled_by_default: true,
    executable: { command: "codex", allow_path_override: true },
    invocation: {
      headless_command_template: ["{executable}", "{prompt}"],
      argument_rendering_strategy: "argv_template",
    },
    context: {
      context_file_type: "AGENTS.md",
      context_target_format: "codex_cli",
      writes_vendor_context_file: true,
    },
    credentials: {
      credential_mode: "cli_profile",
      credential_runtime_name: "codex_cli",
      default_target_path: "/home/agent/.codex",
      supports_oauth_login_state: true,
    },
    sandbox: worktreeCli,
    model: {
      model_provider_mode: "none",
      supports_model_override: false,
      model_config_behavior: "not_applicable",
    },
    permissions: { supports_permission_bypass: false },
    usage: {
      usage_accuracy: "unknown",
      supports_usage_probe: false,
      usage_parser_type: "generic",
    },
    output: {
      output_parser_type: "generic",
      patch_strategy: "git_diff",
      artifact_path_strategy: "none",
    },
    limits: { default_timeout_seconds: 300, max_timeout_seconds: 3600 },
  },
  opencode: {
    adapter_type: "opencode",
    display_name: "OpenCode",
    runtime_kind: "local_cli",
    implementation_status: "planned",
    enabled_by_default: false,
    executable: { command: "opencode", allow_path_override: true },
    invocation: {
      headless_command_template: [],
      argument_rendering_strategy: "argv_template",
    },
    context: {
      context_file_type: "AGENTS.md",
      context_target_format: "generic",
      writes_vendor_context_file: false,
    },
    credentials: {
      credential_mode: "cli_profile",
      credential_runtime_name: "opencode",
    },
    sandbox: worktreeCli,
    model: {
      model_provider_mode: "none",
      supports_model_override: false,
      model_config_behavior: "not_applicable",
    },
    permissions: { supports_permission_bypass: false },
    usage: {
      usage_accuracy: "unknown",
      supports_usage_probe: false,
      usage_parser_type: "generic",
    },
    output: {
      output_parser_type: "generic",
      patch_strategy: "git_diff",
      artifact_path_strategy: "none",
    },
    limits: { default_timeout_seconds: 300, max_timeout_seconds: 3600 },
  },
  gemini_cli: {
    adapter_type: "gemini_cli",
    display_name: "Gemini CLI",
    runtime_kind: "local_cli",
    implementation_status: "planned",
    enabled_by_default: false,
    executable: { command: "gemini", allow_path_override: true },
    invocation: {
      headless_command_template: [],
      argument_rendering_strategy: "argv_template",
    },
    context: {
      context_file_type: "AGENTS.md",
      context_target_format: "generic",
      writes_vendor_context_file: false,
    },
    credentials: {
      credential_mode: "cli_profile",
      credential_runtime_name: "gemini_cli",
    },
    sandbox: worktreeCli,
    model: {
      model_provider_mode: "none",
      supports_model_override: false,
      model_config_behavior: "not_applicable",
    },
    permissions: { supports_permission_bypass: false },
    usage: {
      usage_accuracy: "unknown",
      supports_usage_probe: false,
      usage_parser_type: "generic",
    },
    output: {
      output_parser_type: "generic",
      patch_strategy: "git_diff",
      artifact_path_strategy: "none",
    },
    limits: { default_timeout_seconds: 300, max_timeout_seconds: 3600 },
  },
  custom: {
    adapter_type: "custom",
    display_name: "Custom Runtime Adapter",
    runtime_kind: "custom",
    implementation_status: "planned",
    enabled_by_default: false,
    context: {
      context_file_type: "custom",
      context_target_format: "custom",
      writes_vendor_context_file: false,
    },
    credentials: { credential_mode: "none" },
    sandbox: {
      requires_file_access: true,
      minimum_sandbox_level: "worktree",
      supports_worktree: true,
      supports_one_shot_docker: false,
      requires_workspace_for_execution: true,
    },
    model: {
      model_provider_mode: "optional",
      supports_model_override: false,
      model_config_behavior: "unsupported",
    },
    permissions: { supports_permission_bypass: false },
    usage: {
      usage_accuracy: "unknown",
      supports_usage_probe: false,
      usage_parser_type: "generic",
    },
    output: {
      output_parser_type: "generic",
      patch_strategy: "git_diff",
      artifact_path_strategy: "none",
    },
    limits: { default_timeout_seconds: 300, max_timeout_seconds: 3600 },
  },
};

export function listRuntimeAdapterSpecs(): RuntimeAdapterSpec[] {
  return Object.values(BUILTIN_RUNTIME_ADAPTER_SPECS);
}

export function getRuntimeAdapterSpec(adapterType: string | null | undefined): RuntimeAdapterSpec | null {
  if (!adapterType) return null;
  return BUILTIN_RUNTIME_ADAPTER_SPECS[adapterType as RuntimeAdapterType] ?? null;
}

export function isImplementedRuntimeAdapter(adapterType: string | null | undefined): boolean {
  return getRuntimeAdapterSpec(adapterType)?.implementation_status === "implemented";
}

export function isLocalCliRuntimeAdapter(adapterType: string | null | undefined): boolean {
  return getRuntimeAdapterSpec(adapterType)?.runtime_kind === "local_cli";
}

export function getLocalCliRuntimeAdapterSpec(
  adapterType: string | null | undefined,
): LocalCliRuntimeAdapterSpec | null {
  const spec = getRuntimeAdapterSpec(adapterType);
  if (!spec || spec.runtime_kind !== "local_cli") return null;
  return spec as LocalCliRuntimeAdapterSpec;
}

export function isVendorCliAdapter(adapterType: string | null | undefined): boolean {
  const spec = getRuntimeAdapterSpec(adapterType);
  return spec?.runtime_kind === "local_cli" && spec.implementation_status === "implemented";
}

export function targetFormatForAdapter(adapterType: string | null | undefined): string | null {
  return getRuntimeAdapterSpec(adapterType)?.context.context_target_format ?? null;
}
