import { readFileSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Pool } from "pg";
import {
  PostgreSqlContainer,
  type StartedPostgreSqlContainer,
} from "@testcontainers/postgresql";
import { PgRunRepository } from "../src/modules/runs/repository";
import { PgRunJobRepository } from "../src/modules/runs/jobRepository";

// Real-PostgreSQL integration tests for the TS runs repositories. The unit
// suites use a FakeDb that does not execute SQL, so they cannot catch parameter
// type inference, CHECK/UNIQUE constraints, varchar length, or CTE column
// ambiguity — exactly the class of defects that only surfaced on the real
// stack. These run the actual SQL against a throwaway Postgres (testcontainers)
// loaded with the real table schema (test/fixtures/runsSchema.sql).
//
// The whole suite skips gracefully when Docker is unavailable so `npm test`
// still runs everywhere; where Docker is present (dev, CI) it always runs.

const SCHEMA = readFileSync(
  join(process.cwd(), "test/fixtures/runsSchema.sql"),
  "utf8",
);

let container: StartedPostgreSqlContainer | undefined;
let pool: Pool | undefined;
let available = false;

beforeAll(async () => {
  try {
    container = await new PostgreSqlContainer("postgres:18").start();
    pool = new Pool({ connectionString: container.getConnectionUri() });
    await pool.query(SCHEMA);
    available = true;
  } catch (err) {
    console.warn(
      `[runs-integration] skipped — Docker/Postgres unavailable: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}, 120_000);

afterAll(async () => {
  await pool?.end();
  await container?.stop();
});

beforeEach(async () => {
  if (!available || !pool) return;
  await pool.query(
    "TRUNCATE actors, runs, run_steps, run_events, run_execution_locks, jobs, job_events CASCADE",
  );
});

async function seedRun(
  overrides: Partial<{
    space_id: string;
    status: string;
    adapter_type: string;
    model_provider_id: string | null;
    instructed_by_user_id: string | null;
    required_sandbox_level: string;
  }> = {},
): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO runs (
       id, space_id, agent_id, agent_version_id, run_type, trigger_origin,
       status, mode, usage_accuracy, adapter_type, model_provider_id,
       instructed_by_user_id, required_sandbox_level, created_at, updated_at
     ) VALUES ($1,$2,'agent-1','version-1','agent','manual',$3,'live',
       'estimated',$4,$5,$6,$7,$8,$8)`,
    [
      id,
      overrides.space_id ?? "space-1",
      overrides.status ?? "queued",
      overrides.adapter_type ?? "model_api",
      overrides.model_provider_id ?? "provider-1",
      overrides.instructed_by_user_id ?? null,
      overrides.required_sandbox_level ?? "none",
      now,
    ],
  );
  return id;
}

async function seedJob(
  overrides: Partial<{
    job_type: string;
    status: string;
    attempts: number;
    claimed_by: string | null;
    heartbeat_at: string | null;
    payload: Record<string, unknown>;
  }> = {},
): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();
  await pool!.query(
    `INSERT INTO jobs (
       id, space_id, job_type, status, priority, payload_json, attempts,
       max_attempts, scheduled_at, created_at, updated_at, claimed_by, heartbeat_at
     ) VALUES ($1,'space-1',$2,$3,0,$4::jsonb,$5,3,$6,$6,$6,$7,$8)`,
    [
      id,
      overrides.job_type ?? "agent_run",
      overrides.status ?? "pending",
      JSON.stringify(overrides.payload ?? { run_id: "run-1" }),
      overrides.attempts ?? 0,
      now,
      overrides.claimed_by ?? null,
      overrides.heartbeat_at ?? null,
    ],
  );
  return id;
}

describe("runs repositories against real PostgreSQL", () => {
  it("appends run events with a DB-computed monotonic event_index", async (ctx) => {
    if (!available) return ctx.skip();
    const repo = new PgRunRepository(pool!);
    const runId = await seedRun();

    const e0 = await repo.appendRunEvent({
      run_id: runId,
      space_id: "space-1",
      event_type: "policy_checked",
      status: "succeeded",
    });
    const e1 = await repo.appendRunEvent({
      run_id: runId,
      space_id: "space-1",
      event_type: "adapter_invoked",
      status: "running",
    });

    // The scalar subquery + ::varchar casts must execute; the old
    // INSERT...SELECT shape failed real "inconsistent types deduced" inference.
    expect(e0.event_index).toBe(0);
    expect(e1.event_index).toBe(1);
  });

  it("rejects an event_type outside ck_run_events_event_type", async (ctx) => {
    if (!available) return ctx.skip();
    const repo = new PgRunRepository(pool!);
    const runId = await seedRun();

    // "run_orchestration_failed" is NOT in the CHECK list — this is exactly why
    // orchestration had to switch to the constraint-valid "adapter_completed".
    await expect(
      repo.appendRunEvent({
        run_id: runId,
        space_id: "space-1",
        event_type: "run_orchestration_failed",
        status: "failed",
      }),
    ).rejects.toThrow();
  });

  it("creates a coarse run step and enforces actor_id length + step_type CHECK", async (ctx) => {
    if (!available) return ctx.skip();
    const repo = new PgRunRepository(pool!);
    const runId = await seedRun();
    const actorId = await repo.resolveRunActorId(
      { space_id: "space-1", instructed_by_user_id: null },
      "job",
    );

    const step = await repo.createRunStep({
      run_id: runId,
      space_id: "space-1",
      actor_id: actorId,
      step_type: "adapter_started",
      status: "running",
    });
    expect(step.step_index).toBe(0);

    // The original defect wrote a worker-id string (>36 chars, not an Actor) to
    // actor_id; varchar(36) rejects it.
    await expect(
      repo.createRunStep({
        run_id: runId,
        space_id: "space-1",
        actor_id: `http:${randomUUID()}:${randomUUID()}`,
        step_type: "adapter_started",
        status: "running",
      }),
    ).rejects.toThrow();
  });

  it("resolves/creates real actors and reuses them per type", async (ctx) => {
    if (!available) return ctx.skip();
    const repo = new PgRunRepository(pool!);

    const user1 = await repo.resolveRunActorId(
      { space_id: "space-1", instructed_by_user_id: "user-1" },
      "http",
    );
    const user1Again = await repo.resolveRunActorId(
      { space_id: "space-1", instructed_by_user_id: "user-1" },
      "http",
    );
    expect(user1Again).toBe(user1); // reused, not duplicated

    const jobActor = await repo.resolveRunActorId(
      { space_id: "space-1", instructed_by_user_id: null },
      "job",
    );
    const systemActor = await repo.resolveRunActorId(
      { space_id: "space-1", instructed_by_user_id: null },
      "http",
    );
    expect(new Set([user1, jobActor, systemActor]).size).toBe(3);

    const rows = await pool!.query<{ actor_type: string; service_name: string | null }>(
      "SELECT actor_type, service_name FROM actors WHERE id = ANY($1)",
      [[jobActor, systemActor]],
    );
    const byType = Object.fromEntries(rows.rows.map((r) => [r.actor_type, r.service_name]));
    expect(byType.job).toBe("agent_run");
    expect(byType.system).toBe("run_execution");
  });

  it("marks running then terminal, guarding against overwriting a cancel", async (ctx) => {
    if (!available) return ctx.skip();
    const repo = new PgRunRepository(pool!);
    const runId = await seedRun();

    const running = await repo.markRunRunning({
      run_id: runId,
      space_id: "space-1",
      started_at: new Date().toISOString(),
    });
    expect(running?.status).toBe("running");

    const cancelled = await repo.markRunTerminal({
      run_id: runId,
      space_id: "space-1",
      status: "cancelled",
      completed_at: new Date().toISOString(),
      error_json: { error_code: "run_cancelled" },
    });
    expect(cancelled?.status).toBe("cancelled");

    // A late adapter result must NOT overwrite the terminal cancel.
    const late = await repo.markRunTerminal({
      run_id: runId,
      space_id: "space-1",
      status: "succeeded",
      output_text: "late output",
      completed_at: new Date().toISOString(),
    });
    expect(late).toBeNull();

    const after = await repo.getRun("space-1", runId);
    expect(after?.status).toBe("cancelled");
  });

  it("folds output_text into output_json on the terminal write", async (ctx) => {
    if (!available) return ctx.skip();
    const repo = new PgRunRepository(pool!);
    const runId = await seedRun();
    await repo.markRunRunning({
      run_id: runId,
      space_id: "space-1",
      started_at: new Date().toISOString(),
    });

    await repo.markRunTerminal({
      run_id: runId,
      space_id: "space-1",
      status: "succeeded",
      output_text: "final answer",
      completed_at: new Date().toISOString(),
    });

    const row = await pool!.query<{ output_json: { output_text?: string } }>(
      "SELECT output_json FROM runs WHERE id = $1",
      [runId],
    );
    expect(row.rows[0].output_json.output_text).toBe("final answer");
  });

  it("acquires the execution lock once (ON CONFLICT DO NOTHING)", async (ctx) => {
    if (!available) return ctx.skip();
    const repo = new PgRunRepository(pool!);
    const runId = await seedRun();

    const first = await repo.tryAcquireExecutionLock({ run_id: runId, worker_id: "w1" });
    const second = await repo.tryAcquireExecutionLock({ run_id: runId, worker_id: "w2" });
    expect(first).toBe(true);
    expect(second).toBe(false); // duplicate execution prevented

    await repo.releaseExecutionLock(runId);
    const third = await repo.tryAcquireExecutionLock({ run_id: runId, worker_id: "w3" });
    expect(third).toBe(true);
  });

  it("claims an agent_run job through the real CTE (no ambiguous id)", async (ctx) => {
    if (!available) return ctx.skip();
    const jobs = new PgRunJobRepository(pool!);
    await seedJob({ job_type: "memory_consolidation", status: "pending" }); // must be ignored
    const target = await seedJob({ job_type: "agent_run", status: "pending" });

    const claimed = await jobs.claimNextAgentRun("worker-1");
    // The old "column reference \"id\" is ambiguous" defect threw here.
    expect(claimed?.id).toBe(target);
    expect(claimed?.status).toBe("claimed");
    expect(claimed?.claimed_by).toBe("worker-1");

    // Only agent_run is claimable; a second claim finds nothing.
    const none = await jobs.claimNextAgentRun("worker-2");
    expect(none).toBeNull();
  });

  it("reclaims stuck jobs through the multi-CTE statement", async (ctx) => {
    if (!available) return ctx.skip();
    const jobs = new PgRunJobRepository(pool!);
    const old = new Date(Date.now() - 3600_000).toISOString();
    await seedJob({
      job_type: "agent_run",
      status: "running",
      claimed_by: "dead-worker",
      heartbeat_at: old,
    });

    const result = await jobs.reclaimStuckJobs(600);
    expect(result.reclaimed_count).toBeGreaterThanOrEqual(1);
  });
});
