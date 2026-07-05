import { randomUUID } from "node:crypto";
import type { Queryable } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { AtlasRequestError } from "./domain/service";

type ProjectPaperStatus = "candidate" | "shortlist" | "reading" | "done" | "rejected";
type ProjectPaperReadStatus = "unread" | "skimmed" | "read";

export interface ProjectPaperRow {
  id: string;
  space_id: string;
  project_id: string;
  paper_id: string;
  status: ProjectPaperStatus;
  read_status: ProjectPaperReadStatus;
  rating: number | null;
  tags: string[];
  note: string | null;
  pinned: boolean;
  added_by_user_id: string | null;
  source: string;
  created_at: Date;
  updated_at: Date;
}

export async function listProjectPapers(
  db: Queryable,
  input: { spaceId: string; userId: string; projectId: string },
) {
  await assertProjectReadable(db, input);
  const result = await db.query(
    `SELECT pp.*,
            row_to_json(p.*) AS paper,
            (
              SELECT sr.intake_item_id
                FROM research_atlas_source_records sr
                JOIN research_atlas_entity_sources es ON es.source_record_id = sr.id
               WHERE es.entity_type = 'paper'
                 AND es.entity_id = pp.paper_id
                 AND sr.intake_item_id IS NOT NULL
               ORDER BY sr.fetched_at DESC
               LIMIT 1
            ) AS intake_item_id
       FROM research_atlas_project_papers pp
       JOIN research_atlas_papers p ON p.id = pp.paper_id
      WHERE pp.space_id = $1
        AND pp.project_id = $2
        AND p.merged_into_id IS NULL
      ORDER BY pp.pinned DESC, pp.updated_at DESC`,
    [input.spaceId, input.projectId],
  );
  return { project_id: input.projectId, papers: result.rows };
}

export async function addProjectPaper(
  db: Queryable,
  input: {
    spaceId: string;
    userId: string;
    projectId: string;
    paperId: string;
    source?: "manual" | "intake_sync" | "agent_proposal";
    status?: ProjectPaperStatus;
  },
): Promise<ProjectPaperRow> {
  await assertProjectWriter(db, input);
  await assertPaperInSpace(db, input.spaceId, input.paperId);
  const result = await db.query<ProjectPaperRow>(
    `INSERT INTO research_atlas_project_papers (
       id, space_id, project_id, paper_id, status, read_status, added_by_user_id, source, created_at, updated_at
     ) VALUES ($1, $2, $3, $4, $5, 'unread', $6, $7, $8, $8)
     ON CONFLICT (project_id, paper_id)
     DO UPDATE SET
       status = EXCLUDED.status,
       source = research_atlas_project_papers.source,
       updated_at = EXCLUDED.updated_at
     RETURNING *`,
    [
      randomUUID(),
      input.spaceId,
      input.projectId,
      input.paperId,
      input.status ?? "candidate",
      input.userId,
      input.source ?? "manual",
      new Date(),
    ],
  );
  return result.rows[0]!;
}

export async function updateProjectPaper(
  db: Queryable,
  input: {
    spaceId: string;
    userId: string;
    projectId: string;
    paperId: string;
    body: Record<string, unknown>;
  },
): Promise<ProjectPaperRow> {
  await assertProjectWriter(db, input);
  const patch = parseProjectPaperPatch(input.body);
  if (Object.keys(patch).length === 0) throw new AtlasRequestError(400, "no supported project paper fields provided");
  const fields: string[] = [];
  const params: unknown[] = [input.spaceId, input.projectId, input.paperId];
  for (const [key, value] of Object.entries(patch)) {
    params.push(Array.isArray(value) ? JSON.stringify(value) : value);
    fields.push(`${key} = $${params.length}${Array.isArray(value) ? "::jsonb" : ""}`);
  }
  params.push(new Date());
  const result = await db.query<ProjectPaperRow>(
    `UPDATE research_atlas_project_papers
        SET ${fields.join(", ")}, updated_at = $${params.length}
      WHERE space_id = $1
        AND project_id = $2
        AND paper_id = $3
      RETURNING *`,
    params,
  );
  if (!result.rows[0]) throw new AtlasRequestError(404, "project paper not found");
  return result.rows[0];
}

export async function removeProjectPaper(
  db: Queryable,
  input: { spaceId: string; userId: string; projectId: string; paperId: string },
): Promise<{ deleted: boolean }> {
  await assertProjectWriter(db, input);
  const result = await db.query(
    `DELETE FROM research_atlas_project_papers
      WHERE space_id = $1
        AND project_id = $2
        AND paper_id = $3`,
    [input.spaceId, input.projectId, input.paperId],
  );
  return { deleted: (result.rowCount ?? 0) > 0 };
}

export async function addProjectCandidatesForIntakeItem(
  db: Queryable,
  input: { spaceId: string; userId: string; paperId: string; intakeItemId: string; connectionId: string | null },
): Promise<number> {
  if (!input.connectionId) return 0;
  const bindings = await db.query<{ project_id: string }>(
    `SELECT DISTINCT project_id
       FROM workspace_source_bindings
      WHERE space_id = $1
        AND source_connection_id = $2
        AND status = 'active'`,
    [input.spaceId, input.connectionId],
  );
  let added = 0;
  for (const binding of bindings.rows) {
    const inserted = await db.query(
      `INSERT INTO research_atlas_project_papers (
         id, space_id, project_id, paper_id, status, read_status, added_by_user_id, source, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, 'candidate', 'unread', $5, 'intake_sync', $6, $6)
       ON CONFLICT (project_id, paper_id)
       DO NOTHING`,
      [randomUUID(), input.spaceId, binding.project_id, input.paperId, input.userId === "system" ? null : input.userId, new Date()],
    );
    added += inserted.rowCount ?? 0;
  }
  return added;
}

async function assertPaperInSpace(db: Queryable, spaceId: string, paperId: string): Promise<void> {
  const result = await db.query(
    `SELECT id
       FROM research_atlas_papers
      WHERE space_id = $1
        AND id = $2
        AND merged_into_id IS NULL`,
    [spaceId, paperId],
  );
  if ((result.rowCount ?? result.rows.length) === 0) throw new AtlasRequestError(404, "paper not found");
}

async function assertProjectReadable(
  db: Queryable,
  input: { spaceId: string; userId: string; projectId: string },
): Promise<void> {
  const project = await db.query<{ owner_user_id: string | null }>(
    `SELECT owner_user_id
       FROM projects
      WHERE space_id = $1
        AND id = $2
        AND deleted_at IS NULL
      LIMIT 1`,
    [input.spaceId, input.projectId],
  );
  const row = project.rows[0];
  if (!row) throw new AtlasRequestError(404, "project not found");
  if (row.owner_user_id === input.userId) return;
  const role = await readProjectRole(db, input);
  if (role) return;
  const spaceRole = await readSpaceRole(db, input.spaceId, input.userId);
  if (spaceRole) return;
  throw new AtlasRequestError(404, "project not found");
}

async function assertProjectWriter(
  db: Queryable,
  input: { spaceId: string; userId: string; projectId: string },
): Promise<void> {
  await assertProjectReadable(db, input);
  const role = await readProjectRole(db, input);
  if (role === "owner" || role === "member") return;
  const spaceRole = await readSpaceRole(db, input.spaceId, input.userId);
  if (spaceRole === "owner" || spaceRole === "admin") return;
  const project = await db.query<{ owner_user_id: string | null }>(
    `SELECT owner_user_id FROM projects WHERE space_id = $1 AND id = $2`,
    [input.spaceId, input.projectId],
  );
  if (project.rows[0]?.owner_user_id === input.userId) return;
  throw new AtlasRequestError(403, "requires project writer");
}

async function readProjectRole(
  db: Queryable,
  input: { spaceId: string; userId: string; projectId: string },
): Promise<string | null> {
  const result = await db.query<{ role: string }>(
    `SELECT role
       FROM project_members
      WHERE space_id = $1
        AND project_id = $2
        AND user_id = $3
        AND status = 'active'
      LIMIT 1`,
    [input.spaceId, input.projectId, input.userId],
  );
  return result.rows[0]?.role ?? null;
}

async function readSpaceRole(db: Queryable, spaceId: string, userId: string): Promise<string | null> {
  const result = await db.query<{ role: string }>(
    `SELECT role
       FROM space_memberships
      WHERE space_id = $1
        AND user_id = $2
        AND status = 'active'
      LIMIT 1`,
    [spaceId, userId],
  );
  return result.rows[0]?.role ?? null;
}

function parseProjectPaperPatch(body: Record<string, unknown>) {
  const patch: Record<string, string | number | boolean | string[] | null> = {};
  if (typeof body.status === "string") patch.status = enumValue(body.status, ["candidate", "shortlist", "reading", "done", "rejected"], "status");
  if (typeof body.read_status === "string") patch.read_status = enumValue(body.read_status, ["unread", "skimmed", "read"], "read_status");
  if (body.rating === null) patch.rating = null;
  else if (body.rating !== undefined) {
    const rating = Number(body.rating);
    if (!Number.isInteger(rating) || rating < 1 || rating > 5) throw new AtlasRequestError(400, "rating must be 1..5");
    patch.rating = rating;
  }
  if (Array.isArray(body.tags)) {
    patch.tags = body.tags.filter((tag): tag is string => typeof tag === "string" && tag.trim() !== "");
  }
  if (body.note === null || typeof body.note === "string") patch.note = body.note;
  if (typeof body.pinned === "boolean") patch.pinned = body.pinned;
  return patch;
}

function enumValue<T extends string>(value: string, allowed: readonly T[], name: string): T {
  if (!allowed.includes(value as T)) throw new AtlasRequestError(400, `${name} is invalid`);
  return value as T;
}
