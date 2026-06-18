import { randomUUID } from "node:crypto";
import type { Pool } from "../../db/pool";
import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import { withTransaction } from "../../db/tx";
import {
  MEMORY_COLUMNS,
  type MemoryRow,
  type Queryable,
} from "../memory/repository";
import { recordValue } from "./contextPackage";
import {
  addArrayFilter,
  clampMaxItems,
  evidenceSelectionFromRow,
  generatePersonalSummary,
  hardFilterRows,
  memorySourceRef,
  numeric,
  policySourceRef,
  resolveReadableScopes,
  type EvidenceContextRow,
} from "./contextRepositoryHelpers";

const ALLOWED_RELATION_TYPES = [
  "derived_from",
  "related_to",
  "applies_to",
  "supports",
  "caused_by",
] as const;

const MAX_HOPS = 2;
const DEFAULT_MAX_MEMORIES = 20;

const CONTEXT_MEMORY_COLUMNS = `${MEMORY_COLUMNS}, agent_id, capability_id, access_count, last_accessed_at, last_retrieved_at`;

export interface ContextMemoryRow extends MemoryRow {
  agent_id: string | null;
  capability_id: string | null;
  access_count: number | string;
  last_accessed_at: unknown;
  last_retrieved_at: unknown;
}

export interface RunContextRecord {
  id: string;
  space_id: string;
  agent_id: string | null;
  agent_version_id: string | null;
  context_snapshot_id: string | null;
  prompt: string | null;
  workspace_id: string | null;
  project_id: string | null;
  session_id: string | null;
  instructed_by_user_id: string | null;
  trigger_origin: string | null;
  data_exposure_level: string | null;
  trust_level: string | null;
  has_personal_grant_context: boolean;
  personal_grant_context_json: unknown;
  system_prompt: string | null;
  memory_policy_json: unknown;
}

export interface PolicyRow {
  id: string;
  name: string;
  domain: string;
  policy_key: string | null;
  enforcement_mode: string | null;
  priority: number | string;
  policy_json: unknown;
}

export interface SessionSummaryRow {
  id: string;
  session_id: string;
  summary_text: string;
  version: number | string;
  condenser_version: string | null;
}

export interface ContextDigestRow {
  id: string;
  digest_type: "policy_bundle" | "workspace" | "agent";
  version: number | string;
  status: string;
  content: string | null;
  source_memory_ids_json: unknown;
  source_policy_ids_json: unknown;
  source_relation_ids_json: unknown;
  source_hash: string | null;
  content_hash: string | null;
}

export interface DigestBundle {
  policy_bundle: ContextDigestRow | null;
  workspace: ContextDigestRow | null;
  agent: ContextDigestRow | null;
}

export interface PersonalGrantMetadata {
  grant_id: string;
  granting_user_id: string;
  personal_space_id: string;
  target_space_id: string;
  access_mode: string;
  memory_count: number;
  raw_memory_included: false;
  personal_summary_persisted: false;
}

export interface PersonalGrantResult {
  personal_context_block: string;
  metadata: PersonalGrantMetadata | null;
}

export interface ContextEvidenceSelection {
  item: Record<string, unknown>;
  ref: Record<string, unknown>;
}

interface PersonalGrantRow {
  id: string;
  granting_user_id: string;
  personal_space_id: string;
  target_space_id: string;
  access_mode: string;
  memory_filter_json: unknown;
}

export interface SnapshotUpdateInput {
  snapshotId: string;
  spaceId: string;
  sourceRefs: readonly Record<string, unknown>[];
  includedEvidenceRefs: readonly Record<string, unknown>[];
  retrievalTrace: readonly Record<string, unknown>[];
  tokenBudget: Record<string, unknown>;
  compiledPrefixText: string;
  compiledTailText: string;
  prefixHash: string;
  tailHash: string;
  compilerVersion: string;
  tokenEstimate: number;
  policyBundleVersion?: string | null;
  workspaceDigestVersion?: string | null;
}

/**
 * Repository for the full-run server context.prepare path.
 *
 * This intentionally stays under `modules/context`, even though it touches
 * memory/context tables: context assembly is the "what the runtime saw"
 * authority. Public memory reads continue to live in `modules/memory`.
 */
export class PgRunContextRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ServerConfig): PgRunContextRepository {
    if (!config.databaseUrl) {
      throw new Error("Run context repository requires SERVER_DATABASE_URL");
    }
    return new PgRunContextRepository(getDbPool(config.databaseUrl));
  }

  static poolFromConfig(config: ServerConfig): Pool {
    if (!config.databaseUrl) {
      throw new Error("Run context repository requires SERVER_DATABASE_URL");
    }
    return getDbPool(config.databaseUrl);
  }

  async loadRun(spaceId: string, runId: string): Promise<RunContextRecord | null> {
    const result = await this.db.query<RunContextRecord>(
      `SELECT r.id, r.space_id, r.agent_id, r.agent_version_id,
              r.context_snapshot_id, r.prompt, r.workspace_id, r.project_id,
              r.session_id, r.instructed_by_user_id, r.trigger_origin,
              r.data_exposure_level, r.trust_level,
              r.has_personal_grant_context, r.personal_grant_context_json,
              av.system_prompt, av.memory_policy_json
         FROM runs r
         LEFT JOIN agent_versions av
           ON av.id = r.agent_version_id
          AND av.space_id = r.space_id
          AND av.agent_id = r.agent_id
        WHERE r.space_id = $1 AND r.id = $2
        LIMIT 1`,
      [spaceId, runId],
    );
    return result.rows[0] ?? null;
  }

  async retrieve(input: {
    spaceId: string;
    userId: string;
    workspaceId: string | null;
    agentId: string | null;
    capabilityId?: string | null;
    query: string | null;
    agentMemoryPolicy: Record<string, unknown> | null;
    includeSystemScope: boolean;
    maxMemories?: number;
  }): Promise<{
    memories: ContextMemoryRow[];
    activePolicies: PolicyRow[];
    sourceRefs: Record<string, unknown>[];
    retrievalTrace: Record<string, unknown>;
    tokenBudget: Record<string, unknown>;
  }> {
    const readableScopes = resolveReadableScopes(
      input.agentMemoryPolicy,
      input.includeSystemScope,
    );
    const hardFilterTrace = {
      space_id: input.spaceId,
      user_id: input.userId,
      readable_scopes: [...readableScopes].sort(),
      excluded_statuses: [
        "archived",
        "deleted",
        "proposed",
        "rejected",
        "superseded",
      ],
      cross_space_blocked: true,
      private_other_user_blocked: true,
    };

    const seenIds = new Set<string>();
    const sourceRefs: Record<string, unknown>[] = [];
    const stageTraces: Record<string, unknown>[] = [];

    const symbolRows = hardFilterRows(
      await this.symbolMatch({
        ...input,
        readableScopes,
      }),
      input,
    );
    for (const row of symbolRows) {
      if (seenIds.has(row.id)) continue;
      seenIds.add(row.id);
      sourceRefs.push(memorySourceRef(row, "symbol_match", "symbol_match"));
    }
    stageTraces.push({
      stage: "symbol_match",
      found: sourceRefs.filter((r) => r.stage === "symbol_match").length,
      ids: sourceRefs
        .filter((r) => r.stage === "symbol_match")
        .map((r) => r.source_id),
    });

    if (seenIds.size > 0) {
      const { rows, hopsUsed } = await this.graphExpand({
        ...input,
        seedIds: seenIds,
        readableScopes,
      });
      const newGraphIds: string[] = [];
      for (const row of rows) {
        if (seenIds.has(row.id)) continue;
        seenIds.add(row.id);
        newGraphIds.push(row.id);
        sourceRefs.push(
          memorySourceRef(row, `graph_expansion_hop_${hopsUsed}`, "graph_expansion"),
        );
      }
      stageTraces.push({
        stage: "graph_expansion",
        hops_used: hopsUsed,
        found: newGraphIds.length,
        ids: newGraphIds,
      });
    } else {
      stageTraces.push({
        stage: "graph_expansion",
        hops_used: 0,
        found: 0,
        ids: [],
      });
    }

    const keywordNewIds: string[] = [];
    if (input.query?.trim()) {
      const keywordRows = await this.keywordFallback({
        ...input,
        readableScopes,
      });
      for (const row of keywordRows) {
        if (seenIds.has(row.id)) continue;
        seenIds.add(row.id);
        keywordNewIds.push(row.id);
        sourceRefs.push(memorySourceRef(row, "keyword_fallback", "keyword_fallback"));
      }
    }
    stageTraces.push({
      stage: "keyword_fallback",
      query: input.query ?? "",
      found: keywordNewIds.length,
      ids: keywordNewIds,
    });

    // Embedding fallback currently delegates to the same keyword result set, so
    // after the keyword stage there are no new rows left to add.
    stageTraces.push({
      stage: "embedding_fallback",
      backend: "keyword_delegation",
      found: 0,
      ids: [],
    });

    const finalMemories = await this.loadAndRank({
      ...input,
      ids: [...seenIds],
      maxMemories: input.maxMemories ?? DEFAULT_MAX_MEMORIES,
    });
    const finalIds = new Set(finalMemories.map((row) => row.id));
    const finalSourceRefs = sourceRefs.filter((ref) =>
      typeof ref.source_id === "string" && finalIds.has(ref.source_id),
    );

    const activePolicies = await this.loadActivePolicies(input.spaceId);
    finalSourceRefs.push(...activePolicies.map(policySourceRef));

    const tokenBudget = {
      default_budget_chars: 128_000,
      source: "default",
      note: "token_budget populated by ContextSnapshotPopulator",
    };
    return {
      memories: finalMemories,
      activePolicies,
      sourceRefs: finalSourceRefs,
      tokenBudget,
      retrievalTrace: {
        retrieved_at: new Date().toISOString(),
        space_id: input.spaceId,
        hard_filter: hardFilterTrace,
        stages: stageTraces,
        total_selected: finalMemories.length,
        selected_ids: finalMemories.map((row) => row.id),
        policy_count: activePolicies.length,
        token_budget: tokenBudget,
      },
    };
  }

  async recordContextMemoryAccess(input: {
    memories: readonly ContextMemoryRow[];
    spaceId: string;
    userId: string;
    agentId: string | null;
    runId: string;
    reason: string;
  }): Promise<void> {
    if (input.memories.length === 0) return;
    const now = new Date().toISOString();
    const logCols =
      "id, space_id, memory_id, user_id, agent_id, run_id, access_type, reason, accessed_at";
    const logGroups: string[] = [];
    const logParams: unknown[] = [];
    for (const memory of input.memories) {
      const base = logParams.length;
      logGroups.push(
        `($${base + 1}, $${base + 2}, $${base + 3}, $${base + 4}, ` +
          `$${base + 5}, $${base + 6}, 'context_injection', $${base + 7}, $${base + 8})`,
      );
      logParams.push(
        randomUUID(),
        input.spaceId,
        memory.id,
        input.userId,
        input.agentId,
        input.runId,
        input.reason,
        now,
      );
    }
    await this.db.query(
      `INSERT INTO memory_access_logs (${logCols}) VALUES ${logGroups.join(", ")}`,
      logParams,
    );
    const idPlaceholders = input.memories.map((_, i) => `$${i + 3}`).join(", ");
    await this.db.query(
      `UPDATE memory_entries
          SET access_count = COALESCE(access_count, 0) + 1,
              last_accessed_at = $1,
              last_retrieved_at = $1
        WHERE space_id = $2 AND id IN (${idPlaceholders})`,
      [now, input.spaceId, ...input.memories.map((m) => m.id)],
    );
  }

  async loadLatestSessionSummary(
    spaceId: string,
    sessionId: string | null,
  ): Promise<SessionSummaryRow | null> {
    if (!sessionId) return null;
    const result = await this.db.query<SessionSummaryRow>(
      `SELECT id, session_id, summary_text, version, condenser_version
         FROM session_summaries
        WHERE space_id = $1
          AND session_id = $2
          AND status = 'active'
        ORDER BY version DESC
        LIMIT 1`,
      [spaceId, sessionId],
    );
    return result.rows[0] ?? null;
  }

  async selectEvidenceForContext(input: {
    spaceId: string;
    workspaceId: string | null;
    projectId: string | null;
    runId: string | null;
    limit?: number;
  }): Promise<ContextEvidenceSelection[]> {
    const targets: Array<{ type: string; id: string }> = [
      { type: "space", id: input.spaceId },
    ];
    if (input.workspaceId) {
      targets.push({ type: "workspace", id: input.workspaceId });
    }
    if (input.projectId) {
      targets.push({ type: "project", id: input.projectId });
    }
    if (input.runId) {
      targets.push({ type: "run", id: input.runId });
    }

    const params: unknown[] = [
      input.spaceId,
      ["context_candidate", "supports", "mentions", "provenance"],
    ];
    const targetPredicates = targets.map((target) => {
      const typeIndex = params.length + 1;
      params.push(target.type);
      const idIndex = params.length + 1;
      params.push(target.id);
      return `(el.target_type = $${typeIndex} AND el.target_id = $${idIndex})`;
    });
    params.push(input.limit ?? 8);

    const result = await this.db.query<EvidenceContextRow>(
      `SELECT ev.id, ev.title, ev.content_excerpt, ev.evidence_type,
              ev.trust_level, ev.intake_item_id, ev.source_snapshot_id,
              ev.artifact_id, ev.source_uri,
              el.id AS link_id, el.link_type, el.target_type, el.target_id
         FROM extracted_evidence ev
         JOIN evidence_links el
           ON el.evidence_id = ev.id
          AND el.space_id = ev.space_id
        WHERE ev.space_id = $1
          AND ev.status = 'active'
          AND ev.deleted_at IS NULL
          AND el.status = 'active'
          AND el.link_type = ANY($2::varchar[])
          AND (${targetPredicates.join(" OR ")})
        ORDER BY el.confidence DESC, ev.created_at DESC
        LIMIT $${params.length}`,
      params,
    );

    const seen = new Set<string>();
    const selections: ContextEvidenceSelection[] = [];
    for (const row of result.rows) {
      if (seen.has(row.id)) continue;
      seen.add(row.id);
      if (input.runId) {
        await this.insertUsedInContextEvidenceLink({
          spaceId: input.spaceId,
          evidenceId: row.id,
          runId: input.runId,
        });
      }
      selections.push(evidenceSelectionFromRow(row));
    }
    return selections;
  }

  async loadDigestBundle(input: {
    spaceId: string;
    workspaceId: string | null;
    agentId: string | null;
  }): Promise<DigestBundle> {
    const policy = await this.loadActiveDigest(
      input.spaceId,
      "space",
      null,
      "policy_bundle",
    );
    const workspace = input.workspaceId
      ? await this.loadActiveDigest(
          input.spaceId,
          "workspace",
          input.workspaceId,
          "workspace",
        )
      : null;
    const agent = input.agentId
      ? await this.loadActiveDigest(input.spaceId, "agent", input.agentId, "agent")
      : null;
    return { policy_bundle: policy, workspace, agent };
  }

  async updateSnapshot(input: SnapshotUpdateInput): Promise<void> {
    await this.db.query(
      `UPDATE context_snapshots
          SET compiled_prefix_text = $1,
              compiled_tail_text = $2,
              prefix_hash = $3,
              tail_hash = $4,
              source_refs_json = $5::jsonb,
              included_evidence_refs_json = $6::jsonb,
              retrieval_trace_json = $7::jsonb,
              token_budget_json = $8::jsonb,
              compiler_version = $9,
              token_estimate = $10,
              policy_bundle_version = $11,
              workspace_digest_version = $12
        WHERE id = $13
          AND space_id = $14`,
      [
        input.compiledPrefixText,
        input.compiledTailText,
        input.prefixHash,
        input.tailHash,
        JSON.stringify(input.sourceRefs),
        JSON.stringify(input.includedEvidenceRefs),
        JSON.stringify(input.retrievalTrace),
        JSON.stringify(input.tokenBudget),
        input.compilerVersion,
        input.tokenEstimate,
        input.policyBundleVersion ?? null,
        input.workspaceDigestVersion ?? null,
        input.snapshotId,
        input.spaceId,
      ],
    );
  }

  async resolvePersonalGrantForRun(run: RunContextRecord): Promise<PersonalGrantResult> {
    if (!run.instructed_by_user_id) {
      return { personal_context_block: "", metadata: null };
    }
    const now = new Date().toISOString();
    const grantResult = await this.db.query<PersonalGrantRow>(
      `SELECT id, granting_user_id, personal_space_id, target_space_id,
              access_mode, memory_filter_json
         FROM personal_memory_grants
        WHERE target_run_id = $1
          AND granting_user_id = $2
          AND target_space_id = $3
          AND status = 'active'
          AND grant_scope = 'run'
          AND access_mode = 'summary_only'
          AND target_agent_id IS NULL
          AND read_expires_at > $4
        LIMIT 1`,
      [run.id, run.instructed_by_user_id, run.space_id, now],
    );
    const grant = grantResult.rows[0];
    if (!grant) return { personal_context_block: "", metadata: null };

    const claimed = await this.db.query(
      `UPDATE personal_memory_grants
          SET status = 'consuming',
              consume_started_at = $1,
              updated_at = $1
        WHERE id = $2
          AND status = 'active'
          AND read_expires_at > $1`,
      [now, grant.id],
    );
    if ((claimed.rowCount ?? 0) !== 1) {
      return { personal_context_block: "", metadata: null };
    }

    await this.insertGrantEvent({
      grantId: grant.id,
      eventType: "consuming",
      runId: run.id,
      sourceSpaceId: grant.personal_space_id,
      targetSpaceId: grant.target_space_id,
      metadata: {
        access_mode: grant.access_mode,
        raw_memory_included: false,
      },
    });

    let memories: ContextMemoryRow[];
    try {
      memories = await this.retrieveEligiblePersonalMemories(grant);
    } catch (error) {
      await this.markGrantFailed(grant, run.id, "memory_retrieval");
      return { personal_context_block: "", metadata: null };
    }

    const summary = generatePersonalSummary(memories);
    const usedAt = new Date().toISOString();
    await this.db.query(
      `UPDATE personal_memory_grants
          SET status = 'used',
              used_at = $1,
              updated_at = $1
        WHERE id = $2
          AND status = 'consuming'`,
      [usedAt, grant.id],
    );
    await this.insertGrantEvent({
      grantId: grant.id,
      eventType: "used",
      runId: run.id,
      sourceSpaceId: grant.personal_space_id,
      targetSpaceId: grant.target_space_id,
      metadata: {
        memory_count: memories.length,
        access_mode: "summary_only",
        raw_memory_included: false,
        personal_summary_persisted: false,
      },
    });

    return {
      personal_context_block: summary,
      metadata: {
        grant_id: grant.id,
        granting_user_id: grant.granting_user_id,
        personal_space_id: grant.personal_space_id,
        target_space_id: grant.target_space_id,
        access_mode: grant.access_mode,
        memory_count: memories.length,
        raw_memory_included: false,
        personal_summary_persisted: false,
      },
    };
  }

  async markRunPersonalGrantContext(input: {
    runId: string;
    spaceId: string;
    metadata: PersonalGrantMetadata;
  }): Promise<void> {
    await this.db.query(
      `UPDATE runs
          SET has_personal_grant_context = TRUE,
              personal_grant_context_json = $1::jsonb,
              updated_at = $2
        WHERE id = $3
          AND space_id = $4`,
      [
        JSON.stringify(input.metadata),
        new Date().toISOString(),
        input.runId,
        input.spaceId,
      ],
    );
  }

  async withTransaction<T>(fn: (repo: PgRunContextRepository) => Promise<T>): Promise<T> {
    if (!("connect" in this.db)) return fn(this);
    return withTransaction(this.db as Pool, async (client) =>
      fn(new PgRunContextRepository(client)),
    );
  }

  private async symbolMatch(input: {
    spaceId: string;
    userId: string;
    workspaceId: string | null;
    agentId: string | null;
    capabilityId?: string | null;
    readableScopes: ReadonlySet<string>;
    includeSystemScope: boolean;
  }): Promise<ContextMemoryRow[]> {
    if (input.readableScopes.size === 0) return [];
    const result = await this.db.query<ContextMemoryRow>(
      `SELECT ${CONTEXT_MEMORY_COLUMNS}
         FROM memory_entries
        WHERE space_id = $1
          AND deleted_at IS NULL
          AND status = 'active'
          AND scope_type = ANY($2)
          AND (
            subject_user_id = $3
            OR owner_user_id = $3
            OR ($4::varchar IS NOT NULL AND workspace_id = $4)
            OR ($5::varchar IS NOT NULL AND agent_id = $5)
            OR ($6::varchar IS NOT NULL AND capability_id = $6)
          )
        ORDER BY importance DESC, updated_at DESC
        LIMIT 50`,
      [
        input.spaceId,
        [...input.readableScopes],
        input.userId,
        input.workspaceId,
        input.agentId,
        input.capabilityId ?? null,
      ],
    );
    return result.rows;
  }

  private async graphExpand(input: {
    spaceId: string;
    userId: string;
    workspaceId: string | null;
    agentId: string | null;
    seedIds: Set<string>;
    readableScopes: ReadonlySet<string>;
    includeSystemScope: boolean;
  }): Promise<{ rows: ContextMemoryRow[]; hopsUsed: number }> {
    let frontier = new Set(input.seedIds);
    const allFound: ContextMemoryRow[] = [];
    let hopsUsed = 0;

    for (let hop = 1; hop <= MAX_HOPS; hop += 1) {
      if (frontier.size === 0) break;
      const edgeResult = await this.db.query<{ target_id: string }>(
        `SELECT target_id
           FROM memory_relations
          WHERE space_id = $1
            AND source_type = 'memory'
            AND target_type = 'memory'
            AND relation_type = ANY($2)
            AND source_id = ANY($3)`,
        [input.spaceId, ALLOWED_RELATION_TYPES, [...frontier]],
      );
      const candidateIds = [
        ...new Set(edgeResult.rows.map((row) => row.target_id)),
      ].filter((id) => !input.seedIds.has(id));
      if (candidateIds.length === 0) break;

      const rows = hardFilterRows(
        await this.loadMemoriesByIds(input.spaceId, candidateIds),
        input,
      ).filter((row) => input.readableScopes.has(row.scope_type ?? ""));
      const newIds = new Set(rows.map((row) => row.id));
      for (const row of rows) allFound.push(row);
      for (const id of newIds) input.seedIds.add(id);
      frontier = newIds;
      hopsUsed = hop;
    }

    return { rows: allFound, hopsUsed };
  }

  private async keywordFallback(input: {
    spaceId: string;
    userId: string;
    workspaceId: string | null;
    agentId: string | null;
    query: string | null;
    readableScopes: ReadonlySet<string>;
    includeSystemScope: boolean;
  }): Promise<ContextMemoryRow[]> {
    if (!input.query?.trim() || input.readableScopes.size === 0) return [];
    const result = await this.db.query<ContextMemoryRow>(
      `SELECT ${CONTEXT_MEMORY_COLUMNS}
         FROM memory_entries
        WHERE space_id = $1
          AND deleted_at IS NULL
          AND status = 'active'
          AND scope_type = ANY($2)
          AND (title ILIKE $3 OR content ILIKE $3)
        ORDER BY importance DESC, confidence DESC
        LIMIT 20`,
      [input.spaceId, [...input.readableScopes], `%${input.query}%`],
    );
    return hardFilterRows(result.rows, input).filter((row) =>
      input.readableScopes.has(row.scope_type ?? ""),
    );
  }

  private async loadAndRank(input: {
    spaceId: string;
    userId: string;
    workspaceId: string | null;
    agentId: string | null;
    ids: string[];
    includeSystemScope: boolean;
    maxMemories: number;
  }): Promise<ContextMemoryRow[]> {
    if (input.ids.length === 0) return [];
    const rows = hardFilterRows(
      await this.loadMemoriesByIds(input.spaceId, input.ids),
      input,
    );
    return rows
      .sort(
        (a, b) =>
          numeric(b.importance) - numeric(a.importance) ||
          numeric(b.confidence) - numeric(a.confidence),
      )
      .slice(0, input.maxMemories);
  }

  private async loadMemoriesByIds(
    spaceId: string,
    ids: readonly string[],
  ): Promise<ContextMemoryRow[]> {
    if (ids.length === 0) return [];
    const result = await this.db.query<ContextMemoryRow>(
      `SELECT ${CONTEXT_MEMORY_COLUMNS}
         FROM memory_entries
        WHERE space_id = $1
          AND deleted_at IS NULL
          AND status = 'active'
          AND id = ANY($2)`,
      [spaceId, [...ids]],
    );
    return result.rows;
  }

  private async loadActivePolicies(spaceId: string): Promise<PolicyRow[]> {
    const result = await this.db.query<PolicyRow>(
      `SELECT id, name, domain, policy_key, enforcement_mode, priority, policy_json
         FROM policies
        WHERE space_id = $1
          AND enabled = TRUE
          AND status = 'active'
        ORDER BY priority DESC
        LIMIT 10`,
      [spaceId],
    );
    return result.rows;
  }

  private async loadActiveDigest(
    spaceId: string,
    scopeType: string,
    scopeId: string | null,
    digestType: "policy_bundle" | "workspace" | "agent",
  ): Promise<ContextDigestRow | null> {
    const result = await this.db.query<ContextDigestRow>(
      `SELECT id, digest_type, version, status, content,
              source_memory_ids_json, source_policy_ids_json,
              source_relation_ids_json, source_hash, content_hash
         FROM context_digests
        WHERE space_id = $1
          AND scope_type = $2
          AND (($3::varchar IS NULL AND scope_id IS NULL) OR scope_id = $3)
          AND digest_type = $4
          AND status IN ('active', 'dirty')
        ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                 version DESC
        LIMIT 1`,
      [spaceId, scopeType, scopeId, digestType],
    );
    return result.rows[0] ?? null;
  }

  private async retrieveEligiblePersonalMemories(
    grant: PersonalGrantRow,
  ): Promise<ContextMemoryRow[]> {
    const filter = recordValue(grant.memory_filter_json);
    const maxItems = clampMaxItems(filter.max_items);
    const where = [
      `space_id = $1`,
      `owner_user_id = $2`,
      `visibility = 'private'`,
      `sensitivity_level = ANY($3)`,
      `status = 'active'`,
      `deleted_at IS NULL`,
    ];
    const params: unknown[] = [
      grant.personal_space_id,
      grant.granting_user_id,
      ["normal", "sensitive"],
    ];
    addArrayFilter(where, params, "memory_layer", filter.memory_layers);
    addArrayFilter(where, params, "memory_kind", filter.memory_kinds);
    addArrayFilter(where, params, "namespace", filter.namespaces);
    const result = await this.db.query<ContextMemoryRow>(
      `SELECT ${CONTEXT_MEMORY_COLUMNS}
         FROM memory_entries
        WHERE ${where.join(" AND ")}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT ${maxItems}`,
      params,
    );
    return result.rows;
  }

  private async markGrantFailed(
    grant: PersonalGrantRow,
    runId: string,
    failureStage: string,
  ): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `UPDATE personal_memory_grants
          SET status = 'failed',
              failed_at = $1,
              failure_stage = $2,
              updated_at = $1
        WHERE id = $3`,
      [now, failureStage, grant.id],
    );
    await this.insertGrantEvent({
      grantId: grant.id,
      eventType: "failed",
      runId,
      sourceSpaceId: grant.personal_space_id,
      targetSpaceId: grant.target_space_id,
      metadata: {
        failure_stage: failureStage,
        raw_memory_included: false,
      },
    });
  }

  private async insertGrantEvent(input: {
    grantId: string;
    eventType: "consuming" | "used" | "failed";
    runId: string;
    sourceSpaceId: string;
    targetSpaceId: string;
    metadata: Record<string, unknown>;
  }): Promise<void> {
    await this.db.query(
      `INSERT INTO personal_memory_grant_events (
          id, grant_id, event_type, run_id, source_space_id,
          target_space_id, metadata_json, created_at
       )
       VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)`,
      [
        randomUUID(),
        input.grantId,
        input.eventType,
        input.runId,
        input.sourceSpaceId,
        input.targetSpaceId,
        JSON.stringify(input.metadata),
        new Date().toISOString(),
      ],
    );
  }

  private async insertUsedInContextEvidenceLink(input: {
    spaceId: string;
    evidenceId: string;
    runId: string;
  }): Promise<void> {
    const now = new Date().toISOString();
    await this.db.query(
      `INSERT INTO evidence_links (
          id, space_id, evidence_id, target_type, target_id,
          link_type, status, created_by_run_id, created_at, updated_at
       )
       SELECT $1, $2, $3, 'run', $4, 'used_in_context', 'active', $4, $5, $5
        WHERE NOT EXISTS (
          SELECT 1
            FROM evidence_links
           WHERE space_id = $2
             AND evidence_id = $3
             AND target_type = 'run'
             AND target_id = $4
             AND link_type = 'used_in_context'
             AND status = 'active'
        )`,
      [randomUUID(), input.spaceId, input.evidenceId, input.runId, now],
    );
  }
}
