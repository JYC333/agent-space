import { pgTable, index, unique, uniqueIndex, check, foreignKey, varchar, integer, jsonb, timestamp, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";

/**
 * Source catalog identity. Providers describe external source semantics and
 * capabilities; they do not contain executable fetching code.
 */
export const sourceProviders = pgTable("source_providers", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	providerKey: varchar("provider_key", { length: 128 }).notNull(),
	displayName: varchar("display_name", { length: 256 }).notNull(),
	providerKind: varchar("provider_kind", { length: 32 }).notNull(),
	category: varchar({ length: 64 }).notNull(),
	status: varchar({ length: 32 }).notNull(),
	capabilitiesJson: jsonb("capabilities_json").notNull(),
	configSchemaJson: jsonb("config_schema_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	uniqueIndex("ix_source_providers_provider_key").using("btree", table.providerKey.asc().nullsLast()),
	unique("source_providers_provider_key_key").on(table.providerKey),
	index("ix_source_providers_status").using("btree", table.status.asc().nullsLast()),
	index("ix_source_providers_category").using("btree", table.category.asc().nullsLast()),
	check("ck_source_providers_kind", sql`provider_kind IN ('named','generic')`),
	check("ck_source_providers_status", sql`status IN ('active','disabled')`),
	check("ck_source_providers_capabilities_object", sql`jsonb_typeof(capabilities_json) = 'object'::text`),
]);

/**
 * Built-in implementation catalog. Connector rows are installed by the
 * server, while the implementation itself is registered in code.
 */
export const sourceConnectors = pgTable("source_connectors", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	connectorKey: varchar("connector_key", { length: 128 }).notNull(),
	displayName: varchar("display_name", { length: 256 }).notNull(),
	connectorType: varchar("connector_type", { length: 64 }).notNull(),
	ingestionMode: varchar("ingestion_mode", { length: 32 }).notNull(),
	status: varchar({ length: 32 }).notNull(),
	capabilitiesJson: jsonb("capabilities_json").notNull(),
	configSchemaJson: jsonb("config_schema_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	uniqueIndex("ix_source_connectors_connector_key").using("btree", table.connectorKey.asc().nullsLast()),
	unique("source_connectors_connector_key_key").on(table.connectorKey),
	index("ix_source_connectors_connector_type").using("btree", table.connectorType.asc().nullsLast()),
	index("ix_source_connectors_status").using("btree", table.status.asc().nullsLast()),
	check("ck_source_connectors_connector_type", sql`connector_type IN ('external_feed','external_url','internal_activity','internal_artifact','internal_run','file','document')`),
	check("ck_source_connectors_ingestion_mode", sql`ingestion_mode IN ('pull','manual','internal')`),
	check("ck_source_connectors_status", sql`status IN ('active','disabled')`),
	check("ck_source_connectors_capabilities_object", sql`jsonb_typeof(capabilities_json) = 'object'::text`),
]);

/** A valid provider/implementation pair selected by a Source Connection. */
export const sourceProviderConnectors = pgTable("source_provider_connectors", {
	id: varchar({ length: 36 }).primaryKey().notNull(),
	providerId: varchar("provider_id", { length: 36 }).notNull(),
	connectorId: varchar("connector_id", { length: 36 }).notNull(),
	status: varchar({ length: 32 }).notNull(),
	priority: integer().default(100).notNull(),
	capabilitiesJson: jsonb("capabilities_json").notNull(),
	configSchemaJson: jsonb("config_schema_json"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
	unique("uq_source_provider_connectors_provider_connector").on(table.providerId, table.connectorId),
	unique("uq_source_provider_connectors_id_provider").on(table.id, table.providerId),
	index("ix_source_provider_connectors_provider_status").using("btree", table.providerId.asc().nullsLast(), table.status.asc().nullsLast(), table.priority.asc().nullsLast()),
	index("ix_source_provider_connectors_connector_status").using("btree", table.connectorId.asc().nullsLast(), table.status.asc().nullsLast()),
	foreignKey({ columns: [table.providerId], foreignColumns: [sourceProviders.id], name: "source_provider_connectors_provider_id_fkey" }).onDelete("cascade"),
	foreignKey({ columns: [table.connectorId], foreignColumns: [sourceConnectors.id], name: "source_provider_connectors_connector_id_fkey" }).onDelete("cascade"),
	check("ck_source_provider_connectors_status", sql`status IN ('active','disabled')`),
	check("ck_source_provider_connectors_priority", sql`priority >= 0`),
	check("ck_source_provider_connectors_capabilities_object", sql`jsonb_typeof(capabilities_json) = 'object'::text`),
]);
