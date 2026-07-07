import { randomUUID, createHash } from "node:crypto";
import type { Pool, PoolClient } from "../../../db/pool";
import { withTransaction } from "../../../db/tx";
import { insertProposalRow } from "../../proposals/reviewPackets";
import { HttpError, page, countFromRow, type Queryable } from "../../routeUtils/common";
import { PgSchedulerTaskStore, type SchedulerTaskRow } from "../../scheduler/taskStore";
import { computeNextRunAt, InvalidScheduleError } from "../../automations/schedule";
import type { SourceConnectionRow, IntakeItemRow, EvidenceRow } from "../intakeRepositoryRows";
import { ITEM_COLUMNS, EVIDENCE_COLUMNS, connectionColumnsWithConnectorForAlias } from "../intakeRepositoryRows";
import {
  reindexExtractedEvidenceAndParentForRetrieval,
  reindexIntakeItemAndEvidenceForRetrieval,
} from "../retrievalIndexing";
import {
  enforceSourceRetentionPolicy,
  normalizeSourceConnectionReadGovernance,
} from "../sourceConsent";

export const SOURCE_POST_PROCESSING_EVENT_JOB_TYPE = "source_post_processing_event";
export const SOURCE_POST_PROCESSING_TASK_TYPE = "source_post_processing_rule";

export type SourcePostProcessingTriggerType = "items_materialized" | "schedule" | "manual";
export type SourcePostProcessingRuleStatus = "active" | "paused" | "archived";
export type SourcePostProcessingRunStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";
export type SourcePostProcessingContentProfile = "generic" | "arxiv_new_papers";
export type SourcePostProcessingStrategy = "batch_digest" | "screen_then_digest" | "screen_extract_digest";
export type SourcePostProcessingContentSource =
  | "excerpt_only"
  | "prefer_extracted_text_for_candidates"
  | "require_extracted_text_for_candidates";
export type SourcePostProcessingRetrievalDomain = "knowledge" | "project" | "memory" | "intake";
export type SourcePostProcessingRetrievalMode = "exact" | "lexical" | "hybrid" | "hybrid_rerank";
export type SourcePostProcessingDeepAnalysisContentSource = "prefer_extracted_text" | "require_extracted_text";
export type SourcePostProcessingDeepAnalysisOutput = "deep_report" | "per_item_deep_summary";
export type SourcePostProcessingDecisionReviewStatus =
  | "pending"
  | "accepted"
  | "ignored"
  | "queued"
  | "proposed"
  | "rerun"
  | "dismissed";

export interface SourcePostProcessingActions {
  batch_digest: boolean;
  per_item_summary: boolean;
  extract_evidence: boolean;
  create_proposals: boolean;
  mark_items: boolean;
}

export type SourcePostProcessingItemRelevance = "relevant" | "maybe" | "not_relevant";

export interface SourcePostProcessingItemDecision {
  intake_item_id: string;
  relevance: SourcePostProcessingItemRelevance;
  confidence: number | null;
  reason: string | null;
  matched_context_refs: Record<string, unknown>[];
}

export interface SourcePostProcessingInputConfig {
  window: "new_since_last_success" | "local_day" | "last_24h" | "explicit";
  item_limit: number;
  max_batches_per_event: number;
  processing_strategy: SourcePostProcessingStrategy;
  content_source: SourcePostProcessingContentSource;
  processing_phase?: "standard" | "deep_analysis";
  source_post_processing_parent_run_id?: string | null;
  include_excerpts: boolean;
  include_evidence: boolean;
  timezone: string;
  content_profile?: SourcePostProcessingContentProfile;
  summary_goal?: string;
  output_instructions?: string;
  retrieval_context: SourcePostProcessingRetrievalContextConfig;
  candidate_prefilter: SourcePostProcessingCandidatePrefilterConfig;
  deep_analysis: SourcePostProcessingDeepAnalysisConfig;
  relevance_profile?: SourcePostProcessingRelevanceProfile;
}

export interface SourcePostProcessingCandidatePrefilterConfig {
  enabled: boolean;
  mode: SourcePostProcessingRetrievalMode;
  max_candidates: number;
  min_score?: number;
}

export interface SourcePostProcessingDeepAnalysisConfig {
  enabled: boolean;
  trigger_relevance: Array<"relevant" | "maybe">;
  min_confidence: number;
  max_candidates_per_run: number;
  content_source: SourcePostProcessingDeepAnalysisContentSource;
  output: SourcePostProcessingDeepAnalysisOutput;
}

export interface SourcePostProcessingRetrievalContextConfig {
  enabled: boolean;
  domains: SourcePostProcessingRetrievalDomain[];
  query?: string;
  max_results_per_domain: number;
  mode: SourcePostProcessingRetrievalMode;
}

export interface SourcePostProcessingRelevanceDecisionPolicy {
  relevant?: string;
  maybe?: string;
  not_relevant?: string;
}

export interface SourcePostProcessingRelevanceProfile {
  enabled: boolean;
  objective?: string;
  include_criteria: string[];
  exclude_criteria: string[];
  must_have: string[];
  nice_to_have: string[];
  decision_policy?: SourcePostProcessingRelevanceDecisionPolicy;
}

export interface SourcePostProcessingTriggerConfig {
  min_new_items: number;
  cooldown_seconds: number;
  cron?: string;
  timezone: string;
  skip_when_no_new_items: boolean;
}

export interface SourcePostProcessingRuleRow {
  id: string;
  space_id: string;
  source_connection_id: string;
  agent_id: string;
  project_id: string | null;
  name: string;
  status: SourcePostProcessingRuleStatus;
  trigger_type: SourcePostProcessingTriggerType;
  trigger_config_json: Record<string, unknown>;
  input_config_json: Record<string, unknown>;
  actions_json: Record<string, unknown>;
  cursor_json: Record<string, unknown> | null;
  last_fired_at: unknown;
  created_by_user_id: string;
  created_at: unknown;
  updated_at: unknown;
  next_run_at?: unknown;
}

export interface SourcePostProcessingRunRow {
  id: string;
  space_id: string;
  rule_id: string | null;
  source_connection_id: string;
  agent_id: string;
  project_id: string | null;
  agent_run_id: string | null;
  triggered_by_user_id: string | null;
  trigger_type: SourcePostProcessingTriggerType;
  status: SourcePostProcessingRunStatus;
  input_item_ids_json: unknown;
  input_evidence_ids_json: unknown;
  output_artifact_ids_json: unknown;
  output_proposal_ids_json: unknown;
  output_job_ids_json: unknown;
  cursor_before_json: unknown;
  cursor_after_json: unknown;
  retrieval_context_json: unknown;
  item_decisions_json: unknown;
  summary: string | null;
  error_json: unknown;
  started_at: unknown;
  completed_at: unknown;
  created_at: unknown;
}

export interface SourcePostProcessingItemDecisionRow {
  id: string;
  space_id: string;
  source_connection_id: string;
  rule_id: string | null;
  run_id: string;
  project_id: string | null;
  intake_item_id: string;
  relevance: SourcePostProcessingItemRelevance;
  confidence: number | null;
  reason: string | null;
  matched_context_refs_json: unknown;
  applied_item_status: string | null;
  review_status: SourcePostProcessingDecisionReviewStatus;
  action_json: unknown;
  created_at: unknown;
  updated_at: unknown;
  item_title?: string | null;
  item_source_uri?: string | null;
  item_source_domain?: string | null;
  item_author?: string | null;
  item_status?: string | null;
  item_content_state?: string | null;
  rule_name?: string | null;
  run_status?: string | null;
  run_created_at?: unknown;
}

export interface SourcePostProcessingRuleOut {
  id: string;
  space_id: string;
  source_connection_id: string;
  agent_id: string;
  project_id: string | null;
  name: string;
  status: SourcePostProcessingRuleStatus;
  trigger_type: SourcePostProcessingTriggerType;
  trigger_config_json: SourcePostProcessingTriggerConfig;
  input_config_json: SourcePostProcessingInputConfig;
  actions_json: SourcePostProcessingActions;
  cursor_json: Record<string, unknown> | null;
  last_fired_at: string | null;
  next_run_at: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface SourcePostProcessingRunOut {
  id: string;
  space_id: string;
  rule_id: string | null;
  source_connection_id: string;
  agent_id: string;
  project_id: string | null;
  agent_run_id: string | null;
  triggered_by_user_id: string | null;
  trigger_type: SourcePostProcessingTriggerType;
  status: SourcePostProcessingRunStatus;
  input_item_ids: string[];
  input_evidence_ids: string[];
  output_artifact_ids: string[];
  output_proposal_ids: string[];
  output_job_ids: string[];
  cursor_before_json: Record<string, unknown> | null;
  cursor_after_json: Record<string, unknown> | null;
  retrieval_context_json: Record<string, unknown>;
  item_decisions_json: Record<string, unknown>[];
  summary: string | null;
  error_json: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface SourcePostProcessingItemDecisionOut {
  id: string;
  space_id: string;
  source_connection_id: string;
  rule_id: string | null;
  run_id: string;
  project_id: string | null;
  intake_item_id: string;
  relevance: SourcePostProcessingItemRelevance;
  confidence: number | null;
  reason: string | null;
  matched_context_refs: Record<string, unknown>[];
  applied_item_status: string | null;
  review_status: SourcePostProcessingDecisionReviewStatus;
  action_json: Record<string, unknown>;
  item: {
    title: string | null;
    source_uri: string | null;
    source_domain: string | null;
    author: string | null;
    status: string | null;
    content_state: string | null;
  };
  rule_name: string | null;
  run_status: string | null;
  run_created_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourcePostProcessingBacklogRuleOut {
  rule_id: string;
  rule_name: string;
  status: SourcePostProcessingRuleStatus;
  trigger_type: SourcePostProcessingTriggerType;
  pending_item_count: number;
  batch_size: number;
  max_batches_per_event: number;
  cursor_json: Record<string, unknown> | null;
  last_fired_at: string | null;
  last_run: SourcePostProcessingRunOut | null;
  last_success_run: SourcePostProcessingRunOut | null;
  last_failed_run: SourcePostProcessingRunOut | null;
}

export interface SourcePostProcessingBacklogOut {
  source_connection_id: string;
  rules: SourcePostProcessingBacklogRuleOut[];
}

export interface IntakeWatermark {
  created_at: string;
  id: string;
}

export interface SourcePostProcessingInputBatch {
  items: IntakeItemRow[];
  evidence: EvidenceRow[];
  cursorBefore: IntakeWatermark | null;
  cursorAfter: IntakeWatermark | null;
}

const RULE_COLUMNS = `
  id, space_id, source_connection_id, agent_id, project_id, name, status,
  trigger_type, trigger_config_json, input_config_json, actions_json,
  cursor_json, last_fired_at, created_by_user_id, created_at, updated_at
`;

const RUN_COLUMNS = `
  id, space_id, rule_id, source_connection_id, agent_id, project_id, agent_run_id,
  triggered_by_user_id, trigger_type, status, input_item_ids_json,
  input_evidence_ids_json, output_artifact_ids_json, output_proposal_ids_json,
  output_job_ids_json, cursor_before_json, cursor_after_json, summary, error_json,
  retrieval_context_json, item_decisions_json, started_at, completed_at, created_at
`;

const DECISION_COLUMNS = `
  d.id, d.space_id, d.source_connection_id, d.rule_id, d.run_id, d.project_id,
  d.intake_item_id, d.relevance, d.confidence, d.reason,
  d.matched_context_refs_json, d.applied_item_status, d.review_status,
  d.action_json, d.created_at, d.updated_at,
  ii.title AS item_title, ii.source_uri AS item_source_uri,
  ii.source_domain AS item_source_domain, ii.author AS item_author,
  ii.status AS item_status, ii.content_state AS item_content_state,
  r.name AS rule_name, pr.status AS run_status, pr.created_at AS run_created_at
`;

export class PgSourcePostProcessingRepository {
  private readonly scheduler: PgSchedulerTaskStore;

  constructor(private readonly db: Queryable) {
    this.scheduler = new PgSchedulerTaskStore(db);
  }

  async getConnection(spaceId: string, connectionId: string): Promise<SourceConnectionRow | null> {
    const result = await this.db.query<SourceConnectionRow>(
      `SELECT ${connectionColumnsWithConnectorForAlias("sc", "c")}
         FROM source_connections sc
         JOIN source_connectors c ON c.id = sc.connector_id
        WHERE sc.space_id = $1 AND sc.id = $2 AND sc.deleted_at IS NULL
        LIMIT 1`,
      [spaceId, connectionId],
    );
    return result.rows[0] ?? null;
  }

  async getRule(spaceId: string, ruleId: string): Promise<SourcePostProcessingRuleRow | null> {
    const result = await this.db.query<SourcePostProcessingRuleRow>(
      `SELECT ${RULE_COLUMNS}
         FROM source_post_processing_rules
        WHERE space_id = $1 AND id = $2
        LIMIT 1`,
      [spaceId, ruleId],
    );
    return result.rows[0] ? this.withSchedule(result.rows[0]) : null;
  }

  async listRules(spaceId: string, connectionId: string): Promise<SourcePostProcessingRuleOut[]> {
    const result = await this.db.query<SourcePostProcessingRuleRow>(
      `SELECT ${RULE_COLUMNS}
         FROM source_post_processing_rules
        WHERE space_id = $1 AND source_connection_id = $2
        ORDER BY created_at DESC, id DESC`,
      [spaceId, connectionId],
    );
    const rows = await Promise.all(result.rows.map((row) => this.withSchedule(row)));
    return rows.map(ruleOut);
  }

  async listActiveRulesForSource(
    spaceId: string,
    connectionId: string,
    triggerType: SourcePostProcessingTriggerType,
  ): Promise<SourcePostProcessingRuleRow[]> {
    const result = await this.db.query<SourcePostProcessingRuleRow>(
      `SELECT ${RULE_COLUMNS}
         FROM source_post_processing_rules
        WHERE space_id = $1
          AND source_connection_id = $2
          AND trigger_type = $3
          AND status = 'active'
        ORDER BY created_at ASC, id ASC`,
      [spaceId, connectionId, triggerType],
    );
    return result.rows;
  }

  async listRuns(
    spaceId: string,
    connectionId: string,
    limit: number,
    offset: number,
  ): Promise<{ items: SourcePostProcessingRunOut[]; total: number; limit: number; offset: number }> {
    const total = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total
         FROM source_post_processing_runs
        WHERE space_id = $1 AND source_connection_id = $2`,
      [spaceId, connectionId],
    );
    const result = await this.db.query<SourcePostProcessingRunRow>(
      `SELECT ${RUN_COLUMNS}
         FROM source_post_processing_runs
        WHERE space_id = $1 AND source_connection_id = $2
        ORDER BY created_at DESC, id DESC
        LIMIT $3 OFFSET $4`,
      [spaceId, connectionId, limit, offset],
    );
    return page(result.rows.map(runOut), countFromRow(total.rows[0]), limit, offset);
  }

  async backlog(spaceId: string, connectionId: string): Promise<SourcePostProcessingBacklogOut> {
    const rulesResult = await this.db.query<SourcePostProcessingRuleRow>(
      `SELECT ${RULE_COLUMNS}
         FROM source_post_processing_rules
        WHERE space_id = $1
          AND source_connection_id = $2
          AND status <> 'archived'
        ORDER BY created_at ASC, id ASC`,
      [spaceId, connectionId],
    );
    const rules: SourcePostProcessingBacklogRuleOut[] = [];
    for (const rule of rulesResult.rows) {
      const inputConfig = normalizeInputConfig(rule.input_config_json);
      const [pendingItemCount, recentRuns] = await Promise.all([
        this.countPendingItemsForRule(rule),
        this.recentRunsForRule(spaceId, rule.id),
      ]);
      rules.push({
        rule_id: rule.id,
        rule_name: rule.name,
        status: rule.status,
        trigger_type: rule.trigger_type,
        pending_item_count: pendingItemCount,
        batch_size: inputConfig.item_limit,
        max_batches_per_event: inputConfig.max_batches_per_event,
        cursor_json: recordValue(rule.cursor_json),
        last_fired_at: timestampString(rule.last_fired_at),
        last_run: recentRuns[0] ?? null,
        last_success_run: recentRuns.find((run) => run.status === "succeeded") ?? null,
        last_failed_run: recentRuns.find((run) => run.status === "failed") ?? null,
      });
    }
    return { source_connection_id: connectionId, rules };
  }

  async listDecisions(input: {
    spaceId: string;
    connectionId?: string | null;
    projectId?: string | null;
    ruleId?: string | null;
    relevance?: SourcePostProcessingItemRelevance | null;
    reviewStatus?: SourcePostProcessingDecisionReviewStatus | null;
    limit: number;
    offset: number;
  }): Promise<{ items: SourcePostProcessingItemDecisionOut[]; total: number; limit: number; offset: number }> {
    const { where, params } = decisionListWhere(input);
    const total = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total
         FROM source_post_processing_item_decisions d
        WHERE ${where}`,
      params,
    );
    const result = await this.db.query<SourcePostProcessingItemDecisionRow>(
      `SELECT ${DECISION_COLUMNS}
         FROM source_post_processing_item_decisions d
         JOIN intake_items ii
           ON ii.space_id = d.space_id
          AND ii.id = d.intake_item_id
         LEFT JOIN source_post_processing_rules r
           ON r.space_id = d.space_id
          AND r.id = d.rule_id
         LEFT JOIN source_post_processing_runs pr
           ON pr.space_id = d.space_id
          AND pr.id = d.run_id
        WHERE ${where}
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, input.limit, input.offset],
    );
    return page(result.rows.map(decisionOut), countFromRow(total.rows[0]), input.limit, input.offset);
  }

  async getDecision(spaceId: string, decisionId: string): Promise<SourcePostProcessingItemDecisionOut | null> {
    const result = await this.db.query<SourcePostProcessingItemDecisionRow>(
      `SELECT ${DECISION_COLUMNS}
         FROM source_post_processing_item_decisions d
         JOIN intake_items ii
           ON ii.space_id = d.space_id
          AND ii.id = d.intake_item_id
         LEFT JOIN source_post_processing_rules r
           ON r.space_id = d.space_id
          AND r.id = d.rule_id
         LEFT JOIN source_post_processing_runs pr
           ON pr.space_id = d.space_id
          AND pr.id = d.run_id
        WHERE d.space_id = $1 AND d.id = $2
        LIMIT 1`,
      [spaceId, decisionId],
    );
    return result.rows[0] ? decisionOut(result.rows[0]) : null;
  }

  async createRule(input: {
    spaceId: string;
    sourceConnectionId: string;
    agentId: string;
    projectId: string | null;
    name: string;
    triggerType: SourcePostProcessingTriggerType;
    triggerConfig: SourcePostProcessingTriggerConfig;
    inputConfig: SourcePostProcessingInputConfig;
    actions: SourcePostProcessingActions;
    createdByUserId: string;
  }): Promise<SourcePostProcessingRuleOut> {
    const write = async (db: Queryable) => {
      const id = randomUUID();
      const now = new Date().toISOString();
      const result = await db.query<SourcePostProcessingRuleRow>(
        `INSERT INTO source_post_processing_rules (
           id, space_id, source_connection_id, agent_id, project_id, name, status,
           trigger_type, trigger_config_json, input_config_json, actions_json,
           cursor_json, created_by_user_id, created_at, updated_at
         ) VALUES (
           $1, $2, $3, $4, $5, $6, 'active',
           $7, $8::jsonb, $9::jsonb, $10::jsonb,
           NULL, $11, $12, $12
         )
         RETURNING ${RULE_COLUMNS}`,
        [
          id,
          input.spaceId,
          input.sourceConnectionId,
          input.agentId,
          input.projectId,
          input.name,
          input.triggerType,
          JSON.stringify(input.triggerConfig),
          JSON.stringify(input.inputConfig),
          JSON.stringify(input.actions),
          input.createdByUserId,
          now,
        ],
      );
      const row = result.rows[0];
      if (!row) throw new Error("Post-processing rule insert returned no row");
      const task = await new PgSourcePostProcessingRepository(db).upsertRuleSchedule(row, now);
      return ruleOut({ ...row, next_run_at: task?.next_run_at ?? null });
    };
    return isPool(this.db) ? withTransaction(this.db, write) : write(this.db);
  }

  async updateRule(
    spaceId: string,
    ruleId: string,
    patch: {
      name?: string;
      agentId?: string;
      projectId?: string | null;
      status?: SourcePostProcessingRuleStatus;
      triggerType?: SourcePostProcessingTriggerType;
      triggerConfig?: SourcePostProcessingTriggerConfig;
      inputConfig?: SourcePostProcessingInputConfig;
      actions?: SourcePostProcessingActions;
    },
  ): Promise<SourcePostProcessingRuleOut> {
    const existing = await this.getRule(spaceId, ruleId);
    if (!existing) throw new HttpError(404, "Post-processing rule not found");
    const now = new Date().toISOString();
    const setProject = patch.projectId !== undefined;
    const result = await this.db.query<SourcePostProcessingRuleRow>(
      `UPDATE source_post_processing_rules
          SET name = COALESCE($3, name),
              agent_id = COALESCE($4, agent_id),
              project_id = CASE WHEN $5::boolean THEN $6 ELSE project_id END,
              status = COALESCE($7, status),
              trigger_type = COALESCE($8, trigger_type),
              trigger_config_json = COALESCE($9::jsonb, trigger_config_json),
              input_config_json = COALESCE($10::jsonb, input_config_json),
              actions_json = COALESCE($11::jsonb, actions_json),
              updated_at = $12
        WHERE space_id = $1 AND id = $2
        RETURNING ${RULE_COLUMNS}`,
      [
        spaceId,
        ruleId,
        patch.name ?? null,
        patch.agentId ?? null,
        setProject,
        patch.projectId ?? null,
        patch.status ?? null,
        patch.triggerType ?? null,
        patch.triggerConfig ? JSON.stringify(patch.triggerConfig) : null,
        patch.inputConfig ? JSON.stringify(patch.inputConfig) : null,
        patch.actions ? JSON.stringify(patch.actions) : null,
        now,
      ],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(404, "Post-processing rule not found");
    const task = await this.upsertRuleSchedule(row, now);
    return ruleOut({ ...row, next_run_at: task?.next_run_at ?? null });
  }

  async createRun(input: {
    spaceId: string;
    ruleId: string | null;
    sourceConnectionId: string;
    agentId: string;
    projectId: string | null;
    triggeredByUserId: string | null;
    triggerType: SourcePostProcessingTriggerType;
    inputItemIds: string[];
    inputEvidenceIds: string[];
    cursorBefore: IntakeWatermark | null;
    cursorAfter: IntakeWatermark | null;
  }): Promise<SourcePostProcessingRunRow> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const result = await this.db.query<SourcePostProcessingRunRow>(
      `INSERT INTO source_post_processing_runs (
         id, space_id, rule_id, source_connection_id, agent_id, project_id,
         triggered_by_user_id, trigger_type, status, input_item_ids_json,
         input_evidence_ids_json, cursor_before_json, cursor_after_json,
         started_at, created_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8, 'running', $9::jsonb,
         $10::jsonb, $11::jsonb, $12::jsonb,
         $13, $13
       )
       RETURNING ${RUN_COLUMNS}`,
      [
        id,
        input.spaceId,
        input.ruleId,
        input.sourceConnectionId,
        input.agentId,
        input.projectId,
        input.triggeredByUserId,
        input.triggerType,
        JSON.stringify(input.inputItemIds),
        JSON.stringify(input.inputEvidenceIds),
        input.cursorBefore ? JSON.stringify(input.cursorBefore) : null,
        input.cursorAfter ? JSON.stringify(input.cursorAfter) : null,
        now,
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("Post-processing run insert returned no row");
    return row;
  }

  async markRunFinished(input: {
    runId: string;
    spaceId: string;
    status: SourcePostProcessingRunStatus;
    agentRunId?: string | null;
    outputArtifactIds?: string[];
    outputProposalIds?: string[];
    outputJobIds?: string[];
    retrievalContext?: Record<string, unknown> | null;
    itemDecisions?: Record<string, unknown>[];
    summary?: string | null;
    errorJson?: Record<string, unknown> | null;
  }): Promise<SourcePostProcessingRunOut> {
    const now = new Date().toISOString();
    const result = await this.db.query<SourcePostProcessingRunRow>(
      `UPDATE source_post_processing_runs
          SET status = $3,
              agent_run_id = COALESCE($4, agent_run_id),
              output_artifact_ids_json = $5::jsonb,
              output_proposal_ids_json = $6::jsonb,
              output_job_ids_json = $7::jsonb,
              retrieval_context_json = COALESCE($8::jsonb, retrieval_context_json),
              item_decisions_json = COALESCE($9::jsonb, item_decisions_json),
              summary = $10,
              error_json = $11::jsonb,
              completed_at = $12
        WHERE space_id = $1 AND id = $2
        RETURNING ${RUN_COLUMNS}`,
      [
        input.spaceId,
        input.runId,
        input.status,
        input.agentRunId ?? null,
        JSON.stringify(input.outputArtifactIds ?? []),
        JSON.stringify(input.outputProposalIds ?? []),
        JSON.stringify(input.outputJobIds ?? []),
        input.retrievalContext ? JSON.stringify(input.retrievalContext) : null,
        input.itemDecisions ? JSON.stringify(input.itemDecisions) : null,
        input.summary ?? null,
        input.errorJson ? JSON.stringify(input.errorJson) : null,
        now,
      ],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(404, "Post-processing run not found");
    return runOut(row);
  }

  async updateRunAgentRunId(spaceId: string, postProcessingRunId: string, agentRunId: string): Promise<void> {
    await this.db.query(
      `UPDATE source_post_processing_runs
          SET agent_run_id = $3
        WHERE space_id = $1 AND id = $2`,
      [spaceId, postProcessingRunId, agentRunId],
    );
  }

  async persistItemDecisions(input: {
    spaceId: string;
    sourceConnectionId: string;
    ruleId: string | null;
    runId: string;
    projectId: string | null;
    decisions: SourcePostProcessingItemDecision[];
    appliedByMarkItems: boolean;
  }): Promise<void> {
    if (!input.decisions.length) return;
    const now = new Date().toISOString();
    for (const decision of input.decisions) {
      const appliedStatus = input.appliedByMarkItems ? itemStatusForRelevance(decision.relevance) : null;
      const reviewStatus: SourcePostProcessingDecisionReviewStatus = input.appliedByMarkItems ? "accepted" : "pending";
      await this.db.query(
        `INSERT INTO source_post_processing_item_decisions (
           id, space_id, source_connection_id, rule_id, run_id, project_id,
           intake_item_id, relevance, confidence, reason, matched_context_refs_json,
           applied_item_status, review_status, action_json, created_at, updated_at
         ) VALUES (
           $1, $2, $3, $4, $5, $6,
           $7, $8, $9, $10, $11::jsonb,
           $12, $13, '{}'::jsonb, $14, $14
         )
         ON CONFLICT (space_id, run_id, intake_item_id)
         DO UPDATE SET relevance = EXCLUDED.relevance,
                       confidence = EXCLUDED.confidence,
                       reason = EXCLUDED.reason,
                       matched_context_refs_json = EXCLUDED.matched_context_refs_json,
                       applied_item_status = EXCLUDED.applied_item_status,
                       review_status = EXCLUDED.review_status,
                       updated_at = EXCLUDED.updated_at`,
        [
          randomUUID(),
          input.spaceId,
          input.sourceConnectionId,
          input.ruleId,
          input.runId,
          input.projectId,
          decision.intake_item_id,
          decision.relevance,
          decision.confidence,
          decision.reason,
          JSON.stringify(decision.matched_context_refs),
          appliedStatus,
          reviewStatus,
          now,
        ],
      );
    }
  }

  async updateDecisionReview(input: {
    spaceId: string;
    decisionId: string;
    reviewStatus: SourcePostProcessingDecisionReviewStatus;
    appliedItemStatus?: string | null;
    action: Record<string, unknown>;
  }): Promise<SourcePostProcessingItemDecisionOut> {
    const now = new Date().toISOString();
    const setApplied = Object.hasOwn(input, "appliedItemStatus");
    const result = await this.db.query<SourcePostProcessingItemDecisionRow>(
      `WITH updated AS (
         UPDATE source_post_processing_item_decisions
            SET review_status = $3,
                applied_item_status = CASE WHEN $4::boolean THEN $5 ELSE applied_item_status END,
                action_json = action_json || $6::jsonb,
                updated_at = $7
          WHERE space_id = $1 AND id = $2
          RETURNING *
       )
       SELECT ${DECISION_COLUMNS}
         FROM updated d
         JOIN intake_items ii
           ON ii.space_id = d.space_id
          AND ii.id = d.intake_item_id
         LEFT JOIN source_post_processing_rules r
           ON r.space_id = d.space_id
          AND r.id = d.rule_id
         LEFT JOIN source_post_processing_runs pr
           ON pr.space_id = d.space_id
          AND pr.id = d.run_id`,
      [
        input.spaceId,
        input.decisionId,
        input.reviewStatus,
        setApplied,
        input.appliedItemStatus ?? null,
        JSON.stringify(input.action),
        now,
      ],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(404, "Post-processing decision not found");
    return decisionOut(row);
  }

  async advanceRuleCursor(input: {
    spaceId: string;
    ruleId: string;
    cursor: IntakeWatermark | null;
  }): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE source_post_processing_rules
          SET cursor_json = $3::jsonb,
              last_fired_at = $4,
              updated_at = $4
        WHERE space_id = $1 AND id = $2`,
      [
        input.spaceId,
        input.ruleId,
        input.cursor ? JSON.stringify({ intake_watermark: input.cursor }) : null,
        now,
      ],
    );
  }

  async recordRuleFire(spaceId: string, ruleId: string): Promise<void> {
    const rule = await this.getRule(spaceId, ruleId);
    if (!rule) return;
    const now = new Date().toISOString();
    await this.upsertRuleSchedule(rule, now, true);
  }

  async hasInFlightRun(spaceId: string, ruleId: string): Promise<boolean> {
    const result = await this.db.query<{ id: string }>(
      `SELECT id
         FROM source_post_processing_runs
        WHERE space_id = $1
          AND rule_id = $2
          AND status IN ('queued', 'running')
        LIMIT 1`,
      [spaceId, ruleId],
    );
    return Boolean(result.rows[0]);
  }

  async collectInputBatch(input: {
    spaceId: string;
    sourceConnectionId: string;
    inputConfig: SourcePostProcessingInputConfig;
    cursor: IntakeWatermark | null;
    explicitItemIds?: string[];
    explicitEvidenceIds?: string[];
  }): Promise<SourcePostProcessingInputBatch> {
    const itemIds = input.explicitItemIds ?? [];
    const evidenceIds = input.explicitEvidenceIds ?? [];
    let items: IntakeItemRow[];
    let cursorAfter: IntakeWatermark | null = null;

    if (input.inputConfig.window === "explicit") {
      items = itemIds.length
        ? await this.findItemsByIds(input.spaceId, input.sourceConnectionId, itemIds)
        : [];
    } else {
      const result = await this.findItemsForWindow(input);
      items = result.items;
      cursorAfter = result.cursorAfter;
    }

    const evidence = evidenceIds.length
      ? await this.findEvidenceByIds(input.spaceId, input.sourceConnectionId, evidenceIds)
      : input.inputConfig.include_evidence && items.length
        ? await this.findEvidenceForItems(input.spaceId, items.map((item) => item.id))
        : [];

    return {
      items,
      evidence,
      cursorBefore: input.cursor,
      cursorAfter,
    };
  }

  async insertArtifact(input: {
    spaceId: string;
    runId: string | null;
    ownerUserId: string | null;
    projectId: string | null;
    artifactType: string;
    title: string;
    content: string;
    metadata: Record<string, unknown>;
  }): Promise<string> {
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO artifacts (
         id, space_id, run_id, proposal_id, artifact_type, title, content,
         storage_ref, storage_path, mime_type, exportable, export_formats_json,
         canonical_format, preview, relevant_period_start, relevant_period_end,
         created_at, updated_at, metadata_json, visibility, owner_user_id,
         trust_level, project_id, workspace_id
       ) VALUES (
         $1, $2, $3, NULL, $4, $5, $6,
         NULL, NULL, 'text/markdown; charset=utf-8', true, $7::jsonb,
         'markdown', false, NULL, NULL,
         $8, $8, $9::jsonb, 'space_shared', $10,
         'medium', $11, NULL
       )`,
      [
        id,
        input.spaceId,
        input.runId,
        input.artifactType,
        input.title,
        input.content,
        JSON.stringify(["markdown", "txt"]),
        now,
        JSON.stringify(input.metadata),
        input.ownerUserId,
        input.projectId,
      ],
    );
    return id;
  }

  async insertEvidence(input: {
    spaceId: string;
    item: IntakeItemRow;
    artifactId: string | null;
    title: string;
    content: string;
    createdByUserId: string | null;
    createdByAgentId: string | null;
    createdByRunId: string | null;
    metadata: Record<string, unknown>;
  }): Promise<string> {
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO extracted_evidence (
         id, space_id, intake_item_id, extraction_job_id, source_snapshot_id,
         source_object_type, source_object_id, evidence_type, title,
         content_excerpt, content_hash, artifact_id, source_uri, source_title,
         source_author, occurred_at, trust_level, extraction_method, confidence,
         status, metadata_json, created_by_user_id, created_by_agent_id,
         created_by_run_id, created_at, updated_at
       ) VALUES (
         $1, $2, $3, NULL, NULL,
         $4, $5, 'summary', $6,
         $7, $8, $9, $10, $11,
         $12, $13::timestamptz, 'normal', 'source_post_processing', 0.7,
         'candidate', $14::jsonb, $15, $16,
         $17, $18, $18
       )`,
      [
        id,
        input.spaceId,
        input.item.id,
        input.item.source_object_type,
        input.item.source_object_id,
        input.title,
        input.content.slice(0, 4000),
        sha256(input.content),
        input.artifactId,
        input.item.source_uri,
        input.item.title,
        input.item.author,
        timestampString(input.item.occurred_at),
        JSON.stringify(input.metadata),
        input.createdByUserId,
        input.createdByAgentId,
        input.createdByRunId,
        now,
      ],
    );
    await reindexExtractedEvidenceAndParentForRetrieval(this.db, {
      spaceId: input.spaceId,
      evidenceId: id,
      trigger: "source_post_processing_evidence",
    }).catch((error) => {
      process.stderr.write(
        `[intake.retrieval] evidence reindex failed (${id}): ${String((error as Error)?.message ?? error)}\n`,
      );
    });
    return id;
  }

  async insertProposal(input: {
    spaceId: string;
    runId: string | null;
    agentId: string | null;
    userId: string | null;
    projectId: string | null;
    title: string;
    summary: string;
    payload: Record<string, unknown>;
  }): Promise<string> {
    const row = await insertProposalRow(this.db, {
      spaceId: input.spaceId,
      proposalType: "knowledge_create",
      title: input.title,
      summary: input.summary.slice(0, 1000),
      payload: input.payload,
      rationale: "Source post-processing created a proposal without directly mutating durable knowledge.",
      createdByUserId: input.userId,
      createdByAgentId: input.agentId,
      createdByRunId: input.runId,
      visibility: "space_shared",
      riskLevel: "low",
      urgency: "normal",
      projectId: input.projectId,
    });
    return row.id;
  }

  async updateItemSummary(spaceId: string, itemId: string, artifactId: string): Promise<void> {
    await this.db.query(
      `UPDATE intake_items
          SET summary_artifact_id = $3,
              updated_at = $4
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [spaceId, itemId, artifactId, new Date().toISOString()],
    );
  }

  async markItemsReviewed(spaceId: string, itemIds: string[]): Promise<void> {
    if (!itemIds.length) return;
    await this.db.query(
      `UPDATE intake_items
          SET read_status = 'read',
              updated_at = $3
        WHERE space_id = $1 AND id::text = ANY($2::text[]) AND deleted_at IS NULL`,
      [spaceId, itemIds, new Date().toISOString()],
    );
  }

  async applyItemDecisions(spaceId: string, decisions: SourcePostProcessingItemDecision[]): Promise<void> {
    if (!decisions.length) return;
    const now = new Date().toISOString();
    const selectedIds = decisions
      .filter((decision) => decision.relevance === "relevant")
      .map((decision) => decision.intake_item_id);
    const triagedIds = decisions
      .filter((decision) => decision.relevance === "maybe")
      .map((decision) => decision.intake_item_id);
    const ignoredIds = decisions
      .filter((decision) => decision.relevance === "not_relevant")
      .map((decision) => decision.intake_item_id);
    await this.db.query(
      `UPDATE intake_items
          SET status = CASE
                WHEN id::text = ANY($2::text[]) THEN 'selected'
                WHEN id::text = ANY($3::text[]) THEN 'triaged'
                WHEN id::text = ANY($4::text[]) THEN 'ignored'
                ELSE status
              END,
              updated_at = $5
        WHERE space_id = $1
          AND id::text = ANY($6::text[])
          AND deleted_at IS NULL`,
      [
        spaceId,
        selectedIds,
        triagedIds,
        ignoredIds,
        now,
        decisions.map((decision) => decision.intake_item_id),
      ],
    );
    for (const itemId of [...new Set(decisions.map((decision) => decision.intake_item_id))]) {
      await reindexIntakeItemAndEvidenceForRetrieval(this.db, {
        spaceId,
        itemId,
        trigger: "source_post_processing_item_decision",
      }).catch((error) => {
        process.stderr.write(
          `[intake.retrieval] item reindex failed after post-processing decision (${itemId}): ${String((error as Error)?.message ?? error)}\n`,
        );
      });
    }
  }

  async setItemStatus(spaceId: string, itemId: string, status: "selected" | "triaged" | "ignored"): Promise<void> {
    await this.db.query(
      `UPDATE intake_items
          SET status = $3,
              updated_at = $4
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [spaceId, itemId, status, new Date().toISOString()],
    );
    await reindexIntakeItemAndEvidenceForRetrieval(this.db, {
      spaceId,
      itemId,
      trigger: "source_post_processing_decision_review",
    }).catch((error) => {
      process.stderr.write(
        `[intake.retrieval] item reindex failed after decision review (${itemId}): ${String((error as Error)?.message ?? error)}\n`,
      );
    });
  }

  async loadExtractedTextSnippets(spaceId: string, itemIds: string[], maxChars: number): Promise<Map<string, string>> {
    if (!itemIds.length) return new Map();
    const result = await this.db.query<{ id: string; content: string | null }>(
      `SELECT ii.id, a.content
         FROM intake_items ii
         JOIN artifacts a
           ON a.space_id = ii.space_id
          AND a.id = ii.extracted_artifact_id
        WHERE ii.space_id = $1
          AND ii.id::text = ANY($2::text[])
          AND ii.deleted_at IS NULL
          AND ii.extracted_artifact_id IS NOT NULL
          AND a.content IS NOT NULL`,
      [spaceId, itemIds],
    );
    const snippets = new Map<string, string>();
    for (const row of result.rows) {
      const text = row.content?.trim();
      if (text) snippets.set(row.id, text.slice(0, maxChars));
    }
    return snippets;
  }

  async queueFullTextExtractionForItems(input: {
    spaceId: string;
    connection: SourceConnectionRow;
    itemIds: string[];
    metadata: Record<string, unknown>;
  }): Promise<string[]> {
    if (!input.itemIds.length) return [];
    const governance = normalizeSourceConnectionReadGovernance(input.connection);
    enforceSourceRetentionPolicy(governance.policy, "full_text");
    const now = new Date().toISOString();
    const result = await this.db.query<{ id: string; intake_item_id: string }>(
      `WITH existing AS (
         UPDATE extraction_jobs ej
            SET metadata_json = CASE
              WHEN $5::jsonb ? 'source_post_processing_followups' THEN
                (COALESCE(ej.metadata_json, '{}'::jsonb) || ($5::jsonb - 'source_post_processing_followups'))
                || jsonb_build_object(
                  'source_post_processing_followups',
                  COALESCE(
                    CASE
                      WHEN jsonb_typeof(ej.metadata_json->'source_post_processing_followups') = 'array'
                      THEN ej.metadata_json->'source_post_processing_followups'
                    END,
                    '[]'::jsonb
                  )
                  || COALESCE(
                    CASE
                      WHEN jsonb_typeof($5::jsonb->'source_post_processing_followups') = 'array'
                      THEN $5::jsonb->'source_post_processing_followups'
                    END,
                    '[]'::jsonb
                  )
                )
              ELSE COALESCE(ej.metadata_json, '{}'::jsonb) || $5::jsonb
            END
          WHERE ej.space_id = $1
            AND ej.intake_item_id::text = ANY($2::text[])
            AND ej.job_type = 'extract_text'
            AND ej.status IN ('pending', 'running')
          RETURNING ej.id, ej.intake_item_id
       ), eligible AS (
         SELECT ii.id
           FROM intake_items ii
          WHERE ii.space_id = $1
            AND ii.id::text = ANY($2::text[])
            AND ii.deleted_at IS NULL
            AND ii.content_state <> 'content_saved'
            AND NOT EXISTS (
              SELECT 1 FROM existing ex WHERE ex.intake_item_id = ii.id
            )
       ), updated AS (
         UPDATE intake_items ii
            SET content_state = 'content_queued',
                retention_policy = 'full_text',
                updated_at = $4
           FROM eligible e
          WHERE ii.space_id = $1 AND ii.id = e.id
          RETURNING ii.id
       ), inserted AS (
         INSERT INTO extraction_jobs (
           id, space_id, connection_id, intake_item_id, job_type, status,
           metadata_json, created_at
         )
         SELECT gen_random_uuid()::text, $1, $3, id, 'extract_text', 'pending', $5::jsonb, $4
           FROM updated
         RETURNING id, intake_item_id
       )
       SELECT id, intake_item_id FROM inserted
       UNION ALL
       SELECT id, intake_item_id FROM existing`,
      [
        input.spaceId,
        input.itemIds,
        input.connection.id,
        now,
        JSON.stringify(input.metadata),
      ],
    );
    return result.rows.map((row) => row.id);
  }

  async appendRunOutputJobIds(spaceId: string, runId: string, jobIds: string[]): Promise<void> {
    const ids = [...new Set(jobIds.filter((id) => typeof id === "string" && id.trim().length > 0))];
    if (!ids.length) return;
    await this.db.query(
      `UPDATE source_post_processing_runs
          SET output_job_ids_json = COALESCE((
                SELECT jsonb_agg(value ORDER BY value)
                  FROM (
                    SELECT DISTINCT value
                      FROM (
                        SELECT jsonb_array_elements_text(COALESCE(output_job_ids_json, '[]'::jsonb)) AS value
                        UNION ALL
                        SELECT unnest($3::text[]) AS value
                      ) merged
                     WHERE value <> ''
                  ) deduped
              ), '[]'::jsonb)
        WHERE space_id = $1 AND id = $2`,
      [spaceId, runId, ids],
    );
  }

  async linkEvidenceToProject(input: {
    spaceId: string;
    evidenceId: string;
    projectId: string;
    createdByUserId: string | null;
    createdByAgentId: string | null;
    createdByRunId: string | null;
    reason: string;
  }): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO evidence_links (
         id, space_id, evidence_id, target_type, target_id, link_type,
         status, confidence, reason, created_by_user_id, created_by_agent_id,
         created_by_run_id, created_at, updated_at
       ) VALUES (
         $1, $2, $3, 'project', $4, 'context_candidate',
         'active', 0.7, $5, $6, $7,
         $8, $9, $9
       )
       ON CONFLICT (space_id, evidence_id, target_type, target_id, link_type)
         WHERE status = 'active'
       DO NOTHING`,
      [
        randomUUID(),
        input.spaceId,
        input.evidenceId,
        input.projectId,
        input.reason,
        input.createdByUserId,
        input.createdByAgentId,
        input.createdByRunId,
        now,
      ],
    );
  }

  async listDueRules(nowIso: string, limit = 25): Promise<SourcePostProcessingRuleRow[]> {
    const tasks = await this.scheduler.listDue(SOURCE_POST_PROCESSING_TASK_TYPE, nowIso, limit);
    const rules: SourcePostProcessingRuleRow[] = [];
    for (const task of tasks) {
      if (!task.space_id) continue;
      const row = await this.getRule(task.space_id, task.task_key);
      if (row && row.status === "active" && row.trigger_type === "schedule") rules.push(row);
    }
    return rules;
  }

  private async upsertRuleSchedule(
    rule: SourcePostProcessingRuleRow,
    now: string,
    fired = false,
  ): Promise<SchedulerTaskRow | null> {
    const status = schedulerStatus(rule);
    let nextRunAt: string | null = null;
    if (status === "active" && rule.trigger_type === "schedule") {
      try {
        nextRunAt = computeNextRunAt(rule.trigger_config_json, new Date(now)).toISOString();
      } catch (error) {
        if (error instanceof InvalidScheduleError) nextRunAt = null;
        else throw error;
      }
    }
    return this.scheduler.upsert({
      taskType: SOURCE_POST_PROCESSING_TASK_TYPE,
      taskKey: rule.id,
      scopeType: "space",
      scopeId: rule.space_id,
      spaceId: rule.space_id,
      userId: rule.created_by_user_id,
      status,
      nextRunAt,
      lastRunAt: fired ? now : null,
      stateJson: {},
      updatedAt: now,
    });
  }

  private async withSchedule(row: SourcePostProcessingRuleRow): Promise<SourcePostProcessingRuleRow> {
    const task = await this.scheduler.get(SOURCE_POST_PROCESSING_TASK_TYPE, row.id);
    return { ...row, next_run_at: task?.next_run_at ?? null };
  }

  private async recentRunsForRule(spaceId: string, ruleId: string): Promise<SourcePostProcessingRunOut[]> {
    const result = await this.db.query<SourcePostProcessingRunRow>(
      `SELECT ${RUN_COLUMNS}
         FROM source_post_processing_runs
        WHERE space_id = $1 AND rule_id = $2
        ORDER BY created_at DESC, id DESC
        LIMIT 20`,
      [spaceId, ruleId],
    );
    return result.rows.map(runOut);
  }

  private async countPendingItemsForRule(rule: SourcePostProcessingRuleRow): Promise<number> {
    const inputConfig = normalizeInputConfig(rule.input_config_json);
    if (inputConfig.window === "explicit") return 0;
    const { clauses, params } = itemWindowWhere({
      spaceId: rule.space_id,
      sourceConnectionId: rule.source_connection_id,
      inputConfig,
      cursor: cursorWatermark(rule.cursor_json),
    });
    const result = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total
         FROM intake_items
        WHERE ${clauses.join(" AND ")}`,
      params,
    );
    return countFromRow(result.rows[0]);
  }

  private async findItemsForWindow(input: {
    spaceId: string;
    sourceConnectionId: string;
    inputConfig: SourcePostProcessingInputConfig;
    cursor: IntakeWatermark | null;
  }): Promise<{ items: IntakeItemRow[]; cursorAfter: IntakeWatermark | null }> {
    const { clauses, params } = itemWindowWhere(input);
    params.push(input.inputConfig.item_limit);
    const result = await this.db.query<IntakeItemRow>(
      `SELECT ${ITEM_COLUMNS}
         FROM intake_items
        WHERE ${clauses.join(" AND ")}
        ORDER BY date_trunc('milliseconds', created_at), id
        LIMIT $${params.length}`,
      params,
    );
    const last = result.rows[result.rows.length - 1];
    return {
      items: result.rows,
      cursorAfter: last ? { created_at: timestampString(last.created_at) ?? new Date().toISOString(), id: last.id } : null,
    };
  }

  private async findItemsByIds(
    spaceId: string,
    sourceConnectionId: string,
    itemIds: string[],
  ): Promise<IntakeItemRow[]> {
    const result = await this.db.query<IntakeItemRow>(
      `SELECT ${ITEM_COLUMNS}
         FROM intake_items
        WHERE space_id = $1
          AND connection_id = $2
          AND id::text = ANY($3::text[])
          AND deleted_at IS NULL
        ORDER BY created_at ASC, id ASC`,
      [spaceId, sourceConnectionId, itemIds],
    );
    if (result.rows.length !== itemIds.length) {
      throw new HttpError(404, "Post-processing input item not found in this source");
    }
    return result.rows;
  }

  private async findEvidenceByIds(
    spaceId: string,
    sourceConnectionId: string,
    evidenceIds: string[],
  ): Promise<EvidenceRow[]> {
    const result = await this.db.query<EvidenceRow>(
      `SELECT ${EVIDENCE_COLUMNS}
         FROM extracted_evidence ee
         LEFT JOIN intake_items ii
           ON ii.space_id = ee.space_id
          AND ii.id = ee.intake_item_id
        WHERE ee.space_id = $1
          AND ee.id::text = ANY($2::text[])
          AND ee.deleted_at IS NULL
          AND (ii.connection_id = $3 OR ee.intake_item_id IS NULL)
        ORDER BY ee.created_at ASC, ee.id ASC`,
      [spaceId, evidenceIds, sourceConnectionId],
    );
    if (result.rows.length !== evidenceIds.length) {
      throw new HttpError(404, "Post-processing input evidence not found in this source");
    }
    return result.rows;
  }

  private async findEvidenceForItems(spaceId: string, itemIds: string[]): Promise<EvidenceRow[]> {
    const result = await this.db.query<EvidenceRow>(
      `SELECT ${EVIDENCE_COLUMNS}
         FROM extracted_evidence
        WHERE space_id = $1
          AND intake_item_id::text = ANY($2::text[])
          AND deleted_at IS NULL
        ORDER BY created_at ASC, id ASC`,
      [spaceId, itemIds],
    );
    return result.rows;
  }
}

export function ruleOut(row: SourcePostProcessingRuleRow): SourcePostProcessingRuleOut {
  return {
    id: row.id,
    space_id: row.space_id,
    source_connection_id: row.source_connection_id,
    agent_id: row.agent_id,
    project_id: row.project_id,
    name: row.name,
    status: row.status,
    trigger_type: row.trigger_type,
    trigger_config_json: normalizeTriggerConfig(row.trigger_config_json, row.trigger_type),
    input_config_json: normalizeInputConfig(row.input_config_json),
    actions_json: normalizeActions(row.actions_json),
    cursor_json: recordValue(row.cursor_json),
    last_fired_at: timestampString(row.last_fired_at),
    next_run_at: timestampString(row.next_run_at),
    created_by_user_id: row.created_by_user_id,
    created_at: timestampString(row.created_at) ?? "",
    updated_at: timestampString(row.updated_at) ?? "",
  };
}

export function runOut(row: SourcePostProcessingRunRow): SourcePostProcessingRunOut {
  return {
    id: row.id,
    space_id: row.space_id,
    rule_id: row.rule_id,
    source_connection_id: row.source_connection_id,
    agent_id: row.agent_id,
    project_id: row.project_id,
    agent_run_id: row.agent_run_id,
    triggered_by_user_id: row.triggered_by_user_id,
    trigger_type: row.trigger_type,
    status: row.status,
    input_item_ids: stringArray(row.input_item_ids_json),
    input_evidence_ids: stringArray(row.input_evidence_ids_json),
    output_artifact_ids: stringArray(row.output_artifact_ids_json),
    output_proposal_ids: stringArray(row.output_proposal_ids_json),
    output_job_ids: stringArray(row.output_job_ids_json),
    cursor_before_json: recordValue(row.cursor_before_json),
    cursor_after_json: recordValue(row.cursor_after_json),
    retrieval_context_json: recordValue(row.retrieval_context_json) ?? {},
    item_decisions_json: recordArray(row.item_decisions_json),
    summary: row.summary,
    error_json: recordValue(row.error_json),
    started_at: timestampString(row.started_at),
    completed_at: timestampString(row.completed_at),
    created_at: timestampString(row.created_at) ?? "",
  };
}

export function decisionOut(row: SourcePostProcessingItemDecisionRow): SourcePostProcessingItemDecisionOut {
  return {
    id: row.id,
    space_id: row.space_id,
    source_connection_id: row.source_connection_id,
    rule_id: row.rule_id,
    run_id: row.run_id,
    project_id: row.project_id,
    intake_item_id: row.intake_item_id,
    relevance: row.relevance,
    confidence: row.confidence,
    reason: row.reason,
    matched_context_refs: recordArray(row.matched_context_refs_json),
    applied_item_status: row.applied_item_status,
    review_status: row.review_status,
    action_json: recordValue(row.action_json) ?? {},
    item: {
      title: row.item_title ?? null,
      source_uri: row.item_source_uri ?? null,
      source_domain: row.item_source_domain ?? null,
      author: row.item_author ?? null,
      status: row.item_status ?? null,
      content_state: row.item_content_state ?? null,
    },
    rule_name: row.rule_name ?? null,
    run_status: row.run_status ?? null,
    run_created_at: timestampString(row.run_created_at),
    created_at: timestampString(row.created_at) ?? "",
    updated_at: timestampString(row.updated_at) ?? "",
  };
}

export function isRelevanceScreeningEnabled(
  actions: SourcePostProcessingActions,
  inputConfig: SourcePostProcessingInputConfig,
): boolean {
  return actions.mark_items || inputConfig.relevance_profile?.enabled === true;
}

export function normalizeActions(value: unknown): SourcePostProcessingActions {
  const defaults: SourcePostProcessingActions = {
    batch_digest: true,
    per_item_summary: false,
    extract_evidence: false,
    create_proposals: false,
    mark_items: false,
  };
  const record = recordValue(value) ?? {};
  return {
    batch_digest: booleanValue(record.batch_digest, defaults.batch_digest),
    per_item_summary: booleanValue(record.per_item_summary, defaults.per_item_summary),
    extract_evidence: booleanValue(record.extract_evidence, defaults.extract_evidence),
    create_proposals: booleanValue(record.create_proposals, defaults.create_proposals),
    mark_items: booleanValue(record.mark_items, defaults.mark_items),
  };
}

export function normalizeInputConfig(value: unknown): SourcePostProcessingInputConfig {
  const record = recordValue(value) ?? {};
  const window = enumValue(
    record.window,
    ["new_since_last_success", "local_day", "last_24h", "explicit"],
    "input_config_json.window",
    "new_since_last_success",
  );
  const contentProfile = enumValue(
    record.content_profile,
    ["generic", "arxiv_new_papers"],
    "input_config_json.content_profile",
    "generic",
  );
  const config: SourcePostProcessingInputConfig = {
    window,
    item_limit: boundedInt(record.item_limit, "input_config_json.item_limit", 10, 1, 100),
    max_batches_per_event: boundedInt(
      record.max_batches_per_event,
      "input_config_json.max_batches_per_event",
      10,
      1,
      50,
    ),
    processing_strategy: enumValue(
      record.processing_strategy,
      ["batch_digest", "screen_then_digest", "screen_extract_digest"],
      "input_config_json.processing_strategy",
      "batch_digest",
    ),
    content_source: enumValue(
      record.content_source,
      ["excerpt_only", "prefer_extracted_text_for_candidates", "require_extracted_text_for_candidates"],
      "input_config_json.content_source",
      "excerpt_only",
    ),
    include_excerpts: booleanValue(record.include_excerpts, true),
    include_evidence: booleanValue(record.include_evidence, false),
    timezone: stringValue(record.timezone) ?? "UTC",
    retrieval_context: normalizeRetrievalContext(record.retrieval_context),
    candidate_prefilter: normalizeCandidatePrefilter(record.candidate_prefilter),
    deep_analysis: normalizeDeepAnalysis(record.deep_analysis),
  };
  if (stringValue(record.content_profile)) config.content_profile = contentProfile;
  const summaryGoal = boundedString(record.summary_goal, "input_config_json.summary_goal", 2000);
  if (summaryGoal) config.summary_goal = summaryGoal;
  const outputInstructions = boundedString(record.output_instructions, "input_config_json.output_instructions", 4000);
  if (outputInstructions) config.output_instructions = outputInstructions;
  const relevanceProfile = normalizeRelevanceProfile(record.relevance_profile);
  if (relevanceProfile) config.relevance_profile = relevanceProfile;
  return config;
}

function normalizeCandidatePrefilter(value: unknown): SourcePostProcessingCandidatePrefilterConfig {
  const record = recordValue(value) ?? {};
  const minScore = record.min_score === undefined || record.min_score === null
    ? null
    : numberValue(record.min_score, "input_config_json.candidate_prefilter.min_score");
  if (minScore !== null && minScore < 0) {
    throw new HttpError(422, "input_config_json.candidate_prefilter.min_score must be at least 0");
  }
  const config: SourcePostProcessingCandidatePrefilterConfig = {
    enabled: booleanValue(record.enabled, false),
    mode: enumValue(
      record.mode,
      ["exact", "lexical", "hybrid", "hybrid_rerank"],
      "input_config_json.candidate_prefilter.mode",
      "hybrid",
    ),
    max_candidates: boundedInt(
      record.max_candidates,
      "input_config_json.candidate_prefilter.max_candidates",
      20,
      1,
      100,
    ),
  };
  if (minScore !== null) config.min_score = Math.min(1_000_000, minScore);
  return config;
}

function normalizeDeepAnalysis(value: unknown): SourcePostProcessingDeepAnalysisConfig {
  const record = recordValue(value) ?? {};
  const relevance: Array<"relevant" | "maybe"> = Array.isArray(record.trigger_relevance)
    ? uniqueStrings(record.trigger_relevance).filter((item): item is "relevant" | "maybe" =>
        item === "relevant" || item === "maybe")
    : ["relevant"];
  const minConfidence = record.min_confidence === undefined || record.min_confidence === null
    ? 0.7
    : numberValue(record.min_confidence, "input_config_json.deep_analysis.min_confidence");
  if (minConfidence < 0 || minConfidence > 1) {
    throw new HttpError(422, "input_config_json.deep_analysis.min_confidence must be between 0 and 1");
  }
  return {
    enabled: booleanValue(record.enabled, false),
    trigger_relevance: relevance.length ? relevance : ["relevant"],
    min_confidence: minConfidence,
    max_candidates_per_run: boundedInt(
      record.max_candidates_per_run,
      "input_config_json.deep_analysis.max_candidates_per_run",
      5,
      1,
      25,
    ),
    content_source: enumValue(
      record.content_source,
      ["prefer_extracted_text", "require_extracted_text"],
      "input_config_json.deep_analysis.content_source",
      "prefer_extracted_text",
    ),
    output: enumValue(
      record.output,
      ["deep_report", "per_item_deep_summary"],
      "input_config_json.deep_analysis.output",
      "deep_report",
    ),
  };
}

function normalizeRelevanceProfile(value: unknown): SourcePostProcessingRelevanceProfile | undefined {
  const record = recordValue(value);
  if (!record) return undefined;
  const enabled = booleanValue(record.enabled, false);
  const objective = boundedString(record.objective, "input_config_json.relevance_profile.objective", 2000);
  const includeCriteria = boundedStringArray(record.include_criteria, "input_config_json.relevance_profile.include_criteria");
  const excludeCriteria = boundedStringArray(record.exclude_criteria, "input_config_json.relevance_profile.exclude_criteria");
  const mustHave = boundedStringArray(record.must_have, "input_config_json.relevance_profile.must_have");
  const niceToHave = boundedStringArray(record.nice_to_have, "input_config_json.relevance_profile.nice_to_have");
  const decisionPolicy = normalizeDecisionPolicy(record.decision_policy);
  if (enabled && !objective && includeCriteria.length === 0) {
    throw new HttpError(
      422,
      "input_config_json.relevance_profile requires an objective or include_criteria when enabled",
    );
  }
  const profile: SourcePostProcessingRelevanceProfile = {
    enabled,
    include_criteria: includeCriteria,
    exclude_criteria: excludeCriteria,
    must_have: mustHave,
    nice_to_have: niceToHave,
  };
  if (objective) profile.objective = objective;
  if (decisionPolicy) profile.decision_policy = decisionPolicy;
  return profile;
}

function normalizeDecisionPolicy(value: unknown): SourcePostProcessingRelevanceDecisionPolicy | undefined {
  const record = recordValue(value);
  if (!record) return undefined;
  const relevant = boundedString(record.relevant, "input_config_json.relevance_profile.decision_policy.relevant", 500);
  const maybe = boundedString(record.maybe, "input_config_json.relevance_profile.decision_policy.maybe", 500);
  const notRelevant = boundedString(
    record.not_relevant,
    "input_config_json.relevance_profile.decision_policy.not_relevant",
    500,
  );
  if (!relevant && !maybe && !notRelevant) return undefined;
  const policy: SourcePostProcessingRelevanceDecisionPolicy = {};
  if (relevant) policy.relevant = relevant;
  if (maybe) policy.maybe = maybe;
  if (notRelevant) policy.not_relevant = notRelevant;
  return policy;
}

function boundedStringArray(value: unknown, field: string, maxCount = 20, maxLength = 200): string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new HttpError(422, `${field} must be an array of strings`);
  const items = uniqueStrings(value);
  for (const item of items) {
    if (item.length > maxLength) throw new HttpError(422, `${field} entries must be at most ${maxLength} characters`);
  }
  if (items.length > maxCount) throw new HttpError(422, `${field} must contain at most ${maxCount} entries`);
  return items;
}

function normalizeRetrievalContext(value: unknown): SourcePostProcessingRetrievalContextConfig {
  const record = recordValue(value) ?? {};
  const defaultDomains: SourcePostProcessingRetrievalDomain[] = ["project"];
  const domains: SourcePostProcessingRetrievalDomain[] = Array.isArray(record.domains)
    ? uniqueStrings(record.domains).filter((domain): domain is SourcePostProcessingRetrievalDomain =>
        domain === "knowledge" || domain === "project" || domain === "memory" || domain === "intake")
    : defaultDomains;
  const query = boundedString(record.query, "input_config_json.retrieval_context.query", 1024);
  return {
    enabled: booleanValue(record.enabled, false),
    domains: domains.length > 0 ? domains.slice(0, 4) : defaultDomains,
    ...(query ? { query } : {}),
    max_results_per_domain: boundedInt(
      record.max_results_per_domain,
      "input_config_json.retrieval_context.max_results_per_domain",
      6,
      1,
      20,
    ),
    mode: enumValue(
      record.mode,
      ["exact", "lexical", "hybrid", "hybrid_rerank"],
      "input_config_json.retrieval_context.mode",
      "hybrid",
    ),
  };
}

export function normalizeTriggerConfig(
  value: unknown,
  triggerType: SourcePostProcessingTriggerType,
): SourcePostProcessingTriggerConfig {
  const record = recordValue(value) ?? {};
  const config = {
    min_new_items: boundedInt(record.min_new_items, "trigger_config_json.min_new_items", 1, 1, 1000),
    cooldown_seconds: boundedInt(record.cooldown_seconds, "trigger_config_json.cooldown_seconds", 900, 0, 86_400),
    cron: stringValue(record.cron) ?? undefined,
    timezone: stringValue(record.timezone) ?? "UTC",
    skip_when_no_new_items: booleanValue(record.skip_when_no_new_items, true),
  };
  if (triggerType === "schedule") {
    try {
      computeNextRunAt({ cron: config.cron, timezone: config.timezone });
    } catch (error) {
      if (error instanceof InvalidScheduleError) throw new HttpError(422, error.message);
      throw error;
    }
  }
  return config;
}

export function normalizeTriggerType(value: unknown): SourcePostProcessingTriggerType {
  return enumValue(
    value,
    ["items_materialized", "schedule", "manual"],
    "trigger_type",
    "items_materialized",
  );
}

export function normalizeRuleStatus(value: unknown): SourcePostProcessingRuleStatus {
  return enumValue(value, ["active", "paused", "archived"], "status", "active");
}

export function normalizeItemRelevance(value: unknown): SourcePostProcessingItemRelevance {
  return enumValue(value, ["relevant", "maybe", "not_relevant"], "relevance", "relevant");
}

export function normalizeDecisionReviewStatus(value: unknown): SourcePostProcessingDecisionReviewStatus {
  return enumValue(
    value,
    ["pending", "accepted", "ignored", "queued", "proposed", "rerun", "dismissed"],
    "review_status",
    "pending",
  );
}

export function cursorWatermark(cursorJson: unknown): IntakeWatermark | null {
  const cursor = recordValue(cursorJson);
  const watermark = recordValue(cursor?.intake_watermark);
  const createdAt = stringValue(watermark?.created_at);
  const id = stringValue(watermark?.id);
  return createdAt && id ? { created_at: createdAt, id } : null;
}

export function timestampString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) return value.toISOString();
  const text = String(value);
  return text ? text : null;
}

function schedulerStatus(rule: SourcePostProcessingRuleRow): "active" | "paused" | "archived" {
  if (rule.status === "archived") return "archived";
  if (rule.status === "active" && rule.trigger_type === "schedule") return "active";
  return "paused";
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> =>
        Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

function uniqueStrings(value: unknown[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value) {
    const text = stringValue(item);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    result.push(text);
  }
  return result;
}

function stringValue(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function boundedInt(value: unknown, field: string, fallback: number, min: number, max: number): number {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    throw new HttpError(422, `${field} must be an integer between ${min} and ${max}`);
  }
  return value;
}

function numberValue(value: unknown, field: string): number {
  const parsed = typeof value === "number"
    ? value
    : typeof value === "string" && value.trim()
      ? Number(value)
      : Number.NaN;
  if (!Number.isFinite(parsed)) throw new HttpError(422, `${field} must be a number`);
  return parsed;
}

function boundedString(value: unknown, field: string, maxLength: number): string | undefined {
  const text = stringValue(value);
  if (!text) return undefined;
  if (text.length > maxLength) {
    throw new HttpError(422, `${field} must be at most ${maxLength} characters`);
  }
  return text;
}

function enumValue<const Values extends readonly string[]>(
  value: unknown,
  allowed: Values,
  field: string,
  fallback: Values[number],
): Values[number] {
  const raw = stringValue(value);
  if (!raw) return fallback;
  if ((allowed as readonly string[]).includes(raw)) return raw as Values[number];
  throw new HttpError(422, `${field} must be one of: ${allowed.join(", ")}`);
}

function itemWindowWhere(input: {
  spaceId: string;
  sourceConnectionId: string;
  inputConfig: SourcePostProcessingInputConfig;
  cursor: IntakeWatermark | null;
}): { clauses: string[]; params: unknown[] } {
  const params: unknown[] = [input.spaceId, input.sourceConnectionId];
  const clauses = [
    "space_id = $1",
    "connection_id = $2",
    "deleted_at IS NULL",
    "status <> 'ignored'",
  ];
  if (input.inputConfig.window === "new_since_last_success" && input.cursor) {
    params.push(input.cursor.created_at, input.cursor.id);
    clauses.push(`(date_trunc('milliseconds', created_at), id) > ($${params.length - 1}::timestamptz, $${params.length})`);
  } else if (input.inputConfig.window === "last_24h") {
    params.push(new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString());
    clauses.push(`created_at >= $${params.length}::timestamptz`);
  } else if (input.inputConfig.window === "local_day") {
    const range = localDayRange(input.inputConfig.timezone);
    params.push(range.start, range.end);
    clauses.push(`created_at >= $${params.length - 1}::timestamptz`);
    clauses.push(`created_at < $${params.length}::timestamptz`);
  }
  return { clauses, params };
}

function decisionListWhere(input: {
  spaceId: string;
  connectionId?: string | null;
  projectId?: string | null;
  ruleId?: string | null;
  relevance?: SourcePostProcessingItemRelevance | null;
  reviewStatus?: SourcePostProcessingDecisionReviewStatus | null;
}): { where: string; params: unknown[] } {
  const params: unknown[] = [input.spaceId];
  const clauses = ["d.space_id = $1"];
  if (input.connectionId) {
    params.push(input.connectionId);
    clauses.push(`d.source_connection_id = $${params.length}`);
  }
  if (input.projectId) {
    params.push(input.projectId);
    clauses.push(`d.project_id = $${params.length}`);
  }
  if (input.ruleId) {
    params.push(input.ruleId);
    clauses.push(`d.rule_id = $${params.length}`);
  }
  if (input.relevance) {
    params.push(input.relevance);
    clauses.push(`d.relevance = $${params.length}`);
  }
  if (input.reviewStatus) {
    params.push(input.reviewStatus);
    clauses.push(`d.review_status = $${params.length}`);
  }
  return { where: clauses.join(" AND "), params };
}

export function itemStatusForRelevance(relevance: SourcePostProcessingItemRelevance): "selected" | "triaged" | "ignored" {
  if (relevance === "relevant") return "selected";
  if (relevance === "maybe") return "triaged";
  return "ignored";
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function localDayRange(timezone: string): { start: string; end: string } {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const year = Number(parts.find((part) => part.type === "year")?.value ?? now.getUTCFullYear());
  const month = Number(parts.find((part) => part.type === "month")?.value ?? now.getUTCMonth() + 1);
  const day = Number(parts.find((part) => part.type === "day")?.value ?? now.getUTCDate());
  const start = zonedLocalToUtc({ year, month, day, hour: 0, minute: 0 }, timezone);
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}

function zonedLocalToUtc(
  target: { year: number; month: number; day: number; hour: number; minute: number },
  timezone: string,
): Date {
  let guess = Date.UTC(target.year, target.month - 1, target.day, target.hour, target.minute);
  for (let index = 0; index < 4; index += 1) {
    const actual = zonedParts(new Date(guess), timezone);
    const delta = Date.UTC(
      target.year - actual.year,
      target.month - actual.month,
      target.day - actual.day,
      target.hour - actual.hour,
      target.minute - actual.minute,
    ) - Date.UTC(0, 0, 0, 0, 0);
    if (delta === 0) break;
    guess += delta;
  }
  return new Date(guess);
}

function zonedParts(date: Date, timezone: string): { year: number; month: number; day: number; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((item) => item.type === type)?.value ?? 0);
  return { year: part("year"), month: part("month"), day: part("day"), hour: part("hour"), minute: part("minute") };
}

function isPool(db: Queryable): db is Pool {
  return typeof (db as Pool).connect === "function";
}

export type SourcePostProcessingPoolClient = PoolClient;
