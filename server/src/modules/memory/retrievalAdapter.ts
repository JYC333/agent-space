import {
  RetrievalRegistry,
  type CanonicalObject,
  type RetrievalDomainAdapter,
  type RetrievalObjectRef,
  type RetrievalObjectType,
  type RevalidatedObject,
  loadSourceConnectionIdsForTargets,
} from "../retrieval";
import {
  canReadMemory,
  summaryOnlyRedactContent,
  type MemoryAuthFields,
} from "./memoryReadAuth";
import { accessibleProjectIds } from "./projectAccess";

const MEMORY_OBJECT_TYPES = ["memory_entry"] as const;

interface MemoryProjectionRow {
  id: string;
  workspace_id: string | null;
  owner_user_id: string | null;
  sensitivity_level: string | null;
  visibility: string | null;
  status: string;
  scope_type: string | null;
  selected_user_ids: unknown;
  memory_type: string;
  title: string | null;
  content: string | null;
  updated_at: Date | string | null;
}

interface MemoryVisibilityRow extends MemoryAuthFields {
  id: string;
  project_id: string | null;
  title: string | null;
  content: string | null;
}

type MemoryProjectableFields = Pick<
  MemoryAuthFields,
  "scope_type" | "visibility" | "owner_user_id" | "sensitivity_level" | "selected_user_ids"
>;

// Keep this predicate in lock-step with `isMemoryRetrievalProjectable` below.
// Both lower-case the enum columns so a non-canonical-cased row is judged the
// same way on the SQL (listObjectIds) and TS (loadCanonical) paths.
const MEMORY_RETRIEVAL_PROJECTABLE_SQL = `
  lower(COALESCE(scope_type, '')) <> 'system'
  AND lower(COALESCE(visibility, 'private')) <> 'public_template'
  AND (
    owner_user_id IS NOT NULL
    OR (
      lower(COALESCE(sensitivity_level, 'normal')) <> 'highly_restricted'
      AND lower(COALESCE(visibility, 'private')) NOT IN ('private', 'workspace_shared')
      AND (
        lower(COALESCE(visibility, 'private')) NOT IN ('restricted', 'selected_users')
        OR (
          selected_user_ids IS NOT NULL
          AND (
            (jsonb_typeof(selected_user_ids) = 'array' AND jsonb_array_length(selected_user_ids) > 0)
            OR (jsonb_typeof(selected_user_ids) = 'string' AND length(selected_user_ids #>> '{}') > 0)
          )
        )
      )
    )
  )
`;

/**
 * Memory domain adapter for the shared zero-LLM retrieval engine. It owns all
 * Memory-specific SQL — loading `memory_entries` for projection and the live
 * read-access gate. The engine stays domain-agnostic; this is the only place
 * that touches Memory tables.
 *
 * Boundaries this adapter must preserve:
 * - The single read-access gate is `revalidate`, which reuses the canonical
 *   `canReadMemory` rules plus summary-only content redaction. The derived
 *   `retrieval_*` projection is never trusted for read access.
 * - This adapter never writes `memory_entries`. Memory create/update/archive
 *   stay proposal-gated; the projection is derived index data only.
 * - `revalidate` runs without workspace or system/template context
 *   (workspaceId=null, includeSystemScope=false, includePublicTemplates=false),
 *   so workspace_shared and system/template memories owned by other users fail
 *   closed. The proposer's own private/workspace-shared memories still match
 *   through owner visibility, which is what duplicate detection needs.
 */
export const memoryRetrievalAdapter: RetrievalDomainAdapter = {
  objectTypes: MEMORY_OBJECT_TYPES,

  async loadCanonical(db, spaceId, _objectType, objectId): Promise<CanonicalObject | null> {
    const result = await db.query<MemoryProjectionRow>(
      `SELECT id, workspace_id, owner_user_id, visibility, status, memory_type,
              title, content, sensitivity_level, scope_type, selected_user_ids, updated_at
         FROM memory_entries
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [spaceId, objectId],
    );
    const row = result.rows[0];
    if (!row || row.status !== "active" || !isMemoryRetrievalProjectable(row)) return null;
    const title = row.title ?? "";
    const sourceConnectionIds = (await loadSourceConnectionIdsForTargets(
      db,
      spaceId,
      "memory",
      [row.id],
    )).get(row.id) ?? [];
    return {
      objectType: "memory_entry",
      objectId: row.id,
      title,
      slug: null,
      workspaceId: row.workspace_id,
      ownerUserId: row.owner_user_id,
      visibility: row.visibility,
      status: row.status,
      objectKind: row.memory_type,
      aliases: [],
      text: joinText([title, row.content]),
      sourceConnectionIds,
      updatedAt: memoryIsoOrNull(row.updated_at),
    };
  },

  async revalidate(db, spaceId, _objectType, objectId, viewerUserId): Promise<RevalidatedObject | null> {
    return (await revalidateMemoryMany(db, spaceId, [objectId], viewerUserId)).get(objectId) ?? null;
  },

  async revalidateMany(db, spaceId, _objectType, objectIds, viewerUserId): Promise<Map<string, RevalidatedObject>> {
    return revalidateMemoryMany(db, spaceId, objectIds, viewerUserId);
  },

  async listObjectIds(db, spaceId): Promise<RetrievalObjectRef[]> {
    const result = await db.query<{ id: string }>(
      `SELECT id FROM memory_entries
        WHERE space_id = $1
          AND status = 'active'
          AND deleted_at IS NULL
          AND ${MEMORY_RETRIEVAL_PROJECTABLE_SQL}`,
      [spaceId],
    );
    return result.rows.map((row) => ({ objectType: "memory_entry" as RetrievalObjectType, objectId: row.id }));
  },
};

async function revalidateMemoryMany(
  db: Parameters<RetrievalDomainAdapter["revalidate"]>[0],
  spaceId: string,
  objectIds: readonly string[],
  viewerUserId: string,
): Promise<Map<string, RevalidatedObject>> {
  const ids = uniqueIds(objectIds);
  if (ids.length === 0) return new Map();
  const result = await db.query<MemoryVisibilityRow>(
    `SELECT id, space_id, deleted_at, sensitivity_level, visibility, owner_user_id,
            scope_type, workspace_id, selected_user_ids, project_id, title, content
       FROM memory_entries
      WHERE space_id = $1 AND id = ANY($2::varchar[]) AND status = 'active' AND deleted_at IS NULL`,
    [spaceId, ids],
  );
  // The single read-access gate: no workspace/system/template context, so
  // those classes fail closed unless explicitly readable under this surface.
  const readable = result.rows.filter((row) => canReadMemory(row, { userId: viewerUserId, spaceId }));
  const accessible = await accessibleProjectIds(
    db,
    spaceId,
    viewerUserId,
    readable.map((row) => row.project_id),
  );
  const rows = new Map<string, RevalidatedObject>();
  for (const row of readable) {
    if (row.project_id && !accessible.has(row.project_id)) continue;
    // Mirror the canonical read model: summary_only withholds full content from
    // non-owners. Title is not content and stays visible.
    rows.set(row.id, {
      title: row.title ?? "",
      text: summaryOnlyRedactContent(row, viewerUserId) ? null : row.content,
    });
  }
  return rows;
}

/**
 * Process-wide registry with only the Memory adapter registered. Memory keeps a
 * separate registry from Knowledge so the memory retrieval surface (create-safety,
 * reindex) can never resolve Knowledge objects, and vice versa.
 */
export const memoryRetrievalRegistry = new RetrievalRegistry();
memoryRetrievalRegistry.register(memoryRetrievalAdapter);

function joinText(parts: Array<string | null>): string {
  return parts
    .filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0)
    .join("\n");
}

/** Normalize a pg timestamptz (Date or string) to an ISO string, or null. */
function memoryIsoOrNull(value: Date | string | null | undefined): string | null {
  if (!value) return null;
  if (value instanceof Date) return value.toISOString();
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

export function isMemoryRetrievalProjectable(row: MemoryProjectableFields): boolean {
  const scope = (row.scope_type ?? "").toLowerCase();
  if (scope === "system") return false;

  const visibility = (row.visibility ?? "private").toLowerCase();
  if (visibility === "public_template") return false;
  if (row.owner_user_id) return true;

  const sensitivity = (row.sensitivity_level ?? "normal").toLowerCase();
  if (sensitivity === "highly_restricted") return false;
  if (visibility === "private" || visibility === "workspace_shared") return false;
  if (visibility === "restricted" || visibility === "selected_users") {
    return selectedUserIdsHasEntry(row.selected_user_ids);
  }
  return true;
}

function selectedUserIdsHasEntry(value: unknown): boolean {
  if (Array.isArray(value)) return value.some((entry) => typeof entry === "string" && entry.length > 0);
  if (typeof value === "string") return value.length > 0;
  return false;
}

function uniqueIds(ids: readonly string[]): string[] {
  return [...new Set(ids.filter((id) => id.length > 0))];
}
