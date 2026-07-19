import { pgTable, index, unique, uniqueIndex, check, foreignKey, varchar, text, boolean, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { users } from "./auth";
import { spaces } from "./spaces";
import { sourceConnections, sourceItems } from "./sources";

export const sourceChannels = pgTable("source_channels", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	sourceConnectionId: varchar("source_connection_id", { length: 36 }).notNull(),
	createdByUserId: varchar("created_by_user_id", { length: 36 }).notNull(),
	name: varchar({ length: 512 }).notNull(),
	channelType: varchar("channel_type", { length: 32 }).notNull(),
	endpointUrl: text("endpoint_url"),
	queryJson: jsonb("query_json").notNull(),
	providerQueryJson: jsonb("provider_query_json").notNull(),
	queryFingerprint: varchar("query_fingerprint", { length: 128 }).notNull(),
	status: varchar({ length: 32 }).notNull(),
	fetchFrequency: varchar("fetch_frequency", { length: 32 }).notNull(),
	scheduleRuleJson: jsonb("schedule_rule_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_source_channels_space_status").using("btree", table.spaceId.asc().nullsLast(), table.status.asc().nullsLast()),
	index("ix_source_channels_connection_status").using("btree", table.sourceConnectionId.asc().nullsLast(), table.status.asc().nullsLast()),
	index("ix_source_channels_fingerprint").using("btree", table.spaceId.asc().nullsLast(), table.queryFingerprint.asc().nullsLast()),
	unique("uq_source_channels_id_space").on(table.id, table.spaceId),
	uniqueIndex("uq_source_channels_active_fingerprint").using("btree", table.spaceId.asc().nullsLast(), table.sourceConnectionId.asc().nullsLast(), table.queryFingerprint.asc().nullsLast()).where(sql`status <> 'archived'`),
	foreignKey({ columns: [table.spaceId], foreignColumns: [spaces.id], name: "source_channels_space_id_fkey" }),
	foreignKey({ columns: [table.sourceConnectionId, table.spaceId], foreignColumns: [sourceConnections.id, sourceConnections.spaceId], name: "source_channels_connection_id_fkey" }).onDelete("cascade"),
	foreignKey({ columns: [table.createdByUserId], foreignColumns: [users.id], name: "source_channels_created_by_user_id_fkey" }),
	check("ck_source_channels_type", sql`channel_type IN ('search','feed','web_page','custom_source')`),
	check("ck_source_channels_status", sql`status IN ('active','paused','archived')`),
	check("ck_source_channels_fetch_frequency", sql`fetch_frequency IN ('manual','hourly','daily','weekly')`),
	check("ck_source_channels_query_object", sql`jsonb_typeof(query_json) = 'object'::text`),
	check("ck_source_channels_provider_query_object", sql`jsonb_typeof(provider_query_json) = 'object'::text`),
]);

export const sourceChannelItemLinks = pgTable("source_channel_item_links", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	sourceChannelId: varchar("source_channel_id", { length: 36 }).notNull(),
	sourceItemId: varchar("source_item_id", { length: 36 }).notNull(),
	status: varchar({ length: 32 }).default("active").notNull(),
	matchedAt: timestamp("matched_at", { withTimezone: true, mode: "string" }).notNull(),
	matchReason: text("match_reason"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_source_channel_item_links_channel").using("btree", table.sourceChannelId.asc().nullsLast()),
	index("ix_source_channel_item_links_item").using("btree", table.sourceItemId.asc().nullsLast()),
	index("ix_source_channel_item_links_status").using("btree", table.spaceId.asc().nullsLast(), table.status.asc().nullsLast()),
	unique("uq_source_channel_item_links_channel_item").on(table.sourceChannelId, table.sourceItemId),
	foreignKey({ columns: [table.spaceId], foreignColumns: [spaces.id], name: "source_channel_item_links_space_id_fkey" }),
	foreignKey({ columns: [table.sourceChannelId, table.spaceId], foreignColumns: [sourceChannels.id, sourceChannels.spaceId], name: "source_channel_item_links_channel_id_fkey" }).onDelete("cascade"),
	foreignKey({ columns: [table.sourceItemId], foreignColumns: [sourceItems.id], name: "source_channel_item_links_item_id_fkey" }).onDelete("cascade"),
	check("ck_source_channel_item_links_status", sql`status IN ('active','archived')`),
]);

export const sourceChannelUserSubscriptions = pgTable("source_channel_user_subscriptions", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	spaceId: varchar("space_id", { length: 36 }).notNull(),
	sourceChannelId: varchar("source_channel_id", { length: 36 }).notNull(),
	userId: varchar("user_id", { length: 36 }).notNull(),
	status: varchar({ length: 32 }).notNull(),
	libraryEnabled: boolean("library_enabled").default(true).notNull(),
	digestEnabled: boolean("digest_enabled").default(true).notNull(),
	recommendedByUserId: varchar("recommended_by_user_id", { length: 36 }),
	recommendationMessage: text("recommendation_message"),
	lastNotifiedAt: timestamp("last_notified_at", { withTimezone: true, mode: "string" }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	index("ix_source_channel_user_subscriptions_channel_status").using("btree", table.spaceId.asc().nullsLast(), table.sourceChannelId.asc().nullsLast(), table.status.asc().nullsLast()),
	index("ix_source_channel_user_subscriptions_user_status").using("btree", table.spaceId.asc().nullsLast(), table.userId.asc().nullsLast(), table.status.asc().nullsLast()),
	uniqueIndex("uq_source_channel_user_subscriptions_space_channel_user").using("btree", table.spaceId.asc().nullsLast(), table.sourceChannelId.asc().nullsLast(), table.userId.asc().nullsLast()),
	foreignKey({ columns: [table.spaceId], foreignColumns: [spaces.id], name: "source_channel_user_subscriptions_space_id_fkey" }),
	foreignKey({ columns: [table.sourceChannelId, table.spaceId], foreignColumns: [sourceChannels.id, sourceChannels.spaceId], name: "source_channel_user_subscriptions_channel_id_fkey" }).onDelete("cascade"),
	foreignKey({ columns: [table.userId], foreignColumns: [users.id], name: "source_channel_user_subscriptions_user_id_fkey" }),
	foreignKey({ columns: [table.recommendedByUserId], foreignColumns: [users.id], name: "source_channel_user_subscriptions_recommended_by_user_id_fkey" }).onDelete("set null"),
	check("ck_source_channel_user_subscriptions_status", sql`status IN ('subscribed','pending','dismissed','muted')`),
]);
