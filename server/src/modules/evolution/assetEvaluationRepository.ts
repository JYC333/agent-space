import { randomUUID } from "node:crypto";
import {
  HttpError,
  dateIso,
  objectValue,
  optionalObject,
  optionalString,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";
import { insertProposalRow } from "../proposals/reviewPackets";
import { assertProjectWriter } from "../projects/access";
import { isSpaceOwnerOrAdmin } from "../access/roles";

const EVALUATION_STATUSES = new Set(["queued", "running", "passed", "failed", "blocked", "cancelled"]);

function requiredDateIso(value: unknown): string {
  return dateIso(value) ?? new Date(0).toISOString();
}

function enumValue(value: unknown, allowed: Set<string>, field: string): string | null {
  const text = optionalString(value);
  if (!text) return null;
  if (!allowed.has(text)) throw new HttpError(422, `${field} must be one of ${[...allowed].join(", ")}`);
  return text;
}

interface EvaluationRunRow {
  id: string;
  asset_id: string;
  candidate_version_id: string;
  baseline_version_id: string | null;
  evolution_target_id: string | null;
  run_id: string | null;
  eval_suite_ref_json: unknown;
  evaluator_version: string;
  model_provider_ref_json: unknown;
  status: string;
  metrics_json: unknown;
  blockers_json: unknown;
  output_artifact_id: string | null;
  report_artifact_id: string | null;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

const EVALUATION_RUN_COLUMNS = `
  id, asset_id, candidate_version_id, baseline_version_id, evolution_target_id, run_id,
  eval_suite_ref_json, evaluator_version, model_provider_ref_json, status, metrics_json,
  blockers_json, output_artifact_id, report_artifact_id, created_by_user_id, created_at, updated_at
`;

function evaluationRunOut(row: EvaluationRunRow): Record<string, unknown> {
  return {
    id: row.id,
    asset_id: row.asset_id,
    candidate_version_id: row.candidate_version_id,
    baseline_version_id: row.baseline_version_id,
    evolution_target_id: row.evolution_target_id,
    run_id: row.run_id,
    eval_suite_ref: row.eval_suite_ref_json,
    evaluator_version: row.evaluator_version,
    model_provider_ref: row.model_provider_ref_json ?? null,
    status: row.status,
    metrics: objectValue(row.metrics_json),
    blockers: Array.isArray(row.blockers_json) ? row.blockers_json : [],
    output_artifact_id: row.output_artifact_id,
    report_artifact_id: row.report_artifact_id,
    created_by_user_id: row.created_by_user_id,
    created_at: requiredDateIso(row.created_at),
    updated_at: requiredDateIso(row.updated_at),
  };
}

/**
 * Evaluation-run metadata and promotion-proposal creation for evolvable
 * assets. This does not run an evaluator itself — it records results
 * reported by a human reviewer or an external evaluation process:
 * store real structured results, never fabricate a pass/fail.
 */
export class EvolvableAssetEvaluationRepository {
  constructor(private readonly db: Queryable) {}

  async listEvaluationRuns(identity: SpaceUserIdentity, assetId: string): Promise<Record<string, unknown>[]> {
    await this.requireAsset(identity.spaceId, assetId);
    const result = await this.db.query<EvaluationRunRow>(
      `SELECT ${EVALUATION_RUN_COLUMNS} FROM evolvable_asset_evaluation_runs
        WHERE asset_id = $1 ORDER BY created_at DESC, id ASC`,
      [assetId],
    );
    return result.rows.map(evaluationRunOut);
  }

  async recordEvaluationRun(
    identity: SpaceUserIdentity,
    assetId: string,
    versionId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await this.requireAsset(identity.spaceId, assetId);
    const version = await this.versionRow(assetId, versionId);
    if (!version) throw new HttpError(422, "versionId does not reference a version of this asset");
    if (version.status !== "candidate" && version.status !== "testing") {
      throw new HttpError(422, "Only a candidate or testing version can record an evaluation run");
    }
    const evalSuiteRef = optionalObject(body.eval_suite_ref);
    if (!evalSuiteRef) throw new HttpError(422, "eval_suite_ref is required");
    const evaluatorVersion = optionalString(body.evaluator_version);
    if (!evaluatorVersion) throw new HttpError(422, "evaluator_version is required");
    const status = enumValue(body.status, EVALUATION_STATUSES, "status") ?? "queued";
    const baselineVersionId = optionalString(body.baseline_version_id);
    if (baselineVersionId && !(await this.versionRow(assetId, baselineVersionId))) {
      throw new HttpError(422, "baseline_version_id does not reference a version of this asset");
    }
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO evolvable_asset_evaluation_runs (
         id, space_id, asset_id, candidate_version_id, baseline_version_id, run_id,
         eval_suite_ref_json, evaluator_version, model_provider_ref_json, status, metrics_json,
         blockers_json, output_artifact_id, report_artifact_id, created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9::jsonb, $10, $11::jsonb, $12::jsonb, $13, $14, $15, $16, $16)`,
      [
        id,
        identity.spaceId,
        assetId,
        versionId,
        baselineVersionId,
        optionalString(body.run_id),
        JSON.stringify(evalSuiteRef),
        evaluatorVersion,
        optionalObject(body.model_provider_ref) ? JSON.stringify(body.model_provider_ref) : null,
        status,
        JSON.stringify(objectValue(body.metrics)),
        JSON.stringify(Array.isArray(body.blockers) ? body.blockers : []),
        optionalString(body.output_artifact_id),
        optionalString(body.report_artifact_id),
        identity.userId,
        now,
      ],
    );
    // Recording an evaluation run against a still-candidate version means
    // review/evaluation is now in progress — advance it to 'testing'.
    if (version.status === "candidate") {
      await this.db.query(`UPDATE evolvable_asset_versions SET status = 'testing', updated_at = $3 WHERE asset_id = $1 AND id = $2`, [
        assetId,
        versionId,
        now,
      ]);
    }
    const result = await this.db.query<EvaluationRunRow>(
      `SELECT ${EVALUATION_RUN_COLUMNS} FROM evolvable_asset_evaluation_runs WHERE id = $1`,
      [id],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(500, "Failed to record evaluation run");
    return evaluationRunOut(row);
  }

  async createPromotionProposal(
    identity: SpaceUserIdentity,
    assetId: string,
    versionId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const asset = await this.requireAsset(identity.spaceId, assetId);
    const version = await this.versionRow(assetId, versionId);
    if (!version) throw new HttpError(422, "versionId does not reference a version of this asset");
    if (version.status !== "candidate" && version.status !== "testing") {
      throw new HttpError(422, "Only a candidate or testing version can be proposed for promotion");
    }
    const targetScopeType = optionalString(body.target_scope_type);
    if (!targetScopeType || !["project", "space", "system"].includes(targetScopeType)) {
      throw new HttpError(422, "target_scope_type must be one of project, space, system");
    }
    const targetScopeId = optionalString(body.target_scope_id);
    if (targetScopeType !== "system" && !targetScopeId) {
      throw new HttpError(422, "target_scope_id is required for target_scope_type project/space");
    }
    if (targetScopeType === "system" && targetScopeId) {
      throw new HttpError(422, "target_scope_id must be omitted for target_scope_type system");
    }
    await assertCanProposePromotionScope(this.db, identity, targetScopeType, targetScopeId ?? null);
    const payload = {
      proposal_type: "evolvable_asset_version_promote",
      asset_id: assetId,
      candidate_version_id: versionId,
      target_scope_type: targetScopeType,
      target_scope_id: targetScopeId,
      pin_after_approval: body.pin_after_approval === true,
      deprecate_previous: body.deprecate_previous === true,
      evaluation_run_ids: Array.isArray(body.evaluation_run_ids)
        ? body.evaluation_run_ids.filter((v): v is string => typeof v === "string")
        : [],
      reason: optionalString(body.reason),
    };
    const row = await insertProposalRow(this.db, {
      spaceId: identity.spaceId,
      proposalType: "evolvable_asset_version_promote",
      title: `Promote ${asset.asset_key} v${version.version} to ${targetScopeType}${targetScopeId ? `:${targetScopeId}` : ""}`,
      summary: optionalString(body.reason),
      payload,
      rationale: optionalString(body.reason) ?? "Asset version promotion",
      createdByUserId: identity.userId,
      visibility: "space_shared",
      riskLevel: targetScopeType === "system" ? "high" : "medium",
      projectId: targetScopeType === "project" ? targetScopeId : null,
    });
    return {
      proposal_id: row.id,
      status: row.status,
      proposal_type: row.proposal_type,
    };
  }

  private async requireAsset(spaceId: string, assetId: string): Promise<{ asset_key: string }> {
    const result = await this.db.query<{ asset_key: string }>(
      `SELECT asset_key FROM evolvable_assets WHERE id = $1 AND (space_id = $2 OR space_id IS NULL) LIMIT 1`,
      [assetId, spaceId],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(404, "Evolvable asset not found");
    return row;
  }

  private async versionRow(assetId: string, versionId: string): Promise<{ status: string; version: number } | null> {
    const result = await this.db.query<{ status: string; version: number }>(
      `SELECT status, version FROM evolvable_asset_versions WHERE asset_id = $1 AND id = $2 LIMIT 1`,
      [assetId, versionId],
    );
    return result.rows[0] ?? null;
  }
}

async function assertCanProposePromotionScope(
  db: Queryable,
  identity: SpaceUserIdentity,
  scopeType: string,
  scopeId: string | null,
): Promise<void> {
  if (scopeType === "project") {
    await assertProjectWriter(db, identity.spaceId, scopeId as string, identity.userId);
    return;
  }
  if (scopeType === "space" && scopeId !== identity.spaceId) {
    throw new HttpError(422, "space promotion target_scope_id must match the active space_id");
  }
  const membership = await db.query<{ role: string }>(
    `SELECT role FROM space_memberships WHERE space_id = $1 AND user_id = $2 AND status = 'active' LIMIT 1`,
    [identity.spaceId, identity.userId],
  );
  if (!isSpaceOwnerOrAdmin(membership.rows[0]?.role)) {
    throw new HttpError(403, `Requires space owner/admin role to propose a ${scopeType}-scoped asset promotion`);
  }
}
