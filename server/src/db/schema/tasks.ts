import { pgTable, index, unique, check, foreignKey, varchar, text, integer, boolean, doublePrecision, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { agents } from "./agents";
import { activityRecords } from "./activity";
import { users } from "./auth";
import { runs } from "./runs";
import { spaces } from "./spaces";
import { workspaces } from "./workspaces";
import { artifacts } from "./artifacts";
import { proposals } from "./proposals";
import { projects } from "./projects";

export const boards = pgTable("boards", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	workspaceId: varchar("workspace_id", { length: 36 }),
	projectId: varchar("project_id", { length: 36 }),
	name: varchar({ length: 512 }).notNull(),
	description: text(),
	boardType: varchar("board_type", { length: 64 }).default('workspace').notNull(),
	status: varchar({ length: 32 }).default('active').notNull(),
	defaultView: varchar("default_view", { length: 64 }),
	sortOrder: integer("sort_order"),
	metadataJson: jsonb("metadata_json"),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	createdByAgentId: varchar("created_by_agent_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
	deletedAt: timestamp("deleted_at", { withTimezone: true, mode: 'string' }),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_boards_project_id").using("btree", table.projectId.asc().nullsLast()),
	index("ix_boards_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_boards_workspace_id").using("btree", table.workspaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.createdByAgentId],
			foreignColumns: [agents.id],
			name: "boards_created_by_agent_id_fkey"
		}),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "boards_created_by_user_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "boards_space_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.workspaceId],
			foreignColumns: [workspaces.id, workspaces.spaceId],
			name: "boards_workspace_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.projectId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "boards_project_id_fkey"
		}).onDelete("set null"),
]);

export const boardColumns = pgTable("board_columns", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	boardId: varchar("board_id", { length: 36 }).notNull(),
	name: varchar({ length: 256 }).notNull(),
	description: text(),
	statusKey: varchar("status_key", { length: 64 }).notNull(),
	position: integer().default(0).notNull(),
	wipLimit: integer("wip_limit"),
	isDoneColumn: boolean("is_done_column").default(false).notNull(),
	isDefaultColumn: boolean("is_default_column").default(false).notNull(),
	metadataJson: jsonb("metadata_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
	deletedAt: timestamp("deleted_at", { withTimezone: true, mode: 'string' }),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_board_columns_board_id").using("btree", table.boardId.asc().nullsLast()),
	index("ix_board_columns_space_id").using("btree", table.spaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.boardId],
			foreignColumns: [boards.id],
			name: "board_columns_board_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "board_columns_space_id_fkey"
		}),
]);

export const tasks = pgTable("tasks", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	workspaceId: varchar("workspace_id", { length: 36 }),
	projectId: varchar("project_id", { length: 36 }),
	boardId: varchar("board_id", { length: 36 }),
	columnId: varchar("column_id", { length: 36 }),
	parentTaskId: varchar("parent_task_id", { length: 36 }),
	title: varchar({ length: 512 }).notNull(),
	description: text(),
	taskType: varchar("task_type", { length: 64 }).default('general').notNull(),
	status: varchar({ length: 64 }).default('inbox').notNull(),
	priority: varchar({ length: 32 }).default('normal').notNull(),
	riskLevel: varchar("risk_level", { length: 32 }).default('low').notNull(),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	createdByAgentId: varchar("created_by_agent_id", { length: 36 }),
	assignedUserId: varchar("assigned_user_id", { length: 36 }),
	assignedAgentId: varchar("assigned_agent_id", { length: 36 }),
	claimedByUserId: varchar("claimed_by_user_id", { length: 36 }),
	claimedByAgentId: varchar("claimed_by_agent_id", { length: 36 }),
	sourceActivityId: varchar("source_activity_id", { length: 36 }),
	sourceRunId: varchar("source_run_id", { length: 36 }),
	sourceProposalId: varchar("source_proposal_id", { length: 36 }),
	sourceArtifactId: varchar("source_artifact_id", { length: 36 }),
	acceptanceCriteriaJson: jsonb("acceptance_criteria_json"),
	definitionOfDone: text("definition_of_done"),
	requiredOutputsJson: jsonb("required_outputs_json"),
	dueAt: timestamp("due_at", { withTimezone: true, mode: 'string' }),
	startAfter: timestamp("start_after", { withTimezone: true, mode: 'string' }),
	completedAt: timestamp("completed_at", { withTimezone: true, mode: 'string' }),
	cancelledAt: timestamp("cancelled_at", { withTimezone: true, mode: 'string' }),
	blockedReason: text("blocked_reason"),
	estimatedEffort: varchar("estimated_effort", { length: 64 }),
	actualEffort: varchar("actual_effort", { length: 64 }),
	maxRuns: integer("max_runs"),
	maxCost: doublePrecision("max_cost"),
	maxDurationSeconds: integer("max_duration_seconds"),
	policyJson: jsonb("policy_json"),
	metadataJson: jsonb("metadata_json"),
	tags: jsonb(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
	deletedAt: timestamp("deleted_at", { withTimezone: true, mode: 'string' }),
	visibility: varchar({ length: 32 }).default('space_shared').notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_tasks_board_id").using("btree", table.boardId.asc().nullsLast()),
	index("ix_tasks_column_id").using("btree", table.columnId.asc().nullsLast()),
	index("ix_tasks_parent_task_id").using("btree", table.parentTaskId.asc().nullsLast()),
	index("ix_tasks_project_id").using("btree", table.projectId.asc().nullsLast()),
	index("ix_tasks_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_tasks_workspace_id").using("btree", table.workspaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.assignedAgentId],
			foreignColumns: [agents.id],
			name: "tasks_assigned_agent_id_fkey"
		}),
	foreignKey({
			columns: [table.assignedUserId],
			foreignColumns: [users.id],
			name: "tasks_assigned_user_id_fkey"
		}),
	foreignKey({
			columns: [table.boardId],
			foreignColumns: [boards.id],
			name: "tasks_board_id_fkey"
		}),
	foreignKey({
			columns: [table.claimedByAgentId],
			foreignColumns: [agents.id],
			name: "tasks_claimed_by_agent_id_fkey"
		}),
	foreignKey({
			columns: [table.claimedByUserId],
			foreignColumns: [users.id],
			name: "tasks_claimed_by_user_id_fkey"
		}),
	foreignKey({
			columns: [table.columnId],
			foreignColumns: [boardColumns.id],
			name: "tasks_column_id_fkey"
		}),
	foreignKey({
			columns: [table.createdByAgentId],
			foreignColumns: [agents.id],
			name: "tasks_created_by_agent_id_fkey"
		}),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "tasks_created_by_user_id_fkey"
		}),
	foreignKey({
			columns: [table.parentTaskId],
			foreignColumns: [table.id],
			name: "tasks_parent_task_id_fkey"
		}),
	foreignKey({
			columns: [table.sourceActivityId],
			foreignColumns: [activityRecords.id],
			name: "tasks_source_activity_id_fkey"
		}),
	foreignKey({
			columns: [table.sourceArtifactId],
			foreignColumns: [artifacts.id],
			name: "tasks_source_artifact_id_fkey"
		}),
	foreignKey({
			columns: [table.sourceProposalId],
			foreignColumns: [proposals.id],
			name: "tasks_source_proposal_id_fkey"
		}),
	foreignKey({
			columns: [table.sourceRunId],
			foreignColumns: [runs.id],
			name: "tasks_source_run_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "tasks_space_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.workspaceId],
			foreignColumns: [workspaces.id, workspaces.spaceId],
			name: "tasks_workspace_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.projectId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "tasks_project_id_fkey"
		}).onDelete("set null"),
]);

export const taskArtifacts = pgTable("task_artifacts", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	taskId: varchar("task_id", { length: 36 }).notNull(),
	artifactId: varchar("artifact_id", { length: 36 }).notNull(),
	runId: varchar("run_id", { length: 36 }),
	role: varchar({ length: 32 }).default('output').notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_task_artifacts_artifact_id").using("btree", table.artifactId.asc().nullsLast()),
	index("ix_task_artifacts_run_id").using("btree", table.runId.asc().nullsLast()),
	index("ix_task_artifacts_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_task_artifacts_task_id").using("btree", table.taskId.asc().nullsLast()),
	foreignKey({
			columns: [table.artifactId],
			foreignColumns: [artifacts.id],
			name: "task_artifacts_artifact_id_fkey"
		}),
	foreignKey({
			columns: [table.runId],
			foreignColumns: [runs.id],
			name: "task_artifacts_run_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "task_artifacts_space_id_fkey"
		}),
	foreignKey({
			columns: [table.taskId],
			foreignColumns: [tasks.id],
			name: "task_artifacts_task_id_fkey"
		}),
	unique("uq_task_artifacts_task_artifact").on(table.artifactId, table.taskId),
]);

export const taskDependencies = pgTable("task_dependencies", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	taskId: varchar("task_id", { length: 36 }).notNull(),
	dependsOnTaskId: varchar("depends_on_task_id", { length: 36 }).notNull(),
	dependencyType: varchar("dependency_type", { length: 32 }).default('requires').notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_task_dependencies_depends_on_task_id").using("btree", table.dependsOnTaskId.asc().nullsLast()),
	index("ix_task_dependencies_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_task_dependencies_task_id").using("btree", table.taskId.asc().nullsLast()),
	foreignKey({
			columns: [table.dependsOnTaskId],
			foreignColumns: [tasks.id],
			name: "task_dependencies_depends_on_task_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "task_dependencies_space_id_fkey"
		}),
	foreignKey({
			columns: [table.taskId],
			foreignColumns: [tasks.id],
			name: "task_dependencies_task_id_fkey"
		}),
	unique("uq_task_dependencies_task_depends").on(table.dependsOnTaskId, table.taskId),
]);

export const taskProposals = pgTable("task_proposals", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	taskId: varchar("task_id", { length: 36 }).notNull(),
	proposalId: varchar("proposal_id", { length: 36 }).notNull(),
	role: varchar({ length: 32 }).default('main_change').notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_task_proposals_proposal_id").using("btree", table.proposalId.asc().nullsLast()),
	index("ix_task_proposals_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_task_proposals_task_id").using("btree", table.taskId.asc().nullsLast()),
	foreignKey({
			columns: [table.proposalId],
			foreignColumns: [proposals.id],
			name: "task_proposals_proposal_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "task_proposals_space_id_fkey"
		}),
	foreignKey({
			columns: [table.taskId],
			foreignColumns: [tasks.id],
			name: "task_proposals_task_id_fkey"
		}),
	unique("uq_task_proposals_task_proposal").on(table.proposalId, table.taskId),
]);

export const validationRecipes = pgTable("validation_recipes", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	workspaceId: varchar("workspace_id", { length: 36 }),
	name: varchar({ length: 256 }).notNull(),
	taskType: varchar("task_type", { length: 64 }),
	riskLevel: varchar("risk_level", { length: 32 }).default('low').notNull(),
	commandsJson: jsonb("commands_json").notNull(),
	requiredChecksJson: jsonb("required_checks_json").notNull(),
	artifactExpectationsJson: jsonb("artifact_expectations_json"),
	timeoutSeconds: integer("timeout_seconds"),
	requiresCleanGitState: boolean("requires_clean_git_state").default(false).notNull(),
	enabled: boolean().default(true).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_validation_recipes_enabled").using("btree", table.enabled.asc().nullsLast()),
	index("ix_validation_recipes_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_validation_recipes_task_type").using("btree", table.taskType.asc().nullsLast()),
	index("ix_validation_recipes_workspace_id").using("btree", table.workspaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "validation_recipes_space_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.workspaceId],
			foreignColumns: [workspaces.id, workspaces.spaceId],
			name: "validation_recipes_workspace_id_fkey"
		}),
	check("ck_validation_recipes_risk_level", sql`(risk_level)::text = ANY (ARRAY[('low'::character varying)::text, ('medium'::character varying)::text, ('high'::character varying)::text])`),
]);
