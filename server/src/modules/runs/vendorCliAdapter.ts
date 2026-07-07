import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { RunAdapterResultEnvelope } from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ServerConfig } from "../../config";
import {
  CliCredentialBroker,
  type CredentialGrant,
} from "../providers/cli/credentialBroker";
import type { ProviderProxyLeaseRegistry } from "../providers/proxy/lease";
import {
  RuntimeToolError,
  RuntimeToolRegistry,
  type ResolvedRuntimeTool,
  type RuntimeToolResolverPort,
} from "../runtimeTools";
import {
  getLocalCliRuntimeAdapterSpec,
  type LocalCliRuntimeAdapterSpec,
} from "../runtimeAdapters";
import type { RunRecord } from "./repository";
import {
  redactEvidenceText,
  sanitizeEvidenceJson,
} from "./evidenceRedaction";
import {
  CliRenderError,
  renderCliCommand,
  type RenderedCliCommand,
} from "./cliCommandRendering";
import {
  LocalCliCommandExecutor,
  type CliCommandExecutor,
  type CliExecutionResult,
  type CliProcessRegistry,
} from "./localCliExecution";
import {
  buildRuntimeProviderBinding,
  cleanupRuntimeProviderBinding,
  RuntimeProviderBindingError,
  type RuntimeProviderBinding,
  type RuntimeProviderResolverPort,
} from "./runtimeProviderBinding";
import { buildSubprocessEnv } from "./cliSubprocessEnv";
import {
  envForNetworkProfile,
  resolveNetworkProfileRepository,
} from "../networkProfiles";

export { buildSubprocessEnv } from "./cliSubprocessEnv";
export { renderCliCommand } from "./cliCommandRendering";
export {
  LocalCliProcessRegistry,
  type CliCommandExecutor,
  type CliExecutionResult,
  type CliProcessRegistry,
} from "./localCliExecution";

export type VendorCliAdapterType = "claude_code" | "codex_cli";
export type ExecutorMode = "worktree" | "docker";

export interface CliCredentialBrokerPort {
  grantForRun(
    runId: string,
    spaceId: string,
    runtime: string,
    executorMode: ExecutorMode,
    profileId?: string | null,
  ): Promise<CredentialGrant>;
  cleanupRunHome?(runId: string): Promise<void>;
}

export interface VendorCliAdapterInput {
  run: RunRecord;
  prompt?: string | null;
  mode?: string | null;
  model?: string | null;
  sandbox_cwd?: string | null;
  required_sandbox_level?: string | null;
  context_text?: string | null;
  adapter_config?: Record<string, unknown>;
  risk_level?: string | null;
  trigger_origin?: string | null;
  process_registry?: CliProcessRegistry;
}

export interface VendorCliAdapterDeps {
  credentialBroker?: CliCredentialBrokerPort;
  executor?: CliCommandExecutor;
  toolRegistry?: RuntimeToolResolverPort;
  providerResolver?: RuntimeProviderResolverPort;
  providerLeaseRegistry?: ProviderProxyLeaseRegistry;
  providerProxyBaseUrl?: string;
}

const SECRET_COMMAND_KEYS = ["prompt", "context", "api_key", "token", "secret", "password"];

export async function executeVendorCliAdapter(
  config: ServerConfig,
  input: VendorCliAdapterInput,
  deps: VendorCliAdapterDeps = {},
): Promise<RunAdapterResultEnvelope> {
  const startedAt = new Date().toISOString();
  const adapterType = input.run.adapter_type;
  const spec = getLocalCliRuntimeAdapterSpec(adapterType);
  if (!spec) {
    return cliFailure(input, "runtime_adapter_not_found", "Runtime adapter is not registered.", startedAt);
  }
  if (spec.implementation_status !== "implemented") {
    return cliFailure(input, "runtime_adapter_not_implemented", `Runtime adapter '${adapterType}' is not executable.`, startedAt, spec);
  }

  const sandboxError = validateSandbox(input, spec);
  if (sandboxError) {
    return cliFailure(input, sandboxError.code, sandboxError.message, startedAt, spec);
  }

  const credentialBroker = deps.credentialBroker ?? new CliCredentialBroker(config);
  const credential = await grantCredential(input, spec, credentialBroker);
  if (!credential.granted) {
    return cliFailure(
      input,
      "runtime_credential_profile_required",
      `Runtime adapter '${spec.adapter_type}' requires an explicit credential profile.`,
      startedAt,
      spec,
      { credential_profile_id: profileId(input), fallback_reason: credential.fallback_reason },
    );
  }

  if (!input.adapter_config?.context_file_already_rendered) {
    try {
      await renderVendorContext(input, spec);
    } catch (error) {
      await cleanupCredential(input, credentialBroker);
      return cliFailure(
        input,
        "context_render_failed",
        error instanceof Error ? error.message : "CLI context rendering failed.",
        startedAt,
        spec,
      );
    }
  }

  let tool: ResolvedRuntimeTool;
  try {
    const toolRegistry = deps.toolRegistry ?? new RuntimeToolRegistry(config);
    tool = await toolRegistry.resolveForExecution(
      spec.credentials.credential_runtime_name,
      stringValue(input.adapter_config?.runtime_tool_version),
    );
  } catch (error) {
    await cleanupCredential(input, credentialBroker);
    return cliFailure(
      input,
      error instanceof RuntimeToolError ? error.code : "cli_tool_unavailable",
      error instanceof Error ? error.message : `Runtime tool '${spec.credentials.credential_runtime_name}' is unavailable.`,
      startedAt,
      spec,
    );
  }

  let rendered: RenderedCliCommand;
  try {
    rendered = await renderCliCommand(spec, {
      executable: tool.executable_path,
      prompt: input.prompt ?? input.run.prompt ?? "",
      mode: input.mode ?? input.run.mode,
      model: spec.adapter_type === "codex_cli" ? null : input.model ?? null,
      permission_bypass: Boolean(input.adapter_config?.permission_bypass),
      runtime_policy_json: recordValue(input.adapter_config?.runtime_policy_json),
      risk_level: input.risk_level ?? "low",
      workspace_id: input.run.workspace_id,
      sandbox_cwd: input.sandbox_cwd ?? null,
    });
  } catch (error) {
    await cleanupCredential(input, credentialBroker);
    return cliFailure(
      input,
      error instanceof CliRenderError ? error.code : "cli_command_render_failed",
      error instanceof Error ? error.message : "CLI command render failed.",
      startedAt,
      spec,
    );
  }

  const timeout = timeoutSeconds(input.adapter_config, spec);
  let runtimeBinding: RuntimeProviderBinding;
  try {
    runtimeBinding = await buildRuntimeProviderBinding(
      config,
      {
        run: input.run,
        model: input.model ?? null,
      },
      spec,
      {
        credential,
        providerResolver: deps.providerResolver,
        leaseRegistry: deps.providerLeaseRegistry,
        proxyBaseUrl: deps.providerProxyBaseUrl,
        ttlSeconds: timeout + 300,
      },
    );
  } catch (error) {
    await cleanupCredential(input, credentialBroker);
    return cliFailure(
      input,
      error instanceof RuntimeProviderBindingError ? error.code : "cli_runtime_provider_config_failed",
      error instanceof Error ? error.message : "CLI runtime provider configuration failed.",
      startedAt,
      spec,
    );
  }

  const executor = deps.executor ?? new LocalCliCommandExecutor();
  let result: CliExecutionResult;
  try {
    const cliNetworkEnv = await cliDefaultNetworkEnv(config, input.run.space_id, credential, runtimeBinding);
    result = await executor.runCommand({
      command: rendered.argv,
      cwd: input.sandbox_cwd ?? null,
      timeout_seconds: timeout,
      env: buildSubprocessEnv(credential.env, { ...runtimeBinding.env, ...cliNetworkEnv }),
      run_id: input.run.id,
      stdin: rendered.stdin,
      process_registry: input.process_registry,
    });
  } finally {
    cleanupRuntimeProviderBinding(runtimeBinding);
    await cleanupCredential(input, credentialBroker);
  }

  return cliResultEnvelope(
    input,
    spec,
    rendered,
    result,
    timeout,
    credential,
    tool,
    startedAt,
    runtimeBinding,
  );
}

async function cliDefaultNetworkEnv(
  config: ServerConfig,
  spaceId: string,
  credential: CredentialGrant,
  binding: RuntimeProviderBinding,
): Promise<Record<string, string>> {
  if (binding.provider_id || !credential.network_profile_id) return {};
  try {
    const profile = await resolveNetworkProfileRepository(config).resolve(
      spaceId,
      credential.network_profile_id,
    );
    return envForNetworkProfile(profile);
  } catch {
    return {};
  }
}

function validateSandbox(
  input: VendorCliAdapterInput,
  spec: LocalCliRuntimeAdapterSpec,
): { code: string; message: string } | null {
  const level = input.required_sandbox_level ?? input.run.required_sandbox_level;
  if (level === "one_shot_docker" || level === "docker") {
    return spec.sandbox.supports_one_shot_docker
      ? null
      : {
          code: "docker_sandbox_not_implemented",
          message: `Runtime adapter '${spec.adapter_type}' does not support one-shot Docker execution.`,
        };
  }
  if (level === "ephemeral") {
    // Run-scope sandbox: a system-provisioned throwaway working dir. No
    // workspace required; only a prepared working directory.
    if (!input.sandbox_cwd) {
      return {
        code: "workspace_prepare_failed",
        message: `Runtime adapter '${spec.adapter_type}' requires a prepared sandbox working directory.`,
      };
    }
    return null;
  }
  if (level !== "worktree") {
    return {
      code: "file_access_adapter_requires_worktree_policy",
      message: `Runtime adapter '${spec.adapter_type}' requires worktree sandbox policy.`,
    };
  }
  if (!input.run.workspace_id) {
    return {
      code: "workspace_required",
      message: `Runtime adapter '${spec.adapter_type}' requires a workspace_id.`,
    };
  }
  if (!input.sandbox_cwd) {
    return {
      code: "workspace_prepare_failed",
      message: `Runtime adapter '${spec.adapter_type}' requires a prepared sandbox worktree.`,
    };
  }
  return null;
}

async function grantCredential(
  input: VendorCliAdapterInput,
  spec: LocalCliRuntimeAdapterSpec,
  broker: CliCredentialBrokerPort,
): Promise<CredentialGrant> {
  try {
    return await broker.grantForRun(
      input.run.id,
      input.run.space_id,
      spec.credentials.credential_runtime_name,
      "worktree",
      profileId(input),
    );
  } catch {
    return {
      granted: false,
      profile_id: null,
      runtime: spec.credentials.credential_runtime_name,
      executor_mode: "worktree",
      readonly: false,
      temp_home: null,
      host_source_path: null,
      target_path: null,
      env: {},
      network_profile_id: null,
      fallback_reason: "broker_error",
    };
  }
}

async function renderVendorContext(
  input: VendorCliAdapterInput,
  spec: LocalCliRuntimeAdapterSpec,
): Promise<void> {
  if (!spec.context.writes_vendor_context_file) return;
  if (!input.sandbox_cwd) throw new Error("CLI context rendering requires a sandbox worktree.");
  const content = input.context_text ?? "";
  await writeFile(join(input.sandbox_cwd, spec.context.context_file_type), content, {
    encoding: "utf8",
    mode: 0o600,
  });
}

async function cleanupCredential(
  input: VendorCliAdapterInput,
  broker: CliCredentialBrokerPort,
): Promise<void> {
  try {
    await broker.cleanupRunHome?.(input.run.id);
  } catch {}
}

function cliResultEnvelope(
  input: VendorCliAdapterInput,
  spec: LocalCliRuntimeAdapterSpec,
  rendered: RenderedCliCommand,
  result: CliExecutionResult,
  timeout: number,
  credential: CredentialGrant,
  tool: ResolvedRuntimeTool,
  startedAt: string,
  runtimeBinding: RuntimeProviderBinding,
): RunAdapterResultEnvelope {
  const success = result.returncode === 0 && !result.timed_out;
  const stdout = redactCliOutput(result.stdout);
  const stderr = redactCliOutput(result.stderr);
  const completedAt = new Date().toISOString();
  return {
    adapter_type: spec.adapter_type,
    adapter_kind: "local_cli",
    success,
    output_text: stdout,
    output_json: success ? null : { adapter_type: spec.adapter_type },
    exit_code: result.returncode,
    error_code: success
      ? null
      : result.timed_out
        ? "cli_adapter_timeout"
        : "cli_adapter_nonzero_exit",
    error_message: success ? null : stderr || "CLI adapter failed.",
    started_at: startedAt,
    completed_at: completedAt,
    usage: null,
    metadata_json: sanitizeEvidenceJson({
      adapter_type: spec.adapter_type,
      runtime_kind: "local_cli",
      runtime_tool_version: tool.version,
      runtime_tool_source: tool.source,
      runtime_tool_package: tool.package_name,
      credential_checked: true,
      credential_broker_used: true,
      credential_source: "profile",
      credential_profile_id: credential.profile_id,
      temp_home_created: Boolean(credential.temp_home),
      cleanup_status: credential.temp_home ? "requested" : "not_needed",
      trigger_origin: input.trigger_origin ?? input.run.trigger_origin,
      permission_bypass_requested: Boolean(input.adapter_config?.permission_bypass),
      permission_bypass_used: rendered.permission_bypass_used,
      context_file_type: spec.context.context_file_type,
      context_target_format: spec.context.context_target_format,
      rendered_in_sandbox: spec.context.writes_vendor_context_file,
      runtime_provider_id: runtimeBinding.provider_id,
      runtime_provider_model: runtimeBinding.model ?? modelFromRun(input.run),
      runtime_provider_protocol: runtimeBinding.protocol,
      runtime_provider_proxy: Boolean(runtimeBinding.lease_id),
      claude_compatible_provider_id:
        spec.adapter_type === "claude_code" ? input.run.model_provider_id : null,
      claude_compatible_model:
        spec.adapter_type === "claude_code" ? runtimeBinding.model ?? modelFromRun(input.run) : null,
      claude_compatible_provider_proxy:
        spec.adapter_type === "claude_code" ? Boolean(runtimeBinding.lease_id) : null,
    }) as RunAdapterResultEnvelope["metadata_json"],
    adapter_log_json: sanitizeEvidenceJson({
      adapter_type: spec.adapter_type,
      command: rendered.redacted_argv,
      runtime_tool_version: tool.version,
      exit_code: result.returncode,
      timeout_seconds: timeout,
    }) as RunAdapterResultEnvelope["metadata_json"],
  };
}

function cliFailure(
  input: VendorCliAdapterInput,
  errorCode: string,
  message: string,
  startedAt: string,
  spec?: LocalCliRuntimeAdapterSpec,
  metadataJson: unknown = {},
): RunAdapterResultEnvelope {
  const adapterType = spec?.adapter_type ?? (input.run.adapter_type ?? "unknown");
  return {
    adapter_type: adapterType,
    adapter_kind: "local_cli",
    success: false,
    output_text: "",
    output_json: { adapter_type: adapterType },
    exit_code: 1,
    error_code: errorCode,
    error_message: redactEvidenceText(message),
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    usage: null,
    metadata_json: sanitizeEvidenceJson({
      adapter_type: adapterType,
      runtime_kind: "local_cli",
      ...recordValue(metadataJson),
    }) as RunAdapterResultEnvelope["metadata_json"],
  };
}

function timeoutSeconds(config: Record<string, unknown> | undefined, spec: LocalCliRuntimeAdapterSpec): number {
  const raw = config?.timeout;
  const parsed = typeof raw === "number" ? raw : typeof raw === "string" ? Number(raw) : NaN;
  const selected = Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : spec.limits.default_timeout_seconds;
  return Math.min(selected, spec.limits.max_timeout_seconds);
}

function profileId(input: VendorCliAdapterInput): string | null {
  return stringValue(input.adapter_config?.credential_profile_id);
}

function modelFromRun(run: RunRecord): string | null {
  return stringValue(recordValue(run.model_override_json).model);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function redactCliOutput(value: string): string {
  const truncated = value.length > 12_000 ? `${value.slice(0, 12_000)}\n[TRUNCATED]` : value;
  return redactEvidenceText(truncated) ?? "";
}

export function redactCommandLog(argv: string[]): string[] {
  return argv.map((item) =>
    SECRET_COMMAND_KEYS.some((key) => item.toLowerCase().includes(key)) ? "[REDACTED]" : item,
  );
}
