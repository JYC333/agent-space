import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  HttpError,
  dbPool,
  dateIso,
  jsonBody,
  objectValue,
  optionalObject,
  optionalString,
  params,
  parsePage,
  query,
  resolveIdentity,
  sendRouteError,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";

interface TargetRow {
  id: string;
  space_id: string | null;
  target_type: string;
  target_ref_type: string | null;
  target_ref_id: string | null;
  capability_key: string | null;
  current_version_id: string | null;
  risk_level: string;
  status: string;
  enabled: boolean;
  engine_policy_json: unknown;
  metadata_json: unknown;
  created_at: unknown;
  updated_at: unknown;
  recent_signal_count?: string | number;
}

interface SignalRow {
  id: string;
  space_id: string | null;
  target_id: string;
  target_name: string | null;
  target_type: string | null;
  capability_key: string | null;
  signal_type: string;
  source_type: string;
  source_id: string | null;
  severity: string;
  summary: string | null;
  payload_json: unknown;
  created_at: unknown;
}

const TARGET_COLUMNS = `
  id, space_id, target_type, target_ref_type, target_ref_id, capability_key,
  current_version_id, risk_level, status, enabled, engine_policy_json,
  metadata_json, created_at, updated_at
`;

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => new EvolutionRepository(dbPool(context.config));

  app.get("/api/v1/evolution/summary", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().summary(identity));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/evolution/targets", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listTargets(identity, optionalString(query(request).status)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/evolution/targets", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().createTarget(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/evolution/targets/:targetId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const target = await repository().getTarget(identity, params(request).targetId ?? "");
      if (!target) return reply.code(404).send({ detail: "Evolution target not found" });
      return reply.send(target);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/evolution/targets/:targetId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().updateTarget(identity, params(request).targetId ?? "", jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/evolution/signals", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request), 50);
      return reply.send(await repository().listSignals(identity, null, limit, offset));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/evolution/targets/:targetId/signals", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request), 50);
      return reply.send(await repository().listSignals(identity, params(request).targetId ?? "", limit, offset));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/evolution/targets/:targetId/signals", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().createSignal(identity, params(request).targetId ?? "", jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/evolution/runs", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request), 50);
      return reply.send(await repository().listRuns(identity, limit, offset));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/evolution/targets/:targetId/run", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().recordRunRequest(identity, params(request).targetId ?? "", jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/evolution/proposals", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request), 50);
      return reply.send(await repository().listProposals(identity, limit, offset));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/evolution/validation", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    return reply.send([]);
  });
}

class EvolutionRepository {
  constructor(private readonly db: Queryable) {}

  async summary(identity: SpaceUserIdentity): Promise<Record<string, unknown>> {
    const [targets, signals, proposals, runs] = await Promise.all([
      this.db.query<{ total: string | number }>(
        `SELECT count(id)::text AS total FROM evolution_targets WHERE (space_id = $1 OR space_id IS NULL) AND status = 'active'`,
        [identity.spaceId],
      ),
      this.db.query<{ total: string | number }>(
        `SELECT count(es.id)::text AS total
           FROM evolution_signals es
           JOIN evolution_targets et ON et.id = es.target_id
          WHERE et.space_id = $1 OR et.space_id IS NULL`,
        [identity.spaceId],
      ),
      this.db.query<{ total: string | number }>(
        `SELECT count(id)::text AS total
           FROM proposals
          WHERE space_id = $1 AND status = 'pending' AND proposal_type LIKE 'evolution_%'`,
        [identity.spaceId],
      ),
      this.db.query<{ total: string | number }>(
        `SELECT count(id)::text AS total
           FROM runs
          WHERE space_id = $1 AND run_type = 'evolution' AND created_at > now() - interval '30 days'`,
        [identity.spaceId],
      ),
    ]);
    return {
      active_targets: count(targets.rows[0]),
      signals_collected: count(signals.rows[0]),
      pending_proposals: count(proposals.rows[0]),
      recent_runs: count(runs.rows[0]),
    };
  }

  async listTargets(identity: SpaceUserIdentity, status: string | null): Promise<Record<string, unknown>[]> {
    const paramsList: unknown[] = [identity.spaceId];
    const clauses = ["(et.space_id = $1 OR et.space_id IS NULL)"];
    if (status) {
      paramsList.push(status);
      clauses.push(`et.status = $${paramsList.length}`);
    }
    const rows = await this.db.query<TargetRow>(
      `SELECT et.${TARGET_COLUMNS.replaceAll(", ", ", et.")},
              (SELECT count(es.id)::text FROM evolution_signals es WHERE es.target_id = et.id) AS recent_signal_count
         FROM evolution_targets et
        WHERE ${clauses.join(" AND ")}
        ORDER BY et.updated_at DESC, et.created_at DESC`,
      paramsList,
    );
    return rows.rows.map(targetToOut);
  }

  async getTarget(identity: SpaceUserIdentity, targetId: string): Promise<Record<string, unknown> | null> {
    const rows = await this.db.query<TargetRow>(
      `SELECT et.${TARGET_COLUMNS.replaceAll(", ", ", et.")},
              (SELECT count(es.id)::text FROM evolution_signals es WHERE es.target_id = et.id) AS recent_signal_count
         FROM evolution_targets et
        WHERE et.id = $1 AND (et.space_id = $2 OR et.space_id IS NULL)
        LIMIT 1`,
      [targetId, identity.spaceId],
    );
    return rows.rows[0] ? targetToOut(rows.rows[0]) : null;
  }

  async createTarget(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const now = new Date().toISOString();
    const metadata = {
      ...objectValue(body.metadata_json),
      target_name: optionalString(body.target_name),
      purpose: optionalString(body.purpose),
    };
    const result = await this.db.query<TargetRow>(
      `INSERT INTO evolution_targets (
         id, space_id, target_type, target_ref_type, target_ref_id, capability_key,
         current_version_id, risk_level, status, enabled, engine_policy_json,
         metadata_json, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8, $9, $10, $11::jsonb,
         $12::jsonb, $13, $13
       )
       RETURNING ${TARGET_COLUMNS}, 0::text AS recent_signal_count`,
      [
        randomUUID(),
        identity.spaceId,
        requiredBodyString(body.target_type, "target_type"),
        optionalString(body.target_ref_type),
        optionalString(body.target_ref_id),
        optionalString(body.capability_key),
        optionalString(body.current_version_id),
        optionalString(body.risk_level) ?? "medium",
        optionalString(body.status) ?? "active",
        body.enabled !== false,
        JSON.stringify(optionalObject(body.engine_policy_json) ?? {}),
        JSON.stringify(metadata),
        now,
      ],
    );
    return targetToOut(result.rows[0]!);
  }

  async updateTarget(identity: SpaceUserIdentity, targetId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const current = await this.getTarget(identity, targetId);
    if (!current) throw new HttpError(404, "Evolution target not found");
    const currentMeta = objectValue((current as { metadata_json?: unknown }).metadata_json);
    const metadata = {
      ...currentMeta,
      ...objectValue(body.metadata_json),
      ...(body.target_name !== undefined ? { target_name: optionalString(body.target_name) } : {}),
      ...(body.purpose !== undefined ? { purpose: optionalString(body.purpose) } : {}),
    };
    const now = new Date().toISOString();
    const result = await this.db.query<TargetRow>(
      `UPDATE evolution_targets
          SET target_type = COALESCE($3, target_type),
              target_ref_type = CASE WHEN $4::boolean THEN $5 ELSE target_ref_type END,
              target_ref_id = CASE WHEN $6::boolean THEN $7 ELSE target_ref_id END,
              capability_key = CASE WHEN $8::boolean THEN $9 ELSE capability_key END,
              current_version_id = CASE WHEN $10::boolean THEN $11 ELSE current_version_id END,
              risk_level = COALESCE($12, risk_level),
              status = COALESCE($13, status),
              enabled = COALESCE($14, enabled),
              engine_policy_json = CASE WHEN $15::boolean THEN $16::jsonb ELSE engine_policy_json END,
              metadata_json = $17::jsonb,
              updated_at = $18
        WHERE id = $1 AND (space_id = $2 OR space_id IS NULL)
        RETURNING ${TARGET_COLUMNS},
                  (SELECT count(es.id)::text FROM evolution_signals es WHERE es.target_id = evolution_targets.id) AS recent_signal_count`,
      [
        targetId,
        identity.spaceId,
        optionalString(body.target_type),
        Object.hasOwn(body, "target_ref_type"),
        optionalString(body.target_ref_type),
        Object.hasOwn(body, "target_ref_id"),
        optionalString(body.target_ref_id),
        Object.hasOwn(body, "capability_key"),
        optionalString(body.capability_key),
        Object.hasOwn(body, "current_version_id"),
        optionalString(body.current_version_id),
        optionalString(body.risk_level),
        optionalString(body.status),
        typeof body.enabled === "boolean" ? body.enabled : null,
        Object.hasOwn(body, "engine_policy_json"),
        JSON.stringify(optionalObject(body.engine_policy_json) ?? {}),
        JSON.stringify(metadata),
        now,
      ],
    );
    return targetToOut(result.rows[0]!);
  }

  async listSignals(
    identity: SpaceUserIdentity,
    targetId: string | null,
    limit: number,
    offset: number,
  ): Promise<Record<string, unknown>[]> {
    const values: unknown[] = [identity.spaceId];
    const clauses = ["(et.space_id = $1 OR et.space_id IS NULL)"];
    if (targetId) {
      values.push(targetId);
      clauses.push(`es.target_id = $${values.length}`);
    }
    const rows = await this.db.query<SignalRow>(
      `SELECT es.id, es.space_id, es.target_id,
              et.target_type, et.capability_key,
              et.metadata_json->>'target_name' AS target_name,
              es.signal_type, es.source_type, es.source_id, es.severity,
              es.summary, es.payload_json, es.created_at
         FROM evolution_signals es
         JOIN evolution_targets et ON et.id = es.target_id
        WHERE ${clauses.join(" AND ")}
        ORDER BY es.created_at DESC, es.id DESC
        LIMIT $${values.length + 1} OFFSET $${values.length + 2}`,
      [...values, limit, offset],
    );
    return rows.rows.map(signalToOut);
  }

  async createSignal(identity: SpaceUserIdentity, targetId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const target = await this.getTarget(identity, targetId);
    if (!target) throw new HttpError(404, "Evolution target not found");
    const now = new Date().toISOString();
    const result = await this.db.query<SignalRow>(
      `WITH inserted AS (
         INSERT INTO evolution_signals (
           id, space_id, target_id, signal_type, source_type, source_id,
           severity, summary, payload_json, created_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
         RETURNING id, space_id, target_id, signal_type, source_type, source_id,
                   severity, summary, payload_json, created_at
       )
       SELECT i.id, i.space_id, i.target_id,
              et.target_type, et.capability_key, et.metadata_json->>'target_name' AS target_name,
              i.signal_type, i.source_type, i.source_id, i.severity, i.summary,
              i.payload_json, i.created_at
         FROM inserted i
         JOIN evolution_targets et ON et.id = i.target_id`,
      [
        randomUUID(),
        identity.spaceId,
        targetId,
        requiredBodyString(body.signal_type, "signal_type"),
        requiredBodyString(body.source_type, "source_type"),
        optionalString(body.source_id),
        optionalString(body.severity) ?? "info",
        optionalString(body.summary),
        JSON.stringify(optionalObject(body.payload_json) ?? {}),
        now,
      ],
    );
    return signalToOut(result.rows[0]!);
  }

  async listRuns(identity: SpaceUserIdentity, limit: number, offset: number): Promise<Record<string, unknown>[]> {
    const rows = await this.db.query<Record<string, unknown>>(
      `SELECT r.id AS run_id, NULL::varchar AS target_id, NULL::varchar AS target_name,
              NULL::varchar AS target_type, NULL::varchar AS capability_key,
              r.adapter_type AS engine, r.status, r.created_at, r.started_at,
              (SELECT count(a.id)::int FROM artifacts a WHERE a.run_id = r.id AND a.space_id = r.space_id) AS artifact_count,
              NULL::varchar AS proposal_id
         FROM runs r
        WHERE r.space_id = $1 AND r.run_type = 'evolution'
        ORDER BY r.created_at DESC
        LIMIT $2 OFFSET $3`,
      [identity.spaceId, limit, offset],
    );
    return rows.rows.map((row) => ({
      run_id: row.run_id,
      target_id: row.target_id,
      target_name: row.target_name,
      target_type: row.target_type,
      capability_key: row.capability_key,
      engine: row.engine,
      status: row.status,
      created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
      started_at: dateIso(row.started_at),
      artifact_count: Number(row.artifact_count ?? 0),
      proposal_id: row.proposal_id,
    }));
  }

  async recordRunRequest(identity: SpaceUserIdentity, targetId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const target = await this.getTarget(identity, targetId);
    if (!target) throw new HttpError(404, "Evolution target not found");
    const runId = randomUUID();
    const signal = await this.createSignal(identity, targetId, {
      signal_type: "review_requested",
      source_type: "manual",
      source_id: runId,
      severity: "info",
      summary: `Review requested with ${optionalString(body.engine) ?? "default"} engine.`,
      payload_json: { engine: optionalString(body.engine) ?? null, run_id: runId },
    });
    return {
      run_id: runId,
      target_id: targetId,
      context_artifact_id: "",
      report_artifact_id: "",
      revision_artifact_id: "",
      proposal_id: "",
      proposal_type: "evolution_review",
      run_status: "succeeded",
      signal_id: signal.id,
    };
  }

  async listProposals(identity: SpaceUserIdentity, limit: number, offset: number): Promise<Record<string, unknown>[]> {
    const rows = await this.db.query<Record<string, unknown>>(
      `SELECT p.id, p.proposal_type, p.status, p.summary, p.created_at, p.created_by_run_id,
              NULL::varchar AS target_id, NULL::varchar AS target_name,
              NULL::varchar AS target_type, NULL::varchar AS capability_key
         FROM proposals p
        WHERE p.space_id = $1 AND p.proposal_type LIKE 'evolution_%'
        ORDER BY p.created_at DESC
        LIMIT $2 OFFSET $3`,
      [identity.spaceId, limit, offset],
    );
    return rows.rows.map((row) => ({
      id: row.id,
      proposal_type: row.proposal_type,
      target_id: row.target_id,
      target_name: row.target_name,
      target_type: row.target_type,
      capability_key: row.capability_key,
      status: row.status,
      summary: row.summary,
      created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
      created_by_run_id: row.created_by_run_id,
    }));
  }
}

function targetToOut(row: TargetRow): Record<string, unknown> {
  const metadata = objectValue(row.metadata_json);
  return {
    id: row.id,
    space_id: row.space_id,
    target_name: optionalString(metadata.target_name),
    target_type: row.target_type,
    target_ref_type: row.target_ref_type,
    target_ref_id: row.target_ref_id,
    capability_key: row.capability_key,
    current_version_id: row.current_version_id,
    current_version: optionalString(metadata.current_version),
    scope: optionalString(metadata.scope) ?? (row.space_id ? "space" : "system"),
    purpose: optionalString(metadata.purpose),
    risk_level: row.risk_level,
    status: row.status,
    enabled: row.enabled,
    recent_signal_count: count(row),
    last_run_at: null,
    engine_policy_json: objectValue(row.engine_policy_json),
    metadata_json: metadata,
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
  };
}

function signalToOut(row: SignalRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    target_id: row.target_id,
    target_name: row.target_name,
    target_type: row.target_type,
    capability_key: row.capability_key,
    signal_type: row.signal_type,
    source_type: row.source_type,
    source_id: row.source_id,
    severity: row.severity,
    summary: row.summary,
    payload_json: objectValue(row.payload_json),
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
  };
}

function requiredBodyString(value: unknown, field: string): string {
  const text = optionalString(value);
  if (!text) throw new HttpError(422, `${field} is required`);
  return text;
}

function count(row: { total?: unknown; recent_signal_count?: unknown } | undefined): number {
  const value = row?.total ?? row?.recent_signal_count;
  if (typeof value === "number") return value;
  if (typeof value === "string") return Number(value);
  return 0;
}
