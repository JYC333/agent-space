import type { Queryable } from "../routeUtils/common";

/**
 * Project-level access gate for memory reads.
 *
 * Memory rows may carry a `project_id`. A viewer may only read such a row if
 * they can access that project. There is no global project ACL elsewhere yet, so
 * this is the canonical definition:
 *
 * - Personal space: a single-member space. Its sole member can access every
 *   project in it. Memory search is identity-scoped to the caller's current
 *   space, so the caller is that member.
 * - Shared (team) space: the project owner can access it, and any user with an
 *   active `project_members` row can access it. Everyone else fails closed.
 * - A missing / deleted / cross-space project fails closed.
 *
 * Memory with `project_id = null` is not project-gated and should not call this.
 */
export async function canAccessProject(
  db: Queryable,
  spaceId: string,
  projectId: string,
  viewerUserId: string,
): Promise<boolean> {
  const project = await db.query<{ owner_user_id: string | null }>(
    `SELECT owner_user_id FROM projects
      WHERE id = $1 AND space_id = $2 AND deleted_at IS NULL`,
    [projectId, spaceId],
  );
  const row = project.rows[0];
  if (!row) return false;

  const space = await db.query<{ type: string }>(
    `SELECT type FROM spaces WHERE id = $1`,
    [spaceId],
  );
  if (space.rows[0]?.type === "personal") return true;

  if (row.owner_user_id && row.owner_user_id === viewerUserId) return true;

  const member = await db.query<{ one: number }>(
    `SELECT 1 AS one FROM project_members
      WHERE space_id = $1 AND project_id = $2 AND user_id = $3 AND status = 'active'
      LIMIT 1`,
    [spaceId, projectId, viewerUserId],
  );
  return member.rows.length > 0;
}

/**
 * Batched form of {@link canAccessProject} for filtering a page of rows: returns
 * the subset of `projectIds` the viewer can access, in a fixed number of queries
 * regardless of row count. Empty input short-circuits with no queries so callers
 * with no project-scoped rows pay nothing (and need no project tables present).
 */
export async function accessibleProjectIds(
  db: Queryable,
  spaceId: string,
  viewerUserId: string,
  projectIds: readonly (string | null | undefined)[],
): Promise<Set<string>> {
  const ids = [...new Set(projectIds.filter((id): id is string => typeof id === "string" && id.length > 0))];
  if (ids.length === 0) return new Set();

  const liveProjects = await db.query<{ id: string; owner_user_id: string | null }>(
    `SELECT id, owner_user_id FROM projects
      WHERE space_id = $1 AND id = ANY($2::varchar[]) AND deleted_at IS NULL`,
    [spaceId, ids],
  );
  const liveIds = liveProjects.rows.map((row) => row.id);
  if (liveIds.length === 0) return new Set();

  const space = await db.query<{ type: string }>(`SELECT type FROM spaces WHERE id = $1`, [spaceId]);
  if (space.rows[0]?.type === "personal") return new Set(liveIds);

  const member = await db.query<{ project_id: string }>(
    `SELECT pm.project_id
       FROM project_members pm
       JOIN projects p
         ON p.id = pm.project_id
        AND p.space_id = pm.space_id
        AND p.deleted_at IS NULL
      WHERE pm.space_id = $1
        AND pm.project_id = ANY($2::varchar[])
        AND pm.user_id = $3
        AND pm.status = 'active'`,
    [spaceId, liveIds, viewerUserId],
  );
  const accessible = new Set<string>();
  for (const row of liveProjects.rows) {
    if (row.owner_user_id === viewerUserId) accessible.add(row.id);
  }
  for (const row of member.rows) accessible.add(row.project_id);
  return accessible;
}
