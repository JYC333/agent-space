import { pgTable, index, uniqueIndex, unique, check, foreignKey, varchar, text, integer, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { agents } from "./agents";
import { users } from "./auth";
import { spaces } from "./spaces";
import { workspaces } from "./workspaces";
import { projects } from "./projects";

export const sessions = pgTable("sessions", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	userId: varchar("user_id", { length: 36 }),
	agentId: varchar("agent_id", { length: 36 }),
	workspaceId: varchar("workspace_id", { length: 36 }),
	projectId:varchar("project_id",{length:36}),
	title: varchar({ length: 512 }),
	status: varchar({ length: 32 }).notNull(),
	metadataJson: jsonb("metadata_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_sessions_agent_id").using("btree", table.agentId.asc().nullsLast()),
	index("ix_sessions_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_sessions_status").using("btree", table.status.asc().nullsLast()),
	index("ix_sessions_user_id").using("btree", table.userId.asc().nullsLast()),
	index("ix_sessions_workspace_id").using("btree", table.workspaceId.asc().nullsLast()),
	index("ix_sessions_project_id").on(table.projectId),
	foreignKey({
			columns: [table.agentId],
			foreignColumns: [agents.id],
			name: "sessions_agent_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "sessions_space_id_fkey"
		}),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "sessions_user_id_fkey"
		}),
	foreignKey({
			columns: [table.workspaceId, table.spaceId],
		foreignColumns: [workspaces.id, workspaces.spaceId],
			name: "sessions_workspace_id_fkey"
	}),
	foreignKey({columns:[table.projectId,table.spaceId],foreignColumns:[projects.id,projects.spaceId],name:"sessions_project_id_fkey"}),
]);

export const messages = pgTable("messages", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	sessionId: varchar("session_id", { length: 36 }).notNull(),
	userId: varchar("user_id", { length: 36 }),
	role: varchar({ length: 32 }).notNull(),
	content: text().notNull(),
	metadataJson: jsonb("metadata_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_messages_session_id").using("btree", table.sessionId.asc().nullsLast()),
	index("ix_messages_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_messages_user_id").using("btree", table.userId.asc().nullsLast()),
	foreignKey({
			columns: [table.sessionId],
			foreignColumns: [sessions.id],
			name: "messages_session_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "messages_space_id_fkey"
		}),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "messages_user_id_fkey"
		}),
	check("ck_messages_role", sql`(role)::text = ANY (ARRAY[('user'::character varying)::text, ('assistant'::character varying)::text, ('system'::character varying)::text, ('tool'::character varying)::text])`),
]);

export const sessionSummaries = pgTable("session_summaries", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	sessionId: varchar("session_id", { length: 36 }).notNull(),
	userId: varchar("user_id", { length: 36 }),
	version: integer().notNull(),
	status: varchar({ length: 32 }).notNull(),
	summaryText: text("summary_text").notNull(),
	sourceMessageCount: integer("source_message_count").notNull(),
	sourceFirstMessageId: varchar("source_first_message_id", { length: 36 }),
	sourceLastMessageId: varchar("source_last_message_id", { length: 36 }),
	summaryJson: jsonb("summary_json"),
	tokenEstimateBefore: integer("token_estimate_before"),
	tokenEstimateAfter: integer("token_estimate_after"),
	condenserVersion: varchar("condenser_version", { length: 64 }).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	uniqueIndex("ix_session_summaries_one_active_per_session").using("btree", table.sessionId.asc().nullsLast()).where(sql`((status)::text = 'active'::text)`),
	index("ix_session_summaries_session_id").using("btree", table.sessionId.asc().nullsLast()),
	index("ix_session_summaries_session_status").using("btree", table.sessionId.asc().nullsLast(), table.status.asc().nullsLast()),
	index("ix_session_summaries_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_session_summaries_space_session_status").using("btree", table.spaceId.asc().nullsLast(), table.sessionId.asc().nullsLast(), table.status.asc().nullsLast()),
	index("ix_session_summaries_status").using("btree", table.status.asc().nullsLast()),
	index("ix_session_summaries_user_id").using("btree", table.userId.asc().nullsLast()),
	foreignKey({
			columns: [table.sourceFirstMessageId],
			foreignColumns: [messages.id],
			name: "fk_session_summaries_source_first_message_id_messages"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.sourceLastMessageId],
			foreignColumns: [messages.id],
			name: "fk_session_summaries_source_last_message_id_messages"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.sessionId],
			foreignColumns: [sessions.id],
			name: "session_summaries_session_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "session_summaries_space_id_fkey"
		}),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [users.id],
			name: "session_summaries_user_id_fkey"
		}),
	unique("uq_session_summaries_session_version").on(table.sessionId, table.version),
	check("ck_session_summaries_status", sql`(status)::text = ANY (ARRAY[('active'::character varying)::text, ('superseded'::character varying)::text])`),
]);
