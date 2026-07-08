import { pgTable, index, uniqueIndex, unique, check, foreignKey, varchar, text, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { users } from "./auth";
import { runs } from "./runs";
import { spaceMemberships, spaces } from "./spaces";

export const projects = pgTable("projects", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	ownerUserId: varchar("owner_user_id", { length: 36 }),
	name: varchar({ length: 256 }).notNull(),
	description: text(),
	status: varchar({ length: 32 }).notNull(),
	currentFocus: text("current_focus"),
	settingsJson: jsonb("settings_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
	archivedAt: timestamp("archived_at", { withTimezone: true, mode: 'string' }),
	deletedAt: timestamp("deleted_at", { withTimezone: true, mode: 'string' }),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_projects_owner_user_id").using("btree", table.ownerUserId.asc().nullsLast()),
	index("ix_projects_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_projects_status").using("btree", table.status.asc().nullsLast()),
	uniqueIndex("uq_projects_space_name_active").using("btree", table.spaceId.asc().nullsLast(), table.name.asc().nullsLast()).where(sql`((status)::text = 'active'::text)`),
	foreignKey({
			columns: [table.ownerUserId],
			foreignColumns: [users.id],
			name: "projects_owner_user_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "projects_space_id_fkey"
		}),
	unique("uq_projects_space_id_id").on(table.id, table.spaceId),
	check("ck_projects_status", sql`(status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text, ('deleted'::character varying)::text])`),
]);

export const projectPublicSummaries = pgTable("project_public_summaries", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	summaryText: text("summary_text").notNull(),
	topicsJson: jsonb("topics_json").default([]).notNull(),
	highlightsJson: jsonb("highlights_json").default([]).notNull(),
	sourceRefsJson: jsonb("source_refs_json").default([]).notNull(),
	redactionVersion: varchar("redaction_version", { length: 64 }).notNull(),
	reviewStatus: varchar("review_status", { length: 32 }).default('pending').notNull(),
	updatedByUserId: varchar("updated_by_user_id", { length: 36 }),
	generatedByRunId: varchar("generated_by_run_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	uniqueIndex("ix_project_public_summaries_project_unique").using("btree", table.projectId.asc().nullsLast()),
	index("ix_project_public_summaries_review_status").using("btree", table.reviewStatus.asc().nullsLast()),
	index("ix_project_public_summaries_space_id").using("btree", table.spaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.generatedByRunId],
			foreignColumns: [runs.id],
			name: "project_public_summaries_generated_by_run_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.spaceId, table.projectId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_public_summaries_space_project_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_public_summaries_space_id_fkey"
		}),
	foreignKey({
			columns: [table.updatedByUserId],
			foreignColumns: [users.id],
			name: "project_public_summaries_updated_by_user_id_fkey"
		}).onDelete("set null"),
	check("ck_project_public_summaries_highlights_array", sql`jsonb_typeof(highlights_json) = 'array'::text`),
	check("ck_project_public_summaries_review_status", sql`(review_status)::text = ANY (ARRAY[('draft'::character varying)::text, ('approved'::character varying)::text, ('archived'::character varying)::text])`),
	check("ck_project_public_summaries_source_refs_array", sql`jsonb_typeof(source_refs_json) = 'array'::text`),
	check("ck_project_public_summaries_topics_array", sql`jsonb_typeof(topics_json) = 'array'::text`),
]);

export const projectMembers = pgTable("project_members", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	userId: varchar("user_id", { length: 36 }).notNull(),
	role: varchar({ length: 32 }).notNull(),
	status: varchar({ length: 32 }).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	uniqueIndex("ix_project_members_project_user_unique").using("btree", table.projectId.asc().nullsLast(), table.userId.asc().nullsLast()),
	index("ix_project_members_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_members_user_id").using("btree", table.userId.asc().nullsLast()),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_members_space_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.projectId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_members_space_project_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "project_members_user_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.userId],
			foreignColumns: [spaceMemberships.spaceId, spaceMemberships.userId],
			name: "project_members_space_membership_fkey"
		}).onDelete("cascade"),
	check("ck_project_members_role", sql`(role)::text = ANY (ARRAY[('owner'::character varying)::text, ('member'::character varying)::text, ('viewer'::character varying)::text])`),
	check("ck_project_members_status", sql`(status)::text = ANY (ARRAY[('active'::character varying)::text, ('invited'::character varying)::text, ('revoked'::character varying)::text])`),
]);
