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
import { RetrievalProjectionService } from "../retrieval";
import { assertProjectOwnerLevel, assertProjectWriter, canWriteProject } from "./access";
import { projectRetrievalRegistry } from "./retrievalAdapter";

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

export interface ProjectMemberRow {
  id: string;
  space_id: string;
  project_id: string;
  user_id: string;
  role: string;
  status: string;
  created_at: unknown;
  updated_at: unknown;
}

export interface ProjectPublicSummaryRow {
  id: string;
  space_id: string;
  project_id: string;
  project_name: string;
  summary_text: string;
  topics_json: unknown;
  highlights_json: unknown;
  source_refs_json: unknown;
  redaction_version: string;
  review_status: string;
  updated_by_user_id: string | null;
  generated_by_run_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

const PROJECT_COLUMNS = `
  id, space_id, owner_user_id, name, description, status, current_focus,
  settings_json, created_at, updated_at, archived_at
`;

const LINK_COLUMNS = `id, project_id, workspace_id, role, created_at, updated_at`;
const PUBLIC_SUMMARY_COLUMNS = `
  ps.id, ps.space_id, ps.project_id, p.name AS project_name, ps.summary_text,
  ps.topics_json, ps.highlights_json, ps.source_refs_json, ps.redaction_version,
  ps.review_status, ps.updated_by_user_id, ps.generated_by_run_id,
  ps.created_at, ps.updated_at
`;
const PUBLIC_SUMMARY_REDACTION_VERSION = "project_public_summary.v1";
const PUBLIC_SUMMARY_MAX_CHARS = 4000;
const WORKSPACE_ROLES = new Set([
  "primary_codebase",
  "capability_library",
  "docs",
  "data",
  "deployment",
  "reference",
]);

const MEMBER_COLUMNS = `id, space_id, project_id, user_id, role, status, created_at, updated_at`;
const PROJECT_MEMBER_ROLES = new Set(["owner", "member", "viewer"]);
const PUBLIC_SUMMARY_REVIEW_STATUSES = new Set(["draft", "approved", "archived"]);

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
    const writable = await this.loadWritableContext(identity.spaceId, identity.userId);
    const items = rows.rows.map((row) =>
      projectToOut(row, canSeeSettings(writable, identity.userId, row)),
    );
    return page(items, countFromRow(total.rows[0]), filters.limit, filters.offset);
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
    if (!row) return null;
    // settings_json is free-form per-project configuration and may hold private
    // operational detail. Only project writers (owner / space admin / project
    // owner|member) see it; other space members get a null placeholder.
    const includeSettings = await canWriteProject(this.db, identity.spaceId, projectId, identity.userId);
    return projectToOut(row, includeSettings);
  }

  async update(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
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
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
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

  async listPublicSummaries(
    identity: SpaceUserIdentity,
    filters: { limit: number; offset: number },
  ): Promise<Record<string, unknown>> {
    const params: unknown[] = [identity.spaceId];
    const clauses = [
      "ps.space_id = $1",
      "p.deleted_at IS NULL",
      "p.status = 'active'",
      "ps.review_status = 'approved'",
    ];
    const where = clauses.join(" AND ");
    const total = await this.db.query<{ total: string | number }>(
      `SELECT count(ps.id)::text AS total
         FROM project_public_summaries ps
         JOIN projects p ON p.id = ps.project_id AND p.space_id = ps.space_id
        WHERE ${where}`,
      params,
    );
    const rows = await this.db.query<ProjectPublicSummaryRow>(
      `SELECT ${PUBLIC_SUMMARY_COLUMNS}
         FROM project_public_summaries ps
         JOIN projects p ON p.id = ps.project_id AND p.space_id = ps.space_id
        WHERE ${where}
        ORDER BY ps.updated_at DESC, ps.id DESC
        LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(projectPublicSummaryToOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async getPublicSummary(
    identity: SpaceUserIdentity,
    projectId: string,
  ): Promise<Record<string, unknown> | null> {
    await this.requireProject(identity.spaceId, projectId);
    const result = await this.db.query<ProjectPublicSummaryRow>(
      `SELECT ${PUBLIC_SUMMARY_COLUMNS}
         FROM project_public_summaries ps
         JOIN projects p ON p.id = ps.project_id AND p.space_id = ps.space_id
        WHERE ps.space_id = $1
          AND ps.project_id = $2
          AND p.deleted_at IS NULL
          AND p.status = 'active'
          AND ps.review_status = 'approved'
        LIMIT 1`,
      [identity.spaceId, projectId],
    );
    const row = result.rows[0];
    return row ? projectPublicSummaryToOut(row) : null;
  }

  async upsertPublicSummary(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const summaryText = publicSummaryText(body.summary_text);
    const topics = publicStringList(body.topics_json ?? body.topics, "topics");
    const highlights = publicStringList(body.highlights_json ?? body.highlights, "highlights");
    const sourceRefs = publicSourceRefs(body.source_refs_json ?? body.source_refs);
    const redactionVersion = optionalString(body.redaction_version) ?? PUBLIC_SUMMARY_REDACTION_VERSION;
    // A bare write only stages a draft. Publishing (`approved`) or unpublishing
    // (`archived`) flips the space-public visibility of project content, so it
    // requires project-owner-level authority — a project writer/member cannot
    // self-approve their own summary.
    const reviewStatus = optionalString(body.review_status) ?? "draft";
    if (!PUBLIC_SUMMARY_REVIEW_STATUSES.has(reviewStatus)) {
      throw new HttpError(422, "review_status must be draft, approved, or archived");
    }
    if (reviewStatus !== "draft") {
      await assertProjectOwnerLevel(this.db, identity.spaceId, projectId, identity.userId);
    }
    const generatedByRunId = optionalString(body.generated_by_run_id);
    if (generatedByRunId) {
      const run = await this.db.query<{ id: string }>(
        `SELECT id FROM runs WHERE id = $1 AND space_id = $2 AND project_id = $3`,
        [generatedByRunId, identity.spaceId, projectId],
      );
      if (!run.rows[0]) throw new HttpError(422, "generated_by_run_id must reference this project in this space");
    }
    const now = new Date().toISOString();
    const result = await this.db.query<ProjectPublicSummaryRow>(
      `WITH upserted AS (
         INSERT INTO project_public_summaries (
           id, space_id, project_id, summary_text, topics_json, highlights_json,
           source_refs_json, redaction_version, review_status, updated_by_user_id,
           generated_by_run_id, created_at, updated_at
         ) VALUES (
           $1, $2, $3, $4, $5::jsonb, $6::jsonb,
           $7::jsonb, $8, $9, $10,
           $11, $12, $12
         )
         ON CONFLICT (project_id)
         DO UPDATE SET
           summary_text = EXCLUDED.summary_text,
           topics_json = EXCLUDED.topics_json,
           highlights_json = EXCLUDED.highlights_json,
           source_refs_json = EXCLUDED.source_refs_json,
           redaction_version = EXCLUDED.redaction_version,
           review_status = EXCLUDED.review_status,
           updated_by_user_id = EXCLUDED.updated_by_user_id,
           generated_by_run_id = EXCLUDED.generated_by_run_id,
           updated_at = EXCLUDED.updated_at
         RETURNING id, space_id, project_id, summary_text, topics_json,
                   highlights_json, source_refs_json, redaction_version,
                   review_status, updated_by_user_id, generated_by_run_id,
                   created_at, updated_at
       )
       SELECT ${PUBLIC_SUMMARY_COLUMNS}
         FROM upserted ps
         JOIN projects p ON p.id = ps.project_id AND p.space_id = ps.space_id`,
      [
        randomUUID(),
        identity.spaceId,
        projectId,
        summaryText,
        JSON.stringify(topics),
        JSON.stringify(highlights),
        JSON.stringify(sourceRefs),
        redactionVersion,
        reviewStatus,
        identity.userId,
        generatedByRunId,
        now,
      ],
    );
    await this.reindexPublicSummary(identity.spaceId, projectId);
    return projectPublicSummaryToOut(result.rows[0]!);
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
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
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
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    if (role && !WORKSPACE_ROLES.has(role)) throw new HttpError(422, "invalid workspace role");
    const params: unknown[] = [projectId, workspaceId];
    const clauses = ["project_id = $1", "workspace_id = $2"];
    if (role) {
      params.push(role);
      clauses.push(`role = $${params.length}`);
    }
    await this.db.query(`DELETE FROM project_workspaces WHERE ${clauses.join(" AND ")}`, params);
  }

  // --- Project membership (the project-level memory access ACL) -------------

  async listMembers(identity: SpaceUserIdentity, projectId: string): Promise<Record<string, unknown>[]> {
    await this.requireProject(identity.spaceId, projectId);
    const rows = await this.db.query<ProjectMemberRow>(
      `SELECT ${MEMBER_COLUMNS}
         FROM project_members
        WHERE space_id = $1 AND project_id = $2 AND status = 'active'
        ORDER BY created_at ASC, id ASC`,
      [identity.spaceId, projectId],
    );
    return rows.rows.map(projectMemberToOut);
  }

  async addMember(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const project = await this.requireProjectRow(identity.spaceId, projectId);
    await this.requireProjectAdmin(identity, project);
    const userId = requiredString(body.user_id, "user_id");
    const role = optionalString(body.role) ?? "member";
    if (!PROJECT_MEMBER_ROLES.has(role)) throw new HttpError(422, "invalid project member role");
    // Only an active member of the space can be added to one of its projects.
    const member = await this.db.query<{ one: number }>(
      `SELECT 1 AS one FROM space_memberships
        WHERE space_id = $1 AND user_id = $2 AND status = 'active' LIMIT 1`,
      [identity.spaceId, userId],
    );
    if (!member.rows[0]) throw new HttpError(422, "user is not an active member of this space");
    const now = new Date().toISOString();
    const result = await this.db.query<ProjectMemberRow>(
      `INSERT INTO project_members (id, space_id, project_id, user_id, role, status, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, 'active', $6, $6)
       ON CONFLICT (project_id, user_id)
       DO UPDATE SET role = EXCLUDED.role, status = 'active', updated_at = EXCLUDED.updated_at
       RETURNING ${MEMBER_COLUMNS}`,
      [randomUUID(), identity.spaceId, projectId, userId, role, now],
    );
    return projectMemberToOut(result.rows[0]!);
  }

  async removeMember(identity: SpaceUserIdentity, projectId: string, userId: string): Promise<void> {
    const project = await this.requireProjectRow(identity.spaceId, projectId);
    await this.requireProjectAdmin(identity, project);
    await this.db.query(
      `DELETE FROM project_members WHERE space_id = $1 AND project_id = $2 AND user_id = $3`,
      [identity.spaceId, projectId, userId],
    );
  }

  /** Mutating project membership requires the project owner or a space owner/admin. */
  private async requireProjectAdmin(identity: SpaceUserIdentity, project: ProjectRow): Promise<void> {
    if (project.owner_user_id && project.owner_user_id === identity.userId) return;
    const role = await this.db.query<{ role: string }>(
      `SELECT role FROM space_memberships
        WHERE space_id = $1 AND user_id = $2 AND status = 'active' LIMIT 1`,
      [identity.spaceId, identity.userId],
    );
    const spaceRole = role.rows[0]?.role;
    if (spaceRole === "owner" || spaceRole === "admin") return;
    throw new HttpError(403, "Requires project owner or space owner/admin role");
  }

  private async requireProjectRow(spaceId: string, projectId: string): Promise<ProjectRow> {
    const row = await this.getRow(spaceId, projectId);
    if (!row) throw new HttpError(404, "Project not found");
    return row;
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

  /**
   * Resolve which projects a user may see `settings_json` for, in two queries.
   * Space owner/admin sees all; otherwise only projects they own or are an
   * active `owner`/`member` of. Project ownership is checked per-row by the
   * caller against `owner_user_id`.
   */
  private async loadWritableContext(spaceId: string, userId: string): Promise<WritableContext> {
    const role = await this.db.query<{ role: string }>(
      `SELECT role FROM space_memberships
        WHERE space_id = $1 AND user_id = $2 AND status = 'active' LIMIT 1`,
      [spaceId, userId],
    );
    const spaceRole = role.rows[0]?.role;
    if (spaceRole === "owner" || spaceRole === "admin") {
      return { spaceAdmin: true, memberProjectIds: new Set() };
    }
    const members = await this.db.query<{ project_id: string }>(
      `SELECT project_id FROM project_members
        WHERE space_id = $1 AND user_id = $2 AND status = 'active'
          AND role IN ('owner', 'member')`,
      [spaceId, userId],
    );
    return {
      spaceAdmin: false,
      memberProjectIds: new Set(members.rows.map((row) => row.project_id)),
    };
  }

  private async reindexPublicSummary(spaceId: string, projectId: string): Promise<void> {
    try {
      await new RetrievalProjectionService(this.db, projectRetrievalRegistry)
        .reindex(spaceId, "project_public_summary", projectId);
    } catch (error) {
      process.stderr.write(
        `[projects.retrieval] public summary reindex failed: ${String((error as Error)?.message ?? error)}\n`,
      );
    }
  }

  private async count(table: string, spaceId: string, projectId: string): Promise<{ rows: Array<{ total?: unknown }> }> {
    return this.db.query<{ total: string | number }>(
      `SELECT count(id)::text AS total FROM ${table} WHERE space_id = $1 AND project_id = $2`,
      [spaceId, projectId],
    );
  }
}

interface WritableContext {
  spaceAdmin: boolean;
  memberProjectIds: Set<string>;
}

function canSeeSettings(ctx: WritableContext, userId: string, row: ProjectRow): boolean {
  if (ctx.spaceAdmin) return true;
  if (row.owner_user_id && row.owner_user_id === userId) return true;
  return ctx.memberProjectIds.has(row.id);
}

function projectToOut(row: ProjectRow, includeSettings = true): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    owner_user_id: row.owner_user_id,
    name: row.name,
    description: row.description,
    status: row.status === "deleted" ? "archived" : row.status,
    current_focus: row.current_focus,
    settings_json: includeSettings
      ? (row.settings_json === null ? null : objectValue(row.settings_json))
      : null,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
    archived_at: dateIso(row.archived_at),
  };
}

function projectMemberToOut(row: ProjectMemberRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    project_id: row.project_id,
    user_id: row.user_id,
    role: row.role,
    status: row.status,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
  };
}

function projectPublicSummaryToOut(row: ProjectPublicSummaryRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    project_id: row.project_id,
    project_name: row.project_name,
    summary_text: row.summary_text,
    topics: stringArray(row.topics_json),
    highlights: stringArray(row.highlights_json),
    source_refs: Array.isArray(row.source_refs_json) ? row.source_refs_json : [],
    redaction_version: row.redaction_version,
    review_status: row.review_status,
    updated_by_user_id: row.updated_by_user_id,
    generated_by_run_id: row.generated_by_run_id,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
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

function publicSummaryText(value: unknown): string {
  const text = requiredString(value, "summary_text");
  if (text.length > PUBLIC_SUMMARY_MAX_CHARS) {
    throw new HttpError(422, `summary_text must be ${PUBLIC_SUMMARY_MAX_CHARS} characters or fewer`);
  }
  return text;
}

function publicStringList(value: unknown, field: string): string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new HttpError(422, `${field} must be an array`);
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item !== "string") throw new HttpError(422, `${field} entries must be strings`);
    const normalized = item.trim();
    if (!normalized) continue;
    if (normalized.length > 120) throw new HttpError(422, `${field} entries must be 120 characters or fewer`);
    const key = normalized.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      out.push(normalized);
    }
  }
  if (out.length > 32) throw new HttpError(422, `${field} must contain at most 32 entries`);
  return out;
}

function publicSourceRefs(value: unknown): Array<Record<string, string>> {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new HttpError(422, "source_refs must be an array");
  if (value.length > 50) throw new HttpError(422, "source_refs must contain at most 50 entries");
  return value.map((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new HttpError(422, "source_refs entries must be objects");
    }
    const record = entry as Record<string, unknown>;
    const out: Record<string, string> = {};
    for (const key of ["source_type", "source_id", "label", "trust_level"]) {
      const text = optionalString(record[key]);
      if (text) out[key] = text.slice(0, 256);
    }
    if (!out.source_type || !out.source_id) {
      throw new HttpError(422, "source_refs entries require source_type and source_id");
    }
    return out;
  });
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}
