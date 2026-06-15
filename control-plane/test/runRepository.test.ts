import { describe, expect, it } from "vitest";
import {
  PgRunRepository,
  type QueryResult,
  type Queryable,
} from "../src/modules/runs/repository";

interface QueryCall {
  sql: string;
  params: readonly unknown[];
}

class FakeDb implements Queryable {
  calls: QueryCall[] = [];
  rowCount = 1;
  actorExists = false;

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    this.calls.push({ sql, params });
    if (sql.includes("INSERT INTO actors")) {
      return { rowCount: 1, rows: [{ id: "actor-created" }] as Row[] };
    }
    if (sql.includes("FROM actors")) {
      return {
        rowCount: this.actorExists ? 1 : 0,
        rows: (this.actorExists ? [{ id: "actor-existing" }] : []) as Row[],
      };
    }
    if (sql.includes("RETURNING id, space_id, agent_id")) {
      return {
        rowCount: this.rowCount,
        rows: [
          {
            id: params[1],
            space_id: params[0],
            agent_id: "agent-1",
            agent_version_id: "version-1",
            status: sql.includes("status = 'running'") ? "running" : params[2],
            mode: "live",
            prompt: "Prompt",
            instruction: null,
            workspace_id: null,
            session_id: null,
            project_id: null,
            adapter_type: "model_api",
            model_provider_id: "provider-1",
            required_sandbox_level: "none",
            trigger_origin: "manual",
            started_at: null,
            ended_at: null,
          },
        ] as Row[],
      };
    }
    if (sql.includes("RETURNING id, space_id, run_id, event_index")) {
      return {
        rowCount: this.rowCount,
        rows: [
          {
            id: params[2],
            space_id: params[0],
            run_id: params[1],
            event_index: 0,
            event_type: params[5],
            status: params[6],
          },
        ] as Row[],
      };
    }
    if (sql.includes("RETURNING id, space_id, run_id, step_index")) {
      return {
        rowCount: this.rowCount,
        rows: [
          {
            id: params[2],
            space_id: params[0],
            run_id: params[1],
            step_index: 0,
            step_type: params[5],
            status: params[6],
          },
        ] as Row[],
      };
    }
    return { rowCount: this.rowCount, rows: [] };
  }
}

describe("PgRunRepository", () => {
  it("marks queued runs running with a space-scoped update", async () => {
    const db = new FakeDb();
    const repo = new PgRunRepository(db);

    const row = await repo.markRunRunning({
      run_id: "run-1",
      space_id: "space-1",
      started_at: "2026-06-12T10:00:00.000Z",
      required_sandbox_level: "worktree",
    });

    expect(row?.status).toBe("running");
    expect(db.calls[0].sql).toContain("WHERE space_id = $1 AND id = $2 AND status = 'queued'");
    expect(db.calls[0].params.slice(0, 4)).toEqual([
      "space-1",
      "run-1",
      "2026-06-12T10:00:00.000Z",
      "worktree",
    ]);
  });

  it("appends run events with DB-side event index and redacted metadata", async () => {
    const db = new FakeDb();
    const repo = new PgRunRepository(db);

    await repo.appendRunEvent({
      run_id: "run-1",
      space_id: "space-1",
      event_type: "adapter_invoked",
      status: "running",
      summary: "calling Bearer rawsecrettokenvalue",
      metadata_json: {
        adapter_type: "codex_cli",
        stdout: "raw output",
        nested: { api_key: "sk-1234567890abcdef" },
      },
    });

    const call = db.calls[0];
    expect(call.sql).toContain("INSERT INTO run_events");
    expect(call.sql).toContain("COALESCE(MAX(event_index) + 1, 0)");
    // ::varchar casts keep the parameter type consistent between the inserted
    // value and the scalar-subquery comparison (real-PostgreSQL inference).
    expect(call.sql).toContain("WHERE space_id = $1::varchar AND run_id = $2::varchar");
    expect(call.params[7]).toBe("calling [REDACTED_SECRET]");
    expect(JSON.parse(String(call.params[15]))).toEqual({
      adapter_type: "codex_cli",
      stdout: "[REDACTED_EVIDENCE_FIELD]",
      nested: { api_key: "[REDACTED_EVIDENCE_FIELD]" },
    });
  });

  it("creates coarse run steps without rich duplicated evidence", async () => {
    const db = new FakeDb();
    const repo = new PgRunRepository(db);

    await repo.createRunStep({
      run_id: "run-1",
      space_id: "space-1",
      actor_id: "actor-1",
      step_type: "adapter_started",
      status: "running",
      title: "Adapter started",
      error_message: "password=secret-value",
      metadata_json: { detail: "safe", full_patch: "diff --git ..." },
    });

    const call = db.calls[0];
    expect(call.sql).toContain("INSERT INTO run_steps");
    expect(call.sql).toContain("COALESCE(MAX(step_index) + 1, 0)");
    expect(call.params[18]).toBe("[REDACTED_SECRET]");
    expect(JSON.parse(String(call.params[19]))).toEqual({
      detail: "safe",
      full_patch: "[REDACTED_EVIDENCE_FIELD]",
    });
  });

  it("marks terminal runs with sanitized output and error snapshots", async () => {
    const db = new FakeDb();
    const repo = new PgRunRepository(db);

    await repo.markRunTerminal({
      run_id: "run-1",
      space_id: "space-1",
      status: "failed",
      output_text: "final output",
      output_json: { response: "ok", secret_ref: "secret" },
      error_json: { error_text: "api_key=secret-value" },
      exit_code: 1,
      completed_at: "2026-06-12T10:00:10.000Z",
      usage_json: { total_tokens: 12 },
    });

    const call = db.calls[0];
    expect(call.sql).toContain("UPDATE runs");
    expect(call.sql).toContain("WHERE space_id = $1 AND id = $2");
    // Terminal writes never overwrite an already-terminal run (cancel race).
    expect(call.sql).toContain(
      "AND status NOT IN ('succeeded', 'failed', 'degraded', 'cancelled')",
    );
    expect(JSON.parse(String(call.params[3]))).toEqual({
      response: "ok",
      secret_ref: "[REDACTED_EVIDENCE_FIELD]",
      output_text: "final output",
    });
    expect(JSON.parse(String(call.params[4]))).toEqual({
      error_text: "[REDACTED_SECRET]",
    });
    expect(call.params[8]).toBe("[REDACTED_SECRET]");
  });

  it("acquires and releases execution locks by run id", async () => {
    const db = new FakeDb();
    const repo = new PgRunRepository(db);

    await expect(
      repo.tryAcquireExecutionLock({
        run_id: "run-1",
        worker_id: "worker-1",
        job_id: "job-1",
      }),
    ).resolves.toBe(true);
    await repo.releaseExecutionLock("run-1");

    expect(db.calls[0].sql).toContain("INSERT INTO run_execution_locks");
    expect(db.calls[0].sql).toContain("ON CONFLICT (run_id) DO NOTHING");
    expect(db.calls[1].sql).toBe("DELETE FROM run_execution_locks WHERE run_id = $1");
    expect(db.calls[1].params).toEqual(["run-1"]);
  });

  describe("resolveRunActorId", () => {
    it("resolves the instructing user actor, creating it when absent", async () => {
      const db = new FakeDb();
      const repo = new PgRunRepository(db);

      const id = await repo.resolveRunActorId(
        { space_id: "s1", instructed_by_user_id: "u1" },
        "http",
      );

      expect(id).toBe("actor-created");
      expect(db.calls[0].sql).toContain("FROM actors");
      expect(db.calls[0].sql).toContain("actor_type = 'user'");
      expect(db.calls[0].params).toEqual(["u1", "s1"]);
      expect(db.calls[1].sql).toContain("INSERT INTO actors");
    });

    it("reuses an existing actor without inserting", async () => {
      const db = new FakeDb();
      db.actorExists = true;
      const repo = new PgRunRepository(db);

      const id = await repo.resolveRunActorId(
        { space_id: "s1", instructed_by_user_id: "u1" },
        "http",
      );

      expect(id).toBe("actor-existing");
      // No INSERT — only the existence SELECT ran.
      expect(db.calls).toHaveLength(1);
      expect(db.calls[0].sql).toContain("FROM actors");
    });

    it("uses the agent_run job actor for job runs without an instructing user", async () => {
      const db = new FakeDb();
      const repo = new PgRunRepository(db);

      await repo.resolveRunActorId(
        { space_id: "s1", instructed_by_user_id: null },
        "job",
      );

      // actor_type, service_name, space_id — never impersonates a user.
      expect(db.calls[0].params).toEqual(["job", "agent_run", "s1"]);
    });

    it("uses the run_execution system actor for non-job runs without a user", async () => {
      const db = new FakeDb();
      const repo = new PgRunRepository(db);

      await repo.resolveRunActorId(
        { space_id: "s1", instructed_by_user_id: null },
        "http",
      );

      expect(db.calls[0].params).toEqual(["system", "run_execution", "s1"]);
    });
  });
});
