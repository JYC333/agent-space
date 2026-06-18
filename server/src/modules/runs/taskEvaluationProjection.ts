export interface RunEvaluationProjectionInput {
  id: string;
  run_id: string;
  outcome_status: string;
  failure_layer: string | null;
  failure_reason_code: string | null;
  trajectory_status: string;
  evidence_json: unknown;
  evaluator_version: string;
}

export function taskScoreForOutcome(outcome: string): number | null {
  if (outcome === "passed") return 1;
  if (outcome === "partial") return 0.5;
  if (outcome === "failed") return 0;
  return null;
}

export function taskConfidenceForOutcome(outcome: string): number {
  if (outcome === "passed" || outcome === "failed") return 1;
  if (outcome === "partial") return 0.7;
  return 0.3;
}

export function taskRecommendationForOutcome(outcome: string): string {
  if (outcome === "passed") return "accept";
  if (outcome === "partial") return "review";
  if (outcome === "failed") return "retry";
  return "needs_evidence";
}

export function taskSummaryFromRunEvaluation(row: RunEvaluationProjectionInput): string {
  const outcome = row.outcome_status;
  const trajectory = row.trajectory_status;
  if (outcome === "passed" && trajectory === "acceptable") {
    return "Run evaluation passed with acceptable trajectory.";
  }
  if (outcome === "failed") {
    if (row.failure_layer && row.failure_reason_code) {
      return `Run evaluation failed at ${row.failure_layer}: ${row.failure_reason_code}.`;
    }
    if (row.failure_layer) return `Run evaluation failed at ${row.failure_layer}.`;
    if (row.failure_reason_code) return `Run evaluation failed: ${row.failure_reason_code}.`;
    return "Run evaluation failed.";
  }
  if (outcome === "partial") return `Run evaluation is partial; trajectory ${trajectory}.`;
  if (outcome === "unknown") return `Run evaluation is unknown; trajectory ${trajectory}.`;
  return `Run evaluation ${outcome}; trajectory ${trajectory}.`;
}

export function taskChecklistFromRunEvaluation(row: RunEvaluationProjectionInput): Record<string, unknown> {
  return {
    run_evaluation_id: row.id,
    run_id: row.run_id,
    outcome_status: row.outcome_status,
    trajectory_status: row.trajectory_status,
    failure_layer: row.failure_layer,
    failure_reason_code: row.failure_reason_code,
    evaluator_version: row.evaluator_version,
  };
}

export function taskKnownIssuesFromRunEvaluation(row: RunEvaluationProjectionInput): Record<string, unknown>[] {
  const issues: Record<string, unknown>[] = [];
  if (row.failure_layer || row.failure_reason_code) {
    issues.push({
      kind: "failure",
      failure_layer: row.failure_layer,
      failure_reason_code: row.failure_reason_code,
    });
  }
  const evidence = recordValue(row.evidence_json);
  collectIssueList(issues, recordValue(evidence.context).warnings, "context_warning", "code");
  const materialization = recordValue(evidence.materialization);
  collectIssueList(issues, materialization.codes, "materialization_code", "code");
  collectIssueList(issues, materialization.errors, "materialization_error", "error");
  collectIssueList(issues, materialization.code_patch_warnings, "materialization_warning", "code");
  const validation = recordValue(evidence.validation);
  if (typeof validation.status === "string" && validation.status) {
    issues.push({ kind: "validation_status", status: validation.status });
  }
  collectIssueList(issues, validation.signals, "validation_signal", "code");
  if (row.trajectory_status === "unsafe") {
    issues.push({ kind: "trajectory", status: "unsafe" });
  }
  return issues;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function collectIssueList(
  issues: Record<string, unknown>[],
  value: unknown,
  kind: string,
  field: string,
): void {
  if (!Array.isArray(value)) return;
  for (const item of value) {
    if (item) issues.push({ kind, [field]: item });
  }
}
