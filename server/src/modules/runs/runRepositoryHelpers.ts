import { isVendorCliAdapter } from "../runtimeAdapters/specs";
import {
  RunCreateValidationError,
  type RunCreateInput,
} from "./runRepositoryTypes";

export function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function trimmed(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function extractErrorMessage(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const message = record.error_message ?? record.error_text ?? record.message;
  return typeof message === "string" ? message : null;
}

export function addOptionalFilter(
  clauses: string[],
  params: unknown[],
  column: string,
  value: string | null | undefined,
): void {
  if (value == null || value === "") return;
  params.push(value);
  clauses.push(`${column} = $${params.length}`);
}

export function validateRunCreateInput(input: RunCreateInput): void {
  assertOneOf(input.mode, ["live", "dry_run"], "mode");
  assertOneOf(
    input.run_type,
    ["agent", "system", "workflow", "validation", "reflection", "export", "evolution"],
    "run_type",
  );
  assertOneOf(input.trigger_origin, ["manual", "automation", "job", "system"], "trigger_origin");
}

export function requiredSandboxLevelForRun(
  adapterType: string | null | undefined,
  workspaceId: string | null | undefined,
): string {
  if (!isVendorCliAdapter(adapterType)) return "none";
  return workspaceId ? "worktree" : "ephemeral";
}

function assertOneOf(value: string, allowed: readonly string[], field: string): void {
  if (allowed.includes(value)) return;
  throw new RunCreateValidationError(
    `Invalid ${field} '${value}'. Must be one of: ${allowed.slice().sort().join(", ")}`,
  );
}
