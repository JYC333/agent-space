import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { RunAdapterResultEnvelope } from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ControlPlaneConfig } from "../../config";
import {
  CliCredentialBroker,
  type CredentialGrant,
} from "../providers/cliCredentialBroker";
import {
  RuntimeToolError,
  RuntimeToolRegistry,
  type ResolvedRuntimeTool,
  type RuntimeToolResolverPort,
} from "../runtimeTools";
import type { RunRecord } from "./repository";
import {
  redactEvidenceText,
  sanitizeEvidenceJson,
} from "./evidenceRedaction";

export type VendorCliAdapterType = "claude_code" | "codex_cli";
export type ExecutorMode = "worktree" | "docker";

interface CliAdapterSpec {
  adapter_type: VendorCliAdapterType | "opencode" | "gemini_cli";
  runtime_kind: "local_cli";
  implementation_status: "implemented" | "planned";
  command: string;
  headless_command_template: string[];
  interactive_command_template?: string[];
  argument_rendering_strategy: "argv_template" | "stdin";
  context_file_type: "CLAUDE.md" | "AGENTS.md";
  context_target_format: string;
  writes_vendor_context_file: boolean;
  credential_runtime_name: VendorCliAdapterType | "opencode" | "gemini_cli";
  default_timeout_seconds: number;
  max_timeout_seconds: number;
  supports_model_override: boolean;
  model_arg_template?: string[];
  supports_permission_bypass: boolean;
  permission_bypass_arg_template?: string[];
  permission_bypass_policy_key?: string;
  supports_one_shot_docker: boolean;
}

export interface RenderedCliCommand {
  argv: string[];
  redacted_argv: string[];
  stdin: string | null;
  permission_bypass_used: boolean;
}

export interface CliExecutionResult {
  returncode: number;
  stdout: string;
  stderr: string;
  timed_out: boolean;
}

export interface CliCommandExecutor {
  runCommand(input: {
    command: string[];
    cwd: string | null;
    timeout_seconds: number;
    env: Record<string, string>;
    run_id: string;
    stdin: string | null;
    process_registry?: CliProcessRegistry;
  }): Promise<CliExecutionResult>;
}

export interface CliProcessRegistry {
  register(runId: string, pid: number): void;
  deregister(runId: string): void;
  terminate(runId: string): boolean;
}

export interface CliCredentialBrokerPort {
  grantForRun(
    runId: string,
    runtime: string,
    executorMode: ExecutorMode,
    profileId?: string | null,
  ): Promise<CredentialGrant>;
  cleanupRunHome?(runId: string): Promise<void>;
}

export interface VendorCliAdapterInput {
  run: RunRecord;
  adapter_type?: string | null;
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
}

const SPECS: Record<string, CliAdapterSpec> = {
  claude_code: {
    adapter_type: "claude_code",
    runtime_kind: "local_cli",
    implementation_status: "implemented",
    command: "claude",
    headless_command_template: ["{executable}", "--print", "{prompt}"],
    interactive_command_template: ["{executable}"],
    argument_rendering_strategy: "argv_template",
    context_file_type: "CLAUDE.md",
    context_target_format: "claude",
    writes_vendor_context_file: true,
    credential_runtime_name: "claude_code",
    default_timeout_seconds: 300,
    max_timeout_seconds: 3600,
    supports_model_override: true,
    model_arg_template: ["--model", "{model}"],
    supports_permission_bypass: true,
    permission_bypass_arg_template: ["--dangerously-skip-permissions"],
    permission_bypass_policy_key: "allow_permission_bypass",
    supports_one_shot_docker: false,
  },
  codex_cli: {
    adapter_type: "codex_cli",
    runtime_kind: "local_cli",
    implementation_status: "implemented",
    command: "codex",
    headless_command_template: ["{executable}", "{prompt}"],
    argument_rendering_strategy: "argv_template",
    context_file_type: "AGENTS.md",
    context_target_format: "codex_cli",
    writes_vendor_context_file: true,
    credential_runtime_name: "codex_cli",
    default_timeout_seconds: 300,
    max_timeout_seconds: 3600,
    supports_model_override: false,
    supports_permission_bypass: false,
    supports_one_shot_docker: false,
  },
  opencode: {
    adapter_type: "opencode",
    runtime_kind: "local_cli",
    implementation_status: "planned",
    command: "opencode",
    headless_command_template: [],
    argument_rendering_strategy: "argv_template",
    context_file_type: "AGENTS.md",
    context_target_format: "generic",
    writes_vendor_context_file: false,
    credential_runtime_name: "opencode",
    default_timeout_seconds: 300,
    max_timeout_seconds: 3600,
    supports_model_override: false,
    supports_permission_bypass: false,
    supports_one_shot_docker: false,
  },
  gemini_cli: {
    adapter_type: "gemini_cli",
    runtime_kind: "local_cli",
    implementation_status: "planned",
    command: "gemini",
    headless_command_template: [],
    argument_rendering_strategy: "argv_template",
    context_file_type: "AGENTS.md",
    context_target_format: "generic",
    writes_vendor_context_file: false,
    credential_runtime_name: "gemini_cli",
    default_timeout_seconds: 300,
    max_timeout_seconds: 3600,
    supports_model_override: false,
    supports_permission_bypass: false,
    supports_one_shot_docker: false,
  },
};

const ENV_ALLOWED_KEYS = new Set(["PATH", "TERM", "SHELL", "LANG"]);
const BROKER_ENV_KEYS = new Set(["HOME"]);
const SECRET_COMMAND_KEYS = ["prompt", "context", "api_key", "token", "secret", "password"];

export async function executeVendorCliAdapter(
  config: ControlPlaneConfig,
  input: VendorCliAdapterInput,
  deps: VendorCliAdapterDeps = {},
): Promise<RunAdapterResultEnvelope> {
  const startedAt = new Date().toISOString();
  const adapterType = input.adapter_type ?? input.run.adapter_type;
  const spec = adapterType ? SPECS[adapterType] : undefined;
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
    tool = await toolRegistry.resolveForExecution(spec.credential_runtime_name);
  } catch (error) {
    await cleanupCredential(input, credentialBroker);
    return cliFailure(
      input,
      error instanceof RuntimeToolError ? error.code : "cli_tool_unavailable",
      error instanceof Error ? error.message : `Runtime tool '${spec.credential_runtime_name}' is unavailable.`,
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
      model: input.model ?? null,
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
  const executor = deps.executor ?? new LocalCliCommandExecutor();
  const result = await executor.runCommand({
    command: rendered.argv,
    cwd: input.sandbox_cwd ?? null,
    timeout_seconds: timeout,
    env: buildSubprocessEnv(credential.env),
    run_id: input.run.id,
    stdin: rendered.stdin,
    process_registry: input.process_registry,
  });
  await cleanupCredential(input, credentialBroker);

  return cliResultEnvelope(input, spec, rendered, result, timeout, credential, tool, startedAt);
}

export class LocalCliProcessRegistry implements CliProcessRegistry {
  private readonly processes = new Map<string, number>();

  register(runId: string, pid: number): void {
    this.processes.set(runId, pid);
  }

  deregister(runId: string): void {
    this.processes.delete(runId);
  }

  terminate(runId: string): boolean {
    const pid = this.processes.get(runId);
    if (!pid) return false;
    try {
      process.kill(-pid, "SIGTERM");
    } catch {
      try {
        process.kill(pid, "SIGTERM");
      } catch {
        return false;
      }
    }
    return true;
  }
}

export class LocalCliCommandExecutor implements CliCommandExecutor {
  async runCommand(input: {
    command: string[];
    cwd: string | null;
    timeout_seconds: number;
    env: Record<string, string>;
    run_id: string;
    stdin: string | null;
    process_registry?: CliProcessRegistry;
  }): Promise<CliExecutionResult> {
    return new Promise((resolveResult) => {
      let settled = false;
      let stdout = "";
      let stderr = "";
      let proc;
      try {
        proc = spawn(input.command[0], input.command.slice(1), {
          cwd: input.cwd ?? undefined,
          env: input.env,
          detached: true,
          shell: false,
          stdio: ["pipe", "pipe", "pipe"],
        });
      } catch (error) {
        resolveResult({
          returncode: -1,
          stdout: "",
          stderr: error instanceof Error ? error.message : "CLI spawn failed.",
          timed_out: false,
        });
        return;
      }

      input.process_registry?.register(input.run_id, proc.pid ?? -1);
      proc.stdout?.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf8");
      });
      proc.stderr?.on("data", (chunk: Buffer) => {
        stderr += chunk.toString("utf8");
      });
      proc.on("error", (error: Error) => {
        if (settled) return;
        settled = true;
        input.process_registry?.deregister(input.run_id);
        clearTimeout(timer);
        resolveResult({ returncode: -1, stdout, stderr: error.message, timed_out: false });
      });
      proc.on("close", (code: number | null) => {
        if (settled) return;
        settled = true;
        input.process_registry?.deregister(input.run_id);
        clearTimeout(timer);
        resolveResult({ returncode: code ?? -1, stdout, stderr, timed_out: false });
      });
      if (input.stdin !== null) proc.stdin?.end(input.stdin);
      else proc.stdin?.end();

      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        try {
          if (proc.pid) process.kill(-proc.pid, "SIGKILL");
        } catch {
          proc.kill("SIGKILL");
        }
        input.process_registry?.deregister(input.run_id);
        resolveResult({
          returncode: -1,
          stdout,
          stderr: stderr || "Command timed out.",
          timed_out: true,
        });
      }, input.timeout_seconds * 1000);
    });
  }
}

export function buildSubprocessEnv(extra: Record<string, string> | null | undefined): Record<string, string> {
  const safe: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue;
    if (ENV_ALLOWED_KEYS.has(key) || key.startsWith("LC_")) safe[key] = value;
  }
  for (const [key, value] of Object.entries(extra ?? {})) {
    if (BROKER_ENV_KEYS.has(key)) safe[key] = value;
  }
  return safe;
}

export async function renderCliCommand(
  spec: CliAdapterSpec,
  input: {
    executable: string;
    prompt: string;
    mode: string;
    model: string | null;
    permission_bypass: boolean;
    runtime_policy_json?: Record<string, unknown>;
    risk_level: string;
    workspace_id: string | null;
    sandbox_cwd: string | null;
  },
): Promise<RenderedCliCommand> {
  const template =
    input.mode === "interactive" && spec.interactive_command_template
      ? spec.interactive_command_template
      : spec.headless_command_template;
  const values = { executable: input.executable, prompt: input.prompt };
  const argv = renderTemplate(template, values);
  const redacted = renderTemplate(template, { ...values, prompt: "[REDACTED_PROMPT]" });

  const extraArgs: string[] = [];
  if (input.model) {
    if (!spec.supports_model_override || !spec.model_arg_template) {
      throw new CliRenderError("model_override_not_supported", `adapter_type '${spec.adapter_type}' does not support model override`);
    }
    extraArgs.push(...renderTemplate(spec.model_arg_template, { model: input.model }));
  }

  if (input.permission_bypass) {
    const permissionError = permissionBypassError(spec, input);
    if (permissionError) {
      throw new CliRenderError("permission_bypass_not_allowed", permissionError);
    }
    extraArgs.push(...(spec.permission_bypass_arg_template ?? []));
  }

  if (extraArgs.length > 0) {
    const insertAt = argv.findIndex((arg) => arg === input.prompt);
    argv.splice(insertAt >= 0 ? insertAt : argv.length, 0, ...extraArgs);
    const redactedInsertAt = redacted.findIndex((arg) => arg === "[REDACTED_PROMPT]");
    redacted.splice(redactedInsertAt >= 0 ? redactedInsertAt : redacted.length, 0, ...extraArgs);
  }

  const stdin = spec.argument_rendering_strategy === "stdin" ? input.prompt : null;
  return {
    argv: stdin === null ? argv : argv.filter((arg) => arg !== input.prompt),
    redacted_argv: stdin === null ? redacted : redacted.filter((arg) => arg !== "[REDACTED_PROMPT]"),
    stdin,
    permission_bypass_used:
      input.permission_bypass &&
      (spec.permission_bypass_arg_template ?? []).every((arg) => argv.includes(arg)),
  };
}

class CliRenderError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "CliRenderError";
  }
}

function renderTemplate(template: string[], values: Record<string, string>): string[] {
  return template.map((part) =>
    part.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (_match, name: string) => {
      const value = values[name];
      if (value === undefined) {
        throw new CliRenderError("unknown_template_variable", `unknown command template variable: ${name}`);
      }
      return value;
    }),
  );
}

function validateSandbox(
  input: VendorCliAdapterInput,
  spec: CliAdapterSpec,
): { code: string; message: string } | null {
  const level = input.required_sandbox_level ?? input.run.required_sandbox_level;
  if (level === "one_shot_docker" || level === "docker") {
    return spec.supports_one_shot_docker
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
  spec: CliAdapterSpec,
  broker: CliCredentialBrokerPort,
): Promise<CredentialGrant> {
  try {
    return await broker.grantForRun(
      input.run.id,
      spec.credential_runtime_name,
      "worktree",
      profileId(input),
    );
  } catch {
    return {
      granted: false,
      profile_id: null,
      runtime: spec.credential_runtime_name,
      executor_mode: "worktree",
      readonly: false,
      temp_home: null,
      host_source_path: null,
      target_path: null,
      env: {},
      fallback_reason: "broker_error",
    };
  }
}

async function renderVendorContext(
  input: VendorCliAdapterInput,
  spec: CliAdapterSpec,
): Promise<void> {
  if (!spec.writes_vendor_context_file) return;
  if (!input.sandbox_cwd) throw new Error("CLI context rendering requires a sandbox worktree.");
  const content = input.context_text ?? "";
  await writeFile(join(input.sandbox_cwd, spec.context_file_type), content, {
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
  spec: CliAdapterSpec,
  rendered: RenderedCliCommand,
  result: CliExecutionResult,
  timeout: number,
  credential: CredentialGrant,
  tool: ResolvedRuntimeTool,
  startedAt: string,
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
      context_file_type: spec.context_file_type,
      context_target_format: spec.context_target_format,
      rendered_in_sandbox: spec.writes_vendor_context_file,
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
  spec?: CliAdapterSpec,
  metadataJson: unknown = {},
): RunAdapterResultEnvelope {
  const adapterType = spec?.adapter_type ?? (input.adapter_type ?? input.run.adapter_type ?? "unknown");
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

function permissionBypassError(
  spec: CliAdapterSpec,
  input: {
    runtime_policy_json?: Record<string, unknown>;
    risk_level: string;
    workspace_id: string | null;
    sandbox_cwd: string | null;
  },
): string | null {
  if (!spec.supports_permission_bypass) {
    return `Runtime adapter '${spec.adapter_type}' does not support permission bypass.`;
  }
  const key = spec.permission_bypass_policy_key ?? "allow_permission_bypass";
  if (input.runtime_policy_json?.[key] !== true) {
    return `runtime_policy_json.${key}=true is required for permission bypass.`;
  }
  if (!["high", "critical"].includes(input.risk_level)) {
    return "Permission bypass requires risk_level high or critical.";
  }
  if (!input.workspace_id || !input.sandbox_cwd) {
    return "Permission bypass requires an existing worktree workspace.";
  }
  return null;
}

function timeoutSeconds(config: Record<string, unknown> | undefined, spec: CliAdapterSpec): number {
  const raw = config?.timeout;
  const parsed = typeof raw === "number" ? raw : typeof raw === "string" ? Number(raw) : NaN;
  const selected = Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : spec.default_timeout_seconds;
  return Math.min(selected, spec.max_timeout_seconds);
}

function profileId(input: VendorCliAdapterInput): string | null {
  return stringValue(input.adapter_config?.credential_profile_id);
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
