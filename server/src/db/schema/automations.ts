import { pgTable, index, check, foreignKey, varchar, text, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { agents } from "./agents";
import { users } from "./auth";
import { runs } from "./runs";
import { spaces } from "./spaces";
import { workspaces } from "./workspaces";
import { projects } from "./projects";

export const automations = pgTable("automations", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	ownerUserId: varchar("owner_user_id", { length: 36 }).notNull(),
	agentId: varchar("agent_id", { length: 36 }).notNull(),
	workspaceId: varchar("workspace_id", { length: 36 }),
	projectId: varchar("project_id", { length: 36 }),
	name: varchar({ length: 256 }).notNull(),
	description: text(),
	triggerType: varchar("trigger_type", { length: 64 }).default('manual').notNull(),
	status: varchar({ length: 32 }).default('active').notNull(),
	preflightSnapshotJson: jsonb("preflight_snapshot_json"),
	configJson: jsonb("config_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_automations_agent_id").using("btree", table.agentId.asc().nullsLast()),
	index("ix_automations_owner_user_id").using("btree", table.ownerUserId.asc().nullsLast()),
	index("ix_automations_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_automations_space_project").using("btree", table.spaceId.asc().nullsLast(), table.projectId.asc().nullsLast()),
	index("ix_automations_status").using("btree", table.status.asc().nullsLast()),
	index("ix_automations_workspace_id").using("btree", table.workspaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.agentId],
			foreignColumns: [agents.id],
			name: "automations_agent_id_fkey"
		}),
	foreignKey({
			columns: [table.ownerUserId],
			foreignColumns: [users.id],
			name: "automations_owner_user_id_fkey"
		}),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "automations_project_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "automations_space_id_fkey"
		}),
	foreignKey({
			columns: [table.workspaceId, table.spaceId],
			foreignColumns: [workspaces.id, workspaces.spaceId],
			name: "automations_workspace_id_fkey"
		}),
	check("ck_automations_status", sql`(status)::text = ANY (ARRAY[('active'::character varying)::text, ('paused'::character varying)::text, ('archived'::character varying)::text])`),
	check("ck_automations_trigger_type", sql`(trigger_type)::text = ANY (ARRAY[('manual'::character varying)::text, ('schedule'::character varying)::text])`),
]);

export const automationCredentialGrants = pgTable("automation_credential_grants", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	automationId: varchar("automation_id", { length: 36 }).notNull(),
	grantedByUserId: varchar("granted_by_user_id", { length: 36 }).notNull(),
	status: varchar({ length: 32 }).default('active').notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	revokedAt: timestamp("revoked_at", { withTimezone: true, mode: 'string' }),
	revokedByUserId: varchar("revoked_by_user_id", { length: 36 }),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_automation_credential_grants_automation_id").using("btree", table.automationId.asc().nullsLast()),
	index("ix_automation_credential_grants_granted_by_user_id").using("btree", table.grantedByUserId.asc().nullsLast()),
	index("ix_automation_credential_grants_lookup").using("btree", table.spaceId.asc().nullsLast(), table.automationId.asc().nullsLast(), table.status.asc().nullsLast()),
	index("ix_automation_credential_grants_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_automation_credential_grants_status").using("btree", table.status.asc().nullsLast()),
	foreignKey({
			columns: [table.automationId],
			foreignColumns: [automations.id],
			name: "automation_credential_grants_automation_id_fkey"
		}),
	foreignKey({
			columns: [table.grantedByUserId],
			foreignColumns: [users.id],
			name: "automation_credential_grants_granted_by_user_id_fkey"
		}),
	foreignKey({
			columns: [table.revokedByUserId],
			foreignColumns: [users.id],
			name: "automation_credential_grants_revoked_by_user_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "automation_credential_grants_space_id_fkey"
		}),
	check("ck_automation_credential_grants_status", sql`(status)::text = ANY (ARRAY[('active'::character varying)::text, ('revoked'::character varying)::text])`),
]);

export const automationRuns = pgTable("automation_runs", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	automationId: varchar("automation_id", { length: 36 }).notNull(),
	runId: varchar("run_id", { length: 36 }).notNull(),
	triggeredByUserId: varchar("triggered_by_user_id", { length: 36 }),
	triggerType: varchar("trigger_type", { length: 64 }).default('manual').notNull(),
	preflightSnapshotJson: jsonb("preflight_snapshot_json"),
	triggerContextJson: jsonb("trigger_context_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_automation_runs_automation_created").using("btree", table.automationId.asc().nullsLast(), table.createdAt.asc().nullsLast()),
	index("ix_automation_runs_automation_id").using("btree", table.automationId.asc().nullsLast()),
	index("ix_automation_runs_run_id").using("btree", table.runId.asc().nullsLast()),
	index("ix_automation_runs_triggered_by_user_id").using("btree", table.triggeredByUserId.asc().nullsLast()),
	foreignKey({
			columns: [table.automationId],
			foreignColumns: [automations.id],
			name: "automation_runs_automation_id_fkey"
		}),
	foreignKey({
			columns: [table.runId],
			foreignColumns: [runs.id],
			name: "automation_runs_run_id_fkey"
		}),
	foreignKey({
			columns: [table.triggeredByUserId],
			foreignColumns: [users.id],
			name: "automation_runs_triggered_by_user_id_fkey"
		}),
]);
