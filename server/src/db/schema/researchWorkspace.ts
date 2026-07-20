import { boolean, check, foreignKey, index, integer, jsonb, pgTable, text, timestamp, unique, varchar, type PgTableExtraConfigValue } from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { projects } from "./projects";
import { runs } from "./runs";
import { sourceItems } from "./sources";
import { spaceObjects } from "./knowledge";
import { users } from "./auth";
import { spaces } from "./spaces";

export const researchNotebooks = pgTable("research_notebooks", {
  id: varchar({ length: 36 }).primaryKey().notNull(), spaceId: varchar("space_id", { length: 36 }).notNull(),
  projectId: varchar("project_id", { length: 36 }).notNull(), createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
  unique("uq_research_notebooks_project").on(table.projectId, table.spaceId),
  unique("uq_research_notebooks_id_space").on(table.id, table.spaceId),
  foreignKey({ columns: [table.projectId, table.spaceId], foreignColumns: [projects.id, projects.spaceId], name: "research_notebooks_project_fkey" }).onDelete("cascade"),
]);

export const researchNotebookSections = pgTable("research_notebook_sections", {
  id: varchar({ length: 36 }).primaryKey().notNull(), spaceId: varchar("space_id", { length: 36 }).notNull(),
  notebookId: varchar("notebook_id", { length: 36 }).notNull(),
  sectionKey: varchar("section_key", { length: 32 }).notNull(), contentJson: jsonb("content_json").notNull(),
  normalizedText: text("normalized_text").notNull(), contentHash: varchar("content_hash", { length: 64 }).notNull(),
  refsJson: jsonb("refs_json").default([]).notNull(),
  version: integer().default(1).notNull(), updatedByUserId: varchar("updated_by_user_id", { length: 36 }),
  updatedByRunId: varchar("updated_by_run_id", { length: 36 }), updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
  unique("uq_research_notebook_sections_key").on(table.notebookId, table.sectionKey),
  unique("uq_research_notebook_sections_id_space").on(table.id, table.spaceId),
  index("ix_research_notebook_sections_notebook").on(table.spaceId, table.notebookId),
  foreignKey({ columns: [table.spaceId], foreignColumns: [spaces.id], name: "research_notebook_sections_space_fkey" }),
  foreignKey({ columns: [table.notebookId, table.spaceId], foreignColumns: [researchNotebooks.id, researchNotebooks.spaceId], name: "research_notebook_sections_notebook_fkey" }).onDelete("cascade"),
  foreignKey({ columns: [table.updatedByUserId], foreignColumns: [users.id], name: "research_notebook_sections_user_fkey" }).onDelete("set null"),
  foreignKey({ columns: [table.updatedByRunId], foreignColumns: [runs.id], name: "research_notebook_sections_run_delete_fkey" }).onDelete("set null"),
  foreignKey({ columns: [table.updatedByRunId, table.spaceId], foreignColumns: [runs.id, runs.spaceId], name: "research_notebook_sections_run_fkey" }),
  check("ck_research_notebook_sections_key", sql`section_key IN ('understanding','questions','ideas','experiments')`),
  check("ck_research_notebook_sections_version", sql`version >= 1`),
  check("ck_research_notebook_sections_refs_array", sql`jsonb_typeof(refs_json) = 'array'`),
]);

export const researchNotebookSectionRevisions = pgTable("research_notebook_section_revisions", {
  id: varchar({ length: 36 }).primaryKey().notNull(), spaceId: varchar("space_id", { length: 36 }).notNull(),
  sectionId: varchar("section_id", { length: 36 }).notNull(),
  version: integer().notNull(), contentJson: jsonb("content_json").notNull(),
  normalizedText: text("normalized_text").notNull(), contentHash: varchar("content_hash", { length: 64 }).notNull(),
  refsJson: jsonb("refs_json").default([]).notNull(), source: varchar({ length: 24 }).notNull(),
  diffJson: jsonb("diff_json"), createdByUserId: varchar("created_by_user_id", { length: 36 }),
  createdByRunId: varchar("created_by_run_id", { length: 36 }),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
  unique("uq_research_notebook_section_revisions_version").on(table.sectionId, table.version),
  index("ix_research_notebook_section_revisions_section").on(table.spaceId, table.sectionId, table.version),
  foreignKey({ columns: [table.spaceId], foreignColumns: [spaces.id], name: "research_notebook_section_revisions_space_fkey" }),
  foreignKey({ columns: [table.sectionId, table.spaceId], foreignColumns: [researchNotebookSections.id, researchNotebookSections.spaceId], name: "research_notebook_section_revisions_section_fkey" }).onDelete("cascade"),
  foreignKey({ columns: [table.createdByUserId], foreignColumns: [users.id], name: "research_notebook_section_revisions_user_fkey" }).onDelete("set null"),
  foreignKey({ columns: [table.createdByRunId], foreignColumns: [runs.id], name: "research_notebook_section_revisions_run_delete_fkey" }).onDelete("set null"),
  foreignKey({ columns: [table.createdByRunId, table.spaceId], foreignColumns: [runs.id, runs.spaceId], name: "research_notebook_section_revisions_run_fkey" }),
  check("ck_research_notebook_section_revisions_version", sql`version >= 1`),
  check("ck_research_notebook_section_revisions_source", sql`source IN ('user_edit','ai_monitoring','ai_adhoc','seed','rollback')`),
  check("ck_research_notebook_section_revisions_refs_array", sql`jsonb_typeof(refs_json) = 'array'`),
]);

export const researchIntegrityAlerts = pgTable("research_integrity_alerts", {
  id: varchar({ length: 36 }).primaryKey().notNull(), spaceId: varchar("space_id", { length: 36 }).notNull(),
  projectId: varchar("project_id", { length: 36 }).notNull(), sourceItemId: varchar("source_item_id", { length: 36 }),
  doi: varchar({ length: 512 }).notNull(), eventKey: varchar("event_key", { length: 64 }).notNull(),
  eventType: varchar("event_type", { length: 32 }).notNull(), source: varchar({ length: 64 }).notNull(),
  noticeDoi: varchar("notice_doi", { length: 512 }), detailJson: jsonb("detail_json").default({}).notNull(),
  detectedAt: timestamp("detected_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
  unique("uq_research_integrity_alerts_event").on(table.spaceId, table.projectId, table.eventKey),
  index("ix_research_integrity_alerts_project_detected").on(table.spaceId, table.projectId, table.detectedAt),
  foreignKey({ columns: [table.projectId, table.spaceId], foreignColumns: [projects.id, projects.spaceId], name: "research_integrity_alerts_project_fkey" }).onDelete("cascade"),
  foreignKey({ columns: [table.sourceItemId], foreignColumns: [sourceItems.id], name: "research_integrity_alerts_source_item_delete_fkey" }).onDelete("set null"),
  foreignKey({ columns: [table.sourceItemId, table.spaceId], foreignColumns: [sourceItems.id, sourceItems.spaceId], name: "research_integrity_alerts_source_item_fkey" }),
  check("ck_research_integrity_alerts_event_type", sql`event_type IN ('retraction','correction','expression_of_concern','reinstatement')`),
  check("ck_research_integrity_alerts_detail_object", sql`jsonb_typeof(detail_json) = 'object'`),
]);

export const researchPaperCards = pgTable("research_paper_cards", {
  id: varchar({ length: 36 }).primaryKey().notNull(), spaceId: varchar("space_id", { length: 36 }).notNull(),
  projectId: varchar("project_id", { length: 36 }).notNull(), sourceItemId: varchar("source_item_id", { length: 36 }).notNull(),
  objectId: varchar("object_id", { length: 36 }), whyMd: text("why_md").default("").notNull(), howMd: text("how_md").default("").notNull(),
  whatMd: text("what_md").default("").notNull(), provenanceJson: jsonb("provenance_json").default({}).notNull(),
  editedByUser: boolean("edited_by_user").default(false).notNull(), stance: varchar({ length: 24 }), comparisonDetail: text("comparison_detail"),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(), updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
  unique("uq_research_paper_cards_project_source").on(table.spaceId, table.projectId, table.sourceItemId),
  index("ix_research_paper_cards_project").on(table.spaceId, table.projectId),
  foreignKey({ columns: [table.projectId, table.spaceId], foreignColumns: [projects.id, projects.spaceId], name: "research_paper_cards_project_fkey" }).onDelete("cascade"),
  foreignKey({ columns: [table.sourceItemId, table.spaceId], foreignColumns: [sourceItems.id, sourceItems.spaceId], name: "research_paper_cards_source_item_fkey" }).onDelete("cascade"),
  foreignKey({ columns: [table.objectId], foreignColumns: [spaceObjects.id], name: "research_paper_cards_object_delete_fkey" }).onDelete("set null"),
  foreignKey({ columns: [table.objectId, table.spaceId], foreignColumns: [spaceObjects.id, spaceObjects.spaceId], name: "research_paper_cards_object_fkey" }),
  check("ck_research_paper_cards_stance", sql`stance IS NULL OR stance IN ('supports','contradicts','new_direction')`),
]);

export const researchChecklistItems = pgTable("research_checklist_items", {
  id: varchar({ length: 36 }).primaryKey().notNull(), spaceId: varchar("space_id", { length: 36 }).notNull(), projectId: varchar("project_id", { length: 36 }).notNull(),
  text: text().notNull(), status: varchar({ length: 16 }).default("open").notNull(), sortOrder: integer("sort_order").notNull(),
  origin: varchar({ length: 16 }).notNull(), originRunId: varchar("origin_run_id", { length: 36 }), createdAt: timestamp("created_at", { withTimezone: true, mode: "string" }).notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "string" }).notNull(),
}, (table): PgTableExtraConfigValue[] => [
  index("ix_research_checklist_items_project_order").on(table.spaceId, table.projectId, table.sortOrder),
  foreignKey({ columns: [table.projectId, table.spaceId], foreignColumns: [projects.id, projects.spaceId], name: "research_checklist_items_project_fkey" }).onDelete("cascade"),
  foreignKey({ columns: [table.originRunId], foreignColumns: [runs.id], name: "research_checklist_items_run_delete_fkey" }).onDelete("set null"),
  foreignKey({ columns: [table.originRunId, table.spaceId], foreignColumns: [runs.id, runs.spaceId], name: "research_checklist_items_run_fkey" }),
  check("ck_research_checklist_items_status", sql`status IN ('open','done','dismissed')`),
  check("ck_research_checklist_items_origin", sql`origin IN ('user','agent')`),
  check("ck_research_checklist_items_sort", sql`sort_order >= 0`),
]);
