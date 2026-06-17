import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  DuplicateJobHandlerError,
  JobHandlerRegistry,
  UnknownJobTypeError,
} from "../src/modules/jobs/handlerRegistry";
import { JobWorker } from "../src/modules/jobs/worker";
import type { JobRecord } from "../src/modules/jobs/repository";
import { PgJobQueueRepository } from "../src/modules/jobs/repository";
import { jobEventToOut, jobNotFoundForSpace, jobToOut } from "../src/modules/jobs/routes";
import { SchedulerRegistry, startSchedulerRegistry } from "../src/modules/jobs/schedulerRegistry";
import type { QueryResult, Queryable } from "../src/modules/runs/repository";
import { PgRunRepository } from "../src/modules/runs/repository";
import { computeNextRunAt, InvalidScheduleError } from "../src/modules/automations/schedule";
import { AutomationService } from "../src/modules/automations/service";
import { PgAutomationRepository, type AutomationRow } from "../src/modules/automations/repository";
import {
  isValidTimezone,
  PgDailyReportSettingsRepository,
  type DailyReportSettingRow,
} from "../src/modules/dailyReports/repository";
import { buildDailyReportJobPayload } from "../src/modules/dailyReports/scheduler";
import { pruneMemoryAccessLogs } from "../src/modules/jobs/backgroundServices";
import { loadConfig } from "../src/config";
import { enforce } from "../src/modules/policy";
import { getDbPool } from "../src/db/pool";

vi.mock("../src/db/pool", () => ({
  getDbPool: vi.fn(),
}));

vi.mock("../src/modules/policy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/modules/policy")>();
  return {
    ...actual,
    enforce: vi.fn(),
  };
});

vi.mock("../src/modules/policy/actionRegistry", () => ({
  loadActionRegistry: vi.fn(async () => ({})),
}));

describe("JobHandlerRegistry", () => {
  it("registers handlers and fails fast on duplicates", () => {
    const registry = new JobHandlerRegistry();
    registry.register("memory_consolidation", async () => ({ ok: true }));
    expect(() =>
      registry.register("memory_consolidation", async () => ({ ok: false })),
    ).toThrow(DuplicateJobHandlerError);
  });

  it("dispatch raises UnknownJobTypeError for unregistered types", async () => {
    const registry = new JobHandlerRegistry();
    await expect(
      registry.dispatch({
        job_id: "j1",
        space_id: "s1",
        user_id: "u1",
        job_type: "missing",
        attempts: 1,
        max_attempts: 3,
        worker_id: "w1",
        payload: {},
      }),
    ).rejects.toThrow(UnknownJobTypeError);
  });
});

describe("JobWorker", () => {
  it("fails unknown job types without starting the job", async () => {
    const events: string[] = [];
    const queue = {
      async claimNext() {
        return makeJob({ job_type: "orphan_job" });
      },
      async startJob(jobId: string) {
        events.push(`start:${jobId}`);
        return true;
      },
      async completeJob() {
        return true;
      },
      async failJob(jobId: string, error: string) {
        events.push(`fail:${jobId}:${error}`);
        return "failed";
      },
      async cancelJob() {
        return true;
      },
      async touchHeartbeat() {
        return true;
      },
      async appendJobEvent(input: { message: string }) {
        events.push(`event:${input.message}`);
        return { id: "e1", job_id: "job-1", event_type: "error", message: input.message };
      },
      async reclaimStuckJobs() {
        return { reclaimed_count: 0 };
      },
    };
    const registry = new JobHandlerRegistry();
    const worker = new JobWorker(queue as never, registry, "worker-1", []);
    const result = await worker.processOne();
    expect(result.status).toBe("failed");
    expect(events.some((event) => event.startsWith("fail:job-1"))).toBe(true);
    expect(events.some((event) => event.startsWith("start:"))).toBe(false);
  });

  it("does not dispatch a handler when startJob loses ownership", async () => {
    const events: string[] = [];
    const queue = {
      async claimNext() {
        return makeJob({ job_type: "agent_run" });
      },
      async startJob(jobId: string) {
        events.push(`start:${jobId}`);
        return false;
      },
      async completeJob() {
        events.push("complete");
        return true;
      },
      async failJob() {
        events.push("fail");
        return "failed";
      },
      async cancelJob() {
        return true;
      },
      async touchHeartbeat() {
        return true;
      },
      async appendJobEvent(input: { event_type: string; message: string }) {
        events.push(`event:${input.event_type}:${input.message}`);
        return { id: "e1", job_id: "job-1", event_type: input.event_type, message: input.message };
      },
      async reclaimStuckJobs() {
        return { reclaimed_count: 0 };
      },
    };
    const handler = vi.fn(async () => ({ ok: true }));
    const registry = new JobHandlerRegistry();
    registry.register("agent_run", handler);
    const worker = new JobWorker(queue as never, registry, "worker-1", ["agent_run"]);

    await expect(worker.processOne()).resolves.toEqual({
      status: "failed",
      job_id: "job-1",
      error: "Job start skipped because ownership or status changed",
    });
    expect(handler).not.toHaveBeenCalled();
    expect(events).toEqual([
      "start:job-1",
      "event:warning:Job start skipped because ownership or status changed",
    ]);
  });

  it("reports completion loss without overwriting the job state", async () => {
    const events: string[] = [];
    const queue = {
      async claimNext() {
        return makeJob({ job_type: "agent_run" });
      },
      async startJob(jobId: string) {
        events.push(`start:${jobId}`);
        return true;
      },
      async completeJob(jobId: string) {
        events.push(`complete:${jobId}`);
        return false;
      },
      async failJob() {
        events.push("fail");
        return "failed";
      },
      async cancelJob() {
        return true;
      },
      async touchHeartbeat() {
        return true;
      },
      async appendJobEvent(input: { event_type: string; message: string }) {
        events.push(`event:${input.event_type}:${input.message}`);
        return { id: "e1", job_id: "job-1", event_type: input.event_type, message: input.message };
      },
      async reclaimStuckJobs() {
        return { reclaimed_count: 0 };
      },
    };
    const registry = new JobHandlerRegistry();
    registry.register("agent_run", async () => ({ ok: true }));
    const worker = new JobWorker(queue as never, registry, "worker-1", ["agent_run"]);

    await expect(worker.processOne()).resolves.toEqual({
      status: "failed",
      job_id: "job-1",
      error: "Job completion skipped because ownership or status changed",
    });
    expect(events).toEqual([
      "start:job-1",
      "event:status_change:Job started by TS worker",
      "complete:job-1",
      "event:warning:Job completion skipped because ownership or status changed",
    ]);
  });
});

describe("SchedulerRegistry", () => {
  it("validates task names, duplicate names, and run-on-start options", () => {
    const registry = new SchedulerRegistry();
    expect(() =>
      registry.register({ name: "", intervalSeconds: 1, run: async () => undefined }),
    ).toThrow(/name is required/);
    expect(() =>
      registry.register({ name: "bad", intervalSeconds: 0, run: async () => undefined }),
    ).toThrow(/positive interval/);
    expect(() =>
      registry.register({
        name: "bad-await",
        intervalSeconds: 1,
        run: async () => undefined,
        runOnStart: false,
        awaitRunOnStart: true,
      }),
    ).toThrow(/awaitRunOnStart requires runOnStart/);

    registry.register({ name: "once", intervalSeconds: 1, run: async () => undefined });
    expect(() =>
      registry.register({ name: "once", intervalSeconds: 1, run: async () => undefined }),
    ).toThrow(/already registered/);
  });

  it("awaits awaitRunOnStart tasks before start resolves", async () => {
    vi.useFakeTimers();
    let releaseTask: () => void = () => undefined;
    const taskBlocked = new Promise<void>((resolve) => {
      releaseTask = resolve;
    });
    const run = vi.fn(async () => {
      await taskBlocked;
    });
    const registry = new SchedulerRegistry();
    registry.register({
      name: "startup-task",
      intervalSeconds: 1,
      run,
      awaitRunOnStart: true,
    });

    try {
      let started = false;
      const startPromise = registry.start().then(() => {
        started = true;
      });
      await Promise.resolve();
      expect(run).toHaveBeenCalledTimes(1);
      expect(started).toBe(false);
      releaseTask();
      await startPromise;
      expect(started).toBe(true);
      await registry.stop();
    } finally {
      releaseTask();
      vi.useRealTimers();
    }
  });

  it("waits for an awaitRunOnStart task when stopped during startup", async () => {
    vi.useFakeTimers();
    let releaseTask: () => void = () => undefined;
    const taskBlocked = new Promise<void>((resolve) => {
      releaseTask = resolve;
    });
    const registry = new SchedulerRegistry();
    registry.register({
      name: "startup-stop-task",
      intervalSeconds: 1,
      run: async () => taskBlocked,
      awaitRunOnStart: true,
    });

    try {
      void registry.start();
      let stopped = false;
      const stopPromise = registry.stop().then(() => {
        stopped = true;
      });
      await Promise.resolve();
      expect(stopped).toBe(false);
      releaseTask();
      await stopPromise;
      expect(stopped).toBe(true);
      expect(registry.taskNames).toEqual(["startup-stop-task"]);
    } finally {
      releaseTask();
      vi.useRealTimers();
    }
  });

  it("does not overlap a slow task and waits for it during stop", async () => {
    vi.useFakeTimers();
    let releaseTask: () => void = () => undefined;
    const taskBlocked = new Promise<void>((resolve) => {
      releaseTask = resolve;
    });
    const run = vi.fn(async () => {
      await taskBlocked;
    });

    try {
      const handle = startSchedulerRegistry(
        [{ name: "slow-task", intervalSeconds: 1, run, runOnStart: true }],
        { warn: vi.fn(), error: vi.fn() },
      );

      expect(run).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(5_000);
      expect(run).toHaveBeenCalledTimes(1);

      let stopped = false;
      const stopPromise = handle.stop().then(() => {
        stopped = true;
      });
      await Promise.resolve();
      expect(stopped).toBe(false);

      releaseTask();
      await stopPromise;
      expect(stopped).toBe(true);
      expect(run).toHaveBeenCalledTimes(1);
    } finally {
      releaseTask();
      vi.useRealTimers();
    }
  });
});

describe("jobs route visibility", () => {
  it("treats cross-space jobs as not found", () => {
    expect(jobNotFoundForSpace({ space_id: "space-2" }, "space-1")).toBe(true);
    expect(jobNotFoundForSpace({ space_id: "space-1" }, "space-1")).toBe(false);
  });

  it("maps database job rows to the public jobs schema", () => {
    expect(jobToOut(makeJob({
      payload_json: { run_id: "run-1" },
      result_json: { ok: true },
    }))).toMatchObject({
      id: "job-1",
      payload: { run_id: "run-1" },
      result: { ok: true },
    });
  });

  it("maps job event data and timestamps to the public event schema", () => {
    expect(jobEventToOut({
      id: "event-1",
      job_id: "job-1",
      event_type: "status_change",
      message: "started",
      data: { worker_id: "worker-1" },
      created_at: "2026-06-16T00:00:00.000Z",
    })).toEqual({
      id: "event-1",
      job_id: "job-1",
      event_type: "status_change",
      message: "started",
      data: { worker_id: "worker-1" },
      created_at: "2026-06-16T00:00:00.000Z",
    });
  });
});

describe("automation schedule", () => {
  it("computes the next cron slot after a reference instant", () => {
    const next = computeNextRunAt(
      { cron: "0 9 * * *", timezone: "UTC" },
      new Date("2026-06-16T08:00:00.000Z"),
    );
    expect(next.toISOString()).toBe("2026-06-16T09:00:00.000Z");
  });

  it("supports stepped cron fields without an external cron package", () => {
    const next = computeNextRunAt(
      { cron: "*/15 9-10 * * *", timezone: "UTC" },
      new Date("2026-06-16T09:07:00.000Z"),
    );
    expect(next.toISOString()).toBe("2026-06-16T09:15:00.000Z");
  });

  it("computes cron slots in the configured timezone", () => {
    const next = computeNextRunAt(
      { cron: "0 9 * * *", timezone: "Europe/London" },
      new Date("2026-06-16T07:00:00.000Z"),
    );
    expect(next.toISOString()).toBe("2026-06-16T08:00:00.000Z");
  });

  it("rejects invalid cron expressions", () => {
    expect(() => computeNextRunAt({ cron: "not-a-cron", timezone: "UTC" })).toThrow(
      InvalidScheduleError,
    );
  });

  it("rejects invalid timezones", () => {
    expect(() => computeNextRunAt({ cron: "0 9 * * *", timezone: "Mars/Phobos" })).toThrow(
      InvalidScheduleError,
    );
  });
});

describe("PgJobQueueRepository retry semantics", () => {
  it("returns pending when failJob still has retry budget", async () => {
    const db = new JobQueueFakeDb();
    const repo = new PgJobQueueRepository(db);
    const status = await repo.failJob("job-1", "transient", "worker-1");
    expect(status).toBe("pending");
    expect(db.calls[0].sql).toContain("CASE WHEN attempts < max_attempts THEN 'pending'");
  });

  it("returns failed when failJob exhausts max_attempts", async () => {
    const db = new JobQueueFakeDb({ failStatus: "failed" });
    const repo = new PgJobQueueRepository(db);
    const status = await repo.failJob("job-1", "terminal", "worker-1");
    expect(status).toBe("failed");
  });

  it("reclaims stale claimed/running jobs and fails exhausted agent runs", async () => {
    const db = new JobQueueFakeDb();
    const repo = new PgJobQueueRepository(db);
    const result = await repo.reclaimStuckJobs(600, new Date("2026-06-16T10:10:00.000Z"));
    expect(db.calls[0].sql).toContain("DELETE FROM run_execution_locks");
    expect(db.calls[1].sql).toContain("WITH retryable AS");
    expect(db.calls[1].sql).toContain("failed_runs AS");
    expect(result.reclaimed_count).toBe(2);
  });
});

describe("PgRunRepository stale recovery", () => {
  it("fails stale running runs at TS worker startup", async () => {
    const db = new RunRecoveryFakeDb();
    const repo = new PgRunRepository(db);

    const recovered = await repo.recoverStaleRuns(
      3600,
      new Date("2026-06-16T10:00:00.000Z"),
    );

    expect(recovered).toBe(4);
    expect(db.calls[0].sql).toContain("UPDATE runs");
    expect(db.calls[0].sql).toContain("status = 'running'");
    expect(db.calls[0].sql).toContain("started_at < $1");
    expect(db.calls[0].params[0]).toBe("2026-06-16T09:00:00.000Z");
    expect(db.calls[0].params[1]).toBe("2026-06-16T10:00:00.000Z");
    expect(db.calls[0].params[2]).toContain("TS worker startup");
    expect(JSON.parse(String(db.calls[0].params[3]))).toEqual({
      error_code: "stale_run_recovered",
      error_text: "Run was stuck in running status and was recovered at TS worker startup",
    });
  });
});

describe("memory access-log retention", () => {
  it("prunes by accessed_at, matching the canonical memory_access_logs schema", async () => {
    const db = new MemoryAccessLogFakeDb();
    vi.mocked(getDbPool).mockReturnValue(db as never);
    const config = loadConfig({
      CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      CONTROL_PLANE_MEMORY_ACCESS_LOG_RETENTION_DAYS: "30",
    });

    await expect(pruneMemoryAccessLogs(config)).resolves.toBe(3);

    expect(db.calls[0].sql).toContain("WHERE accessed_at < $1");
    expect(db.calls[0].sql).not.toContain("created_at");
    expect(db.calls[0].params).toHaveLength(1);
  });
});

describe("AutomationService policy preflight", () => {
  const config = loadConfig({
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
  });
  const configWithoutDb = loadConfig({});

  beforeEach(() => {
    vi.mocked(enforce).mockReset();
  });

  it("rejects credential-looking automation config keys before policy enforcement", async () => {
    const repo = new FakeAutomationRepository(sampleAutomation());
    const service = new AutomationService(configWithoutDb, repo);
    await expect(
      service.create({
        spaceId: "space-1",
        ownerUserId: "owner-1",
        body: {
          name: "Nightly",
          agent_id: "agent-1",
          config_json: { nested: { apiToken: "secret" } },
        },
      }),
    ).rejects.toMatchObject({
      statusCode: 422,
      message: expect.stringContaining("apiToken"),
    });
    expect(enforce).not.toHaveBeenCalled();
  });

  it("allows non-secret token budget fields in automation config", async () => {
    vi.mocked(enforce).mockResolvedValue({ status: "allow" });
    const repo = new FakeAutomationRepository(sampleAutomation());
    const service = new AutomationService(configWithoutDb, repo);
    await expect(
      service.create({
        spaceId: "space-1",
        ownerUserId: "owner-1",
        body: {
          name: "Nightly",
          agent_id: "agent-1",
          config_json: { max_tokens: 1024 },
        },
      }),
    ).resolves.toMatchObject({ id: "auto-1" });
    expect(enforce).toHaveBeenCalledOnce();
  });

  it("passes active membership_role into automation policy checks", async () => {
    vi.mocked(enforce).mockResolvedValue({ status: "allow" });
    const repo = new FakeAutomationRepository(sampleAutomation(), "admin");
    const service = new AutomationService(configWithoutDb, repo);
    await service.create({
      spaceId: "space-1",
      ownerUserId: "owner-1",
      body: {
        name: "Nightly",
        agent_id: "agent-1",
        config_json: {},
      },
    });
    expect(vi.mocked(enforce).mock.calls[0]?.[2].context).toMatchObject({
      membership_role: "admin",
    });
  });

  it("blocks fire with 403 when policy denies automation.fire", async () => {
    vi.mocked(enforce).mockResolvedValue({
      status: "blocked",
      message: "automation.fire requires admin or owner authority",
    });
    const repo = new FakeAutomationRepository(sampleAutomation());
    const service = new AutomationService(config, repo);
    await expect(
      service.fire({
        spaceId: "space-1",
        automationId: "auto-1",
        actorUserId: "member-user",
      }),
    ).rejects.toMatchObject({ statusCode: 403, message: expect.stringContaining("admin") });
    expect(repo.createAutomationRunCalls).toBe(0);
  });
});

describe("Automation repository credential grants", () => {
  it("creates scheduled automation credential grants using canonical columns", async () => {
    const db = new AutomationFakeDb();
    const repo = new PgAutomationRepository(db);

    await repo.create({
      spaceId: "space-1",
      ownerUserId: "owner-1",
      name: "Nightly",
      agentId: "agent-1",
      triggerType: "schedule",
      configJson: { cron: "0 8 * * *", timezone: "UTC" },
      preflightSnapshot: { executable: true },
    });

    const grantInsert = db.calls.find((call) =>
      call.sql.includes("INSERT INTO automation_credential_grants"),
    );
    expect(grantInsert?.sql).toContain("created_at");
    expect(grantInsert?.sql).not.toContain("updated_at");
    expect(grantInsert?.params).toHaveLength(5);
  });

  it("revokes automation credential grants without writing a non-existent updated_at column", async () => {
    const db = new AutomationFakeDb(sampleAutomation({ trigger_type: "schedule" }));
    const repo = new PgAutomationRepository(db);

    await repo.update("space-1", "auto-1", { status: "archived" });

    const grantUpdate = db.calls.find((call) =>
      call.sql.includes("UPDATE automation_credential_grants"),
    );
    expect(grantUpdate?.sql).toContain("revoked_at");
    expect(grantUpdate?.sql).toContain("revoked_by_user_id");
    expect(grantUpdate?.sql).not.toContain("updated_at");
    expect(grantUpdate?.params).toHaveLength(4);
  });

  it("rolls back scheduled automation creation when credential grant insert fails", async () => {
    const pool = new AutomationTransactionalFakePool({ failGrantInsert: true });
    const repo = new PgAutomationRepository(pool);

    await expect(
      repo.create({
        spaceId: "space-1",
        ownerUserId: "owner-1",
        name: "Nightly",
        agentId: "agent-1",
        triggerType: "schedule",
        configJson: { cron: "0 8 * * *", timezone: "UTC" },
        preflightSnapshot: { executable: true },
      }),
    ).rejects.toThrow("grant insert failed");

    expect(pool.client.calls.map((call) => call.sql)).toEqual(
      expect.arrayContaining([
        "BEGIN",
        expect.stringContaining("INSERT INTO automations"),
        expect.stringContaining("INSERT INTO automation_credential_grants"),
        "ROLLBACK",
      ]),
    );
    expect(pool.client.calls.some((call) => call.sql === "COMMIT")).toBe(false);
    expect(pool.client.release).toHaveBeenCalledTimes(1);
  });
});

describe("DailyCaptureReport settings validation", () => {
  it("rejects string booleans instead of coercing them", async () => {
    const db = new DailySettingsFakeDb();
    const repo = new PgDailyReportSettingsRepository(db);

    await expect(
      repo.update("space-1", "user-1", { enabled: "false" }),
    ).rejects.toMatchObject({
      statusCode: 422,
      message: "enabled must be a boolean",
    });
    expect(db.calls.some((call) => call.sql.includes("UPDATE daily_capture_report_settings"))).toBe(false);
  });

  it("rejects invalid timezones and unsupported source types", async () => {
    const repo = new PgDailyReportSettingsRepository(new DailySettingsFakeDb());
    await expect(
      repo.update("space-1", "user-1", { enabled: true, timezone: "Mars/Phobos" }),
    ).rejects.toMatchObject({
      statusCode: 422,
      message: expect.stringContaining("valid IANA timezone"),
    });
    await expect(
      repo.update("space-1", "user-1", { include_source_types: ["user_capture", "email"] }),
    ).rejects.toMatchObject({
      statusCode: 422,
      message: expect.stringContaining("unsupported values"),
    });
  });

  it("does not build a scheduled job payload for an invalid legacy timezone", () => {
    const setting = sampleDailyReportSetting();
    expect(isValidTimezone("UTC")).toBe(true);
    expect(isValidTimezone("Mars/Phobos")).toBe(false);
    expect(buildDailyReportJobPayload(
      { ...setting, enabled: true, timezone: "Mars/Phobos", next_run_at: "2026-06-16T09:00:00.000Z" },
      "2026-06-16T09:00:00.000Z",
    )).toBeNull();
  });
});

interface QueryCall {
  sql: string;
  params: readonly unknown[];
}

class JobQueueFakeDb implements Queryable {
  calls: QueryCall[] = [];

  constructor(private readonly options: { failStatus?: "pending" | "failed" } = {}) {}

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    this.calls.push({ sql, params });
    if (sql.includes("AS reclaimed_count")) {
      return { rowCount: 1, rows: [{ reclaimed_count: "2" }] as Row[] };
    }
    if (sql.includes("RETURNING status")) {
      return {
        rowCount: 1,
        rows: [{ status: this.options.failStatus ?? "pending" }] as Row[],
      };
    }
    return { rowCount: 0, rows: [] };
  }
}

class RunRecoveryFakeDb implements Queryable {
  calls: QueryCall[] = [];

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    this.calls.push({ sql, params });
    return { rowCount: 4, rows: [] };
  }
}

class MemoryAccessLogFakeDb implements Queryable {
  calls: QueryCall[] = [];

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    this.calls.push({ sql, params });
    return { rowCount: 3, rows: [] };
  }
}

class FakeAutomationRepository {
  createAutomationRunCalls = 0;

  constructor(
    private readonly automation: AutomationRow,
    private readonly membershipRole: string | null = "owner",
  ) {}

  async get(spaceId: string, automationId: string): Promise<AutomationRow | null> {
    if (spaceId !== this.automation.space_id || automationId !== this.automation.id) return null;
    return this.automation;
  }

  async create(): Promise<AutomationRow> {
    return this.automation;
  }

  async getMembershipRole(): Promise<string | null> {
    return this.membershipRole;
  }

  async update(): Promise<AutomationRow> {
    return this.automation;
  }

  async hasActiveGrant(): Promise<boolean> {
    return false;
  }

  async createAutomationRun(): Promise<string> {
    this.createAutomationRunCalls += 1;
    return "automation-run-1";
  }

  async listDue(): Promise<AutomationRow[]> {
    return [];
  }

  async advanceSchedule(): Promise<void> {
    return;
  }
}

class AutomationFakeDb implements Queryable {
  calls: QueryCall[] = [];

  constructor(
    private readonly automation: AutomationRow = sampleAutomation(),
    private readonly options: { failGrantInsert?: boolean } = {},
  ) {}

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    this.calls.push({ sql, params });
    if (sql === "BEGIN" || sql === "COMMIT" || sql === "ROLLBACK") {
      return { rowCount: null, rows: [] };
    }
    if (sql.includes("SELECT") && sql.includes("FROM automations")) {
      return { rowCount: 1, rows: [this.automation] as Row[] };
    }
    if (sql.includes("INSERT INTO automations")) {
      return {
        rowCount: 1,
        rows: [
          {
            ...this.automation,
            id: String(params[0]),
            space_id: String(params[1]),
            owner_user_id: String(params[2]),
            agent_id: String(params[3]),
            workspace_id: params[4] as string | null,
            name: String(params[5]),
            description: params[6] as string | null,
            trigger_type: String(params[7]),
            preflight_snapshot_json: JSON.parse(String(params[8])) as Record<string, unknown>,
            config_json: JSON.parse(String(params[9])) as Record<string, unknown>,
            next_run_at: params[10] as string | null,
            created_at: String(params[11]),
            updated_at: String(params[11]),
          },
        ] as Row[],
      };
    }
    if (sql.includes("UPDATE automations")) {
      return {
        rowCount: 1,
        rows: [
          {
            ...this.automation,
            status: params[4] ?? this.automation.status,
            next_run_at: params[6] as string | null,
            updated_at: String(params[7]),
          },
        ] as Row[],
      };
    }
    if (sql.includes("automation_credential_grants")) {
      if (
        this.options.failGrantInsert &&
        sql.includes("INSERT INTO automation_credential_grants")
      ) {
        throw new Error("grant insert failed");
      }
      return { rowCount: 1, rows: [] };
    }
    throw new Error(`Unexpected SQL: ${sql}`);
  }
}

class AutomationFakeClient extends AutomationFakeDb {
  release = vi.fn();
}

class AutomationTransactionalFakePool implements Queryable {
  readonly client: AutomationFakeClient;
  calls: QueryCall[] = [];

  constructor(options: { failGrantInsert?: boolean } = {}) {
    this.client = new AutomationFakeClient(sampleAutomation(), options);
  }

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    this.calls.push({ sql, params });
    return { rowCount: 0, rows: [] };
  }

  async connect(): Promise<AutomationFakeClient> {
    return this.client;
  }
}

class DailySettingsFakeDb implements Queryable {
  calls: QueryCall[] = [];

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    this.calls.push({ sql, params });
    if (sql.includes("SELECT") && sql.includes("FROM daily_capture_report_settings")) {
      return { rowCount: 1, rows: [sampleDailyReportSetting()] as Row[] };
    }
    if (sql.includes("UPDATE daily_capture_report_settings")) {
      return {
        rowCount: 1,
        rows: [
          {
            ...sampleDailyReportSetting(),
            enabled: params[2],
            local_time: params[3],
            timezone: params[4],
            next_run_at: params[12],
          },
        ] as Row[],
      };
    }
    throw new Error(`Unexpected SQL: ${sql}`);
  }
}

function sampleDailyReportSetting(): DailyReportSettingRow {
  return {
    id: "setting-1",
    space_id: "space-1",
    user_id: "user-1",
    enabled: false,
    local_time: "09:00",
    timezone: "UTC",
    include_source_types_json: ["user_capture"],
    create_experience_proposals: true,
    create_memory_proposals: true,
    experience_confidence_threshold: 0.6,
    memory_confidence_threshold: 0.7,
    max_experience_proposals_per_day: 5,
    max_memory_proposals_per_day: 3,
    last_report_date: null,
    next_run_at: null,
    created_at: "2026-06-16T00:00:00.000Z",
    updated_at: "2026-06-16T00:00:00.000Z",
  };
}

function sampleAutomation(overrides: Partial<AutomationRow> = {}): AutomationRow {
  return {
    id: "auto-1",
    space_id: "space-1",
    owner_user_id: "owner-1",
    agent_id: "agent-1",
    workspace_id: null,
    name: "Nightly",
    description: null,
    trigger_type: "manual",
    status: "active",
    preflight_snapshot_json: { executable: true },
    config_json: null,
    next_run_at: null,
    last_fired_at: null,
    created_at: "2026-06-16T00:00:00.000Z",
    updated_at: "2026-06-16T00:00:00.000Z",
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobRecord> = {}): JobRecord {
  return {
    id: "job-1",
    space_id: "space-1",
    user_id: "user-1",
    workspace_id: null,
    agent_id: null,
    job_type: "agent_run",
    status: "claimed",
    priority: 0,
    payload_json: { run_id: "run-1" },
    result_json: null,
    error: null,
    attempts: 1,
    max_attempts: 3,
    scheduled_at: new Date().toISOString(),
    claimed_by: "worker-1",
    claimed_at: new Date().toISOString(),
    started_at: null,
    completed_at: null,
    heartbeat_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}
