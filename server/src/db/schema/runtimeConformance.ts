import {
  pgTable,
  index,
  unique,
  check,
  varchar,
  integer,
  jsonb,
  timestamp,
  type PgTableExtraConfigValue,
} from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";

export const runtimeConformanceResults = pgTable("runtime_conformance_results", {
  id: varchar({ length: 36 }).primaryKey().notNull(),
  runtimeAdapterType: varchar("runtime_adapter_type", { length: 64 }).notNull(),
  runtimeVersion: varchar("runtime_version", { length: 128 }).notNull(),
  suiteVersion: varchar("suite_version", { length: 64 }).notNull(),
  status: varchar({ length: 16 }).notNull(),
  trustLevel: varchar("trust_level", { length: 16 }).notNull(),
  passedChecks: integer("passed_checks").notNull(),
  failedChecks: integer("failed_checks").notNull(),
  checksJson: jsonb("checks_json").notNull(),
  evidenceJson: jsonb("evidence_json").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
  index("ix_runtime_conformance_adapter_status").using("btree", table.runtimeAdapterType.asc().nullsLast(), table.status.asc().nullsLast()),
  index("ix_runtime_conformance_updated_at").using("btree", table.updatedAt.desc().nullsLast()),
  unique("uq_runtime_conformance_runtime_version").on(table.runtimeAdapterType, table.runtimeVersion),
  check("ck_runtime_conformance_status", sql`(status)::text = ANY (ARRAY['passed'::text, 'failed'::text, 'partial'::text])`),
  check("ck_runtime_conformance_trust_level", sql`(trust_level)::text = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])`),
  check("ck_runtime_conformance_counts", sql`passed_checks >= 0 AND failed_checks >= 0`),
  check("ck_runtime_conformance_checks_object", sql`jsonb_typeof(checks_json) = 'object'::text`),
  check("ck_runtime_conformance_evidence_object", sql`jsonb_typeof(evidence_json) = 'object'::text`),
]);
