import { createHash } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import { IntakeExtractionWorker } from "../src/modules/intake/extractionWorker";
import type { Queryable } from "../src/modules/routeUtils/common";

type ConnectorKey = "rss" | "atom" | "web_page";
type CapturePolicy =
  | "metadata_only"
  | "excerpt_only"
  | "auto_extract_all_text"
  | "archive_all_snapshots";
type ChildJob = {
  id: string;
  connection_id: string | null;
  intake_item_id: string | null;
  job_type: "extract_text" | "snapshot";
  status: string;
  metadata_json: Record<string, unknown>;
};

class ScanDb implements Queryable {
  readonly calls: Array<{ sql: string; params: readonly unknown[] }> = [];
  private itemId = "item-new";
  private status = "running";
  private readonly childJobs: ChildJob[] = [];
  private schedulerTask: Record<string, unknown> | null = {
    id: "task-1",
    task_type: "source_connection_scan",
    task_key: "conn-1",
    scope_type: "space",
    scope_id: "space-1",
    space_id: "space-1",
    user_id: "user-1",
    status: "active",
    next_run_at: null,
    last_run_at: null,
    state_json: {},
    created_at: "2026-06-30T00:00:00.000Z",
    updated_at: "2026-06-30T00:00:00.000Z",
  };

  constructor(private readonly input: {
    connectorKey: ConnectorKey
    capturePolicy: CapturePolicy
    policyRetention: "metadata_only" | "summary_only" | "full_text" | "full_snapshot"
    configJson?: Record<string, unknown>
    existingItemId?: string
    existingContentState?: string
    existingFollowUpStatus?: "pending" | "running" | "failed"
    manualScan?: boolean
    runFollowUpJobs?: boolean
  }) {}

  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
    this.calls.push({ sql, params });
    if (sql.includes("SET status = 'running'")) {
      const jobId = String(params[0]);
      const child = this.childJobs.find((entry) => entry.id === jobId);
      if (child) {
        child.status = "running";
        return { rows: [childJobRow(child)] as Row[], rowCount: 1 };
      }
      return { rows: [scanJob(this.input.manualScan ? "manual_scan" : "scheduler")] as Row[], rowCount: 1 };
    }
    if (sql.includes("JOIN source_connectors")) {
      return { rows: [this.connection()] as Row[], rowCount: 1 };
    }
    if (sql.includes("FROM scheduler_tasks")) {
      return {
        rows: this.schedulerTask ? [this.schedulerTask as Row] : [],
        rowCount: this.schedulerTask ? 1 : 0,
      };
    }
    if (sql.includes("INSERT INTO scheduler_tasks")) {
      this.schedulerTask = {
        id: this.schedulerTask?.id ?? params[0],
        task_type: params[1],
        task_key: params[2],
        scope_type: params[3],
        scope_id: params[4],
        space_id: params[5] ?? null,
        user_id: params[6] ?? null,
        status: params[7],
        next_run_at: params[8] ?? null,
        last_run_at: params[9] ?? this.schedulerTask?.last_run_at ?? null,
        state_json: JSON.parse(String(params[10] ?? "{}")),
        created_at: this.schedulerTask?.created_at ?? params[11],
        updated_at: params[11],
      };
      return { rows: [this.schedulerTask as Row], rowCount: 1 };
    }
    if (sql.includes("FROM source_connections")) {
      return { rows: [this.connection()] as Row[], rowCount: 1 };
    }
    if (sql.includes("SELECT id, space_id, connection_id, source_uri") && sql.includes("FROM intake_items")) {
      return { rows: [this.intakeItem()] as Row[], rowCount: 1 };
    }
    if (sql.includes("content_state = 'extraction_failed'") && sql.includes("FROM intake_items")) {
      const rows = this.input.existingItemId && this.input.existingContentState === "extraction_failed"
        ? [{ id: this.input.existingItemId }]
        : [];
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (sql.includes("SELECT id") && sql.includes("FROM intake_items")) {
      const rows = this.input.existingItemId
        ? [{ id: this.input.existingItemId, content_state: this.input.existingContentState ?? "metadata_only" }]
        : [];
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (sql.includes("INSERT INTO intake_items")) {
      this.itemId = String(params[0]);
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("UPDATE intake_items") && sql.includes("SET title = $3")) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("UPDATE intake_items")) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO artifacts")) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO source_snapshots")) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO extracted_evidence")) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO extraction_jobs")) {
      this.childJobs.push({
        id: String(params[0]),
        connection_id: nullableString(params[2]),
        intake_item_id: nullableString(params[3]),
        job_type: params[5] === "snapshot" ? "snapshot" : "extract_text",
        status: "pending",
        metadata_json: JSON.parse(String(params[6])) as Record<string, unknown>,
      });
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("UPDATE source_connections")) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("UPDATE extraction_jobs") && sql.includes("items_seen")) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("SET status = $3")) {
      const jobId = String(params[0]);
      const child = this.childJobs.find((entry) => entry.id === jobId);
      if (child) {
        child.status = String(params[2]);
      } else {
        this.status = String(params[2]);
      }
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("UPDATE extraction_jobs SET source_snapshot_id")) {
      return { rows: [] as Row[], rowCount: 1 };
    }
    if (sql.includes("status IN ('pending', 'running')")) {
      const rows = this.input.existingFollowUpStatus === "pending" || this.input.existingFollowUpStatus === "running"
        ? [{ id: "job-existing-follow-up" }]
        : [];
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (sql.includes("metadata_json->>'parent_job_id'")) {
      const rows = this.input.runFollowUpJobs
        ? this.childJobs
          .filter((child) => child.status === "pending" && child.metadata_json.parent_job_id === params[1])
          .map((child) => ({ id: child.id }))
        : [];
      return { rows: rows as Row[], rowCount: rows.length };
    }
    if (sql.includes("FROM extraction_jobs")) {
      const jobId = String(params[0]);
      const child = this.childJobs.find((entry) => entry.id === jobId);
      if (child) return { rows: [childJobRow(child)] as Row[], rowCount: 1 };
      return {
        rows: [{
          ...scanJob(this.input.manualScan ? "manual_scan" : "scheduler"),
          status: this.status,
          intake_item_id: this.itemId,
        }] as Row[],
        rowCount: 1,
      };
    }
    throw new Error(`unexpected SQL: ${sql}`);
  }

  private connection() {
    return {
      id: "conn-1",
      space_id: "space-1",
      connector_id: "connector-1",
      owner_user_id: "user-1",
      credential_id: null,
      name: "Source",
      endpoint_url: "https://example.test/feed.xml",
      status: "active",
      fetch_frequency: "hourly",
      capture_policy: this.input.capturePolicy,
      trust_level: "normal",
      topic_hints_json: null,
      consent_json: {},
      policy_json: {
        retention_policy: this.input.policyRetention,
        source_egress_class: "internal_only",
        derived_write_policy: "proposal_required",
      },
      config_json: this.input.configJson ?? {},
      last_checked_at: null,
      next_check_at: null,
      created_at: "2026-06-30T00:00:00.000Z",
      updated_at: "2026-06-30T00:00:00.000Z",
      connector_key: this.input.connectorKey,
      deleted_at: null,
    };
  }

  private intakeItem() {
    const sourceUri = this.input.connectorKey === "web_page"
      ? "https://example.test/feed.xml"
      : "https://example.test/item-1";
    return {
      id: this.input.existingItemId ?? this.itemId,
      space_id: "space-1",
      connection_id: "conn-1",
      source_uri: sourceUri,
      canonical_uri: sourceUri,
      source_external_id: "guid-1",
      title: "Feed item",
      excerpt: "Feed excerpt.",
      author: null,
      occurred_at: "2026-06-30T09:00:00.000Z",
      content_state: "content_queued",
    };
  }
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("IntakeExtractionWorker connection_scan", () => {
  it("fetches an RSS feed, writes item/snapshot/evidence, and stores the new scan cursor", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "excerpt_only",
      policyRetention: "summary_only",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(rssFeed(), {
      status: 200,
      headers: {
        etag: "\"feed-v1\"",
        "last-modified": "Tue, 30 Jun 2026 09:30:00 GMT",
      },
    }));

    await expect(new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1"))
      .resolves.toMatchObject({ status: "succeeded" });

    expect(db.calls.some(call => call.sql.includes("INSERT INTO intake_items"))).toBe(true);
    expect(db.calls.some(call => call.sql.includes("INSERT INTO source_snapshots"))).toBe(true);
    expect(db.calls.some(call => call.sql.includes("INSERT INTO extracted_evidence"))).toBe(true);
    const connectionUpdate = db.calls.find(call => call.sql.includes("UPDATE source_connections"));
    expect(JSON.parse(String(connectionUpdate?.params[2])).scan_cursor).toEqual({
      etag: "\"feed-v1\"",
      last_modified: "Tue, 30 Jun 2026 09:30:00 GMT",
      last_guid: "guid-1",
      last_published_at: "2026-06-30T09:00:00.000Z",
    });
    const stats = db.calls.find(call => call.sql.includes("items_seen"));
    expect(stats?.params.slice(2, 5)).toEqual([1, 1, 0]);
  });

  it("updates an existing feed item when canonical/source/hash dedupe finds one", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "metadata_only",
      policyRetention: "metadata_only",
      existingItemId: "item-existing",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(rssFeed(), { status: 200 }));

    await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(db.calls.some(call => call.sql.includes("INSERT INTO intake_items"))).toBe(false);
    expect(db.calls.some(call => call.sql.includes("UPDATE intake_items") && call.sql.includes("SET title = $3"))).toBe(true);
    const stats = db.calls.find(call => call.sql.includes("items_seen"));
    expect(stats?.params.slice(2, 5)).toEqual([1, 0, 1]);
  });

  it("scans web pages with title, excerpt, and raw content hash", async () => {
    const raw = "<html><head><title>Hello page</title></head><body><p>Visible text.</p></body></html>";
    const db = new ScanDb({
      connectorKey: "web_page",
      capturePolicy: "metadata_only",
      policyRetention: "metadata_only",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(raw, { status: 200 }));

    await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    const insert = db.calls.find(call => call.sql.includes("INSERT INTO intake_items"));
    expect(insert?.params[3]).toBe("external_url");
    expect(insert?.params[4]).toBe("Hello page");
    expect(insert?.params[12]).toBe(sha256(raw));
    expect(insert?.params[13]).toContain("Visible text.");
  });

  it("sends conditional fetch headers and advances scan state on 304 responses", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "metadata_only",
      policyRetention: "metadata_only",
      configJson: {
        scan_cursor: {
          etag: "\"old\"",
          last_modified: "Tue, 30 Jun 2026 08:00:00 GMT",
          last_guid: "guid-old",
        },
      },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 304 }));

    await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(fetchMock).toHaveBeenCalledWith("https://example.test/feed.xml", {
      redirect: "follow",
      headers: {
        "If-None-Match": "\"old\"",
        "If-Modified-Since": "Tue, 30 Jun 2026 08:00:00 GMT",
      },
    });
    expect(db.calls.some(call => call.sql.includes("INSERT INTO intake_items"))).toBe(false);
    const stats = db.calls.find(call => call.sql.includes("items_seen"));
    expect(stats?.params.slice(2, 5)).toEqual([0, 0, 0]);
    expect(JSON.parse(String(stats?.params[5]))).toEqual({ not_modified: true });
  });

  it("queues extract_text follow-up jobs for auto_extract_all_text scans", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "auto_extract_all_text",
      policyRetention: "full_text",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(rssFeed(), { status: 200 }));

    await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    const followUp = db.calls.find(call =>
      call.sql.includes("INSERT INTO extraction_jobs") && call.params[5] === "extract_text"
    );
    expect(followUp?.params[2]).toBe("conn-1");
    expect(followUp?.params[3]).toEqual(expect.any(String));
    expect(db.calls.some(call => call.sql.includes("INSERT INTO extracted_evidence"))).toBe(false);
  });

  it("runs extract_text follow-up jobs after a successful full-text scan", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "auto_extract_all_text",
      policyRetention: "full_text",
      runFollowUpJobs: true,
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(rssFeed(), { status: 200 }))
      .mockResolvedValueOnce(new Response("<html><body><article>Full article text.</article></body></html>", { status: 200 }));

    await expect(new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1"))
      .resolves.toMatchObject({ status: "succeeded" });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("https://example.test/item-1");
    const childClaim = db.calls.find((call) =>
      call.sql.includes("SET status = 'running'") && call.params[0] !== "job-1"
    );
    expect(childClaim).toBeTruthy();
    const childFinish = db.calls.find((call) =>
      call.sql.includes("SET status = $3") && call.params[0] !== "job-1"
    );
    expect(childFinish?.params[2]).toBe("succeeded");
    const artifactInsert = db.calls.find((call) => call.sql.includes("INSERT INTO artifacts"));
    expect(artifactInsert?.sql).toContain("export_formats_json");
    expect(artifactInsert?.params).toContain(JSON.stringify(["txt"]));
  });

  it("queues extract_text when an existing shallow feed item is upgraded to full-text capture", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "auto_extract_all_text",
      policyRetention: "full_text",
      existingItemId: "item-existing",
      existingContentState: "metadata_only",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(rssFeed(), { status: 200 }));

    await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(db.calls.some(call => call.sql.includes("INSERT INTO intake_items"))).toBe(false);
    const followUp = db.calls.find(call =>
      call.sql.includes("INSERT INTO extraction_jobs") && call.params[5] === "extract_text"
    );
    expect(followUp?.params[3]).toBe("item-existing");
  });

  it("queues extract_text when an existing failed feed item is rescanned", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "auto_extract_all_text",
      policyRetention: "full_text",
      existingItemId: "item-existing",
      existingContentState: "extraction_failed",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(rssFeed(), { status: 200 }));

    await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    const itemUpdate = db.calls.find(call =>
      call.sql.includes("UPDATE intake_items") && call.sql.includes("SET title = $3")
    );
    expect(itemUpdate?.sql).toContain("extraction_failed");
    expect(itemUpdate?.params[12]).toBe("content_queued");
    const followUp = db.calls.find(call =>
      call.sql.includes("INSERT INTO extraction_jobs") && call.params[5] === "extract_text"
    );
    expect(followUp?.params[3]).toBe("item-existing");
  });

  it("does not queue a duplicate extract_text job when one is already active", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "auto_extract_all_text",
      policyRetention: "full_text",
      existingItemId: "item-existing",
      existingContentState: "extraction_failed",
      existingFollowUpStatus: "pending",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(rssFeed(), { status: 200 }));

    await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(db.calls.some(call => call.sql.includes("INSERT INTO extraction_jobs"))).toBe(false);
  });

  it("retries failed extract_text jobs on manual not-modified scans", async () => {
    const db = new ScanDb({
      connectorKey: "rss",
      capturePolicy: "auto_extract_all_text",
      policyRetention: "full_text",
      existingItemId: "item-existing",
      existingContentState: "extraction_failed",
      manualScan: true,
      runFollowUpJobs: true,
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 304 }))
      .mockResolvedValueOnce(new Response("<html><body><article>Retried full text.</article></body></html>", { status: 200 }));

    await expect(new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1"))
      .resolves.toMatchObject({ status: "succeeded" });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("https://example.test/item-1");
    const followUp = db.calls.find(call =>
      call.sql.includes("INSERT INTO extraction_jobs") && call.params[5] === "extract_text"
    );
    expect(followUp?.params[3]).toBe("item-existing");
    expect(JSON.parse(String(followUp?.params[6]))).toMatchObject({
      created_by: "connection_scan_retry",
      retry_reason: "previous_extraction_failed",
    });
    const childFinish = db.calls.find((call) =>
      call.sql.includes("SET status = $3") && call.params[0] !== "job-1"
    );
    expect(childFinish?.params[2]).toBe("succeeded");
  });
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    ARTIFACT_STORAGE_ROOT: "/tmp/agent-space-test-artifacts",
  });
}

function scanJob(createdBy: "manual_scan" | "scheduler" = "scheduler") {
  return {
    id: "job-1",
    space_id: "space-1",
    connection_id: "conn-1",
    intake_item_id: null,
    source_object_type: null,
    source_object_id: null,
    job_type: "connection_scan",
    status: "running",
    metadata_json: { created_by: createdBy },
  };
}

function childJobRow(job: ChildJob) {
  return {
    id: job.id,
    space_id: "space-1",
    connection_id: job.connection_id,
    intake_item_id: job.intake_item_id,
    source_object_type: null,
    source_object_id: null,
    job_type: job.job_type,
    status: job.status,
    metadata_json: job.metadata_json,
  };
}

function nullableString(value: unknown): string | null {
  return value == null ? null : String(value);
}

function rssFeed() {
  return `<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Feed item</title>
          <link>https://example.test/item-1</link>
          <guid>guid-1</guid>
          <pubDate>Tue, 30 Jun 2026 09:00:00 GMT</pubDate>
          <description>Feed excerpt.</description>
        </item>
      </channel>
    </rss>`;
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}
