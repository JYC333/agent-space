import { mkdtemp, mkdir, readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";
import { ContextCompiler } from "../src/modules/context/compiler";
import { ContextPrepareService } from "../src/modules/context/prepareService";
import {
  PgRunContextRepository,
  type ContextDigestRow,
  type ContextMemoryRow,
  type DigestBundle,
  type RunContextRecord,
  type SessionSummaryRow,
  type SnapshotUpdateInput,
  type PersonalGrantMetadata,
  type ContextEvidenceSelection,
} from "../src/modules/context/repository";
import { serializeMemoryRow } from "../src/modules/memory/repository";
import type { ServerConfig } from "../src/config";

function config(): ServerConfig {
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
    internalToken: "token",
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

function memory(over: Partial<ContextMemoryRow> = {}): ContextMemoryRow {
  return {
    id: "mem-1",
    space_id: "space-1",
    subject_user_id: "user-1",
    owner_user_id: "user-1",
    workspace_id: null,
    scope_type: "user",
    namespace: null,
    memory_type: "fact",
    title: "Known fact",
    content: "The user prefers concise plans.",
    status: "active",
    visibility: "private",
    sensitivity_level: "normal",
    selected_user_ids: null,
    last_confirmed_at: null,
    confidence: 0.9,
    importance: 0.8,
    source_id: null,
    created_by: "user-1",
    created_at: "2026-06-16T00:00:00.000Z",
    updated_at: "2026-06-16T00:00:00.000Z",
    deleted_at: null,
    version: 1,
    tags: [],
    memory_layer: "semantic",
    memory_kind: "preference",
    source_trust: "internal_system",
    created_from_proposal_id: null,
    root_memory_id: null,
    supersedes_memory_id: null,
    project_id: null,
    agent_id: "agent-1",
    capability_id: null,
    access_count: 0,
    last_accessed_at: null,
    last_retrieved_at: null,
    ...over,
  };
}

class FakeContextRepo extends PgRunContextRepository {
  readonly accesses: unknown[] = [];
  readonly snapshots: SnapshotUpdateInput[] = [];
  readonly runMarkers: Array<{ runId: string; metadata: PersonalGrantMetadata }> = [];
  readonly evidenceSelections: ContextEvidenceSelection[] = [
    {
      item: {
        id: "evidence-1",
        title: "Evidence",
        content_excerpt: "Relevant linked evidence.",
        evidence_type: "excerpt",
        trust_level: "normal",
        source_uri: null,
        artifact_id: null,
        link_id: "evidence-link-1",
        target_type: "space",
        target_id: "space-1",
      },
      ref: {
        source_type: "evidence",
        source_id: "evidence-1",
        evidence_type: "excerpt",
        link_id: "evidence-link-1",
        link_type: "context_candidate",
        target_type: "space",
        target_id: "space-1",
        trust_level: "normal",
        provenance_trust: "normal",
        section: "dynamic_tail",
      },
    },
  ];
  run: RunContextRecord | null = {
    id: "run-1",
    space_id: "space-1",
    agent_id: "agent-1",
    agent_version_id: "version-1",
    context_snapshot_id: "snapshot-1",
    prompt: "Do the work",
    workspace_id: null,
    project_id: null,
    session_id: "session-1",
    instructed_by_user_id: "user-1",
    trigger_origin: "manual",
    data_exposure_level: "model_provider",
    trust_level: "trusted",
    has_personal_grant_context: false,
    personal_grant_context_json: null,
    system_prompt: "You are a test agent.",
    memory_policy_json: { readable_scopes: ["user", "system"] },
  };
  rows: ContextMemoryRow[] = [memory()];
  digest: DigestBundle = {
    policy_bundle: null,
    workspace: null,
    agent: null,
  };
  grant = {
    personal_context_block:
      "The user has 1 relevant personal memory entry available for this context.",
    metadata: {
      grant_id: "grant-1",
      granting_user_id: "user-1",
      personal_space_id: "personal-space",
      target_space_id: "space-1",
      access_mode: "summary_only",
      memory_count: 1,
      raw_memory_included: false,
      personal_summary_persisted: false,
    } satisfies PersonalGrantMetadata,
  };

  constructor() {
    super({ async query() { return { rows: [], rowCount: 0 }; } });
  }

  override async withTransaction<T>(
    fn: (repo: PgRunContextRepository) => Promise<T>,
  ): Promise<T> {
    return fn(this);
  }

  override async loadRun(): Promise<RunContextRecord | null> {
    return this.run;
  }

  override async retrieve() {
    return {
      memories: this.rows,
      activePolicies: [
        {
          id: "policy-1",
          name: "Policy",
          domain: "runtime",
          policy_key: "runtime.policy",
          enforcement_mode: "allow",
          priority: 10,
          policy_json: { decision: "allow" },
        },
      ],
      sourceRefs: [
        {
          source_type: "memory",
          source_id: "mem-1",
          section: "stable_prefix",
          stage: "symbol_match",
        },
      ],
      retrievalTrace: { total_selected: 1 },
      tokenBudget: { default_budget_chars: 128000 },
    };
  }

  override async recordContextMemoryAccess(input: unknown): Promise<void> {
    this.accesses.push(input);
  }

  override async loadLatestSessionSummary(): Promise<SessionSummaryRow | null> {
    return {
      id: "summary-1",
      session_id: "session-1",
      summary_text: "Earlier context.",
      version: 1,
      condenser_version: "v1",
    };
  }

  override async selectEvidenceForContext(): Promise<ContextEvidenceSelection[]> {
    return this.evidenceSelections;
  }

  override async loadDigestBundle(): Promise<DigestBundle> {
    return this.digest;
  }

  override async updateSnapshot(input: SnapshotUpdateInput): Promise<void> {
    this.snapshots.push(input);
  }

  override async resolvePersonalGrantForRun() {
    return this.grant;
  }

  override async markRunPersonalGrantContext(input: {
    runId: string;
    spaceId: string;
    metadata: PersonalGrantMetadata;
  }): Promise<void> {
    this.runMarkers.push({ runId: input.runId, metadata: input.metadata });
  }
}

describe("ContextPrepareService", () => {
  it("populates the run snapshot, logs context memory reads, and keeps grant text ephemeral", async () => {
    const repo = new FakeContextRepo();
    const service = new ContextPrepareService(config(), repo);

    const result = await service.prepare({
      runId: "run-1",
      spaceId: "space-1",
      adapterType: "model_api",
      sandboxCwd: null,
      targetFormat: "generic",
      workspacePath: null,
    });

    expect(result).toMatchObject({
      runtime_prompt: expect.stringContaining(
        "[Personal context granted for this run - reasoning only]",
      ),
      context_snapshot_id: "snapshot-1",
      context_rendered: false,
    });
    expect(repo.accesses).toHaveLength(1);
    expect(repo.accesses[0]).toMatchObject({
      spaceId: "space-1",
      userId: "user-1",
      agentId: "agent-1",
      runId: "run-1",
      reason: "run_execution:run-1",
    });

    const snapshot = repo.snapshots[0]!;
    expect(snapshot.compiledPrefixText).toContain("[system_prompt]");
    expect(snapshot.compiledPrefixText).toContain("The user prefers concise plans.");
    expect(snapshot.compiledTailText).toContain("[prompt]\nDo the work");
    expect(snapshot.compiledTailText).toContain(
      "[evidence:evidence-1:Evidence]\nRelevant linked evidence.",
    );
    expect(snapshot.includedEvidenceRefs).toContainEqual(
      expect.objectContaining({
        source_type: "evidence",
        source_id: "evidence-1",
        link_id: "evidence-link-1",
      }),
    );
    expect(snapshot.retrievalTrace[0]).toMatchObject({
      evidence_selection: {
        selected_count: 1,
        selection_owner: "ts_context_prepare",
        selection_status: "selected",
      },
    });
    expect(snapshot.tokenEstimate).toBeGreaterThan(0);
    expect(snapshot.sourceRefs).toContainEqual(
      expect.objectContaining({
        source_type: "personal_memory_grant",
        grant_id: "grant-1",
        raw_memory_included: false,
        personal_summary_persisted: false,
      }),
    );
    expect(JSON.stringify(snapshot.sourceRefs)).not.toContain(
      "The user has 1 relevant personal memory entry",
    );
    expect(snapshot.retrievalTrace[0]).toMatchObject({
      personal_memory_grant: {
        grant_id: "grant-1",
        raw_memory_included: false,
        personal_summary_persisted: false,
      },
    });
    expect(repo.runMarkers).toHaveLength(1);
  });

  it("records active digest source refs when a digest is available", async () => {
    const repo = new FakeContextRepo();
    const digest: ContextDigestRow = {
      id: "digest-1",
      digest_type: "policy_bundle",
      version: 3,
      status: "active",
      content: "Digest content",
      source_memory_ids_json: ["mem-1"],
      source_policy_ids_json: ["policy-1"],
      source_relation_ids_json: [],
      source_hash: "source-hash",
      content_hash: "content-hash",
    };
    repo.digest = { policy_bundle: digest, workspace: null, agent: null };

    await new ContextPrepareService(config(), repo).prepare({
      runId: "run-1",
      spaceId: "space-1",
      adapterType: "model_api",
      sandboxCwd: null,
      targetFormat: "generic",
      workspacePath: null,
    });

    expect(repo.snapshots[0]?.compiledPrefixText).toContain(
      "[digest:policy_bundle:v3]",
    );
    expect(repo.snapshots[0]?.sourceRefs).toContainEqual(
      expect.objectContaining({
        source_type: "context_digest",
        source_id: "digest-1",
        digest_version: 3,
      }),
    );
    expect(repo.snapshots[0]?.policyBundleVersion).toBe("3");
  });
});

describe("ContextCompiler", () => {
  it("writes vendor files to the sandbox and refuses the real workspace", async () => {
    const root = await mkdtemp(join(tmpdir(), "aspace-context-"));
    const workspace = join(root, "workspace");
    const sandbox = join(root, "sandbox");
    await mkdir(join(workspace, ".agent"), { recursive: true });
    await mkdir(sandbox, { recursive: true });

    const compiler = new ContextCompiler();
    const compiled = await compiler.compile({
      target: "codex_cli",
      taskGoal: "Do the task",
      sandboxDir: sandbox,
      workspacePath: workspace,
      context: {
        user_memory: [serializeMemoryRow(memory(), "user-1")],
        workspace_memory: [],
        capability_memory: [],
        agent_memory: [],
        system_policy: [],
        recent_session_summary: [],
        relevant_episodes: [],
        evidence_items: [],
        attachments: [],
        active_policies: [],
        stable_prefix_refs: [],
        dynamic_tail_refs: [],
        source_refs: [],
        retrieval_trace: {},
        token_budget: {},
        personal_context_block: "",
      },
    });

    expect(compiled.instruction_file_path).toBe(join(sandbox, "AGENTS.md"));
    await expect(stat(join(sandbox, "AGENTS.md"))).resolves.toBeTruthy();
    await expect(stat(join(workspace, "AGENTS.md"))).rejects.toThrow();
    await expect(readFile(join(sandbox, "AGENTS.md"), "utf8")).resolves.toContain(
      "Do the task",
    );

    await expect(
      compiler.compile({
        target: "codex_cli",
        taskGoal: "Nope",
        sandboxDir: workspace,
        workspacePath: workspace,
        context: {
          user_memory: [],
          workspace_memory: [],
          capability_memory: [],
          agent_memory: [],
          system_policy: [],
          recent_session_summary: [],
          relevant_episodes: [],
          evidence_items: [],
          attachments: [],
          active_policies: [],
          stable_prefix_refs: [],
          dynamic_tail_refs: [],
          source_refs: [],
          retrieval_trace: {},
          token_budget: {},
          personal_context_block: "",
        },
      }),
    ).rejects.toThrow(/refuses to write/);
  });
});
