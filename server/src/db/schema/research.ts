import { check, foreignKey, index, jsonb, pgTable, timestamp, unique, varchar, integer, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { spaces } from "./spaces";
import { users } from "./auth";
import { projects } from "./projects";
import { projectOperations } from "./projectOperations";

/** Immutable, reproducible execution records emitted by the system-level research engine. */
export const researchSearchStrategies = pgTable("research_search_strategies", {
  id: varchar({ length: 36 }).primaryKey().notNull(),
  spaceId: varchar("space_id", { length: 36 }).notNull(),
  projectId: varchar("project_id", { length: 36 }),
  operationId: varchar("operation_id", { length: 36 }),
  createdByUserId: varchar("created_by_user_id", { length: 36 }).notNull(),
  question: varchar({ length: 2000 }).notNull(),
  scopeJson: jsonb("scope_json").default({}).notNull(),
  providersJson: jsonb("providers_json").default([]).notNull(),
  queriesJson: jsonb("queries_json").default([]).notNull(),
  filtersJson: jsonb("filters_json").default({}).notNull(),
  timeWindowJson: jsonb("time_window_json"),
  hitCountsJson: jsonb("hit_counts_json").default({}).notNull(),
  providerErrorsJson: jsonb("provider_errors_json").default({}).notNull(),
  resultCount: integer("result_count").default(0).notNull(),
  status: varchar({ length: 16 }).notNull(),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
  completedAt: timestamp("completed_at", { withTimezone: true, mode: "string" }),
}, (table): PgTableExtraConfigValue[] => [
  index("ix_research_search_strategies_space_created").on(table.spaceId, table.createdAt),
  index("ix_research_search_strategies_operation").on(table.operationId),
  unique("uq_research_search_strategies_id_space").on(table.id, table.spaceId),
  foreignKey({ columns: [table.spaceId], foreignColumns: [spaces.id], name: "research_search_strategies_space_fkey" }),
  foreignKey({ columns: [table.projectId, table.spaceId], foreignColumns: [projects.id, projects.spaceId], name: "research_search_strategies_project_fkey" }).onDelete("cascade"),
  foreignKey({ columns: [table.operationId], foreignColumns: [projectOperations.id], name: "research_search_strategies_operation_fkey" }).onDelete("set null"),
  foreignKey({ columns: [table.createdByUserId], foreignColumns: [users.id], name: "research_search_strategies_user_fkey" }),
  check("ck_research_search_strategies_status", sql`status IN ('running','completed','partial','failed')`),
  check("ck_research_search_strategies_result_count", sql`result_count >= 0`),
  check("ck_research_search_strategies_json", sql`jsonb_typeof(scope_json)='object' AND jsonb_typeof(providers_json)='array' AND jsonb_typeof(queries_json)='array' AND jsonb_typeof(filters_json)='object' AND jsonb_typeof(hit_counts_json)='object' AND jsonb_typeof(provider_errors_json)='object'`),
]);
