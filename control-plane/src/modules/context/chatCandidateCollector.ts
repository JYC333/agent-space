import type { ControlPlaneConfig } from "../../config";
import type {
  ChatContextCandidateItem,
  ChatContextCandidatesRequest,
  ChatContextCandidatesResult,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import {
  PgChatCandidateRepository,
  excerpt,
  tokenCount,
  type CandidateRow,
  type ContextPolicy,
} from "./candidateRepository";

/**
 * Native TS chat context candidate collection.
 *
 * Port of `app.memory.chat_context.ChatContextBuilder.collect_candidates`: load
 * the agent version's `context_policy_json` boundary, then run the per-source
 * selectors in priority order at their per-source caps, with **no** cumulative
 * budget. Produces the same `ChatContextCandidatesResult` the Python
 * `context-candidates` port returned, so the existing `buildChatContext`
 * budget/dedup loop is unchanged. Read-only.
 */

/** All source tokens recognised by `context_policy_json.sources` (Python `_ALL_SOURCES`). */
const ALL_SOURCES: readonly string[] = [
  "memory",
  "knowledge_item",
  "source",
  "activity_record",
  "task",
  "project",
  "workspace",
  "run",
  "proposal",
  "artifact",
  "manual_context",
];

const DEFAULT_MAX_TOKENS = 4000;
const DEFAULT_MAX_ITEMS = 20;

/** Caps the per-source memory fetch (Python `min(limit, 10)`). */
const MEMORY_SOURCE_CAP = 10;

export class ChatContextError extends Error {
  constructor(
    message: string,
    readonly statusCode = 500,
    readonly body: unknown = { detail: message },
  ) {
    super(message);
    this.name = "ChatContextError";
  }
}

export class ChatContextCandidateCollector {
  constructor(private readonly repo: PgChatCandidateRepository) {}

  static fromConfig(config: ControlPlaneConfig): ChatContextCandidateCollector {
    return new ChatContextCandidateCollector(
      PgChatCandidateRepository.fromConfig(config),
    );
  }

  async fetchCandidates(
    request: ChatContextCandidatesRequest,
  ): Promise<ChatContextCandidatesResult> {
    const message = request.message.trim();
    if (!message) {
      throw new ChatContextError("message must not be empty", 422);
    }

    const policy = await this.repo.loadContextPolicy(
      request.space_id,
      request.agent_id,
    );
    const { allowed, maxTokens, maxItems } = resolvePolicy(policy);

    const items: ChatContextCandidateItem[] = [];

    // Priority order matches Python `collect_candidates`. manual_context,
    // workspace, and project never fire on the chat path (the request carries no
    // such fields), so only the four DB-backed source selectors run.
    if (allowed.has("memory")) {
      const rows = await this.repo.selectMemories(
        request.space_id,
        request.user_id,
        Math.min(maxItems, MEMORY_SOURCE_CAP),
      );
      pushItems(items, rows, "memory", 0.8, "approved_memory");
    }
    if (allowed.has("knowledge_item")) {
      const rows = await this.repo.selectKnowledgeItems(
        request.space_id,
        message,
        maxItems,
      );
      pushItems(items, rows, "knowledge_item", 0.7, "knowledge_item");
    }
    if (allowed.has("source")) {
      const rows = await this.repo.selectSources(request.space_id, maxItems);
      pushItems(items, rows, "source", 0.6, "source");
    }
    if (allowed.has("activity_record")) {
      const rows = await this.repo.selectActivityRecords(
        request.space_id,
        maxItems,
      );
      pushItems(items, rows, "activity_record", 0.5, "recent_activity");
    }

    return {
      allowed_sources: [...allowed].sort(),
      max_tokens: maxTokens,
      max_items: maxItems,
      // Python: `bool(request.agent_version_id)` — true when a current version
      // backed the policy load.
      context_policy_applied: policy.resolved,
      items,
    };
  }
}

function resolvePolicy(policy: ContextPolicy): {
  allowed: Set<string>;
  maxTokens: number;
  maxItems: number;
} {
  const raw = policy.policy;
  const sources = raw.sources;
  // Empty/absent `sources` → all sources allowed (Python `_load_policy`).
  const allowed =
    Array.isArray(sources) && sources.length > 0
      ? new Set(
          sources.filter(
            (s): s is string => typeof s === "string" && ALL_SOURCES.includes(s),
          ),
        )
      : new Set(ALL_SOURCES);
  return {
    allowed,
    maxTokens: positiveInt(raw.max_tokens, DEFAULT_MAX_TOKENS),
    maxItems: positiveInt(raw.max_items, DEFAULT_MAX_ITEMS),
  };
}

function pushItems(
  items: ChatContextCandidateItem[],
  rows: readonly CandidateRow[],
  itemType: string,
  score: number,
  reason: string,
): void {
  for (const row of rows) {
    items.push({
      item_type: itemType,
      item_id: row.item_id,
      title: row.title,
      excerpt: excerpt(row.text),
      score,
      reason,
      token_count: tokenCount(row.text),
      metadata: {},
    });
  }
}

function positiveInt(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return Math.floor(value);
  }
  return fallback;
}
