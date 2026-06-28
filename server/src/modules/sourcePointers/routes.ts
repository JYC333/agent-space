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
const CREATE_FIELDS = new Set([
  "source_space_id",
  "source_object_type",
  "source_object_id",
  "access_mode",
  "expires_at",
  "metadata_json",
]);
const SOURCE_OBJECT_QUERIES: Record<string, string> = {
  memory_entry: "SELECT 1 FROM memory_entries WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL LIMIT 1",
  artifact: "SELECT 1 FROM artifacts WHERE space_id = $1 AND id = $2 LIMIT 1",
  activity_record: "SELECT 1 FROM activity_records WHERE space_id = $1 AND id = $2 LIMIT 1",
  run: "SELECT 1 FROM runs WHERE space_id = $1 AND id = $2 LIMIT 1",
  proposal: "SELECT 1 FROM proposals WHERE space_id = $1 AND id = $2 LIMIT 1",
  knowledge_item: "SELECT 1 FROM knowledge_items WHERE space_id = $1 AND object_id = $2 LIMIT 1",
  note: "SELECT 1 FROM notes WHERE space_id = $1 AND object_id = $2 LIMIT 1",
  source: "SELECT 1 FROM sources WHERE space_id = $1 AND object_id = $2 LIMIT 1",
  claim: "SELECT 1 FROM claims WHERE space_id = $1 AND object_id = $2 LIMIT 1",
  project: "SELECT 1 FROM projects WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL LIMIT 1",
  workspace: "SELECT 1 FROM workspaces WHERE space_id = $1 AND id = $2 LIMIT 1",
};
const CONTENT_METADATA_KEYS = new Set([
  "body",
  "content",
  "diff",
  "file_content",
  "generated_summary",
  "html",
  "markdown",
  "memory_text",
  "patch",
  "personal_context_block",
  "personal_summary",
  "prompt",
  "raw_content",
  "raw_memory",
  "raw_private_memory",
  "raw_private_memory_text",
  "raw_text",
  "rendered_context",
  "stderr",
  "stdout",
  "summary",
  "text",
  "transcript",
]);
const GRANT_METADATA_KEYS = new Set([
  "derived_from_personal_memory",
  "derived_from_personal_memory_grant",
  "egress_guard_required",
  "grant_id",
  "personal_context_derived",
  "personal_memory_grant_ids",
  "personal_summary_persisted",
  "raw_private_memory_included",
]);
const MAX_METADATA_BYTES = 16 * 1024;
const MAX_METADATA_DEPTH = 8;
const MAX_METADATA_ITEMS = 256;
const MAX_METADATA_KEY_LENGTH = 128;
const MAX_METADATA_STRING_LENGTH = 2048;

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

  app.get("/api/v1/source-pointers/:pointerId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().get(identity, params(request).pointerId ?? ""));
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

  async get(identity: SpaceUserIdentity, pointerId: string): Promise<Record<string, unknown>> {
    const rows = await this.db.query<SourcePointerRow>(
      `SELECT ${COLUMNS}
         FROM source_pointers
        WHERE id = $1
          AND owner_space_id = $2
          AND (expires_at IS NULL OR expires_at > now())`,
      [pointerId, identity.spaceId],
    );
    if (!rows.rows[0]) throw new HttpError(404, "Source pointer not found");
    return out(rows.rows[0]);
  }

  async create(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    rejectUnknownFields(body);
    const sourceSpaceId = requiredString(body.source_space_id, "source_space_id");
    const sourceObjectType = requiredString(body.source_object_type, "source_object_type");
    const sourceObjectId = requiredString(body.source_object_id, "source_object_id");
    const accessMode = optionalString(body.access_mode) ?? "read";
    if (!ACCESS_MODES.has(accessMode)) throw new HttpError(422, "invalid access_mode");
    await this.requireActiveMembership(identity.userId, identity.spaceId, "owner_space_id");
    await this.requireActiveMembership(identity.userId, sourceSpaceId, "source_space_id");
    await this.requireSourceObject(sourceSpaceId, sourceObjectType, sourceObjectId);
    const metadata = validateMetadata(optionalObject(body.metadata_json) ?? {});
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
        sourceSpaceId,
        sourceObjectType,
        sourceObjectId,
        accessMode,
        identity.userId,
        toDbDate(body.expires_at),
        JSON.stringify(metadata),
        now,
      ],
    );
    return out(rows.rows[0]!);
  }

  async delete(identity: SpaceUserIdentity, pointerId: string): Promise<void> {
    await this.requireOwnerOrAdmin(identity.userId, identity.spaceId);
    const result = await this.db.query(
      `DELETE FROM source_pointers WHERE id = $1 AND owner_space_id = $2`,
      [pointerId, identity.spaceId],
    );
    if ((result.rowCount ?? 0) === 0) throw new HttpError(404, "Source pointer not found");
  }

  private async requireActiveMembership(userId: string, spaceId: string, field: string): Promise<void> {
    const rows = await this.db.query<{ role: string }>(
      `SELECT role
         FROM space_memberships
        WHERE user_id = $1
          AND space_id = $2
          AND status = 'active'
        LIMIT 1`,
      [userId, spaceId],
    );
    if (!rows.rows[0]) throw new HttpError(403, `active membership required for ${field}`);
  }

  private async requireOwnerOrAdmin(userId: string, spaceId: string): Promise<void> {
    const rows = await this.db.query<{ role: string }>(
      `SELECT role
         FROM space_memberships
        WHERE user_id = $1
          AND space_id = $2
          AND status = 'active'
        LIMIT 1`,
      [userId, spaceId],
    );
    const role = rows.rows[0]?.role;
    if (role !== "owner" && role !== "admin") {
      throw new HttpError(403, "Only owner/admin can delete source pointers");
    }
  }

  private async requireSourceObject(spaceId: string, objectType: string, objectId: string): Promise<void> {
    const sql = SOURCE_OBJECT_QUERIES[objectType];
    if (!sql) throw new HttpError(422, "invalid source_object_type");
    const rows = await this.db.query(sql, [spaceId, objectId]);
    if (!rows.rows[0]) throw new HttpError(404, "source object not found in source_space_id");
  }
}

function rejectUnknownFields(body: Record<string, unknown>): void {
  for (const key of Object.keys(body)) {
    if (!CREATE_FIELDS.has(key)) throw new HttpError(422, `unsupported source pointer field: ${key}`);
  }
}

function validateMetadata(metadata: Record<string, unknown>): Record<string, unknown> {
  const json = JSON.stringify(metadata);
  if (Buffer.byteLength(json, "utf8") > MAX_METADATA_BYTES) {
    throw new HttpError(422, "metadata_json exceeds 16 KiB");
  }
  const counter = { count: 0 };
  validateMetadataNode(metadata, 0, counter);
  return metadata;
}

function validateMetadataNode(value: unknown, depth: number, counter: { count: number }): void {
  if (depth > MAX_METADATA_DEPTH) throw new HttpError(422, "metadata_json exceeds maximum depth");
  if (value === null || typeof value === "boolean" || typeof value === "number") return;
  if (typeof value === "string") {
    if (value.length > MAX_METADATA_STRING_LENGTH) {
      throw new HttpError(422, "metadata_json string value exceeds maximum length");
    }
    return;
  }
  if (Array.isArray(value)) {
    counter.count += value.length;
    if (counter.count > MAX_METADATA_ITEMS) throw new HttpError(422, "metadata_json has too many items");
    for (const item of value) validateMetadataNode(item, depth + 1, counter);
    return;
  }
  if (!value || typeof value !== "object") {
    throw new HttpError(422, "metadata_json must be JSON-compatible");
  }
  const entries = Object.entries(value as Record<string, unknown>);
  counter.count += entries.length;
  if (counter.count > MAX_METADATA_ITEMS) throw new HttpError(422, "metadata_json has too many items");
  for (const [key, child] of entries) {
    if (key.length > MAX_METADATA_KEY_LENGTH) {
      throw new HttpError(422, "metadata_json key exceeds maximum length");
    }
    const normalized = key.trim().toLowerCase();
    if (CONTENT_METADATA_KEYS.has(normalized) || GRANT_METADATA_KEYS.has(normalized)) {
      throw new HttpError(422, `metadata_json contains forbidden key ${JSON.stringify(key)}`);
    }
    validateMetadataNode(child, depth + 1, counter);
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
