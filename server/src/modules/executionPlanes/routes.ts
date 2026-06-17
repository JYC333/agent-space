import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  boolQuery,
  dateIso,
  dbPool,
  objectValue,
  optionalString,
  params,
  query,
  resolveIdentity,
  sendRouteError,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";

interface ExecutionPlaneRow {
  id: string;
  space_id: string;
  name: string;
  type: string;
  provider: string;
  execution_location: string;
  runtime_origin: string;
  trust_level: string;
  observability_level: string;
  data_exposure_level: string;
  credential_mode: string;
  config_json: unknown;
  enabled: boolean;
  created_at: unknown;
  updated_at: unknown;
}

const COLUMNS = `
  id, space_id, name, type, provider, execution_location, runtime_origin,
  trust_level, observability_level, data_exposure_level, credential_mode,
  config_json, enabled, created_at, updated_at
`;

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => new ExecutionPlaneRepository(dbPool(context.config));

  app.get("/api/v1/execution-planes", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().list(identity, query(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/execution-planes/:planeId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const row = await repository().get(identity, params(request).planeId ?? "");
      if (!row) return reply.code(404).send({ detail: "Execution plane not found" });
      return reply.send(row);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}

class ExecutionPlaneRepository {
  constructor(private readonly db: Queryable) {}

  async list(
    identity: SpaceUserIdentity,
    filters: Record<string, string | undefined>,
  ): Promise<Record<string, unknown>[]> {
    const values: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    const enabled = filters.enabled === undefined ? null : boolQuery(filters.enabled);
    if (enabled !== null) {
      values.push(enabled);
      clauses.push(`enabled = $${values.length}`);
    }
    const type = optionalString(filters.type);
    if (type) {
      values.push(type);
      clauses.push(`type = $${values.length}`);
    }
    const rows = await this.db.query<ExecutionPlaneRow>(
      `SELECT ${COLUMNS}
         FROM execution_planes
        WHERE ${clauses.join(" AND ")}
        ORDER BY enabled DESC, name ASC, id ASC`,
      values,
    );
    return rows.rows.map(out);
  }

  async get(identity: SpaceUserIdentity, planeId: string): Promise<Record<string, unknown> | null> {
    const rows = await this.db.query<ExecutionPlaneRow>(
      `SELECT ${COLUMNS}
         FROM execution_planes
        WHERE id = $1 AND space_id = $2
        LIMIT 1`,
      [planeId, identity.spaceId],
    );
    return rows.rows[0] ? out(rows.rows[0]) : null;
  }
}

function out(row: ExecutionPlaneRow): Record<string, unknown> {
  return {
    ...row,
    config_json: objectValue(row.config_json),
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}
