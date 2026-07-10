import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { loadConfig } from "../src/config";
import { CliCredentialBroker } from "../src/modules/providers/cli/credentialBroker";
import { CliHistoryImportService } from "../src/modules/usage/cliHistoryImport";
import type { PgUsageRepository, UsageImportBatchRecord } from "../src/modules/usage/repository";
import type { NormalizedUsageObservation } from "../src/modules/usage/types";

let tempDir: string | undefined;

afterEach(async () => {
  if (tempDir) await rm(tempDir, { recursive: true, force: true });
  tempDir = undefined;
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
  });
}

function assistantLine(): string {
  return JSON.stringify({
    type: "assistant",
    timestamp: "2026-06-14T10:00:00.000Z",
    requestId: "req-1",
    message: {
      id: "msg-1",
      role: "assistant",
      model: "claude-sonnet-4-6",
      content: "SECRET_COMPLETION_TEXT",
      usage: {
        input_tokens: 100,
        output_tokens: 25,
        cache_read_input_tokens: 10,
      },
    },
  });
}

function fakeRepository(appended: NormalizedUsageObservation[]): PgUsageRepository {
  let batch: UsageImportBatchRecord | null = null;
  return {
    async getOrCreateInstanceId() {
      return "instance-1";
    },
    async countExistingIdempotencyKeys() {
      return 0;
    },
    async createImportBatch(input: {
      instanceId: string;
      targetSpaceId: string;
      ownerUserId: string;
      sourceType: string;
      sourceKind: string;
      sourceFingerprint: string;
      previewSummary: Record<string, unknown>;
    }) {
      batch = {
        id: "batch-1",
        instance_id: input.instanceId,
        target_space_id: input.targetSpaceId,
        owner_user_id: input.ownerUserId,
        source_type: input.sourceType,
        source_kind: input.sourceKind,
        status: "previewed",
        started_at: null,
        completed_at: null,
        source_fingerprint: input.sourceFingerprint,
        preview_summary_json: input.previewSummary,
        import_summary_json: {},
        error_json: null,
        created_at: "2026-06-14T10:00:00.000Z",
        updated_at: "2026-06-14T10:00:00.000Z",
      };
      return batch;
    },
    async getImportBatch(id: string, targetSpaceId: string) {
      if (!batch) return null;
      return batch.id === id && batch.target_space_id === targetSpaceId ? batch : null;
    },
    async markImportBatchImporting() {
      if (batch) batch.status = "importing";
    },
    async appendEvent(event: NormalizedUsageObservation) {
      appended.push(event);
      return {} as never;
    },
    async completeImportBatch(id: string, summary: Record<string, unknown>) {
      if (!batch || batch.id !== id) throw new Error("missing batch");
      batch.status = "completed";
      batch.completed_at = "2026-06-14T10:00:01.000Z";
      batch.import_summary_json = summary;
      return batch;
    },
    async failImportBatch() {
      throw new Error("unexpected failure");
    },
  } as unknown as PgUsageRepository;
}

function fakeBroker(profileDir: string): CliCredentialBroker {
  return {
    async resolveProfile(runtime: string, profileId?: string | null) {
      expect(runtime).toBe("claude_code");
      expect(profileId).toBe("profile-1");
      return {
        id: "profile-1",
        runtime: "claude_code",
        name: "Claude Main",
        source_path: profileDir,
        target_path: "/home/agent/.claude",
        readonly: true,
        notes: "",
        network_profile_id: null,
      };
    },
  } as unknown as CliCredentialBroker;
}

describe("CliHistoryImportService", () => {
  it("rejects imports into a Space outside the active identity", async () => {
    const service = new CliHistoryImportService(
      config(),
      fakeRepository([]),
      {} as CliCredentialBroker,
    );

    await expect(service.preview(
      { spaceId: "space-1", userId: "user-1" },
      {
        runtime: "claude_code",
        sourceKind: "managed_profile",
        targetSpaceId: "space-2",
      },
    )).rejects.toMatchObject({ statusCode: 403 });
  });

  it("previews and commits managed Claude transcript usage as lower-bound ledger events", async () => {
    tempDir = await mkdtemp(join(tmpdir(), "aspace-cli-import-"));
    const project = join(tempDir, "projects", "demo");
    await mkdir(project, { recursive: true });
    await writeFile(join(project, "session.jsonl"), assistantLine());

    const appended: NormalizedUsageObservation[] = [];
    const service = new CliHistoryImportService(
      config(),
      fakeRepository(appended),
      fakeBroker(tempDir),
    );

    const preview = await service.preview(
      { spaceId: "space-1", userId: "user-1" },
      {
        runtime: "claude_code",
        sourceKind: "managed_profile",
        credentialProfileId: "profile-1",
      },
    );

    expect(preview).toMatchObject({
      import_batch_id: "batch-1",
      status: "previewed",
      detected_runtime: "claude_code",
      source_kind: "managed_profile",
      credential_profile_id: "profile-1",
      candidate_event_count: 1,
      duplicate_count: 0,
      totals: {
        event_count: 1,
        input_tokens: 100,
        output_tokens: 25,
        cache_read_input_tokens: 10,
        total_tokens: 135,
      },
    });
    expect(JSON.stringify(preview)).not.toContain("SECRET_COMPLETION_TEXT");

    const committed = await service.commit(
      { spaceId: "space-1", userId: "user-1" },
      { importBatchId: "batch-1", confirmation: true },
    );

    expect(committed).toMatchObject({
      import_batch_id: "batch-1",
      status: "completed",
      imported_event_count: 1,
      candidate_event_count: 1,
    });
    expect(appended).toHaveLength(1);
    expect(appended[0]).toMatchObject({
      instance_id: "instance-1",
      space_id: "space-1",
      event_type: "cli.history_usage",
      source_type: "cli_history_import",
      execution_channel: "local_cli_transcript",
      meter_subject_type: "session",
      subject_user_id: "user-1",
      adapter_type: "claude_code",
      vendor: "anthropic",
      model: "claude-sonnet-4-6",
      external_session_id: expect.stringMatching(/^claude_code:/),
      session_path: "projects/demo/session.jsonl",
      input_tokens: 100,
      output_tokens: 25,
      cache_read_input_tokens: 10,
      total_tokens: 135,
      usage_accuracy: "transcript_lower_bound",
      import_batch_id: "batch-1",
      dimensions_json: expect.objectContaining({
        runtime: "claude_code",
        source_kind: "managed_profile",
        credential_profile_id: "profile-1",
      }),
    });
    expect(JSON.stringify(appended[0])).not.toContain("SECRET_COMPLETION_TEXT");
  });
});
