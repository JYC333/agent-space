import type { ControlPlaneConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import {
  MEMORY_COLUMNS,
  type MemoryRow,
  type Queryable,
} from "../memory/repository";
import { canReadMemory } from "../memory/memoryReadAuth";

/**
 * Native TS reads for chat context candidate sources.
 *
 * Faithful port of the per-source selectors in
 * `app.memory.chat_context.ChatContextBuilder` (`_select_memory`,
 * `_select_knowledge_items`, `_select_sources`, `_select_activity_records`).
 * Replaces the Python `context-candidates` read port: each source is fetched at
 * its natural per-source cap, in priority order, without the cumulative budget —
 * the TS `buildChatContext` loop applies `max_items` / `max_tokens` / dedup over
 * the ordered prefix, so the final selection matches Python `build`.
 *
 * The chat request carries no `workspace_id` / `project_id` / `manual_context`,
 * so only the memory / knowledge / source / activity selectors fire in this
 * path (mirroring the Python `collect_candidates` inputs for a chat turn).
 *
 * Memory reads are intentionally **not** access-logged here: the Python chat
 * candidate path (`MemoryRetriever.retrieve`) wrote no `memory_access_logs`
 * rows; only full-run context preparation logs `context_injection`.
 * `canReadMemory` is the read-authorization boundary.
 *
 * Fidelity note: memory selection here ranks readable active memories by
 * `importance DESC, confidence DESC` (Python `_load_and_rank`), which is the
 * dominant `MemoryRetriever` output. Graph expansion and keyword-fallback union
 * are handled by the full-run context repository.
 */

/** Per-item excerpt truncation limit (Python `_MAX_EXCERPT_CHARS`). */
const MAX_EXCERPT_CHARS = 800;

/** Cap on candidate memory rows fetched before the read-auth filter. */
const MEMORY_FETCH_CAP = 200;

/** Knowledge `item_type` values selected when `knowledge_item` is allowed. */
const KNOWLEDGE_ITEM_TYPES = [
  "concept",
  "claim",
  "lesson",
  "procedure",
  "decision",
  "question",
  "answer",
  "summary",
];

export interface CandidateRow {
  item_id: string;
  title: string | null;
  text: string;
}

export interface ContextPolicy {
  /** Raw `agent_versions.context_policy_json` (may be `{}`). */
  policy: Record<string, unknown>;
  /** True when a current agent version backed this policy load. */
  resolved: boolean;
}

export function excerpt(text: string | null): string | null {
  if (!text) return null;
  return text.slice(0, MAX_EXCERPT_CHARS);
}

export function tokenCount(text: string | null): number {
  return Math.floor((text ?? "").length / 4);
}

export class PgChatCandidateRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ControlPlaneConfig): PgChatCandidateRepository {
    if (!config.databaseUrl) {
      throw new Error(
        "Chat candidate repository requires CONTROL_PLANE_DATABASE_URL",
      );
    }
    return new PgChatCandidateRepository(getDbPool(config.databaseUrl));
  }

  /**
   * Load `context_policy_json` from the agent's current version. Mirrors Python
   * `_load_policy`: a missing agent/version yields `{}` (conservative-permissive
   * — the collector then allows all sources).
   */
  async loadContextPolicy(
    spaceId: string,
    agentId: string,
  ): Promise<ContextPolicy> {
    const result = await this.db.query<{ context_policy_json: unknown }>(
      `SELECT av.context_policy_json
         FROM agents a
         JOIN agent_versions av ON av.id = a.current_version_id
        WHERE a.space_id = $1 AND a.id = $2
        LIMIT 1`,
      [spaceId, agentId],
    );
    const row = result.rows[0];
    if (!row) return { policy: {}, resolved: false };
    const policy =
      row.context_policy_json && typeof row.context_policy_json === "object"
        ? (row.context_policy_json as Record<string, unknown>)
        : {};
    return { policy, resolved: true };
  }

  /**
   * Readable active memories ranked `importance DESC, confidence DESC`. The
   * read-authorization filter runs in app code (like the memory read model), so
   * the cap applies to the readable set. No access logging (see module note).
   */
  async selectMemories(
    spaceId: string,
    userId: string,
    limit: number,
  ): Promise<CandidateRow[]> {
    const result = await this.db.query<MemoryRow>(
      `SELECT ${MEMORY_COLUMNS} FROM memory_entries
        WHERE space_id = $1 AND status = 'active' AND deleted_at IS NULL
        ORDER BY importance DESC, confidence DESC
        LIMIT ${MEMORY_FETCH_CAP}`,
      [spaceId],
    );
    const readable = result.rows.filter((row) =>
      canReadMemory(row, {
        userId,
        spaceId,
        workspaceId: null,
        includeSystemScope: false,
      }),
    );
    return readable.slice(0, limit).map((row) => ({
      item_id: row.id,
      title: row.title,
      text: row.content ?? "",
    }));
  }

  /**
   * Active knowledge items of the recognised types, recent-first, optionally
   * keyword-filtered by the message prefix (Python `_select_knowledge_items`).
   */
  async selectKnowledgeItems(
    spaceId: string,
    message: string,
    limit: number,
  ): Promise<CandidateRow[]> {
    const where = [
      `space_id = $1`,
      `status = 'active'`,
      `item_type = ANY($2)`,
    ];
    const params: unknown[] = [spaceId, KNOWLEDGE_ITEM_TYPES];
    if (message) {
      params.push(`%${message.slice(0, 40)}%`);
      where.push(`(title ILIKE $${params.length} OR content ILIKE $${params.length})`);
    }
    const result = await this.db.query<{
      id: string;
      title: string | null;
      content: string | null;
    }>(
      `SELECT id, title, content FROM knowledge_items
        WHERE ${where.join(" AND ")}
        ORDER BY updated_at DESC
        LIMIT ${clampLimit(limit)}`,
      params,
    );
    return result.rows.map((row) => ({
      item_id: row.id,
      title: row.title,
      text: row.content ?? "",
    }));
  }

  /** Processed sources, recent-first (Python `_select_sources`). */
  async selectSources(spaceId: string, limit: number): Promise<CandidateRow[]> {
    const result = await this.db.query<{
      id: string;
      title: string | null;
      summary: string | null;
      raw_text: string | null;
    }>(
      `SELECT id, title, summary, raw_text FROM sources
        WHERE space_id = $1 AND status = 'processed'
        ORDER BY created_at DESC
        LIMIT ${clampLimit(limit)}`,
      [spaceId],
    );
    return result.rows.map((row) => ({
      item_id: row.id,
      title: row.title,
      text: row.summary ?? row.raw_text ?? "",
    }));
  }

  /** Recent activity records (Python `_select_activity_records`). */
  async selectActivityRecords(
    spaceId: string,
    limit: number,
  ): Promise<CandidateRow[]> {
    const result = await this.db.query<{
      id: string;
      title: string | null;
      content: string | null;
    }>(
      `SELECT id, title, content FROM activity_records
        WHERE space_id = $1
        ORDER BY occurred_at DESC
        LIMIT ${clampLimit(limit)}`,
      [spaceId],
    );
    return result.rows.map((row) => ({
      item_id: row.id,
      title: row.title,
      text: row.content ?? "",
    }));
  }
}

/** Guard the inlined LIMIT against non-positive / non-integer values. */
function clampLimit(limit: number): number {
  const n = Math.floor(limit);
  return n > 0 ? n : 1;
}
