import { randomUUID } from "node:crypto";
import {
  HttpError,
  dateIso,
  objectValue,
  optionalString,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";
import { contentReadSql } from "../access/contentAccessSql";
import { assertProjectReadable, assertProjectWriter } from "../projects/access";
import { ProjectCorpusRepository } from "../projects/corpusRepository";

const OUTPUT_TYPES = new Set(["paper", "thesis", "report", "review", "proposal", "other"]);
const PAPER_TYPES = new Set(["empirical", "theory", "survey", "review", "position", "case_study", "other"]);
const CITATION_STYLES = new Set(["apa", "mla", "chicago", "ieee", "acm", "vancouver", "other"]);
const EXPERIMENT_INTAKE = new Set(["none", "code_experiments", "human_study", "both", "undecided"]);
const WORKFLOW_TYPES = new Set(["literature_review", "empirical_paper", "theory_paper", "paper_review", "revision"]);
const WORKFLOW_MODES = new Set(["manual", "agent_assisted", "autonomous"]);
const CHECKPOINT_TYPES = new Set(["profile_approval", "screening_gate", "integrity_gate", "manuscript_gate", "review_gate", "other"]);
export const ARTIFACT_TYPES = new Set([
  "rq_brief",
  "methodology_blueprint",
  "search_strategy",
  "annotated_bibliography",
  "literature_matrix",
  "synthesis_report",
  "integrity_report",
  "outline",
  "draft",
  "review_package",
  "revision_plan",
  "final_export",
  "process_summary",
]);
const CHECKPOINT_DECISIONS = new Set(["approved", "rejected", "waived"]);
const SUPPORT_STATUSES = new Set(["unsupported", "supported", "partial", "gap_declared"]);

interface ProfileRow {
  id: string;
  project_id: string;
  preset_key: string;
  research_question: string | null;
  working_title: string | null;
  domain: string | null;
  output_type: string | null;
  paper_type: string | null;
  citation_style: string | null;
  target_venue: string | null;
  language: string;
  experiment_intake_declaration: string;
  status: string;
  approved_by_user_id: string | null;
  approved_at: unknown;
  created_at: unknown;
  updated_at: unknown;
}

interface WorkflowRow {
  id: string;
  project_id: string;
  workflow_type: string;
  current_stage: string | null;
  status: string;
  mode: string;
  state_json: unknown;
  started_by_user_id: string | null;
  started_run_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

interface CheckpointRow {
  id: string;
  project_id: string;
  workflow_id: string;
  stage_key: string;
  checkpoint_type: string;
  status: string;
  machine_result_json: unknown;
  user_decision: string | null;
  decision_reason: string | null;
  decided_by_user_id: string | null;
  decided_at: unknown;
  created_at: unknown;
  updated_at: unknown;
}

interface ArtifactLinkRow {
  id: string;
  project_id: string;
  workflow_id: string | null;
  stage_key: string | null;
  artifact_id: string;
  artifact_type: string;
  created_by_user_id: string | null;
  created_by_run_id: string | null;
  created_at: unknown;
  artifact_title: string | null;
  artifact_content: string | null;
  artifact_created_at: unknown;
}

interface ClaimLinkRow {
  id: string;
  project_id: string;
  workflow_id: string | null;
  claim_id: string;
  support_status: string;
  planned_experiment_ids_json: unknown;
  citation_anchors_json: unknown;
  unresolved_gap: boolean;
  gap_reason: string | null;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

const PROFILE_COLUMNS = `
  id, project_id, preset_key, research_question, working_title, domain, output_type,
  paper_type, citation_style, target_venue, language, experiment_intake_declaration,
  status, approved_by_user_id, approved_at, created_at, updated_at
`;

const WORKFLOW_COLUMNS = `
  id, project_id, workflow_type, current_stage, status, mode, state_json,
  started_by_user_id, started_run_id, created_at, updated_at
`;

const CLAIM_LINK_SELECT = `
  pcl.id, pcl.project_id, pcl.workflow_id, pcl.claim_id, pcl.support_status,
  pcl.planned_experiment_ids_json, pcl.citation_anchors_json, pcl.unresolved_gap,
  pcl.gap_reason, pcl.created_by_user_id, pcl.created_at, pcl.updated_at
`;

const CHECKPOINT_COLUMNS = `
  id, project_id, workflow_id, stage_key, checkpoint_type, status, machine_result_json,
  user_decision, decision_reason, decided_by_user_id, decided_at, created_at, updated_at
`;

function requiredDateIso(value: unknown): string {
  return dateIso(value) ?? new Date(0).toISOString();
}

function profileOut(row: ProfileRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    preset_key: row.preset_key,
    research_question: row.research_question,
    working_title: row.working_title,
    domain: row.domain,
    output_type: row.output_type,
    paper_type: row.paper_type,
    citation_style: row.citation_style,
    target_venue: row.target_venue,
    language: row.language,
    experiment_intake_declaration: row.experiment_intake_declaration,
    status: row.status,
    approved_by_user_id: row.approved_by_user_id,
    approved_at: dateIso(row.approved_at),
    created_at: requiredDateIso(row.created_at),
    updated_at: requiredDateIso(row.updated_at),
  };
}

function workflowOut(row: WorkflowRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    workflow_type: row.workflow_type,
    current_stage: row.current_stage,
    status: row.status,
    mode: row.mode,
    state_json: objectValue(row.state_json),
    started_by_user_id: row.started_by_user_id,
    started_run_id: row.started_run_id,
    created_at: requiredDateIso(row.created_at),
    updated_at: requiredDateIso(row.updated_at),
  };
}

function checkpointOut(row: CheckpointRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    workflow_id: row.workflow_id,
    stage_key: row.stage_key,
    checkpoint_type: row.checkpoint_type,
    status: row.status,
    machine_result_json: row.machine_result_json === null ? null : objectValue(row.machine_result_json),
    user_decision: row.user_decision,
    decision_reason: row.decision_reason,
    decided_by_user_id: row.decided_by_user_id,
    decided_at: dateIso(row.decided_at),
    created_at: requiredDateIso(row.created_at),
    updated_at: requiredDateIso(row.updated_at),
  };
}

function artifactLinkOut(row: ArtifactLinkRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    workflow_id: row.workflow_id,
    stage_key: row.stage_key,
    artifact_id: row.artifact_id,
    artifact_type: row.artifact_type,
    created_by_user_id: row.created_by_user_id,
    created_by_run_id: row.created_by_run_id,
    created_at: requiredDateIso(row.created_at),
    artifact: {
      id: row.artifact_id,
      title: row.artifact_title,
      content: row.artifact_content,
      created_at: dateIso(row.artifact_created_at),
    },
  };
}

function claimLinkOut(row: ClaimLinkRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    workflow_id: row.workflow_id,
    claim_id: row.claim_id,
    support_status: row.support_status,
    planned_experiment_ids: jsonStringArray(row.planned_experiment_ids_json),
    citation_anchors: jsonStringArray(row.citation_anchors_json),
    unresolved_gap: row.unresolved_gap,
    gap_reason: row.gap_reason,
    created_by_user_id: row.created_by_user_id,
    created_at: requiredDateIso(row.created_at),
    updated_at: requiredDateIso(row.updated_at),
  };
}

function enumValue(value: unknown, allowed: Set<string>, field: string): string | null {
  const text = optionalString(value);
  if (!text) return null;
  if (!allowed.has(text)) throw new HttpError(422, `${field} must be one of ${[...allowed].join(", ")}`);
  return text;
}

export class ProjectResearchRepository {
  constructor(private readonly db: Queryable) {}

  // --- Profile ---------------------------------------------------------

  async getProfile(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown> | null> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const row = await this.profileRow(identity.spaceId, projectId);
    return row ? profileOut(row) : null;
  }

  async upsertProfile(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const outputType = enumValue(body.output_type, OUTPUT_TYPES, "output_type");
    const paperType = enumValue(body.paper_type, PAPER_TYPES, "paper_type");
    const citationStyle = enumValue(body.citation_style, CITATION_STYLES, "citation_style");
    const experimentIntake = enumValue(body.experiment_intake_declaration, EXPERIMENT_INTAKE, "experiment_intake_declaration") ?? "undecided";
    const now = new Date().toISOString();
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO project_research_profiles (
         id, space_id, project_id, research_question, working_title, domain, output_type,
         paper_type, citation_style, target_venue, language, experiment_intake_declaration,
         status, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6, $7,
         $8, $9, $10, $11, $12,
         'draft', $13, $13
       )
       ON CONFLICT (space_id, project_id)
       DO UPDATE SET research_question = EXCLUDED.research_question,
                     working_title = EXCLUDED.working_title,
                     domain = EXCLUDED.domain,
                     output_type = EXCLUDED.output_type,
                     paper_type = EXCLUDED.paper_type,
                     citation_style = EXCLUDED.citation_style,
                     target_venue = EXCLUDED.target_venue,
                     language = EXCLUDED.language,
                     experiment_intake_declaration = EXCLUDED.experiment_intake_declaration,
                     status = 'draft',
                     approved_by_user_id = NULL,
                     approved_at = NULL,
                     updated_at = EXCLUDED.updated_at`,
      [
        id,
        identity.spaceId,
        projectId,
        optionalString(body.research_question),
        optionalString(body.working_title),
        optionalString(body.domain),
        outputType,
        paperType,
        citationStyle,
        optionalString(body.target_venue),
        optionalString(body.language) ?? "en",
        experimentIntake,
        now,
      ],
    );
    const row = await this.profileRow(identity.spaceId, projectId);
    if (!row) throw new HttpError(500, "Failed to upsert research profile");
    return profileOut(row);
  }

  async approveProfile(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const row = await this.profileRow(identity.spaceId, projectId);
    if (!row) throw new HttpError(404, "Research profile not found");
    if (row.status === "archived") throw new HttpError(422, "Cannot approve an archived research profile");
    if (row.status === "approved") return profileOut(row);
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE project_research_profiles
          SET status = 'approved', approved_by_user_id = $3, approved_at = $4, updated_at = $4
        WHERE space_id = $1 AND project_id = $2`,
      [identity.spaceId, projectId, identity.userId, now],
    );
    const updated = await this.profileRow(identity.spaceId, projectId);
    if (!updated) throw new HttpError(500, "Failed to approve research profile");
    return profileOut(updated);
  }

  private async profileRow(spaceId: string, projectId: string): Promise<ProfileRow | null> {
    const result = await this.db.query<ProfileRow>(
      `SELECT ${PROFILE_COLUMNS} FROM project_research_profiles WHERE space_id = $1 AND project_id = $2 LIMIT 1`,
      [spaceId, projectId],
    );
    return result.rows[0] ?? null;
  }

  // --- Workflows ---------------------------------------------------------

  async listWorkflows(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const result = await this.db.query<WorkflowRow>(
      `SELECT ${WORKFLOW_COLUMNS} FROM project_research_workflows
        WHERE space_id = $1 AND project_id = $2
        ORDER BY created_at DESC, id ASC`,
      [identity.spaceId, projectId],
    );
    return result.rows.map(workflowOut);
  }

  async startWorkflow(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const profile = await this.profileRow(identity.spaceId, projectId);
    if (!profile || profile.status !== "approved") {
      throw new HttpError(422, "The research profile must be approved before starting a workflow");
    }
    const workflowType = enumValue(body.workflow_type, WORKFLOW_TYPES, "workflow_type");
    if (!workflowType) throw new HttpError(422, "workflow_type is required");
    const mode = enumValue(body.mode, WORKFLOW_MODES, "mode") ?? "manual";
    const now = new Date().toISOString();
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO project_research_workflows (
         id, space_id, project_id, workflow_type, status, mode, state_json,
         started_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, 'active', $5, '{}'::jsonb, $6, $7, $7)`,
      [id, identity.spaceId, projectId, workflowType, mode, identity.userId, now],
    );
    const row = await this.workflowRow(identity.spaceId, projectId, id);
    if (!row) throw new HttpError(500, "Failed to start research workflow");
    return workflowOut(row);
  }

  async runStage(
    identity: SpaceUserIdentity,
    projectId: string,
    workflowId: string,
    stageKey: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const row = await this.workflowRow(identity.spaceId, projectId, workflowId);
    if (!row) throw new HttpError(404, "Research workflow not found");
    if (row.status !== "active") throw new HttpError(422, `Cannot run a stage on a workflow with status ${row.status}`);
    const runId = optionalString(body.run_id);
    const now = new Date().toISOString();
    const stageEntry = { status: runId ? "running" : "recorded", run_id: runId, updated_at: now };
    // jsonb_set against the current DB value (not the row read above) so two
    // concurrent runStage calls for different stage keys on the same
    // workflow don't lose one update in a read-modify-write race. stageKey
    // is passed as two separate parameters ($4, $5) rather than reused —
    // reusing one parameter across a plain-column context and an ARRAY[]
    // context in the same statement trips "inconsistent types deduced for
    // parameter" on this pg version/driver combination.
    await this.db.query(
      `UPDATE project_research_workflows
          SET current_stage = $4,
              state_json = jsonb_set(
                jsonb_set(coalesce(state_json, '{}'::jsonb), '{stages}', coalesce(state_json->'stages', '{}'::jsonb), true),
                ARRAY['stages', $5], $6::jsonb, true
              ),
              updated_at = $7
        WHERE space_id = $1 AND project_id = $2 AND id = $3`,
      [identity.spaceId, projectId, workflowId, stageKey, stageKey, JSON.stringify(stageEntry), now],
    );
    const updated = await this.workflowRow(identity.spaceId, projectId, workflowId);
    if (!updated) throw new HttpError(500, "Failed to run research workflow stage");
    return workflowOut(updated);
  }

  private async workflowRow(spaceId: string, projectId: string, workflowId: string): Promise<WorkflowRow | null> {
    const result = await this.db.query<WorkflowRow>(
      `SELECT ${WORKFLOW_COLUMNS} FROM project_research_workflows
        WHERE space_id = $1 AND project_id = $2 AND id = $3 LIMIT 1`,
      [spaceId, projectId, workflowId],
    );
    return result.rows[0] ?? null;
  }

  // --- Checkpoints ---------------------------------------------------------

  async listCheckpoints(identity: SpaceUserIdentity, projectId: string, workflowId: string): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    await this.requireWorkflow(identity.spaceId, projectId, workflowId);
    const result = await this.db.query<CheckpointRow>(
      `SELECT ${CHECKPOINT_COLUMNS} FROM project_research_checkpoints
        WHERE space_id = $1 AND project_id = $2 AND workflow_id = $3
        ORDER BY created_at DESC, id ASC`,
      [identity.spaceId, projectId, workflowId],
    );
    return result.rows.map(checkpointOut);
  }

  async createCheckpoint(
    identity: SpaceUserIdentity,
    projectId: string,
    workflowId: string,
    input: { stageKey: string; checkpointType: string; machineResult: Record<string, unknown> | null },
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    await this.requireWorkflow(identity.spaceId, projectId, workflowId);
    const checkpointType = enumValue(input.checkpointType, CHECKPOINT_TYPES, "checkpoint_type");
    if (!checkpointType) throw new HttpError(422, "checkpoint_type is required");
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO project_research_checkpoints (
         id, space_id, project_id, workflow_id, stage_key, checkpoint_type, status,
         machine_result_json, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7::jsonb, $8, $8)`,
      [id, identity.spaceId, projectId, workflowId, input.stageKey, checkpointType, JSON.stringify(input.machineResult ?? {}), now],
    );
    const row = await this.checkpointRow(identity.spaceId, projectId, id);
    if (!row) throw new HttpError(500, "Failed to create checkpoint");
    return checkpointOut(row);
  }

  async decideCheckpoint(
    identity: SpaceUserIdentity,
    projectId: string,
    workflowId: string,
    checkpointId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    await this.requireWorkflow(identity.spaceId, projectId, workflowId);
    const decision = enumValue(body.decision, CHECKPOINT_DECISIONS, "decision");
    if (!decision) throw new HttpError(422, "decision is required and must be one of approved, rejected, waived");
    const row = await this.checkpointRow(identity.spaceId, projectId, checkpointId);
    if (!row || row.workflow_id !== workflowId) throw new HttpError(404, "Checkpoint not found");
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE project_research_checkpoints
          SET status = $5, user_decision = $5, decision_reason = $6,
              decided_by_user_id = $7, decided_at = $8, updated_at = $8
        WHERE space_id = $1 AND project_id = $2 AND workflow_id = $3 AND id = $4`,
      [identity.spaceId, projectId, workflowId, checkpointId, decision, optionalString(body.reason), identity.userId, now],
    );
    const updated = await this.checkpointRow(identity.spaceId, projectId, checkpointId);
    if (!updated) throw new HttpError(500, "Failed to decide checkpoint");
    return checkpointOut(updated);
  }

  private async checkpointRow(spaceId: string, projectId: string, checkpointId: string): Promise<CheckpointRow | null> {
    const result = await this.db.query<CheckpointRow>(
      `SELECT ${CHECKPOINT_COLUMNS} FROM project_research_checkpoints
        WHERE space_id = $1 AND project_id = $2 AND id = $3 LIMIT 1`,
      [spaceId, projectId, checkpointId],
    );
    return result.rows[0] ?? null;
  }

  private async requireWorkflow(spaceId: string, projectId: string, workflowId: string): Promise<void> {
    const row = await this.workflowRow(spaceId, projectId, workflowId);
    if (!row) throw new HttpError(404, "Research workflow not found");
  }

  // --- Artifact links ---------------------------------------------------------

  async listArtifactLinks(
    identity: SpaceUserIdentity,
    projectId: string,
    filters: { workflowId?: string | null; artifactType?: string | null },
  ): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    return this.artifactLinkRows(identity.spaceId, projectId, identity.userId, filters);
  }

  private async artifactLinkRows(
    spaceId: string,
    projectId: string,
    viewerUserId: string,
    filters: { id?: string | null; workflowId?: string | null; artifactType?: string | null },
  ): Promise<Record<string, unknown>[]> {
    const params: unknown[] = [spaceId, projectId, viewerUserId];
    const clauses = ["ral.space_id = $1", "ral.project_id = $2", contentReadSql("artifact", "a", "$3")];
    if (filters.id) {
      params.push(filters.id);
      clauses.push(`ral.id = $${params.length}`);
    }
    if (filters.workflowId) {
      params.push(filters.workflowId);
      clauses.push(`ral.workflow_id = $${params.length}`);
    }
    if (filters.artifactType) {
      if (!ARTIFACT_TYPES.has(filters.artifactType)) throw new HttpError(422, "artifact_type is invalid");
      params.push(filters.artifactType);
      clauses.push(`ral.artifact_type = $${params.length}`);
    }
    const result = await this.db.query<ArtifactLinkRow>(
      `SELECT ral.id, ral.project_id, ral.workflow_id, ral.stage_key, ral.artifact_id, ral.artifact_type,
              ral.created_by_user_id, ral.created_by_run_id, ral.created_at,
              a.title AS artifact_title, a.content AS artifact_content, a.created_at AS artifact_created_at
         FROM project_research_artifact_links ral
         JOIN artifacts a ON a.id = ral.artifact_id AND a.space_id = ral.space_id
        WHERE ${clauses.join(" AND ")}
        ORDER BY ral.created_at DESC, ral.id ASC`,
      params,
    );
    return result.rows.map(artifactLinkOut);
  }

  async linkArtifact(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const artifactId = optionalString(body.artifact_id);
    if (!artifactId) throw new HttpError(422, "artifact_id is required");
    const artifactType = enumValue(body.artifact_type, ARTIFACT_TYPES, "artifact_type");
    if (!artifactType) throw new HttpError(422, "artifact_type is required");
    const artifactExists = await this.db.query<{ id: string }>(
      `SELECT a.id
         FROM artifacts a
        WHERE a.id = $1
          AND a.space_id = $2
          AND ${contentReadSql("artifact", "a", "$3")}
          AND (a.project_id IS NULL OR a.project_id = $4)
        LIMIT 1`,
      [artifactId, identity.spaceId, identity.userId, projectId],
    );
    if (!artifactExists.rows[0]) {
      throw new HttpError(422, "artifact_id does not reference an artifact available to this project");
    }
    const workflowId = optionalString(body.workflow_id);
    if (workflowId) await this.requireWorkflow(identity.spaceId, projectId, workflowId);
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO project_research_artifact_links (
         id, space_id, project_id, workflow_id, stage_key, artifact_id, artifact_type,
         created_by_user_id, created_by_run_id, created_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [id, identity.spaceId, projectId, workflowId, optionalString(body.stage_key), artifactId, artifactType, identity.userId, optionalString(body.run_id), now],
    );
    const created = (await this.artifactLinkRows(identity.spaceId, projectId, identity.userId, { id }))[0];
    if (!created) throw new HttpError(500, "Failed to link artifact");
    return created;
  }

  // --- Integrity ---------------------------------------------------------

  async runIntegrityCheck(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const workflowId = optionalString(body.workflow_id);
    if (!workflowId) throw new HttpError(422, "workflow_id is required");
    const stageKey = optionalString(body.stage_key) ?? "integrity_gate";
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    await this.requireWorkflow(identity.spaceId, projectId, workflowId);
    const report = await this.computeIntegrityReport(identity.spaceId, projectId, workflowId, identity.userId);
    const artifactId = await this.createArtifact(identity, projectId, {
      artifactType: "integrity_report",
      title: `Integrity Report (${new Date().toISOString()})`,
      content: JSON.stringify(report),
    });
    await this.linkArtifactInternal(identity, projectId, {
      workflowId,
      stageKey,
      artifactId,
      artifactType: "integrity_report",
    });
    return this.createCheckpoint(identity, projectId, workflowId, {
      stageKey,
      checkpointType: "integrity_gate",
      machineResult: report,
    });
  }

  /**
   * V1 checks: citation existence for cited papers, claim has evidence or
   * an explicit gap, evidence source is visible in the project corpus, and
   * experiment-backed claims reference a project_experiment_provenance row.
   */
  private async computeIntegrityReport(
    spaceId: string,
    projectId: string,
    workflowId: string,
    viewerUserId: string,
  ): Promise<Record<string, unknown>> {
    const links = await this.db.query<{
      id: string;
      claim_id: string;
      support_status: string;
      planned_experiment_ids_json: unknown;
      citation_anchors_json: unknown;
      unresolved_gap: boolean;
    }>(
      `SELECT pcl.id, pcl.claim_id, pcl.support_status, pcl.planned_experiment_ids_json,
              pcl.citation_anchors_json, pcl.unresolved_gap
         FROM project_research_claim_links pcl
         JOIN claims c ON c.object_id = pcl.claim_id AND c.space_id = pcl.space_id
         JOIN space_objects so
           ON so.id = c.object_id
          AND so.space_id = c.space_id
          AND so.object_type = 'claim'
          AND so.deleted_at IS NULL
        WHERE pcl.space_id = $1
          AND pcl.project_id = $2
          AND (pcl.workflow_id = $3 OR pcl.workflow_id IS NULL)
          AND ${contentReadSql("space_object", "so", "$4")}`,
      [spaceId, projectId, workflowId, viewerUserId],
    );
    const findings: Array<{ severity: "high" | "medium" | "low"; claim_link_id: string; code: string; message: string }> = [];

    for (const link of links.rows) {
      const citationAnchors = Array.isArray(link.citation_anchors_json)
        ? link.citation_anchors_json.filter((v): v is string => typeof v === "string")
        : [];
      const plannedExperimentIds = Array.isArray(link.planned_experiment_ids_json)
        ? link.planned_experiment_ids_json.filter((v): v is string => typeof v === "string")
        : [];

      for (const paperObjectId of citationAnchors) {
        const exists = await this.db.query<{ object_id: string }>(
          `SELECT ap.object_id FROM academic_papers ap
             JOIN space_objects so ON so.id = ap.object_id AND so.space_id = ap.space_id
            WHERE ap.space_id = $1 AND ap.object_id = $2 AND so.deleted_at IS NULL LIMIT 1`,
          [spaceId, paperObjectId],
        );
        if (!exists.rows[0]) {
          findings.push({
            severity: "high",
            claim_link_id: link.id,
            code: "citation_not_found",
            message: `Cited paper ${paperObjectId} does not exist in this space`,
          });
        }
      }

      const evidenceRows = await this.db.query<{ source_object_id: string | null }>(
        `SELECT source_object_id FROM claim_sources WHERE space_id = $1 AND claim_id = $2`,
        [spaceId, link.claim_id],
      );
      if (evidenceRows.rows.length === 0 && !link.unresolved_gap) {
        findings.push({
          severity: "high",
          claim_link_id: link.id,
          code: "no_evidence_no_gap",
          message: "Claim has no evidence link and is not marked as a material gap",
        });
      }
      for (const evidence of evidenceRows.rows) {
        if (!evidence.source_object_id) continue;
        const inCorpus = await this.db.query<{ id: string }>(
          `SELECT id FROM project_corpus_items
            WHERE space_id = $1 AND project_id = $2 AND object_id = $3 AND status = 'active' LIMIT 1`,
          [spaceId, projectId, evidence.source_object_id],
        );
        if (!inCorpus.rows[0]) {
          findings.push({
            severity: "medium",
            claim_link_id: link.id,
            code: "evidence_not_in_project_corpus",
            message: `Evidence source ${evidence.source_object_id} is not visible in this project's corpus`,
          });
        }
      }

      for (const experimentKey of plannedExperimentIds) {
        const provenance = await this.db.query<{ id: string }>(
          `SELECT id FROM project_experiment_provenance
            WHERE space_id = $1 AND project_id = $2 AND experiment_key = $3 LIMIT 1`,
          [spaceId, projectId, experimentKey],
        );
        if (!provenance.rows[0]) {
          findings.push({
            severity: "high",
            claim_link_id: link.id,
            code: "experiment_provenance_not_found",
            message: `Declared experiment '${experimentKey}' has no provenance record in this project`,
          });
        }
      }
    }

    const blocking = findings.some((finding) => finding.severity === "high");
    return {
      schema_version: "integrity_report.v1",
      workflow_id: workflowId,
      generated_at: new Date().toISOString(),
      checked_claim_links: links.rows.length,
      findings,
      blocking,
    };
  }

  private async createArtifact(
    identity: SpaceUserIdentity,
    projectId: string,
    input: { artifactType: string; title: string; content: string },
  ): Promise<string> {
    const artifactId = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, project_id, artifact_type, title, content, mime_type,
         exportable, export_formats_json, canonical_format, preview,
         created_at, updated_at, visibility, owner_user_id
       ) VALUES (
         $1, $2, $3, $4, $5, $6, 'application/json',
         true, $7::jsonb, 'json', false,
         $8, $8, 'space_shared', $9
       )`,
      [artifactId, identity.spaceId, projectId, input.artifactType, input.title.slice(0, 512), input.content, JSON.stringify(["json"]), now, identity.userId],
    );
    return artifactId;
  }

  private async linkArtifactInternal(
    identity: SpaceUserIdentity,
    projectId: string,
    input: { workflowId: string | null; stageKey: string | null; artifactId: string; artifactType: string },
  ): Promise<void> {
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO project_research_artifact_links (
         id, space_id, project_id, workflow_id, stage_key, artifact_id, artifact_type,
         created_by_user_id, created_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
      [id, identity.spaceId, projectId, input.workflowId, input.stageKey, input.artifactId, input.artifactType, identity.userId, now],
    );
  }

  // --- Claim links ---------------------------------------------------------

  async listClaimLinks(identity: SpaceUserIdentity, projectId: string, workflowId?: string | null): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const params: unknown[] = [identity.spaceId, projectId, identity.userId];
    let where = `pcl.space_id = $1 AND pcl.project_id = $2 AND ${contentReadSql("space_object", "so", "$3")}`;
    if (workflowId) {
      params.push(workflowId);
      where += ` AND pcl.workflow_id = $${params.length}`;
    }
    const result = await this.db.query<ClaimLinkRow>(
      `SELECT ${CLAIM_LINK_SELECT}
         FROM project_research_claim_links pcl
         JOIN claims c ON c.object_id = pcl.claim_id AND c.space_id = pcl.space_id
         JOIN space_objects so
           ON so.id = c.object_id
          AND so.space_id = c.space_id
          AND so.object_type = 'claim'
          AND so.deleted_at IS NULL
        WHERE ${where}
        ORDER BY pcl.created_at DESC, pcl.id ASC`,
      params,
    );
    return result.rows.map(claimLinkOut);
  }

  async createClaimLink(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const claimId = optionalString(body.claim_id);
    if (!claimId) throw new HttpError(422, "claim_id is required");
    const claimExists = await this.db.query<{ object_id: string }>(
      `SELECT c.object_id
         FROM claims c
         JOIN space_objects so
           ON so.id = c.object_id
          AND so.space_id = c.space_id
          AND so.object_type = 'claim'
          AND so.deleted_at IS NULL
        WHERE c.object_id = $1
          AND c.space_id = $2
          AND ${contentReadSql("space_object", "so", "$3")}
        LIMIT 1`,
      [claimId, identity.spaceId, identity.userId],
    );
    if (!claimExists.rows[0]) throw new HttpError(422, "claim_id is not readable by this user");
    const existingLink = await this.db.query<{ id: string }>(
      `SELECT id FROM project_research_claim_links WHERE space_id = $1 AND project_id = $2 AND claim_id = $3 LIMIT 1`,
      [identity.spaceId, projectId, claimId],
    );
    if (existingLink.rows[0]) throw new HttpError(409, "This claim is already linked to the project");
    const workflowId = optionalString(body.workflow_id);
    if (workflowId) await this.requireWorkflow(identity.spaceId, projectId, workflowId);
    const supportStatus = enumValue(body.support_status, SUPPORT_STATUSES, "support_status") ?? "unsupported";
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO project_research_claim_links (
         id, space_id, project_id, workflow_id, claim_id, support_status,
         planned_experiment_ids_json, citation_anchors_json, unresolved_gap, gap_reason,
         created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11, $12, $12)`,
      [
        id,
        identity.spaceId,
        projectId,
        workflowId,
        claimId,
        supportStatus,
        JSON.stringify(stringArray(body.planned_experiment_ids)),
        JSON.stringify(stringArray(body.citation_anchors)),
        body.unresolved_gap === true,
        optionalString(body.gap_reason),
        identity.userId,
        now,
      ],
    );
    const row = await this.claimLinkRow(identity.spaceId, projectId, id, identity.userId);
    if (!row) throw new HttpError(500, "Failed to create claim link");
    return claimLinkOut(row);
  }

  async updateClaimLink(
    identity: SpaceUserIdentity,
    projectId: string,
    claimLinkId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const current = await this.claimLinkRow(identity.spaceId, projectId, claimLinkId, identity.userId);
    if (!current) throw new HttpError(404, "Claim link not found");
    const supportStatus = body.support_status === undefined
      ? current.support_status
      : enumValue(body.support_status, SUPPORT_STATUSES, "support_status") ?? current.support_status;
    const plannedExperimentIds = body.planned_experiment_ids === undefined
      ? jsonStringArray(current.planned_experiment_ids_json)
      : stringArray(body.planned_experiment_ids);
    const citationAnchors = body.citation_anchors === undefined
      ? jsonStringArray(current.citation_anchors_json)
      : stringArray(body.citation_anchors);
    const unresolvedGap = body.unresolved_gap === undefined ? current.unresolved_gap : body.unresolved_gap === true;
    const gapReason = body.gap_reason === undefined ? current.gap_reason : optionalString(body.gap_reason);
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE project_research_claim_links
          SET support_status = $4, planned_experiment_ids_json = $5::jsonb, citation_anchors_json = $6::jsonb,
              unresolved_gap = $7, gap_reason = $8, updated_at = $9
        WHERE space_id = $1 AND project_id = $2 AND id = $3`,
      [identity.spaceId, projectId, claimLinkId, supportStatus, JSON.stringify(plannedExperimentIds), JSON.stringify(citationAnchors), unresolvedGap, gapReason, now],
    );
    const updated = await this.claimLinkRow(identity.spaceId, projectId, claimLinkId, identity.userId);
    if (!updated) throw new HttpError(500, "Failed to update claim link");
    return claimLinkOut(updated);
  }

  private async claimLinkRow(
    spaceId: string,
    projectId: string,
    claimLinkId: string,
    viewerUserId: string,
  ): Promise<ClaimLinkRow | null> {
    const result = await this.db.query<ClaimLinkRow>(
      `SELECT ${CLAIM_LINK_SELECT}
         FROM project_research_claim_links pcl
         JOIN claims c ON c.object_id = pcl.claim_id AND c.space_id = pcl.space_id
         JOIN space_objects so
           ON so.id = c.object_id
          AND so.space_id = c.space_id
          AND so.object_type = 'claim'
          AND so.deleted_at IS NULL
        WHERE pcl.space_id = $1
          AND pcl.project_id = $2
          AND pcl.id = $3
          AND ${contentReadSql("space_object", "so", "$4")}
        LIMIT 1`,
      [spaceId, projectId, claimLinkId, viewerUserId],
    );
    return result.rows[0] ?? null;
  }

  // --- Literature matrix / synthesis ---------------------------------------
  //
  // Thin read model over the existing Project Corpus (included/maybe papers).
  // The route contract stays stable as the backing query gains richer academic
  // metadata, extracted evidence, and annotations.

  async getLiteratureMatrix(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const result = await this.db.query<{
      id: string;
      object_id: string | null;
      triage_status: string;
      relevance: string | null;
      confidence: number | null;
      reason: string | null;
      object_title: string | null;
      object_summary: string | null;
      arxiv_id: string | null;
      doi: string | null;
      publication_date: unknown;
      venue: string | null;
      paper_type: string | null;
      cited_by_count: number | null;
      reference_count: number | null;
      source_uri: string | null;
      authors: unknown;
      categories: unknown;
      evidence_count: string;
      annotation_count: string;
    }>(
      `SELECT pci.id, pci.object_id, pci.triage_status, pci.relevance, pci.confidence, pci.reason,
              so.title AS object_title, so.summary AS object_summary,
              ap.arxiv_id, ap.doi, ap.publication_date, ap.venue, ap.paper_type,
              ap.cited_by_count, ap.reference_count,
              src.uri AS source_uri, src.metadata_json->'authors' AS authors, src.metadata_json->'categories' AS categories,
              (SELECT count(*) FROM extracted_evidence ee
                WHERE ee.space_id = pci.space_id AND ee.source_item_id = pci.source_item_id
                  AND pci.source_item_id IS NOT NULL AND ee.deleted_at IS NULL) AS evidence_count,
              (SELECT count(*) FROM reader_annotations ra
                WHERE ra.space_id = pci.space_id AND ra.source_item_id = pci.source_item_id
                  AND pci.source_item_id IS NOT NULL AND ra.status = 'active') AS annotation_count
         FROM project_corpus_items pci
         LEFT JOIN space_objects so ON so.id = pci.object_id AND so.space_id = pci.space_id
         LEFT JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = pci.space_id
         LEFT JOIN sources src ON src.object_id = so.id AND src.space_id = pci.space_id
        WHERE pci.space_id = $1 AND pci.project_id = $2 AND pci.status = 'active'
          AND pci.triage_status IN ('included', 'maybe')
        ORDER BY pci.triage_status ASC, so.title ASC NULLS LAST`,
      [identity.spaceId, projectId],
    );
    return result.rows.map((row) => ({
      corpus_item_id: row.id,
      object_id: row.object_id,
      title: row.object_title,
      summary: row.object_summary,
      triage_status: row.triage_status,
      relevance: row.relevance,
      confidence: row.confidence,
      reason: row.reason,
      evidence_count: Number(row.evidence_count),
      annotation_count: Number(row.annotation_count),
      // paper_type is NOT NULL on academic_papers — a reliable "joined" signal.
      academic: row.paper_type !== null
        ? {
            arxiv_id: row.arxiv_id,
            doi: row.doi,
            publication_date: dateIso(row.publication_date),
            venue: row.venue,
            paper_type: row.paper_type,
            cited_by_count: row.cited_by_count,
            reference_count: row.reference_count,
            source_uri: row.source_uri,
            authors: Array.isArray(row.authors) ? row.authors : [],
            categories: Array.isArray(row.categories) ? row.categories : [],
          }
        : null,
    }));
  }

  async rebuildLiteratureMatrix(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    await new ProjectCorpusRepository(this.db).backfillFromSources(identity, projectId);
    return this.getLiteratureMatrix(identity, projectId);
  }

  async listSynthesisArtifacts(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    return this.listArtifactLinks(identity, projectId, { artifactType: "synthesis_report" });
  }

  // --- Screening criteria ---------------------------------------------------------

  async getScreeningCriteria(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const row = await this.screeningCriteriaRow(identity.spaceId, projectId);
    return row ? screeningCriteriaOut(row) : emptyScreeningCriteria(projectId);
  }

  async upsertScreeningCriteria(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const includeKeywords = stringArray(body.include_keywords);
    const excludeKeywords = stringArray(body.exclude_keywords);
    const methods = stringArray(body.methods);
    const venues = stringArray(body.venues);
    const requiredEvidenceFields = stringArray(body.required_evidence_fields);
    const dateRangeStart = optionalString(body.date_range_start);
    const dateRangeEnd = optionalString(body.date_range_end);
    if (dateRangeStart && dateRangeEnd && dateRangeStart > dateRangeEnd) {
      throw new HttpError(422, "date_range_start must be before date_range_end");
    }
    const now = new Date().toISOString();
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO project_research_screening_criteria (
         id, space_id, project_id, include_keywords_json, exclude_keywords_json, methods_json,
         date_range_start, date_range_end, venues_json, required_evidence_fields_json,
         created_at, updated_at
       ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8, $9::jsonb, $10::jsonb, $11, $11)
       ON CONFLICT (space_id, project_id)
       DO UPDATE SET include_keywords_json = EXCLUDED.include_keywords_json,
                     exclude_keywords_json = EXCLUDED.exclude_keywords_json,
                     methods_json = EXCLUDED.methods_json,
                     date_range_start = EXCLUDED.date_range_start,
                     date_range_end = EXCLUDED.date_range_end,
                     venues_json = EXCLUDED.venues_json,
                     required_evidence_fields_json = EXCLUDED.required_evidence_fields_json,
                     updated_at = EXCLUDED.updated_at`,
      [
        id,
        identity.spaceId,
        projectId,
        JSON.stringify(includeKeywords),
        JSON.stringify(excludeKeywords),
        JSON.stringify(methods),
        dateRangeStart,
        dateRangeEnd,
        JSON.stringify(venues),
        JSON.stringify(requiredEvidenceFields),
        now,
      ],
    );
    const row = await this.screeningCriteriaRow(identity.spaceId, projectId);
    if (!row) throw new HttpError(500, "Failed to upsert screening criteria");
    return screeningCriteriaOut(row);
  }

  private async screeningCriteriaRow(spaceId: string, projectId: string): Promise<ScreeningCriteriaRow | null> {
    const result = await this.db.query<ScreeningCriteriaRow>(
      `SELECT id, project_id, include_keywords_json, exclude_keywords_json, methods_json,
              date_range_start, date_range_end, venues_json, required_evidence_fields_json,
              created_at, updated_at
         FROM project_research_screening_criteria
        WHERE space_id = $1 AND project_id = $2 LIMIT 1`,
      [spaceId, projectId],
    );
    return result.rows[0] ?? null;
  }
}

interface ScreeningCriteriaRow {
  id: string;
  project_id: string;
  include_keywords_json: unknown;
  exclude_keywords_json: unknown;
  methods_json: unknown;
  date_range_start: unknown;
  date_range_end: unknown;
  venues_json: unknown;
  required_evidence_fields_json: unknown;
  created_at: unknown;
  updated_at: unknown;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function jsonStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function screeningCriteriaOut(row: ScreeningCriteriaRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    include_keywords: jsonStringArray(row.include_keywords_json),
    exclude_keywords: jsonStringArray(row.exclude_keywords_json),
    methods: jsonStringArray(row.methods_json),
    date_range_start: dateIso(row.date_range_start),
    date_range_end: dateIso(row.date_range_end),
    venues: jsonStringArray(row.venues_json),
    required_evidence_fields: jsonStringArray(row.required_evidence_fields_json),
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

function emptyScreeningCriteria(projectId: string): Record<string, unknown> {
  return {
    id: null,
    project_id: projectId,
    include_keywords: [],
    exclude_keywords: [],
    methods: [],
    date_range_start: null,
    date_range_end: null,
    venues: [],
    required_evidence_fields: [],
    created_at: null,
    updated_at: null,
  };
}
