import { describe, expect, it } from "vitest";
import type { SourcePostProcessingRunOut } from "../src/modules/sources/postProcessing/repository";
import type { Queryable } from "../src/modules/routeUtils/common";
import {
  SourcePostProcessingRecoveryService,
  isRetryableSourcePostProcessingFailure,
  sourcePostProcessingFailureCode,
} from "../src/modules/sources/postProcessing/recoveryService";

function failedRun(errorJson: Record<string, unknown>): SourcePostProcessingRunOut {
  return {
    status: "failed",
    error_json: errorJson,
  } as SourcePostProcessingRunOut;
}

describe("source post-processing recovery failures", () => {
  it("retries transient provider network failures", () => {
    const run = failedRun({ agent_run_error_code: "provider_network_error" });

    expect(sourcePostProcessingFailureCode(run)).toBe("provider_network_error");
    expect(isRetryableSourcePostProcessingFailure(run)).toBe(true);
  });

  it("honors an explicitly retryable transport failure", () => {
    expect(isRetryableSourcePostProcessingFailure(failedRun({ retryable: true }))).toBe(true);
  });

  it("does not retry permanent structured-output failures", () => {
    const run = failedRun({ error_code: "structured_output_invalid" });

    expect(isRetryableSourcePostProcessingFailure(run)).toBe(false);
  });

  it("scopes classification coverage to the operation's research-question version", async () => {
    const calls: Array<{ sql: string; params: unknown[] }> = [];
    const db = {
      async query<T>(sql: string, params: unknown[] = []) {
        calls.push({ sql, params });
        return { rows: [{ classified: "1", failed_runs: "0", failed_run_summary: null, failed_run_error: null, pending_recovery_jobs: "0", failed_recovery_jobs: "0", failed_recovery_job_error: null }] as T[], rowCount: 1 };
      },
    } as Queryable;

    const result = await new SourcePostProcessingRecoveryService(db).ensureItemsProcessed({
      spaceId: "space-1", projectId: "project-1", channelIds: ["channel-1"], ruleIds: ["rule-1"],
      sourceItemIds: ["item-1"], operationId: "operation-1", researchQuestionVersion: 2,
    });

    expect(result).toEqual({ status: "ready" });
    expect(calls[0]?.sql).toContain("research_question_version=$8");
    expect(calls[0]?.params[7]).toBe(2);
  });
});
