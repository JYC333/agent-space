import { describe, expect, it } from "vitest";
import { PgActivityRepository } from "../src/modules/activity/repository";
import { PgIntakeRepository } from "../src/modules/intake/repository";
import { PgKnowledgeRepository } from "../src/modules/knowledge/repository";
import type { ControlPlaneConfig } from "../src/config";
import type { SpaceUserIdentity, Queryable } from "../src/modules/routeUtils/common";

function intakeConfig(): ControlPlaneConfig {
  return {
    host: "127.0.0.1",
    port: 8010,
    pythonApiBaseUrl: "http://python.test",
    enablePythonFallbackProxy: false,
    logLevel: "silent",
    requestTimeoutMs: 1000,
    catalogRoot: "/tmp/catalog",
    runEventStreamPollIntervalMs: 1000,
    runEventStreamPageLimit: 100,
    enableNotificationWebhookEgress: false,
    notificationWebhookAllowlist: [],
    notificationMaxPayloadBytes: 64 * 1024,
    databaseUrl: null,
    agentSpaceHome: "/tmp/aspace",
    workspaceRoot: "/tmp/aspace/workspaces",
    cliToolsRoot: "/tmp/aspace/runtime-tools",
    sandboxRoot: "/tmp/aspace/sandboxes",
    deployerSocketPath: "/tmp/aspace/run/deployer.sock",
    artifactStorageRoot: "/tmp/aspace/storage/artifacts",
    internalToken: null,
    googleClientId: "",
    googleClientSecret: "",
    googleRedirectUri: "",
    frontendUrl: "http://localhost:5173",
    sessionExpireDays: 30,
    debug: true,
    dailyReportSchedulerEnabled: true,
    dailyReportSchedulerIntervalSeconds: 60,
    automationSchedulerEnabled: true,
    automationSchedulerIntervalSeconds: 60,
    memoryAccessLogRetentionEnabled: true,
    memoryAccessLogRetentionDays: 90,
    memoryAccessLogPruneIntervalSeconds: 3600,
    intakeExtractionSchedulerEnabled: true,
    intakeExtractionSchedulerIntervalSeconds: 30,
    agentSpaceEnv: "",
    appVersion: null,
    backupEnabled: false,
    backupIntervalHours: 24,
    backupRetentionCount: 7,
    backupIncludeLogs: false,
    backupOnStartup: true,
    backupRoot: "/tmp/backups",
    backupAcceptNoBackup: false,
    backupDatabaseUrl: null,
  };
}


type QueryCall = { sql: string; params: readonly unknown[] };

class FakeDb implements Queryable {
  readonly calls: QueryCall[] = [];

  constructor(private readonly handler: (sql: string, params: readonly unknown[]) => unknown[]) {}

  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
    this.calls.push({ sql, params });
    return { rows: this.handler(sql, params) as Row[], rowCount: null };
  }
}

const identity: SpaceUserIdentity = { spaceId: "space-1", userId: "user-1" };

function activityRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "activity-1",
    space_id: "space-1",
    source_run_id: null,
    session_id: null,
    user_id: "user-1",
    workspace_id: null,
    agent_id: null,
    source_task_id: null,
    project_id: null,
    source_url: null,
    activity_type: "user_capture",
    title: "Captured note",
    content: "Remember the sourced activity.",
    payload_json: {},
    occurred_at: "2026-06-16T00:00:00.000Z",
    created_at: "2026-06-16T00:00:00.000Z",
    status: "raw",
    updated_at: "2026-06-16T00:00:00.000Z",
    source_kind: "user_capture",
    source_trust: "user_confirmed",
    source_integrity_json: null,
    entity_refs_json: null,
    subject_user_id: "user-1",
    owner_user_id: "user-1",
    visibility: "space_shared",
    processed_at: null,
    discarded_at: null,
    consolidation_status: "pending",
    ...overrides,
  };
}

function proposalRow(params: readonly unknown[]) {
  return {
    id: String(params[0] ?? "proposal-1"),
    space_id: String(params[1] ?? "space-1"),
    created_by_user_id: typeof params[8] === "string" ? params[8] : "user-1",
    workspace_id: typeof params[6] === "string" ? params[6] : null,
    created_by_run_id: null,
    proposal_type: String(params[2] ?? "memory_create"),
    status: "pending",
    risk_level: "low",
    urgency: "normal",
    preview: false,
    title: String(params[3] ?? "Proposal"),
    payload_json: JSON.parse(String(params[4] ?? "{}")) as Record<string, unknown>,
    rationale: String(params[7] ?? ""),
    visibility: "space_shared",
    review_deadline: null,
    expires_at: null,
    created_at: String(params[5] ?? "2026-06-16T00:00:00.000Z"),
    reviewed_at: null,
    project_id: typeof params[9] === "string" ? params[9] : null,
    egress_approval_id: null,
    egress_approval_status: null,
  };
}

function sqlLog(db: FakeDb): string {
  return db.calls.map((call) => call.sql).join("\n");
}

describe("Leaf domain repository behavior", () => {
  it("captures raw input as an activity record before any proposal or memory write", async () => {
    const db = new FakeDb((sql) => {
      if (sql.includes("INSERT INTO activity_records")) return [activityRow()];
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const out = await new PgActivityRepository(db).create(identity, {
      source_type: "user_capture",
      title: "Captured note",
      content: "Remember the sourced activity.",
    });

    expect(out).toMatchObject({ id: "activity-1", status: "raw" });
    expect(db.calls).toHaveLength(1);
    expect(sqlLog(db)).toMatch(/INSERT INTO activity_records/);
    expect(sqlLog(db)).not.toMatch(/INSERT INTO proposals|memory_entries/);
  });

  it("consolidates activity into a pending memory proposal with activity provenance only", async () => {
    const db = new FakeDb((sql, params) => {
      if (sql.includes("FROM activity_records")) return [activityRow()];
      if (sql.includes("INSERT INTO proposals")) return [proposalRow(params)];
      if (sql.includes("UPDATE activity_records")) return [];
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const proposals = await new PgActivityRepository(db).consolidate(identity, "activity-1");

    expect(proposals).toHaveLength(1);
    expect(proposals[0]).toMatchObject({ proposal_type: "memory_create", status: "pending" });
    expect(proposals[0].provenance_entries).toEqual([
      expect.objectContaining({
        source_type: "activity",
        source_id: "activity-1",
        source_trust: "user_confirmed",
      }),
    ]);
    expect(sqlLog(db)).toMatch(/UPDATE activity_records/);
    expect(sqlLog(db)).not.toMatch(/INSERT INTO memory_entries|UPDATE memory_entries/);
  });

  it("creates intake summary proposals with evidence and intake provenance, not direct memory writes", async () => {
    const proposalPayloads: Record<string, unknown>[] = [];
    const db = new FakeDb((sql, params) => {
      if (sql.includes("FROM extracted_evidence")) {
        return [{ id: "evidence-1", title: "Evidence", content_excerpt: "Excerpt", source_uri: "https://example.test/e", trust_level: "normal" }];
      }
      if (sql.includes("FROM intake_items")) {
        return [{ id: "item-1", title: "Item", excerpt: "Item excerpt", source_uri: "https://example.test/i", content_state: "excerpt_saved" }];
      }
      if (sql.includes("INSERT INTO artifacts")) return [];
      if (sql.includes("INSERT INTO proposals")) {
        proposalPayloads.push(JSON.parse(String(params[4])) as Record<string, unknown>);
        return [{ id: `${params[2]}-proposal` }];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const out = await new PgIntakeRepository(db, intakeConfig()).createSummaryRun(identity, {
      evidence_ids: ["evidence-1"],
      intake_item_ids: ["item-1"],
      create_memory_proposal: true,
      create_knowledge_proposal: true,
    });

    expect(out).toMatchObject({ status: "succeeded", proposal_ids: ["memory_create-proposal", "knowledge_create-proposal"] });
    expect(proposalPayloads[0]).toMatchObject({
      provenance_entries: [
        { source_type: "artifact", source_trust: "internal_system" },
        { source_type: "extracted_evidence", source_id: "evidence-1", source_trust: "agent_inferred" },
        { source_type: "intake_item", source_id: "item-1", source_trust: "untrusted_external" },
      ],
    });
    expect(proposalPayloads[1]).toMatchObject({
      source_refs: [
        { source_type: "artifact", source_trust: "internal_system" },
        { source_type: "extracted_evidence", source_id: "evidence-1", source_trust: "agent_inferred" },
        { source_type: "intake_item", source_id: "item-1", source_trust: "untrusted_external" },
      ],
    });
    expect(sqlLog(db)).not.toMatch(/INSERT INTO memory_entries|UPDATE memory_entries/);
  });

  it("creates Knowledge proposals without auto-promoting into Memory", async () => {
    const db = new FakeDb((sql, params) => {
      if (sql.includes("INSERT INTO proposals")) return [proposalRow(params)];
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const proposal = await new PgKnowledgeRepository(db).proposeCreate(identity, {
      item_type: "concept",
      title: "Knowledge item",
      content: "Curated knowledge content.",
      source_refs: [{ source_type: "activity", source_id: "activity-1", source_trust: "user_confirmed" }],
    });

    expect(proposal).toMatchObject({ proposal_type: "knowledge_create", status: "pending" });
    expect(proposal.provenance_entries).toBeNull();
    expect(sqlLog(db)).toMatch(/INSERT INTO proposals/);
    expect(sqlLog(db)).not.toMatch(/INSERT INTO memory_entries|UPDATE memory_entries/);
  });
});
