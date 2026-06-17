import { randomUUID } from "node:crypto";
import type { ServerConfig } from "../../config";
import {
  HttpError,
  countFromRow,
  dateIso,
  objectValue,
  optionalObject,
  optionalString,
  page,
  requiredString,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";
import { getDbPool } from "../../db/pool";

export interface ProjectRow {
  id: string;
  space_id: string;
  owner_user_id: string | null;
  name: string;
  description: string | null;
  status: string;
  current_focus: string | null;
  settings_json: unknown;
  created_at: unknown;
  updated_at: unknown;
  archived_at: unknown;
}

export interface ProjectWorkspaceLinkRow {
  id: string;
  project_id: string;
  workspace_id: string;
  role: string;
  created_at: unknown;
  updated_at: unknown;
}

const PROJECT_COLUMNS = `
  id, space_id, owner_user_id, name, description, status, current_focus,
  settings_json, created_at, updated_at, archived_at
`;

const LINK_COLUMNS = `id, project_id, workspace_id, role, created_at, updated_at`;
const WORKSPACE_ROLES = new Set([
  "primary_codebase",
  "capability_library",
  "docs",
  "data",
  "deployment",
  "reference",
]);

export class PgProjectRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ServerConfig): PgProjectRepository {
    if (!config.databaseUrl) throw new HttpError(502, "SERVER_DATABASE_URL is required");
    return new PgProjectRepository(getDbPool(config.databaseUrl));
  }

  async list(
    identity: SpaceUserIdentity,
    filters: { status?: string | null; limit: number; offset: number },
  ): Promise<Record<string, unknown>> {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1", "deleted_at IS NULL"];
    if (filters.status) {
      params.push(filters.status);
      clauses.push(`status = $${params.length}`);
    }
    const total = await this.db.query<{ total: string | number }>(
      `SELECT count(id)::text AS total FROM projects WHERE ${clauses.join(" AND ")}`,
      params,
    );
    const rows = await this.db.query<ProjectRow>(
      `SELECT ${PROJECT_COLUMNS}
         FROM projects
        WHERE ${clauses.join(" AND ")}
        ORDER BY updated_at DESC, created_at DESC, id DESC
        LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(projectToOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async create(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const name = requiredString(body.name, "name");
    const now = new Date().toISOString();
    const result = await this.db.query<ProjectRow>(
      `INSERT INTO projects (
         id, space_id, owner_user_id, name, description, status, current_focus,
         settings_json, created_at, updated_at, archived_at, deleted_at
       ) VALUES ($1, $2, $3, $4, $5, 'active', $6, $7::jsonb, $8, $8, NULL, NULL)
       RETURNING ${PROJECT_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        identity.userId,
        name,
        optionalString(body.description),
        optionalString(body.current_focus),
        JSON.stringify(optionalObject(body.settings_json) ?? {}),
        now,
      ],
    );
    return projectToOut(result.rows[0]!);
  }

  async get(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown> | null> {
    const row = await this.getRow(identity.spaceId, projectId);
    return row ? projectToOut(row) : null;
  }

  async update(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await this.requireProject(identity.spaceId, projectId);
    const current = await this.getRow(identity.spaceId, projectId);
    if (!current) throw new HttpError(404, "Project not found");
    const status = optionalString(body.status) ?? current.status;
    if (!["active", "archived"].includes(status)) throw new HttpError(422, "status must be active or archived");
    const now = new Date().toISOString();
    const result = await this.db.query<ProjectRow>(
      `UPDATE projects
          SET name = $3,
              description = $4,
              status = $5,
              current_focus = $6,
              settings_json = $7::jsonb,
              archived_at = CASE
                WHEN $5 = 'archived' AND archived_at IS NULL THEN $8::timestamptz
                WHEN $5 = 'active' THEN NULL
                ELSE archived_at
              END,
              updated_at = $8
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL
        RETURNING ${PROJECT_COLUMNS}`,
      [
        identity.spaceId,
        projectId,
        optionalString(body.name) ?? current.name,
        body.description === undefined ? current.description : optionalString(body.description),
        status,
        body.current_focus === undefined ? current.current_focus : optionalString(body.current_focus),
        JSON.stringify(optionalObject(body.settings_json) ?? objectValue(current.settings_json)),
        now,
      ],
    );
    return projectToOut(result.rows[0]!);
  }

  async archive(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>> {
    await this.requireProject(identity.spaceId, projectId);
    const now = new Date().toISOString();
    const result = await this.db.query<ProjectRow>(
      `UPDATE projects
          SET status = 'archived',
              archived_at = COALESCE(archived_at, $3::timestamptz),
              updated_at = $3
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL
        RETURNING ${PROJECT_COLUMNS}`,
      [identity.spaceId, projectId, now],
    );
    return projectToOut(result.rows[0]!);
  }

  async summary(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>> {
    await this.requireProject(identity.spaceId, projectId);
    const [
      activities,
      artifacts,
      pendingProposals,
      workspaces,
      activeRuns,
      memories,
    ] = await Promise.all([
      this.count("activity_records", identity.spaceId, projectId),
      this.count("artifacts", identity.spaceId, projectId),
      this.db.query<{ total: string | number }>(
        `SELECT count(id)::text AS total
           FROM proposals
          WHERE space_id = $1 AND project_id = $2 AND status = 'pending'`,
        [identity.spaceId, projectId],
      ),
      this.db.query<{ total: string | number }>(
        `SELECT count(pw.id)::text AS total
           FROM project_workspaces pw
           JOIN projects p ON p.id = pw.project_id
          WHERE p.space_id = $1 AND pw.project_id = $2 AND p.deleted_at IS NULL`,
        [identity.spaceId, projectId],
      ),
      this.db.query<{ total: string | number }>(
        `SELECT count(id)::text AS total
           FROM runs
          WHERE space_id = $1
            AND project_id = $2
            AND status IN ('queued', 'running', 'waiting_for_review')`,
        [identity.spaceId, projectId],
      ),
      this.db.query<{ total: string | number }>(
        `SELECT count(id)::text AS total
           FROM memory_entries
          WHERE space_id = $1 AND project_id = $2 AND deleted_at IS NULL`,
        [identity.spaceId, projectId],
      ),
    ]);
    return {
      project_id: projectId,
      activity_count: countFromRow(activities.rows[0]),
      artifact_count: countFromRow(artifacts.rows[0]),
      pending_proposal_count: countFromRow(pendingProposals.rows[0]),
      workspace_count: countFromRow(workspaces.rows[0]),
      active_run_count: countFromRow(activeRuns.rows[0]),
      memory_entry_count: countFromRow(memories.rows[0]),
    };
  }

  async listWorkspaces(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    await this.requireProject(identity.spaceId, projectId);
    const rows = await this.db.query<ProjectWorkspaceLinkRow>(
      `SELECT pw.${LINK_COLUMNS.replaceAll(", ", ", pw.")}
         FROM project_workspaces pw
         JOIN workspaces w ON w.id = pw.workspace_id
        WHERE pw.project_id = $1
          AND w.space_id = $2
        ORDER BY pw.created_at ASC, pw.id ASC`,
      [projectId, identity.spaceId],
    );
    return rows.rows.map(projectWorkspaceLinkToOut);
  }

  async linkWorkspace(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await this.requireProject(identity.spaceId, projectId);
    const workspaceId = requiredString(body.workspace_id, "workspace_id");
    const role = optionalString(body.role) ?? "reference";
    if (!WORKSPACE_ROLES.has(role)) throw new HttpError(422, "invalid workspace role");
    const workspace = await this.db.query<{ id: string }>(
      `SELECT id FROM workspaces WHERE id = $1 AND space_id = $2 AND status = 'active'`,
      [workspaceId, identity.spaceId],
    );
    if (!workspace.rows[0]) throw new HttpError(404, "Workspace not found");
    const now = new Date().toISOString();
    const result = await this.db.query<ProjectWorkspaceLinkRow>(
      `INSERT INTO project_workspaces (id, project_id, workspace_id, role, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $5)
       ON CONFLICT (project_id, workspace_id, role)
       DO UPDATE SET updated_at = EXCLUDED.updated_at
       RETURNING ${LINK_COLUMNS}`,
      [randomUUID(), projectId, workspaceId, role, now],
    );
    return projectWorkspaceLinkToOut(result.rows[0]!);
  }

  async unlinkWorkspace(
    identity: SpaceUserIdentity,
    projectId: string,
    workspaceId: string,
    role: string | null,
  ): Promise<void> {
    await this.requireProject(identity.spaceId, projectId);
    if (role && !WORKSPACE_ROLES.has(role)) throw new HttpError(422, "invalid workspace role");
    const params: unknown[] = [projectId, workspaceId];
    const clauses = ["project_id = $1", "workspace_id = $2"];
    if (role) {
      params.push(role);
      clauses.push(`role = $${params.length}`);
    }
    await this.db.query(`DELETE FROM project_workspaces WHERE ${clauses.join(" AND ")}`, params);
  }

  private async getRow(spaceId: string, projectId: string): Promise<ProjectRow | null> {
    const result = await this.db.query<ProjectRow>(
      `SELECT ${PROJECT_COLUMNS}
         FROM projects
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL
        LIMIT 1`,
      [spaceId, projectId],
    );
    return result.rows[0] ?? null;
  }

  private async requireProject(spaceId: string, projectId: string): Promise<void> {
    if (!(await this.getRow(spaceId, projectId))) throw new HttpError(404, "Project not found");
  }

  private async count(table: string, spaceId: string, projectId: string): Promise<{ rows: Array<{ total?: unknown }> }> {
    return this.db.query<{ total: string | number }>(
      `SELECT count(id)::text AS total FROM ${table} WHERE space_id = $1 AND project_id = $2`,
      [spaceId, projectId],
    );
  }
}

function projectToOut(row: ProjectRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    owner_user_id: row.owner_user_id,
    name: row.name,
    description: row.description,
    status: row.status === "deleted" ? "archived" : row.status,
    current_focus: row.current_focus,
    settings_json: row.settings_json === null ? null : objectValue(row.settings_json),
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
    archived_at: dateIso(row.archived_at),
  };
}

function projectWorkspaceLinkToOut(row: ProjectWorkspaceLinkRow): Record<string, unknown> {
  return {
    id: row.id,
    project_id: row.project_id,
    workspace_id: row.workspace_id,
    role: row.role,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
  };
}
