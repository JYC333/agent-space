import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  HttpError,
  dateIso,
  dbPool,
  jsonBody,
  objectValue,
  optionalString,
  params,
  query,
  requiredString,
  resolveIdentity,
  sendRouteError,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";

interface WorkspaceProfileRow {
  id: string;
  space_id: string;
  workspace_id: string;
  repo_type: string | null;
  tech_stack_json: unknown;
  important_paths_json: unknown;
  forbidden_paths_json: unknown;
  test_commands_json: unknown;
  build_commands_json: unknown;
  architecture_boundaries_json: unknown;
  current_focus: string | null;
  known_failures_json: unknown;
  validation_recipe_id: string | null;
  cloud_allowed: boolean;
  max_data_exposure_level: string | null;
  min_observability_level: string | null;
  created_at: unknown;
  updated_at: unknown;
}

const COLUMNS = `
  id, space_id, workspace_id, repo_type, tech_stack_json, important_paths_json,
  forbidden_paths_json, test_commands_json, build_commands_json,
  architecture_boundaries_json, current_focus, known_failures_json,
  validation_recipe_id, cloud_allowed, max_data_exposure_level,
  min_observability_level, created_at, updated_at
`;

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => new WorkspaceProfileRepository(dbPool(context.config));

  app.get("/api/v1/workspace-profiles", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().list(identity, query(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/workspace-profiles", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().create(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspace-profiles/:profileId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const row = await repository().get(identity, params(request).profileId ?? "");
      if (!row) return reply.code(404).send({ detail: "Workspace profile not found" });
      return reply.send(row);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/workspace-profiles/:profileId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository().update(identity, params(request).profileId ?? "", jsonBody(request)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}

class WorkspaceProfileRepository {
  constructor(private readonly db: Queryable) {}

  async list(
    identity: SpaceUserIdentity,
    filters: Record<string, string | undefined>,
  ): Promise<Record<string, unknown>[]> {
    const values: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    const workspaceId = optionalString(filters.workspace_id);
    if (workspaceId) {
      values.push(workspaceId);
      clauses.push(`workspace_id = $${values.length}`);
    }
    const rows = await this.db.query<WorkspaceProfileRow>(
      `SELECT ${COLUMNS}
         FROM workspace_profiles
        WHERE ${clauses.join(" AND ")}
        ORDER BY updated_at DESC, id DESC`,
      values,
    );
    return rows.rows.map(out);
  }

  async get(identity: SpaceUserIdentity, profileId: string): Promise<Record<string, unknown> | null> {
    const rows = await this.db.query<WorkspaceProfileRow>(
      `SELECT ${COLUMNS}
         FROM workspace_profiles
        WHERE id = $1 AND space_id = $2
        LIMIT 1`,
      [profileId, identity.spaceId],
    );
    return rows.rows[0] ? out(rows.rows[0]) : null;
  }

  async create(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const workspaceId = requiredString(body.workspace_id, "workspace_id");
    await this.requireWorkspace(identity, workspaceId);
    const now = new Date().toISOString();
    const rows = await this.db.query<WorkspaceProfileRow>(
      `INSERT INTO workspace_profiles (
         id, space_id, workspace_id, repo_type, tech_stack_json,
         important_paths_json, forbidden_paths_json, test_commands_json,
         build_commands_json, architecture_boundaries_json, current_focus,
         known_failures_json, validation_recipe_id, cloud_allowed,
         max_data_exposure_level, min_observability_level, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5::jsonb,
         $6::jsonb, $7::jsonb, $8::jsonb,
         $9::jsonb, $10::jsonb, $11,
         $12::jsonb, $13, $14,
         $15, $16, $17, $17
       )
       RETURNING ${COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        workspaceId,
        optionalString(body.repo_type),
        json(body.tech_stack_json, []),
        json(body.important_paths_json, []),
        json(body.forbidden_paths_json, []),
        json(body.test_commands_json, []),
        json(body.build_commands_json, []),
        json(body.architecture_boundaries_json, {}),
        optionalString(body.current_focus),
        json(body.known_failures_json, []),
        optionalString(body.validation_recipe_id),
        body.cloud_allowed === true,
        optionalString(body.max_data_exposure_level),
        optionalString(body.min_observability_level),
        now,
      ],
    );
    return out(rows.rows[0]!);
  }

  async update(
    identity: SpaceUserIdentity,
    profileId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const current = await this.get(identity, profileId);
    if (!current) throw new HttpError(404, "Workspace profile not found");
    const now = new Date().toISOString();
    const rows = await this.db.query<WorkspaceProfileRow>(
      `UPDATE workspace_profiles
          SET repo_type = CASE WHEN $3::boolean THEN $4 ELSE repo_type END,
              tech_stack_json = CASE WHEN $5::boolean THEN $6::jsonb ELSE tech_stack_json END,
              important_paths_json = CASE WHEN $7::boolean THEN $8::jsonb ELSE important_paths_json END,
              forbidden_paths_json = CASE WHEN $9::boolean THEN $10::jsonb ELSE forbidden_paths_json END,
              test_commands_json = CASE WHEN $11::boolean THEN $12::jsonb ELSE test_commands_json END,
              build_commands_json = CASE WHEN $13::boolean THEN $14::jsonb ELSE build_commands_json END,
              architecture_boundaries_json = CASE WHEN $15::boolean THEN $16::jsonb ELSE architecture_boundaries_json END,
              current_focus = CASE WHEN $17::boolean THEN $18 ELSE current_focus END,
              known_failures_json = CASE WHEN $19::boolean THEN $20::jsonb ELSE known_failures_json END,
              validation_recipe_id = CASE WHEN $21::boolean THEN $22 ELSE validation_recipe_id END,
              cloud_allowed = COALESCE($23::boolean, cloud_allowed),
              max_data_exposure_level = CASE WHEN $24::boolean THEN $25 ELSE max_data_exposure_level END,
              min_observability_level = CASE WHEN $26::boolean THEN $27 ELSE min_observability_level END,
              updated_at = $28
        WHERE id = $1 AND space_id = $2
        RETURNING ${COLUMNS}`,
      [
        profileId,
        identity.spaceId,
        Object.hasOwn(body, "repo_type"),
        optionalString(body.repo_type),
        Object.hasOwn(body, "tech_stack_json"),
        json(body.tech_stack_json, []),
        Object.hasOwn(body, "important_paths_json"),
        json(body.important_paths_json, []),
        Object.hasOwn(body, "forbidden_paths_json"),
        json(body.forbidden_paths_json, []),
        Object.hasOwn(body, "test_commands_json"),
        json(body.test_commands_json, []),
        Object.hasOwn(body, "build_commands_json"),
        json(body.build_commands_json, []),
        Object.hasOwn(body, "architecture_boundaries_json"),
        json(body.architecture_boundaries_json, {}),
        Object.hasOwn(body, "current_focus"),
        optionalString(body.current_focus),
        Object.hasOwn(body, "known_failures_json"),
        json(body.known_failures_json, []),
        Object.hasOwn(body, "validation_recipe_id"),
        optionalString(body.validation_recipe_id),
        typeof body.cloud_allowed === "boolean" ? body.cloud_allowed : null,
        Object.hasOwn(body, "max_data_exposure_level"),
        optionalString(body.max_data_exposure_level),
        Object.hasOwn(body, "min_observability_level"),
        optionalString(body.min_observability_level),
        now,
      ],
    );
    return out(rows.rows[0]!);
  }

  private async requireWorkspace(identity: SpaceUserIdentity, workspaceId: string): Promise<void> {
    const rows = await this.db.query<{ id: string }>(
      `SELECT id FROM workspaces WHERE id = $1 AND space_id = $2 LIMIT 1`,
      [workspaceId, identity.spaceId],
    );
    if (!rows.rows[0]) throw new HttpError(404, "Workspace not found");
  }
}

function json(value: unknown, fallback: unknown): string {
  return JSON.stringify(value === undefined ? fallback : value);
}

function out(row: WorkspaceProfileRow): Record<string, unknown> {
  return {
    ...row,
    tech_stack_json: objectValue(row.tech_stack_json),
    important_paths_json: row.important_paths_json ?? [],
    forbidden_paths_json: row.forbidden_paths_json ?? [],
    test_commands_json: row.test_commands_json ?? [],
    build_commands_json: row.build_commands_json ?? [],
    architecture_boundaries_json: objectValue(row.architecture_boundaries_json),
    known_failures_json: row.known_failures_json ?? [],
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}
