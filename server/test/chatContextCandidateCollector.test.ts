import { describe, expect, it } from "vitest";
import { ChatContextCandidateCollector } from "../src/modules/context/chatCandidateCollector";
import { PgChatCandidateRepository } from "../src/modules/context/candidateRepository";
import type { Queryable } from "../src/modules/memory/repository";

interface Call {
  sql: string;
  params: readonly unknown[];
}

/**
 * Fake `Queryable` that dispatches by the table named in the SQL. Lets the
 * collector + repository run end-to-end without a database, the way the budget
 * loop is unit-tested.
 */
class FakeDb implements Queryable {
  readonly calls: Call[] = [];
  constructor(
    private readonly rowsByTable: Record<string, Record<string, unknown>[]>,
  ) {}

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<{ rows: Row[]; rowCount: number | null }> {
    this.calls.push({ sql, params });
    const table = tableOf(sql);
    const rows = (this.rowsByTable[table] ?? []) as Row[];
    return { rows, rowCount: rows.length };
  }
}

function tableOf(sql: string): string {
  if (sql.includes("FROM agents")) return "policy";
  if (sql.includes("FROM memory_entries")) return "memory_entries";
  if (sql.includes("FROM knowledge_items")) return "knowledge_items";
  if (sql.includes("FROM sources")) return "sources";
  if (sql.includes("FROM activity_records")) return "activity_records";
  return "unknown";
}

function memoryRow(over: Record<string, unknown>): Record<string, unknown> {
  return {
    id: "m1",
    space_id: "space-1",
    subject_user_id: "user-1",
    owner_user_id: "user-1",
    workspace_id: null,
    scope_type: "user",
    namespace: null,
    memory_type: "fact",
    title: "Mem",
    content: "memory content",
    status: "active",
    visibility: "private",
    sensitivity_level: "normal",
    selected_user_ids: null,
    deleted_at: null,
    importance: 0.9,
    confidence: 0.9,
    ...over,
  };
}

const request = {
  agent_id: "agent-1",
  space_id: "space-1",
  user_id: "user-1",
  session_id: "session-1",
  message: "hello world",
};

function collector(db: FakeDb): ChatContextCandidateCollector {
  return new ChatContextCandidateCollector(new PgChatCandidateRepository(db));
}

describe("ChatContextCandidateCollector", () => {
  it("rejects an empty message before touching the DB", async () => {
    const db = new FakeDb({});
    await expect(
      collector(db).fetchCandidates({ ...request, message: "   " }),
    ).rejects.toMatchObject({ statusCode: 422 });
    expect(db.calls).toHaveLength(0);
  });

  it("defaults to all sources when the version policy is empty", async () => {
    const db = new FakeDb({
      policy: [{ context_policy_json: {} }],
      memory_entries: [memoryRow({})],
      knowledge_items: [{ id: "k1", title: "K", content: "knowledge" }],
      sources: [{ id: "s1", title: "S", summary: "src summary", raw_text: null }],
      activity_records: [{ id: "a1", title: "A", content: "activity" }],
    });
    const result = await collector(db).fetchCandidates(request);

    expect(result.context_policy_applied).toBe(true);
    expect(result.max_tokens).toBe(4000);
    expect(result.max_items).toBe(20);
    // Priority order: memory, knowledge_item, source, activity_record.
    expect(result.items.map((i) => i.item_type)).toEqual([
      "memory",
      "knowledge_item",
      "source",
      "activity_record",
    ]);
    const memory = result.items[0];
    expect(memory).toMatchObject({
      item_id: "m1",
      excerpt: "memory content",
      score: 0.8,
      reason: "approved_memory",
      token_count: Math.floor("memory content".length / 4),
    });
    // allowed_sources echoes the full recognised set, sorted.
    expect(result.allowed_sources).toContain("workspace");
    expect(result.allowed_sources).toEqual([...result.allowed_sources].sort());
  });

  it("honors the context_policy_json sources allow-list and caps", async () => {
    const db = new FakeDb({
      policy: [
        {
          context_policy_json: {
            sources: ["memory"],
            max_tokens: 1000,
            max_items: 5,
          },
        },
      ],
      memory_entries: [memoryRow({})],
      knowledge_items: [{ id: "k1", title: "K", content: "knowledge" }],
    });
    const result = await collector(db).fetchCandidates(request);

    expect(result.allowed_sources).toEqual(["memory"]);
    expect(result.max_tokens).toBe(1000);
    expect(result.max_items).toBe(5);
    expect(result.items.map((i) => i.item_type)).toEqual(["memory"]);
    // knowledge_items must not be queried when not allowed.
    expect(db.calls.some((c) => c.sql.includes("FROM knowledge_items"))).toBe(
      false,
    );
  });

  it("applies memory read authorization and never logs reads", async () => {
    const db = new FakeDb({
      policy: [{ context_policy_json: { sources: ["memory"] } }],
      memory_entries: [
        memoryRow({ id: "mine", owner_user_id: "user-1" }),
        // Private memory owned by another user — must be filtered out.
        memoryRow({ id: "theirs", owner_user_id: "user-2", subject_user_id: "user-2" }),
      ],
    });
    const result = await collector(db).fetchCandidates(request);

    expect(result.items.map((i) => i.item_id)).toEqual(["mine"]);
    // No INSERT into memory_access_logs; chat candidate collection is read-only.
    expect(db.calls.some((c) => c.sql.includes("memory_access_logs"))).toBe(false);
  });

  it("marks context_policy_applied false when no current version resolves", async () => {
    const db = new FakeDb({ policy: [] });
    const result = await collector(db).fetchCandidates(request);
    expect(result.context_policy_applied).toBe(false);
    // Falls back to all sources, so the DB-backed selectors still run.
    expect(db.calls.some((c) => c.sql.includes("FROM memory_entries"))).toBe(true);
  });
});
