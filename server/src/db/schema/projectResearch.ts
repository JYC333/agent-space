import { pgTable, index, uniqueIndex, unique, check, foreignKey, varchar, text, jsonb, boolean, integer, doublePrecision, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { users } from "./auth";
import { runs } from "./runs";
import { artifacts } from "./artifacts";
import { projects } from "./projects";
import { spaces } from "./spaces";
import { claims } from "./knowledge";
import { workspaces } from "./workspaces";

// Project-owned Academic Research workflow foundation. Runs/Artifacts/
// Proposals keep their existing authority boundaries — these tables only
// track workflow state, human checkpoints, and which Artifacts belong to
// which workflow stage.

export const projectResearchProfiles = pgTable("project_research_profiles", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	presetKey: varchar("preset_key", { length: 64 }).default('academic_research').notNull(),
	researchQuestion: text("research_question"),
	workingTitle: varchar("working_title", { length: 512 }),
	domain: varchar({ length: 128 }),
	outputType: varchar("output_type", { length: 32 }),
	paperType: varchar("paper_type", { length: 32 }),
	citationStyle: varchar("citation_style", { length: 32 }),
	targetVenue: varchar("target_venue", { length: 256 }),
	language: varchar({ length: 16 }).default('en').notNull(),
	experimentIntakeDeclaration: varchar("experiment_intake_declaration", { length: 32 }).default('undecided').notNull(),
	status: varchar({ length: 16 }).default('draft').notNull(),
	approvedByUserId: varchar("approved_by_user_id", { length: 36 }),
	approvedAt: timestamp("approved_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_research_profiles_space_id").using("btree", table.spaceId.asc().nullsLast()),
	uniqueIndex("uq_project_research_profiles_project").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast()),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_research_profiles_project_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_research_profiles_space_id_fkey"
		}),
	foreignKey({
			columns: [table.approvedByUserId],
			foreignColumns: [users.id],
			name: "project_research_profiles_approved_by_user_id_fkey"
		}).onDelete("set null"),
	check("ck_project_research_profiles_status", sql`(status)::text = ANY (ARRAY[('draft'::character varying)::text, ('approved'::character varying)::text, ('archived'::character varying)::text])`),
	check("ck_project_research_profiles_output_type", sql`(output_type IS NULL) OR ((output_type)::text = ANY (ARRAY[('paper'::character varying)::text, ('thesis'::character varying)::text, ('report'::character varying)::text, ('review'::character varying)::text, ('proposal'::character varying)::text, ('other'::character varying)::text]))`),
	check("ck_project_research_profiles_paper_type", sql`(paper_type IS NULL) OR ((paper_type)::text = ANY (ARRAY[('empirical'::character varying)::text, ('theory'::character varying)::text, ('survey'::character varying)::text, ('review'::character varying)::text, ('position'::character varying)::text, ('case_study'::character varying)::text, ('other'::character varying)::text]))`),
	check("ck_project_research_profiles_citation_style", sql`(citation_style IS NULL) OR ((citation_style)::text = ANY (ARRAY[('apa'::character varying)::text, ('mla'::character varying)::text, ('chicago'::character varying)::text, ('ieee'::character varying)::text, ('acm'::character varying)::text, ('vancouver'::character varying)::text, ('other'::character varying)::text]))`),
	check("ck_project_research_profiles_experiment_intake", sql`(experiment_intake_declaration)::text = ANY (ARRAY[('none'::character varying)::text, ('code_experiments'::character varying)::text, ('human_study'::character varying)::text, ('both'::character varying)::text, ('undecided'::character varying)::text])`),
]);

export const projectResearchWorkflows = pgTable("project_research_workflows", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	workflowType: varchar("workflow_type", { length: 32 }).notNull(),
	currentStage: varchar("current_stage", { length: 64 }),
	status: varchar({ length: 16 }).default('active').notNull(),
	mode: varchar({ length: 16 }).default('manual').notNull(),
	stateJson: jsonb("state_json").default({}).notNull(),
	startedByUserId: varchar("started_by_user_id", { length: 36 }),
	startedRunId: varchar("started_run_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_research_workflows_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_research_workflows_project_status").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast(), table.status.asc().nullsLast()),
	unique("uq_project_research_workflows_id_space_id").on(table.id, table.spaceId),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_research_workflows_project_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_research_workflows_space_id_fkey"
		}),
	foreignKey({
			columns: [table.startedByUserId],
			foreignColumns: [users.id],
			name: "project_research_workflows_started_by_user_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.startedRunId],
			foreignColumns: [runs.id],
			name: "project_research_workflows_started_run_id_fkey"
		}).onDelete("set null"),
	check("ck_project_research_workflows_workflow_type", sql`(workflow_type)::text = ANY (ARRAY[('literature_review'::character varying)::text, ('empirical_paper'::character varying)::text, ('theory_paper'::character varying)::text, ('paper_review'::character varying)::text, ('revision'::character varying)::text])`),
	check("ck_project_research_workflows_status", sql`(status)::text = ANY (ARRAY[('not_started'::character varying)::text, ('active'::character varying)::text, ('paused'::character varying)::text, ('completed'::character varying)::text, ('archived'::character varying)::text])`),
	check("ck_project_research_workflows_mode", sql`(mode)::text = ANY (ARRAY[('manual'::character varying)::text, ('agent_assisted'::character varying)::text, ('autonomous'::character varying)::text])`),
	check("ck_project_research_workflows_state_object", sql`jsonb_typeof(state_json) = 'object'::text`),
]);

export const projectResearchCheckpoints = pgTable("project_research_checkpoints", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	workflowId: varchar("workflow_id", { length: 36 }).notNull(),
	stageKey: varchar("stage_key", { length: 64 }).notNull(),
	checkpointType: varchar("checkpoint_type", { length: 32 }).notNull(),
	status: varchar({ length: 16 }).default('pending').notNull(),
	machineResultJson: jsonb("machine_result_json"),
	userDecision: varchar("user_decision", { length: 16 }),
	decisionReason: text("decision_reason"),
	decidedByUserId: varchar("decided_by_user_id", { length: 36 }),
	decidedAt: timestamp("decided_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_research_checkpoints_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_research_checkpoints_project_id").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast()),
	index("ix_project_research_checkpoints_workflow_stage").using("btree", table.spaceId.asc().nullsLast(), table.workflowId.asc().nullsLast(), table.stageKey.asc().nullsLast()),
	index("ix_project_research_checkpoints_status").using("btree", table.spaceId.asc().nullsLast(), table.status.asc().nullsLast()),
	foreignKey({
			columns: [table.workflowId, table.spaceId],
			foreignColumns: [projectResearchWorkflows.id, projectResearchWorkflows.spaceId],
			name: "project_research_checkpoints_workflow_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_research_checkpoints_project_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_research_checkpoints_space_id_fkey"
		}),
	foreignKey({
			columns: [table.decidedByUserId],
			foreignColumns: [users.id],
			name: "project_research_checkpoints_decided_by_user_id_fkey"
		}).onDelete("set null"),
	check("ck_project_research_checkpoints_checkpoint_type", sql`(checkpoint_type)::text = ANY (ARRAY[('profile_approval'::character varying)::text, ('screening_gate'::character varying)::text, ('integrity_gate'::character varying)::text, ('manuscript_gate'::character varying)::text, ('review_gate'::character varying)::text, ('other'::character varying)::text])`),
	check("ck_project_research_checkpoints_status", sql`(status)::text = ANY (ARRAY[('pending'::character varying)::text, ('approved'::character varying)::text, ('rejected'::character varying)::text, ('waived'::character varying)::text])`),
	check("ck_project_research_checkpoints_user_decision", sql`(user_decision IS NULL) OR ((user_decision)::text = ANY (ARRAY[('approved'::character varying)::text, ('rejected'::character varying)::text, ('waived'::character varying)::text]))`),
]);

export const projectResearchArtifactLinks = pgTable("project_research_artifact_links", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	workflowId: varchar("workflow_id", { length: 36 }),
	stageKey: varchar("stage_key", { length: 64 }),
	artifactId: varchar("artifact_id", { length: 36 }).notNull(),
	artifactType: varchar("artifact_type", { length: 32 }).notNull(),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	createdByRunId: varchar("created_by_run_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_research_artifact_links_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_research_artifact_links_project_type").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast(), table.artifactType.asc().nullsLast()),
	index("ix_project_research_artifact_links_workflow_id").using("btree", table.workflowId.asc().nullsLast()),
	index("ix_project_research_artifact_links_artifact_id").using("btree", table.artifactId.asc().nullsLast()),
	// Single-column FK (not composite with space_id): a composite FK's
	// ON DELETE SET NULL nulls every column in the FK, which would also null
	// the NOT NULL space_id column. workflow_id (the workflow's PK) is
	// already globally unique, so this loses no referential integrity.
	foreignKey({
			columns: [table.workflowId],
			foreignColumns: [projectResearchWorkflows.id],
			name: "project_research_artifact_links_workflow_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_research_artifact_links_project_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.artifactId],
			foreignColumns: [artifacts.id],
			name: "project_research_artifact_links_artifact_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_research_artifact_links_space_id_fkey"
		}),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "project_research_artifact_links_created_by_user_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.createdByRunId],
			foreignColumns: [runs.id],
			name: "project_research_artifact_links_created_by_run_id_fkey"
		}).onDelete("set null"),
	check("ck_project_research_artifact_links_artifact_type", sql`(artifact_type)::text = ANY (ARRAY[('rq_brief'::character varying)::text, ('methodology_blueprint'::character varying)::text, ('search_strategy'::character varying)::text, ('annotated_bibliography'::character varying)::text, ('literature_matrix'::character varying)::text, ('synthesis_report'::character varying)::text, ('integrity_report'::character varying)::text, ('outline'::character varying)::text, ('draft'::character varying)::text, ('review_package'::character varying)::text, ('revision_plan'::character varying)::text, ('final_export'::character varying)::text, ('process_summary'::character varying)::text])`),
]);

// Project-owned screening criteria (include/exclude keywords,
// methods, date range, venues/source types, required evidence fields) used
// to focus paper triage. One row per project; AI screening suggestions and
// the corpus/matrix read models consume this, but project_corpus_items.
// triage_status (gated by triage_confirmed_by_user) remains the durable,
// user-confirmed source of truth — this table never itself marks a paper
// included/excluded.
export const projectResearchScreeningCriteria = pgTable("project_research_screening_criteria", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	includeKeywordsJson: jsonb("include_keywords_json").default([]).notNull(),
	excludeKeywordsJson: jsonb("exclude_keywords_json").default([]).notNull(),
	methodsJson: jsonb("methods_json").default([]).notNull(),
	dateRangeStart: timestamp("date_range_start", { withTimezone: true, mode: 'string' }),
	dateRangeEnd: timestamp("date_range_end", { withTimezone: true, mode: 'string' }),
	venuesJson: jsonb("venues_json").default([]).notNull(),
	requiredEvidenceFieldsJson: jsonb("required_evidence_fields_json").default([]).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_research_screening_criteria_space_id").using("btree", table.spaceId.asc().nullsLast()),
	uniqueIndex("uq_project_research_screening_criteria_project").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast()),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_research_screening_criteria_project_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_research_screening_criteria_space_id_fkey"
		}),
	check("ck_project_research_screening_criteria_include_keywords_array", sql`jsonb_typeof(include_keywords_json) = 'array'::text`),
	check("ck_project_research_screening_criteria_exclude_keywords_array", sql`jsonb_typeof(exclude_keywords_json) = 'array'::text`),
	check("ck_project_research_screening_criteria_methods_array", sql`jsonb_typeof(methods_json) = 'array'::text`),
	check("ck_project_research_screening_criteria_venues_array", sql`jsonb_typeof(venues_json) = 'array'::text`),
	check("ck_project_research_screening_criteria_evidence_fields_array", sql`jsonb_typeof(required_evidence_fields_json) = 'array'::text`),
	check("ck_project_research_screening_criteria_date_range", sql`(date_range_start IS NULL) OR (date_range_end IS NULL) OR (date_range_start <= date_range_end)`),
]);

// Project-level claim intent records for the integrity gate. Claims
// themselves stay global and proposal-gated (see
// .agent/architecture/CLAIM_FACT_ATOM_MODEL.md) — this table never writes
// `claims` directly, it only links an already-canonical claim to this
// project's workflow with project-specific tracking (support status,
// planned experiment ids, citation anchors, unresolved-gap markers) that the
// integrity gate reads.
export const projectResearchClaimLinks = pgTable("project_research_claim_links", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	workflowId: varchar("workflow_id", { length: 36 }),
	claimId: varchar("claim_id", { length: 36 }).notNull(),
	supportStatus: varchar("support_status", { length: 32 }).default('unsupported').notNull(),
	plannedExperimentIdsJson: jsonb("planned_experiment_ids_json").default([]).notNull(),
	citationAnchorsJson: jsonb("citation_anchors_json").default([]).notNull(),
	unresolvedGap: boolean("unresolved_gap").default(false).notNull(),
	gapReason: text("gap_reason"),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_research_claim_links_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_research_claim_links_project_id").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast()),
	index("ix_project_research_claim_links_workflow_id").using("btree", table.workflowId.asc().nullsLast()),
	uniqueIndex("uq_project_research_claim_links_project_claim").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast(), table.claimId.asc().nullsLast()),
	foreignKey({
			columns: [table.claimId, table.spaceId],
			foreignColumns: [claims.objectId, claims.spaceId],
			name: "project_research_claim_links_claim_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_research_claim_links_project_id_fkey"
		}).onDelete("cascade"),
	// Single-column FK (see project_research_artifact_links.workflow_id):
	// composite (workflow_id, space_id) + ON DELETE SET NULL would null the
	// NOT NULL space_id column on delete.
	foreignKey({
			columns: [table.workflowId],
			foreignColumns: [projectResearchWorkflows.id],
			name: "project_research_claim_links_workflow_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_research_claim_links_space_id_fkey"
		}),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "project_research_claim_links_created_by_user_id_fkey"
		}).onDelete("set null"),
	check("ck_project_research_claim_links_support_status", sql`(support_status)::text = ANY (ARRAY[('unsupported'::character varying)::text, ('supported'::character varying)::text, ('partial'::character varying)::text, ('gap_declared'::character varying)::text])`),
	check("ck_project_research_claim_links_planned_experiment_ids_array", sql`jsonb_typeof(planned_experiment_ids_json) = 'array'::text`),
	check("ck_project_research_claim_links_citation_anchors_array", sql`jsonb_typeof(citation_anchors_json) = 'array'::text`),
]);

// Experiment Track Foundation. Data model only — campaigns/runs
// execute through existing Runs/Workspace sandboxing (a campaign run's
// run_id points at a normal `runs` row), not a parallel execution system.
// Editable/protected scope enforcement at patch-collection/proposal-apply
// time is deferred until a real code-patch loop is wired to campaigns.
export const projectExperimentCampaigns = pgTable("project_experiment_campaigns", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	workspaceId: varchar("workspace_id", { length: 36 }).notNull(),
	name: varchar({ length: 256 }).notNull(),
	researchQuestion: text("research_question"),
	hypothesisScope: text("hypothesis_scope"),
	status: varchar({ length: 16 }).default('draft').notNull(),
	editableScopeJson: jsonb("editable_scope_json").default([]).notNull(),
	protectedScopeJson: jsonb("protected_scope_json").default([]).notNull(),
	setupCommandsJson: jsonb("setup_commands_json").default([]).notNull(),
	runCommand: text("run_command"),
	metricParserJson: jsonb("metric_parser_json").default({}).notNull(),
	timeBudgetSeconds: integer("time_budget_seconds"),
	timeoutSeconds: integer("timeout_seconds"),
	resourceBudgetJson: jsonb("resource_budget_json").default({}).notNull(),
	baselineRunId: varchar("baseline_run_id", { length: 36 }),
	bestRunId: varchar("best_run_id", { length: 36 }),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_experiment_campaigns_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_experiment_campaigns_project_id").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast()),
	unique("uq_project_experiment_campaigns_id_space_id").on(table.id, table.spaceId),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_experiment_campaigns_project_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.workspaceId],
			foreignColumns: [workspaces.id],
			name: "project_experiment_campaigns_workspace_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_experiment_campaigns_space_id_fkey"
		}),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "project_experiment_campaigns_created_by_user_id_fkey"
		}).onDelete("set null"),
	// Single-column FKs (not composite with space_id): a composite FK's
	// ON DELETE SET NULL nulls every column in the FK, including the NOT
	// NULL space_id column — see project_research_artifact_links.workflow_id.
	foreignKey({
			columns: [table.baselineRunId],
			foreignColumns: [projectExperimentRuns.id],
			name: "project_experiment_campaigns_baseline_run_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.bestRunId],
			foreignColumns: [projectExperimentRuns.id],
			name: "project_experiment_campaigns_best_run_id_fkey"
		}).onDelete("set null"),
	check("ck_project_experiment_campaigns_status", sql`(status)::text = ANY (ARRAY[('draft'::character varying)::text, ('active'::character varying)::text, ('paused'::character varying)::text, ('completed'::character varying)::text, ('archived'::character varying)::text])`),
	check("ck_project_experiment_campaigns_editable_scope_array", sql`jsonb_typeof(editable_scope_json) = 'array'::text`),
	check("ck_project_experiment_campaigns_protected_scope_array", sql`jsonb_typeof(protected_scope_json) = 'array'::text`),
	check("ck_project_experiment_campaigns_setup_commands_array", sql`jsonb_typeof(setup_commands_json) = 'array'::text`),
]);

export const projectExperimentRuns = pgTable("project_experiment_runs", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	campaignId: varchar("campaign_id", { length: 36 }).notNull(),
	runId: varchar("run_id", { length: 36 }),
	workspaceId: varchar("workspace_id", { length: 36 }).notNull(),
	isBaseline: boolean("is_baseline").default(false).notNull(),
	hypothesis: text(),
	patchSummary: text("patch_summary"),
	commitRef: varchar("commit_ref", { length: 128 }),
	status: varchar({ length: 16 }).default('queued').notNull(),
	metricsJson: jsonb("metrics_json").default({}).notNull(),
	primaryMetricName: varchar("primary_metric_name", { length: 128 }),
	primaryMetricValue: doublePrecision("primary_metric_value"),
	decisionReason: text("decision_reason"),
	artifactIdsJson: jsonb("artifact_ids_json").default([]).notNull(),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_experiment_runs_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_experiment_runs_campaign_id").using("btree", table.spaceId.asc().nullsLast(), table.campaignId.asc().nullsLast()),
	unique("uq_project_experiment_runs_id_space_id").on(table.id, table.spaceId),
	foreignKey({
			columns: [table.campaignId, table.spaceId],
			foreignColumns: [projectExperimentCampaigns.id, projectExperimentCampaigns.spaceId],
			name: "project_experiment_runs_campaign_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.workspaceId],
			foreignColumns: [workspaces.id],
			name: "project_experiment_runs_workspace_id_fkey"
		}),
	foreignKey({
			columns: [table.runId],
			foreignColumns: [runs.id],
			name: "project_experiment_runs_run_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_experiment_runs_space_id_fkey"
		}),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "project_experiment_runs_created_by_user_id_fkey"
		}).onDelete("set null"),
	check("ck_project_experiment_runs_status", sql`(status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('keep'::character varying)::text, ('discard'::character varying)::text, ('crash'::character varying)::text, ('cancelled'::character varying)::text])`),
	check("ck_project_experiment_runs_metrics_object", sql`jsonb_typeof(metrics_json) = 'object'::text`),
	check("ck_project_experiment_runs_artifact_ids_array", sql`jsonb_typeof(artifact_ids_json) = 'array'::text`),
]);

export const projectExperimentProvenance = pgTable("project_experiment_provenance", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	campaignId: varchar("campaign_id", { length: 36 }),
	experimentKey: varchar("experiment_key", { length: 160 }).notNull(),
	plannedSummary: text("planned_summary"),
	executedSummary: text("executed_summary"),
	negativeResults: text("negative_results"),
	limitations: text(),
	reproLockJson: jsonb("repro_lock_json").default({}).notNull(),
	linkedArtifactIdsJson: jsonb("linked_artifact_ids_json").default([]).notNull(),
	linkedRunIdsJson: jsonb("linked_run_ids_json").default([]).notNull(),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_experiment_provenance_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_experiment_provenance_project_id").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast()),
	uniqueIndex("uq_project_experiment_provenance_project_key").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast(), table.experimentKey.asc().nullsLast()),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_experiment_provenance_project_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.campaignId],
			foreignColumns: [projectExperimentCampaigns.id],
			name: "project_experiment_provenance_campaign_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_experiment_provenance_space_id_fkey"
		}),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "project_experiment_provenance_created_by_user_id_fkey"
		}).onDelete("set null"),
	check("ck_project_experiment_provenance_linked_artifact_ids_array", sql`jsonb_typeof(linked_artifact_ids_json) = 'array'::text`),
	check("ck_project_experiment_provenance_linked_run_ids_array", sql`jsonb_typeof(linked_run_ids_json) = 'array'::text`),
]);
