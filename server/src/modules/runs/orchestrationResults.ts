import type {
  RunAdapterResultEnvelope,
  RunMaterializationItemSummary,
  RunStatus,
  RunTerminalStatus,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import {
  redactEvidenceText,
  sanitizeEvidenceJson,
} from "./evidenceRedaction";
import { RunPreparationError } from "./orchestrationErrors";
import type { RunRecord } from "./repository";

interface PreparedRuntimeInput {
  prompt: string | null;
  sandbox_cwd: string | null;
  context_text: string | null;
  adapter_config: Record<string, unknown>;
  risk_level: string | null;
}

export function terminalStatusFromAdapter(result: RunAdapterResultEnvelope): RunTerminalStatus {
  if (result.success) return "succeeded";
  if (result.error_code === "run_cancelled") return "cancelled";
  return "failed";
}

export function adapterErrorJson(result: RunAdapterResultEnvelope): unknown {
  if (result.success) return {};
  const output = recordValue(result.output_json);
  const diagnostics = recordValue(output.structured_output_diagnostics);
  return sanitizeEvidenceJson({
    error_code: result.error_code ?? "adapter_failed",
    error_text: result.error_message ?? "Runtime adapter failed.",
    adapter_type: result.adapter_type,
    adapter_kind: result.adapter_kind,
    exit_code: result.exit_code,
    ...(Object.keys(diagnostics).length > 0
      ? { structured_output_diagnostics: diagnostics }
      : {}),
  });
}

export function outputJsonWithMaterialization(
  outputJson: unknown,
  items: RunMaterializationItemSummary[],
  errors: string[],
): unknown {
  const output = recordValue(outputJson);
  if (items.length > 0) output.materialization = sanitizeEvidenceJson(items);
  if (errors.length > 0) output.materialization_errors = errors.map((error) => redactEvidenceText(error));
  return sanitizeEvidenceJson(output);
}

export function waitingForDependencyFromAdapter(
  result: RunAdapterResultEnvelope,
): Record<string, unknown> | null {
  if (!result.success) return null;
  const waiting = recordValue(recordValue(result.output_json).waiting_for_results);
  if (waiting.status !== "waiting") return null;
  const dependsOnRunIds = stringArrayValue(waiting.depends_on_run_ids);
  if (dependsOnRunIds.length === 0) return null;
  return sanitizeEvidenceJson({
    ...waiting,
    status: "waiting",
    depends_on_run_ids: dependsOnRunIds,
    pending_run_ids: stringArrayValue(waiting.pending_run_ids),
  }) as Record<string, unknown>;
}

export function materializationEventStatus(
  item: RunMaterializationItemSummary,
): "succeeded" | "failed" | "warning" | "skipped" {
  if (item.status === "succeeded") return "succeeded";
  if (item.status === "skipped") return "skipped";
  if (item.status === "warning") return "warning";
  return "failed";
}

export function adapterFailureEnvelope(
  run: RunRecord,
  errorCode: string,
  message: string,
): RunAdapterResultEnvelope {
  const now = new Date().toISOString();
  return {
    adapter_type: run.adapter_type ?? "unknown",
    adapter_kind: "custom",
    success: false,
    output_text: "",
    output_json: { adapter_type: run.adapter_type ?? "unknown" },
    exit_code: 1,
    error_code: errorCode,
    error_message: redactEvidenceText(message),
    started_at: now,
    completed_at: now,
    usage: null,
    metadata_json: {
      adapter_type: run.adapter_type ?? "unknown",
    },
  };
}

export function adapterTimeoutEnvelope(
  run: RunRecord,
  timeoutMs: number,
): RunAdapterResultEnvelope {
  const now = new Date().toISOString();
  return {
    adapter_type: run.adapter_type ?? "unknown",
    adapter_kind: run.adapter_type === "claude_code" || run.adapter_type === "codex_cli" || run.adapter_type === "opencode"
      ? "local_cli"
      : "managed_api",
    success: false,
    output_text: "",
    output_json: { adapter_type: run.adapter_type ?? "unknown" },
    exit_code: 1,
    error_code: "adapter_timeout",
    error_message: `Runtime adapter timed out after ${timeoutMs}ms.`,
    started_at: now,
    completed_at: now,
    usage: null,
    metadata_json: {
      adapter_type: run.adapter_type ?? "unknown",
      timeout_ms: timeoutMs,
    },
  };
}

export function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  timeoutValue: T,
): Promise<T> {
  return new Promise((resolveValue, reject) => {
    const timer = setTimeout(() => resolveValue(timeoutValue), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolveValue(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

export function inputWithPreparedRuntime<T extends {
  prompt?: string | null;
  sandbox_cwd?: string | null;
  context_text?: string | null;
  adapter_config?: Record<string, unknown>;
  risk_level?: string | null;
}>(
  input: T,
  prepared: PreparedRuntimeInput,
): T {
  return {
    ...input,
    prompt: prepared.prompt,
    sandbox_cwd: prepared.sandbox_cwd,
    context_text: prepared.context_text,
    adapter_config: prepared.adapter_config,
    risk_level: prepared.risk_level ?? input.risk_level ?? null,
  };
}

export function toRunPreparationError(error: unknown, fallbackCode: string): RunPreparationError {
  if (error instanceof RunPreparationError) return error;
  const code = errorCodeValue(error) ?? fallbackCode;
  return new RunPreparationError(code, errorMessage(error));
}

export function errorCodeValue(error: unknown): string | null {
  if (error !== null && typeof error === "object") {
    const code = (error as { code?: unknown }).code;
    return typeof code === "string" && code ? code : null;
  }
  return null;
}

export function isTerminalRunStatus(status: string): status is RunTerminalStatus | "waiting_for_review" {
  return [
    "succeeded",
    "failed",
    "degraded",
    "cancelled",
    "orphaned",
    "waiting_for_review",
  ].includes(status);
}

export function isHardTerminalRunStatus(status: string): status is RunTerminalStatus {
  return ["succeeded", "failed", "degraded", "cancelled", "orphaned"].includes(status);
}

export function protocolRunStatus(status: string): RunStatus | "unknown" {
  if (
    [
      "queued",
      "running",
      "cancelling",
      "succeeded",
      "failed",
      "degraded",
      "cancelled",
      "orphaned",
      "waiting_for_review",
      "waiting_for_dependency",
    ].includes(status)
  ) {
    return status as RunStatus;
  }
  return "unknown";
}

export function summarizeOutput(value: string | undefined): string | null {
  if (!value) return null;
  return redactEvidenceText(value.length > 500 ? `${value.slice(0, 500)}...` : value);
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "run orchestration failed";
}

export function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringArrayValue(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value
    .map((item) => typeof item === "string" ? item.trim() : "")
    .filter((item) => item.length > 0))];
}
