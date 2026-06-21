import type {
  CanonicalModelEvent,
  CanonicalUsage,
  RuntimeHostExecuteRequest,
  RuntimeHostExecuteResponse,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ServerConfig } from "../../config";
import { resolveProviderCommandStore } from "../providers/providerCommandStore";
import {
  completeProviderMessages,
  ProviderInvocationError,
} from "../providers/providerInvocation";

function nowIso(): string {
  return new Date().toISOString();
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.trunc(value)
    : undefined;
}

function normalizeUsage(raw: Record<string, unknown> | null | undefined): CanonicalUsage | null {
  if (!raw) return null;
  const inputTokens = numberValue(raw.input_tokens ?? raw.prompt_tokens);
  const outputTokens = numberValue(raw.output_tokens ?? raw.completion_tokens);
  const totalTokens = numberValue(raw.total_tokens ?? raw.total_tokens_used ?? raw.total);
  const usage: CanonicalUsage = {};
  if (inputTokens !== undefined) usage.input_tokens = inputTokens;
  if (outputTokens !== undefined) usage.output_tokens = outputTokens;
  if (totalTokens !== undefined) usage.total_tokens = totalTokens;
  return Object.keys(usage).length > 0 ? usage : null;
}

function modelEvents({
  model,
  text,
  usage,
  startedAt,
}: {
  model: string;
  text: string;
  usage: CanonicalUsage | null;
  startedAt: string;
}): CanonicalModelEvent[] {
  const events: CanonicalModelEvent[] = [
    { type: "model.message_start", model, occurred_at: startedAt },
  ];
  if (text) events.push({ type: "model.text_delta", delta: text });
  if (usage) events.push({ type: "model.usage", usage });
  events.push({ type: "model.message_stop", finish_reason: "stop" });
  return events;
}

function failureResponse(
  input: RuntimeHostExecuteRequest,
  startedAt: string,
  errorCode: string,
  errorText: string,
): RuntimeHostExecuteResponse {
  const completedAt = nowIso();
  return {
    success: false,
    stdout: "",
    stderr: errorText,
    output_text: "",
    output_json: {
      adapter_type: "ts_agent_host",
      run_id: input.run_id,
    },
    exit_code: 1,
    error_code: errorCode,
    error_text: errorText,
    started_at: startedAt,
    completed_at: completedAt,
    model: input.model ?? null,
    usage: null,
    events: [
      {
        type: "model.error",
        error: {
          code: errorCode,
          message: errorText,
        },
      },
    ],
    adapter_metadata: {
      adapter_type: "ts_agent_host",
      run_id: input.run_id,
      tool_mode: input.tool_mode,
    },
    adapter_log_json: null,
  };
}

export async function executeRuntimeHost(
  config: ServerConfig,
  input: RuntimeHostExecuteRequest,
): Promise<RuntimeHostExecuteResponse> {
  const startedAt = nowIso();
  const toolMode = input.tool_mode ?? "disabled";
  const toolBindings = input.tool_bindings ?? [];

  if (toolMode !== "disabled" || toolBindings.length > 0) {
    return failureResponse(
      input,
      startedAt,
      "runtime_tools_not_implemented",
      "server runtime host tool execution is not enabled yet.",
    );
  }

  try {
    const result = await completeProviderMessages(
      resolveProviderCommandStore(config),
      input.space_id,
      {
        provider_id: input.model_provider_id,
        model: input.model,
        system: input.system_prompt ?? "",
        messages: input.messages?.length
          ? input.messages.map((message) => ({
              role: message.role,
              content: message.content ?? "",
            }))
          : [{ role: "user", content: input.prompt }],
        max_tokens: input.max_tokens,
        task: "runtime_host",
      },
    );
    const completedAt = nowIso();
    const usage = normalizeUsage(result.usage);
    return {
      success: true,
      stdout: result.text,
      stderr: "",
      output_text: result.text,
      output_json: {
        adapter_type: "ts_agent_host",
        model: result.model,
        usage,
      },
      exit_code: 0,
      error_code: null,
      error_text: null,
      started_at: startedAt,
      completed_at: completedAt,
      model: result.model,
      usage,
      events: modelEvents({
        model: result.model,
        text: result.text,
        usage,
        startedAt,
      }),
      adapter_metadata: {
        adapter_type: "ts_agent_host",
        run_id: input.run_id,
        model_provider_id: input.model_provider_id,
        tool_mode: "disabled",
      },
      adapter_log_json: {
        events_source: "provider_text_completion",
      },
    };
  } catch (error) {
    if (error instanceof ProviderInvocationError) {
      return failureResponse(
        input,
        startedAt,
        "provider_invocation_failed",
        error.message,
      );
    }
    return failureResponse(
      input,
      startedAt,
      "runtime_host_call_failed",
      "server runtime host provider invocation failed.",
    );
  }
}
