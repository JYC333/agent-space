import {
  type PgRunRepository,
  type RunEvaluationRecord,
  type RunFinalizationRecord,
  type RunRecord,
} from "./repository";
import type { EvolutionRunEvaluationForSolidifier } from "../evolution/solidifier";

export const RUN_FINALIZER_VERSION = "post_run_finalization.v1";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "degraded", "cancelled"]);

const EXACT_ERROR_CODE_MAP: Record<string, { layer: string; reason: string }> = {
  context_snapshot_population_failed: {
    layer: "context",
    reason: "context_snapshot_population_failed",
  },
  sandbox_required: { layer: "sandbox", reason: "sandbox_required" },
  critical_runtime_requires_unimplemented_one_shot_docker: {
    layer: "sandbox",
    reason: "critical_runtime_requires_unimplemented_one_shot_docker",
  },
  file_access_adapter_requires_worktree_policy: {
    layer: "policy",
    reason: "file_access_adapter_requires_worktree_policy",
  },
  credentials_missing: { layer: "policy", reason: "credentials_missing" },
  adapter_runtime_error: { layer: "runtime", reason: "adapter_runtime_error" },
  runtime_removed: { layer: "runtime", reason: "runtime_removed" },
  duplicate_execution: { layer: "orchestration", reason: "duplicate_execution" },
  run_cancelled: { layer: "orchestration", reason: "run_cancelled" },
  validation_failed: { layer: "validation", reason: "validation_failed" },
  validation_command_failed: {
    layer: "validation",
    reason: "validation_command_failed",
  },
  code_patch_validation_failed: {
    layer: "validation",
    reason: "code_patch_validation_failed",
  },
  code_patch_collection_error: {
    layer: "tool",
    reason: "code_patch_collection_error",
  },
  produced_artifact_ingestion_error: {
    layer: "tool",
    reason: "produced_artifact_ingestion_error",
  },
  runtime_output_artifact: { layer: "tool", reason: "runtime_output_artifact" },
  output_artifact_materialization_error: {
    layer: "tool",
    reason: "output_artifact_materialization_error",
  },
  output_proposal_materialization_error: {
    layer: "tool",
    reason: "output_proposal_materialization_error",
  },
  output_activity_materialization_error: {
    layer: "tool",
    reason: "output_activity_materialization_error",
  },
};

export class RunNotFoundError extends Error {}
export class NonTerminalRunError extends Error {}

export interface EvolutionRunEvaluationSolidifier {
  solidifyFromRunEvaluation(
    evaluation: EvolutionRunEvaluationForSolidifier,
  ): Promise<{ id: string } | null>;
}

export class PostRunFinalizationService {
  constructor(
    private readonly repository: PgRunRepository,
    private readonly evolutionSolidifier?: EvolutionRunEvaluationSolidifier,
  ) {}

  async finalize(runId: string, spaceId: string): Promise<RunFinalizationRecord> {
    const run = await this.repository.getRun(spaceId, runId);
    if (!run) {
      throw new RunNotFoundError(`Run '${runId}' not found in space '${spaceId}'`);
    }
    if (!TERMINAL_STATUSES.has(run.status)) {
      throw new NonTerminalRunError(
        `Run '${runId}' is not terminal (status='${run.status}'); finalization requires a terminal status: succeeded, failed, degraded, or cancelled.`,
      );
    }

    const existing = await this.repository.getRunFinalizationByVersion(
      spaceId,
      runId,
      RUN_FINALIZER_VERSION,
    );
    if (existing) return existing;

    if (run.status === "succeeded") {
      // Commit the automation intake watermark proposed at fire time. Only
      // successful runs advance the cursor; the advance itself is monotonic,
      // so a retried finalization cannot regress or double-apply it.
      await this.repository.advanceAutomationIntakeCursorForRun(spaceId, runId);
    }

    const evaluation = await this.evaluate(run);
    const now = new Date().toISOString();
    const taskBridge = await this.repository.bridgeTaskEvaluationForRunEvaluation(
      spaceId,
      evaluation,
    );
    const evolutionExperience = await this.evolutionSolidifier?.solidifyFromRunEvaluation(evaluation) ?? null;
    const skippedReasons = taskBridge.skippedReason ? [taskBridge.skippedReason] : [];
    const finalization = await this.repository.insertRunFinalization({
      space_id: spaceId,
      run_id: runId,
      finalizer_version: RUN_FINALIZER_VERSION,
      status: "completed",
      run_evaluation_id: evaluation.id,
      task_evaluation_id: taskBridge.taskEvaluationId,
      outcome_status: evaluation.outcome_status,
      failure_layer: evaluation.failure_layer,
      failure_reason_code: evaluation.failure_reason_code,
      trajectory_status: evaluation.trajectory_status,
      skipped_reasons_json: skippedReasons,
      metadata_json: {
        finalizer_version: RUN_FINALIZER_VERSION,
        evolution_experience_id: evolutionExperience?.id ?? null,
      },
      finalized_at: now,
      created_at: now,
    });
    try {
      await this.repository.appendRunEvent({
        run_id: runId,
        space_id: spaceId,
        event_type: "run_finalized",
        status: "succeeded",
        metadata_json: {
          run_finalization_id: finalization.id,
          run_evaluation_id: evaluation.id,
          task_evaluation_id: taskBridge.taskEvaluationId,
          evolution_experience_id: evolutionExperience?.id ?? null,
          skipped_reasons: skippedReasons,
          finalizer_version: RUN_FINALIZER_VERSION,
        },
      });
    } catch {
      // RunEvent is an append-only audit log. A missed audit event must not
      // turn a completed finalization into a failed one.
    }
    return finalization;
  }

  private async evaluate(run: RunRecord): Promise<RunEvaluationRecord> {
    const [steps, events] = await Promise.all([
      this.repository.listRunSteps(run.space_id, run.id),
      this.repository.listRunEvents(run.space_id, run.id),
    ]);
    const eventErrorCodes = events
      .map((event) => event.error_code)
      .filter((code): code is string => Boolean(code));
    const stepErrorCodes = steps
      .filter((step) => step.status === "failed" && step.error_type)
      .map((step) => step.error_type as string);
    const errorCodes = dedupe([
      ...eventErrorCodes,
      ...collectErrorCodes(run.error_json),
      ...collectErrorCodes(run.output_json),
      ...stepErrorCodes,
    ]);
    const mapped = mapFailure(errorCodes);
    const outcome = outcomeForRun(run, mapped.reason);
    const now = new Date().toISOString();
    return this.repository.insertRunEvaluation({
      space_id: run.space_id,
      run_id: run.id,
      outcome_status: outcome.outcome_status,
      failure_layer: mapped.layer,
      failure_reason_code: mapped.reason,
      trajectory_status: outcome.trajectory_status,
      evidence_json: {
        run_status: run.status,
        event_count: events.length,
        step_count: steps.length,
        event_types: events.map((event) => event.event_type),
        error_codes: errorCodes,
        required_sandbox_level: run.required_sandbox_level,
        adapter_type: run.adapter_type,
      },
      rule_trace_json: [
        {
          rule: "ts_post_run_finalization.v1",
          terminal_status: run.status,
          mapped_failure_reason: mapped.reason,
        },
      ],
      notes: null,
      evaluated_at: now,
    });
  }
}

function outcomeForRun(
  run: RunRecord,
  failureReason: string | null,
): { outcome_status: string; trajectory_status: string } {
  if (run.status === "succeeded") {
    return failureReason
      ? { outcome_status: "partial", trajectory_status: "incomplete" }
      : { outcome_status: "passed", trajectory_status: "acceptable" };
  }
  if (run.status === "degraded") {
    return { outcome_status: "partial", trajectory_status: "incomplete" };
  }
  if (run.status === "cancelled") {
    return { outcome_status: "failed", trajectory_status: "incomplete" };
  }
  return { outcome_status: "failed", trajectory_status: "incomplete" };
}

function mapFailure(errorCodes: string[]): { layer: string | null; reason: string | null } {
  for (const code of errorCodes) {
    const mapped = EXACT_ERROR_CODE_MAP[code];
    if (mapped) return { layer: mapped.layer, reason: mapped.reason };
  }
  if (errorCodes.length > 0) return { layer: "unknown", reason: errorCodes[0] };
  return { layer: null, reason: null };
}

function collectErrorCodes(value: unknown): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const record = value as Record<string, unknown>;
  const codes = [record.error_code, record.code].filter(
    (code): code is string => typeof code === "string" && code.length > 0,
  );
  return codes;
}

function dedupe(values: string[]): string[] {
  return [...new Set(values)];
}
