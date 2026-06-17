import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { loadConfig } from "../src/config";
import { RunMaterializationService } from "../src/modules/runs/materializationService";
import type { QueryResult, Queryable, RunRecord } from "../src/modules/runs/repository";
import type { RunFinalizationRecord } from "../src/modules/runs/repository";

let tempRoots: string[] = [];

afterEach(async () => {
  await Promise.all(tempRoots.map((root) => rm(root, { recursive: true, force: true })));
  tempRoots = [];
});

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "run-1",
    space_id: "space-1",
    agent_id: "agent-1",
    agent_version_id: "agent-version-1",
    status: "running",
    mode: "live",
    prompt: "Say hello",
    instruction: null,
    workspace_id: "workspace-1",
    session_id: null,
    project_id: "project-1",
    adapter_type: "model_api",
    model_provider_id: "provider-1",
    required_sandbox_level: "none",
    trigger_origin: "manual",
    instructed_by_user_id: "user-1",
    started_at: null,
    ended_at: null,
    ...overrides,
  };
}

class FakeDb implements Queryable {
  artifacts: unknown[][] = [];
  proposals: unknown[][] = [];

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<QueryResult<Row>> {
    if (sql.includes("INSERT INTO artifacts")) {
      this.artifacts.push([...params]);
      return { rows: [], rowCount: 1 };
    }
    if (sql.includes("INSERT INTO proposals")) {
      this.proposals.push([...params]);
      return { rows: [], rowCount: 1 };
    }
    throw new Error(`Unexpected SQL: ${sql}`);
  }
}

describe("RunMaterializationService", () => {
  it("materializes artifacts and supported proposals natively", async () => {
    const artifactRoot = await mkdtemp(join(tmpdir(), "aspace-artifacts-"));
    const sandboxRoot = await mkdtemp(join(tmpdir(), "aspace-sandbox-"));
    tempRoots.push(artifactRoot, sandboxRoot);
    await mkdir(join(sandboxRoot, "logs"), { recursive: true });
    await writeFile(join(sandboxRoot, "logs", "out.txt"), "file artifact", "utf8");

    const db = new FakeDb();
    const config = loadConfig({
      SERVER_DATABASE_URL: "postgresql://server@localhost:5432/agent_space",
      ARTIFACT_STORAGE_ROOT: artifactRoot,
    });
    const service = new RunMaterializationService(
      config,
      db,
      undefined,
      async () => ({ status: "allow" }),
    );

    const result = await service.materializeAdapterResult({
      run: run(),
      sandbox_cwd: sandboxRoot,
      adapterResult: {
        adapter_type: "model_api",
        adapter_kind: "managed_api",
        success: true,
        output_text: "hello token=secret",
        output_json: {
          artifacts: [
            {
              title: "Report",
              content: "ok",
              mime_type: "text/markdown",
              metadata_json: { section: "summary" },
            },
          ],
          proposed_changes: [
            {
              proposal_type: "code_patch",
              workspace_id: "workspace-1",
              patch: {
                operations: [
                  {
                    type: "replace_file",
                    path: "a.txt",
                    content: "x",
                    preimage_sha256: null,
                    preimage_exists: false,
                  },
                ],
              },
            },
            { proposal_type: "deployment_job", title: "unsupported" },
          ],
          activities: [{ title: "activity" }],
        },
        produced_artifact_paths: ["logs/out.txt"],
        exit_code: 0,
        error_code: null,
        error_message: null,
        started_at: "2026-06-12T10:00:00.000Z",
        completed_at: "2026-06-12T10:00:01.000Z",
        usage: null,
      },
    });

    expect(result.items).toMatchObject([
      { kind: "artifact", status: "succeeded" },
      { kind: "artifact", status: "succeeded" },
      { kind: "artifact", status: "succeeded" },
      { kind: "proposal", status: "succeeded" },
      {
        kind: "proposal",
        status: "failed",
        error_code: "output_proposal_materialization_error",
      },
      {
        kind: "activity",
        status: "failed",
        error_code: "output_activity_materialization_error",
      },
    ]);
    expect(db.artifacts).toHaveLength(3);
    expect(db.proposals).toHaveLength(1);

    const runtimeStoragePath = db.artifacts[0][6] as string;
    expect(await readFile(join(artifactRoot, runtimeStoragePath), "utf8")).toBe(
      "hello token=secret",
    );

    const copiedStoragePath = db.artifacts[1][6] as string;
    expect(await readFile(join(artifactRoot, copiedStoragePath), "utf8")).toBe(
      "file artifact",
    );

    expect(db.artifacts[2][5]).toBe("ok");
    expect(db.artifacts[2][7]).toBe("text/markdown");

    const proposalPayload = JSON.parse(db.proposals[0][9] as string) as Record<string, unknown>;
    expect(proposalPayload.patch).toEqual({
      operations: [
        {
          type: "replace_file",
          path: "a.txt",
          content: "x",
          preimage_sha256: null,
          preimage_exists: false,
        },
      ],
    });
    expect(result.errors).toEqual([
      'proposal:output_proposal_materialization_error:unsupported proposal_type "deployment_job"',
      "activity:output_activity_materialization_error:Activity materialization is intentionally deferred in the server backend.",
    ]);
  });

  it("calls the server finalization service directly", async () => {
    const db = new FakeDb();
    const config = loadConfig({
      SERVER_DATABASE_URL: "postgresql://server@localhost:5432/agent_space",
    });
    const calls: Array<{ runId: string; spaceId: string }> = [];
    const finalizer = {
      async finalize(runId: string, spaceId: string): Promise<RunFinalizationRecord> {
        calls.push({ runId, spaceId });
        return {
          id: "finalization-1",
          space_id: spaceId,
          run_id: runId,
          finalizer_version: "post_run_finalization.v1",
          status: "completed",
          run_evaluation_id: "evaluation-1",
          task_evaluation_id: "task-evaluation-1",
          outcome_status: "passed",
          failure_layer: null,
          failure_reason_code: null,
          trajectory_status: "acceptable",
          skipped_reasons_json: [],
          error_json: null,
          metadata_json: {},
          finalized_at: "2026-06-12T10:00:00.000Z",
          created_at: "2026-06-12T10:00:00.000Z",
        };
      },
    };
    const service = new RunMaterializationService(
      config,
      db,
      finalizer,
      async () => ({ status: "allow" }),
    );

    const result = await service.finalizeRun(run({ status: "succeeded" }));

    expect(calls).toEqual([{ runId: "run-1", spaceId: "space-1" }]);
    expect(result).toMatchObject({
      kind: "activity",
      status: "succeeded",
      activity_id: "finalization-1",
      metadata_json: {
        run_finalization_id: "finalization-1",
        run_evaluation_id: "evaluation-1",
        task_evaluation_id: "task-evaluation-1",
      },
    });
  });
});
