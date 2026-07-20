import { createHash, randomUUID } from "node:crypto";
import { HttpError, type Queryable } from "../routeUtils/common";
import { applyNotebookOps, normalizePmText, type NotebookOp } from "./notebookDocument";

export type NotebookRevisionSource = "user_edit" | "ai_monitoring" | "ai_adhoc" | "seed" | "rollback";

export interface NotebookSectionRow {
  id: string;
  section_key: string;
  content_json: Record<string, unknown>;
  normalized_text: string;
  content_hash: string;
  refs_json: unknown;
  version: number;
  updated_by_user_id: string | null;
  updated_by_run_id: string | null;
  updated_at: string;
}

export type SectionWriteResult =
  | { outcome: "written"; section: NotebookSectionRow }
  | { outcome: "version_conflict"; currentVersion: number };

/**
 * Single writer for notebook sections. Every path — user save, AI ops,
 * seeding, rollback — goes through here so each new version always gets a
 * revision row, which is what makes rollback trustworthy.
 */
export async function writeNotebookSection(db: Queryable, input: {
  spaceId: string;
  projectId: string;
  sectionKey: string;
  expectVersion?: number | null;
  content: { kind: "doc"; doc: Record<string, unknown> } | { kind: "ops"; ops: NotebookOp[] };
  source: NotebookRevisionSource;
  userId?: string | null;
  runId?: string | null;
  refs?: string[];
  diff?: unknown;
}): Promise<SectionWriteResult> {
  const locked = await db.query<NotebookSectionRow>(
    `SELECT s.id,s.section_key,s.content_json,s.normalized_text,s.content_hash,s.refs_json,s.version,s.updated_by_user_id,s.updated_by_run_id,s.updated_at
       FROM research_notebook_sections s JOIN research_notebooks n ON n.id=s.notebook_id
      WHERE n.space_id=$1 AND n.project_id=$2 AND s.section_key=$3 FOR UPDATE OF s`,
    [input.spaceId, input.projectId, input.sectionKey],
  );
  const current = locked.rows[0];
  if (!current) throw new HttpError(404, "Research notebook section not found");
  if (input.expectVersion !== null && input.expectVersion !== undefined && input.expectVersion !== current.version) {
    return { outcome: "version_conflict", currentVersion: current.version };
  }
  const doc = input.content.kind === "doc" ? input.content.doc : applyNotebookOps(current.content_json, input.content.ops);
  const normalized = normalizePmText(doc);
  const mergedRefs = [...new Set([
    ...(Array.isArray(current.refs_json) ? current.refs_json.filter((v): v is string => typeof v === "string") : []),
    ...(input.refs ?? []),
  ])];
  const now = new Date().toISOString();
  const hash = sha256(normalized);
  const updated = await db.query<NotebookSectionRow>(
    `UPDATE research_notebook_sections
        SET content_json=$2::jsonb,normalized_text=$3,content_hash=$4,refs_json=$5::jsonb,version=version+1,
            updated_by_user_id=$6,updated_by_run_id=$7,updated_at=$8
      WHERE id=$1 AND space_id=$9
      RETURNING id,section_key,content_json,normalized_text,content_hash,refs_json,version,updated_by_user_id,updated_by_run_id,updated_at`,
    [current.id, JSON.stringify(doc), normalized, hash, JSON.stringify(mergedRefs), input.userId ?? null, input.runId ?? null, now, input.spaceId],
  );
  const section = updated.rows[0]!;
  await insertRevision(db, {
    spaceId: input.spaceId, sectionId: section.id, version: section.version, doc, normalized, hash, refs: mergedRefs,
    source: input.source, userId: input.userId ?? null, runId: input.runId ?? null, diff: input.diff ?? null, at: now,
  });
  await db.query(`UPDATE research_notebooks SET updated_at=$3 WHERE space_id=$1 AND project_id=$2`, [input.spaceId, input.projectId, now]);
  return { outcome: "written", section };
}

export async function rollbackNotebookSection(db: Queryable, input: {
  spaceId: string;
  projectId: string;
  sectionKey: string;
  toVersion: number;
  userId: string;
}): Promise<NotebookSectionRow> {
  const revision = await db.query<{ content_json: Record<string, unknown>; refs_json: unknown }>(
    `SELECT r.content_json,r.refs_json
       FROM research_notebook_section_revisions r
       JOIN research_notebook_sections s ON s.id=r.section_id
       JOIN research_notebooks n ON n.id=s.notebook_id
      WHERE n.space_id=$1 AND n.project_id=$2 AND s.section_key=$3 AND r.version=$4`,
    [input.spaceId, input.projectId, input.sectionKey, input.toVersion],
  );
  if (!revision.rows[0]) throw new HttpError(404, "Notebook revision not found");
  const result = await writeNotebookSection(db, {
    spaceId: input.spaceId,
    projectId: input.projectId,
    sectionKey: input.sectionKey,
    content: { kind: "doc", doc: revision.rows[0].content_json },
    source: "rollback",
    userId: input.userId,
    refs: Array.isArray(revision.rows[0].refs_json) ? revision.rows[0].refs_json.filter((v): v is string => typeof v === "string") : [],
    diff: { rolled_back_to_version: input.toVersion },
  });
  if (result.outcome !== "written") throw new HttpError(409, "Notebook section changed while rolling back; retry");
  return result.section;
}

export async function listNotebookRevisions(db: Queryable, input: {
  spaceId: string;
  projectId: string;
  sectionKey: string;
  limit?: number;
}): Promise<Array<Record<string, unknown>>> {
  const limit = Math.min(50, Math.max(1, input.limit ?? 20));
  const rows = await db.query(
    `SELECT r.id,r.version,r.content_json,r.normalized_text,r.refs_json,r.source,r.diff_json,r.created_by_user_id,r.created_by_run_id,r.created_at
       FROM research_notebook_section_revisions r
       JOIN research_notebook_sections s ON s.id=r.section_id
       JOIN research_notebooks n ON n.id=s.notebook_id
      WHERE n.space_id=$1 AND n.project_id=$2 AND s.section_key=$3
      ORDER BY r.version DESC
      LIMIT $4`,
    [input.spaceId, input.projectId, input.sectionKey, limit],
  );
  return rows.rows;
}

export async function insertInitialRevision(db: Queryable, input: {
  spaceId: string;
  sectionId: string;
  doc: Record<string, unknown>;
  at: string;
}): Promise<void> {
  await insertRevision(db, {
    spaceId: input.spaceId, sectionId: input.sectionId, version: 1, doc: input.doc, normalized: "", hash: sha256(""), refs: [],
    source: "seed", userId: null, runId: null, diff: null, at: input.at,
  });
}

async function insertRevision(db: Queryable, input: {
  spaceId: string; sectionId: string; version: number; doc: Record<string, unknown>; normalized: string; hash: string;
  refs: string[]; source: NotebookRevisionSource; userId: string | null; runId: string | null; diff: unknown; at: string;
}): Promise<void> {
  await db.query(
    `INSERT INTO research_notebook_section_revisions
       (id,space_id,section_id,version,content_json,normalized_text,content_hash,refs_json,source,diff_json,created_by_user_id,created_by_run_id,created_at)
     VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8::jsonb,$9,$10::jsonb,$11,$12,$13)
     ON CONFLICT (section_id,version) DO NOTHING`,
    [randomUUID(), input.spaceId, input.sectionId, input.version, JSON.stringify(input.doc), input.normalized, input.hash,
      JSON.stringify(input.refs), input.source, input.diff === null || input.diff === undefined ? null : JSON.stringify(input.diff), input.userId, input.runId, input.at],
  );
}

export function sha256(value: string): string { return createHash("sha256").update(value).digest("hex"); }
