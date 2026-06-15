import { randomUUID } from "node:crypto";
import type { ControlPlaneConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import {
  redactEvidenceText,
  sanitizeErrorJson,
  sanitizeEvidenceJson,
} from "./evidenceRedaction";

export interface QueryResult<Row> {
  rows: Row[];
  rowCount: number | null;
}

export interface Queryable {
  query<Row = Record<string, unknown>>(
    sql: string,
    params?: readonly unknown[],
  ): Promise<QueryResult<Row>>;
}

export interface RunRecord {
  id: string;
  space_id: string;
  agent_id: string;
  agent_version_id: string;
  run_type?: string;
  status: string;
  mode: string;
  prompt: string | null;
  instruction: string | null;
  workspace_id: string | null;
  session_id: string | null;
  project_id: string | null;
  adapter_type: string | null;
  model_provider_id: string | null;
  required_sandbox_level: string;
  trigger_origin: string;
  instructed_by_user_id?: string | null;
  error_message?: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface RunTerminalUpdate {
  run_id: string;
  space_id: string;
  status: "succeeded" | "failed" | "degraded" | "cancelled";
  output_text?: string | null;
  output_json?: unknown;
  error_json?: unknown;
  exit_code?: number | null;
  completed_at: string;
  usage_json?: unknown;
}

export interface RunEventRecord {
  id: string;
  space_id: string;
  run_id: string;
  event_index: number;
  event_type: string;
  status: string;
}

export interface RunChatResultRecord {
  id: string;
  space_id: string;
  status: string;
  output_json: unknown;
  error_json: unknown;
}

export interface RunEventInput {
  run_id: string;
  space_id: string;
  event_type: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped" | "warning" | "cancelled";
  step_id?: string | null;
  actor_id?: string | null;
  summary?: string | null;
  metadata_json?: unknown;
  error_code?: string | null;
  error_message?: string | null;
  workspace_id?: string | null;
  artifact_id?: string | null;
  proposal_id?: string | null;
  data_exposure_level?: string | null;
  trust_level?: string | null;
}

export interface RunStepRecord {
  id: string;
  space_id: string;
  run_id: string;
  step_index: number;
  step_type: string;
  status: string;
}

export interface RunStepInput {
  run_id: string;
  space_id: string;
  actor_id: string;
  step_type: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped" | "cancelled";
  title?: string | null;
  parent_step_id?: string | null;
  workspace_id?: string | null;
  session_id?: string | null;
  task_id?: string | null;
  artifact_id?: string | null;
  proposal_id?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  input_summary?: string | null;
  output_summary?: string | null;
  error_type?: string | null;
  error_message?: string | null;
  metadata_json?: unknown;
}

export class PgRunRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ControlPlaneConfig): PgRunRepository {
    if (!config.databaseUrl) {
      throw new Error("Run repository requires CONTROL_PLANE_DATABASE_URL");
    }
    return new PgRunRepository(getDbPool(config.databaseUrl));
  }

  async getRun(spaceId: string, runId: string): Promise<RunRecord | null> {
    const result = await this.db.query<RunRecord>(
      `SELECT id, space_id, agent_id, agent_version_id, run_type, status, mode,
              prompt, instruction, workspace_id, session_id, project_id,
              adapter_type, model_provider_id,
              required_sandbox_level, trigger_origin, instructed_by_user_id, error_message, started_at, ended_at
         FROM runs
        WHERE space_id = $1 AND id = $2`,
      [spaceId, runId],
    );
    return result.rows[0] ?? null;
  }

  async getChatRunResult(
    spaceId: string,
    runId: string,
  ): Promise<RunChatResultRecord | null> {
    const result = await this.db.query<RunChatResultRecord>(
      `SELECT id, space_id, status, output_json, error_json
         FROM runs
        WHERE space_id = $1 AND id = $2`,
      [spaceId, runId],
    );
    return result.rows[0] ?? null;
  }

  /**
   * Resolve the Actor row for run evidence, creating it when absent — the
   * TS port of Python `runs.steps.resolve_run_actor`: instructing user actor
   * first, then the `agent_run` job actor for job dispatch, otherwise the
   * `run_execution` system actor. `run_steps.actor_id` is a non-null Actor FK,
   * so worker/request identifiers must never be written there directly.
   */
  async resolveRunActorId(
    run: Pick<RunRecord, "space_id" | "instructed_by_user_id">,
    commandSource: string,
  ): Promise<string> {
    if (run.instructed_by_user_id) {
      const existing = await this.db.query<{ id: string }>(
        `SELECT id FROM actors
          WHERE actor_type = 'user' AND user_id = $1 AND space_id = $2
            AND status = 'active'
          LIMIT 1`,
        [run.instructed_by_user_id, run.space_id],
      );
      if (existing.rows[0]) return existing.rows[0].id;
      const created = await this.db.query<{ id: string }>(
        `INSERT INTO actors (
            id, space_id, actor_type, user_id, agent_id, service_name,
            display_name, status, metadata_json, created_at, updated_at
         )
         VALUES ($1, $2, 'user', $3, NULL, NULL, NULL, 'active', '{}'::jsonb, $4, $4)
         RETURNING id`,
        [
          randomUUID(),
          run.space_id,
          run.instructed_by_user_id,
          new Date().toISOString(),
        ],
      );
      const row = created.rows[0];
      if (!row) throw new Error("user actor insert returned no row");
      return row.id;
    }

    const actorType = commandSource === "job" ? "job" : "system";
    const serviceName = commandSource === "job" ? "agent_run" : "run_execution";
    const existing = await this.db.query<{ id: string }>(
      `SELECT id FROM actors
        WHERE actor_type = $1 AND service_name = $2 AND space_id = $3
          AND status = 'active'
        LIMIT 1`,
      [actorType, serviceName, run.space_id],
    );
    if (existing.rows[0]) return existing.rows[0].id;
    const created = await this.db.query<{ id: string }>(
      `INSERT INTO actors (
          id, space_id, actor_type, user_id, agent_id, service_name,
          display_name, status, metadata_json, created_at, updated_at
       )
       VALUES ($1, $2, $3, NULL, NULL, $4, NULL, 'active', '{}'::jsonb, $5, $5)
       RETURNING id`,
      [randomUUID(), run.space_id, actorType, serviceName, new Date().toISOString()],
    );
    const row = created.rows[0];
    if (!row) throw new Error(`${actorType} actor insert returned no row`);
    return row.id;
  }

  async markRunRunning(input: {
    run_id: string;
    space_id: string;
    started_at: string;
    required_sandbox_level?: string | null;
  }): Promise<RunRecord | null> {
    const result = await this.db.query<RunRecord>(
      `UPDATE runs
          SET status = 'running',
              started_at = $3,
              updated_at = $3,
              required_sandbox_level = COALESCE($4, required_sandbox_level)
        WHERE space_id = $1 AND id = $2 AND status = 'queued'
        RETURNING id, space_id, agent_id, agent_version_id, run_type, status, mode,
                  prompt, instruction, workspace_id, session_id, project_id,
                  adapter_type, model_provider_id,
                  required_sandbox_level, trigger_origin, instructed_by_user_id, error_message, started_at, ended_at`,
      [
        input.space_id,
        input.run_id,
        input.started_at,
        input.required_sandbox_level ?? null,
      ],
    );
    return result.rows[0] ?? null;
  }

  async updateRunSandboxLevel(input: {
    run_id: string;
    space_id: string;
    required_sandbox_level: string;
  }): Promise<void> {
    await this.db.query(
      `UPDATE runs
          SET required_sandbox_level = $3, updated_at = now()
        WHERE space_id = $1 AND id = $2 AND status = 'running'`,
      [input.space_id, input.run_id, input.required_sandbox_level],
    );
  }

  async markRunTerminal(input: RunTerminalUpdate): Promise<RunRecord | null> {
    // The public run read model surfaces output through output_json.output_text
    // (Python parity), so the terminal write folds it in before sanitization.
    const outputJson = sanitizeEvidenceJson({
      ...(recordValue(input.output_json)),
      ...(input.output_text ? { output_text: input.output_text } : {}),
    });
    const errorJson = sanitizeErrorJson(input.error_json ?? {});
    const usageJson = sanitizeEvidenceJson(input.usage_json ?? {});
    const result = await this.db.query<RunRecord>(
      `UPDATE runs
          SET status = $3,
              output_json = $4::jsonb,
              error_json = $5::jsonb,
              exit_code = $6,
              usage_json = $7::jsonb,
              ended_at = $8,
              updated_at = $8,
              error_message = $9
        WHERE space_id = $1 AND id = $2
          AND status NOT IN ('succeeded', 'failed', 'degraded', 'cancelled')
        RETURNING id, space_id, agent_id, agent_version_id, run_type, status, mode,
                  prompt, instruction, workspace_id, session_id, project_id,
                  adapter_type, model_provider_id,
                  required_sandbox_level, trigger_origin, instructed_by_user_id, error_message, started_at, ended_at`,
      [
        input.space_id,
        input.run_id,
        input.status,
        JSON.stringify(outputJson),
        JSON.stringify(errorJson),
        input.exit_code ?? null,
        JSON.stringify(usageJson),
        input.completed_at,
        redactEvidenceText(extractErrorMessage(errorJson)),
      ],
    );
    return result.rows[0] ?? null;
  }

  async appendRunEvent(input: RunEventInput): Promise<RunEventRecord> {
    // $1/$2 appear both as inserted values (deduced as the varchar column
    // type) and in the scalar subquery comparison (deduced as text via the
    // text equality operator). Without the explicit ::varchar casts PostgreSQL
    // fails with "inconsistent types deduced for parameter".
    const result = await this.db.query<RunEventRecord>(
      `INSERT INTO run_events (
          id, space_id, run_id, event_index, step_id, actor_id, event_type,
          status, summary, error_code, error_message, workspace_id,
          artifact_id, proposal_id, data_exposure_level,
          trust_level, metadata_json, created_at
       )
       VALUES ($3, $1, $2,
               (SELECT COALESCE(MAX(event_index) + 1, 0)
                  FROM run_events
                 WHERE space_id = $1::varchar AND run_id = $2::varchar),
               $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
               $16::jsonb, $17)
       RETURNING id, space_id, run_id, event_index, event_type, status`,
      [
        input.space_id,
        input.run_id,
        randomUUID(),
        input.step_id ?? null,
        input.actor_id ?? null,
        input.event_type,
        input.status,
        redactEvidenceText(input.summary),
        input.error_code ?? null,
        redactEvidenceText(input.error_message),
        input.workspace_id ?? null,
        input.artifact_id ?? null,
        input.proposal_id ?? null,
        input.data_exposure_level ?? null,
        input.trust_level ?? null,
        JSON.stringify(sanitizeEvidenceJson(input.metadata_json ?? {})),
        new Date().toISOString(),
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("RunEvent append returned no row");
    return row;
  }

  async createRunStep(input: RunStepInput): Promise<RunStepRecord> {
    // Same ::varchar casts as appendRunEvent — see the comment there.
    const result = await this.db.query<RunStepRecord>(
      `INSERT INTO run_steps (
          id, space_id, run_id, parent_step_id, actor_id, step_index,
          step_type, status, title, workspace_id, session_id, task_id,
          artifact_id, proposal_id, started_at, ended_at,
          input_summary, output_summary, error_type, error_message,
          metadata_json, created_at, updated_at
       )
       VALUES ($3, $1, $2, $4, $5,
               (SELECT COALESCE(MAX(step_index) + 1, 0)
                  FROM run_steps
                 WHERE space_id = $1::varchar AND run_id = $2::varchar),
               $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
               $17, $18, $19, $20::jsonb, $21, $21)
       RETURNING id, space_id, run_id, step_index, step_type, status`,
      [
        input.space_id,
        input.run_id,
        randomUUID(),
        input.parent_step_id ?? null,
        input.actor_id,
        input.step_type,
        input.status,
        input.title ?? null,
        input.workspace_id ?? null,
        input.session_id ?? null,
        input.task_id ?? null,
        input.artifact_id ?? null,
        input.proposal_id ?? null,
        input.started_at ?? null,
        input.ended_at ?? null,
        redactEvidenceText(input.input_summary),
        redactEvidenceText(input.output_summary),
        input.error_type ?? null,
        redactEvidenceText(input.error_message),
        JSON.stringify(sanitizeEvidenceJson(input.metadata_json ?? {})),
        new Date().toISOString(),
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("RunStep insert returned no row");
    return row;
  }

  async updateRunStepStatus(input: {
    step_id: string;
    run_id: string;
    space_id: string;
    status: "succeeded" | "failed" | "skipped" | "cancelled";
    ended_at: string;
    output_summary?: string | null;
    error_type?: string | null;
    error_message?: string | null;
  }): Promise<boolean> {
    const result = await this.db.query(
      `UPDATE run_steps
          SET status = $4,
              ended_at = $5,
              output_summary = COALESCE($6, output_summary),
              error_type = COALESCE($7, error_type),
              error_message = COALESCE($8, error_message),
              updated_at = $5
        WHERE id = $1 AND run_id = $2 AND space_id = $3`,
      [
        input.step_id,
        input.run_id,
        input.space_id,
        input.status,
        input.ended_at,
        redactEvidenceText(input.output_summary),
        input.error_type ?? null,
        redactEvidenceText(input.error_message),
      ],
    );
    return (result.rowCount ?? 0) > 0;
  }

  async tryAcquireExecutionLock(input: {
    run_id: string;
    worker_id: string;
    job_id?: string | null;
  }): Promise<boolean> {
    const result = await this.db.query(
      `INSERT INTO run_execution_locks (run_id, locked_at, worker_id, job_id)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (run_id) DO NOTHING`,
      [input.run_id, new Date().toISOString(), input.worker_id, input.job_id ?? null],
    );
    return (result.rowCount ?? 0) === 1;
  }

  async releaseExecutionLock(runId: string): Promise<void> {
    await this.db.query("DELETE FROM run_execution_locks WHERE run_id = $1", [runId]);
  }
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function extractErrorMessage(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const message = record.error_message ?? record.error_text ?? record.message;
  return typeof message === "string" ? message : null;
}
