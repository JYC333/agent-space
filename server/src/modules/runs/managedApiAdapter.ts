import type {
  CanonicalMessage,
  CanonicalUsage,
  RunAdapterResultEnvelope,
  RuntimeHostExecuteRequest,
  RuntimeHostExecuteResponse,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ServerConfig } from "../../config";
import { executeRuntimeHost } from "../runtimeHost";
import type { RunRecord } from "./repository";
import {
  executeWithRetrievalTools,
  resolveRetrievalToolBinding,
  type ManagedApiRetrievalToolDeps,
} from "./managedRetrievalTools";
import {
  executeWithAgentDelegationTools,
  resolveAgentDelegationToolBinding,
  type AgentDelegationToolDeps,
} from "./managedAgentDelegationTools";
import {
  redactEvidenceText,
  redactSecretPatterns,
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
  model?: string | null;
  system_prompt?: string | null;
  prompt?: string | null;
  context_text?: string | null;
  max_tokens?: number | null;
  context_snapshot_id?: string | null;
}

export interface ManagedApiNoToolAdapterDeps extends ManagedApiRetrievalToolDeps {
  executeRuntimeHost?: RuntimeHostExecutor;
  agentDelegationTools?: AgentDelegationToolDeps;
}

export async function executeManagedApiNoToolAdapter(
  config: ServerConfig,
  input: ManagedApiNoToolAdapterInput,
  deps: ManagedApiNoToolAdapterDeps = {},
): Promise<RunAdapterResultEnvelope> {
  const startedAt = new Date().toISOString();
  const adapterType = normalizeManagedApiAdapterType(
    input.run.adapter_type,
  );
  if (!adapterType) {
    return failureEnvelope(
      input,
      "managed_api_adapter_unsupported",
      `Managed API no-tool execution does not support adapter '${input.run.adapter_type ?? "unknown"}'.`,
      startedAt,
    );
  }

  const modelProviderId = input.run.model_provider_id;
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
  const agentDelegationTools = await resolveAgentDelegationToolBinding(
    config,
    input.run,
    deps.agentDelegationTools,
  );
  const retrievalTools = await resolveRetrievalToolBinding(config, input.run, deps);
  let response: RuntimeHostExecuteResponse;
  if (agentDelegationTools) {
    response = await executeWithAgentDelegationTools(config, input.run, request, execute, agentDelegationTools);
  } else if (retrievalTools) {
    response = await executeWithRetrievalTools(config, input.run, request, execute, retrievalTools);
  } else {
    response = await execute(config, request);
  }
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
  const groupedAgentIdentity = groupedAgentIdentityContext(input.run);
  const override = recordOrEmpty(input.run.model_override_json);
  const messages = canonicalMessages(override.messages);
  const chatContextPreamble = typeof override.chat_context_preamble === "string"
    ? override.chat_context_preamble
    : null;
  return {
    run_id: input.run.id,
    space_id: input.run.space_id,
    model_provider_id: modelProviderId,
    model: input.model ?? null,
    system_prompt: composeSystemContext(
      groupedAgentIdentity,
      systemPrompt,
      input.context_text ?? null,
      chatContextPreamble,
    ),
    prompt: input.prompt ?? input.run.prompt ?? "",
    ...(messages ? { messages } : {}),
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

function groupedAgentIdentityContext(run: RunRecord): string | null {
  if (!run.run_group_id) return null;
  const name = stringValue(run.agent_name);
  const label = name ?? "the current room agent";
  return [
    "Agent room execution context:",
    `- You are ${label} for this run.`,
    "- If the user message includes a structured @mention matching your name, treat it as addressing you directly.",
    "- Do not claim to be the room manager or another room member unless this run's agent identity is that agent.",
    "- Internal agent IDs, run IDs, UUIDs, and tool identifiers are system details. Do not include them in user-facing replies unless the user explicitly asks for audit/debug identifiers.",
  ].join("\n");
}

function composeSystemContext(
  systemPrompt: string | null | undefined,
  ...contextParts: Array<string | null | undefined>
): string {
  return [systemPrompt, ...contextParts]
    .map((part) => typeof part === "string" ? part.trim() : "")
    .filter((part) => part.length > 0)
    .join("\n\n");
}

function canonicalMessages(value: unknown): CanonicalMessage[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const messages: CanonicalMessage[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const record = item as Record<string, unknown>;
    if (typeof record.role !== "string" || record.role.trim().length === 0) {
      return null;
    }
    if (record.content !== null && typeof record.content !== "string") {
      return null;
    }
    messages.push({
      role: record.role,
      content: record.content ?? "",
    });
  }
  return messages;
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
    model_provider_id: input.run.model_provider_id,
    model: response.model ?? input.model ?? null,
  });
  return {
    adapter_type: adapterType,
    adapter_kind: "managed_api",
    success: response.success,
    // Model chat output is consumed downstream as structured data (e.g.
    // source_post_processing's JSON result contract) and is bounded by the
    // request's max_tokens rather than by arbitrary CLI stdout/patch size, so
    // it must not be cut with the fixed 4000-char evidence-display limit that
    // redactEvidenceText applies — only the secret-pattern redaction applies.
    output_text: redactSecretPatterns(response.output_text || response.stdout || ""),
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

function stringValue(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeUsage(value: CanonicalUsage | null | undefined): CanonicalUsage | null {
  if (!value) return null;
  const usage: CanonicalUsage = {};
  if (typeof value.input_tokens === "number") usage.input_tokens = value.input_tokens;
  if (typeof value.output_tokens === "number") usage.output_tokens = value.output_tokens;
  if (typeof value.total_tokens === "number") usage.total_tokens = value.total_tokens;
  return Object.keys(usage).length > 0 ? usage : null;
}
