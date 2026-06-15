import { describe, expect, it } from "vitest";
import {
  PgRunJobRepository,
  type RunJobRecord,
} from "../src/modules/runs/jobRepository";
import { RunJobWorker, type RunJobQueuePort } from "../src/modules/runs/jobWorker";
import type { QueryResult, Queryable } from "../src/modules/runs/repository";

interface QueryCall {
  sql: string;
  params: readonly unknown[];
}

class FakeDb implements Queryable {
  calls: QueryCall[] = [];
  rowCount = 1;

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    this.calls.push({ sql, params });
    if (sql.includes("AS reclaimed_count")) {
      return { rowCount: this.rowCount, rows: [{ reclaimed_count: "2" }] as Row[] };
    }
    if (sql.includes("RETURNING") && sql.includes("payload_json")) {
      return {
        rowCount: this.rowCount,
        rows: [
          makeJob({
            id: "job-1",
            space_id: "space-1",
            user_id: "user-1",
            claimed_by: params[0] === "worker-1" ? "worker-1" : null,
            attempts: 1,
          }),
        ] as Row[],
      };
    }
    if (sql.includes("RETURNING status")) {
      return { rowCount: this.rowCount, rows: [{ status: "pending" }] as Row[] };
    }
    if (sql.includes("RETURNING id, job_id, event_type, message")) {
      return {
        rowCount: this.rowCount,
        rows: [
          {
            id: "event-1",
            job_id: params[1],
            event_type: params[2],
            message: params[3],
          },
        ] as Row[],
      };
    }
    return { rowCount: this.rowCount, rows: [] };
  }
}

class FakeQueue implements RunJobQueuePort {
  events: string[] = [];
  job: RunJobRecord | null = makeJob({ attempts: 1 });

  async claimNextAgentRun(workerId: string): Promise<RunJobRecord | null> {
    this.events.push(`claim:${workerId}`);
    return this.job;
  }

  async startJob(jobId: string, workerId: string | null): Promise<boolean> {
    this.events.push(`start:${jobId}:${workerId}`);
    return true;
  }

  async completeJob(
    jobId: string,
    resultJson: unknown,
    workerId: string | null,
  ): Promise<boolean> {
    const result = resultJson as { status?: string } | null;
    this.events.push(`complete:${jobId}:${result?.status ?? "null"}:${workerId}`);
    return true;
  }

  async failJob(
    jobId: string,
    error: string,
    workerId: string | null,
  ): Promise<string | null> {
    this.events.push(`fail:${jobId}:${error}:${workerId}`);
    return "pending";
  }

  async cancelJob(jobId: string, workerId: string | null): Promise<boolean> {
    this.events.push(`cancel:${jobId}:${workerId}`);
    return true;
  }

  async touchHeartbeat(jobId: string, workerId: string | null): Promise<boolean> {
    this.events.push(`heartbeat:${jobId}:${workerId}`);
    return true;
  }

  async appendJobEvent(input: {
    job_id: string;
    event_type: string;
    message: string;
    data?: unknown;
  }): Promise<unknown> {
    this.events.push(`event:${input.job_id}:${input.event_type}:${input.message}`);
    return {};
  }

  async reclaimStuckJobs(): Promise<{ reclaimed_count: number }> {
    this.events.push("reclaim");
    return { reclaimed_count: 3 };
  }
}

describe("PgRunJobRepository", () => {
  it("claims only agent_run jobs with DB row locking and attempt consumption", async () => {
    const db = new FakeDb();
    const repo = new PgRunJobRepository(db);

    const job = await repo.claimNextAgentRun(
      "worker-1",
      new Date("2026-06-12T10:00:00.000Z"),
    );

    expect(job?.claimed_by).toBe("worker-1");
    expect(db.calls[0].sql).toContain("FOR UPDATE SKIP LOCKED");
    expect(db.calls[0].sql).toContain("job_type = 'agent_run'");
    expect(db.calls[0].sql).toContain("attempts = attempts + 1");
    // Tripwire for the real-PG "column reference id is ambiguous" defect: the
    // candidate CTE column must stay aliased so the UPDATE...FROM join is
    // unambiguous. (FakeDb does not execute SQL, so this string check is the
    // only guard at the unit layer.)
    expect(db.calls[0].sql).toContain("candidate_job_id");
    expect(db.calls[0].sql).not.toMatch(/jobs\.id = candidate\.id\b/);
    expect(db.calls[0].params).toEqual([
      "worker-1",
      "2026-06-12T10:00:00.000Z",
    ]);
  });

  it("starts, completes, and fails only claimed or running jobs owned by the worker", async () => {
    const db = new FakeDb();
    const repo = new PgRunJobRepository(db);

    await repo.startJob("job-1", "worker-1", new Date("2026-06-12T10:01:00.000Z"));
    await repo.completeJob(
      "job-1",
      { run_id: "run-1", status: "succeeded", stdout: "raw" },
      "worker-1",
      new Date("2026-06-12T10:02:00.000Z"),
    );
    const retryStatus = await repo.failJob(
      "job-1",
      "token=secret",
      "worker-1",
      new Date("2026-06-12T10:03:00.000Z"),
    );

    expect(db.calls[0].sql).toContain("status = 'claimed'");
    expect(db.calls[0].sql).toContain("claimed_by = $3");
    expect(db.calls[1].sql).toContain("status IN ('claimed', 'running')");
    expect(JSON.parse(String(db.calls[1].params[1]))).toEqual({
      run_id: "run-1",
      status: "succeeded",
      stdout: "[REDACTED_EVIDENCE_FIELD]",
    });
    expect(db.calls[2].sql).toContain("CASE WHEN attempts < max_attempts THEN 'pending'");
    expect(db.calls[2].params[1]).toBe("[REDACTED_SECRET]");
    expect(retryStatus).toBe("pending");
  });

  it("cancels linked agent runs without reopening terminal runs", async () => {
    const db = new FakeDb();
    const repo = new PgRunJobRepository(db);

    await repo.cancelJob("job-1", null, new Date("2026-06-12T10:04:00.000Z"));

    expect(db.calls[0].sql).toContain("WITH cancelled_job AS");
    expect(db.calls[0].sql).toContain("UPDATE runs");
    expect(db.calls[0].sql).toContain("runs.status <> ALL($4::text[])");
    expect(db.calls[0].params[2]).toBeNull();
  });

  it("reclaims stale work and fails exhausted linked runs", async () => {
    const db = new FakeDb();
    const repo = new PgRunJobRepository(db);

    const result = await repo.reclaimStuckJobs(
      600,
      new Date("2026-06-12T10:10:00.000Z"),
    );

    expect(db.calls[0].sql).toContain("DELETE FROM run_execution_locks");
    expect(db.calls[0].sql).toContain("job_type = 'agent_run'");
    expect(db.calls[1].sql).toContain("WITH retryable AS");
    expect(db.calls[1].sql).toContain("failed_runs AS");
    expect(db.calls[1].sql).toContain("job stuck and retry attempts exhausted");
    expect(db.calls[0].params[0]).toBe("2026-06-12T10:00:00.000Z");
    expect(result.reclaimed_count).toBe(2);
  });
});

describe("RunJobWorker", () => {
  it("claims, starts, dispatches, completes, and records status events", async () => {
    const queue = new FakeQueue();
    const worker = new RunJobWorker(queue, "worker-1", async (job) => ({
      run_id: String(job.payload.run_id),
      status: "succeeded",
    }));

    await expect(worker.processOne()).resolves.toEqual({
      status: "completed",
      job_id: "job-1",
    });

    expect(queue.events).toEqual([
      "claim:worker-1",
      "start:job-1:worker-1",
      "event:job-1:status_change:Job started by TS worker",
      "complete:job-1:succeeded:worker-1",
      "event:job-1:status_change:Job completed successfully",
    ]);
  });

  it("fails invalid or throwing jobs without completing them", async () => {
    const queue = new FakeQueue();
    queue.job = makeJob({ payload_json: {}, attempts: 1 });
    const worker = new RunJobWorker(queue, "worker-1", async () => {
      throw new Error("handler should not run");
    });

    await expect(worker.processOne()).resolves.toEqual({
      status: "failed",
      job_id: "job-1",
      error: "agent_run payload requires run_id, task_id, or agent_id",
    });

    expect(queue.events).toEqual([
      "claim:worker-1",
      "fail:job-1:agent_run payload requires run_id, task_id, or agent_id:worker-1",
      "event:job-1:error:Job failed: agent_run payload requires run_id, task_id, or agent_id",
    ]);
  });

  it("exposes cancel, heartbeat, and reclaim controls", async () => {
    const queue = new FakeQueue();
    const worker = new RunJobWorker(queue, "worker-1", async () => null);

    await worker.cancelJob("job-1");
    await worker.heartbeat("job-1");
    await expect(worker.reclaimStuckJobs(600)).resolves.toBe(3);

    expect(queue.events).toEqual([
      "cancel:job-1:worker-1",
      "heartbeat:job-1:worker-1",
      "reclaim",
    ]);
  });
});

function makeJob(overrides: Partial<RunJobRecord> = {}): RunJobRecord {
  return {
    id: "job-1",
    space_id: "space-1",
    user_id: "user-1",
    workspace_id: null,
    agent_id: "agent-1",
    job_type: "agent_run",
    status: "claimed",
    priority: 0,
    payload_json: { run_id: "run-1" },
    result_json: null,
    error: null,
    attempts: 0,
    max_attempts: 3,
    scheduled_at: "2026-06-12T09:00:00.000Z",
    claimed_by: null,
    claimed_at: null,
    started_at: null,
    completed_at: null,
    heartbeat_at: null,
    created_at: "2026-06-12T09:00:00.000Z",
    updated_at: "2026-06-12T09:00:00.000Z",
    ...overrides,
  };
}
