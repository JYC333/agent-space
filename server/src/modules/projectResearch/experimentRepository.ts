import { randomUUID } from "node:crypto";
import { posix as pathPosix } from "node:path";
import {
  HttpError,
  dateIso,
  numberValue,
  objectValue,
  optionalString,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";
import { assertProjectReadable, assertProjectWriter, assertWorkspaceLinkedToProject } from "../projects/access";

const CAMPAIGN_STATUSES = new Set(["draft", "active", "paused", "completed", "archived"]);
const RUN_DECISIONS = new Set(["keep", "discard", "crash"]);

function requiredDateIso(value: unknown): string {
  return dateIso(value) ?? new Date(0).toISOString();
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value
        .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        .map((item) => item.trim())
    : [];
}

function jsonStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function enumValue(value: unknown, allowed: Set<string>, field: string): string | null {
  const text = optionalString(value);
  if (!text) return null;
  if (!allowed.has(text)) throw new HttpError(422, `${field} must be one of ${[...allowed].join(", ")}`);
  return text;
}

function scopePathArray(value: unknown, field: string): string[] {
  const paths: string[] = [];
  const seen = new Set<string>();
  for (const raw of stringArray(value)) {
    if (raw.includes("\0") || raw.includes("\\") || /^[A-Za-z]:/.test(raw) || pathPosix.isAbsolute(raw)) {
      throw new HttpError(422, `${field} entries must be relative POSIX workspace paths`);
    }
    const normalized = pathPosix.normalize(raw);
    if (normalized === "." || normalized === ".." || normalized.startsWith("../")) {
      throw new HttpError(422, `${field} entries must stay inside the workspace`);
    }
    if (normalized.includes("*")) {
      throw new HttpError(422, `${field} entries must be literal files or directories, not glob patterns`);
    }
    if (!seen.has(normalized)) {
      seen.add(normalized);
      paths.push(normalized);
    }
  }
  return paths;
}

function scopeContains(parent: string, child: string): boolean {
  return child === parent || child.startsWith(`${parent}/`);
}

/** Rejects overlap between the editable and protected scope declarations — a path cannot be both or nested under both. */
function assertScopesDoNotOverlap(editable: string[], protectedPaths: string[]): void {
  for (const editablePath of editable) {
    for (const protectedPath of protectedPaths) {
      if (scopeContains(editablePath, protectedPath) || scopeContains(protectedPath, editablePath)) {
        throw new HttpError(422, `Path '${editablePath}' overlaps protected scope '${protectedPath}'`);
      }
    }
  }
}

interface CampaignRow {
  id: string;
  project_id: string;
  workspace_id: string;
  name: string;
  research_question: string | null;
  hypothesis_scope: string | null;
  status: string;
  editable_scope_json: unknown;
  protected_scope_json: unknown;
  setup_commands_json: unknown;
  run_command: string | null;
  metric_parser_json: unknown;
  time_budget_seconds: number | null;
  timeout_seconds: number | null;
  resource_budget_json: unknown;
  baseline_run_id: string | null;
  best_run_id: string | null;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

const CAMPAIGN_COLUMNS = `
  id, project_id, workspace_id, name, research_question, hypothesis_scope, status,
  editable_scope_json, protected_scope_json, setup_commands_json, run_command,
  metric_parser_json, time_budget_seconds, timeout_seconds, resource_budget_json,
  baseline_run_id, best_run_id, created_by_user_id, created_at, updated_at
`;

function campaignOut(row: CampaignRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    workspace_id: row.workspace_id,
    name: row.name,
    research_question: row.research_question,
    hypothesis_scope: row.hypothesis_scope,
    status: row.status,
    editable_scope: jsonStringArray(row.editable_scope_json),
    protected_scope: jsonStringArray(row.protected_scope_json),
    setup_commands: jsonStringArray(row.setup_commands_json),
    run_command: row.run_command,
    metric_parser: objectValue(row.metric_parser_json),
    time_budget_seconds: row.time_budget_seconds,
    timeout_seconds: row.timeout_seconds,
    resource_budget: objectValue(row.resource_budget_json),
    baseline_run_id: row.baseline_run_id,
    best_run_id: row.best_run_id,
    created_by_user_id: row.created_by_user_id,
    created_at: requiredDateIso(row.created_at),
    updated_at: requiredDateIso(row.updated_at),
  };
}

interface RunRow {
  id: string;
  campaign_id: string;
  run_id: string | null;
  workspace_id: string;
  is_baseline: boolean;
  hypothesis: string | null;
  patch_summary: string | null;
  commit_ref: string | null;
  status: string;
  metrics_json: unknown;
  primary_metric_name: string | null;
  primary_metric_value: number | null;
  decision_reason: string | null;
  artifact_ids_json: unknown;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

const RUN_COLUMNS = `
  id, campaign_id, run_id, workspace_id, is_baseline, hypothesis, patch_summary, commit_ref,
  status, metrics_json, primary_metric_name, primary_metric_value, decision_reason,
  artifact_ids_json, created_by_user_id, created_at, updated_at
`;

function runOut(row: RunRow): Record<string, unknown> {
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    run_id: row.run_id,
    workspace_id: row.workspace_id,
    is_baseline: row.is_baseline,
    hypothesis: row.hypothesis,
    patch_summary: row.patch_summary,
    commit_ref: row.commit_ref,
    status: row.status,
    metrics: objectValue(row.metrics_json),
    primary_metric_name: row.primary_metric_name,
    primary_metric_value: row.primary_metric_value,
    decision_reason: row.decision_reason,
    artifact_ids: jsonStringArray(row.artifact_ids_json),
    created_by_user_id: row.created_by_user_id,
    created_at: requiredDateIso(row.created_at),
    updated_at: requiredDateIso(row.updated_at),
  };
}

interface ProvenanceRow {
  id: string;
  project_id: string;
  campaign_id: string | null;
  experiment_key: string;
  planned_summary: string | null;
  executed_summary: string | null;
  negative_results: string | null;
  limitations: string | null;
  repro_lock_json: unknown;
  linked_artifact_ids_json: unknown;
  linked_run_ids_json: unknown;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

const PROVENANCE_COLUMNS = `
  id, project_id, campaign_id, experiment_key, planned_summary, executed_summary,
  negative_results, limitations, repro_lock_json, linked_artifact_ids_json, linked_run_ids_json,
  created_by_user_id, created_at, updated_at
`;

function provenanceOut(row: ProvenanceRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    campaign_id: row.campaign_id,
    experiment_key: row.experiment_key,
    planned_summary: row.planned_summary,
    executed_summary: row.executed_summary,
    negative_results: row.negative_results,
    limitations: row.limitations,
    repro_lock: objectValue(row.repro_lock_json),
    linked_artifact_ids: jsonStringArray(row.linked_artifact_ids_json),
    linked_run_ids: jsonStringArray(row.linked_run_ids_json),
    created_by_user_id: row.created_by_user_id,
    created_at: requiredDateIso(row.created_at),
    updated_at: requiredDateIso(row.updated_at),
  };
}

export class ProjectExperimentRepository {
  constructor(private readonly db: Queryable) {}

  // --- Campaigns ---------------------------------------------------------

  async listCampaigns(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const result = await this.db.query<CampaignRow>(
      `SELECT ${CAMPAIGN_COLUMNS} FROM project_experiment_campaigns
        WHERE space_id = $1 AND project_id = $2
        ORDER BY created_at DESC, id ASC`,
      [identity.spaceId, projectId],
    );
    return result.rows.map(campaignOut);
  }

  async createCampaign(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const workspaceId = optionalString(body.workspace_id);
    if (!workspaceId) throw new HttpError(422, "workspace_id is required");
    await assertWorkspaceLinkedToProject(this.db, identity.spaceId, projectId, workspaceId);
    const name = optionalString(body.name);
    if (!name) throw new HttpError(422, "name is required");
    const editableScope = scopePathArray(body.editable_scope, "editable_scope");
    const protectedScope = scopePathArray(body.protected_scope, "protected_scope");
    assertScopesDoNotOverlap(editableScope, protectedScope);
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO project_experiment_campaigns (
         id, space_id, project_id, workspace_id, name, research_question, hypothesis_scope, status,
         editable_scope_json, protected_scope_json, setup_commands_json, run_command,
         metric_parser_json, time_budget_seconds, timeout_seconds, resource_budget_json,
         created_by_user_id, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6, $7, 'draft',
         $8::jsonb, $9::jsonb, $10::jsonb, $11,
         $12::jsonb, $13, $14, $15::jsonb,
         $16, $17, $17
       )`,
      [
        id,
        identity.spaceId,
        projectId,
        workspaceId,
        name,
        optionalString(body.research_question),
        optionalString(body.hypothesis_scope),
        JSON.stringify(editableScope),
        JSON.stringify(protectedScope),
        JSON.stringify(stringArray(body.setup_commands)),
        optionalString(body.run_command),
        JSON.stringify(objectValue(body.metric_parser)),
        numberValue(body.time_budget_seconds),
        numberValue(body.timeout_seconds),
        JSON.stringify(objectValue(body.resource_budget)),
        identity.userId,
        now,
      ],
    );
    const row = await this.campaignRow(identity.spaceId, projectId, id);
    if (!row) throw new HttpError(500, "Failed to create experiment campaign");
    return campaignOut(row);
  }

  async updateCampaign(
    identity: SpaceUserIdentity,
    projectId: string,
    campaignId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const current = await this.campaignRow(identity.spaceId, projectId, campaignId);
    if (!current) throw new HttpError(404, "Experiment campaign not found");
    const status = body.status === undefined ? current.status : enumValue(body.status, CAMPAIGN_STATUSES, "status") ?? current.status;
    const editableScope = body.editable_scope === undefined
      ? scopePathArray(current.editable_scope_json, "editable_scope")
      : scopePathArray(body.editable_scope, "editable_scope");
    const protectedScope = body.protected_scope === undefined
      ? scopePathArray(current.protected_scope_json, "protected_scope")
      : scopePathArray(body.protected_scope, "protected_scope");
    assertScopesDoNotOverlap(editableScope, protectedScope);
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE project_experiment_campaigns
          SET status = $4, research_question = $5, hypothesis_scope = $6,
              editable_scope_json = $7::jsonb, protected_scope_json = $8::jsonb,
              setup_commands_json = $9::jsonb, run_command = $10, metric_parser_json = $11::jsonb,
              time_budget_seconds = $12, timeout_seconds = $13, resource_budget_json = $14::jsonb,
              updated_at = $15
        WHERE space_id = $1 AND project_id = $2 AND id = $3`,
      [
        identity.spaceId,
        projectId,
        campaignId,
        status,
        body.research_question === undefined ? current.research_question : optionalString(body.research_question),
        body.hypothesis_scope === undefined ? current.hypothesis_scope : optionalString(body.hypothesis_scope),
        JSON.stringify(editableScope),
        JSON.stringify(protectedScope),
        JSON.stringify(body.setup_commands === undefined ? jsonStringArray(current.setup_commands_json) : stringArray(body.setup_commands)),
        body.run_command === undefined ? current.run_command : optionalString(body.run_command),
        JSON.stringify(body.metric_parser === undefined ? objectValue(current.metric_parser_json) : objectValue(body.metric_parser)),
        body.time_budget_seconds === undefined ? current.time_budget_seconds : numberValue(body.time_budget_seconds),
        body.timeout_seconds === undefined ? current.timeout_seconds : numberValue(body.timeout_seconds),
        JSON.stringify(body.resource_budget === undefined ? objectValue(current.resource_budget_json) : objectValue(body.resource_budget)),
        now,
      ],
    );
    const updated = await this.campaignRow(identity.spaceId, projectId, campaignId);
    if (!updated) throw new HttpError(500, "Failed to update experiment campaign");
    return campaignOut(updated);
  }

  private async campaignRow(spaceId: string, projectId: string, campaignId: string): Promise<CampaignRow | null> {
    const result = await this.db.query<CampaignRow>(
      `SELECT ${CAMPAIGN_COLUMNS} FROM project_experiment_campaigns WHERE space_id = $1 AND project_id = $2 AND id = $3 LIMIT 1`,
      [spaceId, projectId, campaignId],
    );
    return result.rows[0] ?? null;
  }

  private async requireCampaign(spaceId: string, projectId: string, campaignId: string): Promise<CampaignRow> {
    const row = await this.campaignRow(spaceId, projectId, campaignId);
    if (!row) throw new HttpError(404, "Experiment campaign not found");
    return row;
  }

  // --- Runs ---------------------------------------------------------

  async listRuns(identity: SpaceUserIdentity, projectId: string, campaignId: string): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    await this.requireCampaign(identity.spaceId, projectId, campaignId);
    const result = await this.db.query<RunRow>(
      `SELECT ${RUN_COLUMNS} FROM project_experiment_runs WHERE space_id = $1 AND campaign_id = $2 ORDER BY created_at DESC, id ASC`,
      [identity.spaceId, campaignId],
    );
    return result.rows.map(runOut);
  }

  async createRun(
    identity: SpaceUserIdentity,
    projectId: string,
    campaignId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const campaign = await this.requireCampaign(identity.spaceId, projectId, campaignId);
    const isBaseline = body.is_baseline === true;
    if (!isBaseline && !campaign.baseline_run_id) {
      throw new HttpError(422, "A baseline run must be created (and kept) before any other campaign run");
    }
    const runId = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO project_experiment_runs (
         id, space_id, campaign_id, run_id, workspace_id, is_baseline, hypothesis, patch_summary,
         commit_ref, status, created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'queued', $10, $11, $11)`,
      [
        runId,
        identity.spaceId,
        campaignId,
        optionalString(body.run_id),
        campaign.workspace_id,
        isBaseline,
        optionalString(body.hypothesis),
        optionalString(body.patch_summary),
        optionalString(body.commit_ref),
        identity.userId,
        now,
      ],
    );
    const row = await this.runRow(identity.spaceId, campaignId, runId);
    if (!row) throw new HttpError(500, "Failed to create experiment run");
    return runOut(row);
  }

  async decideRun(
    identity: SpaceUserIdentity,
    projectId: string,
    campaignId: string,
    runId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    await this.requireCampaign(identity.spaceId, projectId, campaignId);
    const run = await this.runRow(identity.spaceId, campaignId, runId);
    if (!run) throw new HttpError(404, "Experiment run not found");
    const decision = enumValue(body.decision, RUN_DECISIONS, "decision");
    if (!decision) throw new HttpError(422, "decision is required and must be one of keep, discard, crash");
    const metrics = objectValue(body.metrics);
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE project_experiment_runs
          SET status = $4, metrics_json = $5::jsonb, primary_metric_name = $6, primary_metric_value = $7,
              decision_reason = $8, artifact_ids_json = $9::jsonb, updated_at = $10
        WHERE space_id = $1 AND campaign_id = $2 AND id = $3`,
      [
        identity.spaceId,
        campaignId,
        runId,
        decision,
        JSON.stringify(metrics),
        optionalString(body.primary_metric_name),
        numberValue(body.primary_metric_value),
        optionalString(body.reason),
        JSON.stringify(stringArray(body.artifact_ids)),
        now,
      ],
    );
    if (decision === "keep") {
      if (run.is_baseline) {
        await this.db.query(
          `UPDATE project_experiment_campaigns SET baseline_run_id = $3, updated_at = $4 WHERE id = $1 AND space_id = $2`,
          [campaignId, identity.spaceId, runId, now],
        );
      }
      if (body.mark_as_best === true) {
        await this.db.query(
          `UPDATE project_experiment_campaigns SET best_run_id = $3, updated_at = $4 WHERE id = $1 AND space_id = $2`,
          [campaignId, identity.spaceId, runId, now],
        );
      }
    }
    const updated = await this.runRow(identity.spaceId, campaignId, runId);
    if (!updated) throw new HttpError(500, "Failed to decide experiment run");
    return runOut(updated);
  }

  private async runRow(spaceId: string, campaignId: string, runId: string): Promise<RunRow | null> {
    const result = await this.db.query<RunRow>(
      `SELECT ${RUN_COLUMNS} FROM project_experiment_runs WHERE space_id = $1 AND campaign_id = $2 AND id = $3 LIMIT 1`,
      [spaceId, campaignId, runId],
    );
    return result.rows[0] ?? null;
  }

  // --- Provenance ---------------------------------------------------------

  async listProvenance(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const result = await this.db.query<ProvenanceRow>(
      `SELECT ${PROVENANCE_COLUMNS} FROM project_experiment_provenance
        WHERE space_id = $1 AND project_id = $2
        ORDER BY created_at DESC, id ASC`,
      [identity.spaceId, projectId],
    );
    return result.rows.map(provenanceOut);
  }

  async createProvenance(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const experimentKey = optionalString(body.experiment_key);
    if (!experimentKey) throw new HttpError(422, "experiment_key is required");
    const campaignId = optionalString(body.campaign_id);
    if (campaignId) await this.requireCampaign(identity.spaceId, projectId, campaignId);
    const existing = await this.db.query<{ id: string }>(
      `SELECT id FROM project_experiment_provenance WHERE space_id = $1 AND project_id = $2 AND experiment_key = $3 LIMIT 1`,
      [identity.spaceId, projectId, experimentKey],
    );
    if (existing.rows[0]) throw new HttpError(409, "experiment_key is already in use for this project");
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO project_experiment_provenance (
         id, space_id, project_id, campaign_id, experiment_key, planned_summary, executed_summary,
         negative_results, limitations, repro_lock_json, linked_artifact_ids_json, linked_run_ids_json,
         created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12::jsonb, $13, $14, $14)`,
      [
        id,
        identity.spaceId,
        projectId,
        campaignId,
        experimentKey,
        optionalString(body.planned_summary),
        optionalString(body.executed_summary),
        optionalString(body.negative_results),
        optionalString(body.limitations),
        JSON.stringify(objectValue(body.repro_lock)),
        JSON.stringify(stringArray(body.linked_artifact_ids)),
        JSON.stringify(stringArray(body.linked_run_ids)),
        identity.userId,
        now,
      ],
    );
    const result = await this.db.query<ProvenanceRow>(
      `SELECT ${PROVENANCE_COLUMNS} FROM project_experiment_provenance WHERE space_id = $1 AND id = $2 LIMIT 1`,
      [identity.spaceId, id],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(500, "Failed to create experiment provenance record");
    return provenanceOut(row);
  }
}
