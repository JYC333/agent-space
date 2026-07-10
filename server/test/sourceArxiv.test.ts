import { afterEach, describe, expect, it, vi } from "vitest";
import type { FastifyInstance } from "fastify";
import { loadConfig } from "../src/config";
import { buildServer } from "../src/server";
import { __setAuthIdentityForTests } from "../src/modules/auth";
import {
  buildArxivQueryUrl,
  parseArxivFeed,
  parseArxivReference,
} from "../src/modules/sources/connectors/arxiv";
import {
  __setArxivThrottleForTests,
  acquireArxivRequestSlot,
} from "../src/modules/sources/connectors/arxivThrottle";
import {
  normalizeArxivQueryConfig,
  listSourcePresets,
  SourcePresetService,
} from "../src/modules/sources/sourcePresets/service";
import { SourceExtractionWorker } from "../src/modules/sources/extractionWorker";
import type { Queryable } from "../src/modules/routeUtils/common";
import { HttpError } from "../src/modules/routeUtils/common";
import { simplePdfBytes } from "./fixtures/simplePdf";
import { handleSourceRetrievalTestSql } from "./helpers/sourceRetrievalTestSql";

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    ARTIFACT_STORAGE_ROOT: "/tmp/agent-space-test-artifacts",
  });
}

const identity = { spaceId: "space-1", userId: "user-1" };

afterEach(() => {
  vi.restoreAllMocks();
  __setArxivThrottleForTests(null);
  __setAuthIdentityForTests(null);
});

// ── arXiv id / URL parsing ────────────────────────────────────────────────────

describe("parseArxivReference", () => {
  it.each([
    ["https://arxiv.org/abs/2402.08954", "2402.08954", null],
    ["https://arxiv.org/abs/2402.08954v2", "2402.08954", "v2"],
    ["https://arxiv.org/pdf/2402.08954", "2402.08954", null],
    ["https://arxiv.org/pdf/2402.08954v1.pdf", "2402.08954", "v1"],
    ["https://arxiv.org/html/2402.08954v3", "2402.08954", "v3"],
    ["http://export.arxiv.org/abs/2402.08954v1", "2402.08954", "v1"],
    ["arXiv:2402.08954v2", "2402.08954", "v2"],
    ["2402.08954", "2402.08954", null],
    ["hep-th/9901001v2", "hep-th/9901001", "v2"],
    ["https://arxiv.org/abs/hep-th/9901001v2", "hep-th/9901001", "v2"],
    ["https://arxiv.org/pdf/math.GT/0309136", "math.GT/0309136", null],
    ["https://arxiv.org/abs/physics.comp-ph/9901001v2", "physics.comp-ph/9901001", "v2"],
  ])("parses %s", (input, baseId, version) => {
    expect(parseArxivReference(input)).toEqual({ baseId, version });
  });

  it.each([
    "https://example.com/abs/2402.08954",
    "https://arxiv.org/list/cs.AI/recent",
    "https://arxiv.org/abs/not-an-id",
    "not a reference",
    "",
    null,
  ])("returns null for %s", (input) => {
    expect(parseArxivReference(input)).toBeNull();
  });
});

describe("buildArxivQueryUrl", () => {
  it("builds an export.arxiv.org query URL from a normalized config", () => {
    const url = buildArxivQueryUrl({
      search_query: 'cat:cs.AI AND all:"agent"',
      max_results: 25,
      sort_by: "lastUpdatedDate",
      sort_order: "descending",
    });
    expect(url.startsWith("https://export.arxiv.org/api/query?")).toBe(true);
    const parsed = new URL(url);
    expect(parsed.searchParams.get("search_query")).toBe('cat:cs.AI AND all:"agent"');
    expect(parsed.searchParams.get("start")).toBe("0");
    expect(parsed.searchParams.get("max_results")).toBe("25");
    expect(parsed.searchParams.get("sortBy")).toBe("lastUpdatedDate");
    expect(parsed.searchParams.get("sortOrder")).toBe("descending");
  });
});

// ── arXiv Atom parsing ────────────────────────────────────────────────────────

describe("parseArxivFeed", () => {
  it("parses arXiv Atom entries into normalized paper records", () => {
    const papers = parseArxivFeed(arxivFeed());
    expect(papers).toHaveLength(1);
    expect(papers[0]).toEqual({
      arxiv_id: "2402.08954",
      arxiv_version: "v2",
      title: "Agent Paper Title",
      authors: ["Author One", "Author Two"],
      summary: "Abstract text for the agent paper.",
      published_at: "2024-02-14T05:19:17.000Z",
      updated_at: "2024-02-15T05:19:17.000Z",
      categories: ["cs.AI", "cs.LG"],
      primary_category: "cs.AI",
      doi: "10.1234/example",
      journal_ref: "Example Journal 2024",
      comment: "10 pages",
      abs_url: "https://arxiv.org/abs/2402.08954",
      html_url: "https://arxiv.org/html/2402.08954",
      pdf_url: "https://arxiv.org/pdf/2402.08954",
    });
  });

  it("fails closed on arXiv API error entries instead of returning no papers", () => {
    const errorFeed = `<?xml version="1.0"?>
      <feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
          <id>http://arxiv.org/api/errors#incorrect_field</id>
          <title>Error</title>
          <summary>malformed query: unknown field xyz</summary>
        </entry>
      </feed>`;
    expect(() => parseArxivFeed(errorFeed)).toThrow(/arXiv API error: malformed query/);
  });

  it("skips entries without a parseable arXiv id and rejects non-Atom bodies", () => {
    const feed = `<?xml version="1.0"?>
      <feed xmlns="http://www.w3.org/2005/Atom">
        <entry><id>http://example.com/other</id><title>Other</title></entry>
      </feed>`;
    expect(parseArxivFeed(feed)).toEqual([]);
    expect(() => parseArxivFeed("<html><body>error page</body></html>")).toThrow(HttpError);
  });
});

// ── Polite throttle ───────────────────────────────────────────────────────────

describe("arXiv polite throttle", () => {
  it("spaces consecutive requests by the minimum interval using the injected clock", async () => {
    const sleeps: number[] = [];
    let nowMs = 0;
    __setArxivThrottleForTests({
      minIntervalMs: 3_000,
      now: () => nowMs,
      sleep: async (ms) => {
        sleeps.push(ms);
        nowMs += ms;
      },
    });

    await acquireArxivRequestSlot();
    await acquireArxivRequestSlot();
    await acquireArxivRequestSlot();

    expect(sleeps).toEqual([3_000, 3_000]);
  });
});

// ── Source preset service ─────────────────────────────────────────────────────

describe("normalizeArxivQueryConfig", () => {
  it("applies defaults and trims the search query", () => {
    expect(normalizeArxivQueryConfig({ search_query: "  all:agents  " }, { maxResults: 50 })).toEqual({
      mode: "search",
      categories: [],
      search_query: "all:agents",
      max_results: 50,
      sort_by: "lastUpdatedDate",
      sort_order: "descending",
    });
  });

  it("builds a recent-by-category query without requiring keywords", () => {
    expect(normalizeArxivQueryConfig({ mode: "recent_by_category", categories: ["cs.ai"] }, { maxResults: 50 })).toEqual({
      mode: "recent_by_category",
      categories: ["cs.AI"],
      search_query: "cat:cs.AI",
      max_results: 50,
      sort_by: "submittedDate",
      sort_order: "descending",
    });
  });

  it("builds a recent query from multiple categories", () => {
    expect(normalizeArxivQueryConfig(
      { mode: "recent_by_category", categories: ["cs.ai", "cs.LG", "physics.SOC-PH", "q-fin.tr", "cs.AI"] },
      { maxResults: 50 },
    )).toEqual({
      mode: "recent_by_category",
      categories: ["cs.AI", "cs.LG", "physics.soc-ph", "q-fin.TR"],
      search_query: "cat:cs.AI OR cat:cs.LG OR cat:physics.soc-ph OR cat:q-fin.TR",
      max_results: 50,
      sort_by: "submittedDate",
      sort_order: "descending",
    });
  });

  it.each([
    [{}, /search_query is required/],
    [{ search_query: "   " }, /search_query is required/],
    [{ mode: "latest" }, /mode/],
    [{ mode: "recent_by_category" }, /at least one category is required/],
    [{ mode: "recent_by_category", categories: ["not a category"] }, /category/],
    [{ mode: "recent_by_category", categories: ["cs.ZZ"] }, /official arXiv taxonomy/],
    [{ mode: "recent_by_category", categories: "cs.AI" }, /categories must be an array/],
    [{ mode: "recent_by_category", categories: ["cs.AI", 12] }, /categories must be an array/],
    [{ search_query: "x".repeat(501) }, /at most 500/],
    [{ search_query: "all:agents", max_results: 0 }, /max_results/],
    [{ search_query: "all:agents", max_results: 101 }, /max_results/],
    [{ search_query: "all:agents", max_results: 2.5 }, /max_results/],
    [{ search_query: "all:agents", sort_by: "newest" }, /sort_by/],
    [{ search_query: "all:agents", sort_order: "up" }, /sort_order/],
  ])("rejects invalid input %j", (body, message) => {
    expect(() => normalizeArxivQueryConfig(body as Record<string, unknown>, { maxResults: 50 }))
      .toThrow(message);
  });
});

describe("SourcePresetService", () => {
  it("lists the arXiv preset in the academic category", () => {
    expect(listSourcePresets().items).toEqual([
      expect.objectContaining({ id: "arxiv", category: "academic", connector_key: "arxiv" }),
    ]);
  });

  it("previewArxiv fetches the arXiv API and returns parsed papers without writing rows", async () => {
    __setArxivThrottleForTests({ sleep: async () => {} });
    const db = new PresetDb();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(arxivFeed(), { status: 200 }));

    const result = await new SourcePresetService(db, config()).previewArxiv(identity, {
      search_query: 'cat:cs.AI AND all:"agent"',
    });

    expect(result.preset_id).toBe("arxiv");
    expect(result.query_url).toContain("export.arxiv.org/api/query");
    expect(result.items).toHaveLength(1);
    expect(result.items[0]?.arxiv_id).toBe("2402.08954");
    expect(result.warnings).toEqual([]);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(result.query_url);
    expect(new URL(result.query_url).searchParams.get("max_results")).toBe("50");
    expect(db.calls.some((call) => call.sql.trimStart().toUpperCase().startsWith("INSERT"))).toBe(false);
    expect(db.calls.some((call) => call.sql.trimStart().toUpperCase().startsWith("UPDATE"))).toBe(false);
  });

  it("createArxiv creates a built-in arxiv source connection with defaults", async () => {
    const db = new PresetDb();

    await new SourcePresetService(db, config()).createArxiv(identity, {
      search_query: 'cat:cs.AI AND all:"agent"',
      schedule_rule: { frequency: "weekly", weekday: 1, hour: 9, minute: 0 },
    });

    const connectorLookup = db.calls.find((call) => call.sql.includes("FROM source_connectors"));
    expect(connectorLookup?.params[0]).toBe("arxiv");
    const insert = db.calls.find((call) => call.sql.includes("INSERT INTO source_connections"));
    expect(insert?.params[6]).toBe('arXiv: cat:cs.AI AND all:"agent"');
    expect(String(insert?.params[7])).toContain("https://export.arxiv.org/api/query?");
    expect(insert?.params[8]).toBe("weekly");
    expect(insert?.params[9]).toBe("extract_text");
    expect(JSON.parse(String(insert?.params[12]))).toMatchObject({
      allow_external_model_egress: true,
    });
    expect(JSON.parse(String(insert?.params[13]))).toMatchObject({
      source_egress_class: "external_provider_allowed",
    });
    expect(JSON.parse(String(insert?.params[14]))).toEqual({
      preset_id: "arxiv",
      mode: "search",
      categories: [],
      search_query: 'cat:cs.AI AND all:"agent"',
      max_results: 50,
      sort_by: "lastUpdatedDate",
      sort_order: "descending",
    });
    expect(JSON.parse(String(insert?.params[15]))).toEqual({ frequency: "weekly", weekday: 1, hour: 9, minute: 0 });
  });

  it("createArxiv creates a recent category source without a search keyword", async () => {
    const db = new PresetDb();

    await new SourcePresetService(db, config()).createArxiv(identity, {
      mode: "recent_by_category",
      categories: ["cs.LG"],
      schedule_rule: { frequency: "weekly", weekday: 1, hour: 9, minute: 0 },
    });

    const insert = db.calls.find((call) => call.sql.includes("INSERT INTO source_connections"));
    expect(insert?.params[6]).toBe("arXiv new: cs.LG");
    expect(new URL(String(insert?.params[7])).searchParams.get("search_query")).toBe("cat:cs.LG");
    expect(new URL(String(insert?.params[7])).searchParams.get("sortBy")).toBe("submittedDate");
    expect(JSON.parse(String(insert?.params[14]))).toEqual({
      preset_id: "arxiv",
      mode: "recent_by_category",
      categories: ["cs.LG"],
      search_query: "cat:cs.LG",
      max_results: 50,
      sort_by: "submittedDate",
      sort_order: "descending",
    });
  });

  it("createArxiv creates one recent source for multiple categories", async () => {
    const db = new PresetDb();

    await new SourcePresetService(db, config()).createArxiv(identity, {
      mode: "recent_by_category",
      categories: ["cs.LG", "stat.ml"],
      schedule_rule: { frequency: "weekly", weekday: 1, hour: 9, minute: 0 },
    });

    const insert = db.calls.find((call) => call.sql.includes("INSERT INTO source_connections"));
    expect(insert?.params[6]).toBe("arXiv new: cs.LG + stat.ML");
    expect(new URL(String(insert?.params[7])).searchParams.get("search_query")).toBe("cat:cs.LG OR cat:stat.ML");
    expect(JSON.parse(String(insert?.params[14]))).toEqual({
      preset_id: "arxiv",
      mode: "recent_by_category",
      categories: ["cs.LG", "stat.ML"],
      search_query: "cat:cs.LG OR cat:stat.ML",
      max_results: 50,
      sort_by: "submittedDate",
      sort_order: "descending",
    });
  });

  it("createArxiv rejects unsupported fetch frequencies", async () => {
    const db = new PresetDb();
    await expect(
      new SourcePresetService(db, config()).createArxiv(identity, {
        search_query: "all:agents",
        fetch_frequency: "yearly",
      }),
    ).rejects.toThrow(/fetch_frequency/);
  });
});

// ── Preset routes ─────────────────────────────────────────────────────────────

describe("source preset routes", () => {
  let app: FastifyInstance | undefined;

  afterEach(async () => {
    await app?.close();
    app = undefined;
  });

  it("returns 401 to unauthenticated preset requests", async () => {
    app = buildServer(config(), { logger: false });
    for (const request of [
      { method: "GET" as const, url: "/api/v1/sources/source-presets" },
      { method: "POST" as const, url: "/api/v1/sources/source-presets/arxiv/preview" },
      { method: "POST" as const, url: "/api/v1/sources/source-presets/arxiv" },
    ]) {
      const res = await app.inject(request);
      expect(res.statusCode).toBe(401);
    }
  });

  it("lists the arXiv preset for authenticated users", async () => {
    __setAuthIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/sources/source-presets" });

    expect(res.statusCode).toBe(200);
    expect(res.json().items).toEqual([
      expect.objectContaining({
        id: "arxiv",
        category: "academic",
        display_name: "arXiv",
        connector_key: "arxiv",
        fields: expect.arrayContaining(["mode", "search_query", "categories", "max_results", "sort_by", "sort_order"]),
        category_options: expect.arrayContaining([
          expect.objectContaining({
            group: "Computer Science",
            options: expect.arrayContaining([
              expect.objectContaining({ value: "cs.AI", label: "Artificial Intelligence" }),
            ]),
          }),
        ]),
      }),
    ]);
  });
});

// ── HTML-first extraction ─────────────────────────────────────────────────────

describe("SourceExtractionWorker arXiv HTML-first extraction", () => {
  it("extracts arXiv abs URLs from the HTML rendition first", async () => {
    __setArxivThrottleForTests({ sleep: async () => {} });
    const db = new ExtractionDb("extract_text", "https://arxiv.org/abs/2402.08954");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(
      "<html><body><article><h1>Agent Paper</h1><p>Full paper text.</p></article></body></html>",
      { status: 200 },
    ));

    const result = await new SourceExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("succeeded");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("https://arxiv.org/html/2402.08954");
    const artifactInserts = db.calls.filter((call) => call.sql.includes("INSERT INTO artifacts"));
    expect(artifactInserts).toHaveLength(1);
    expect(artifactInserts[0]?.sql).toContain("'source_reader_document'");
    expect(String(artifactInserts[0]?.params[3])).toContain("\"extraction_method\":\"structured_html_v1\"");
    const artifactMetadata = JSON.parse(String(artifactInserts[0]?.params[6]));
    expect(artifactMetadata).toMatchObject({
      content_source_format: "html",
      content_source_url: "https://arxiv.org/html/2402.08954",
      arxiv_id: "2402.08954",
    });
    const snapshotInsert = db.calls.find((call) => call.sql.includes("INSERT INTO source_snapshots"));
    expect(JSON.parse(String(snapshotInsert?.params[10]))).toMatchObject({
      content_source_format: "html",
      arxiv_id: "2402.08954",
    });
  });

  it("falls back to the PDF rendition when the HTML rendition is unavailable", async () => {
    __setArxivThrottleForTests({ sleep: async () => {} });
    const db = new ExtractionDb("extract_text", "https://arxiv.org/abs/2402.08954");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("Not found", { status: 404 }))
      .mockResolvedValueOnce(new Response(simplePdfBytes("Agent Paper PDF"), {
        status: 200,
        headers: { "content-type": "application/pdf" },
      }));

    const result = await new SourceExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("succeeded");
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("https://arxiv.org/html/2402.08954");
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe("https://arxiv.org/pdf/2402.08954");
    const artifactInserts = db.calls.filter((call) => call.sql.includes("INSERT INTO artifacts"));
    expect(artifactInserts).toHaveLength(2);
    expect(artifactInserts[0]?.sql).toContain("'source_raw_snapshot'");
    expect(artifactInserts[0]?.params[4]).toBe("application/pdf");
    expect(artifactInserts[1]?.sql).toContain("'source_reader_document'");
    expect(String(artifactInserts[1]?.params[3])).toContain("\"extraction_method\":\"pdf_text_v1\"");
    const extractedSnapshot = db.calls.filter((call) => call.sql.includes("INSERT INTO source_snapshots")).at(-1);
    expect(JSON.parse(String(extractedSnapshot?.params[10]))).toMatchObject({
      content_source_format: "pdf",
      content_source_url: "https://arxiv.org/pdf/2402.08954",
      fallback_from: "html",
      fallback_reason: expect.stringContaining("404"),
      arxiv_id: "2402.08954",
    });
  });

  it("uses HTML first for manually saved arXiv PDF URLs", async () => {
    __setArxivThrottleForTests({ sleep: async () => {} });
    const db = new ExtractionDb("extract_text", "https://arxiv.org/pdf/2402.08954v1");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(
      "<html><body><article><p>HTML rendition text.</p></article></body></html>",
      { status: 200 },
    ));

    const result = await new SourceExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("succeeded");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("https://arxiv.org/html/2402.08954");
  });

  it("fails the job with the last meaningful error when every arXiv candidate fails", async () => {
    __setArxivThrottleForTests({ sleep: async () => {} });
    const db = new ExtractionDb("extract_text", "https://arxiv.org/abs/2402.08954");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("Not found", { status: 404 }));

    const result = await new SourceExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("failed");
    const finish = db.calls.find((call) => call.sql.includes("SET status = $3"));
    expect(finish?.params[2]).toBe("failed");
    expect(finish?.params[5]).toContain("404");
  });

  it("keeps single-fetch behavior for non-arXiv URLs", async () => {
    const db = new ExtractionDb("extract_text", "https://example.test/article");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(
      "<html><body><article><p>Regular article.</p></article></body></html>",
      { status: 200 },
    ));

    const result = await new SourceExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("succeeded");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("https://example.test/article");
    const snapshotInsert = db.calls.find((call) => call.sql.includes("INSERT INTO source_snapshots"));
    expect(JSON.parse(String(snapshotInsert?.params[10]))).not.toHaveProperty("content_source_format");
  });

  it("prefers the HTML raw snapshot for arXiv snapshot jobs", async () => {
    __setArxivThrottleForTests({ sleep: async () => {} });
    const db = new ExtractionDb("snapshot", "https://arxiv.org/abs/2402.08954", "full_snapshot");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(
      "<html><body><article><p>HTML rendition text.</p></article></body></html>",
      { status: 200, headers: { "content-type": "text/html" } },
    ));

    const result = await new SourceExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("succeeded");
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("https://arxiv.org/html/2402.08954");
    const artifactInserts = db.calls.filter((call) => call.sql.includes("INSERT INTO artifacts"));
    expect(artifactInserts[0]?.sql).toContain("'source_raw_snapshot'");
    expect(artifactInserts[0]?.params[4]).toBe("text/html");
    expect(artifactInserts[1]?.sql).toContain("'source_reader_document'");
  });
});

// ── Fakes and fixtures ────────────────────────────────────────────────────────

/** Fake Queryable for preset service tests (settings + createConnection path). */
class PresetDb implements Queryable {
  readonly calls: Array<{ sql: string; params: readonly unknown[] }> = [];
  private lastConnection: Record<string, unknown> | undefined;

  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
    this.calls.push({ sql, params });
    if (sql.includes("AS effective_access_level")) {
      return this.lastConnection
        ? { rows: [{ effective_access_level: "full" }] as Row[], rowCount: 1 }
        : { rows: [] as Row[], rowCount: 0 };
    }
    if (sql.includes("FROM settings")) {
      return { rows: [] as Row[], rowCount: 0 };
    }
    if (sql.includes("JOIN source_connectors")) {
      // getConnectionRow's re-fetch after createConnection inserts + subscribes.
      return { rows: [{ ...this.lastConnection, subscription_status: "subscribed" }] as Row[], rowCount: 1 };
    }
    if (sql.includes("FROM source_connectors")) {
      return { rows: [{ id: "connector-arxiv" }] as Row[], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO source_connections")) {
      this.lastConnection = connectionRow(params);
      return { rows: [this.lastConnection] as Row[], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO source_connection_user_subscriptions")) {
      return { rows: [{ status: params[4] }] as Row[], rowCount: 1 };
    }
    if (sql.includes("SELECT type FROM spaces")) {
      // Personal space: createDefaultPendingSubscriptions short-circuits
      // before fanning pending subscriptions out to other space members.
      return { rows: [{ type: "personal" }] as Row[], rowCount: 1 };
    }
    if (sql.includes("FROM scheduler_tasks")) {
      return { rows: [] as Row[], rowCount: 0 };
    }
    if (sql.includes("INSERT INTO scheduler_tasks")) {
      return { rows: [schedulerTaskRow(params)] as Row[], rowCount: 1 };
    }
    throw new Error(`unexpected SQL: ${sql}`);
  }
}

function connectionRow(params: readonly unknown[]): Record<string, unknown> {
  return {
    id: params[0],
    space_id: params[1],
    connector_id: params[2],
    owner_user_id: params[3],
    credential_id: params[4],
    visibility: params[5],
    access_level: "full",
    name: params[6],
    endpoint_url: params[7],
    status: "active",
    fetch_frequency: params[8],
    capture_policy: params[9],
    trust_level: params[10],
    topic_hints_json: null,
    consent_json: {},
    policy_json: {},
    config_json: JSON.parse(String(params[14])),
    schedule_rule_json: JSON.parse(String(params[15])),
    handler_kind: "built_in",
    active_handler_version_id: null,
    active_recipe_version_id: null,
    repair_status: "ok",
    last_handler_run_id: null,
    last_checked_at: null,
    next_check_at: null,
    created_at: "2026-07-03T00:00:00.000Z",
    updated_at: "2026-07-03T00:00:00.000Z",
    deleted_at: null,
  };
}

function schedulerTaskRow(params: readonly unknown[]): Record<string, unknown> {
  return {
    id: params[0],
    task_type: params[1],
    task_key: params[2],
    scope_type: params[3],
    scope_id: params[4],
    space_id: params[5] ?? null,
    user_id: params[6] ?? null,
    status: params[7],
    next_run_at: params[8] ?? null,
    last_run_at: params[9] ?? null,
    state_json: {},
    created_at: "2026-07-03T00:00:00.000Z",
    updated_at: "2026-07-03T00:00:00.000Z",
  };
}

/** Fake Queryable for extraction jobs against a configurable item source_uri. */
class ExtractionDb implements Queryable {
  readonly calls: Array<{ sql: string; params: readonly unknown[] }> = [];
  private status = "running";

  constructor(
    private readonly jobType: "extract_text" | "snapshot",
    private readonly sourceUri: string,
    private readonly policyRetention: "full_text" | "full_snapshot" = "full_text",
  ) {}

  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
    this.calls.push({ sql, params });
    const retrievalResult = handleSourceRetrievalTestSql<Row>(sql, params);
    if (retrievalResult) return retrievalResult;
    if (sql.includes("SET status = 'running'")) {
      return { rows: [this.jobRow()] as Row[], rowCount: 1 };
    }
    if (sql.includes("SELECT id, space_id, connection_id, source_uri")) {
      return {
        rows: [{
          id: "item-1",
          space_id: "space-1",
          connection_id: "conn-1",
          source_uri: this.sourceUri,
          title: "arXiv paper",
          content_state: "content_queued",
        }] as Row[],
        rowCount: 1,
      };
    }
    if (sql.includes("FROM source_connections")) {
      return {
        rows: [{
          id: "conn-1",
          space_id: "space-1",
          connector_id: "connector-1",
          owner_user_id: "user-1",
          capture_policy: "extract_text",
          trust_level: "normal",
          consent_json: {},
          policy_json: { retention_policy: this.policyRetention },
        }] as Row[],
        rowCount: 1,
      };
    }
    if (sql.includes("FROM scheduler_tasks") || sql.includes("FROM settings")) {
      return { rows: [] as Row[], rowCount: 0 };
    }
    if (
      sql.includes("INSERT INTO artifacts") ||
      sql.includes("INSERT INTO source_snapshots") ||
      sql.includes("UPDATE source_items") ||
      sql.includes("INSERT INTO extracted_evidence") ||
      sql.includes("UPDATE extraction_jobs SET source_snapshot_id")
    ) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO evidence_links")) {
      return { rows: [] as Row[], rowCount: 0 };
    }
    if (sql.includes("SET status = $3")) {
      this.status = String(params[2]);
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("SELECT") && sql.includes("FROM extraction_jobs")) {
      return { rows: [{ ...this.jobRow(), status: this.status }] as Row[], rowCount: 1 };
    }
    throw new Error(`unexpected SQL: ${sql}`);
  }

  private jobRow() {
    return {
      id: "job-1",
      space_id: "space-1",
      connection_id: "conn-1",
      source_item_id: "item-1",
      source_object_type: null,
      source_object_id: null,
      job_type: this.jobType,
      status: "running",
      metadata_json: {},
    };
  }
}

function arxivFeed() {
  return `<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <title>ArXiv Query: search_query=cat:cs.AI</title>
      <entry>
        <id>http://arxiv.org/abs/2402.08954v2</id>
        <updated>2024-02-15T05:19:17Z</updated>
        <published>2024-02-14T05:19:17Z</published>
        <title>Agent  Paper
   Title</title>
        <summary>  Abstract text for
 the agent paper.
</summary>
        <author><name>Author One</name></author>
        <author><name>Author Two</name></author>
        <arxiv:doi>10.1234/example</arxiv:doi>
        <arxiv:comment>10 pages</arxiv:comment>
        <arxiv:journal_ref>Example Journal 2024</arxiv:journal_ref>
        <link href="http://arxiv.org/abs/2402.08954v2" rel="alternate" type="text/html"/>
        <link title="pdf" href="http://arxiv.org/pdf/2402.08954v2" rel="related" type="application/pdf"/>
        <arxiv:primary_category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
        <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
        <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
      </entry>
    </feed>`;
}
