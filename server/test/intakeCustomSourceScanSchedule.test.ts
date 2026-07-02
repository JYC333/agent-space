import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { mkdtemp, rm, writeFile, mkdir } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { loadConfig, type ServerConfig } from "../src/config";
import { enqueueDueSourceConnectionScans } from "../src/modules/intake/scanSchedule";
import {
  enqueueDueCustomSourceHandlerRuns,
  reclaimStuckCustomSourceHandlerRuns,
} from "../src/modules/intake/customSourceScanSchedule";
import { runPendingCustomSourceHandlerRuns } from "../src/modules/intake/customSourceScanWorker";
import { generateCustomSourceHandlerSource } from "../src/modules/intake/customSourceHandlerTemplate";
import { sha256 } from "../src/modules/intake/intakeRepositoryMappers";
import { PgIntakeRepository } from "../src/modules/intake/repository";

// Real-Postgres + real-child-process + real local HTTP server (not a live
// external provider — a loopback server this test controls) integration
// tests for the "first scan job integration" scheduler/worker pair.

const SCHEMA = readFileSync(join(process.cwd(), "test/fixtures/intakeCustomSourceCreateFlowSchema.sql"), "utf8");

const SPACE_A = "space-a";
const CUSTOM_SOURCE_INSTANCE_RUNNER_SETTINGS_KEY = "intake.custom_source.runner";

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let config: ServerConfig | undefined;
let artifactStorageRoot: string | undefined;
let httpServer: Server | undefined;
let serverPort = 0;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("pgvector/pgvector:pg18").start();
    pool = new Pool({ connectionString: container.getConnectionUri() });
    await pool.query(SCHEMA);
    available = true;
  } catch (err) {
    console.warn(
      `[intake-custom-source-scan-schedule] skipped — Docker/Postgres unavailable: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return;
  }

  httpServer = createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/html" });
    res.end(`<html><body>
      <div class="article"><a href="/a1">First Title</a><p>First excerpt text.</p></div>
    </body></html>`);
  });
  await new Promise<void>((resolveListen) => httpServer!.listen(0, "127.0.0.1", resolveListen));
  const address = httpServer.address();
  serverPort = typeof address === "object" && address ? address.port : 0;
}, 120_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
  await new Promise<void>((resolveClose) => (httpServer ? httpServer.close(() => resolveClose()) : resolveClose()));
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    `TRUNCATE source_handler_runs, source_handler_versions, source_recipe_versions, source_connections, source_connectors,
              scheduler_tasks, settings, artifacts, extraction_jobs, intake_items,
              source_snapshots, extracted_evidence`,
  );
  await pool.query(
    `INSERT INTO source_connectors (
       id, connector_key, display_name, connector_type, ingestion_mode, status,
       capabilities_json, created_at, updated_at
     ) VALUES
       ('connector-custom-source', 'custom_source', 'Custom Source', 'external_url', 'pull', 'active', '{}'::jsonb, now(), now()),
       ('connector-rss', 'rss', 'RSS Feed', 'external_feed', 'pull', 'active', '{}'::jsonb, now(), now())`,
  );
  artifactStorageRoot = await mkdtemp(join(tmpdir(), "custom-source-scan-schedule-artifacts-"));
  config = {
    ...loadConfig({}),
    artifactStorageRoot,
    customSourceAllowedLanguages: ["typescript_node"],
  };
});

afterEach(async () => {
  if (artifactStorageRoot) await rm(artifactStorageRoot, { recursive: true, force: true });
});

const POLICY_ENVELOPE = {
  allowed_network_origins: [`http://127.0.0.1:0`], // overridden per-test with the real port
  capture_policy: "auto_extract_relevant",
  retention_policy: "full_text",
  credential_ref: null,
  language: "typescript_node" as const,
  browser_automation_enabled: false,
  shell_enabled: false,
  dependency_installation_enabled: false,
  log_redaction_enabled: true,
  limits: {
    timeout_ms: 5000,
    max_download_bytes: 1_000_000,
    max_output_bytes: 1_000_000,
    max_files: 5,
    max_items: 20,
    max_evidence_items: 20,
    log_max_bytes: 65536,
  },
};

async function insertConnection(input: {
  id: string;
  handlerKind: "built_in" | "generated_custom";
  status?: string;
  fetchFrequency?: string;
  activeHandlerVersionId?: string | null;
  repairStatus?: string;
  nextCheckAt?: string | null;
  endpointUrl?: string;
}): Promise<void> {
  await pool!.query(
    `INSERT INTO source_connections (
       id, space_id, connector_id, owner_user_id, name, endpoint_url, status, fetch_frequency,
       capture_policy, trust_level, consent_json, policy_json, config_json,
       handler_kind, active_handler_version_id, repair_status,
       created_at, updated_at
     ) VALUES ($1, $2, $3, 'user-1', 'Test source', $4, $5, $6,
       'auto_extract_relevant', 'normal', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
       $7, $8, $9, now(), now())`,
    [
      input.id,
      SPACE_A,
      input.handlerKind === "built_in" ? "connector-rss" : "connector-custom-source",
      input.endpointUrl ?? `http://127.0.0.1:${serverPort}/feed`,
      input.status ?? "active",
      input.fetchFrequency ?? "hourly",
      input.handlerKind,
      input.activeHandlerVersionId ?? null,
      input.repairStatus ?? "ok",
    ],
  );
  const status = input.status ?? "active";
  const fetchFrequency = input.fetchFrequency ?? "hourly";
  const nextRunAt =
    status === "active" && fetchFrequency !== "manual"
      ? input.nextCheckAt ?? new Date(0).toISOString()
      : null;
  await pool!.query(
    `INSERT INTO scheduler_tasks (
       id, task_type, task_key, scope_type, scope_id, space_id, user_id, status,
       next_run_at, last_run_at, state_json, created_at, updated_at
     ) VALUES (
       $1, 'source_connection_scan', $2, 'space', $3, $3, 'user-1', $4,
       $5, NULL, '{}'::jsonb, now(), now()
     )`,
    [
      randomUUID(),
      input.id,
      SPACE_A,
      status === "archived" ? "archived" : status === "active" ? "active" : "paused",
      nextRunAt,
    ],
  );
}

async function insertActiveHandlerVersion(
  connectionId: string,
  options: { source?: string; policyEnvelope?: typeof POLICY_ENVELOPE } = {},
): Promise<string> {
  const versionId = randomUUID();
  const source = options.source ?? generateCustomSourceHandlerSource({ listSelector: "article" });
  const artifactId = randomUUID();
  const relativePath = join(SPACE_A, "custom-source", `${artifactId}.handler.cjs`);
  const absolutePath = resolve(config!.artifactStorageRoot, relativePath);
  await mkdir(dirname(absolutePath), { recursive: true });
  await writeFile(absolutePath, source, "utf8");
  await pool!.query(
    `INSERT INTO artifacts (
       id, space_id, artifact_type, title, storage_path, mime_type,
       exportable, export_formats_json, canonical_format, preview, created_at, updated_at
     ) VALUES ($1, $2, 'intake_custom_source_handler_code', 'test handler', $3, 'application/javascript',
       true, '["javascript"]'::jsonb, 'javascript', false, now(), now())`,
    [artifactId, SPACE_A, relativePath],
  );
  const envelope = options.policyEnvelope ?? { ...POLICY_ENVELOPE, allowed_network_origins: [`http://127.0.0.1:${serverPort}`] };
  await pool!.query(
    `INSERT INTO source_handler_versions (
       id, space_id, source_connection_id, version_number, language, entrypoint,
       handler_artifact_id, manifest_json, policy_envelope_json, checksum, status,
       created_at, activated_at
     ) VALUES ($1, $2, $3, 1, 'typescript_node', 'handler.cjs', $4, '{}'::jsonb, $5::jsonb, $6, 'active', now(), now())`,
    [versionId, SPACE_A, connectionId, artifactId, JSON.stringify(envelope), sha256(source)],
  );
  await pool!.query(`UPDATE source_connections SET active_handler_version_id = $1 WHERE id = $2`, [
    versionId,
    connectionId,
  ]);
  return versionId;
}

describe("enqueueDueSourceConnectionScans (built_in only)", () => {
  it("does not enqueue a generated_custom connection", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom" });
    const count = await enqueueDueSourceConnectionScans(pool!, 25);
    expect(count).toBe(0);
    const jobs = await pool!.query(`SELECT * FROM extraction_jobs WHERE connection_id = $1`, [connId]);
    expect(jobs.rows).toHaveLength(0);
  });

  it("still enqueues a built_in connection", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "built_in" });
    const count = await enqueueDueSourceConnectionScans(pool!, 25);
    expect(count).toBe(1);
  });
});

describe("enqueueDueCustomSourceHandlerRuns", () => {
  it("excludes built_in connections", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "built_in" });
    const count = await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    expect(count).toBe(0);
  });

  it("excludes a connection with no active_handler_version_id", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom" });
    const count = await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    expect(count).toBe(0);
  });

  it("excludes a repair_status='disabled' connection", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom", repairStatus: "disabled" });
    await insertActiveHandlerVersion(connId);
    const count = await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    expect(count).toBe(0);
  });

  it("enqueues an eligible generated_custom connection with a paired extraction_job + source_handler_run", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom" });
    const versionId = await insertActiveHandlerVersion(connId);
    const count = await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    expect(count).toBe(1);

    const runs = await pool!.query<{ status: string; handler_version_id: string; extraction_job_id: string }>(
      `SELECT status, handler_version_id, extraction_job_id FROM source_handler_runs WHERE source_connection_id = $1`,
      [connId],
    );
    expect(runs.rows).toHaveLength(1);
    expect(runs.rows[0]?.status).toBe("queued");
    expect(runs.rows[0]?.handler_version_id).toBe(versionId);
    const job = await pool!.query(`SELECT job_type, status FROM extraction_jobs WHERE id = $1`, [
      runs.rows[0]?.extraction_job_id,
    ]);
    expect(job.rows[0]?.job_type).toBe("connection_scan");
  });

  it("does not double-enqueue while a run is already queued", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom" });
    await insertActiveHandlerVersion(connId);
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    const second = await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    expect(second).toBe(0);
  });

  it("reclaims a stale running handler run so the connection can be scheduled again", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom" });
    await insertActiveHandlerVersion(connId);
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);

    const startedAt = new Date(Date.now() - 15 * 60 * 1000).toISOString();
    await pool!.query(
      `UPDATE source_handler_runs SET status = 'running', started_at = $2 WHERE source_connection_id = $1`,
      [connId, startedAt],
    );
    await pool!.query(`UPDATE extraction_jobs SET status = 'running' WHERE connection_id = $1`, [connId]);

    expect(await enqueueDueCustomSourceHandlerRuns(pool!, 25)).toBe(0);
    expect(await reclaimStuckCustomSourceHandlerRuns(pool!, 600)).toBe(1);

    const reclaimed = await pool!.query<{ status: string; failure_class: string | null }>(
      `SELECT status, failure_class FROM source_handler_runs WHERE source_connection_id = $1`,
      [connId],
    );
    expect(reclaimed.rows[0]).toMatchObject({ status: "failed", failure_class: "stuck_reclaimed" });
    const job = await pool!.query<{ status: string; error_code: string | null }>(
      `SELECT status, error_code FROM extraction_jobs WHERE connection_id = $1`,
      [connId],
    );
    expect(job.rows[0]).toMatchObject({ status: "failed", error_code: "stuck_reclaimed" });

    expect(await enqueueDueCustomSourceHandlerRuns(pool!, 25)).toBe(1);
  });

  it("manual scan for a generated_custom connection creates and runs the paired handler run", async () => {
    if (!available || !config) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom" });
    const versionId = await insertActiveHandlerVersion(connId);
    const repo = new PgIntakeRepository(pool!, config);

    const job = await repo.scanConnection(
      { spaceId: SPACE_A, userId: "user-1" },
      connId,
    );
    expect(job.status).toBe("pending");

    const run = await pool!.query<{ status: string; handler_version_id: string; extraction_job_id: string }>(
      `SELECT status, handler_version_id, extraction_job_id FROM source_handler_runs WHERE extraction_job_id = $1`,
      [job.id],
    );
    expect(run.rows[0]).toMatchObject({
      status: "queued",
      handler_version_id: versionId,
      extraction_job_id: job.id,
    });

    const completed = await repo.runJob({ spaceId: SPACE_A, userId: "user-1" }, job.id);
    expect(completed.status).toBe("succeeded");
    expect(completed.items_created).toBe(1);

    const completedRun = await pool!.query<{ status: string }>(
      `SELECT status FROM source_handler_runs WHERE extraction_job_id = $1`,
      [job.id],
    );
    expect(completedRun.rows[0]?.status).toBe("succeeded");
  });
});

describe("runPendingCustomSourceHandlerRuns", () => {
  it("processes a queued run end-to-end: materializes an intake_item, completes the extraction_job, and advances the scheduler task", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom", nextCheckAt: new Date(0).toISOString() });
    await insertActiveHandlerVersion(connId);
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);

    const processed = await runPendingCustomSourceHandlerRuns(pool!, config!, 10);
    expect(processed).toBe(1);

    const run = await pool!.query<{ status: string }>(
      `SELECT status FROM source_handler_runs WHERE source_connection_id = $1`,
      [connId],
    );
    expect(run.rows[0]?.status).toBe("succeeded");

    const job = await pool!.query<{ status: string; items_created: number }>(
      `SELECT status, items_created FROM extraction_jobs WHERE connection_id = $1`,
      [connId],
    );
    expect(job.rows[0]?.status).toBe("succeeded");
    expect(job.rows[0]?.items_created).toBe(1);

    const items = await pool!.query(`SELECT title, source_uri FROM intake_items WHERE connection_id = $1`, [connId]);
    expect(items.rows).toHaveLength(1);
    expect(items.rows[0]?.title).toBe("First Title");

    const scheduleTask = await pool!.query<{ next_run_at: string | null; last_run_at: string | null }>(
      `SELECT next_run_at, last_run_at
         FROM scheduler_tasks
        WHERE task_type = 'source_connection_scan' AND task_key = $1`,
      [connId],
    );
    expect(scheduleTask.rows[0]?.last_run_at).not.toBeNull();
    expect(new Date(scheduleTask.rows[0]!.next_run_at!).getTime()).toBeGreaterThan(Date.now());
  });

  it("advances the scheduler task even when the fetch fails, avoiding a tight retry loop", async () => {
    if (!available) return;
    const connId = randomUUID();
    // Point at a closed port so the worker's fetch fails.
    await insertConnection({
      id: connId,
      handlerKind: "generated_custom",
      endpointUrl: "http://127.0.0.1:1",
      nextCheckAt: new Date(0).toISOString(),
    });
    await insertActiveHandlerVersion(connId);
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);

    const processed = await runPendingCustomSourceHandlerRuns(pool!, config!, 10);
    expect(processed).toBe(1);

    const run = await pool!.query<{ status: string }>(
      `SELECT status FROM source_handler_runs WHERE source_connection_id = $1`,
      [connId],
    );
    expect(run.rows[0]?.status).toBe("failed");

    const scheduleTask = await pool!.query<{ next_run_at: string | null }>(
      `SELECT next_run_at
         FROM scheduler_tasks
        WHERE task_type = 'source_connection_scan' AND task_key = $1`,
      [connId],
    );
    expect(new Date(scheduleTask.rows[0]!.next_run_at!).getTime()).toBeGreaterThan(Date.now());

    // Not re-enqueued immediately after failure (next_run_at moved into the future).
    const reEnqueued = await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    expect(reEnqueued).toBe(0);
  });

  it("records a blocked handler run and fails the paired extraction_job", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom", nextCheckAt: new Date(0).toISOString() });
    await insertActiveHandlerVersion(connId, {
      policyEnvelope: {
        ...POLICY_ENVELOPE,
        allowed_network_origins: [`http://127.0.0.1:${serverPort}`],
        browser_automation_enabled: true,
      },
    });
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);

    expect(await runPendingCustomSourceHandlerRuns(pool!, config!, 10)).toBe(1);

    const run = await pool!.query<{ id: string; status: string; failure_class: string | null }>(
      `SELECT id, status, failure_class FROM source_handler_runs WHERE source_connection_id = $1`,
      [connId],
    );
    expect(run.rows[0]).toMatchObject({ status: "blocked", failure_class: "browser_automation_requested" });
    const job = await pool!.query<{ status: string; error_code: string | null }>(
      `SELECT status, error_code FROM extraction_jobs WHERE connection_id = $1`,
      [connId],
    );
    expect(job.rows[0]).toMatchObject({ status: "failed", error_code: "browser_automation_requested" });
    const connection = await pool!.query<{ last_handler_run_id: string | null }>(
      `SELECT last_handler_run_id FROM source_connections WHERE id = $1`,
      [connId],
    );
    expect(connection.rows[0]?.last_handler_run_id).toBe(run.rows[0]?.id);
  });

  it("records runner_disabled from the instance setting and fails the paired extraction_job", async () => {
    if (!available) return;
    const connId = randomUUID();
    await pool!.query(
      `INSERT INTO settings (
         id, scope_type, scope_id, settings_key, settings_json, updated_by_user_id, created_at, updated_at
       ) VALUES ($1, 'instance', 'instance', $2, $3::jsonb, 'user-1', now(), now())`,
      [
        randomUUID(),
        CUSTOM_SOURCE_INSTANCE_RUNNER_SETTINGS_KEY,
        JSON.stringify({ runner_enabled: false }),
      ],
    );
    await insertConnection({ id: connId, handlerKind: "generated_custom", nextCheckAt: new Date(0).toISOString() });
    await insertActiveHandlerVersion(connId);
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);

    expect(await runPendingCustomSourceHandlerRuns(pool!, config!, 10)).toBe(1);

    const run = await pool!.query<{ status: string; failure_class: string | null }>(
      `SELECT status, failure_class FROM source_handler_runs WHERE source_connection_id = $1`,
      [connId],
    );
    expect(run.rows[0]).toMatchObject({ status: "blocked", failure_class: "runner_disabled" });
    const job = await pool!.query<{ status: string; error_code: string | null }>(
      `SELECT status, error_code FROM extraction_jobs WHERE connection_id = $1`,
      [connId],
    );
    expect(job.rows[0]).toMatchObject({ status: "failed", error_code: "runner_disabled" });
  });

  it("records a nonzero_exit handler run and fails the paired extraction_job", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom", nextCheckAt: new Date(0).toISOString() });
    await insertActiveHandlerVersion(connId, {
      source: `'use strict';\nconsole.error('handler failed deliberately');\nprocess.exit(7);\n`,
    });
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);

    expect(await runPendingCustomSourceHandlerRuns(pool!, config!, 10)).toBe(1);

    const run = await pool!.query<{ status: string; failure_class: string | null }>(
      `SELECT status, failure_class FROM source_handler_runs WHERE source_connection_id = $1`,
      [connId],
    );
    expect(run.rows[0]).toMatchObject({ status: "failed", failure_class: "nonzero_exit" });
    const job = await pool!.query<{ status: string; error_code: string | null }>(
      `SELECT status, error_code FROM extraction_jobs WHERE connection_id = $1`,
      [connId],
    );
    expect(job.rows[0]).toMatchObject({ status: "failed", error_code: "nonzero_exit" });
  });

  it("records a timeout handler run and fails the paired extraction_job", async () => {
    if (!available || !config) return;
    config = { ...config, customSourceTimeoutMsMax: 100 };
    const connId = randomUUID();
    await insertConnection({ id: connId, handlerKind: "generated_custom", nextCheckAt: new Date(0).toISOString() });
    await insertActiveHandlerVersion(connId, {
      source: `'use strict';\nsetInterval(() => undefined, 1000);\n`,
    });
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);

    expect(await runPendingCustomSourceHandlerRuns(pool!, config, 10)).toBe(1);

    const run = await pool!.query<{ status: string; failure_class: string | null }>(
      `SELECT status, failure_class FROM source_handler_runs WHERE source_connection_id = $1`,
      [connId],
    );
    expect(run.rows[0]).toMatchObject({ status: "failed", failure_class: "timeout" });
    const job = await pool!.query<{ status: string; error_code: string | null }>(
      `SELECT status, error_code FROM extraction_jobs WHERE connection_id = $1`,
      [connId],
    );
    expect(job.rows[0]).toMatchObject({ status: "failed", error_code: "timeout" });
  }, 10_000);
});

describe("Phase 9 automatic repair_status transitions", () => {
  async function resetForNextRun(connId: string): Promise<void> {
    await pool!.query(
      `UPDATE scheduler_tasks SET next_run_at = $2 WHERE task_type = 'source_connection_scan' AND task_key = $1`,
      [connId, new Date(0).toISOString()],
    );
  }

  it("flips repair_status to repair_required after 3 consecutive failing runs, and back to ok on the next success", async () => {
    if (!available) return;
    const connId = randomUUID();
    // A closed port fails deterministically; the working local HTTP server succeeds.
    await insertConnection({
      id: connId,
      handlerKind: "generated_custom",
      endpointUrl: "http://127.0.0.1:1",
      nextCheckAt: new Date(0).toISOString(),
    });
    await insertActiveHandlerVersion(connId);

    for (let attempt = 0; attempt < 3; attempt++) {
      await enqueueDueCustomSourceHandlerRuns(pool!, 25);
      expect(await runPendingCustomSourceHandlerRuns(pool!, config!, 10)).toBe(1);
      if (attempt < 2) await resetForNextRun(connId);
    }

    const afterThreeFailures = await pool!.query<{ repair_status: string }>(
      `SELECT repair_status FROM source_connections WHERE id = $1`,
      [connId],
    );
    expect(afterThreeFailures.rows[0]?.repair_status).toBe("repair_required");

    // Point the connection at the working local HTTP server and run once more.
    await pool!.query(`UPDATE source_connections SET endpoint_url = $2 WHERE id = $1`, [
      connId,
      `http://127.0.0.1:${serverPort}/feed`,
    ]);
    await resetForNextRun(connId);
    await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    expect(await runPendingCustomSourceHandlerRuns(pool!, config!, 10)).toBe(1);

    const afterSuccess = await pool!.query<{ repair_status: string }>(
      `SELECT repair_status FROM source_connections WHERE id = $1`,
      [connId],
    );
    expect(afterSuccess.rows[0]?.repair_status).toBe("ok");
  });

  it("does not flip repair_status while it is repair_pending (an in-flight repair awaiting approval)", async () => {
    if (!available) return;
    const connId = randomUUID();
    await insertConnection({
      id: connId,
      handlerKind: "generated_custom",
      endpointUrl: "http://127.0.0.1:1",
      nextCheckAt: new Date(0).toISOString(),
      repairStatus: "repair_pending",
    });
    await insertActiveHandlerVersion(connId);

    await enqueueDueCustomSourceHandlerRuns(pool!, 25);
    expect(await runPendingCustomSourceHandlerRuns(pool!, config!, 10)).toBe(1);

    const after = await pool!.query<{ repair_status: string }>(
      `SELECT repair_status FROM source_connections WHERE id = $1`,
      [connId],
    );
    expect(after.rows[0]?.repair_status).toBe("repair_pending");
  });
});
