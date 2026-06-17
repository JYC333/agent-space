import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  HttpError,
  dateIso,
  dbPool,
  jsonBody,
  objectValue,
  optionalObject,
  optionalString,
  params,
  query,
  requiredString,
  resolveIdentity,
  sendRouteError,
  toDbDate,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";

interface SourcePointerRow {
  id: string;
  owner_space_id: string;
  source_space_id: string;
  source_object_type: string;
  source_object_id: string;
  access_mode: string;
  granted_by_user_id: string | null;
  expires_at: unknown;
  metadata_json: unknown;
  created_at: unknown;
}

const COLUMNS = `
  id, owner_space_id, source_space_id, source_object_type, source_object_id,
  access_mode, granted_by_user_id, expires_at, metadata_json, created_at
`;
const ACCESS_MODES = new Set(["read", "subscribe", "federated"]);

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => new SourcePointerRepository(dbPool(context.config));

  app.get("/api/v1/source-pointers", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().list(identity, query(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/source-pointers", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().create(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/source-pointers/:pointerId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      await repository().delete(identity, params(request).pointerId ?? "");
      return reply.code(204).send();
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}

class SourcePointerRepository {
  constructor(private readonly db: Queryable) {}

  async list(
    identity: SpaceUserIdentity,
    filters: Record<string, string | undefined>,
  ): Promise<Record<string, unknown>[]> {
    const values: unknown[] = [identity.spaceId];
    const clauses = ["owner_space_id = $1", "(expires_at IS NULL OR expires_at > now())"];
    for (const [queryKey, column] of [
      ["source_space_id", "source_space_id"],
      ["source_object_type", "source_object_type"],
      ["source_object_id", "source_object_id"],
      ["access_mode", "access_mode"],
    ] as const) {
      const value = optionalString(filters[queryKey]);
      if (!value) continue;
      values.push(value);
      clauses.push(`${column} = $${values.length}`);
    }
    const rows = await this.db.query<SourcePointerRow>(
      `SELECT ${COLUMNS}
         FROM source_pointers
        WHERE ${clauses.join(" AND ")}
        ORDER BY created_at DESC, id DESC`,
      values,
    );
    return rows.rows.map(out);
  }

  async create(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const accessMode = optionalString(body.access_mode) ?? "read";
    if (!ACCESS_MODES.has(accessMode)) throw new HttpError(422, "invalid access_mode");
    const now = new Date().toISOString();
    const rows = await this.db.query<SourcePointerRow>(
      `INSERT INTO source_pointers (
         id, owner_space_id, source_space_id, source_object_type, source_object_id,
         access_mode, granted_by_user_id, expires_at, metadata_json, created_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
       RETURNING ${COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        requiredString(body.source_space_id, "source_space_id"),
        requiredString(body.source_object_type, "source_object_type"),
        requiredString(body.source_object_id, "source_object_id"),
        accessMode,
        identity.userId,
        toDbDate(body.expires_at),
        JSON.stringify(optionalObject(body.metadata_json) ?? {}),
        now,
      ],
    );
    return out(rows.rows[0]!);
  }

  async delete(identity: SpaceUserIdentity, pointerId: string): Promise<void> {
    const result = await this.db.query(
      `DELETE FROM source_pointers WHERE id = $1 AND owner_space_id = $2`,
      [pointerId, identity.spaceId],
    );
    if ((result.rowCount ?? 0) === 0) throw new HttpError(404, "Source pointer not found");
  }
}

function out(row: SourcePointerRow): Record<string, unknown> {
  return {
    ...row,
    expires_at: dateIso(row.expires_at),
    metadata_json: objectValue(row.metadata_json),
    created_at: dateIso(row.created_at),
  };
}
