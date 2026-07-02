import { afterEach, describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import { IntakeExtractionWorker } from "../src/modules/intake/extractionWorker";
import type { Queryable } from "../src/modules/routeUtils/common";

class FakeDb implements Queryable {
  readonly calls: Array<{ sql: string; params: readonly unknown[] }> = [];
  private status = "running";

  constructor(
    private readonly jobType: "extract_text" | "snapshot",
    private readonly policyRetention: "metadata_only" | "full_text" | "full_snapshot" = "metadata_only",
  ) {}

  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
    this.calls.push({ sql, params });
    if (sql.includes("SET status = 'running'")) {
      return { rows: [jobRow(this.jobType)], rowCount: 1 } as { rows: Row[]; rowCount: number };
    }
    if (sql.includes("SELECT id, space_id, connection_id, source_uri")) {
      return {
        rows: [{
          id: "item-1",
          space_id: "space-1",
          connection_id: "conn-1",
          source_uri: "https://example.test/private",
          title: "Private page",
          content_state: "content_queued",
        }],
        rowCount: 1,
      } as { rows: Row[]; rowCount: number };
    }
    if (sql.includes("FROM source_connections")) {
      return {
        rows: [{
          id: "conn-1",
          space_id: "space-1",
          connector_id: "connector-1",
          owner_user_id: "user-1",
          capture_policy: "metadata_only",
          trust_level: "normal",
          consent_json: {},
          policy_json: { retention_policy: this.policyRetention },
        }],
        rowCount: 1,
      } as { rows: Row[]; rowCount: number };
    }
    if (sql.includes("FROM scheduler_tasks")) {
      return { rows: [], rowCount: 0 };
    }
    if (sql.includes("INSERT INTO artifacts")) {
      return { rows: [], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO source_snapshots")) {
      return { rows: [], rowCount: 1 };
    }
    if (sql.includes("UPDATE intake_items")) {
      return { rows: [], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO extracted_evidence")) {
      return { rows: [], rowCount: 1 };
    }
    if (sql.includes("UPDATE extraction_jobs SET source_snapshot_id")) {
      return { rows: [], rowCount: 1 };
    }
    if (sql.includes("SET status = $3")) {
      this.status = String(params[2]);
      return { rows: [], rowCount: 1 };
    }
    if (sql.includes("SET content_state = 'extraction_failed'")) {
      return { rows: [], rowCount: 1 };
    }
    if (sql.includes("SELECT") && sql.includes("FROM extraction_jobs")) {
      return { rows: [{ ...jobRow(this.jobType), status: this.status }], rowCount: 1 } as { rows: Row[]; rowCount: number };
    }
    throw new Error(`unexpected SQL: ${sql}`);
  }
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("IntakeExtractionWorker source retention policy", () => {
  it("blocks extract_text jobs before fetching when source policy disallows full text", async () => {
    const db = new FakeDb("extract_text");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const result = await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("failed");
    expect(fetchSpy).not.toHaveBeenCalled();
    const finish = db.calls.find((call) => call.sql.includes("SET status = $3"));
    expect(finish?.params[2]).toBe("failed");
    expect(finish?.params[4]).toBe("403");
    expect(finish?.params[5]).toBe("Source retention policy does not allow full_text");
  });

  it("blocks snapshot jobs before fetching when source policy disallows snapshots", async () => {
    const db = new FakeDb("snapshot");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const result = await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("failed");
    expect(fetchSpy).not.toHaveBeenCalled();
    const finish = db.calls.find((call) => call.sql.includes("SET status = $3"));
    expect(finish?.params[4]).toBe("403");
    expect(finish?.params[5]).toBe("Source retention policy does not allow full_snapshot");
  });

  it("writes extract_text artifacts as structured reader documents", async () => {
    const db = new FakeDb("extract_text", "full_text");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(
      "<html><body><article><h1>Readable article</h1><p>Article text.</p><img src='/image.png'></article></body></html>",
      { status: 200 },
    ));

    const result = await new IntakeExtractionWorker(db, config()).runPendingJob("job-1", "space-1");

    expect(result.status).toBe("succeeded");
    const artifactInsert = db.calls.find((call) => call.sql.includes("INSERT INTO artifacts"));
    expect(artifactInsert?.sql).toContain("'intake_reader_document'");
    expect(artifactInsert?.sql).toContain("'application/json'");
    expect(artifactInsert?.sql).toContain("'reader_document_json'");
    expect(artifactInsert?.sql).toContain("export_formats_json");
    expect(artifactInsert?.params).toContain(JSON.stringify(["json"]));
    expect(String(artifactInsert?.params[3])).toContain("\"image_policy\":\"remote_reference\"");
    expect(String(artifactInsert?.params[3])).toContain("\"src\":\"https://example.test/image.png\"");
  });
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    ARTIFACT_STORAGE_ROOT: "/tmp/agent-space-test-artifacts",
  });
}

function jobRow(jobType: "extract_text" | "snapshot") {
  return {
    id: "job-1",
    space_id: "space-1",
    connection_id: "conn-1",
    intake_item_id: "item-1",
    source_object_type: null,
    source_object_id: null,
    job_type: jobType,
    status: "running",
    metadata_json: {},
  };
}
