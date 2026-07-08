import { pgTable, index, check, foreignKey, varchar, text, boolean, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { users } from "./auth";
import { runs } from "./runs";
import { spaces } from "./spaces";
import { workspaces } from "./workspaces";
import { proposals } from "./proposals";
import { projects } from "./projects";

export const artifacts = pgTable("artifacts", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	runId: varchar("run_id", { length: 36 }),
	proposalId: varchar("proposal_id", { length: 36 }),
	artifactType: varchar("artifact_type", { length: 64 }).notNull(),
	title: varchar({ length: 512 }).notNull(),
	content: text(),
	storageRef: varchar("storage_ref", { length: 1024 }),
	storagePath: varchar("storage_path", { length: 1024 }),
	mimeType: varchar("mime_type", { length: 256 }),
	exportable: boolean().default(true).notNull(),
	exportFormatsJson: jsonb("export_formats_json").notNull(),
	canonicalFormat: varchar("canonical_format", { length: 64 }),
	preview: boolean().default(false).notNull(),
	relevantPeriodStart: timestamp("relevant_period_start", { withTimezone: true, mode: 'string' }),
	relevantPeriodEnd: timestamp("relevant_period_end", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
	metadataJson: jsonb("metadata_json"),
	visibility: varchar({ length: 32 }).default('space_shared').notNull(),
	ownerUserId: varchar("owner_user_id", { length: 36 }),
	trustLevel: varchar("trust_level", { length: 32 }),
	projectId: varchar("project_id", { length: 36 }),
	workspaceId: varchar("workspace_id", { length: 36 }),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_artifacts_artifact_type").using("btree", table.artifactType.asc().nullsLast()),
	index("ix_artifacts_owner_user_id").using("btree", table.ownerUserId.asc().nullsLast()),
	index("ix_artifacts_project_id").using("btree", table.projectId.asc().nullsLast()),
	index("ix_artifacts_proposal_id").using("btree", table.proposalId.asc().nullsLast()),
	index("ix_artifacts_run_id").using("btree", table.runId.asc().nullsLast()),
	index("ix_artifacts_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_artifacts_workspace_id").using("btree", table.workspaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.ownerUserId],
			foreignColumns: [users.id],
			name: "artifacts_owner_user_id_fkey"
		}),
	foreignKey({
			columns: [table.proposalId],
			foreignColumns: [proposals.id],
			name: "artifacts_proposal_id_fkey"
		}),
	foreignKey({
			columns: [table.runId],
			foreignColumns: [runs.id],
			name: "artifacts_run_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "artifacts_space_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.workspaceId],
			foreignColumns: [workspaces.id, workspaces.spaceId],
			name: "artifacts_workspace_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId, table.projectId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "fk_artifacts_project_id_projects"
		}).onDelete("set null"),
	check("ck_artifacts_storage_path_relative", sql`(storage_path IS NULL) OR ((storage_path)::text !~~ '/%'::text)`),
	check("ck_artifacts_trust_level", sql`(trust_level IS NULL) OR ((trust_level)::text = ANY (ARRAY[('high'::character varying)::text, ('medium'::character varying)::text, ('low'::character varying)::text, ('unknown'::character varying)::text]))`),
	check("ck_artifacts_workspace_shared_workspace", sql`((visibility)::text <> 'workspace_shared'::text) OR (workspace_id IS NOT NULL)`),
]);
