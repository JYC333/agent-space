import { pgTable, index, check, foreignKey, varchar, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { users } from "./auth";
import { spaces } from "./spaces";

export const sourcePointers = pgTable("source_pointers", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	ownerSpaceId: varchar("owner_space_id", { length: 36 }).notNull(),
	sourceSpaceId: varchar("source_space_id", { length: 36 }).notNull(),
	sourceObjectType: varchar("source_object_type", { length: 64 }).notNull(),
	sourceObjectId: varchar("source_object_id", { length: 36 }).notNull(),
	accessMode: varchar("access_mode", { length: 32 }).notNull(),
	grantedByUserId: varchar("granted_by_user_id", { length: 36 }),
	expiresAt: timestamp("expires_at", { withTimezone: true, mode: 'string' }),
	metadataJson: jsonb("metadata_json").default({}).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_source_pointers_expires_at").using("btree", table.expiresAt.asc().nullsLast()),
	index("ix_source_pointers_granted_by_user_id").using("btree", table.grantedByUserId.asc().nullsLast()),
	index("ix_source_pointers_owner_space_id").using("btree", table.ownerSpaceId.asc().nullsLast()),
	index("ix_source_pointers_source").using("btree", table.sourceSpaceId.asc().nullsLast(), table.sourceObjectType.asc().nullsLast(), table.sourceObjectId.asc().nullsLast()),
	foreignKey({
			columns: [table.grantedByUserId],
			foreignColumns: [users.id],
			name: "source_pointers_granted_by_user_id_fkey"
		}),
	foreignKey({
			columns: [table.ownerSpaceId],
			foreignColumns: [spaces.id],
			name: "source_pointers_owner_space_id_fkey"
		}),
	foreignKey({
			columns: [table.sourceSpaceId],
			foreignColumns: [spaces.id],
			name: "source_pointers_source_space_id_fkey"
		}),
	check("ck_source_pointers_access_mode", sql`(access_mode)::text = ANY (ARRAY[('read'::character varying)::text, ('subscribe'::character varying)::text, ('federated'::character varying)::text])`),
	check("ck_source_pointers_metadata_object", sql`jsonb_typeof(metadata_json) = 'object'::text`),
	check("ck_source_pointers_source_object_type", sql`(source_object_type)::text = ANY (ARRAY[('memory_entry'::character varying)::text, ('artifact'::character varying)::text, ('activity_record'::character varying)::text, ('run'::character varying)::text, ('proposal'::character varying)::text, ('knowledge_item'::character varying)::text, ('note'::character varying)::text, ('source'::character varying)::text, ('claim'::character varying)::text, ('project'::character varying)::text, ('workspace'::character varying)::text])`),
]);
