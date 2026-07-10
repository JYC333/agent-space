import {
	pgTable,
	index,
	unique,
	check,
	foreignKey,
	varchar,
	timestamp,
	type PgTableExtraConfigValue,
} from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { users } from "./auth";
import { spaceMemberships, spaces } from "./spaces";

/**
 * Explicit per-resource grants for content whose visibility is
 * `selected_users`. Resource existence is validated by the content-access
 * registry because PostgreSQL cannot express a foreign key to multiple tables.
 */
export const contentAccessGrants = pgTable("content_access_grants", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	resourceType: varchar("resource_type", { length: 64 }).notNull(),
	resourceId: varchar("resource_id", { length: 36 }).notNull(),
	granteeUserId: varchar("grantee_user_id", { length: 36 }).notNull(),
	grantedByUserId: varchar("granted_by_user_id", { length: 36 }).notNull(),
	accessLevel: varchar("access_level", { length: 16 }).default("full").notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
	revokedAt: timestamp("revoked_at", { withTimezone: true, mode: "string" }),
	revokedByUserId: varchar("revoked_by_user_id", { length: 36 }),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_content_access_grants_grantee").using(
		"btree",
		table.spaceId.asc().nullsLast(),
		table.granteeUserId.asc().nullsLast(),
		table.revokedAt.asc().nullsLast(),
	),
	index("ix_content_access_grants_resource").using(
		"btree",
		table.spaceId.asc().nullsLast(),
		table.resourceType.asc().nullsLast(),
		table.resourceId.asc().nullsLast(),
	),
	unique("uq_content_access_grants_resource_grantee").on(
		table.spaceId,
		table.resourceType,
		table.resourceId,
		table.granteeUserId,
	),
	foreignKey({
		columns: [table.spaceId],
		foreignColumns: [spaces.id],
		name: "content_access_grants_space_id_fkey",
	}).onDelete("cascade"),
	foreignKey({
		columns: [table.spaceId, table.granteeUserId],
		foreignColumns: [spaceMemberships.spaceId, spaceMemberships.userId],
		name: "content_access_grants_grantee_membership_fkey",
	}),
	foreignKey({
		columns: [table.spaceId, table.grantedByUserId],
		foreignColumns: [spaceMemberships.spaceId, spaceMemberships.userId],
		name: "content_access_grants_grantor_membership_fkey",
	}),
	foreignKey({
		columns: [table.revokedByUserId],
		foreignColumns: [users.id],
		name: "content_access_grants_revoked_by_user_id_fkey",
	}),
	check("ck_content_access_grants_access_level", sql`access_level IN ('full', 'summary')`),
]);
