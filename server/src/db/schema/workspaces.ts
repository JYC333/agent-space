import { pgTable, index, uniqueIndex, unique, check, foreignKey, varchar, text, integer, boolean, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { users } from "./auth";
import { sessions } from "./sessions";
import { spaces } from "./spaces";
import { projects } from "./projects";
import { sourceConnections, sourceItems } from "./sources";
import { validationRecipes } from "./tasks";

export const workspaces = pgTable("workspaces", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	name: varchar({ length: 256 }).notNull(),
	description: text(),
	rootPath: varchar("root_path", { length: 1024 }),
	repoUrl: text("repo_url"),
	status: varchar({ length: 32 }).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	slug: varchar({ length: 256 }),
	workspaceType: varchar("workspace_type", { length: 32 }).notNull(),
	kind: varchar({ length: 32 }).notNull(),
	defaultBranch: varchar("default_branch", { length: 256 }),
	visibility: varchar({ length: 32 }).notNull(),
	protected: boolean().notNull(),
	systemManaged: boolean("system_managed").notNull(),
	registeredFrom: varchar("registered_from", { length: 32 }),
	metadataJson: jsonb("metadata_json"),
	allowExternalRoot: boolean("allow_external_root").default(false).notNull(),
	snapshotRetentionDays: integer("snapshot_retention_days"),
	snapshotMaxCount: integer("snapshot_max_count"),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_workspaces_slug").using("btree", table.slug.asc().nullsLast()),
	index("ix_workspaces_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_workspaces_status").using("btree", table.status.asc().nullsLast()),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "workspaces_created_by_user_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "workspaces_space_id_fkey"
		}),
	unique("uq_workspaces_space_id_id").on(table.id, table.spaceId),
	check("ck_workspaces_workspace_type", sql`(workspace_type)::text = ANY (ARRAY['project'::text, 'repo'::text, 'knowledge_base'::text, 'personal'::text, 'team'::text, 'system_core'::text])`),
	check("ck_workspaces_status", sql`(status)::text = ANY (ARRAY['active'::text, 'archived'::text, 'stale'::text])`),
	check("ck_workspaces_visibility", sql`(visibility)::text = ANY (ARRAY['private'::text, 'space_shared'::text, 'workspace_shared'::text, 'restricted'::text])`),
]);

export const workingDirs = pgTable("working_dirs", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	scope: varchar({ length: 16 }).notNull(),
	sessionId: varchar("session_id", { length: 36 }),
	projectId: varchar("project_id", { length: 36 }),
	relPath: varchar("rel_path", { length: 1024 }).notNull(),
	status: varchar({ length: 16 }).default('active').notNull(),
	metadataJson: jsonb("metadata_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
	lastUsedAt: timestamp("last_used_at", { withTimezone: true, mode: 'string' }),
	cleanedAt: timestamp("cleaned_at", { withTimezone: true, mode: 'string' }),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_working_dirs_project_id").using("btree", table.projectId.asc().nullsLast()),
	uniqueIndex("ix_working_dirs_project_uniq").using("btree", table.projectId.asc().nullsLast()).where(sql`(project_id IS NOT NULL)`),
	index("ix_working_dirs_session_id").using("btree", table.sessionId.asc().nullsLast()),
	uniqueIndex("ix_working_dirs_session_uniq").using("btree", table.sessionId.asc().nullsLast()).where(sql`(session_id IS NOT NULL)`),
	index("ix_working_dirs_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_working_dirs_status").using("btree", table.status.asc().nullsLast()),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "working_dirs_project_id_fkey"
		}),
	foreignKey({
			columns: [table.sessionId],
			foreignColumns: [sessions.id],
			name: "working_dirs_session_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "working_dirs_space_id_fkey"
		}),
	check("ck_working_dirs_owner", sql`(((scope)::text = 'session'::text) AND (session_id IS NOT NULL) AND (project_id IS NULL)) OR (((scope)::text = 'project'::text) AND (project_id IS NOT NULL) AND (session_id IS NULL))`),
	check("ck_working_dirs_scope", sql`(scope)::text = ANY (ARRAY[('session'::character varying)::text, ('project'::character varying)::text])`),
	check("ck_working_dirs_status", sql`(status)::text = ANY (ARRAY[('active'::character varying)::text, ('cleaning'::character varying)::text, ('cleaned'::character varying)::text])`),
]);

export const projectWorkspaces = pgTable("project_workspaces", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	workspaceId: varchar("workspace_id", { length: 36 }).notNull(),
	role: varchar({ length: 64 }).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_workspaces_project_id").using("btree", table.projectId.asc().nullsLast()),
	index("ix_project_workspaces_workspace_id").using("btree", table.workspaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_workspaces_space_id_fkey"
		}),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_workspaces_project_id_fkey"
		}),
	foreignKey({
			columns: [table.workspaceId, table.spaceId],
			foreignColumns: [workspaces.id, workspaces.spaceId],
			name: "project_workspaces_workspace_id_fkey"
		}),
	unique("uq_project_workspaces_project_workspace_role").on(table.projectId, table.role, table.spaceId, table.workspaceId),
	check("ck_project_workspaces_role", sql`(role)::text = ANY (ARRAY[('primary_codebase'::character varying)::text, ('capability_library'::character varying)::text, ('docs'::character varying)::text, ('data'::character varying)::text, ('deployment'::character varying)::text, ('reference'::character varying)::text])`),
]);

export const workspaceProfiles = pgTable("workspace_profiles", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	workspaceId: varchar("workspace_id", { length: 36 }).notNull(),
	repoType: varchar("repo_type", { length: 64 }),
	techStackJson: jsonb("tech_stack_json"),
	importantPathsJson: jsonb("important_paths_json"),
	forbiddenPathsJson: jsonb("forbidden_paths_json"),
	testCommandsJson: jsonb("test_commands_json"),
	buildCommandsJson: jsonb("build_commands_json"),
	architectureBoundariesJson: jsonb("architecture_boundaries_json"),
	currentFocus: text("current_focus"),
	knownFailuresJson: jsonb("known_failures_json"),
	validationRecipeId: varchar("validation_recipe_id", { length: 36 }),
	cloudAllowed: boolean("cloud_allowed").default(false).notNull(),
	maxDataExposureLevel: varchar("max_data_exposure_level", { length: 64 }),
	minObservabilityLevel: varchar("min_observability_level", { length: 64 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_workspace_profiles_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_workspace_profiles_workspace_id").using("btree", table.workspaceId.asc().nullsLast()),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "workspace_profiles_space_id_fkey"
		}),
	foreignKey({
			columns: [table.validationRecipeId],
			foreignColumns: [validationRecipes.id],
			name: "workspace_profiles_validation_recipe_id_fkey"
		}),
	foreignKey({
			columns: [table.workspaceId, table.spaceId],
			foreignColumns: [workspaces.id, workspaces.spaceId],
			name: "workspace_profiles_workspace_id_fkey"
		}),
	unique("uq_workspace_profiles_workspace").on(table.workspaceId),
	check("ck_workspace_profiles_max_data_exposure_level", sql`(max_data_exposure_level IS NULL) OR ((max_data_exposure_level)::text = ANY (ARRAY[('local_only'::character varying)::text, ('model_provider'::character varying)::text, ('vendor_platform'::character varying)::text, ('third_party_tools'::character varying)::text, ('unknown'::character varying)::text]))`),
	check("ck_workspace_profiles_min_observability_level", sql`(min_observability_level IS NULL) OR ((min_observability_level)::text = ANY (ARRAY[('full_trace'::character varying)::text, ('structured_events'::character varying)::text, ('artifacts_only'::character varying)::text, ('final_output_only'::character varying)::text, ('black_box'::character varying)::text]))`),
]);

export const projectSourceBindings = pgTable("project_source_bindings", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	sourceConnectionId: varchar("source_connection_id", { length: 36 }).notNull(),
	bindingKey: varchar("binding_key", { length: 128 }).default('default').notNull(),
	status: varchar({ length: 32 }).notNull(),
	priority: integer().notNull(),
	deliveryScope: varchar("delivery_scope", { length: 32 }).default('project_members').notNull(),
	collectionNotificationsEnabled: boolean("collection_notifications_enabled").default(true).notNull(),
	filtersJson: jsonb("filters_json").notNull(),
	routingPolicyJson: jsonb("routing_policy_json").notNull(),
	extractionPolicyJson: jsonb("extraction_policy_json").notNull(),
	createdByUserId: varchar("created_by_user_id", { length: 36 }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_source_bindings_created_by_user_id").using("btree", table.createdByUserId.asc().nullsLast()),
	index("ix_project_source_bindings_project_id").using("btree", table.projectId.asc().nullsLast()),
	index("ix_project_source_bindings_source_connection_id").using("btree", table.sourceConnectionId.asc().nullsLast()),
	index("ix_project_source_bindings_space_id").using("btree", table.spaceId.asc().nullsLast()),
	index("ix_project_source_bindings_status").using("btree", table.status.asc().nullsLast()),
	foreignKey({
			columns: [table.createdByUserId],
			foreignColumns: [users.id],
			name: "project_source_bindings_created_by_user_id_fkey"
		}),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_source_bindings_project_id_fkey"
		}),
	foreignKey({
			columns: [table.sourceConnectionId],
			foreignColumns: [sourceConnections.id],
			name: "project_source_bindings_source_connection_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_source_bindings_space_id_fkey"
		}),
	unique("uq_project_source_bindings_project_connection").on(table.bindingKey, table.projectId, table.sourceConnectionId, table.spaceId),
	check("ck_project_source_bindings_delivery_scope", sql`(delivery_scope)::text = ANY (ARRAY[('project_members'::character varying)::text, ('source_subscribers'::character varying)::text])`),
	check("ck_project_source_bindings_status", sql`(status)::text = ANY (ARRAY[('active'::character varying)::text, ('paused'::character varying)::text, ('archived'::character varying)::text])`),
]);

export const projectSourceItemLinks = pgTable("project_source_item_links", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	projectId: varchar("project_id", { length: 36 }).notNull(),
	projectSourceBindingId: varchar("project_source_binding_id", { length: 36 }).notNull(),
	sourceConnectionId: varchar("source_connection_id", { length: 36 }),
	sourceItemId: varchar("source_item_id", { length: 36 }).notNull(),
	status: varchar({ length: 32 }).default('active').notNull(),
	matchedAt: timestamp("matched_at", { withTimezone: true, mode: 'string' }).notNull(),
	matchReason: text("match_reason"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_project_source_item_links_binding_id").using("btree", table.projectSourceBindingId.asc().nullsLast()),
	index("ix_project_source_item_links_matched_at").using("btree", table.matchedAt.asc().nullsLast()),
	index("ix_project_source_item_links_project_id").using("btree", table.projectId.asc().nullsLast()),
	index("ix_project_source_item_links_source_connection_id").using("btree", table.sourceConnectionId.asc().nullsLast()),
	index("ix_project_source_item_links_source_item_id").using("btree", table.sourceItemId.asc().nullsLast()),
	index("ix_project_source_item_links_status").using("btree", table.status.asc().nullsLast()),
	foreignKey({
			columns: [table.projectSourceBindingId],
			foreignColumns: [projectSourceBindings.id],
			name: "project_source_item_links_binding_id_fkey"
		}),
	foreignKey({
			columns: [table.projectId, table.spaceId],
			foreignColumns: [projects.id, projects.spaceId],
			name: "project_source_item_links_project_id_fkey"
		}),
	foreignKey({
			columns: [table.sourceConnectionId],
			foreignColumns: [sourceConnections.id],
			name: "project_source_item_links_source_connection_id_fkey"
		}),
	foreignKey({
			columns: [table.sourceItemId],
			foreignColumns: [sourceItems.id],
			name: "project_source_item_links_source_item_id_fkey"
		}),
	foreignKey({
			columns: [table.spaceId],
			foreignColumns: [spaces.id],
			name: "project_source_item_links_space_id_fkey"
		}),
	unique("uq_project_source_item_links_binding_item").on(table.projectSourceBindingId, table.projectId, table.sourceItemId, table.spaceId),
	check("ck_project_source_item_links_status", sql`(status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text])`),
]);
