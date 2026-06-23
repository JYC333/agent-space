import { describe, expect, it } from "vitest";
import { PgActivityRepository } from "../src/modules/activity/repository";
import { PgIntakeRepository } from "../src/modules/intake/repository";
import { PgKnowledgeRepository } from "../src/modules/knowledge/repository";
import type { ServerConfig } from "../src/config";
import type { SpaceUserIdentity, Queryable } from "../src/modules/routeUtils/common";

function intakeConfig(): ServerConfig {
  return {
    host: "127.0.0.1",
    port: 8010,
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
    instanceAdminEmail: null,
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
    memoryMaintenanceSchedulerEnabled: true,
    memoryMaintenanceSchedulerIntervalSeconds: 900,
    memoryMaintenanceSchedulerBatchLimit: 5,
    intakeExtractionSchedulerEnabled: true,
    intakeExtractionSchedulerIntervalSeconds: 30,
    retrievalRerankEnabled: false,
    retrievalQueryRewriteEnabled: false,
    agentSpaceEnv: "",
    appVersion: null,
    enableSystemEvolution: false,
    systemCoreOwnerEmail: null,
    systemCoreBaseBranch: "main",
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


class FakeDb implements Queryable {
  constructor(private readonly handler: (sql: string, params: readonly unknown[]) => unknown[]) {}

  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
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

function noteRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "note-1",
    space_id: "space-1",
    title: "Project note",
    content_json: {},
    content_format: "plain",
    content_schema_version: 1,
    plain_text: "Project note body",
    excerpt: "Project note body",
    status: "active",
    primary_project_id: null,
    collection_id: "collection-1",
    created_from_activity_id: null,
    created_by_user_id: "user-1",
    created_at: "2026-06-16T00:00:00.000Z",
    updated_at: "2026-06-16T00:00:00.000Z",
    archived_at: null,
    deleted_at: null,
    ...overrides,
  };
}

function claimRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "claim-1",
    space_id: "space-1",
    subject_object_id: null,
    subject_text: "Retrieval",
    claim_kind: "fact",
    claim_text: "The retrieval default embedding dimension is 2560.",
    normalized_claim_hash: "hash-1",
    holder_object_id: null,
    holder_type: null,
    holder_id: null,
    confidence: 0.9,
    confidence_method: "human_confirmed",
    resolution_state: "confirmed",
    valid_from: null,
    valid_until: null,
    observed_at: null,
    metadata_json: {},
    status: "active",
    visibility: "space_shared",
    title: "Retrieval embedding dimension",
    excerpt: null,
    owner_user_id: "user-1",
    primary_project_id: null,
    workspace_id: null,
    created_by_user_id: "user-1",
    created_by_agent_id: null,
    created_by_run_id: null,
    created_from_proposal_id: null,
    approved_by_user_id: null,
    created_at: "2026-06-16T00:00:00.000Z",
    updated_at: "2026-06-16T00:00:00.000Z",
    archived_at: null,
    ...overrides,
  };
}

function claimRelationRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "claim-relation-1",
    space_id: "space-1",
    from_claim_id: "claim-1",
    to_claim_id: "claim-2",
    relation_type: "supports",
    status: "active",
    confidence: 0.8,
    evidence_summary: null,
    source_proposal_id: null,
    created_by_user_id: "user-1",
    created_by_agent_id: null,
    created_at: "2026-06-16T00:00:00.000Z",
    updated_at: "2026-06-16T00:00:00.000Z",
    ...overrides,
  };
}

function objectRelationRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "object-relation-1",
    space_id: "space-1",
    from_object_id: "claim-1",
    from_object_type: "claim",
    to_object_id: "claim-2",
    to_object_type: "claim",
    relation_type: "supports",
    status: "active",
    confidence: 0.8,
    evidence_summary: null,
    source_claim_id: "claim-source-1",
    source_object_id: "source-1",
    source_proposal_id: null,
    metadata_json: {},
    created_by_user_id: "user-1",
    created_by_agent_id: null,
    created_at: "2026-06-16T00:00:00.000Z",
    updated_at: "2026-06-16T00:00:00.000Z",
    ...overrides,
  };
}

function intakeItemRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "item-1",
    title: "Item",
    excerpt: "Item excerpt",
    source_uri: "https://example.test/i",
    content_state: "metadata_only",
    connection_id: null,
    ...overrides,
  };
}

function sourceConnectionRow(policyOverrides: Record<string, unknown> = {}) {
  return {
    id: "conn-1",
    space_id: "space-1",
    connector_id: "connector-1",
    owner_user_id: "user-1",
    capture_policy: "metadata_only",
    trust_level: "normal",
    consent_json: {},
    policy_json: {
      schema_version: 1,
      source_egress_class: "internal_only",
      retention_policy: "summary_only",
      import_trust_level: "normal",
      derived_write_policy: "proposal_required",
      allowed_import_targets: ["activity", "source_artifact"],
      revalidation: { required: true, viewer_scoped: true },
      ...policyOverrides,
    },
  };
}

describe("Leaf domain repository behavior", () => {
  it("captures raw input as an activity record", async () => {
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
  });

  it("consolidates activity into a pending memory proposal with activity provenance", async () => {
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
  });

  it("creates intake summary proposals with evidence and intake provenance", async () => {
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
  });

  it("blocks connected manual URL content queueing beyond source retention policy", async () => {
    const db = new FakeDb((sql) => {
      if (sql.includes("FROM source_connections")) {
        return [sourceConnectionRow({ retention_policy: "metadata_only" })];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await expect(new PgIntakeRepository(db, intakeConfig()).createManualUrl(identity, {
      connection_id: "conn-1",
      url: "https://example.test/private",
      queue_content: true,
    })).rejects.toThrow("Source retention policy does not allow full_text");
  });

  it("blocks connected intake item actions beyond source retention policy", async () => {
    const db = new FakeDb((sql) => {
      if (sql.includes("FROM intake_items")) {
        return [intakeItemRow({ connection_id: "conn-1" })];
      }
      if (sql.includes("FROM source_connections")) {
        return [sourceConnectionRow({ retention_policy: "metadata_only" })];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await expect(new PgIntakeRepository(db, intakeConfig()).itemAction(identity, "item-1", {
      action: "queue_content",
    })).rejects.toThrow("Source retention policy does not allow full_text");
  });

  it("blocks source-derived summary proposals unless the source policy allows the target", async () => {
    const db = new FakeDb((sql) => {
      if (sql.includes("FROM intake_items")) {
        return [intakeItemRow({ connection_id: "conn-1" })];
      }
      if (sql.includes("INSERT INTO artifacts")) return [];
      if (sql.includes("FROM source_connections")) {
        return [sourceConnectionRow({ allowed_import_targets: ["activity", "source_artifact"] })];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await expect(new PgIntakeRepository(db, intakeConfig()).createSummaryRun(identity, {
      intake_item_ids: ["item-1"],
      create_memory_proposal: true,
    })).rejects.toThrow("Source policy does not allow memory_proposal imports");
  });

  it("allows source-derived summary proposals when the source policy opts in", async () => {
    const db = new FakeDb((sql, params) => {
      if (sql.includes("FROM intake_items")) {
        return [intakeItemRow({ connection_id: "conn-1" })];
      }
      if (sql.includes("INSERT INTO artifacts")) return [];
      if (sql.includes("FROM source_connections")) {
        return [sourceConnectionRow({ allowed_import_targets: ["activity", "source_artifact", "memory_proposal", "knowledge"] })];
      }
      if (sql.includes("INSERT INTO proposals")) return [{ id: `${params[2]}-proposal` }];
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const out = await new PgIntakeRepository(db, intakeConfig()).createSummaryRun(identity, {
      intake_item_ids: ["item-1"],
      create_memory_proposal: true,
      create_knowledge_proposal: true,
    });

    expect(out).toMatchObject({ proposal_ids: ["memory_create-proposal", "knowledge_create-proposal"] });
  });

  it("creates Knowledge proposals with knowledge-specific provenance", async () => {
    const db = new FakeDb((sql, params) => {
      if (sql.includes("INSERT INTO proposals")) return [proposalRow(params)];
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const proposal = await new PgKnowledgeRepository(db).proposeCreate(identity, {
      knowledge_kind: "concept",
      title: "Knowledge item",
      content: "Curated knowledge content.",
      source_refs: [{ source_type: "activity", source_id: "activity-1", source_trust: "user_confirmed" }],
    });

    expect(proposal).toMatchObject({ proposal_type: "knowledge_create", status: "pending" });
    expect(proposal.provenance_entries).toBeNull();
  });

  it("creates Claim proposals with normalized sources", async () => {
    const payloads: Record<string, unknown>[] = [];
    const db = new FakeDb((sql, params) => {
      if (sql.includes("FROM source_connections")) {
        return [sourceConnectionRow()];
      }
      if (sql.includes("INSERT INTO proposals")) {
        payloads.push(JSON.parse(String(params[4])) as Record<string, unknown>);
        return [proposalRow(params)];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const proposal = await new PgKnowledgeRepository(db).proposeClaimCreate(identity, {
      claim_kind: "fact",
      subject_text: "Retrieval",
      claim_text: "The retrieval default embedding dimension is 2560.",
      sources: [{
        source_ref_type: "external_pointer",
        source_ref_id: "pointer-1",
        source_connection_id: "conn-1",
        evidence_role: "supports",
        confidence: 0.8,
      }],
    });

    expect(proposal).toMatchObject({ proposal_type: "claim_create", status: "pending" });
    expect(payloads[0]).toMatchObject({
      operation: "claim_create",
      claim_kind: "fact",
      subject_text: "Retrieval",
      sources: [expect.objectContaining({
        source_ref_type: "external_pointer",
        source_ref_id: "pointer-1",
        source_connection_id: "conn-1",
        evidence_role: "supports",
        confidence: 0.8,
      })],
    });
  });

  it("rejects claim source refs without a source connection", async () => {
    const db = new FakeDb(() => {
      throw new Error("unexpected DB call");
    });

    await expect(new PgKnowledgeRepository(db).proposeClaimCreate(identity, {
      claim_kind: "fact",
      subject_text: "Retrieval",
      claim_text: "The retrieval default embedding dimension is 2560.",
      sources: [{
        source_ref_type: "external_pointer",
        source_ref_id: "pointer-1",
        evidence_role: "supports",
      }],
    })).rejects.toThrow("source_ref entries require source_connection_id");
  });

  it("creates object relation proposals after checking both endpoint objects", async () => {
    const seenObjectLookups: unknown[][] = [];
    const payloads: Record<string, unknown>[] = [];
    const db = new FakeDb((sql, params) => {
      if (sql.includes("FROM space_objects")) {
        seenObjectLookups.push([...params]);
        return [{
          id: params[0],
          space_id: "space-1",
          object_type: "claim",
          title: String(params[0]),
          status: "active",
          visibility: "space_shared",
          owner_user_id: "user-1",
          primary_project_id: null,
          workspace_id: null,
          created_by_user_id: "user-1",
        }];
      }
      if (sql.includes("INSERT INTO proposals")) {
        payloads.push(JSON.parse(String(params[4])) as Record<string, unknown>);
        return [proposalRow(params)];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const proposal = await new PgKnowledgeRepository(db).proposeObjectRelation(identity, {
      from_object_id: "claim-a",
      to_object_id: "claim-b",
      relation_type: "supports",
    });

    expect(seenObjectLookups).toEqual([
      ["claim-a", "space-1"],
      ["claim-b", "space-1"],
    ]);
    expect(proposal).toMatchObject({ proposal_type: "object_relation_create", status: "pending" });
    expect(payloads[0]).toMatchObject({
      operation: "object_relation_create",
      from_object_id: "claim-a",
      to_object_id: "claim-b",
      relation_type: "supports",
    });
  });

  it("counts only visible active claims in the knowledge summary", async () => {
    const db = new FakeDb((sql, params) => {
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("FROM notes n")) return [{ status: "active", total: "2" }];
      if (norm.includes("FROM knowledge_items ki")) return [{ total: "3" }];
      if (norm.includes("FROM sources s")) return [{ total: "4" }];
      if (norm.includes("FROM claims c")) {
        expect(sql).toContain("so.visibility IN ('space_shared', 'workspace_shared')");
        expect(sql).toContain("so.owner_user_id = $2");
        expect(sql).toContain("so.created_by_user_id = $2");
        expect(params).toEqual(["space-1", "user-1"]);
        return [{ total: "1" }];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const out = await new PgKnowledgeRepository(db).summary(identity);

    expect(out).toMatchObject({
      claims: { active: 1 },
      notes: { active: 2 },
      wiki: { active: 3 },
      sources: { total: 4 },
    });
  });

  it("hides claim relations unless both endpoint claims are visible", async () => {
    const db = new FakeDb((sql, params) => {
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("FROM claims c")) return [claimRow()];
      if (norm.includes("FROM claim_relations r")) {
        expect(sql).toContain("JOIN space_objects from_so");
        expect(sql).toContain("JOIN space_objects to_so");
        expect(sql).toContain("from_so.visibility IN ('space_shared', 'workspace_shared')");
        expect(sql).toContain("to_so.visibility IN ('space_shared', 'workspace_shared')");
        expect(sql).toContain("from_so.owner_user_id = $2");
        expect(sql).toContain("to_so.owner_user_id = $2");
        expect(sql).toContain("from_so.deleted_at IS NULL");
        expect(sql).toContain("to_so.deleted_at IS NULL");
        expect(params).toEqual(["space-1", "user-1", "claim-1"]);
        return [claimRelationRow()];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const out = await new PgKnowledgeRepository(db).claimRelations(identity, "claim-1");

    expect(out).toEqual([expect.objectContaining({ id: "claim-relation-1" })]);
  });

  it("hides object relations unless endpoints and evidence objects are visible", async () => {
    const db = new FakeDb((sql, params) => {
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("FROM object_relations r")) {
        expect(sql).toContain("JOIN space_objects from_so");
        expect(sql).toContain("JOIN space_objects to_so");
        expect(sql).toContain("from_so.object_type AS from_object_type");
        expect(sql).toContain("to_so.object_type AS to_object_type");
        expect(sql).toContain("LEFT JOIN space_objects source_claim_so");
        expect(sql).toContain("LEFT JOIN space_objects source_so");
        expect(sql).toContain("from_so.visibility IN ('space_shared', 'workspace_shared')");
        expect(sql).toContain("to_so.visibility IN ('space_shared', 'workspace_shared')");
        expect(sql).toContain("source_claim_so.visibility IN ('space_shared', 'workspace_shared')");
        expect(sql).toContain("source_so.visibility IN ('space_shared', 'workspace_shared')");
        expect(sql).toContain("r.source_claim_id IS NULL OR");
        expect(sql).toContain("r.source_object_id IS NULL OR");
        expect(params).toEqual(["space-1", "user-1", "claim-1"]);
        return [objectRelationRow()];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const out = await new PgKnowledgeRepository(db).objectRelations(identity, {
      from_object_id: "claim-1",
    });

    expect(out).toEqual([expect.objectContaining({ id: "object-relation-1", retrieval_projected: true })]);
  });

  it("marks object relations as not retrieval projected when an endpoint is not indexed by Knowledge retrieval", async () => {
    const db = new FakeDb((sql, params) => {
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("FROM object_relations r")) {
        expect(params).toEqual(["space-1", "user-1"]);
        return [objectRelationRow({ from_object_id: "project-1", from_object_type: "project", to_object_type: "claim" })];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const out = await new PgKnowledgeRepository(db).objectRelations(identity, {});

    expect(out).toEqual([
      expect.objectContaining({
        id: "object-relation-1",
        from_object_id: "project-1",
        retrieval_projected: false,
      }),
    ]);
  });

  it("filters notes by collection in both count and row queries", async () => {
    const seenSql: string[] = [];
    const db = new FakeDb((sql, params) => {
      seenSql.push(sql);
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("count(DISTINCT n.object_id)")) {
        expect(sql).toContain("LEFT JOIN note_collection_items nci_filter");
        expect(sql).toContain("nci_filter.space_id = n.space_id");
        expect(sql).toContain("nci_filter.collection_id = $2");
        expect(params).toEqual(["space-1", "collection-1"]);
        return [{ total: "1" }];
      }
      if (norm.includes("FROM notes n")) {
        expect(sql).toContain("LEFT JOIN note_collection_items nci_filter");
        expect(sql).toContain("nci_filter.space_id = n.space_id");
        expect(sql).toContain("nci_filter.collection_id = $2");
        return [noteRow()];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    const out = await new PgKnowledgeRepository(db).listNotes(identity, {
      status: null,
      projectId: null,
      collectionId: "collection-1",
      q: null,
      limit: 50,
      offset: 0,
    });

    expect(out).toMatchObject({ total: 1 });
    expect(seenSql).toHaveLength(2);
  });

  it("rejects note statuses outside the note lifecycle", async () => {
    let updateCount = 0;
    const db = new FakeDb((sql) => {
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("FROM notes n")) return [noteRow()];
      if (sql.includes("UPDATE space_objects")) {
        updateCount += 1;
        return [];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await expect(new PgKnowledgeRepository(db).updateNote(identity, "note-1", {
      status: "processed",
    })).rejects.toThrow("invalid note status");

    expect(updateCount).toBe(0);
  });

  it("writes note collection memberships with the current space", async () => {
    const seenSql: string[] = [];
    const db = new FakeDb((sql, params) => {
      seenSql.push(sql);
      const norm = sql.replace(/\s+/g, " ");
      if (norm.includes("FROM notes n")) return [noteRow()];
      if (sql.includes("UPDATE space_objects")) return [];
      if (sql.includes("SELECT id FROM note_collections")) {
        expect(params).toEqual(["collection-1", "space-1"]);
        return [{ id: "collection-1" }];
      }
      if (sql.includes("DELETE FROM note_collection_items")) {
        expect(sql).toContain("space_id = $2");
        expect(params).toEqual(["note-1", "space-1"]);
        return [];
      }
      if (sql.includes("INSERT INTO note_collection_items")) {
        expect(sql).toContain("id, space_id, collection_id, note_id");
        expect(params.slice(1, 4)).toEqual(["space-1", "collection-1", "note-1"]);
        return [];
      }
      throw new Error(`unexpected SQL: ${sql}`);
    });

    await new PgKnowledgeRepository(db).updateNote(identity, "note-1", {
      collection_id: "collection-1",
    });

    expect(seenSql.some((sql) => sql.includes("INSERT INTO note_collection_items"))).toBe(true);
  });
});
