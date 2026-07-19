import { createHash, randomUUID } from "node:crypto";
import { getDbPool } from "../../db/pool";
import type { ServerConfig } from "../../config";
import type { Queryable, SpaceUserIdentity } from "../routeUtils/common";
import { HttpError, dateIso, objectValue, optionalString, withQueryableTransaction } from "../routeUtils/common";
import { assertProjectWriter } from "../projects/access";
import { ProjectOperationService } from "../projects/projectOperationService";
import { ProjectSourceBindingService } from "../projects/projectSourceBindingService";
import { PgJobQueueRepository } from "../jobs/repository";
import type { JobHandlerRegistry, JobHandlerResult } from "../jobs/handlerRegistry";
import { PgRunRepository } from "../runs/repository";
import { SourceBackfillPlanningService } from "../sources/sourceBackfillService";
import { SourceBackfillExecutionService } from "../sources/sourceBackfillExecutionService";
import { ARXIV_HISTORY_FLOOR } from "../sources/sourceBackfillStrategy";
import { SourcePostProcessingService } from "../sources/postProcessing/service";
import { SOURCE_POST_PROCESSING_LIMITS } from "../sources/postProcessing/config";
import { SourcePostProcessingRecoveryService } from "../sources/postProcessing/recoveryService";
import { SourceChannelService } from "../sources/channels/sourceChannelService";
import { upsertSourceChannelScanTask } from "../sources/sourceConnectionScheduler";
import { syncProjectCorpusDecisionForSourceItem } from "../projects/corpusRepository";
import { createManagedExecutionPolicy } from "../policy/managedExecutionPolicy";
import { ProjectResearchRepository } from "./repository";
import { ProjectResearchArtifactService } from "./artifactService";
import { ProjectResearchReportMaterializer } from "./reportMaterializer";
import { ProjectResearchWorkspaceService } from "./workspaceService";
import { ProjectResearchReportStatusService } from "./reportStatusService";
import { assignReportReferenceIds } from "./reportReferenceNumbering";
import {
  validateResearchArtifacts,
  type ResearchArtifactRecord,
  type ResearchArtifactValidationFailure,
} from "./artifactValidation";
import { rejectLegacyResearchRuntimeFields } from "./inputValidation";
import { researchQuestionDrift } from "./questionDrift";
import {
  RESEARCH_SYNTHESIS_CRITIQUE_OUTPUT_CONTRACT,
  RESEARCH_SYNTHESIS_OUTPUT_CONTRACT,
  RESEARCH_SYNTHESIS_REJECTION_CODES,
  type ResearchSynthesisRejection,
} from "./outputSchemas";
import {
  ProjectResearchExecutionProfileService,
  type ResearchExecutionSelection,
} from "./executionProfileService";
import {
  PROJECT_RESEARCH_SYNTHESIS_PROMPT_KEY,
  PROJECT_RESEARCH_SYNTHESIS_CRITIQUE_PROMPT_KEY,
  resolveProjectResearchCritiquePrompt,
  resolveProjectResearchSynthesisPrompt,
} from "./promptRegistry";
import {
  applyResearchStatePatch,
  deriveSkippedAfterScreeningSteps,
  deriveStepStates,
  operationSteps,
  researchStage,
  researchStageIndex,
  researchState,
  transition as transitionResearchOperation,
  updateProjection,
  type HistoryMode,
  type ResearchOperationError,
  type ResearchOperationState,
  type ResearchReportDepth,
  type ResearchStage,
  type ResearchStepOverride,
  type ResearchTransitionResult,
} from "./stateMachine";
import { ProjectResearchMonitorComparisonService } from "./monitorComparisonService";
import { ProjectResearchIntegrityMonitorService } from "./integrityMonitorService";

const MONITORING_FIELDS = new Set(["submittedDate", "lastUpdatedDate"]);
const MAX_ITEMS_DEFAULT = 10_000;
const OVERLAP_HOURS = 48;
const RESEARCH_CAPABILITIES = [
  "research.source_collect",
  "research.source_summarize",
  "research.evidence_extract",
  "research.brief_synthesize",
  "research.idea_generate",
];

interface ResearchInput {
  researchQuestion: string;
  sourceChannelIds: string[];
  historyMode: HistoryMode;
  from: string | null;
  to: string | null;
  maxItems: number;
  monitoringField: "submittedDate" | "lastUpdatedDate";
  schedule: "daily";
  agentId: string;
  runtimeProfileId: string;
  execution: ResearchExecutionSelection;
  idempotencyKey: string;
  reportDepth: ResearchReportDepth;
  questionRefineSkipped: boolean;
  searchStrategyId: string | null;
}

interface InitialIntakeDraft {
  researchQuestion: string;
  sourceChannelIds: string[];
  historyMode: HistoryMode;
  from: string | null;
  to: string | null;
  maxItems: number;
  monitoringField: "submittedDate" | "lastUpdatedDate";
  schedule: "daily";
  execution: ResearchExecutionSelection;
  reportDepth: ResearchReportDepth;
  questionRefineSkipped: boolean;
  searchStrategyId: string | null;
  questionRefinement: Record<string, unknown> | null;
}

interface OperationRow {
  id: string;
  space_id: string;
  project_id: string;
  status: string;
  progress_json: unknown;
  created_at?: string;
}

interface OperationRead extends OperationRow {
  steps: Record<string, unknown>[];
  links: Record<string, unknown>[];
}

interface WorkflowRow {
  id: string;
  status: string;
  state_json: unknown;
  [key: string]: unknown;
}

export class ProjectResearchOrchestrator {
  constructor(
    private readonly db: Queryable,
    private readonly config?: ServerConfig,
  ) {}

  /** Records a successful zero-item source scan and closes an explicit
   * incremental operation once every channel scan it started has settled. */
  async onSourceScanCompleted(input: {
    spaceId: string;
    sourceChannelId: string | null;
    scanJobId: string;
    scannedAt: string;
    scanWindowStart: string | null;
    newItemCount: number;
  }): Promise<void> {
    if (!input.sourceChannelId || input.newItemCount > 0) return;
    const workflows = await this.db.query<{ id: string; project_id: string }>(
      `SELECT id, project_id
         FROM project_research_workflows
        WHERE space_id=$1 AND status='active'
          AND state_json @> $2::jsonb
          AND state_json @> '{"monitoring":{"active":true}}'::jsonb`,
      [input.spaceId, JSON.stringify({ channel_ids: [input.sourceChannelId] })],
    );
    for (const workflow of workflows.rows) {
      const operationResult = await this.db.query<OperationRow>(
        `SELECT id, space_id, project_id, status, progress_json, created_at
           FROM project_operations
          WHERE space_id=$1 AND project_id=$2 AND kind='research'
            AND status='active'
            AND progress_json->>'workflow_id'=$3
            AND progress_json->>'run_kind'='incremental'
            AND COALESCE((progress_json->>'awaiting_source_scan')::boolean,false)=true
          ORDER BY created_at DESC LIMIT 1`,
        [input.spaceId, workflow.project_id, workflow.id],
      );
      const operation = operationResult.rows[0] ?? null;
      if (operation) {
        const otherPending = await this.db.query<{ count: string }>(
          `SELECT count(*)::text AS count FROM extraction_jobs
            WHERE space_id=$1 AND id<>$2 AND job_type='connection_scan'
              AND status IN ('pending','running')
              AND metadata_json->>'source_channel_id' = ANY(
                ARRAY(SELECT jsonb_array_elements_text($3::jsonb))
              )`,
          [input.spaceId, input.scanJobId, JSON.stringify(researchState(operation.progress_json).channel_ids)],
        );
        if (Number(otherPending.rows[0]?.count ?? 0) > 0) continue;
        const state = researchState(operation.progress_json);
        const pendingPostProcessing = await this.db.query<{ count: string }>(
          `SELECT (
             (SELECT count(*) FROM source_post_processing_runs
               WHERE space_id=$1 AND source_channel_id=ANY($2::text[]) AND status IN ('queued','running'))
             +
             (SELECT count(*) FROM jobs
               WHERE space_id=$1 AND job_type='source_post_processing_event' AND status IN ('pending','claimed','running')
                 AND payload_json->>'source_channel_id'=ANY($2::text[]))
           )::text AS count`,
          [input.spaceId, state.channel_ids],
        );
        if (Number(pendingPostProcessing.rows[0]?.count ?? 0) > 0) continue;
        state.awaiting_source_scan = false;
        state.watermark = { before: state.watermark.after ?? input.scanWindowStart, after: input.scannedAt, overlap_hours: OVERLAP_HOURS };
        state.current_stage = "complete";
        state.stage_state = "skipped";
        state.screening_progress = {
          ...await this.screeningProgressFor(input.spaceId, workflow.project_id, operation.id, state, operation.created_at),
          phase: "completed", total_items: 0, classified_items: 0, unclassified_items: 0,
          message: "The monitoring scan completed with no new papers.", updated_at: input.scannedAt,
        };
        await this.recordScanSummary(operation, state, { relevant: 0, maybe: 0, excluded: 0 });
        await this.setState(operation, state, deriveSkippedAfterScreeningSteps());
      } else {
        // One zero-result row per workflow per day, refreshed to the latest
        // scan time. Day boundaries are UTC, matching the pinned UTC timezone
        // of research post-processing rules; frequent scan schedules must not
        // flood the timeline with per-scan rows.
        await this.insertScanSummary({
          spaceId: input.spaceId,
          projectId: workflow.project_id,
          workflowId: workflow.id,
          operationId: null,
          scanKey: `source-scan-day:${workflow.id}:${input.scannedAt.slice(0, 10)}`,
          scanWindowStart: input.scanWindowStart,
          scanWindowEnd: input.scannedAt,
          scannedAt: input.scannedAt,
          newItemCount: 0,
          relevantCount: 0,
          maybeCount: 0,
          excludedCount: 0,
          onConflict: "refresh_scan_time",
        });
      }
    }
  }

  async startInitialIntake(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const profile = await this.db.query<{ research_question: string | null }>(
      `SELECT research_question FROM project_research_profiles WHERE space_id=$1 AND project_id=$2 LIMIT 1`,
      [identity.spaceId, projectId],
    );
    const input = normalizeInitialIntakeInput(body, profile.rows[0]?.research_question ?? null);
    if (!this.config) throw new HttpError(503, "Auto research requires server configuration");
    const execution = await new ProjectResearchExecutionProfileService(this.db, this.config)
      .resolve(identity, input.execution);
    input.agentId = execution.agentId;
    input.runtimeProfileId = execution.runtimeProfileId;

    return withQueryableTransaction(this.db, (db) =>
      new ProjectResearchOrchestrator(db, this.config).startInitialIntakeLocked(identity, projectId, input),
    );
  }

  async saveInitialIntakeDraft(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    // Older baseline operations could leave an empty screening gate pending.
    // Reconcile that legacy state before opening setup so the new empty-result
    // path also repairs projects created before this guard existed.
    const legacyEmpty = await this.db.query<{ id: string; status: string; progress_json: unknown }>(
      `SELECT id, status, progress_json FROM project_operations
        WHERE space_id=$1 AND project_id=$2 AND kind='research'
          AND progress_json->>'run_kind'='baseline'
        ORDER BY created_at DESC LIMIT 1`,
      [identity.spaceId, projectId],
    );
    const legacyProgress = objectValue(legacyEmpty.rows[0]?.progress_json);
    const legacySourceItems = Array.isArray(legacyProgress.source_item_ids)
      ? legacyProgress.source_item_ids.filter((value): value is string => typeof value === "string" && value.length > 0)
      : [];
    if (legacyEmpty.rows[0]?.status === "waiting_review"
      && legacyProgress.current_stage === "screening"
      && legacySourceItems.length === 0) {
      await this.reconcileOperation(identity.spaceId, legacyEmpty.rows[0].id);
    }
    const profile = await this.db.query<{ research_question: string | null }>(
      `SELECT research_question FROM project_research_profiles WHERE space_id=$1 AND project_id=$2 LIMIT 1`,
      [identity.spaceId, projectId],
    );
    const draft = normalizeInitialIntakeDraft(body, profile.rows[0]?.research_question ?? null);
    return withQueryableTransaction(this.db, (db) =>
      new ProjectResearchOrchestrator(db, this.config).saveInitialIntakeDraftLocked(identity, projectId, draft),
    );
  }

  private async saveInitialIntakeDraftLocked(identity: SpaceUserIdentity, projectId: string, draft: InitialIntakeDraft) {
    await this.db.query(
      `UPDATE projects SET current_focus=$3, updated_at=$4 WHERE space_id=$1 AND id=$2 AND status='active'`,
      [identity.spaceId, projectId, draft.researchQuestion, new Date().toISOString()],
    );
    const existing = await this.db.query<WorkflowRow>(
      `SELECT * FROM project_research_workflows
        WHERE space_id=$1 AND project_id=$2 AND status IN ('not_started','paused')
        ORDER BY updated_at DESC LIMIT 1 FOR UPDATE`,
      [identity.spaceId, projectId],
    );
    const active = await this.db.query<{ id: string }>(
      `SELECT id FROM project_research_workflows
        WHERE space_id=$1 AND project_id=$2 AND status='active'
        ORDER BY updated_at DESC LIMIT 1`,
      [identity.spaceId, projectId],
    );
    if (active.rows[0]) throw new HttpError(409, "An active research workflow cannot be edited after initial literature intake has started");
    const startedBaseline = await this.db.query<{ id: string }>(
      `SELECT id FROM project_operations
        WHERE space_id=$1 AND project_id=$2 AND kind='research'
          AND progress_json->>'run_kind'='baseline'
        ORDER BY created_at DESC LIMIT 1`,
      [identity.spaceId, projectId],
    );
    if (startedBaseline.rows[0]) {
      const latestBaseline = await this.db.query<{ status: string; progress_json: unknown }>(
        `SELECT status, progress_json FROM project_operations
          WHERE space_id=$1 AND project_id=$2 AND kind='research'
            AND progress_json->>'run_kind'='baseline'
          ORDER BY created_at DESC LIMIT 1`,
        [identity.spaceId, projectId],
      );
      const latestProgress = objectValue(latestBaseline.rows[0]?.progress_json);
      const emptyResult = objectValue(latestProgress.empty_result);
      const canReconfigureEmptyIntake = latestBaseline.rows[0]?.status === "completed"
        && emptyResult.kind === "no_source_items";
      if (!canReconfigureEmptyIntake) {
        throw new HttpError(409, "Initial literature intake already started; its execution snapshot cannot be edited");
      }
    }

    const now = new Date().toISOString();
    const state = initialIntakeDraftState(draft, now);
    const workflowId = existing.rows[0]?.id ?? randomUUID();
    if (existing.rows[0]) {
      await this.db.query(
        `UPDATE project_research_workflows
            SET status='not_started', current_stage='initial_intake_setup', mode='autonomous', state_json=$4::jsonb, updated_at=$5
          WHERE space_id=$1 AND project_id=$2 AND id=$3`,
        [identity.spaceId, projectId, workflowId, JSON.stringify(state), now],
      );
    } else {
      await this.db.query(
        `INSERT INTO project_research_workflows
          (id,space_id,project_id,workflow_type,status,mode,current_stage,state_json,started_by_user_id,created_at,updated_at)
         VALUES ($1,$2,$3,'literature_review','not_started','autonomous','initial_intake_setup',$4::jsonb,$5,$6,$6)`,
        [workflowId, identity.spaceId, projectId, JSON.stringify(state), identity.userId, now],
      );
    }
    const workflow = await this.workflow(identity.spaceId, projectId, workflowId);
    if (!workflow) throw new HttpError(500, "Failed to save initial literature intake setup");
    return workflowOutput(workflow);
  }

  async startHistoricalBackfill(
    identity: SpaceUserIdentity,
    projectId: string,
    workflowId: string,
    body: Record<string, unknown>,
  ) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    return withQueryableTransaction(this.db, (db) =>
      new ProjectResearchOrchestrator(db, this.config).startHistoricalBackfillLocked(identity, projectId, workflowId, body),
    );
  }

  async applyQuestionForward(identity: SpaceUserIdentity, projectId: string) {
    return this.resolveQuestionChange(identity, projectId, "apply_forward");
  }

  async questionChangeImpact(identity: SpaceUserIdentity, projectId: string) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const workflow = await this.workflow(identity.spaceId, projectId, null, true);
    if (!workflow) throw new HttpError(409, "There is no active research workflow to update");
    const state = objectValue(workflow.state_json);
    const version = questionVersion(state);
    const [screened, reports] = await Promise.all([
      this.db.query<{ count: string }>(
        `SELECT count(DISTINCT source_item_id)::int AS count
           FROM source_post_processing_item_decisions
          WHERE space_id=$1 AND project_id=$2 AND research_question_version=$3`,
        [identity.spaceId, projectId, version],
      ),
      this.db.query<{ count: string }>(
        `SELECT count(*)::int AS count
           FROM project_research_reports
          WHERE space_id=$1 AND project_id=$2 AND workflow_id=$3`,
        [identity.spaceId, projectId, workflow.id],
      ),
    ]);
    return {
      workflow_id: workflow.id,
      previous_question: optionalString(state.research_question),
      current_question: await this.projectResearchQuestion(identity.spaceId, projectId),
      previous_version: version,
      screened_papers: Number(screened.rows[0]?.count ?? 0),
      reports: Number(reports.rows[0]?.count ?? 0),
    };
  }

  async resolveQuestionChange(
    identity: SpaceUserIdentity,
    projectId: string,
    strategy: "rescreen" | "synthesis_only" | "apply_forward",
  ) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    return withQueryableTransaction(this.db, (db) =>
      new ProjectResearchOrchestrator(db, this.config).resolveQuestionChangeLocked(identity, projectId, strategy),
    );
  }

  async generateReportSnapshot(identity: SpaceUserIdentity, projectId: string) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    return withQueryableTransaction(this.db, async (db) => {
      const service = new ProjectResearchOrchestrator(db, this.config);
      const workflow = await service.workflow(identity.spaceId, projectId, null, true);
      if (!workflow) throw new HttpError(409, "There is no active research workflow to synthesize");
      await service.assertResearchQuestionAligned(identity.spaceId, projectId, workflow.state_json);
      const active = await service.activeResearchOperation(identity.spaceId, projectId, workflow.id);
      if (active) throw new HttpError(409, "Wait for the active research operation to finish before generating a report snapshot");
      const corpus = await db.query<{ source_item_id: string }>(
        `SELECT DISTINCT source_item_id FROM project_corpus_items WHERE space_id=$1 AND project_id=$2 AND status='active' AND source_item_id IS NOT NULL ORDER BY source_item_id`,
        [identity.spaceId, projectId],
      );
      const sourceItemIds = corpus.rows.map((row) => row.source_item_id);
      if (!sourceItemIds.length) throw new HttpError(409, "The project corpus has no papers to synthesize");
      const key = `snapshot:${workflow.id}:${new Date().toISOString()}`;
      const state = incrementalStateFromWorkflow(workflow.state_json, workflow.id, sourceItemIds, key, null);
      state.run_kind = "synthesis_only";
      state.current_stage = "synthesis";
      state.stage_state = "running";
      const operation = await service.createOperation(identity, projectId, {
        title: "Generate research report snapshot",
        intentText: "Synthesize the current reviewed corpus into a new immutable report snapshot.",
        steps: operationSteps(),
        state,
      });
      await service.queueSynthesis({
        spaceId: identity.spaceId,
        userId: identity.userId,
        projectId,
        operationId: operation.id,
        workflowId: workflow.id,
        from: ["synthesis"],
        reuseExistingRun: false,
      });
      return service.readOperation(identity, projectId, operation.id);
    });
  }

  private async resolveQuestionChangeLocked(
    identity: SpaceUserIdentity,
    projectId: string,
    strategy: "rescreen" | "synthesis_only" | "apply_forward",
  ) {
    const project = await this.db.query<{ current_focus: string | null }>(
      `SELECT current_focus FROM projects WHERE space_id=$1 AND id=$2 FOR UPDATE`,
      [identity.spaceId, projectId],
    );
    const currentQuestion = optionalString(project.rows[0]?.current_focus);
    if (!currentQuestion) throw new HttpError(422, "Set a current research question before applying it to future runs");

    const workflow = await this.workflow(identity.spaceId, projectId, null, true);
    if (!workflow) throw new HttpError(409, "There is no active research workflow to update");
    const workflowState = objectValue(workflow.state_json);
    const workflowQuestion = optionalString(workflowState.research_question);
    const ruleIds = stringArray(workflowState.source_post_processing_rule_ids);
    if (!workflowQuestion) throw new HttpError(409, "The research workflow has no question snapshot to update");
    if (!researchQuestionDrift(currentQuestion, workflowQuestion)) return workflowOutput(workflow);

    const active = await this.activeResearchOperation(identity.spaceId, projectId, workflow.id);
    if (active) throw new HttpError(409, "Wait for the active research operation to finish before applying a new research question");
    const processing = await this.db.query<{ id: string }>(
      `SELECT id FROM source_post_processing_runs
        WHERE space_id=$1 AND project_id=$2 AND status IN ('queued','running')
        ORDER BY created_at DESC LIMIT 1`,
      [identity.spaceId, projectId],
    );
    if (processing.rows[0]) throw new HttpError(409, "Wait for source processing to finish before applying a new research question");
    if (ruleIds.length > 0) {
      const queuedProcessing = await this.db.query<{ id: string }>(
        `SELECT id FROM jobs
          WHERE space_id=$1 AND job_type='source_post_processing_event'
            AND status IN ('pending','claimed','running')
            AND payload_json->>'rule_id'=ANY($2::text[])
          ORDER BY created_at DESC LIMIT 1`,
        [identity.spaceId, ruleIds],
      );
      if (queuedProcessing.rows[0]) throw new HttpError(409, "Wait for queued source screening to finish before applying a new research question");
    }

    const now = new Date().toISOString();
    const previousVersion = questionVersion(workflowState);
    const nextVersion = previousVersion + 1;
    const nextState = {
      ...workflowState,
      research_question: currentQuestion,
      research_question_version: nextVersion,
      previous_research_question: workflowQuestion,
      previous_research_question_version: previousVersion,
      question_changed_at: now,
      question_change_mode: strategy,
      question_history: [
        { from: workflowQuestion, to: currentQuestion, from_version: previousVersion, to_version: nextVersion, applied_at: now, applied_by_user_id: identity.userId, mode: strategy },
      ],
    };
    await this.db.query(
      `UPDATE project_research_workflows SET state_json=$4::jsonb, updated_at=$5 WHERE space_id=$1 AND project_id=$2 AND id=$3`,
      [identity.spaceId, projectId, workflow.id, JSON.stringify(nextState), now],
    );

    await this.db.query(
      `UPDATE project_research_profiles
          SET research_question=$3, status='draft', approved_by_user_id=NULL, approved_at=NULL, updated_at=$4
        WHERE space_id=$1 AND project_id=$2`,
      [identity.spaceId, projectId, currentQuestion, now],
    );

    if (ruleIds.length > 0) {
      const rules = await this.db.query<{ id: string; source_channel_id: string; input_config_json: unknown }>(
        `SELECT id, source_channel_id, input_config_json
           FROM source_post_processing_rules
          WHERE space_id=$1 AND id=ANY($2::text[]) AND project_id=$3 AND status <> 'archived'`,
        [identity.spaceId, ruleIds, projectId],
      );
      const service = new SourcePostProcessingService(this.db, this.config!);
      for (const rule of rules.rows) {
        const inputConfig = objectValue(rule.input_config_json);
        const relevanceProfile = objectValue(inputConfig.relevance_profile);
        await service.updateRule(identity, rule.source_channel_id, rule.id, {
          input_config_json: {
            ...inputConfig,
            research_question_version: nextVersion,
            summary_goal: currentQuestion,
            retrieval_context: { ...objectValue(inputConfig.retrieval_context), query: currentQuestion },
            relevance_profile: {
              ...relevanceProfile,
              objective: currentQuestion,
              include_criteria: [currentQuestion],
            },
          },
        });
      }
    }

    if (strategy === "apply_forward") {
      const updated = await this.workflow(identity.spaceId, projectId, workflow.id);
      if (!updated) throw new HttpError(500, "Failed to apply the research question to the workflow");
      return workflowOutput(updated);
    }

    const corpus = await this.db.query<{ source_item_id: string }>(
      `SELECT DISTINCT source_item_id
         FROM project_corpus_items
        WHERE space_id=$1 AND project_id=$2 AND status='active' AND source_item_id IS NOT NULL
        ORDER BY source_item_id`,
      [identity.spaceId, projectId],
    );
    const sourceItemIds = corpus.rows.map((row) => row.source_item_id);
    if (sourceItemIds.length === 0) throw new HttpError(409, "The project corpus has no papers to process for the new question");

    const key = `question:${strategy}:${workflow.id}:v${nextVersion}`;
    const state = incrementalStateFromWorkflow(nextState, workflow.id, sourceItemIds, key, null);
    state.run_kind = strategy === "rescreen" ? "question_rescreen" : "synthesis_only";
    state.research_question = currentQuestion;
    state.research_question_version = nextVersion;

    if (strategy === "rescreen") {
      await this.db.query(
        `UPDATE project_corpus_items
            SET triage_status='new', source_decision_id=NULL, relevance=NULL, confidence=NULL,
                reason=NULL, last_reviewed_at=NULL, updated_at=$3
          WHERE space_id=$1 AND project_id=$2 AND status='active'
            AND source_item_id IS NOT NULL AND triage_confirmed_by_user=false`,
        [identity.spaceId, projectId, now],
      );
      const operation = await this.createOperation(identity, projectId, {
        title: "Re-screen corpus for revised research question",
        intentText: `Re-screen the existing corpus for: ${currentQuestion}`,
        steps: operationSteps(),
        state,
      });
      await this.enqueueReconcile(identity.spaceId, identity.userId, operation.id, "question_rescreen");
      const updatedWorkflow = await this.workflow(identity.spaceId, projectId, workflow.id);
      if (!updatedWorkflow) throw new HttpError(500, "Research workflow disappeared while starting re-screening");
      return { workflow: workflowOutput(updatedWorkflow), operation: await this.readOperation(identity, projectId, operation.id) };
    }

    state.current_stage = "synthesis";
    state.stage_state = "running";
    const operation = await this.createOperation(identity, projectId, {
      title: "Re-run synthesis for revised research question",
      intentText: `Re-synthesize the existing corpus for: ${currentQuestion}`,
      steps: operationSteps(),
      state,
    });
    await this.queueSynthesis({
      spaceId: identity.spaceId,
      userId: identity.userId,
      projectId,
      operationId: operation.id,
      workflowId: workflow.id,
      from: ["synthesis"],
      reuseExistingRun: false,
    });
    const updatedWorkflow = await this.workflow(identity.spaceId, projectId, workflow.id);
    if (!updatedWorkflow) throw new HttpError(500, "Research workflow disappeared while starting synthesis");
    return { workflow: workflowOutput(updatedWorkflow), operation: await this.readOperation(identity, projectId, operation.id) };
  }

  private async startHistoricalBackfillLocked(
    identity: SpaceUserIdentity,
    projectId: string,
    workflowId: string,
    body: Record<string, unknown>,
  ) {
    const workflow = await this.workflow(identity.spaceId, projectId, workflowId, true);
    if (!workflow) throw new HttpError(404, "Research workflow not found");
    await this.assertResearchQuestionAligned(identity.spaceId, projectId, workflow.state_json);
    const workflowState = objectValue(workflow.state_json);
    const monitoring = objectValue(workflowState.monitoring);
    if (monitoring.active !== true) throw new HttpError(409, "Historical extension requires a completed baseline with active monitoring");
    if (objectValue(workflowState.initial_intake).history_mode === "all_available") {
      throw new HttpError(409, "All available history baseline does not need an earlier history extension");
    }
    const channelIds = stringArray(workflowState.channel_ids);
    const bindingIds = stringArray(workflowState.project_source_binding_ids);
    const ruleIds = stringArray(workflowState.source_post_processing_rule_ids);
    if (!channelIds.length || channelIds.length !== bindingIds.length || channelIds.length !== ruleIds.length) throw new HttpError(409, "The research workflow has not completed monitor setup");

    const coverage = historyCoverage(workflowState);
    if (coverage.some((range) => range.status === "partial")) {
      throw new HttpError(409, "Continue the partial history backfill before extending into an earlier range");
    }
    const currentFrom = coverage.map((range) => range.from).sort()[0] ?? optionalString(objectValue(workflowState.initial_intake).from);
    if (!currentFrom) throw new HttpError(409, "The research workflow has no recorded historical coverage");
    const from = optionalString(body.from);
    const to = optionalString(body.to) ?? currentFrom;
    if (!from) throw new HttpError(422, "from is required for historical backfill");
    if (Number.isNaN(Date.parse(from)) || Number.isNaN(Date.parse(to)) || Date.parse(from) >= Date.parse(to)) {
      throw new HttpError(422, "from must be earlier than to");
    }
    if (Date.parse(from) < Date.parse(ARXIV_HISTORY_FLOOR)) {
      throw new HttpError(422, `from must not be earlier than ${ARXIV_HISTORY_FLOOR}`);
    }
    if (Date.parse(to) > Date.parse(currentFrom)) {
      throw new HttpError(422, "to must not be later than the earliest covered history date");
    }
    if (coverage.some((range) => Date.parse(from) < Date.parse(range.to) && Date.parse(to) > Date.parse(range.from))) {
      throw new HttpError(409, "The requested history range overlaps existing research coverage");
    }
    const maxItems = body.max_items === undefined ? MAX_ITEMS_DEFAULT : Number(body.max_items);
    if (!Number.isInteger(maxItems) || maxItems < 1 || maxItems > MAX_ITEMS_DEFAULT) {
      throw new HttpError(422, `max_items must be an integer between 1 and ${MAX_ITEMS_DEFAULT}`);
    }
    const idempotencyKey = optionalString(body.idempotency_key) ?? fingerprintOf({ workflowId, from, to, maxItems, source_channel_ids: channelIds });
    const prior = await this.operationByIdempotency(identity.spaceId, projectId, idempotencyKey);
    if (prior && prior.status !== "failed" && prior.status !== "cancelled") return this.readOperation(identity, projectId, prior.id);
    const active = await this.activeResearchOperation(identity.spaceId, projectId, workflowId);
    if (active) throw new HttpError(409, "Another Project Research operation is already active for this workflow");

    const normalizedFrom = new Date(from).toISOString();
    const normalizedTo = new Date(to).toISOString();
    const fingerprint = fingerprintOf({ workflowId, run_kind: "historical_backfill", from: normalizedFrom, to: normalizedTo, maxItems, source_channel_ids: channelIds });
    const state = historicalBackfillStateFromWorkflow(workflowState, workflowId, normalizedFrom, normalizedTo, maxItems, idempotencyKey, fingerprint);
    const operation = await this.createOperation(identity, projectId, {
      title: "Extend automatic research history",
      intentText: `Import earlier research history from ${normalizedFrom} to ${normalizedTo}.`,
      steps: operationSteps(),
      state,
    });
    try {
      const planner = new SourceBackfillPlanningService(this.db, this.config);
      const plans: Record<string, unknown>[] = [];
      for (let index = 0; index < channelIds.length; index += 1) {
        const plan = await planner.create(identity, channelIds[index]!, {
          strategy: {
            window_unit: "date_window",
            history_mode: "bounded_range",
            from: normalizedFrom,
            to: normalizedTo,
            window_size: 30,
            max_items: maxItems,
            direction: "backward",
            monitoring_field: optionalString(objectValue(workflowState.monitoring).field) ?? "submittedDate",
          },
          quota_policy: { window: "minute", limit_count: 10 },
          idempotency_key: `${idempotencyKey}:backfill:${channelIds[index]}`,
          project_source_binding_id: bindingIds[index],
          project_operation_id: operation.id,
        });
        await new SourceBackfillExecutionService(this.db).startUserAuthorized(
          identity.spaceId,
          String(plan.id),
          operation.id,
          identity.userId,
        );
        plans.push(plan);
      }
      state.source_backfill_plan_ids = plans.map((plan) => String(plan.id));
      state.source_backfill_plan_id = state.source_backfill_plan_ids[0] ?? null;
      state.coverage_ranges = [{ from: normalizedFrom, to: normalizedTo, operation_id: operation.id, status: "pending" }];
      state.current_stage = "backfill";
      state.stage_state = "running";
      await this.setState(operation, state, [
        { seq: 0, status: "skipped" },
        { seq: 1, status: "active", detail: { plan_ids: state.source_backfill_plan_ids, authorization: "explicit_user_start" } },
        { seq: 2, status: "pending" },
        { seq: 3, status: "pending" },
        { seq: 4, status: "pending" },
      ]);
      await this.appendWorkflowCoverage(identity.spaceId, projectId, workflowId, {
        from: normalizedFrom,
        to: normalizedTo,
        operation_id: operation.id,
        status: "pending",
      });
      await new ProjectOperationService(this.db).link(identity.spaceId, projectId, operation.id, "research_workflow", workflowId, "workflow_definition");
      for (let index = 0; index < plans.length; index += 1) {
        await new ProjectOperationService(this.db).link(identity.spaceId, projectId, operation.id, "project_source_binding", bindingIds[index]!, "source_binding");
        await new ProjectOperationService(this.db).link(identity.spaceId, projectId, operation.id, "source_backfill_plan", String(plans[index]!.id), "history_backfill");
      }
      return this.readOperation(identity, projectId, operation.id);
    } catch (error) {
      await this.failOperation(operation, error instanceof Error ? error.message : "Historical backfill setup failed");
      throw error;
    }
  }

  async triggerIncremental(identity: SpaceUserIdentity, projectId: string, workflowId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const workflow = await this.workflow(identity.spaceId, projectId, workflowId);
    if (!workflow) throw new HttpError(404, "Research workflow not found");
    await this.assertResearchQuestionAligned(identity.spaceId, projectId, workflow.state_json);
    const state = researchState(workflow.state_json);
    const bindingIds = state.project_source_binding_ids?.length
      ? state.project_source_binding_ids
      : state.project_source_binding_id ? [state.project_source_binding_id] : [];
    if (!(state.channel_ids?.length ?? 0) || bindingIds.length !== state.channel_ids.length) {
      throw new HttpError(409, "The research workflow has not completed monitor setup");
    }
    if (objectValue(objectValue(workflow.state_json).monitoring).active !== true && state.monitoring_active !== true) {
      throw new HttpError(409, "Baseline research must complete its review checkpoints before incremental monitoring can run");
    }
    const historical = await this.activeHistoricalBackfill(identity.spaceId, projectId, workflowId);
    if (historical) throw new HttpError(409, "A historical backfill is already updating this research workflow");
    const key = optionalString(body.idempotency_key) ?? `incremental:${workflowId}:${new Date().toISOString().slice(0, 13)}`;
    const workflowState = objectValue(workflow.state_json);
    const pendingItemIds = stringArray(workflowState.pending_incremental_source_item_ids);
    const itemIds = unique([...pendingItemIds, ...stringArray(body.source_item_ids)]);
    if (pendingItemIds.length > 0) {
      await this.db.query(
        `UPDATE project_research_workflows SET state_json=state_json - 'pending_incremental_source_item_ids', updated_at=$4 WHERE space_id=$1 AND project_id=$2 AND id=$3`,
        [identity.spaceId, projectId, workflowId, new Date().toISOString()],
      );
    }
    const prior = await this.operationByIdempotency(identity.spaceId, projectId, key);
    if (prior && prior.status !== "failed" && prior.status !== "cancelled") {
      return this.readOperation(identity, projectId, prior.id);
    }
    const awaitingSourceScan = itemIds.length === 0;
    if (awaitingSourceScan) {
      if (!this.config) throw new HttpError(503, "Incremental source scans require server configuration");
      if (!state.channel_ids.length || !this.config) throw new HttpError(409, "Research workflow has no active search channels");
      for (const channelId of state.channel_ids) {
        await new SourceChannelService(this.db, this.config).scan(identity, channelId);
      }
    }
    const existing = await this.activeIncremental(identity.spaceId, projectId, workflowId);
    if (existing) {
      if (awaitingSourceScan) return this.readOperation(identity, projectId, existing.id);
      const existingState = researchState(existing.progress_json);
      const merged = { ...existingState, source_item_ids: unique([...existingState.source_item_ids, ...itemIds]) };
      await this.setState(existing, merged, deriveStepStates(merged));
      return this.readOperation(identity, projectId, existing.id);
    }

    const operationState = incrementalStateFromWorkflow(workflow.state_json, workflowId, itemIds, key, null);
    operationState.awaiting_source_scan = awaitingSourceScan;
    const operation = await this.createOperation(identity, projectId, {
      title: "Run incremental research update",
      intentText: "Scan new source content and prepare a human-reviewed research delta.",
      steps: operationSteps(),
      state: operationState,
    });
    await this.enqueueReconcile(identity.spaceId, identity.userId, operation.id, "incremental_trigger");
    return this.readOperation(identity, projectId, operation.id);
  }

  async decideCheckpoint(
    identity: SpaceUserIdentity,
    projectId: string,
    workflowId: string,
    checkpointId: string,
    body: Record<string, unknown>,
  ) {
    const research = new ProjectResearchRepository(this.db);
    const checkpoint = await research.decideCheckpoint(identity, projectId, workflowId, checkpointId, body);
    if (checkpoint.user_decision === "approved" || checkpoint.user_decision === "waived") {
      await this.resumeAfterCheckpoint(identity.spaceId, identity.userId, projectId, workflowId, checkpointId);
    } else if (checkpoint.user_decision === "rejected") {
      const operation = await this.operationForCheckpoint(identity.spaceId, projectId, checkpointId);
      if (operation) {
        await new ProjectResearchReportStatusService(this.db).transitionForOperation(identity.spaceId, operation.id, "rejected");
        await this.failOperation(operation, "Checkpoint rejected by user");
      }
    }
    return checkpoint;
  }

  async reconcileOperation(spaceId: string, operationId: string): Promise<void> {
    const row = await this.operation(spaceId, operationId);
    if (!row || row.status === "cancelled" || row.status === "completed") return;
    const state = researchState(row.progress_json);
    if (!state.workflow_id) return;

    if (state.current_stage === "monitor_setup") {
      await this.reconcileMonitorSetup(row, state);
      return;
    }

    if (state.current_stage === "synthesis") {
      if (!state.synthesis_run_id) {
        await this.recoverUnboundSynthesisStage(spaceId, row, state);
        return;
      }
      await this.reconcileSynthesisStage(spaceId, row, state);
      return;
    }

    if (state.current_stage === "comparison") {
      await this.reconcileComparisonStage(spaceId, row, state);
      return;
    }

    if (state.current_stage === "idea_review") {
      await this.reconcileIdeaReviewStage(spaceId, row, state);
      return;
    }

    const backfillPlanIds = state.source_backfill_plan_ids?.length
      ? state.source_backfill_plan_ids
      : state.source_backfill_plan_id ? [state.source_backfill_plan_id] : [];
    if ((state.run_kind === "baseline" || state.run_kind === "historical_backfill") && backfillPlanIds.length > 0) {
      const plans = await this.db.query<{
        id: string;
        status: string;
        segments_total: number | null;
        segments_completed: number | null;
        segments_failed: number | null;
        items_ingested: number | null;
        updated_at: string | null;
      }>(
        `SELECT id, status, segments_total, segments_completed, segments_failed, items_ingested, updated_at
           FROM source_backfill_plans
          WHERE id=ANY($1::text[]) AND space_id=$2`,
        [backfillPlanIds, spaceId],
      );
      const segmentProgress = await this.db.query<{
        total_segments: number;
        completed_segments: number;
        failed_segments: number;
        running_segments: number;
        pending_segments: number;
      }>(
        `SELECT
            count(*)::int AS total_segments,
            count(*) FILTER (WHERE status IN ('succeeded', 'skipped'))::int AS completed_segments,
            count(*) FILTER (WHERE status='failed')::int AS failed_segments,
            count(*) FILTER (WHERE status='running')::int AS running_segments,
            count(*) FILTER (WHERE status='pending')::int AS pending_segments
           FROM source_backfill_segments
          WHERE plan_id=ANY($1::text[]) AND space_id=$2`,
        [backfillPlanIds, spaceId],
      );
      const now = new Date().toISOString();
      const segmentTotals = segmentProgress.rows[0] ?? {
        total_segments: 0,
        completed_segments: 0,
        failed_segments: 0,
        running_segments: 0,
        pending_segments: 0,
      };
      state.backfill_progress = {
        total_segments: Number(segmentTotals.total_segments ?? 0),
        completed_segments: Number(segmentTotals.completed_segments ?? 0),
        failed_segments: Number(segmentTotals.failed_segments ?? 0),
        running_segments: Number(segmentTotals.running_segments ?? 0),
        pending_segments: Number(segmentTotals.pending_segments ?? 0),
        items_ingested: plans.rows.reduce((sum, plan) => sum + Number(plan.items_ingested ?? 0), 0),
        plans: plans.rows.map((plan) => ({
          id: plan.id,
          status: plan.status,
          segments_total: Number(plan.segments_total ?? 0),
          segments_completed: Number(plan.segments_completed ?? 0),
          segments_failed: Number(plan.segments_failed ?? 0),
          items_ingested: Number(plan.items_ingested ?? 0),
          updated_at: plan.updated_at,
        })),
        updated_at: now,
      };
      const backfillDone = plans.rows.length === backfillPlanIds.length && plans.rows.every((plan) => ["completed", "failed"].includes(plan.status));
      // Once the workflow has advanced past screening (synthesis, idea_review,
      // complete, failed, ...), this whole backfill->screening transition must
      // stay inert. Without this guard, backfillDone stays true forever (plans
      // never leave 'completed'), so every later reconcile tick would still
      // re-enter it, stomp current_stage back to "screening", and — since
      // createCheckpoint only recognizes a still-*pending* checkpoint as
      // "already exists" — mint a brand-new pending screening_gate checkpoint
      // even after the user already approved it and synthesis started. That is
      // exactly what "I approved the checkpoint but it came back after
      // refresh" looks like from the outside.
      const stillAtOrBeforeScreening = state.current_stage === "backfill" || state.current_stage === "screening";
      if (backfillDone && stillAtOrBeforeScreening && !plans.rows.some((plan) => plan.status === "failed")) {
        // Keep the items-in-scope list and screening progress fresh on every
        // reconcile tick, independent of whether classification batches are
        // still running. isSourcePipelineDrained below only gates the stage
        // transition (finalizing coverage and creating the screening_gate
        // checkpoint) — without this, "Papers classified"/"Batches" only ever
        // showed their pre-run (empty) and post-run (final) values, never
        // anything in between while batches were actually in flight.
        const sourceRecoveryPreview = new SourcePostProcessingRecoveryService(this.db);
        state.source_item_ids = await sourceRecoveryPreview.channelScopedItemIds(
          spaceId,
          state.channel_ids,
          unique([...state.source_item_ids, ...(await this.sourceItemsForBackfillPlans(spaceId, backfillPlanIds))]),
        );
        state.screening_progress = await this.screeningProgressFor(spaceId, row.project_id, row.id, state, row.created_at);
      }
      state.heartbeat_at = now;
      await this.setState(row, state, deriveStepStates(state));
      if (backfillDone && stillAtOrBeforeScreening) {
        if (plans.rows.some((plan) => plan.status === "failed")) {
          await this.failOperation(row, "Source history backfill failed");
          return;
        }
        if (!(await this.isSourcePipelineDrained(spaceId, state))) return;
        const partialSegment = await this.db.query<{ count: string }>(
          `SELECT count(*)::int AS count FROM source_backfill_segments
            WHERE plan_id=ANY($1::text[]) AND space_id=$2 AND window_json->>'partial'='true'
              AND COALESCE(window_json->>'exhausted','false') <> 'true'`,
          [backfillPlanIds, spaceId],
        );
        state.partial = Number(partialSegment.rows[0]?.count ?? 0) > 0;
        const sourceRecovery = new SourcePostProcessingRecoveryService(this.db);
        state.watermark = {
          ...state.watermark,
          after: state.watermark.after ?? new Date().toISOString(),
        };
        state.current_stage = "screening";
        state.stage_state = "running";
        const preparation = await sourceRecovery.ensureItemsProcessed({
          spaceId,
          projectId: row.project_id,
          channelIds: state.channel_ids,
          ruleIds: unique([
            ...state.source_post_processing_rule_ids,
            ...(state.source_post_processing_rule_id ? [state.source_post_processing_rule_id] : []),
          ]),
          sourceItemIds: state.source_item_ids,
          operationId: row.id,
          recoveryRequestedAt: state.post_processing_recovery_requested_at,
          operationCreatedAt: row.created_at,
          researchQuestionVersion: state.research_question_version,
        });
        if (preparation.status === "failed") {
          await this.failOperation(row, preparation.message);
          return;
        }
        if (preparation.status === "waiting") {
          state.post_processing_recovery_requested_at = preparation.requestedAt;
          state.screening_progress = await this.screeningProgressFor(
            spaceId,
            row.project_id,
            row.id,
            state,
            row.created_at,
          );
          state.screening_progress = {
            ...state.screening_progress,
            started_at: preparation.requestedAt,
          };
          state.heartbeat_at = new Date().toISOString();
          await this.setState(row, state, deriveStepStates(state));
          return;
        }
        delete state.post_processing_recovery_requested_at;
        state.screening_progress = await this.screeningProgressFor(
          spaceId,
          row.project_id,
          row.id,
          state,
          row.created_at,
        );
        state.heartbeat_at = new Date().toISOString();
        if (state.run_kind === "historical_backfill") {
          const count = await this.countRelevantItems(spaceId, row.project_id, state.source_item_ids);
          if (count.relevant + count.maybe === 0) {
            state.current_stage = "complete";
            state.stage_state = "skipped";
            const completedState = withOperationCoverageStatus(state, row.id, state.partial ? "partial" : "completed");
            await this.setState(row, completedState, deriveSkippedAfterScreeningSteps());
            await this.completeWorkflowCoverage(spaceId, row.project_id, state.workflow_id, row.id, state.partial ? "partial" : "completed");
            await this.flushPendingIncremental(spaceId, row.project_id, state.workflow_id);
          } else {
            await this.createScreeningGate(row, state);
          }
        } else {
          if (Number(state.screening_progress?.total_items ?? state.source_item_ids.length) === 0) {
            await this.completeEmptyInitialIntake(row, state);
          } else {
            await this.createScreeningGate(row, state);
          }
        }
      }
      return;
    }

    if ((state.run_kind === "incremental" || state.run_kind === "question_rescreen") && state.current_stage === "screening") {
      if (state.awaiting_source_scan && state.source_item_ids.length === 0) return;
      if (state.run_kind === "question_rescreen") {
        const preparation = await new SourcePostProcessingRecoveryService(this.db).ensureItemsProcessed({
          spaceId,
          projectId: row.project_id,
          channelIds: state.channel_ids,
          ruleIds: state.source_post_processing_rule_ids,
          sourceItemIds: state.source_item_ids,
          operationId: row.id,
          recoveryRequestedAt: state.post_processing_recovery_requested_at,
          operationCreatedAt: row.created_at,
          researchQuestionVersion: state.research_question_version,
        });
        if (preparation.status === "failed") {
          await this.failOperation(row, preparation.message);
          return;
        }
        if (preparation.status === "waiting") {
          state.post_processing_recovery_requested_at = preparation.requestedAt;
          state.screening_progress = await this.screeningProgressFor(spaceId, row.project_id, row.id, state, row.created_at);
          state.screening_progress.started_at = preparation.requestedAt;
          state.heartbeat_at = new Date().toISOString();
          await this.setState(row, state, deriveStepStates(state));
          return;
        }
        delete state.post_processing_recovery_requested_at;
      }
      state.screening_progress = await this.screeningProgressFor(
        spaceId,
        row.project_id,
        row.id,
        state,
        row.created_at,
      );
      state.heartbeat_at = new Date().toISOString();
      const count = await this.countRelevantItems(spaceId, row.project_id, state.source_item_ids);
      if (state.run_kind === "incremental") await this.recordScanSummary(row, state, count);
      if (count.relevant + count.maybe === 0) {
        state.current_stage = "complete";
        state.stage_state = "skipped";
        state.screening_progress = {
          ...state.screening_progress,
          phase: "completed",
          message: "No relevant or maybe papers were found in this update.",
        };
        await this.setState(row, state, deriveSkippedAfterScreeningSteps());
      } else {
        await this.createScreeningGate(row, state);
      }
    }
  }

  private async reconcileMonitorSetup(row: OperationRow, state: ResearchOperationState): Promise<void> {
    const planIds = state.source_backfill_plan_ids?.length
      ? state.source_backfill_plan_ids
      : state.source_backfill_plan_id ? [state.source_backfill_plan_id] : [];
    const plans = await this.db.query<{ id: string }>(
      `SELECT id FROM source_backfill_plans
        WHERE space_id=$1
          AND (project_operation_id=$2 OR id=ANY($3::text[]))
        ORDER BY created_at ASC`,
      [row.space_id, row.id, planIds],
    );
    if (plans.rows.length === 0) return;

    const next = { ...state };
    next.source_backfill_plan_ids = unique(plans.rows.map((plan) => plan.id));
    next.source_backfill_plan_id = next.source_backfill_plan_ids[0] ?? null;
    next.current_stage = "backfill";
    next.stage_state = "running";
    await this.setState(row, next, deriveStepStates(next));
  }

  private async reconcileIdeaReviewStage(spaceId: string, row: OperationRow, state: ResearchOperationState): Promise<void> {
    const checkpoint = await this.db.query<{
      id: string;
      status: string;
      decided_by_user_id: string | null;
    }>(
      `SELECT id, status, decided_by_user_id
         FROM project_research_checkpoints
        WHERE space_id=$1 AND project_id=$2 AND workflow_id=$3
          AND checkpoint_type='idea_review'
          AND machine_result_json->>'operation_id'=$4
          AND status IN ('approved','waived')
        ORDER BY updated_at DESC LIMIT 1`,
      [spaceId, row.project_id, state.workflow_id, row.id],
    );
    const value = checkpoint.rows[0];
    if (!value) return;
    const actorUserId = value.decided_by_user_id ?? await this.projectWriterActor(spaceId, row.project_id);
    if (!actorUserId) return;
    await this.resumeAfterCheckpoint(spaceId, actorUserId, row.project_id, state.workflow_id, value.id);
  }

  /**
   * A synthesis stage with no bound run can never progress: the stage
   * reconciler needs the run id, and nothing else re-queues. Every stage
   * writer binds the run in the same transition that enters synthesis, so
   * this state only appears when a binding write was lost. Adopt the newest
   * synthesis run recorded for this operation, or fail the operation into a
   * retryable state when none exists.
   */
  private async recoverUnboundSynthesisStage(spaceId: string, row: OperationRow, state: ResearchOperationState): Promise<void> {
    if (state.synthesis_critique?.status === "needs_queue") {
      const actor = await this.projectWriterActor(spaceId, row.project_id);
      if (!actor) {
        await this.failOperation(row, "Synthesis critique could not resolve a project writer");
        return;
      }
      try {
        await this.queueCritique({ spaceId, userId: actor, projectId: row.project_id, operationId: row.id, workflowId: state.workflow_id });
      } catch (error) {
        await this.failOperation(row, error instanceof Error ? error.message : "Failed to queue synthesis critique");
      }
      return;
    }
    if (state.synthesis_critique?.status === "revision_needed") {
      const actor = await this.projectWriterActor(spaceId, row.project_id);
      if (!actor) {
        await this.failOperation(row, "Synthesis revision could not resolve a project writer");
        return;
      }
      try {
        await this.queueSynthesisRevision({ spaceId, userId: actor, projectId: row.project_id, operationId: row.id, workflowId: state.workflow_id });
      } catch (error) {
        await this.failOperation(row, error instanceof Error ? error.message : "Failed to queue synthesis revision");
      }
      return;
    }
    const run = await this.db.query<{ id: string }>(
      `SELECT id FROM runs
        WHERE space_id=$1
          AND contract_snapshot_json->'workflow_input_json'->'project_research'->>'operation_id'=$2
          AND contract_snapshot_json->'workflow_input_json'->'project_research'->>'stage_key' IN ('synthesis','synthesis_revision','synthesis_critique')
        ORDER BY created_at DESC
        LIMIT 1`,
      [spaceId, row.id],
    );
    const runId = run.rows[0]?.id;
    if (!runId) {
      await this.failOperation(row, "The synthesis stage has no synthesis run bound and none exists for this operation; retry synthesis");
      return;
    }
    state.synthesis_run_id = runId;
    await this.setState(row, state, deriveStepStates(state));
    await this.reconcileSynthesisStage(spaceId, row, state);
  }

  /**
   * The agent_run terminal callback only nudges the reconciler. This periodic
   * pass is both the live read model for the stage — run status/queued/started,
   * so the UI can show what synthesis is actually doing — and the recovery
   * path that finalizes or fails the operation from the run's terminal state.
   */
  private async reconcileSynthesisStage(spaceId: string, row: OperationRow, state: ResearchOperationState): Promise<void> {
    const runId = state.synthesis_run_id!;
    const [run, job, event] = await Promise.all([
      this.db.query<{
        status: string;
        created_at: unknown;
        started_at: unknown;
        updated_at: unknown;
      }>(
        `SELECT status, created_at, started_at, updated_at FROM runs WHERE id=$1 AND space_id=$2`,
        [runId, spaceId],
      ),
      this.db.query<{
        id: string;
        status: string;
        attempts: number;
        heartbeat_at: unknown;
        updated_at: unknown;
      }>(
        `SELECT id, status, attempts, heartbeat_at, updated_at
           FROM jobs
          WHERE space_id=$1
            AND job_type='agent_run'
            AND payload_json->>'run_id'=$2
          ORDER BY created_at DESC
          LIMIT 1`,
        [spaceId, runId],
      ),
      this.db.query<{ event_type: string; created_at: unknown }>(
        `SELECT event_type, created_at
           FROM run_events
          WHERE space_id=$1 AND run_id=$2
          ORDER BY created_at DESC, event_index DESC, id DESC
          LIMIT 1`,
        [spaceId, runId],
      ),
    ]);
    const value = run.rows[0];
    if (!value) {
      await this.failOperation(row, "The queued synthesis run no longer exists; retry to queue a new synthesis run");
      return;
    }
    if (["succeeded", "degraded", "failed", "cancelled"].includes(value.status)) {
      await this.reconcileCompletedRun(spaceId, runId);
      const after = await this.operation(spaceId, row.id);
      const afterState = after ? researchState(after.progress_json) : null;
      if (after && !["completed", "failed", "cancelled"].includes(after.status) && afterState?.current_stage === "synthesis" && afterState.synthesis_run_id === runId) {
        await this.failOperation(after, `Synthesis run finished with status ${value.status} but its output could not be applied to this operation; retry synthesis`);
      }
      return;
    }
    const now = new Date().toISOString();
    state.synthesis_progress = {
      run_id: runId,
      run_status: value.status,
      job_id: job.rows[0]?.id ?? null,
      job_status: job.rows[0]?.status ?? null,
      job_attempts: job.rows[0]?.attempts ?? null,
      job_heartbeat_at: dateIso(job.rows[0]?.heartbeat_at),
      job_updated_at: dateIso(job.rows[0]?.updated_at),
      run_updated_at: dateIso(value.updated_at),
      last_event_at: dateIso(event.rows[0]?.created_at),
      last_event_type: event.rows[0]?.event_type ?? null,
      queued_at: dateIso(value.created_at),
      started_at: dateIso(value.started_at),
      updated_at: now,
      message: value.status === "running"
        ? "The synthesis agent is writing the structured research report from the approved corpus."
        : "The synthesis run is queued and waiting for an agent worker to pick it up.",
    };
    state.heartbeat_at = now;
    await this.setState(row, state, deriveStepStates(state));
  }

  async reconcileRun(spaceId: string, runId: string): Promise<void> {
    const run = await this.db.query<{ contract_snapshot_json: unknown }>(
      `SELECT contract_snapshot_json FROM runs WHERE id=$1 AND space_id=$2`,
      [runId, spaceId],
    );
    const workflowInput = objectValue(objectValue(run.rows[0]?.contract_snapshot_json).workflow_input_json);
    if (workflowInput.research_adhoc) {
      await new ProjectResearchWorkspaceService(this.db, this.config).applyAdhocRunOutput(spaceId, runId);
      return;
    }
    const contract = objectValue(workflowInput.project_research);
    const operationId = optionalString(contract.operation_id);
    if (!operationId) return;
    await this.reconcileOperation(spaceId, operationId);
  }

  async reconcileCompletedRun(spaceId: string, runId: string): Promise<void> {
    const run = await this.db.query<{ id: string; project_id: string | null; instructed_by_user_id: string | null; status: string; output_json: unknown; contract_snapshot_json: unknown; error_message: string | null; error_json: unknown }>(
      `SELECT id, project_id, instructed_by_user_id, status, output_json, contract_snapshot_json, error_message, error_json FROM runs WHERE id=$1 AND space_id=$2`,
      [runId, spaceId],
    );
    const row = run.rows[0];
    const contract = objectValue(objectValue(row?.contract_snapshot_json).workflow_input_json).project_research;
    if (!row || !row.project_id || !contract || typeof contract !== "object") return;
    const researchContract = objectValue(contract);
    const operationId = optionalString(researchContract.operation_id);
    const workflowId = optionalString(researchContract.workflow_id);
    const stageKey = optionalString(researchContract.stage_key);
    if (!operationId || !workflowId || !["monitor_compare", "synthesis", "synthesis_revision", "synthesis_critique"].includes(stageKey ?? "")) return;
    const operation = await this.operation(spaceId, operationId);
    if (!operation) return;
    if (!["succeeded", "degraded"].includes(row.status)) {
      const runError = objectValue(row.error_json);
      const detail = optionalString(row.error_message)
        ?? optionalString(runError.error_message)
        ?? optionalString(runError.message)
        ?? optionalString(runError.agent_run_error_code)
        ?? optionalString(runError.error_code);
      const runLabel = stageKey === "monitor_compare" ? "Monitoring comparison run" : "Synthesis agent run";
      await this.failOperation(operation, `${runLabel} ${row.status}${detail ? `: ${detail}` : " with no recorded error detail"}`);
      return;
    }

    if (stageKey === "monitor_compare") {
      const expected = Array.isArray(researchContract.source_item_ids)
        ? researchContract.source_item_ids.filter((item): item is string => typeof item === "string")
        : [];
      try {
        const result = await new ProjectResearchMonitorComparisonService(this.db).materialize({
          spaceId,
          projectId: row.project_id,
          workflowId,
          operationId,
          runId,
          output: row.output_json,
          expectedSourceItemIds: expected,
        });
        await transitionResearchOperation(this.db, spaceId, operationId, {
          from: ["comparison"],
          to: "complete",
          mutate: (ctx) => {
            ctx.state.stage_state = "succeeded";
            ctx.state.monitoring_active = true;
            ctx.state.heartbeat_at = new Date().toISOString();
          },
          stepOverrides: [
            { seq: 0, status: "done" }, { seq: 1, status: "done" }, { seq: 2, status: "done" },
            { seq: 3, status: "done", detail: { run_id: runId, notebook_version: result.notebookVersion, comparison_count: result.comparisons.length } },
            { seq: 4, status: "skipped" },
          ],
        });
        const completed = await this.operation(spaceId, operationId);
        if (completed?.status === "completed") {
          await this.setWorkflowMonitoring(spaceId, row.project_id, workflowId, researchState(completed.progress_json));
          await this.enqueueIntegrityMonitor(spaceId, row.instructed_by_user_id, row.project_id, workflowId, "comparison_complete");
        }
      } catch (error) {
        await this.failOperation(operation, error instanceof Error ? error.message : "Monitoring comparison output is invalid");
      }
      return;
    }

    if (stageKey === "synthesis_critique") {
      await this.reconcileCompletedCritique({
        spaceId,
        projectId: row.project_id,
        workflowId,
        operation,
        runId,
        userId: await this.projectWriterActor(spaceId, row.project_id),
        output: row.output_json,
      });
      return;
    }

    const synthesisResult = inspectSynthesisResult(row.output_json);
    if (synthesisResult?.kind === "invalid") {
      await this.failOperation(operation, synthesisResult.message, { code: "synthesis_output_invalid" });
      return;
    }
    if (synthesisResult?.kind === "rejected") {
      await this.failOperation(operation, synthesisResult.rejection.message, {
        code: "synthesis_rejected",
        rejection: synthesisResult.rejection,
      });
      return;
    }

    const materialization = objectValue(row.output_json).materialization;
    const materialized = Array.isArray(materialization) ? materialization : [];
    const artifacts: ResearchArtifactRecord[] = [];
    for (const item of materialized) {
      const value = objectValue(item);
      const artifactId = optionalString(value.artifact_id);
      if (!artifactId) continue;
      const artifact = await this.db.query<{ id: string; artifact_type: string; content: string | null }>(
        `SELECT id, artifact_type, content FROM artifacts WHERE id=$1 AND space_id=$2 AND project_id=$3`,
        [artifactId, spaceId, row.project_id],
      );
      if (artifact.rows[0]) artifacts.push(artifact.rows[0]);
    }
    const validation = await validateResearchArtifacts(artifacts);
    if (!validation.ok) {
      await this.recordSynthesisValidationFailure(spaceId, runId, validation.failure);
      await this.failOperation(operation, validation.failure.message, {
        code: validation.failure.code,
        diagnostics: validation.failure.diagnostics,
      });
      return;
    }
    if (validation.normalized_content) {
      await this.db.query(
        `UPDATE artifacts SET content=$1, updated_at=now() WHERE id=$2 AND space_id=$3`,
        [validation.normalized_content, validation.archive.id, spaceId],
      );
    }
    await withQueryableTransaction(this.db, async (db) => {
      const tx = new ProjectResearchOrchestrator(db, this.config);
      await tx.stageSynthesisCandidate({
        spaceId, projectId: row.project_id!, workflowId, operationId: operation.id, runId,
        report: validation.report, archiveArtifactId: validation.archive.id,
      });
    });
    const actor = await this.projectWriterActor(spaceId, row.project_id);
    if (!actor) {
      await this.failOperation(operation, "Research synthesis critique requires a project writer");
      return;
    }
    try {
      await this.queueCritique({ spaceId, userId: actor, projectId: row.project_id, operationId: operation.id, workflowId });
    } catch (error) {
      await this.failOperation(operation, error instanceof Error ? error.message : "Failed to queue synthesis critique");
    }
  }

  private async stageSynthesisCandidate(input: {
    spaceId: string; projectId: string; workflowId: string; operationId: string; runId: string;
    report: Record<string, unknown>; archiveArtifactId: string;
  }): Promise<void> {
    const locked = await this.db.query<OperationRow>(
      `SELECT id,space_id,project_id,kind,title,intent_text,status,progress_json,created_at,updated_at
         FROM project_operations WHERE space_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`,
      [input.spaceId, input.projectId, input.operationId],
    );
    const operation = locked.rows[0];
    if (!operation) throw new HttpError(404, "Research operation not found");
    const state = researchState(operation.progress_json);
    if (state.synthesis_critique?.report_run_id === input.runId) return;
    const previous = state.synthesis_critique;
    const numberedReport = await assignReportReferenceIds(this.db, input.spaceId, input.report);
    await this.db.query(
      `UPDATE artifacts SET content=$1, updated_at=$2 WHERE id=$3 AND space_id=$4 AND project_id=$5`,
      [JSON.stringify(numberedReport), new Date().toISOString(), input.archiveArtifactId, input.spaceId, input.projectId],
    );
    if (previous && previous.archive_artifact_id !== input.archiveArtifactId) {
      await this.db.query(
        `UPDATE artifacts
            SET surface_role='system_archive',
                metadata_json=COALESCE(metadata_json,'{}'::jsonb) || $1::jsonb,
                updated_at=$2
          WHERE id=$3 AND space_id=$4 AND project_id=$5`,
        [JSON.stringify({ superseded_by_run_id: input.runId }), new Date().toISOString(), previous.archive_artifact_id, input.spaceId, input.projectId],
      );
    }
    state.synthesis_run_id = null;
    state.synthesis_critique = {
      status: "needs_queue",
      run_id: null,
      report_run_id: input.runId,
      archive_artifact_id: input.archiveArtifactId,
      round: previous?.status === "revision_needed" || previous?.revision_count === 1 ? 1 : 0,
      revision_count: previous?.revision_count ?? 0,
      issues: [],
      all_issues: previous?.all_issues ?? [],
      artifact_ids: previous?.artifact_ids ?? [],
    };
    state.synthesis_progress = {
      run_id: input.runId,
      run_status: "succeeded",
      queued_at: null,
      started_at: null,
      updated_at: new Date().toISOString(),
      message: "The report draft is complete and queued for an adversarial critique pass.",
    };
    await this.setState(operation, state, deriveStepStates(state));
  }

  private async reconcileCompletedCritique(input: {
    spaceId: string;
    projectId: string;
    workflowId: string;
    operation: OperationRow;
    runId: string;
    userId: string | null;
    output: unknown;
  }): Promise<void> {
    if (!input.userId) {
      await this.failOperation(input.operation, "Synthesis critique could not resolve a project writer");
      return;
    }
    const result = critiqueResult(input.output);
    if (!result) {
      await this.failOperation(input.operation, "Synthesis critique output is invalid", { code: "synthesis_critique_output_invalid" });
      return;
    }
    let revisionNeeded = false;
    await withQueryableTransaction(this.db, async (db) => {
      const locked = await db.query<OperationRow>(
        `SELECT id,space_id,project_id,kind,title,intent_text,status,progress_json,created_at,updated_at
           FROM project_operations WHERE space_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`,
        [input.spaceId, input.projectId, input.operation.id],
      );
      const operation = locked.rows[0];
      if (!operation) throw new HttpError(404, "Research operation not found");
      const state = researchState(operation.progress_json);
      const critique = state.synthesis_critique;
      if (!critique || critique.run_id !== input.runId || critique.status === "completed") return;
      const critiqueArtifactId = await this.ensureCritiqueArtifact(db, {
        ...input,
        userId: input.userId!,
        result,
        round: critique.round,
      });
      critique.verdict = result.verdict;
      critique.issues = result.issues;
      critique.all_issues = [...critique.all_issues, ...result.issues];
      critique.artifact_ids = unique([...critique.artifact_ids, critiqueArtifactId]);
      state.artifact_ids = unique([...state.artifact_ids, critiqueArtifactId]);
      const hasCritical = result.issues.some((issue) => issue.severity === "critical");
      revisionNeeded = state.report_depth === "full" && result.verdict === "revise" && hasCritical && critique.revision_count < 1;
      if (revisionNeeded) {
        critique.status = "revision_needed";
        critique.revision_count = 1;
        state.synthesis_run_id = null;
        state.synthesis_progress = {
          run_id: input.runId,
          run_status: "succeeded",
          queued_at: null,
          started_at: null,
          updated_at: new Date().toISOString(),
          message: "The critique found a critical issue; one bounded synthesis revision is queued.",
        };
        await new ProjectResearchOrchestrator(db, this.config).setState(operation, state, deriveStepStates(state));
        return;
      }

      const artifact = await db.query<{ content: string | null }>(
        `SELECT content FROM artifacts WHERE id=$1 AND space_id=$2 AND project_id=$3`,
        [critique.archive_artifact_id, input.spaceId, input.projectId],
      );
      if (!artifact.rows[0]?.content) throw new HttpError(500, "Critiqued synthesis report is unavailable");
      const report = objectValue(JSON.parse(artifact.rows[0].content));
      report.limitations = appendCritiqueLimitations(report.limitations, critique.all_issues, critique.round > 0 || state.report_depth === "quick");
      const strategy = await db.query<{ id: string; providers_json: unknown; queries_json: unknown; hit_counts_json: unknown; provider_errors_json: unknown }>(
        `SELECT id,providers_json,queries_json,hit_counts_json,provider_errors_json
           FROM research_search_strategies WHERE space_id=$1 AND operation_id=$2 ORDER BY created_at DESC LIMIT 1`,
        [input.spaceId, input.operation.id],
      );
      if (strategy.rows[0]) {
        const row = strategy.rows[0];
        const line = `[search strategy ${row.id}] providers=${JSON.stringify(row.providers_json)}; queries=${JSON.stringify(row.queries_json)}; hits=${JSON.stringify(row.hit_counts_json)}; provider_errors=${JSON.stringify(row.provider_errors_json)}`;
        report.limitations = unique([...stringArray(report.limitations), line]);
      }
      await db.query(
        `UPDATE artifacts SET content=$1, updated_at=$2 WHERE id=$3 AND space_id=$4`,
        [JSON.stringify(report), new Date().toISOString(), critique.archive_artifact_id, input.spaceId],
      );
      critique.status = "completed";
      state.synthesis_run_id = input.runId;
      await new ProjectResearchOrchestrator(db, this.config).setState(operation, state, deriveStepStates(state));
      await new ProjectResearchOrchestrator(db, this.config).persistCompletedSynthesis({
        spaceId: input.spaceId,
        projectId: input.projectId,
        workflowId: input.workflowId,
        operationId: input.operation.id,
        runId: critique.report_run_id,
        report,
        archiveArtifactId: critique.archive_artifact_id,
      });
    });
    if (revisionNeeded) {
      try {
        await this.queueSynthesisRevision({
          spaceId: input.spaceId,
          userId: input.userId,
          projectId: input.projectId,
          operationId: input.operation.id,
          workflowId: input.workflowId,
        });
      } catch (error) {
        const operation = await this.operation(input.spaceId, input.operation.id);
        if (operation) await this.failOperation(operation, error instanceof Error ? error.message : "Failed to queue synthesis revision");
      }
    }
  }

  private async ensureCritiqueArtifact(db: Queryable, input: {
    spaceId: string;
    projectId: string;
    workflowId: string;
    operation: OperationRow;
    runId: string;
    userId: string;
    result: CritiqueResult;
    round: number;
  }): Promise<string> {
    const existing = await db.query<{ id: string }>(
      `SELECT id FROM artifacts WHERE space_id=$1 AND run_id=$2 AND artifact_type='research_critique' LIMIT 1`,
      [input.spaceId, input.runId],
    );
    if (existing.rows[0]) return existing.rows[0].id;
    const id = randomUUID();
    const now = new Date().toISOString();
    await db.query(
      `INSERT INTO artifacts (
         id,space_id,run_id,project_id,artifact_type,surface_role,title,content,mime_type,
         exportable,export_formats_json,canonical_format,preview,created_at,updated_at,
         metadata_json,visibility,owner_user_id,trust_level
       ) VALUES ($1,$2,$3,$4,'research_critique','operational',$5,$6,'application/json',
         true,'["json"]'::jsonb,'json',false,$7,$7,$8::jsonb,'space_shared',$9,'high')`,
      [
        id, input.spaceId, input.runId, input.projectId,
        `Research synthesis critique · round ${input.round + 1}`,
        JSON.stringify({ schema_version: "research_critique.v1", round: input.round, ...input.result }),
        now,
        JSON.stringify({ project_research_operation_id: input.operation.id, project_research_workflow_id: input.workflowId }),
        input.userId,
      ],
    );
    return id;
  }

  private async persistCompletedSynthesis(input: {
    spaceId: string; projectId: string; workflowId: string; operationId: string; runId: string;
    report: Record<string, unknown>; archiveArtifactId: string;
  }): Promise<void> {
    const locked = await this.db.query<OperationRow>(
      `SELECT id,space_id,project_id,kind,title,intent_text,status,progress_json,created_at,updated_at
         FROM project_operations WHERE space_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`,
      [input.spaceId, input.projectId, input.operationId],
    );
    const operation = locked.rows[0];
    if (!operation) throw new HttpError(404, "Research operation not found");
    const state = researchState(operation.progress_json);
    const materialized = await new ProjectResearchReportMaterializer(this.db).materialize({
      spaceId: input.spaceId, projectId: input.projectId, workflowId: input.workflowId,
      operationId: input.operationId, synthesisRunId: input.runId, runKind: state.run_kind,
      researchQuestion: state.research_question, researchQuestionVersion: state.research_question_version,
      report: input.report, archiveArtifactId: input.archiveArtifactId,
      literatureMatrixArtifactId: optionalString(state.matrix_artifact_id),
    });
    state.artifact_ids = unique([...state.artifact_ids, input.archiveArtifactId]);
    state.synthesis_run_id = input.runId;
    state.current_stage = "idea_review";
    state.stage_state = "waiting_review";
    await this.setState(operation, state, [
      { seq: 0, status: "done" }, { seq: 1, status: "done" }, { seq: 2, status: "done" },
      { seq: 3, status: "done", detail: { run_id: input.runId, report_id: materialized.id } },
      { seq: 4, status: "blocked", detail: { checkpoint_type: "idea_review", report_id: materialized.id } },
    ]);
    await this.createCheckpoint(input.spaceId, input.projectId, input.workflowId, operation.id, "idea_review", {
      operation_id: operation.id, run_kind: state.run_kind, report_id: materialized.id,
      idea_count: materialized.ideaCount, requires_batch_decision: true,
    });
  }

  async resumeAfterCheckpoint(spaceId: string, userId: string, projectId: string, workflowId: string, checkpointId: string): Promise<void> {
    const checkpoint = await this.db.query<{ checkpoint_type: string; status: string; machine_result_json: unknown }>(
      `SELECT checkpoint_type, status, machine_result_json FROM project_research_checkpoints WHERE id=$1 AND space_id=$2 AND project_id=$3 AND workflow_id=$4`,
      [checkpointId, spaceId, projectId, workflowId],
    );
    const value = checkpoint.rows[0];
    if (!value || !["approved", "waived"].includes(value.status)) return;
    const operationId = optionalString(objectValue(value.machine_result_json).operation_id);
    if (!operationId) return;
    const operation = await this.operation(spaceId, operationId);
    if (!operation) return;
    const state = researchState(operation.progress_json);
    if (value.checkpoint_type === "screening_gate") {
      const machineResult = objectValue(value.machine_result_json);
      const screeningTotal = typeof machineResult.total === "number" ? machineResult.total : null;
      if (screeningTotal === 0 && !state.synthesis_run_id) {
        throw new HttpError(409, "No papers matched this search window; revise the search query or date range and rescan before continuing");
      }
      try {
        // A not-applied transition means the operation already moved past
        // screening (converged); reuseExistingRun re-enters a run bound by an
        // earlier clobbered pass instead of queueing a duplicate.
        if (state.run_kind === "incremental") {
          await this.queueMonitorComparison({ spaceId, userId, projectId, operationId: operation.id, workflowId });
        } else {
          await this.queueSynthesis({
            spaceId,
            userId,
            projectId,
            operationId: operation.id,
            workflowId,
            from: ["screening", "synthesis"],
            reuseExistingRun: true,
          });
        }
      } catch (error) {
        await this.failOperation(operation, error instanceof Error ? error.message : "Failed to queue synthesis run");
        throw error;
      }
      return;
    }
    if (value.checkpoint_type === "idea_review") {
      await new ProjectResearchReportStatusService(this.db).transitionForOperation(spaceId, operation.id, "complete");
      state.current_stage = "complete";
      state.stage_state = "succeeded";
      state.monitoring_active = true;
      const completedState = (state.run_kind === "baseline" || state.run_kind === "historical_backfill")
        ? withOperationCoverageStatus(state, operation.id, state.partial ? "partial" : "completed")
        : state;
      await this.setState(operation, completedState, [
        { seq: 0, status: "done" },
        { seq: 1, status: "done" },
        { seq: 2, status: "done" },
        { seq: 3, status: "done" },
        { seq: 4, status: "done", detail: { checkpoint_id: checkpointId, decided_by_user_id: userId } },
      ]);
      await this.setWorkflowMonitoring(spaceId, projectId, workflowId, state);
      await this.enqueueIntegrityMonitor(spaceId, userId, projectId, workflowId, "monitoring_activated");
      if (state.run_kind === "baseline") {
        await this.completeWorkflowCoverage(spaceId, projectId, workflowId, operation.id, state.partial ? "partial" : "completed");
      }
      if (state.run_kind === "historical_backfill") {
        await this.completeWorkflowCoverage(spaceId, projectId, workflowId, operation.id, state.partial ? "partial" : "completed");
        await this.flushPendingIncremental(spaceId, projectId, workflowId);
      }
    }
  }

  async retryFailedOperation(identity: SpaceUserIdentity, projectId: string, operationId: string) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const operation = await this.operation(identity.spaceId, operationId);
    if (!operation || operation.project_id !== projectId) throw new HttpError(404, "Research operation not found");
    if (operation.status !== "failed") throw new HttpError(409, "Only failed research operations can be retried");
    const state = researchState(operation.progress_json);
    await this.assertResearchQuestionAligned(identity.spaceId, projectId, state.workflow_id ? (await this.workflow(identity.spaceId, projectId, state.workflow_id))?.state_json : null);
    const active = state.workflow_id ? await this.activeResearchOperation(identity.spaceId, projectId, state.workflow_id) : null;
    if (active && active.id !== operation.id) throw new HttpError(409, "Another Project Research operation is already active for this workflow");
    const failedStage = researchStage(state.failed_stage ?? state.current_stage);
    if (state.run_kind === "baseline" && failedStage === "monitor_setup") {
      return this.retryMonitorSetup(identity, projectId, state);
    }

    const backfillPlanIds = state.source_backfill_plan_ids?.length
      ? state.source_backfill_plan_ids
      : state.source_backfill_plan_id ? [state.source_backfill_plan_id] : [];
    const ruleIds = unique([
      ...state.source_post_processing_rule_ids,
      ...(state.source_post_processing_rule_id ? [state.source_post_processing_rule_id] : []),
    ]);
    if (
      (state.run_kind === "baseline" || state.run_kind === "historical_backfill")
      && (failedStage === "backfill" || failedStage === "screening")
      && ruleIds.length > 0
    ) {
      await this.ensureResearchProcessingBatchSize(identity, ruleIds);
      const failedPlans = backfillPlanIds.length
        ? await this.db.query<{ id: string }>(
          `SELECT id FROM source_backfill_plans
             WHERE space_id=$1 AND id=ANY($2::text[]) AND status='failed'`,
          [identity.spaceId, backfillPlanIds],
        )
        : { rows: [] as Array<{ id: string }> };
      if (failedStage === "backfill" && failedPlans.rows.length > 0) {
        state.current_stage = "backfill";
        state.stage_state = "running";
        delete state.failed_stage;
        await this.setState(operation, state, deriveStepStates(state));
        try {
          for (const plan of failedPlans.rows) {
            await new SourceBackfillExecutionService(this.db).retry(identity.spaceId, plan.id);
          }
          await this.enqueueReconcile(identity.spaceId, identity.userId, operation.id, "retry_backfill");
        } catch (error) {
          await this.failOperation(operation, error instanceof Error ? error.message : "Research backfill retry failed");
          throw error;
        }
        return this.readOperation(identity, projectId, operation.id);
      }

      state.current_stage = "screening";
      state.stage_state = "running";
      state.post_processing_recovery_requested_at = new Date().toISOString();
      state.screening_progress = state.screening_progress
        ? { ...state.screening_progress, phase: "preparing_batches", started_at: state.post_processing_recovery_requested_at, message: "Preparing screening batches for retry." }
        : undefined;
      delete state.failed_stage;
      await this.setState(operation, state, deriveStepStates(state));
      await this.enqueueReconcile(identity.spaceId, identity.userId, operation.id, "retry_screening");
      return this.readOperation(identity, projectId, operation.id);
    }

    if (failedStage === "synthesis") {
      // queueSynthesis performs the failed -> synthesis transition, the new
      // run, and its job in one transaction: the retry either fully takes
      // effect or changes nothing and the operation stays failed/retryable.
      const queued = await this.queueSynthesis({
        spaceId: identity.spaceId,
        userId: identity.userId,
        projectId,
        operationId: operation.id,
        workflowId: state.workflow_id,
        from: ["failed"],
        reuseExistingRun: false,
      });
      if (!queued.applied) throw new HttpError(409, "Research operation changed while retrying synthesis; reload and retry");
      return this.readOperation(identity, projectId, operation.id);
    }

    if (failedStage === "comparison") {
      state.comparison_run_id = null;
      state.comparison_source_item_ids = [];
      const queued = await this.queueMonitorComparison({
        spaceId: identity.spaceId,
        userId: identity.userId,
        projectId,
        operationId: operation.id,
        workflowId: state.workflow_id,
      });
      if (!queued.applied) throw new HttpError(409, "Research operation changed while retrying comparison; reload and retry");
      return this.readOperation(identity, projectId, operation.id);
    }

    state.current_stage = failedStage;
    delete state.failed_stage;
    state.stage_state = "running";
    await this.setState(operation, state, deriveStepStates(state));
    try {
      if (failedStage === "backfill" && state.source_backfill_plan_id) {
        await new SourceBackfillExecutionService(this.db).retry(identity.spaceId, state.source_backfill_plan_id);
      } else {
        await this.enqueueReconcile(identity.spaceId, identity.userId, operation.id, "retry");
      }
    } catch (error) {
      await this.failOperation(operation, error instanceof Error ? error.message : "Research retry failed");
      throw error;
    }
    return this.readOperation(identity, projectId, operation.id);
  }

  /**
   * Repair-only action for a stale operation projection. It observes the
   * canonical run and applies the normal reconciliation rules; it never
   * queues or re-executes a synthesis run.
   */
  async reconcileOperationForUser(identity: SpaceUserIdentity, projectId: string, operationId: string) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const operation = await this.operation(identity.spaceId, operationId);
    if (!operation || operation.project_id !== projectId) throw new HttpError(404, "Research operation not found");
    const beforeState = researchState(operation.progress_json);
    const boundRunId = beforeState.synthesis_run_id;
    const boundRun = boundRunId
      ? await this.db.query<{ status: string; updated_at: unknown }>(
        `SELECT status, updated_at FROM runs WHERE id=$1 AND space_id=$2`,
        [boundRunId, identity.spaceId],
      )
      : { rows: [] as Array<{ status: string; updated_at: unknown }> };
    const boundRunSnapshot = boundRun.rows[0] ?? null;
    await this.reconcileOperation(identity.spaceId, operation.id);
    let reconciled = await this.operation(identity.spaceId, operation.id);
    if (!reconciled) throw new HttpError(404, "Research operation disappeared during reconciliation");

    // A terminal canonical run must never leave its owning operation active.
    // If the normal artifact projection could not advance it, make the
    // failure explicit and retryable instead of returning another silent
    // synthesis state to the UI.
    const reconciledState = researchState(reconciled.progress_json);
    const terminalRun = boundRunSnapshot && ["succeeded", "degraded", "failed", "cancelled"].includes(boundRunSnapshot.status);
    if (
      terminalRun
      && reconciled.status === "active"
      && reconciledState.current_stage === "synthesis"
      && reconciledState.synthesis_run_id === boundRunId
    ) {
      await this.failOperation(reconciled, "The synthesis run is terminal but its result could not be applied to the research operation; retry synthesis", {
        code: "research_operation_reconcile_stuck",
        diagnostics: {
          operation_id: operation.id,
          run_id: boundRunId,
          run_status: boundRunSnapshot.status,
          run_updated_at: dateIso(boundRunSnapshot.updated_at),
          reconciliation: "terminal_run_active_operation_fallback",
        },
      });
      reconciled = await this.operation(identity.spaceId, operation.id);
      if (!reconciled) throw new HttpError(404, "Research operation disappeared after reconciliation fallback");
    }

    const result = await this.readOperation(identity, projectId, operation.id);
    return {
      ...result,
      reconcile_diagnostic: {
        operation_id: operation.id,
        bound_run_id: boundRunId,
        bound_run_status: boundRunSnapshot?.status ?? null,
        before_status: operation.status,
        after_status: reconciled.status,
        after_stage: researchState(reconciled.progress_json).current_stage,
      },
    };
  }

  /**
   * Updates the saved intake limit without requiring the rest of the intake
   * setup. Project Settings owns this value independently; the research
   * question and source monitors are only required when the user starts the
   * intake.
   */
  async updateInitialItemLimit(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    return withQueryableTransaction(this.db, (db) =>
      new ProjectResearchOrchestrator(db, this.config).updateInitialItemLimitLocked(identity, projectId, body),
    );
  }

  private async updateInitialItemLimitLocked(identity: SpaceUserIdentity, projectId: string, body: Record<string, unknown>) {
    const requestedLimit = Number(body.max_items);
    if (!Number.isInteger(requestedLimit) || requestedLimit < 1 || requestedLimit > MAX_ITEMS_DEFAULT) {
      throw new HttpError(422, `max_items must be an integer between 1 and ${MAX_ITEMS_DEFAULT}`);
    }
    const existing = await this.db.query<WorkflowRow>(
      `SELECT * FROM project_research_workflows
        WHERE space_id=$1 AND project_id=$2 AND status IN ('not_started','active','paused')
        ORDER BY updated_at DESC LIMIT 1 FOR UPDATE`,
      [identity.spaceId, projectId],
    );
    const now = new Date().toISOString();
    const current = existing.rows[0];
    if (current) {
      const operation = await this.db.query<{ id: string }>(
        `SELECT id FROM project_operations
          WHERE space_id=$1 AND project_id=$2 AND kind='research'
            AND status IN ('draft','active','waiting_review')
            AND progress_json->>'run_kind' IN ('baseline','historical_backfill')
          ORDER BY updated_at DESC LIMIT 1`,
        [identity.spaceId, projectId],
      );
      if (operation.rows[0]) {
        throw new HttpError(409, "An active Project Research operation owns the item limit");
      }
      const state = objectValue(current.state_json);
      const initialIntake = objectValue(state.initial_intake);
      const nextState = {
        ...state,
        initial_intake: { ...initialIntake, max_items: requestedLimit },
      };
      await this.db.query(
        `UPDATE project_research_workflows SET state_json=$4::jsonb, updated_at=$5
          WHERE space_id=$1 AND project_id=$2 AND id=$3`,
        [identity.spaceId, projectId, current.id, JSON.stringify(nextState), now],
      );
      const workflow = await this.workflow(identity.spaceId, projectId, current.id);
      if (!workflow) throw new HttpError(500, "Failed to update the research item limit");
      return workflowOutput(workflow);
    }

    const id = randomUUID();
    const state = {
      schema_version: "project_research_initial_intake.v1",
      initial_intake: { max_items: requestedLimit },
      draft: { status: "partial", saved_at: now },
    };
    await this.db.query(
      `INSERT INTO project_research_workflows
        (id,space_id,project_id,workflow_type,status,mode,current_stage,state_json,started_by_user_id,created_at,updated_at)
       VALUES ($1,$2,$3,'literature_review','not_started','autonomous','initial_intake_setup',$4::jsonb,$5,$6,$6)`,
      [id, identity.spaceId, projectId, JSON.stringify(state), identity.userId, now],
    );
    const workflow = await this.workflow(identity.spaceId, projectId, id);
    if (!workflow) throw new HttpError(500, "Failed to save the research item limit");
    return workflowOutput(workflow);
  }

  /**
   * Changes the effective research item limit only from the explicit Project
   * Settings action. Recovery actions such as rescan never choose or add a
   * budget on their own.
   */
  async updateItemLimit(identity: SpaceUserIdentity, projectId: string, operationId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    return withQueryableTransaction(this.db, (db) =>
      new ProjectResearchOrchestrator(db, this.config).updateItemLimitLocked(identity, projectId, operationId, body),
    );
  }

  private async updateItemLimitLocked(identity: SpaceUserIdentity, projectId: string, operationId: string, body: Record<string, unknown>) {
    const requestedLimit = Number(body.max_items);
    if (!Number.isInteger(requestedLimit) || requestedLimit < 1 || requestedLimit > MAX_ITEMS_DEFAULT) {
      throw new HttpError(422, `max_items must be an integer between 1 and ${MAX_ITEMS_DEFAULT}`);
    }
    const operation = await this.operation(identity.spaceId, operationId);
    if (!operation || operation.project_id !== projectId) throw new HttpError(404, "Research operation not found");
    const state = researchState(operation.progress_json);
    if (state.run_kind !== "baseline" && state.run_kind !== "historical_backfill") {
      throw new HttpError(409, "Only literature backfill operations have an item limit");
    }
    const planIds = state.source_backfill_plan_ids?.length
      ? state.source_backfill_plan_ids
      : state.source_backfill_plan_id ? [state.source_backfill_plan_id] : [];
    const currentLimit = state.history?.max_items;
    if (typeof currentLimit !== "number" || !Number.isInteger(currentLimit) || currentLimit < 1) {
      throw new HttpError(409, "This operation has no recorded item limit");
    }
    if (requestedLimit < currentLimit) {
      throw new HttpError(409, "An active research item limit can only be increased");
    }
    if (requestedLimit === currentLimit) return this.readOperation(identity, projectId, operation.id);

    // A monitor_setup operation has already captured the limit, but may not
    // have created plans yet (for example after a setup failure). Updating
    // that snapshot must still be independent of the question/source setup;
    // the next setup/retry pass will use the new explicit limit.
    if (planIds.length === 0) {
      const setupStage = state.failed_stage ?? state.current_stage;
      if (setupStage !== "monitor_setup") throw new HttpError(409, "This operation has no backfill plans");
      state.history = { ...(state.history ?? { mode: null, from: null, to: null, max_items: null }), max_items: requestedLimit };
      await this.setState(operation, state, deriveStepStates(state));
      return this.readOperation(identity, projectId, operation.id);
    }

    const additionalItems = requestedLimit - currentLimit;
    const wasPartial = state.partial;
    state.history = { ...(state.history ?? { mode: null, from: null, to: null, max_items: null }), max_items: requestedLimit };
    state.partial = false;
    state.current_stage = "backfill";
    state.stage_state = "running";
    delete state.failed_stage;
    await this.waivePendingScreeningCheckpoint(identity, projectId, state.workflow_id, operation.id, "Superseded by item limit update");
    await this.setState(operation, state, deriveStepStates(state));
    const execution = new SourceBackfillExecutionService(this.db);
    if (wasPartial) {
      if (!state.source_backfill_plan_id) throw new HttpError(409, "This partial operation has no resumable backfill plan");
      await execution.continuePartial(identity.spaceId, state.source_backfill_plan_id, additionalItems);
    } else {
      for (const planId of planIds) await execution.rescanZeroYield(identity.spaceId, planId, 0);
    }
    await this.enqueueReconcile(identity.spaceId, identity.userId, operation.id, "item_limit_update");
    return this.readOperation(identity, projectId, operation.id);
  }

  /**
   * Re-runs zero-yield windows against the monitor's current query. This is a
   * query-recovery action only; it never changes the operation's item budget.
   * Any budget change must go through updateItemLimit, which is the explicit
   * Project Settings path.
   */
  async rescanEmptyBackfill(identity: SpaceUserIdentity, projectId: string, operationId: string, body: Record<string, unknown>) {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const operation = await this.operation(identity.spaceId, operationId);
    if (!operation || operation.project_id !== projectId) throw new HttpError(404, "Research operation not found");
    const state = researchState(operation.progress_json);
    await this.assertResearchQuestionAligned(identity.spaceId, projectId, state.workflow_id ? (await this.workflow(identity.spaceId, projectId, state.workflow_id))?.state_json : null);
    if (!(state.run_kind === "baseline" || state.run_kind === "historical_backfill")) {
      throw new HttpError(409, "Only a literature intake or historical backfill operation can be rescanned");
    }
    if (state.partial) {
      throw new HttpError(409, "This partial backfill must be resumed by increasing the item limit in Project Settings");
    }
    const stage = state.failed_stage ?? state.current_stage;
    if (stage === "monitor_setup") {
      throw new HttpError(409, "This operation hasn't started importing literature yet");
    }
    const active = await this.activeResearchOperation(identity.spaceId, projectId, state.workflow_id);
    if (active && active.id !== operation.id) throw new HttpError(409, "Another Project Research operation is already active for this workflow");
    const additionalItems = body.additional_max_items === undefined ? 0 : Number(body.additional_max_items);
    if (!Number.isInteger(additionalItems) || additionalItems < 0 || additionalItems > MAX_ITEMS_DEFAULT) {
      throw new HttpError(422, `additional_max_items must be an integer between 0 and ${MAX_ITEMS_DEFAULT}`);
    }
    if (additionalItems > 0) {
      throw new HttpError(409, "Changing the item limit is only available from Project Settings");
    }
    const planIds = state.source_backfill_plan_ids?.length ? state.source_backfill_plan_ids : state.source_backfill_plan_id ? [state.source_backfill_plan_id] : [];
    if (planIds.length === 0) throw new HttpError(409, "This operation has no backfill plans to rescan");
    await this.waivePendingScreeningCheckpoint(identity, projectId, state.workflow_id, operation.id, "Superseded by rescan");
    state.partial = false;
    state.current_stage = "backfill";
    state.stage_state = "running";
    delete state.failed_stage;
    await this.setState(operation, state, deriveStepStates(state));
    const execution = new SourceBackfillExecutionService(this.db);
    for (const planId of planIds) await execution.rescanZeroYield(identity.spaceId, planId, 0);
    await this.enqueueReconcile(identity.spaceId, identity.userId, operation.id, "rescan_zero_yield");
    return this.readOperation(identity, projectId, operation.id);
  }

  async reconcileAll(spaceId: string): Promise<number> {
    const operations = await this.db.query<{ id: string }>(
      `SELECT id FROM project_operations WHERE space_id=$1 AND kind='research' AND status IN ('draft','active','waiting_review') ORDER BY updated_at ASC LIMIT 100`,
      [spaceId],
    );
    for (const operation of operations.rows) await this.reconcileOperation(spaceId, operation.id);
    return operations.rows.length;
  }

  async onPostProcessingRecoveryStarted(input: { spaceId: string; operationId: string }): Promise<void> {
    await this.enqueueReconcile(input.spaceId, null, input.operationId, "post_processing_recovery_started");
  }

  async onPostProcessingSucceeded(input: {
    spaceId: string;
    projectId: string | null;
    sourcePostProcessingRunId: string;
    userId: string | null;
  }): Promise<void> {
    if (!input.projectId) return;
    await this.enqueueReconcile(input.spaceId, input.userId, null, "post_processing_succeeded", {
      source_post_processing_run_id: input.sourcePostProcessingRunId,
    });
  }

  async reconcilePostProcessingRun(spaceId: string, runId: string): Promise<void> {
    await withQueryableTransaction(this.db, (db) =>
      new ProjectResearchOrchestrator(db, this.config).reconcilePostProcessingRunLocked(spaceId, runId));
  }

  private async reconcilePostProcessingRunLocked(spaceId: string, runId: string): Promise<void> {
    const result = await this.db.query<{
      id: string;
      project_id: string | null;
      source_channel_id: string;
      status: string;
      input_item_ids_json: unknown;
      triggered_by_user_id: string | null;
      research_reconciled_at: string | null;
    }>(
      `SELECT id, project_id, source_channel_id, status, input_item_ids_json, triggered_by_user_id,
              research_reconciled_at
         FROM source_post_processing_runs
        WHERE id=$1 AND space_id=$2
        FOR UPDATE`,
      [runId, spaceId],
    );
    const run = result.rows[0];
    if (!run || run.status !== "succeeded" || !run.project_id || run.research_reconciled_at) return;
    const sourceItemIds = stringArray(run.input_item_ids_json);
    if (sourceItemIds.length === 0) return;
    try {
      await this.syncPostProcessingCorpus(spaceId, run.project_id, sourceItemIds);

      const workflow = await this.db.query<{ id: string; state_json: unknown }>(
        `SELECT id, state_json FROM project_research_workflows WHERE space_id=$1 AND project_id=$2 AND status='active' ORDER BY updated_at DESC LIMIT 1`,
        [spaceId, run.project_id],
      );
      const candidate = workflow.rows[0];
      if (!candidate) return;
      const state = researchState(candidate.state_json);
      if (!(state.channel_ids ?? []).includes(run.source_channel_id)) return;
      if (await this.hasResearchQuestionDrift(spaceId, run.project_id, candidate.state_json)) {
        await this.appendPendingIncrementalItems(spaceId, run.project_id, candidate.id, sourceItemIds);
        return;
      }
      const cursor = await this.db.query<{ metadata_json: unknown }>(
        `SELECT metadata_json FROM scheduler_tasks WHERE task_type='source_channel_scan' AND task_key=$1 AND space_id=$2 LIMIT 1`,
        [run.source_channel_id, spaceId],
      );
      const watermarkAfter = optionalString(objectValue(objectValue(cursor.rows[0]?.metadata_json).cursor).last_published_at) ?? new Date().toISOString();
      const monitoringActive = objectValue(objectValue(candidate.state_json).monitoring).active === true || state.monitoring_active === true;
      if (!monitoringActive) {
        if (state.source_backfill_plan_id) {
          const baseline = await this.db.query<{ id: string }>(
            `SELECT id FROM project_operations
               WHERE space_id=$1 AND project_id=$2 AND kind='research'
                 AND ($3 = ANY(ARRAY(SELECT jsonb_array_elements_text(COALESCE(progress_json->'source_backfill_plan_ids', '[]'::jsonb)))) OR progress_json->>'source_backfill_plan_id'=$4)
               ORDER BY created_at DESC LIMIT 1`,
            [spaceId, run.project_id, state.source_backfill_plan_id, state.source_backfill_plan_id],
          );
          if (baseline.rows[0]) await this.reconcileOperation(spaceId, baseline.rows[0].id);
        }
        return;
      }
      const historical = await this.activeHistoricalBackfill(spaceId, run.project_id, candidate.id);
      if (historical) {
        const itemOrigins = await this.backfillPlanForItems(spaceId, sourceItemIds);
        const historicalPlanIds = researchState(historical.progress_json).source_backfill_plan_ids;
        const historicalIds = sourceItemIds.filter((id) => historicalPlanIds.includes(itemOrigins.get(id)?.created_plan_id ?? ""));
        const historicalUpdates = sourceItemIds.filter((id) => historicalPlanIds.includes(itemOrigins.get(id)?.last_plan_id ?? ""));
        const pendingIds = sourceItemIds.filter((id) => !historicalIds.includes(id) && !historicalUpdates.includes(id));
        if (historicalIds.length > 0) {
          await updateProjection(this.db, spaceId, historical.id, ({ state: current }) => {
            current.source_item_ids = unique([...current.source_item_ids, ...historicalIds]);
            current.watermark = { before: current.watermark.after, after: watermarkAfter, overlap_hours: OVERLAP_HOURS };
          }, deriveStepStates);
        }
        if (pendingIds.length > 0) {
          await this.appendPendingIncrementalItems(spaceId, run.project_id, candidate.id, pendingIds);
        }
        await this.reconcileOperation(spaceId, historical.id);
        return;
      }
      const idempotencyKey = `source-post-processing:${run.source_channel_id}:${sourceItemIds[0]}`;
      const prior = await this.operationByIdempotency(spaceId, run.project_id, idempotencyKey);
      if (prior && prior.status !== "failed" && prior.status !== "cancelled") return;
      const operation = await this.activeIncremental(spaceId, run.project_id, candidate.id);
      if (operation) {
        await updateProjection(this.db, spaceId, operation.id, ({ state: current }) => {
          current.source_item_ids = unique([...current.source_item_ids, ...sourceItemIds]);
          current.awaiting_source_scan = false;
          current.watermark = {
            before: current.watermark.after,
            after: watermarkAfter,
            overlap_hours: OVERLAP_HOURS,
          };
        }, deriveStepStates);
        await this.reconcileOperation(spaceId, operation.id);
        return;
      }
      const actorUserId = run.triggered_by_user_id ?? await this.projectWriterActor(spaceId, run.project_id);
      if (!actorUserId) return;
      const identity: SpaceUserIdentity = { spaceId, userId: actorUserId };
      const operationState = incrementalStateFromWorkflow(
        candidate.state_json,
        candidate.id,
        unique(sourceItemIds),
        idempotencyKey,
        {
          before: optionalString(objectValue(objectValue(candidate.state_json).monitoring).watermark_after),
          after: watermarkAfter,
          overlap_hours: OVERLAP_HOURS,
        },
      );
      const created = await this.createOperation(identity, run.project_id, {
        title: "Process new research items",
        intentText: "Prepare a human-reviewed incremental research update.",
        steps: operationSteps(),
        state: operationState,
      });
      await this.reconcileOperation(spaceId, created.id);
    } finally {
      await this.db.query(
        `UPDATE source_post_processing_runs SET research_reconciled_at=$3 WHERE id=$1 AND space_id=$2`,
        [runId, spaceId, new Date().toISOString()],
      );
    }
  }

  private async syncPostProcessingCorpus(spaceId: string, projectId: string, sourceItemIds: string[]): Promise<void> {
    for (const sourceItemId of sourceItemIds) {
      await syncProjectCorpusDecisionForSourceItem(this.db, { spaceId, sourceItemId, projectId });
    }
  }

  async onPostProcessingRecoveryFinished(input: { spaceId: string; operationId: string }): Promise<void> {
    await this.enqueueReconcile(input.spaceId, null, input.operationId, "post_processing_recovery_finished");
  }

  private async startInitialIntakeLocked(identity: SpaceUserIdentity, projectId: string, input: ResearchInput) {
    await this.db.query(
      `UPDATE projects SET current_focus=$3, updated_at=$4 WHERE space_id=$1 AND id=$2 AND status='active'`,
      [identity.spaceId, projectId, input.researchQuestion, new Date().toISOString()],
    );
    const existing = await this.db.query<{ id: string; progress_json: unknown }>(
      `SELECT id, progress_json FROM project_operations WHERE space_id=$1 AND project_id=$2 AND kind='research' AND progress_json->'idempotency'->>'key'=$3 ORDER BY created_at LIMIT 1`,
      [identity.spaceId, projectId, input.idempotencyKey],
    );
    if (existing.rows[0]) {
      const prior = researchState(existing.rows[0].progress_json);
      const retryableSourceSetup = prior.run_kind === "baseline"
        && prior.failed_stage === "monitor_setup"
        && (await this.operation(identity.spaceId, existing.rows[0].id))?.status === "failed";
      if (!retryableSourceSetup) {
        if (prior.idempotency.fingerprint !== initialIntakeFingerprint(input)) {
          throw new HttpError(409, "idempotency_key is already used with different research parameters");
        }
        return this.startResponse(identity, projectId, existing.rows[0].id);
      }
      input = { ...input, idempotencyKey: `${input.idempotencyKey}:retry:${randomUUID()}` };
    }
    const fingerprint = initialIntakeFingerprint(input);

    const workflow = await this.createOrReuseWorkflow(identity.spaceId, projectId, identity.userId, input);
    if (!workflow) throw new HttpError(500, "Failed to create research workflow");
    await this.db.query(
      `SELECT id FROM project_research_workflows WHERE space_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`,
      [identity.spaceId, projectId, workflow.id],
    );
    const active = await this.activeResearchOperation(identity.spaceId, projectId, workflow.id);
    if (active) throw new HttpError(409, "Another Project Research operation is already active for this workflow");
    if (objectValue(objectValue(workflow.state_json).monitoring).active === true) {
      throw new HttpError(409, "This Project Research workflow already has an active initial literature intake");
    }
    await this.db.query(
      `UPDATE project_research_workflows SET status='active', updated_at=$4 WHERE space_id=$1 AND project_id=$2 AND id=$3`,
      [identity.spaceId, projectId, workflow.id, new Date().toISOString()],
    );
    const operation = await this.createOperation(identity, projectId, {
      title: "Start initial literature intake",
      intentText: `Initialize research workflow for: ${input.researchQuestion}`,
      steps: operationSteps(),
      state: initialState(input, workflow.id, fingerprint),
    });
    try {
    if (input.searchStrategyId) {
      const linked = await this.db.query(
        `UPDATE research_search_strategies SET operation_id=$4,project_id=$3
          WHERE id=$1 AND space_id=$2 AND created_by_user_id=$5 AND operation_id IS NULL RETURNING id`,
        [input.searchStrategyId, identity.spaceId, projectId, operation.id, identity.userId],
      );
      if (!linked.rows[0]) throw new HttpError(422, "search_strategy_id is unavailable or already attached");
    }
      const channels = await this.resolveResearchChannels(identity, input);
      if (channels.length === 0) throw new HttpError(422, "At least one literature monitor is required");
      const bindings: Record<string, unknown>[] = [];
      const rules: Record<string, unknown>[] = [];
      for (let index = 0; index < channels.length; index += 1) {
        const channel = channels[index]!;
        const binding = await this.ensureBinding(identity, projectId, String(channel.id));
        const rule = await this.ensurePostProcessingRule(
          identity,
          projectId,
          String(channel.id),
          input,
          String(channel.name ?? `Monitor ${index + 1}`),
          String(channel.provider_key ?? "generic"),
        );
        bindings.push(binding);
        rules.push(rule);
      }
      const binding = bindings[0]!;
      const rule = rules[0]!;
      const planner = new SourceBackfillPlanningService(this.db, this.config);
      const plans: Record<string, unknown>[] = [];
      for (let index = 0; index < channels.length; index += 1) {
        const channel = channels[index]!;
        const channelBinding = bindings[index]!;
        const plan = await planner.create(identity, String(channel.id), {
          strategy: { window_unit: "date_window", history_mode: input.historyMode, from: input.from, to: input.to, window_size: 30, max_items: input.maxItems, direction: "backward", monitoring_field: input.monitoringField },
          quota_policy: { window: "minute", limit_count: 10 },
          idempotency_key: `${input.idempotencyKey}:backfill:${String(channel.id)}`,
          project_source_binding_id: String(channelBinding.id),
          project_operation_id: operation.id,
        });
        await new SourceBackfillExecutionService(this.db).startUserAuthorized(
          identity.spaceId,
          String(plan.id),
          operation.id,
          identity.userId,
        );
        plans.push(plan);
      }
      const state = researchState(operation.progress_json);
      state.channel_ids = channels.map((channel) => String(channel.id));
      state.project_source_binding_ids = bindings.map((row) => String(row.id));
      state.source_post_processing_rule_ids = rules.map((row) => String(row.id));
      state.project_source_binding_id = String(binding.id);
      state.source_post_processing_rule_id = String(rule.id);
      state.source_backfill_plan_ids = plans.map((plan) => String(plan.id));
      state.source_backfill_plan_id = state.source_backfill_plan_ids[0] ?? null;
      state.coverage_ranges = [{ from: input.from!, to: input.to!, operation_id: operation.id, status: "pending" }];
      state.current_stage = "backfill";
      state.stage_state = "running";
      await this.setState(operation, state, [
        { seq: 0, status: "done", detail: { channel_ids: state.channel_ids, binding_ids: state.project_source_binding_ids, rule_ids: state.source_post_processing_rule_ids } },
        { seq: 1, status: "active", detail: { plan_ids: state.source_backfill_plan_ids, authorization: "explicit_user_start" } },
        { seq: 2, status: "pending" },
        { seq: 3, status: "pending" },
        { seq: 4, status: "pending" },
      ]);
      await this.db.query(
        `UPDATE project_research_workflows
            SET state_json = COALESCE(state_json, '{}'::jsonb) || $4::jsonb,
                updated_at=$5
          WHERE space_id=$1 AND project_id=$2 AND id=$3`,
        [identity.spaceId, projectId, workflow.id, JSON.stringify({
          channel_ids: state.channel_ids,
          project_source_binding_id: state.project_source_binding_id,
          source_post_processing_rule_id: state.source_post_processing_rule_id,
          source_backfill_plan_id: state.source_backfill_plan_id,
          source_backfill_plan_ids: state.source_backfill_plan_ids,
          agent_id: state.agent_id,
          runtime_profile_id: state.runtime_profile_id,
          report_depth: state.report_depth,
          question_refine_skipped: state.question_refine_skipped,
          initial_intake: { ...objectValue(objectValue(workflow.state_json).initial_intake), history_mode: input.historyMode, from: input.from, to: input.to },
          coverage_ranges: [{ from: input.from, to: input.to, operation_id: operation.id, status: "pending" }],
        }), new Date().toISOString()],
      );
      await new ProjectOperationService(this.db).link(identity.spaceId, projectId, operation.id, "research_workflow", workflow.id, "workflow_definition");
      await new ProjectOperationService(this.db).link(identity.spaceId, projectId, operation.id, "project_source_binding", String(binding.id), "source_binding");
      for (let index = 0; index < plans.length; index += 1) {
        await new ProjectOperationService(this.db).link(identity.spaceId, projectId, operation.id, "source_backfill_plan", String(plans[index]!.id), "history_backfill");
      }
      return this.startResponse(identity, projectId, operation.id);
    } catch (error) {
      await this.failOperation(operation, error instanceof Error ? error.message : "Initial literature intake setup failed");
      throw error;
    }
  }

  private async resolveResearchChannels(identity: SpaceUserIdentity, input: ResearchInput): Promise<Record<string, unknown>[]> {
    const channels = await this.db.query<Record<string, unknown>>(
      `SELECT sc.*, sp.provider_key
         FROM source_channels sc
         JOIN source_connections scon ON scon.id=sc.source_connection_id AND scon.space_id=sc.space_id
         JOIN source_provider_connectors spc ON spc.id=scon.provider_connector_id
         JOIN source_providers sp ON sp.id=spc.provider_id
        WHERE sc.space_id=$1 AND sc.id=ANY($2::text[]) AND sc.status <> 'archived'
        ORDER BY array_position($2::text[], sc.id)`,
      [identity.spaceId, input.sourceChannelIds],
    );
    if (channels.rows.length !== input.sourceChannelIds.length) {
      throw new HttpError(422, "One or more selected literature monitors are unavailable");
    }
    return channels.rows;
  }

  private async ensureBinding(identity: SpaceUserIdentity, projectId: string, channelId: string): Promise<Record<string, unknown>> {
    const existing = await this.db.query<Record<string, unknown>>(
      `SELECT * FROM project_source_bindings WHERE space_id=$1 AND project_id=$2 AND source_channel_id=$3 AND status <> 'archived' ORDER BY updated_at DESC LIMIT 1`,
      [identity.spaceId, projectId, channelId],
    );
    if (existing.rows[0]) return existing.rows[0];
    return new ProjectSourceBindingService(this.db).createBinding(identity, {
      project_id: projectId,
      source_channel_id: channelId,
      binding_key: "auto-research",
      delivery_scope: "project_members",
      extraction_policy: { mode: "metadata_and_text", full_text: true },
      routing_policy: { archive_non_matching: false },
    });
  }

  private async ensurePostProcessingRule(
    identity: SpaceUserIdentity,
    projectId: string,
    channelId: string,
    input: ResearchInput,
    monitorName: string,
    providerKey: string,
  ): Promise<Record<string, unknown>> {
    const existing = await this.db.query<Record<string, unknown>>(
      `SELECT * FROM source_post_processing_rules WHERE space_id=$1 AND project_id=$2 AND source_channel_id=$3 AND status <> 'archived' AND name=$4 LIMIT 1`,
      [identity.spaceId, projectId, channelId, `Auto Research: ${monitorName}`],
    );
    if (existing.rows[0]) {
      await this.ensureResearchProcessingBatchSize(identity, [String(existing.rows[0].id)]);
      const refreshed = await this.db.query<Record<string, unknown>>(
        `SELECT * FROM source_post_processing_rules WHERE space_id=$1 AND id=$2`,
        [identity.spaceId, String(existing.rows[0].id)],
      );
      return refreshed.rows[0] ?? existing.rows[0];
    }
    return this.asRecord(await new SourcePostProcessingService(this.db, this.config!).createRule(identity, channelId, {
      project_id: projectId,
      agent_id: input.agentId,
      name: `Auto Research: ${monitorName}`,
      trigger_type: "items_materialized",
      trigger_config_json: { min_new_items: 1, cooldown_seconds: 0, timezone: "UTC", skip_when_no_new_items: true },
      input_config_json: {
        window: "new_since_last_success",
        item_limit: SOURCE_POST_PROCESSING_LIMITS.researchStructuredOutputBatchSize,
        max_batches_per_event: 10,
        processing_strategy: "screen_extract_digest",
        content_source: "prefer_extracted_text_for_candidates",
        include_excerpts: true,
        include_evidence: true,
        timezone: "UTC",
        runtime_profile_id: input.runtimeProfileId,
        structured_output_schema_id: "source_post_processing.result.v1",
        research_question_version: 1,
        content_profile: contentProfileForProvider(providerKey),
        summary_goal: input.researchQuestion,
        retrieval_context: { enabled: true, domains: ["project"], query: input.researchQuestion, max_results_per_domain: 10, mode: "hybrid" },
        candidate_prefilter: { enabled: true, mode: "hybrid", max_candidates: 100 },
        deep_analysis: { enabled: true, trigger_relevance: ["relevant", "maybe"], min_confidence: 0.5, max_candidates_per_run: SOURCE_POST_PROCESSING_LIMITS.deepAnalysisMaxCandidatesPerRun, content_source: "prefer_extracted_text", output: "per_item_deep_summary" },
        relevance_profile: { enabled: true, objective: input.researchQuestion, include_criteria: [input.researchQuestion], exclude_criteria: [], must_have: [], nice_to_have: [] },
      },
      actions_json: { batch_digest: true, per_item_summary: true, extract_evidence: true, create_proposals: false, mark_items: true },
    }));
  }

  private async ensureResearchProcessingBatchSize(
    identity: SpaceUserIdentity,
    ruleIds: string[],
  ): Promise<void> {
    const rules = await this.db.query<{
      id: string;
      source_channel_id: string;
      input_config_json: unknown;
    }>(
      `SELECT id, source_channel_id, input_config_json
         FROM source_post_processing_rules
        WHERE space_id=$1 AND id=ANY($2::text[]) AND project_id IS NOT NULL AND status <> 'archived'`,
      [identity.spaceId, ruleIds],
    );
    const service = new SourcePostProcessingService(this.db, this.config!);
    for (const rule of rules.rows) {
      const inputConfig = objectValue(rule.input_config_json);
      if (inputConfig.item_limit === SOURCE_POST_PROCESSING_LIMITS.researchStructuredOutputBatchSize) {
        continue;
      }
      await service.updateRule(identity, rule.source_channel_id, rule.id, {
        input_config_json: {
          ...inputConfig,
          item_limit: SOURCE_POST_PROCESSING_LIMITS.researchStructuredOutputBatchSize,
        },
      });
    }
  }

  private async retryMonitorSetup(
    identity: SpaceUserIdentity,
    projectId: string,
    state: ResearchOperationState,
  ) {
    const workflow = await this.workflow(identity.spaceId, projectId, state.workflow_id);
    if (!workflow) throw new HttpError(404, "Research workflow not found");
    const workflowState = objectValue(workflow.state_json);
    const historyMode = state.history.mode ?? "bounded_range";
    if (historyMode === "bounded_range" && (!state.history.from || !state.history.to)) {
      throw new HttpError(409, "The failed initial literature intake is missing its historical range and cannot be retried");
    }
    const input: ResearchInput = {
      researchQuestion: optionalString(workflowState.research_question) ?? "Project research",
      sourceChannelIds: state.channel_ids,
      historyMode,
      from: state.history.from,
      to: state.history.to,
      maxItems: state.history.max_items ?? MAX_ITEMS_DEFAULT,
      monitoringField: state.query.sort_by === "lastUpdatedDate" ? "lastUpdatedDate" : "submittedDate",
      schedule: "daily",
      agentId: state.agent_id,
      runtimeProfileId: state.runtime_profile_id,
      execution: {},
      idempotencyKey: `${state.idempotency.key}:retry:${randomUUID()}`,
      reportDepth: state.report_depth,
      questionRefineSkipped: state.question_refine_skipped,
      searchStrategyId: null,
    };
    return this.startInitialIntakeLocked(identity, projectId, input);
  }

  private async createOperation(identity: SpaceUserIdentity, projectId: string, input: { title: string; intentText: string; steps: string[]; state: ResearchOperationState }) {
    const created = await new ProjectOperationService(this.db).create(identity, projectId, {
      kind: "research",
      title: input.title,
      intent_text: input.intentText,
      progress: input.state,
      steps: input.steps.map((title) => ({ title })),
    });
    const operation = await this.operation(identity.spaceId, String(created.id));
    if (!operation) throw new HttpError(500, "Failed to create project research operation");
    await this.setState(operation, input.state, deriveStepStates(input.state));
    return operation;
  }

  private async createOrReuseWorkflow(spaceId: string, projectId: string, userId: string, input: ResearchInput) {
    const existing = await this.workflow(spaceId, projectId, null, false, true);
    if (existing && ["active", "paused", "not_started"].includes(existing.status)) return existing;
    const id = randomUUID();
    const now = new Date().toISOString();
    const state = {
      research_question: input.researchQuestion,
      research_question_version: 1,
      source_channel_ids: input.sourceChannelIds,
      agent_id: input.agentId,
      runtime_profile_id: input.runtimeProfileId,
      report_depth: input.reportDepth,
      question_refine_skipped: input.questionRefineSkipped,
      search_strategy_id: input.searchStrategyId,
      initial_intake: { history_mode: input.historyMode, from: input.from, to: input.to, max_items: input.maxItems },
      coverage_ranges: [],
      monitoring: { field: input.monitoringField, schedule: input.schedule, overlap_hours: OVERLAP_HOURS, active: false },
    };
    await this.db.query(
      `INSERT INTO project_research_workflows (id,space_id,project_id,workflow_type,status,mode,state_json,started_by_user_id,created_at,updated_at)
       VALUES ($1,$2,$3,'literature_review','active','autonomous',$4::jsonb,$5,$6,$6)`,
      [id, spaceId, projectId, JSON.stringify(state), userId, now],
    );
    const workflow = await this.workflow(spaceId, projectId, id);
    if (!workflow) throw new HttpError(500, "Failed to create research workflow");
    return workflow;
  }

  /**
   * Queue (or re-attach to) the synthesis agent run for an operation.
   *
   * The stage transition, the run row, its agent_run job, and the state that
   * binds them all commit in one transaction, and every decision is made
   * against the freshly locked operation state: a transition that does not
   * apply creates nothing, and an applied transition can never leave an
   * unbound run behind. `from` scopes the stages the caller may queue from;
   * `reuseExistingRun` re-enters a still-bound run instead of queueing a
   * duplicate.
   */
  private async queueMonitorComparison(input: {
    spaceId: string;
    userId: string;
    projectId: string;
    operationId: string;
    workflowId: string;
  }): Promise<ResearchTransitionResult> {
    let queued: { runId: string; jobId: string; sourceItemIds: string[] } | null = null;
    const result = await transitionResearchOperation(this.db, input.spaceId, input.operationId, {
      from: ["screening", "comparison", "failed"],
      to: "comparison",
      mutate: async ({ db, state }) => {
        state.stage_state = "running";
        if (state.current_stage === "failed") {
          state.comparison_run_id = null;
          state.comparison_source_item_ids = [];
        }
        delete state.failed_stage;
        if (state.comparison_run_id) return;
        queued = await new ProjectResearchMonitorComparisonService(db).queue({
          spaceId: input.spaceId,
          userId: input.userId,
          projectId: input.projectId,
          workflowId: input.workflowId,
          operationId: input.operationId,
          agentId: state.agent_id,
          runtimeProfileId: state.runtime_profile_id || null,
          researchQuestion: researchQueryText(state),
          sourceItemIds: state.source_item_ids,
        });
        state.comparison_run_id = queued?.runId ?? null;
        state.comparison_source_item_ids = queued?.sourceItemIds ?? [];
        state.heartbeat_at = new Date().toISOString();
      },
      stepOverrides: (state) => [
        { seq: 0, status: "done" }, { seq: 1, status: "done" }, { seq: 2, status: "done" },
        { seq: 3, status: "active", detail: { run_id: state.comparison_run_id } },
        { seq: 4, status: "skipped" },
      ],
      onIllegal: "noop",
    });
    if (result.applied && !result.state?.comparison_run_id) {
      await transitionResearchOperation(this.db, input.spaceId, input.operationId, {
        from: ["comparison"], to: "complete",
        mutate: ({ state }) => { state.stage_state = "skipped"; state.monitoring_active = true; },
        stepOverrides: [
          { seq: 0, status: "done" }, { seq: 1, status: "done" }, { seq: 2, status: "done" },
          { seq: 3, status: "skipped", detail: { reason: "No eligible papers to compare" } }, { seq: 4, status: "skipped" },
        ],
      });
      const completed = await this.operation(input.spaceId, input.operationId);
      if (completed) await this.setWorkflowMonitoring(input.spaceId, input.projectId, input.workflowId, researchState(completed.progress_json));
    }
    return result;
  }

  private async reconcileComparisonStage(spaceId: string, row: OperationRow, state: ResearchOperationState): Promise<void> {
    const runId = state.comparison_run_id;
    if (!runId) {
      const actor = await this.projectWriterActor(spaceId, row.project_id);
      if (!actor) {
        await this.failOperation(row, "Monitoring comparison requires a project writer");
        return;
      }
      await this.queueMonitorComparison({ spaceId, userId: actor, projectId: row.project_id, operationId: row.id, workflowId: state.workflow_id });
      return;
    }
    const run = await this.db.query<{ status: string; updated_at: unknown }>(
      `SELECT status,updated_at FROM runs WHERE id=$1 AND space_id=$2`,
      [runId, spaceId],
    );
    if (!run.rows[0]) {
      await this.failOperation(row, "The monitoring comparison run no longer exists");
      return;
    }
    if (["succeeded", "degraded", "failed", "cancelled"].includes(run.rows[0].status)) {
      await this.reconcileCompletedRun(spaceId, runId);
      return;
    }
    state.heartbeat_at = new Date().toISOString();
    await this.setState(row, state, deriveStepStates(state));
  }

  private async queueSynthesis(input: {
    spaceId: string;
    userId: string;
    projectId: string;
    operationId: string;
    workflowId: string;
    from: readonly ResearchStage[];
    reuseExistingRun: boolean;
    stageKey?: "synthesis" | "synthesis_revision";
    critiqueContext?: string;
  }): Promise<ResearchTransitionResult> {
    const { spaceId, userId, projectId, operationId, workflowId } = input;
    return await transitionResearchOperation(this.db, spaceId, operationId, {
      from: input.from,
      to: "synthesis",
      mutate: async ({ db, state: current }) => {
        current.stage_state = "running";
        delete current.failed_stage;
        if (input.reuseExistingRun && current.synthesis_run_id) return;
        const resolvedPrompt = await resolveProjectResearchSynthesisPrompt(db, {
          spaceId,
          userId,
          projectId,
          agentId: current.agent_id,
          researchQuestion: researchQueryText(current),
          reportDepth: current.report_depth,
          critiqueContext: input.critiqueContext,
        });
        if (!resolvedPrompt) throw new HttpError(500, "Project Research synthesis prompt is not resolvable");
        const matrixArtifactId = await new ProjectResearchArtifactService(db).ensureLiteratureMatrix({
          spaceId,
          projectId,
          workflowId,
          operationId,
          ownerUserId: userId,
        });
        current.matrix_artifact_id = matrixArtifactId;
        current.artifact_ids = unique([...current.artifact_ids, matrixArtifactId]);
        const run = await new PgRunRepository(db).createQueuedRunWithBudgetAdmission({
          agent_id: current.agent_id,
          space_id: spaceId,
          user_id: userId,
          mode: "live",
          run_type: "agent",
          // The research workflow is the business context; run trigger_origin is
          // the execution class accepted by the shared run contract.
          trigger_origin: "system",
          project_id: projectId,
          // researchState defaults a missing profile to ""; the run contract
          // expects null for "no explicitly requested runtime profile".
          runtime_profile_id: current.runtime_profile_id || null,
          prompt: `${input.stageKey === "synthesis_revision" ? "Revise" : "Synthesize"} the approved project research corpus for: ${researchQueryText(current)}`,
          instruction: resolvedPrompt.instruction,
          capability_id: "research.brief_synthesize",
          capabilities_json: RESEARCH_CAPABILITIES,
          contract_snapshot: {
            source: { kind: "workflow", id: workflowId },
            project_id: projectId,
            required_outputs_json: { artifact_types: ["research_report.archive.v1"] },
            structured_output_json: RESEARCH_SYNTHESIS_OUTPUT_CONTRACT,
            workflow_input_json: {
              project_research: {
                workflow_id: workflowId,
                operation_id: operationId,
                run_kind: current.run_kind,
                stage_key: input.stageKey ?? "synthesis",
                report_depth: current.report_depth,
                prompt_asset_key: PROJECT_RESEARCH_SYNTHESIS_PROMPT_KEY,
                prompt_version_id: resolvedPrompt.resolveResult.version_id,
                prompt_content_hash: resolvedPrompt.resolveResult.content_hash,
              },
            },
            policy_context_json: createManagedExecutionPolicy("project_research", true),
            risk_level: "low",
          },
        });
        const job = await new PgJobQueueRepository(db).enqueue({ job_type: "agent_run", space_id: spaceId, user_id: userId, agent_id: current.agent_id, payload: { run_id: run.id } });
        const now = new Date().toISOString();
        current.synthesis_run_id = run.id;
        current.synthesis_progress = {
          run_id: run.id,
          run_status: run.status,
          job_id: job.id,
          job_status: job.status,
          job_attempts: job.attempts,
          job_heartbeat_at: dateIso(job.heartbeat_at),
          job_updated_at: dateIso(job.updated_at),
          run_updated_at: dateIso(run.updated_at),
          last_event_at: null,
          last_event_type: null,
          queued_at: run.created_at ?? now,
          started_at: run.started_at ?? null,
          updated_at: now,
          message: run.status === "running"
            ? "The synthesis agent is writing the structured research report from the approved corpus."
            : "The synthesis run is queued and waiting for an agent worker to pick it up.",
        };
        if (input.stageKey === "synthesis_revision" && current.synthesis_critique) {
          current.synthesis_critique.status = "queued";
          current.synthesis_critique.run_id = run.id;
        }
      },
      stepOverrides: (current) => [
        { seq: 0, status: "done" },
        { seq: 1, status: "done" },
        { seq: 2, status: "done" },
        { seq: 3, status: "active", detail: { run_id: current.synthesis_run_id } },
        { seq: 4, status: "pending" },
      ],
      onIllegal: "noop",
    });
  }

  private async queueCritique(input: {
    spaceId: string;
    userId: string;
    projectId: string;
    operationId: string;
    workflowId: string;
  }): Promise<ResearchTransitionResult> {
    return transitionResearchOperation(this.db, input.spaceId, input.operationId, {
      from: ["synthesis"],
      to: "synthesis",
      mutate: async ({ db, state }) => {
        const critique = state.synthesis_critique;
        if (!critique || critique.status !== "needs_queue") return false;
        const artifact = await db.query<{ content: string | null }>(
          `SELECT content FROM artifacts WHERE id=$1 AND space_id=$2 AND project_id=$3`,
          [critique.archive_artifact_id, input.spaceId, input.projectId],
        );
        if (!artifact.rows[0]?.content) throw new HttpError(500, "Synthesis critique report candidate is unavailable");
        const report = objectValue(JSON.parse(artifact.rows[0].content));
        const resolved = await resolveProjectResearchCritiquePrompt(db, {
          spaceId: input.spaceId,
          userId: input.userId,
          projectId: input.projectId,
          agentId: state.agent_id,
          researchQuestion: researchQueryText(state),
          reportDepth: state.report_depth,
          report,
          corpusSummary: critiqueCorpusSummary(report),
        });
        if (!resolved) throw new HttpError(500, "Project Research synthesis critique prompt is not resolvable");
        const run = await new PgRunRepository(db).createQueuedRunWithBudgetAdmission({
          agent_id: state.agent_id,
          space_id: input.spaceId,
          user_id: input.userId,
          mode: "live",
          run_type: "agent",
          trigger_origin: "system",
          project_id: input.projectId,
          runtime_profile_id: state.runtime_profile_id || null,
          prompt: `Critique the Project Research report for: ${researchQueryText(state)}`,
          instruction: resolved.instruction,
          capability_id: "research.brief_synthesize",
          capabilities_json: RESEARCH_CAPABILITIES,
          contract_snapshot: {
            source: { kind: "workflow", id: input.workflowId },
            project_id: input.projectId,
            required_outputs_json: { artifact_types: [] },
            structured_output_json: RESEARCH_SYNTHESIS_CRITIQUE_OUTPUT_CONTRACT,
            workflow_input_json: {
              project_research: {
                workflow_id: input.workflowId,
                operation_id: input.operationId,
                run_kind: state.run_kind,
                stage_key: "synthesis_critique",
                critique_round: critique.round,
                report_run_id: critique.report_run_id,
                prompt_asset_key: PROJECT_RESEARCH_SYNTHESIS_CRITIQUE_PROMPT_KEY,
                prompt_version_id: resolved.resolveResult.version_id,
                prompt_content_hash: resolved.resolveResult.content_hash,
              },
            },
            policy_context_json: createManagedExecutionPolicy("project_research", true),
            risk_level: "low",
          },
        });
        const job = await new PgJobQueueRepository(db).enqueue({
          job_type: "agent_run",
          space_id: input.spaceId,
          user_id: input.userId,
          agent_id: state.agent_id,
          payload: { run_id: run.id },
        });
        critique.status = "queued";
        critique.run_id = run.id;
        state.synthesis_run_id = run.id;
        const now = new Date().toISOString();
        state.synthesis_progress = {
          run_id: run.id,
          run_status: run.status,
          job_id: job.id,
          job_status: job.status,
          job_attempts: job.attempts,
          queued_at: run.created_at ?? now,
          started_at: run.started_at ?? null,
          updated_at: now,
          message: "The synthesis draft is undergoing an adversarial evidence critique.",
        };
      },
      stepOverrides: (state) => [
        { seq: 0, status: "done" }, { seq: 1, status: "done" }, { seq: 2, status: "done" },
        { seq: 3, status: "active", detail: { run_id: state.synthesis_run_id, phase: "critique" } },
        { seq: 4, status: "pending" },
      ],
      onIllegal: "noop",
    });
  }

  private async queueSynthesisRevision(input: {
    spaceId: string;
    userId: string;
    projectId: string;
    operationId: string;
    workflowId: string;
  }): Promise<ResearchTransitionResult> {
    const operation = await this.operation(input.spaceId, input.operationId);
    const state = operation ? researchState(operation.progress_json) : null;
    if (!state?.synthesis_critique || state.synthesis_critique.status !== "revision_needed") {
      return { applied: false, reason: "aborted" };
    }
    const context = state.synthesis_critique.issues
      .map((issue) => `${issue.severity}/${issue.kind}: ${issue.detail}${issue.affected_refs.length ? ` (${issue.affected_refs.join(", ")})` : ""}`)
      .join("\n");
    return this.queueSynthesis({
      ...input,
      from: ["synthesis"],
      reuseExistingRun: false,
      stageKey: "synthesis_revision",
      critiqueContext: context,
    });
  }

  private async createScreeningGate(operation: OperationRow, state: ResearchOperationState): Promise<void> {
    const counts = await this.countRelevantItems(operation.space_id, operation.project_id, state.source_item_ids);
    const checkpointId = await this.createCheckpoint(operation.space_id, operation.project_id, state.workflow_id, operation.id, "screening_gate", {
      operation_id: operation.id,
      run_kind: state.run_kind,
      total: state.source_item_ids.length,
      relevant: counts.relevant,
      maybe: counts.maybe,
      excluded: counts.excluded,
      missing_full_text: counts.missing_full_text,
      evidence_count: counts.evidence_count,
      failed_items: counts.failed_items,
      partial: state.partial,
    });
    if (!state.checkpoint_ids.includes(checkpointId)) state.checkpoint_ids.push(checkpointId);
    state.current_stage = "screening";
    state.stage_state = "waiting_review";
    state.heartbeat_at = new Date().toISOString();
    await this.setState(operation, state, [
      { seq: 0, status: "done" },
      { seq: 1, status: "done" },
      { seq: 2, status: "blocked", detail: { checkpoint_id: checkpointId, counts } },
      { seq: 3, status: "pending" },
      { seq: 4, status: "pending" },
    ]);
  }

  /**
   * A successful source search with no returned items is a valid terminal
   * outcome, not a human screening decision. Keep the operation auditable,
   * stop the downstream stages, and return the workflow to setup so the user
   * can adjust the saved query/date range and start a new intake.
   */
  private async completeEmptyInitialIntake(operation: OperationRow, state: ResearchOperationState): Promise<void> {
    const now = new Date().toISOString();
    state.empty_result = {
      kind: "no_source_items",
      source_item_count: 0,
      detected_at: now,
      message: "Search completed, but no papers matched the selected source and history window.",
    };
    state.current_stage = "complete";
    state.stage_state = "skipped";
    state.monitoring_active = false;
    state.screening_progress = {
      ...(state.screening_progress ?? await this.screeningProgressFor(
        operation.space_id,
        operation.project_id,
        operation.id,
        state,
        operation.created_at,
      )),
      phase: "completed",
      total_items: 0,
      classified_items: 0,
      unclassified_items: 0,
      message: state.empty_result.message,
      updated_at: now,
    };
    await this.skipPendingScreeningCheckpoint(
      operation.space_id,
      operation.project_id,
      state.workflow_id,
      operation.id,
      "No source items were returned; screening was skipped automatically.",
    );
    await this.setState(operation, state, deriveSkippedAfterScreeningSteps());
    await this.completeWorkflowCoverage(operation.space_id, operation.project_id, state.workflow_id, operation.id, "completed");
    await this.db.query(
      `UPDATE project_research_workflows
          SET status='paused', current_stage='initial_intake_setup',
              state_json=jsonb_set(
                COALESCE(state_json,'{}'::jsonb) || jsonb_build_object(
                  'draft', COALESCE(state_json->'draft','{}'::jsonb) || jsonb_build_object('status','saved')
                ),
                '{last_empty_result}',$4::jsonb,true
              ),
              updated_at=$5
        WHERE space_id=$1 AND project_id=$2 AND id=$3`,
      [
        operation.space_id,
        operation.project_id,
        state.workflow_id,
        JSON.stringify(state.empty_result),
        now,
      ],
    );
  }

  private async createCheckpoint(spaceId: string, projectId: string, workflowId: string, operationId: string, type: string, result: Record<string, unknown>): Promise<string> {
    const existing = await this.db.query<{ id: string }>(
      `SELECT id FROM project_research_checkpoints WHERE space_id=$1 AND project_id=$2 AND workflow_id=$3 AND checkpoint_type=$4 AND machine_result_json->>'operation_id'=$5 AND status='pending' ORDER BY created_at DESC LIMIT 1`,
      [spaceId, projectId, workflowId, type, operationId],
    );
    if (existing.rows[0]) {
      await this.db.query(
        `UPDATE project_research_checkpoints SET machine_result_json=$2::jsonb, updated_at=$3 WHERE id=$1 AND space_id=$4`,
        [existing.rows[0].id, JSON.stringify(result), new Date().toISOString(), spaceId],
      );
      return existing.rows[0].id;
    }
    const id = randomUUID();
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO project_research_checkpoints (id,space_id,project_id,workflow_id,stage_key,checkpoint_type,status,machine_result_json,created_at,updated_at)
       VALUES ($1,$2,$3,$4,$5,$6,'pending',$7::jsonb,$8,$8)`,
      [id, spaceId, projectId, workflowId, type === "idea_review" ? "idea_review" : "screening", type, JSON.stringify(result), now],
    );
    return id;
  }

  private async countRelevantItems(spaceId: string, projectId: string, sourceItemIds: string[]) {
    if (sourceItemIds.length === 0) {
      return {
        total: 0,
        relevant: 0,
        maybe: 0,
        excluded: 0,
        missing_full_text: 0,
        evidence_count: 0,
        failed_items: 0,
      };
    }
    // A paper may have separate source-item, object, and evidence corpus rows.
    // Aggregate those rows by source item before counting so one paper cannot
    // inflate missing-full-text, evidence, or screening totals.
    const result = await this.db.query<{ total: string; relevant: string; maybe: string; excluded: string; missing_full_text: string; evidence_count: string; failed_items: string }>(
      `WITH requested_items AS (
         SELECT DISTINCT unnest($3::text[]) AS source_item_id
       ), per_source_item AS (
         SELECT requested_items.source_item_id,
                COALESCE(bool_or(pci.triage_status IN ('relevant','included') OR pci.relevance='relevant'), false) AS is_relevant,
                COALESCE(bool_or(pci.triage_status='maybe' OR pci.relevance='maybe'), false) AS is_maybe,
                COALESCE(bool_or(pci.triage_status='excluded' OR pci.relevance='not_relevant'), false) AS is_excluded,
                COALESCE(bool_or(pci.object_id IS NOT NULL), false) AS has_full_text,
                count(DISTINCT pci.evidence_id)::int AS evidence_records,
                COALESCE(bool_or(pci.metadata_json->>'processing_status'='failed'), false) AS has_failed_item
           FROM requested_items
           LEFT JOIN project_corpus_items pci
             ON pci.space_id=$1
            AND pci.project_id=$2
            AND pci.source_item_id=requested_items.source_item_id
            AND pci.status='active'
          GROUP BY requested_items.source_item_id
       )
       SELECT count(*)::int AS total,
              count(*) FILTER (WHERE is_relevant)::int AS relevant,
              count(*) FILTER (WHERE NOT is_relevant AND is_maybe)::int AS maybe,
              count(*) FILTER (WHERE NOT is_relevant AND NOT is_maybe AND is_excluded)::int AS excluded,
              count(*) FILTER (WHERE NOT has_full_text)::int AS missing_full_text,
              COALESCE(sum(evidence_records), 0)::int AS evidence_count,
              count(*) FILTER (WHERE has_failed_item)::int AS failed_items
         FROM per_source_item`,
      [spaceId, projectId, sourceItemIds],
    );
    const row = result.rows[0];
    return {
      total: Number(row?.total ?? 0), relevant: Number(row?.relevant ?? 0), maybe: Number(row?.maybe ?? 0), excluded: Number(row?.excluded ?? 0),
      missing_full_text: Number(row?.missing_full_text ?? 0), evidence_count: Number(row?.evidence_count ?? 0), failed_items: Number(row?.failed_items ?? 0),
    };
  }

  private async recordScanSummary(
    operation: Pick<OperationRow, "id" | "space_id" | "project_id">,
    state: ResearchOperationState,
    counts: { relevant: number; maybe: number; excluded: number },
  ): Promise<void> {
    const scannedAt = state.watermark.after ?? new Date().toISOString();
    await this.insertScanSummary({
      spaceId: operation.space_id,
      projectId: operation.project_id,
      workflowId: state.workflow_id,
      operationId: operation.id,
      scanKey: `operation:${operation.id}`,
      scanWindowStart: state.watermark.before ?? null,
      scanWindowEnd: state.watermark.after ?? scannedAt,
      scannedAt,
      newItemCount: state.source_item_ids.length,
      relevantCount: counts.relevant,
      maybeCount: counts.maybe,
      excludedCount: counts.excluded,
    });
  }

  private async insertScanSummary(input: {
    spaceId: string; projectId: string; workflowId: string; operationId: string | null;
    scanKey: string; scanWindowStart: string | null; scanWindowEnd: string | null; scannedAt: string;
    newItemCount: number; relevantCount: number; maybeCount: number; excludedCount: number;
    onConflict?: "ignore" | "refresh_scan_time";
  }): Promise<void> {
    const now = new Date().toISOString();
    const conflictAction = input.onConflict === "refresh_scan_time"
      ? `DO UPDATE SET scanned_at = EXCLUDED.scanned_at, scan_window_end = EXCLUDED.scan_window_end`
      : `DO NOTHING`;
    await this.db.query(
      `INSERT INTO research_scan_summaries (
         id,space_id,project_id,workflow_id,operation_id,scan_key,scan_window_start,scan_window_end,
         scanned_at,new_item_count,relevant_count,maybe_count,excluded_count,created_at
       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
       ON CONFLICT (space_id,workflow_id,scan_key) ${conflictAction}`,
      [randomUUID(), input.spaceId, input.projectId, input.workflowId, input.operationId, input.scanKey,
        input.scanWindowStart, input.scanWindowEnd, input.scannedAt, input.newItemCount,
        input.relevantCount, input.maybeCount, input.excludedCount, now],
    );
  }

  private async isSourcePipelineDrained(spaceId: string, state: ResearchOperationState): Promise<boolean> {
    const result = await this.db.query<{ pending_extraction: string; pending_processing: string; pending_events: string }>(
      `SELECT
         (SELECT count(*)::int FROM extraction_jobs
           WHERE space_id=$1 AND status IN ('pending','running')
             AND metadata_json->>'source_backfill_plan_id'=ANY($2::text[])) AS pending_extraction,
         (SELECT count(*)::int FROM source_post_processing_runs
           WHERE space_id=$1 AND source_channel_id=ANY($3::text[]) AND status IN ('queued','running')) AS pending_processing,
         (SELECT count(*)::int FROM jobs
           WHERE space_id=$1 AND job_type='source_post_processing_event' AND status IN ('pending','claimed','running')
             AND payload_json->>'source_channel_id'=ANY($4::text[])) AS pending_events`,
      [spaceId, state.source_backfill_plan_ids?.length ? state.source_backfill_plan_ids : [state.source_backfill_plan_id], state.channel_ids, state.channel_ids],
    );
    return Number(result.rows[0]?.pending_extraction ?? 0) === 0
      && Number(result.rows[0]?.pending_processing ?? 0) === 0
      && Number(result.rows[0]?.pending_events ?? 0) === 0;
  }

  private async screeningProgressFor(
    spaceId: string,
    projectId: string,
    operationId: string,
    state: ResearchOperationState,
    operationCreatedAt?: string,
  ): Promise<NonNullable<ResearchOperationState["screening_progress"]>> {
    const sourceItemIds = unique(state.source_item_ids);
    const totalItems = sourceItemIds.length;
    const startedAt = optionalString(objectValue(state.screening_progress).started_at)
      ?? state.post_processing_recovery_requested_at
      ?? operationCreatedAt
      ?? null;
    const classified = await this.db.query<{
      classified: string;
      relevant: string;
      maybe: string;
      excluded: string;
    }>(
      `SELECT
         count(DISTINCT source_item_id)::int AS classified,
         count(DISTINCT source_item_id) FILTER (WHERE relevance='relevant')::int AS relevant,
         count(DISTINCT source_item_id) FILTER (WHERE relevance='maybe')::int AS maybe,
         count(DISTINCT source_item_id) FILTER (WHERE relevance='not_relevant')::int AS excluded
       FROM source_post_processing_item_decisions
      WHERE space_id=$1 AND project_id=$2
        AND source_channel_id=ANY($3::text[])
        AND source_item_id=ANY($4::text[])
        AND research_question_version=$5`,
      [spaceId, projectId, state.channel_ids, sourceItemIds, state.research_question_version],
    );
    const jobs = await this.db.query<{
      total: string;
      completed: string;
      active: string;
      failed: string;
    }>(
      `SELECT
         count(*)::int AS total,
         count(*) FILTER (
           WHERE status='completed'
             AND result_json->>'status'='succeeded'
         )::int AS completed,
         count(*) FILTER (WHERE status IN ('pending','claimed','running'))::int AS active,
         count(*) FILTER (
           WHERE status='failed'
              OR (status='completed' AND result_json->>'status'='failed')
         )::int AS failed
       FROM jobs
      WHERE space_id=$1
        AND job_type='source_post_processing_event'
        AND payload_json->>'phase'='research_recovery'
        AND payload_json->>'recovery_for_operation_id'=$2
        AND ($3::timestamptz IS NULL OR created_at >= $3::timestamptz)`,
      [spaceId, operationId, startedAt],
    );
    const jobRow = jobs.rows[0];
    const corpus = await this.countRelevantItems(spaceId, projectId, sourceItemIds);
    const classifiedItems = Math.min(totalItems, Number(classified.rows[0]?.classified ?? 0));
    const totalBatches = Number(jobRow?.total ?? 0);
    const completedBatches = Number(jobRow?.completed ?? 0);
    const activeBatches = Number(jobRow?.active ?? 0);
    const failedBatches = Number(jobRow?.failed ?? 0);
    const phase = failedBatches > 0
      ? "failed"
      : classifiedItems >= totalItems && totalItems > 0
        ? "ready_for_review"
        : totalBatches > 0
          ? "screening_batches"
          : "preparing_batches";
    const message = phase === "failed"
      ? "A screening batch failed; retry is available from the research operation."
      : phase === "ready_for_review"
        ? `All ${classifiedItems.toLocaleString()} papers are classified. The screening review is ready.`
        : phase === "screening_batches"
          ? `${activeBatches > 0 ? "Screening" : "Waiting for"} batch ${Math.min(completedBatches + 1, totalBatches)} of ${totalBatches} · ${classifiedItems}/${totalItems} papers classified.`
          : `Preparing ${totalItems.toLocaleString()} papers for screening in batches of ${SOURCE_POST_PROCESSING_LIMITS.researchStructuredOutputBatchSize}.`;
    return {
      phase,
      total_items: totalItems,
      classified_items: classifiedItems,
      unclassified_items: Math.max(0, totalItems - classifiedItems),
      relevant_items: Number(classified.rows[0]?.relevant ?? 0),
      maybe_items: Number(classified.rows[0]?.maybe ?? 0),
      excluded_items: Number(classified.rows[0]?.excluded ?? 0),
      missing_full_text: corpus.missing_full_text,
      evidence_count: corpus.evidence_count,
      failed_items: corpus.failed_items,
      batch_size: SOURCE_POST_PROCESSING_LIMITS.researchStructuredOutputBatchSize,
      total_batches: totalBatches,
      completed_batches: completedBatches,
      active_batches: activeBatches,
      failed_batches: failedBatches,
      started_at: startedAt,
      updated_at: new Date().toISOString(),
      message,
    };
  }

  private async projectWriterActor(spaceId: string, projectId: string): Promise<string | null> {
    const result = await this.db.query<{ user_id: string }>(
      `SELECT owner_user_id AS user_id FROM projects WHERE space_id=$1 AND id=$2 AND owner_user_id IS NOT NULL
       UNION ALL
       SELECT user_id FROM space_memberships WHERE space_id=$1 AND role IN ('owner','admin') AND status='active'
       ORDER BY user_id LIMIT 1`,
      [spaceId, projectId],
    );
    return result.rows[0]?.user_id ?? null;
  }

  private async setWorkflowMonitoring(spaceId: string, projectId: string, workflowId: string, state: ResearchOperationState): Promise<void> {
    // jsonb_set silently no-ops when an intermediate path key is missing, and
    // reused workflows (created by draft/item-limit paths) may have no
    // `monitoring` object at all — merge with || so the object is created.
    await this.db.query(
      `UPDATE project_research_workflows
          SET state_json=COALESCE(state_json,'{}'::jsonb) || jsonb_build_object(
                'monitoring',
                COALESCE(state_json->'monitoring','{}'::jsonb) || jsonb_build_object(
                  'active', true,
                  'channel_ids', $4::jsonb,
                  'watermark_after', $5::jsonb
                )
              ),
              updated_at=$6
        WHERE space_id=$1 AND project_id=$2 AND id=$3`,
      [spaceId, projectId, workflowId, JSON.stringify(state.channel_ids), JSON.stringify(new Date().toISOString()), new Date().toISOString()],
    );
    for (const channelId of state.channel_ids ?? []) {
      const channel = await this.db.query<{ id: string; space_id: string; owner_user_id: string; status: string; fetch_frequency: string }>(
        `UPDATE source_channels SET status='active', fetch_frequency='daily', schedule_rule_json=COALESCE(schedule_rule_json, '{"frequency":"daily","hour":0,"minute":0}'::jsonb), updated_at=$3
          WHERE space_id=$1 AND id=$2 RETURNING id, space_id, (SELECT owner_user_id FROM source_connections WHERE id=source_channels.source_connection_id) AS owner_user_id, status, fetch_frequency`,
        [spaceId, channelId, new Date().toISOString()],
      );
      if (channel.rows[0]) await upsertSourceChannelScanTask(this.db, { channel: channel.rows[0], nextRunAt: new Date().toISOString(), updatedAt: new Date().toISOString() });
    }
    for (const ruleId of state.source_post_processing_rule_ids ?? []) {
      await this.db.query(
        `UPDATE source_post_processing_rules SET status='active', updated_at=$3 WHERE space_id=$1 AND id=$2 AND status <> 'archived'`,
        [spaceId, ruleId, new Date().toISOString()],
      );
    }
  }

  private async waivePendingScreeningCheckpoint(
    identity: SpaceUserIdentity,
    projectId: string,
    workflowId: string,
    operationId: string,
    reason: string,
  ): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE project_research_checkpoints
          SET status='waived', user_decision='waived', decision_reason=$4, decided_by_user_id=$5, decided_at=$6, updated_at=$6
        WHERE space_id=$1 AND project_id=$2 AND workflow_id=$3 AND checkpoint_type='screening_gate' AND status='pending'
          AND machine_result_json->>'operation_id'=$7`,
      [identity.spaceId, projectId, workflowId, reason, identity.userId, now, operationId],
    );
  }

  private async skipPendingScreeningCheckpoint(
    spaceId: string,
    projectId: string,
    workflowId: string,
    operationId: string,
    reason: string,
  ): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE project_research_checkpoints
          SET status='waived', user_decision='waived', decision_reason=$4,
              decided_by_user_id=NULL, decided_at=$5, updated_at=$5
        WHERE space_id=$1 AND project_id=$2 AND workflow_id=$3
          AND checkpoint_type='screening_gate' AND status='pending'
          AND machine_result_json->>'operation_id'=$6`,
      [spaceId, projectId, workflowId, reason, now, operationId],
    );
  }

  private async workflow(spaceId: string, projectId: string, workflowId: string | null, forUpdate = false, includeDraft = false): Promise<WorkflowRow | null> {
    const result = await this.db.query<WorkflowRow>(
      `SELECT * FROM project_research_workflows WHERE space_id=$1 AND project_id=$2 ${workflowId ? "AND id=$3" : includeDraft ? "AND status IN ('active','paused','not_started')" : "AND status IN ('active','paused')"} ORDER BY updated_at DESC LIMIT 1${forUpdate ? " FOR UPDATE" : ""}`,
      workflowId ? [spaceId, projectId, workflowId] : [spaceId, projectId],
    );
    return result.rows[0] ?? null;
  }

  private async operation(spaceId: string, operationId: string): Promise<OperationRow | null> {
    const result = await this.db.query<OperationRow>(`SELECT id,space_id,project_id,status,progress_json,created_at FROM project_operations WHERE id=$1 AND space_id=$2`, [operationId, spaceId]);
    return result.rows[0] ?? null;
  }

  private async activeIncremental(spaceId: string, projectId: string, workflowId: string) {
    const result = await this.db.query<OperationRow>(
      `SELECT id,space_id,project_id,status,progress_json FROM project_operations
        WHERE space_id=$1 AND project_id=$2 AND kind='research'
          AND status IN ('active','waiting_review')
          AND progress_json->>'run_kind'='incremental'
          AND progress_json->>'workflow_id'=$3
          AND progress_json->>'current_stage' IN ('screening','monitor_setup','backfill')
        ORDER BY updated_at DESC LIMIT 1`,
      [spaceId, projectId, workflowId],
    );
    return result.rows[0] ?? null;
  }

  private async activeHistoricalBackfill(spaceId: string, projectId: string, workflowId: string) {
    const result = await this.db.query<OperationRow>(
      `SELECT id,space_id,project_id,status,progress_json FROM project_operations
        WHERE space_id=$1 AND project_id=$2 AND kind='research'
          AND status IN ('active','waiting_review')
          AND progress_json->>'run_kind'='historical_backfill'
          AND progress_json->>'workflow_id'=$3
        ORDER BY updated_at DESC LIMIT 1`,
      [spaceId, projectId, workflowId],
    );
    return result.rows[0] ?? null;
  }

  private async activeResearchOperation(spaceId: string, projectId: string, workflowId: string) {
    const result = await this.db.query<OperationRow>(
      `SELECT id,space_id,project_id,status,progress_json FROM project_operations
        WHERE space_id=$1 AND project_id=$2 AND kind='research'
          AND status IN ('active','waiting_review')
          AND progress_json->>'workflow_id'=$3
        ORDER BY updated_at DESC LIMIT 1`,
      [spaceId, projectId, workflowId],
    );
    return result.rows[0] ?? null;
  }

  private async operationByIdempotency(spaceId: string, projectId: string, key: string): Promise<OperationRow | null> {
    const result = await this.db.query<OperationRow>(
      `SELECT id,space_id,project_id,status,progress_json FROM project_operations
        WHERE space_id=$1 AND project_id=$2 AND kind='research'
          AND progress_json->'idempotency'->>'key'=$3
        ORDER BY created_at LIMIT 1`,
      [spaceId, projectId, key],
    );
    return result.rows[0] ?? null;
  }

  private async appendWorkflowCoverage(
    spaceId: string,
    projectId: string,
    workflowId: string,
    range: { from: string; to: string; operation_id: string; status: "pending" | "completed" | "partial" },
  ): Promise<void> {
    const workflow = await this.workflow(spaceId, projectId, workflowId);
    if (!workflow) throw new HttpError(404, "Research workflow not found");
    const state = objectValue(workflow.state_json);
    const ranges = historyCoverage(state).filter((item) => item.operation_id !== range.operation_id);
    ranges.push(range);
    await this.db.query(
      `UPDATE project_research_workflows SET state_json=jsonb_set(COALESCE(state_json,'{}'::jsonb),'{coverage_ranges}',$4::jsonb,true),updated_at=$5 WHERE space_id=$1 AND project_id=$2 AND id=$3`,
      [spaceId, projectId, workflowId, JSON.stringify(ranges), new Date().toISOString()],
    );
  }

  private async completeWorkflowCoverage(
    spaceId: string,
    projectId: string,
    workflowId: string,
    operationId: string,
    status: "completed" | "partial",
  ): Promise<void> {
    const workflow = await this.workflow(spaceId, projectId, workflowId);
    if (!workflow) return;
    const ranges = historyCoverage(workflow.state_json).map((range) =>
      range.operation_id === operationId ? { ...range, status } : range,
    );
    await this.db.query(
      `UPDATE project_research_workflows SET state_json=jsonb_set(COALESCE(state_json,'{}'::jsonb),'{coverage_ranges}',$4::jsonb,true),updated_at=$5 WHERE space_id=$1 AND project_id=$2 AND id=$3`,
      [spaceId, projectId, workflowId, JSON.stringify(ranges), new Date().toISOString()],
    );
  }

  private async sourceItemsForBackfillPlans(spaceId: string, planIds: string[]): Promise<string[]> {
    if (planIds.length === 0) return [];
    const result = await this.db.query<{ id: string }>(
      `SELECT id FROM source_items
        WHERE space_id=$1 AND deleted_at IS NULL
          AND (
            metadata_json->>'source_backfill_plan_id'=ANY($2::text[])
            OR metadata_json->>'source_backfill_created_plan_id'=ANY($2::text[])
          )`,
      [spaceId, planIds],
    );
    return result.rows.map((row) => row.id);
  }

  private async backfillPlanForItems(spaceId: string, itemIds: string[]): Promise<Map<string, { last_plan_id: string | null; created_plan_id: string | null }>> {
    if (itemIds.length === 0) return new Map();
    const result = await this.db.query<{ id: string; last_plan_id: string | null; created_plan_id: string | null }>(
      `SELECT id,
              metadata_json->>'source_backfill_plan_id' AS last_plan_id,
              metadata_json->>'source_backfill_created_plan_id' AS created_plan_id
         FROM source_items
        WHERE space_id=$1 AND id=ANY($2::text[])`,
      [spaceId, itemIds],
    );
    return new Map(result.rows.map((row) => [row.id, { last_plan_id: row.last_plan_id, created_plan_id: row.created_plan_id }]));
  }

  private async appendPendingIncrementalItems(spaceId: string, projectId: string, workflowId: string, itemIds: string[]): Promise<void> {
    const workflow = await this.workflow(spaceId, projectId, workflowId);
    if (!workflow) return;
    const state = objectValue(workflow.state_json);
    const pending = unique([...stringArray(state.pending_incremental_source_item_ids), ...itemIds]);
    await this.db.query(
      `UPDATE project_research_workflows SET state_json=jsonb_set(COALESCE(state_json,'{}'::jsonb),'{pending_incremental_source_item_ids}',$4::jsonb,true),updated_at=$5 WHERE space_id=$1 AND project_id=$2 AND id=$3`,
      [spaceId, projectId, workflowId, JSON.stringify(pending), new Date().toISOString()],
    );
  }

  private async flushPendingIncremental(spaceId: string, projectId: string, workflowId: string): Promise<void> {
    const workflow = await this.workflow(spaceId, projectId, workflowId);
    if (!workflow) return;
    if (await this.hasResearchQuestionDrift(spaceId, projectId, workflow.state_json)) return;
    const state = objectValue(workflow.state_json);
    const pending = unique(stringArray(state.pending_incremental_source_item_ids));
    if (pending.length === 0) return;
    await this.db.query(
      `UPDATE project_research_workflows SET state_json=state_json - 'pending_incremental_source_item_ids',updated_at=$4 WHERE space_id=$1 AND project_id=$2 AND id=$3`,
      [spaceId, projectId, workflowId, new Date().toISOString()],
    );
    const actorUserId = await this.projectWriterActor(spaceId, projectId);
    if (!actorUserId) return;
    await this.triggerIncremental(
      { spaceId, userId: actorUserId },
      projectId,
      workflowId,
      { source_item_ids: pending, idempotency_key: `historical-backfill-flush:${workflowId}:${pending.join(",")}` },
    );
  }

  private async projectResearchQuestion(spaceId: string, projectId: string): Promise<string | null> {
    const result = await this.db.query<{ current_focus: string | null; research_question: string | null }>(
      `SELECT p.current_focus, pr.research_question
         FROM projects p
         LEFT JOIN project_research_profiles pr ON pr.space_id=p.space_id AND pr.project_id=p.id
        WHERE p.space_id=$1 AND p.id=$2
        LIMIT 1`,
      [spaceId, projectId],
    );
    const row = result.rows[0];
    return optionalString(row?.current_focus) ?? optionalString(row?.research_question);
  }

  private async hasResearchQuestionDrift(spaceId: string, projectId: string, workflowValue: unknown): Promise<boolean> {
    return researchQuestionDrift(
      await this.projectResearchQuestion(spaceId, projectId),
      optionalString(objectValue(workflowValue).research_question),
    );
  }

  private async assertResearchQuestionAligned(spaceId: string, projectId: string, workflowValue: unknown): Promise<void> {
    if (await this.hasResearchQuestionDrift(spaceId, projectId, workflowValue)) {
      throw new HttpError(409, "The project research question changed. Apply it to future runs before continuing research.");
    }
  }

  private async operationForCheckpoint(spaceId: string, projectId: string, checkpointId: string) {
    const result = await this.db.query<OperationRow>(
      `SELECT po.id,po.space_id,po.project_id,po.status,po.progress_json FROM project_operations po JOIN project_research_checkpoints c ON c.machine_result_json->>'operation_id'=po.id WHERE po.space_id=$1 AND po.project_id=$2 AND c.id=$3 LIMIT 1`,
      [spaceId, projectId, checkpointId],
    );
    return result.rows[0] ?? null;
  }

  private async setState(
    operation: Pick<OperationRow, "id" | "space_id" | "project_id" | "progress_json">,
    state: ResearchOperationState,
    steps: ResearchStepOverride[],
  ) {
    const base = researchState(operation.progress_json);
    const from = base.current_stage;
    const to = researchStage(state.current_stage);
    if (from === to) {
      await updateProjection(
        this.db,
        operation.space_id,
        operation.id,
        ({ state: current }) => {
          applyResearchStatePatch(current, base, state);
        },
        steps,
      );
      return;
    }
    await transitionResearchOperation(this.db, operation.space_id, operation.id, {
      from: [from],
      to,
      mutate: ({ state: current }) => {
        applyResearchStatePatch(current, base, state);
      },
      stepOverrides: steps,
      onIllegal: "noop",
    });
  }

  private async failOperation(
    operation: OperationRow,
    message: string,
    details: {
      code?: string;
      rejection?: ResearchSynthesisRejection;
      diagnostics?: Record<string, unknown>;
    } = {},
  ): Promise<void> {
    if (["completed", "failed", "cancelled"].includes(operation.status)) return;
    const state = researchState(operation.progress_json);
    const failedStage = state.current_stage;
    state.stage_state = "failed";
    state.current_stage = "failed";
    if (failedStage === "screening") {
      const progress = await this.screeningProgressFor(
        operation.space_id,
        operation.project_id,
        operation.id,
        state,
        operation.created_at,
      );
      state.screening_progress = {
        ...progress,
        phase: "failed",
        message: "Screening failed. Review the operation error and retry the screening stage.",
      };
    }
    const error: ResearchOperationError = {
      code: details.code ?? "research_operation_failed",
      message,
      at: new Date().toISOString(),
      ...(details.rejection ? { rejection: details.rejection } : {}),
      ...(details.diagnostics ? { diagnostics: details.diagnostics } : {}),
    };
    const failedSteps = deriveStepStates({ ...state, current_stage: failedStage })
      .map((step) => step.seq === researchStageIndex(failedStage)
        ? {
            ...step,
            detail: {
              error: message,
              error_code: error.code,
              ...(details.rejection ? { rejection: details.rejection } : {}),
              ...(details.diagnostics ? { diagnostics: details.diagnostics } : {}),
            },
          }
        : step);
    await this.setState(operation, { ...state, failed_stage: failedStage, error }, failedSteps);
  }

  private async readOperation(identity: SpaceUserIdentity, projectId: string, operationId: string): Promise<OperationRead> {
    return await new ProjectOperationService(this.db).get(identity, projectId, operationId) as unknown as OperationRead;
  }

  private async recordSynthesisValidationFailure(
    spaceId: string,
    runId: string,
    failure: ResearchArtifactValidationFailure,
  ): Promise<void> {
    process.stderr.write(`[project-research.synthesis] validation_failed ${JSON.stringify({
      run_id: runId,
      code: failure.code,
      message: failure.message,
      diagnostics: failure.diagnostics,
    })}\n`);
    const completedAt = new Date().toISOString();
    const repository = new PgRunRepository(this.db);
    try {
      await repository.markRunDegraded({
        run_id: runId,
        space_id: spaceId,
        completed_at: completedAt,
        error_code: failure.code,
        error_message: failure.message,
        diagnostics: failure.diagnostics,
      });
    } catch {
      // The operation error below remains the source of truth if the run
      // read-model update cannot be written.
    }
    try {
      await repository.appendRunEvent({
        run_id: runId,
        space_id: spaceId,
        event_type: "validation_completed",
        status: "failed",
        summary: "Project Research synthesis artifact validation failed.",
        error_code: failure.code,
        error_message: failure.message,
        trust_level: "high",
        metadata_json: {
          validation_layer: "project_research_synthesis",
          ...failure.diagnostics,
        },
      });
    } catch {
      // Run events are best-effort diagnostics; the operation still records
      // the structured failure and its safe content summary.
    }
  }

  private async startResponse(identity: SpaceUserIdentity, projectId: string, operationId: string) {
    const operation = await this.readOperation(identity, projectId, operationId);
    const state = researchState(operation.progress_json);
    const workflow = await this.workflow(identity.spaceId, projectId, state.workflow_id);
    const channelRows = state.channel_ids?.length
      ? await new SourceChannelService(this.db, this.config!).listForSpaceByIds(identity, state.channel_ids)
      : [];
    const bindingIds = state.project_source_binding_ids?.length
      ? state.project_source_binding_ids
      : state.project_source_binding_id ? [state.project_source_binding_id] : [];
    const bindingRows = bindingIds.length
      ? (await this.db.query(
        `SELECT * FROM project_source_bindings WHERE id=ANY($1::text[]) AND space_id=$2 ORDER BY created_at ASC`,
        [bindingIds, identity.spaceId],
      )).rows
      : [];
    return {
      workflow,
      operation,
      source_channel: channelRows[0] ?? null,
      source_channels: channelRows,
      source_binding: bindingRows[0] ?? null,
      source_bindings: bindingRows,
      status: operation.status === "completed" ? "succeeded" : operation.status,
    };
  }

  private async enqueueReconcile(
    spaceId: string,
    userId: string | null,
    operationId: string | null,
    reason: string,
    extra: Record<string, unknown> = {},
  ): Promise<void> {
    await new PgJobQueueRepository(this.db).enqueue({
      job_type: "project_research_reconcile",
      space_id: spaceId,
      user_id: userId,
      payload: {
        ...(operationId ? { operation_id: operationId } : {}),
        ...extra,
        reason,
      },
    });
  }

  private async enqueueIntegrityMonitor(
    spaceId: string,
    userId: string | null,
    projectId: string,
    workflowId: string,
    reason: string,
  ): Promise<void> {
    const active = await this.db.query<{ id: string }>(
      `SELECT id FROM jobs WHERE space_id=$1 AND job_type='project_research_integrity_monitor'
        AND payload_json->>'project_id'=$2 AND status IN ('pending','claimed','running') LIMIT 1`,
      [spaceId, projectId],
    );
    if (active.rows[0]) return;
    await new PgJobQueueRepository(this.db).enqueue({
      job_type: "project_research_integrity_monitor",
      space_id: spaceId,
      user_id: userId,
      payload: { project_id: projectId, workflow_id: workflowId, reason },
    });
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return objectValue(value);
  }
}

export function registerProjectResearchHandler(registry: JobHandlerRegistry, config: ServerConfig): void {
  if (!config.databaseUrl) return;
  registry.register("project_research_reconcile", async (job): Promise<JobHandlerResult> => {
    const db = getDbPool(config.databaseUrl!);
    const orchestrator = new ProjectResearchOrchestrator(db, config);
    const operationId = optionalString(job.payload.operation_id);
    const runId = optionalString(job.payload.run_id);
    const sourcePostProcessingRunId = optionalString(job.payload.source_post_processing_run_id);
    if (runId) await orchestrator.reconcileRun(job.space_id, runId);
    if (sourcePostProcessingRunId) await orchestrator.reconcilePostProcessingRun(job.space_id, sourcePostProcessingRunId);
    if (operationId) await orchestrator.reconcileOperation(job.space_id, operationId);
    return { operation_id: operationId, run_id: runId, source_post_processing_run_id: sourcePostProcessingRunId, status: "reconciled" };
  });
  registry.register("project_research_integrity_monitor", async (job): Promise<JobHandlerResult> => {
    const projectId = optionalString(job.payload.project_id);
    const workflowId = optionalString(job.payload.workflow_id);
    if (!projectId || !workflowId) throw new Error("project_research_integrity_monitor requires project_id and workflow_id");
    return new ProjectResearchIntegrityMonitorService(getDbPool(config.databaseUrl!)).check({
      spaceId: job.space_id,
      projectId,
      workflowId,
      userId: job.user_id,
    });
  });
}

function normalizeInitialIntakeInput(body: Record<string, unknown>, profileQuestion: string | null): ResearchInput {
  rejectLegacyResearchRuntimeFields(body);
  const researchQuestion = optionalString(body.research_question) ?? profileQuestion;
  if (!researchQuestion) throw new HttpError(422, "research_question is required");
  const sourceChannelIds = normalizeSourceChannelIds(body.source_channel_ids);
  if (sourceChannelIds.length < 1) throw new HttpError(422, "source_channel_ids must contain at least one monitor");
  const historyMode = optionalString(body.history_mode) ?? "bounded_range";
  if (historyMode !== "bounded_range" && historyMode !== "all_available") {
    throw new HttpError(422, "history_mode must be bounded_range or all_available");
  }
  const requestedFrom = optionalString(body.from);
  const requestedTo = optionalString(body.to);
  let from: string;
  let to: string;
  if (historyMode === "all_available") {
    if (requestedFrom || requestedTo) throw new HttpError(422, "from and to must be omitted for all_available history");
    from = ARXIV_HISTORY_FLOOR;
    to = new Date().toISOString();
  } else {
    if (!requestedFrom || !requestedTo) throw new HttpError(422, "from and to are required for bounded_range initial literature intake");
    if (Number.isNaN(Date.parse(requestedFrom)) || Number.isNaN(Date.parse(requestedTo)) || Date.parse(requestedFrom) >= Date.parse(requestedTo)) throw new HttpError(422, "from must be earlier than to");
    from = new Date(requestedFrom).toISOString();
    to = new Date(requestedTo).toISOString();
  }
  const maxItems = body.max_items === undefined ? MAX_ITEMS_DEFAULT : Number(body.max_items);
  if (!Number.isInteger(maxItems) || maxItems < 1 || maxItems > MAX_ITEMS_DEFAULT) throw new HttpError(422, `max_items must be an integer between 1 and ${MAX_ITEMS_DEFAULT}`);
  const monitoringField = optionalString(body.monitoring_field) ?? "submittedDate";
  if (!MONITORING_FIELDS.has(monitoringField)) throw new HttpError(422, "monitoring_field must be submittedDate or lastUpdatedDate");
  const schedule = optionalString(body.schedule) ?? "daily";
  if (schedule !== "daily") throw new HttpError(422, "v1 supports a daily monitoring schedule");
  const executionBody = objectValue(body.execution);
  const reportDepth = normalizeReportDepth(body.report_depth);
  const questionRefineSkipped = normalizeQuestionRefineSkipped(body.question_refine_skipped);
  // Refinement is a hard gate for starting (revised D5): a failing question
  // may still be saved as a draft, but it cannot spend the intake budget.
  if (questionRefineSkipped) {
    throw new HttpError(422, "The research question has not passed refinement; adopt a suggested question or reassess with your answers before starting");
  }
  const searchStrategyId = optionalString(body.search_strategy_id);
  const execution: ResearchExecutionSelection = {
    modelProviderId: optionalString(executionBody.model_provider_id),
    modelName: optionalString(executionBody.model_name),
  };
  const idempotencyKey = optionalString(body.idempotency_key) ?? fingerprintOf({ researchQuestion, sourceChannelIds, historyMode, from: historyMode === "bounded_range" ? from : null, to: historyMode === "bounded_range" ? to : null, maxItems, monitoringField, schedule, execution });
  return { researchQuestion, sourceChannelIds, historyMode: historyMode as HistoryMode, from, to, maxItems, monitoringField: monitoringField as ResearchInput["monitoringField"], schedule: "daily", agentId: "", runtimeProfileId: "", execution, idempotencyKey, reportDepth, questionRefineSkipped, searchStrategyId };
}

function normalizeInitialIntakeDraft(body: Record<string, unknown>, profileQuestion: string | null): InitialIntakeDraft {
  rejectLegacyResearchRuntimeFields(body);
  const researchQuestion = optionalString(body.research_question) ?? profileQuestion;
  if (!researchQuestion) throw new HttpError(422, "research_question is required");
  // A draft may be saved before any monitor exists (question refinement is
  // step one); only starting the intake requires monitors.
  const sourceChannelIds = normalizeSourceChannelIds(body.source_channel_ids);
  const historyMode = optionalString(body.history_mode) ?? "bounded_range";
  if (historyMode !== "bounded_range" && historyMode !== "all_available") {
    throw new HttpError(422, "history_mode must be bounded_range or all_available");
  }
  const from = historyMode === "all_available" ? null : optionalDraftDate(body.from);
  const to = historyMode === "all_available" ? null : optionalDraftDate(body.to);
  if (from && to && Date.parse(from) >= Date.parse(to)) throw new HttpError(422, "from must be earlier than to");
  const maxItems = body.max_items === undefined || body.max_items === "" ? MAX_ITEMS_DEFAULT : Number(body.max_items);
  if (!Number.isInteger(maxItems) || maxItems < 1 || maxItems > MAX_ITEMS_DEFAULT) {
    throw new HttpError(422, `max_items must be an integer between 1 and ${MAX_ITEMS_DEFAULT}`);
  }
  const monitoringField = optionalString(body.monitoring_field) ?? "submittedDate";
  if (!MONITORING_FIELDS.has(monitoringField)) throw new HttpError(422, "monitoring_field must be submittedDate or lastUpdatedDate");
  const schedule = optionalString(body.schedule) ?? "daily";
  if (schedule !== "daily") throw new HttpError(422, "v1 supports a daily monitoring schedule");
  const executionBody = objectValue(body.execution);
  const reportDepth = normalizeReportDepth(body.report_depth);
  const questionRefineSkipped = normalizeQuestionRefineSkipped(body.question_refine_skipped);
  const searchStrategyId = optionalString(body.search_strategy_id);
  const questionRefinement = normalizeQuestionRefinementDraft(body.question_refinement);
  return {
    researchQuestion,
    sourceChannelIds,
    historyMode: historyMode as HistoryMode,
    from,
    to,
    maxItems,
    monitoringField: monitoringField as InitialIntakeDraft["monitoringField"],
    schedule: "daily",
    execution: {
      modelProviderId: optionalString(executionBody.model_provider_id),
      modelName: optionalString(executionBody.model_name),
    },
    reportDepth,
    questionRefineSkipped,
    searchStrategyId,
    questionRefinement,
  };
}

function normalizeQuestionRefinementDraft(value: unknown): Record<string, unknown> | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "object" || Array.isArray(value)) throw new HttpError(422, "question_refinement must be an object");
  const record = value as Record<string, unknown>;
  if (JSON.stringify(record).length > 20_000) throw new HttpError(422, "question_refinement is too large to persist");
  return record;
}

function normalizeSourceChannelIds(value: unknown): string[] {
  return unique(Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).map(item => item.trim())
    : []);
}

function normalizeReportDepth(value: unknown): ResearchReportDepth {
  const depth = optionalString(value);
  if (!depth) throw new HttpError(422, "report_depth is required");
  if (depth !== "quick" && depth !== "full") throw new HttpError(422, "report_depth must be quick or full");
  return depth;
}

function normalizeQuestionRefineSkipped(value: unknown): boolean {
  if (typeof value !== "boolean") throw new HttpError(422, "question_refine_skipped is required");
  return value;
}

function optionalDraftDate(value: unknown): string | null {
  const raw = optionalString(value);
  if (!raw) return null;
  return Number.isNaN(Date.parse(raw)) ? raw : new Date(raw).toISOString();
}

function initialIntakeDraftState(draft: InitialIntakeDraft, savedAt: string): Record<string, unknown> {
  return {
    schema_version: "project_research_initial_intake.v1",
    research_question: draft.researchQuestion,
    research_question_version: 1,
    source_channel_ids: draft.sourceChannelIds,
    initial_intake: {
      history_mode: draft.historyMode,
      from: draft.from,
      to: draft.to,
      max_items: draft.maxItems,
      monitoring_field: draft.monitoringField,
      schedule: draft.schedule,
      report_depth: draft.reportDepth,
    },
    execution: {
      model_provider_id: draft.execution.modelProviderId ?? null,
      model_name: draft.execution.modelName ?? null,
    },
    question_refine_skipped: draft.questionRefineSkipped,
    search_strategy_id: draft.searchStrategyId,
    question_refinement: draft.questionRefinement,
    draft: { status: "saved", saved_at: savedAt },
  };
}

function workflowOutput(row: WorkflowRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    workflow_type: row.workflow_type,
    current_stage: row.current_stage ?? null,
    status: row.status,
    mode: row.mode,
    state_json: objectValue(row.state_json),
    started_by_user_id: row.started_by_user_id ?? null,
    started_run_id: row.started_run_id ?? null,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
  };
}

function initialIntakeFingerprint(input: ResearchInput): string {
  return fingerprintOf({
    researchQuestion: input.researchQuestion,
    sourceChannelIds: input.sourceChannelIds,
    historyMode: input.historyMode,
    from: input.historyMode === "bounded_range" ? input.from : null,
    to: input.historyMode === "bounded_range" ? input.to : null,
    maxItems: input.maxItems,
    monitoringField: input.monitoringField,
    schedule: input.schedule,
    execution: input.execution,
    reportDepth: input.reportDepth,
    questionRefineSkipped: input.questionRefineSkipped,
    searchStrategyId: input.searchStrategyId,
  });
}

function questionVersion(value: unknown): number {
  const version = objectValue(value).research_question_version;
  return typeof version === "number" && Number.isInteger(version) && version >= 1 ? version : 1;
}

function contentProfileForProvider(providerKey: string): "generic" | "arxiv_new_papers" {
  return providerKey === "arxiv" ? "arxiv_new_papers" : "generic";
}

function initialState(input: ResearchInput, workflowId: string, fingerprint: string): ResearchOperationState {
  return {
    schema_version: "project_research_operation.v1", run_kind: "baseline", workflow_id: workflowId, research_question: input.researchQuestion, research_question_version: 1, report_depth: input.reportDepth, question_refine_skipped: input.questionRefineSkipped, channel_ids: input.sourceChannelIds, project_source_binding_ids: [], source_post_processing_rule_ids: [], project_source_binding_id: null, source_post_processing_rule_id: null, source_backfill_plan_id: null,
    query: { source_channel_ids: input.sourceChannelIds, fingerprint: fingerprintOf({ source_channel_ids: input.sourceChannelIds, history_mode: input.historyMode, from: input.from, to: input.to, sort_by: input.monitoringField }), sort_by: input.monitoringField, history_mode: input.historyMode, from: input.from, to: input.to },
    history: { mode: input.historyMode, from: input.from, to: input.to, max_items: input.maxItems }, watermark: { before: null, after: null, overlap_hours: OVERLAP_HOURS }, source_item_ids: [], current_stage: "monitor_setup", stage_state: "running", agent_id: input.agentId, runtime_profile_id: input.runtimeProfileId,
    source_backfill_plan_ids: [], checkpoint_ids: [], synthesis_run_id: null, artifact_ids: [], partial: false, monitoring_active: false, idempotency: { key: input.idempotencyKey, fingerprint },
  };
}

function incrementalStateFromWorkflow(
  workflowValue: unknown,
  workflowId: string,
  sourceItemIds: string[],
  idempotencyKey: string,
  watermark: ResearchOperationState["watermark"] | null,
): ResearchOperationState {
  const workflow = objectValue(workflowValue);
  const monitoring = objectValue(workflow.monitoring);
  const monitoringField = optionalString(monitoring.field) === "lastUpdatedDate" ? "lastUpdatedDate" : "submittedDate";
  const resolvedWatermark = watermark ?? {
    before: optionalString(monitoring.watermark_after),
    after: null,
    overlap_hours: OVERLAP_HOURS,
  };
  return {
    schema_version: "project_research_operation.v1",
    run_kind: "incremental",
    workflow_id: workflowId,
    research_question: optionalString(workflow.research_question) ?? "Project research",
    research_question_version: questionVersion(workflow),
    report_depth: normalizeReportDepth(workflow.report_depth),
    question_refine_skipped: workflow.question_refine_skipped === true,
    channel_ids: stringArray(workflow.channel_ids),
    project_source_binding_ids: stringArray(workflow.project_source_binding_ids),
    source_post_processing_rule_ids: stringArray(workflow.source_post_processing_rule_ids),
    project_source_binding_id: optionalString(workflow.project_source_binding_id),
    source_post_processing_rule_id: optionalString(workflow.source_post_processing_rule_id),
    source_backfill_plan_id: null,
    source_backfill_plan_ids: [],
    query: {
      source_channel_ids: stringArray(workflow.source_channel_ids ?? workflow.channel_ids),
      fingerprint: fingerprintOf({ source_channel_ids: stringArray(workflow.source_channel_ids ?? workflow.channel_ids), monitoring_field: monitoringField }),
      sort_by: monitoringField,
      history_mode: null,
      from: null,
      to: null,
    },
    history: { mode: null, from: null, to: null, max_items: null },
    watermark: resolvedWatermark,
    source_item_ids: unique(sourceItemIds),
    current_stage: "screening",
    stage_state: "running",
    agent_id: optionalString(workflow.agent_id) ?? "",
    runtime_profile_id: optionalString(workflow.runtime_profile_id) ?? "",
    checkpoint_ids: [],
    synthesis_run_id: null,
    artifact_ids: [],
    partial: false,
    monitoring_active: true,
    idempotency: { key: idempotencyKey, fingerprint: fingerprintOf({ workflowId, sourceItemIds, idempotencyKey }) },
  };
}

function historicalBackfillStateFromWorkflow(
  workflowValue: unknown,
  workflowId: string,
  from: string,
  to: string,
  maxItems: number,
  idempotencyKey: string,
  fingerprint: string,
): ResearchOperationState {
  const workflow = objectValue(workflowValue);
  const monitoring = objectValue(workflow.monitoring);
  const monitoringField = optionalString(monitoring.field) === "lastUpdatedDate" ? "lastUpdatedDate" : "submittedDate";
  return {
    schema_version: "project_research_operation.v1",
    run_kind: "historical_backfill",
    workflow_id: workflowId,
    research_question: optionalString(workflow.research_question) ?? "Project research",
    research_question_version: questionVersion(workflow),
    report_depth: normalizeReportDepth(workflow.report_depth),
    question_refine_skipped: workflow.question_refine_skipped === true,
    channel_ids: stringArray(workflow.channel_ids),
    project_source_binding_ids: stringArray(workflow.project_source_binding_ids),
    source_post_processing_rule_ids: stringArray(workflow.source_post_processing_rule_ids),
    project_source_binding_id: optionalString(workflow.project_source_binding_id),
    source_post_processing_rule_id: optionalString(workflow.source_post_processing_rule_id),
    source_backfill_plan_id: null,
    source_backfill_plan_ids: [],
    query: {
      source_channel_ids: stringArray(workflow.source_channel_ids ?? workflow.channel_ids),
      fingerprint: fingerprintOf({ source_channel_ids: stringArray(workflow.source_channel_ids ?? workflow.channel_ids), monitoring_field: monitoringField, from, to }),
      sort_by: monitoringField,
      history_mode: "bounded_range",
      from,
      to,
    },
    history: { mode: "bounded_range", from, to, max_items: maxItems },
    watermark: { before: optionalString(monitoring.watermark_after), after: null, overlap_hours: OVERLAP_HOURS },
    source_item_ids: [],
    current_stage: "monitor_setup",
    stage_state: "running",
    agent_id: optionalString(workflow.agent_id) ?? "",
    runtime_profile_id: optionalString(workflow.runtime_profile_id) ?? "",
    checkpoint_ids: [],
    synthesis_run_id: null,
    artifact_ids: [],
    partial: false,
    monitoring_active: monitoring.active === true,
    idempotency: { key: idempotencyKey, fingerprint },
  };
}

function historyCoverage(value: unknown): Array<{ from: string; to: string; operation_id: string; status: "pending" | "completed" | "partial" }> {
  const raw = objectValue(value).coverage_ranges;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    const row = objectValue(item);
    const from = optionalString(row.from);
    const to = optionalString(row.to);
    const operationId = optionalString(row.operation_id);
    const status = optionalString(row.status);
    if (!from || !to || !operationId || !["pending", "completed", "partial"].includes(status ?? "")) return [];
    return [{ from, to, operation_id: operationId, status: status as "pending" | "completed" | "partial" }];
  });
}

function withOperationCoverageStatus(
  state: ResearchOperationState,
  operationId: string,
  status: "completed" | "partial",
): ResearchOperationState {
  const ranges = state.coverage_ranges ?? [];
  const matching = ranges.some((range) => range.operation_id === operationId);
  return {
    ...state,
    coverage_ranges: matching
      ? ranges.map((range) => range.operation_id === operationId ? { ...range, status } : range)
      : state.history.from && state.history.to
        ? [...ranges, { from: state.history.from, to: state.history.to, operation_id: operationId, status }]
        : ranges,
  };
}

type SynthesisResultInspection =
  | { kind: "legacy" }
  | { kind: "succeeded" }
  | { kind: "rejected"; rejection: ResearchSynthesisRejection }
  | { kind: "invalid"; message: string };

type CritiqueIssue = NonNullable<ResearchOperationState["synthesis_critique"]>["issues"][number];
type CritiqueResult = { verdict: "pass" | "revise"; issues: CritiqueIssue[] };

function critiqueResult(value: unknown): CritiqueResult | null {
  const output = objectValue(value);
  const verdict = optionalString(output.verdict);
  if (verdict !== "pass" && verdict !== "revise") return null;
  if (!Array.isArray(output.issues)) return null;
  const issues: CritiqueIssue[] = [];
  for (const item of output.issues) {
    const issue = objectValue(item);
    const severity = optionalString(issue.severity);
    const kind = optionalString(issue.kind);
    const detail = optionalString(issue.detail);
    if (!severity || !["critical", "major", "minor"].includes(severity)
      || !kind || !["cherry_picking", "missing_contradiction", "unsupported_claim", "alternative_explanation", "overreach"].includes(kind)
      || !detail || !Array.isArray(issue.affected_refs)) return null;
    const affectedRefs = stringArray(issue.affected_refs);
    if (affectedRefs.some((ref) => !/^ref-[0-9]+$/.test(ref))) return null;
    issues.push({
      severity: severity as CritiqueIssue["severity"],
      kind: kind as CritiqueIssue["kind"],
      detail,
      affected_refs: affectedRefs,
    });
  }
  return { verdict, issues };
}

function critiqueCorpusSummary(report: Record<string, unknown>): string {
  const sources = Array.isArray(report.sources) ? report.sources : [];
  const titles = sources.map((source) => optionalString(objectValue(source).title)).filter((title): title is string => Boolean(title));
  return `${sources.length} report sources; ${titles.slice(0, 20).join(" | ") || "no titled sources"}`;
}

function appendCritiqueLimitations(value: unknown, issues: CritiqueIssue[], unresolvedCritical: boolean): string[] {
  const limitations = stringArray(value);
  for (const issue of issues) {
    const prefix = issue.severity === "critical" && unresolvedCritical ? "[unresolved critique] " : "[critique] ";
    const refs = issue.affected_refs.length ? ` (${issue.affected_refs.join(", ")})` : "";
    const line = `${prefix}${issue.kind}: ${issue.detail}${refs}`;
    if (!limitations.includes(line)) limitations.push(line);
  }
  return limitations;
}

function inspectSynthesisResult(value: unknown): SynthesisResultInspection | null {
  const output = objectValue(value);
  if (!Object.hasOwn(output, "status")) return { kind: "legacy" };
  if (output.status === "succeeded") {
    if (output.rejection !== null) return { kind: "invalid", message: "Synthesis output with status succeeded must set rejection to null" };
    return { kind: "succeeded" };
  }
  if (output.status !== "rejected") return { kind: "invalid", message: "Synthesis output status must be succeeded or rejected" };
  if (!Array.isArray(output.artifacts) || output.artifacts.length > 0) return { kind: "invalid", message: "Synthesis output with status rejected must contain an empty artifacts array" };
  const rejection = synthesisRejectionFromOutput(output);
  if (!rejection) return { kind: "invalid", message: "Synthesis output with status rejected must contain a valid rejection object" };
  return { kind: "rejected", rejection };
}

function synthesisRejectionFromOutput(output: Record<string, unknown>): ResearchSynthesisRejection | null {
  if (output.status !== "rejected") return null;
  const rejection = objectValue(output.rejection);
  const code = optionalString(rejection.code);
  const message = optionalString(rejection.message);
  const reason = optionalString(rejection.reason);
  const suggestions = stringArray(rejection.suggestions);
  if (!code || !RESEARCH_SYNTHESIS_REJECTION_CODES.includes(code as ResearchSynthesisRejection["code"]) || !message || !reason || suggestions.length === 0) return null;
  return { code: code as ResearchSynthesisRejection["code"], message, reason, suggestions };
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function researchQueryText(state: ResearchOperationState): string {
  return state.research_question || "approved research corpus";
}

function unique(values: string[]): string[] { return [...new Set(values)]; }

function fingerprintOf(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(canonical(value))).digest("hex");
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]));
  return value;
}
