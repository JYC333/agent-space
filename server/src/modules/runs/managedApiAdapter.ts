import type {
  CanonicalUsage,
  RunAdapterResultEnvelope,
  RuntimeHostExecuteRequest,
  RuntimeHostExecuteResponse,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ServerConfig } from "../../config";
import { executeRuntimeHost } from "../runtimeHost";
import type { RunRecord } from "./repository";
import {
  redactEvidenceText,
  sanitizeEvidenceJson,
} from "./evidenceRedaction";

export type ManagedApiAdapterType = "model_api" | "ts_agent_host";

// NOTE: runtime.execute / runtime.use_credential policy is enforced once,
// upstream, in RunOrchestrationService.enforceRuntimePolicy. This adapter is
// only reached after that gate allows the run, so it holds no policy seam of
// its own.

export type RuntimeHostExecutor = (
  config: ServerConfig,
  request: RuntimeHostExecuteRequest,
) => Promise<RuntimeHostExecuteResponse>;

export interface ManagedApiNoToolAdapterInput {
  run: RunRecord;
  adapter_type?: string | null;
  model_provider_id?: string | null;
  model?: string | null;
  system_prompt?: string | null;
  prompt?: string | null;
  context_text?: string | null;
  max_tokens?: number | null;
  context_snapshot_id?: string | null;
}

export interface ManagedApiNoToolAdapterDeps {
  executeRuntimeHost?: RuntimeHostExecutor;
}

export async function executeManagedApiNoToolAdapter(
  config: ServerConfig,
  input: ManagedApiNoToolAdapterInput,
  deps: ManagedApiNoToolAdapterDeps = {},
): Promise<RunAdapterResultEnvelope> {
  const startedAt = new Date().toISOString();
  const adapterType = normalizeManagedApiAdapterType(
    input.adapter_type ?? input.run.adapter_type,
  );
  if (!adapterType) {
    return failureEnvelope(
      input,
      "managed_api_adapter_unsupported",
      `Managed API no-tool execution does not support adapter '${input.adapter_type ?? input.run.adapter_type ?? "unknown"}'.`,
      startedAt,
    );
  }

  const modelProviderId = input.model_provider_id ?? input.run.model_provider_id;
  if (!modelProviderId) {
    return failureEnvelope(
      input,
      "model_provider_required",
      `${adapterType} adapter requires an explicit ModelProvider grant.`,
      startedAt,
      adapterType,
    );
  }

  const request = runtimeHostRequest(input, adapterType, modelProviderId);
  const execute = deps.executeRuntimeHost ?? executeRuntimeHost;
  const response = await execute(config, request);
  return envelopeFromRuntimeHost(input, adapterType, response, startedAt);
}

function normalizeManagedApiAdapterType(value: string | null | undefined): ManagedApiAdapterType | null {
  if (value === "model_api" || value === "ts_agent_host") return value;
  return null;
}

function runtimeHostRequest(
  input: ManagedApiNoToolAdapterInput,
  adapterType: ManagedApiAdapterType,
  modelProviderId: string,
): RuntimeHostExecuteRequest {
  const systemPrompt =
    input.system_prompt ?? input.run.system_prompt ?? input.run.instruction ?? null;
  return {
    run_id: input.run.id,
    space_id: input.run.space_id,
    model_provider_id: modelProviderId,
    model: input.model ?? null,
    system_prompt: composeSystemContext(systemPrompt, input.context_text ?? null),
    prompt: input.prompt ?? input.run.prompt ?? "",
    mode: input.run.mode,
    instruction: input.run.instruction,
    project_id: input.run.project_id,
    workspace_id: input.run.workspace_id,
    capability_id: null,
    context_snapshot_id: input.context_snapshot_id ?? null,
    max_tokens: input.max_tokens ?? undefined,
    tool_mode: "disabled",
    tool_bindings: [],
  };
}

function composeSystemContext(
  systemPrompt: string | null | undefined,
  contextText: string | null | undefined,
): string {
  return [systemPrompt, contextText]
    .map((part) => typeof part === "string" ? part.trim() : "")
    .filter((part) => part.length > 0)
    .join("\n\n");
}

function envelopeFromRuntimeHost(
  input: ManagedApiNoToolAdapterInput,
  adapterType: ManagedApiAdapterType,
  response: RuntimeHostExecuteResponse,
  startedAt: string,
): RunAdapterResultEnvelope {
  const metadata = sanitizeEvidenceJson({
    ...(recordOrEmpty(response.adapter_metadata)),
    adapter_type: adapterType,
    runtime_host_adapter_type: recordOrEmpty(response.adapter_metadata).adapter_type,
    model_provider_id: input.model_provider_id ?? input.run.model_provider_id,
    model: response.model ?? input.model ?? null,
  });
  return {
    adapter_type: adapterType,
    adapter_kind: "managed_api",
    success: response.success,
    output_text: redactEvidenceText(response.output_text || response.stdout || "") ?? "",
    output_json: sanitizeEvidenceJson({
      ...(recordOrEmpty(response.output_json)),
      adapter_type: adapterType,
      model: response.model ?? input.model ?? null,
      usage: normalizeUsage(response.usage),
    }) as RunAdapterResultEnvelope["output_json"],
    exit_code: response.exit_code,
    error_code: response.error_code ?? null,
    error_message: redactEvidenceText(response.error_text ?? null),
    started_at: response.started_at ?? startedAt,
    completed_at: response.completed_at ?? new Date().toISOString(),
    usage: normalizeUsage(response.usage),
    metadata_json: metadata as RunAdapterResultEnvelope["metadata_json"],
  };
}

function failureEnvelope(
  input: ManagedApiNoToolAdapterInput,
  errorCode: string,
  message: string,
  startedAt: string,
  adapterType: ManagedApiAdapterType = "ts_agent_host",
  metadataJson: unknown = {},
): RunAdapterResultEnvelope {
  const completedAt = new Date().toISOString();
  return {
    adapter_type: adapterType,
    adapter_kind: "managed_api",
    success: false,
    output_text: "",
    output_json: {
      adapter_type: adapterType,
      run_id: input.run.id,
    },
    exit_code: 1,
    error_code: errorCode,
    error_message: redactEvidenceText(message),
    started_at: startedAt,
    completed_at: completedAt,
    usage: null,
    metadata_json: sanitizeEvidenceJson({
      adapter_type: adapterType,
      run_id: input.run.id,
      ...recordOrEmpty(metadataJson),
    }) as RunAdapterResultEnvelope["metadata_json"],
  };
}

function recordOrEmpty(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function normalizeUsage(value: CanonicalUsage | null | undefined): CanonicalUsage | null {
  if (!value) return null;
  const usage: CanonicalUsage = {};
  if (typeof value.input_tokens === "number") usage.input_tokens = value.input_tokens;
  if (typeof value.output_tokens === "number") usage.output_tokens = value.output_tokens;
  if (typeof value.total_tokens === "number") usage.total_tokens = value.total_tokens;
  return Object.keys(usage).length > 0 ? usage : null;
}
