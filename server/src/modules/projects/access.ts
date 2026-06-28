import {
  HttpError,
  type Queryable,
} from "../routeUtils/common";
import { isSpaceOwnerOrAdmin } from "../access/roles";

export async function assertProjectInSpace(
  db: Queryable,
  spaceId: string,
  projectId: string | null | undefined,
  options: { statusCode?: number; message?: string } = {},
): Promise<void> {
  if (!projectId) return;
  const result = await db.query<{ id: string }>(
    `SELECT id
       FROM projects
      WHERE id = $1
        AND space_id = $2
        AND deleted_at IS NULL`,
    [projectId, spaceId],
  );
  if ((result.rowCount ?? result.rows.length) === 0) {
    throw new HttpError(options.statusCode ?? 422, options.message ?? "Project not found");
  }
}

export async function canWriteProject(
  db: Queryable,
  spaceId: string,
  projectId: string,
  userId: string,
): Promise<boolean> {
  const project = await db.query<{ owner_user_id: string | null }>(
    `SELECT owner_user_id
       FROM projects
      WHERE id = $1
        AND space_id = $2
        AND deleted_at IS NULL`,
    [projectId, spaceId],
  );
  const row = project.rows[0];
  if (!row) return false;
  if (row.owner_user_id && row.owner_user_id === userId) return true;

  const spaceRole = await db.query<{ role: string }>(
    `SELECT role
       FROM space_memberships
      WHERE space_id = $1
        AND user_id = $2
        AND status = 'active'
      LIMIT 1`,
    [spaceId, userId],
  );
  const role = spaceRole.rows[0]?.role;
  if (isSpaceOwnerOrAdmin(role)) return true;

  const projectRole = await db.query<{ role: string }>(
    `SELECT role
       FROM project_members
      WHERE space_id = $1
        AND project_id = $2
        AND user_id = $3
        AND status = 'active'
      LIMIT 1`,
    [spaceId, projectId, userId],
  );
  const memberRole = projectRole.rows[0]?.role;
  return memberRole === "owner" || memberRole === "member";
}

export async function assertProjectWriter(
  db: Queryable,
  spaceId: string,
  projectId: string,
  userId: string,
): Promise<void> {
  const exists = await db.query<{ id: string }>(
    `SELECT id
       FROM projects
      WHERE id = $1
        AND space_id = $2
        AND deleted_at IS NULL`,
    [projectId, spaceId],
  );
  if ((exists.rowCount ?? exists.rows.length) === 0) {
    throw new HttpError(404, "Project not found");
  }
  if (!(await canWriteProject(db, spaceId, projectId, userId))) {
    throw new HttpError(403, "Requires project writer, project owner, or space owner/admin role");
  }
}

/**
 * Owner-level authority: the project `owner_user_id` or a space `owner`/`admin`.
 * Unlike `canWriteProject`, an active project member role of `owner`/`member`
 * does NOT qualify — this is the gate for publishing a public summary
 * (`review_status` other than `draft`), so a project writer can only stage a
 * draft and the project owner / space admin performs the review/publish step.
 */
export async function isProjectOwnerLevel(
  db: Queryable,
  spaceId: string,
  projectId: string,
  userId: string,
): Promise<boolean> {
  const project = await db.query<{ owner_user_id: string | null }>(
    `SELECT owner_user_id
       FROM projects
      WHERE id = $1
        AND space_id = $2
        AND deleted_at IS NULL`,
    [projectId, spaceId],
  );
  const row = project.rows[0];
  if (!row) return false;
  if (row.owner_user_id && row.owner_user_id === userId) return true;

  const spaceRole = await db.query<{ role: string }>(
    `SELECT role
       FROM space_memberships
      WHERE space_id = $1
        AND user_id = $2
        AND status = 'active'
      LIMIT 1`,
    [spaceId, userId],
  );
  const role = spaceRole.rows[0]?.role;
  return isSpaceOwnerOrAdmin(role);
}

export async function assertProjectOwnerLevel(
  db: Queryable,
  spaceId: string,
  projectId: string,
  userId: string,
): Promise<void> {
  if (!(await isProjectOwnerLevel(db, spaceId, projectId, userId))) {
    throw new HttpError(403, "Requires project owner or space owner/admin role to publish a public summary");
  }
}
