import { describe, expect, it } from "vitest";
import {
  ContextBuildRequestSchema,
  ContextBuildResultSchema,
  ContextCompileRequestSchema,
  ContextCompileResultSchema,
  ContextEngineEventSchema,
  ContextPackageSchema,
  ContextSnapshotAuditSchema,
  ContextSnapshotItemAuditSchema,
  ChatContextCandidateItemSchema,
  ChatContextCandidatesRequestSchema,
  ChatContextCandidatesResultSchema,
  ChatRunCreateRequestSchema,
  ChatRunCreateResultSchema,
  ChatTurnPrepareRunRequestSchema,
  ChatTurnPrepareRunResultSchema,
  ChatTurnRequestSchema,
  ChatTurnResultSchema,
  MemorySearchRequestSchema,
  MemoryPageSchema,
  MemoryOutSchema,
  MemoryProposalCommandSchema,
  MemoryProposalCreateResultSchema,
  MemoryReadRequestSchema,
  MemoryReadTraceSchema,
  MessageCreateRequestSchema,
  MessageOutSchema,
  SessionCreateRequestSchema,
  SessionOutSchema,
  SessionPageSchema,
  SessionSummaryForContextSchema,
  SessionSummaryGetLatestRequestSchema,
  SessionSummaryGetLatestResultSchema,
} from "../src/index";

describe("memory + sessions contracts", () => {
  const memory = {
    id: "memory-1",
    space_id: "space-1",
    subject_user_id: null,
    owner_user_id: "user-1",
    workspace_id: null,
    scope: "user",
    namespace: "default",
    type: "fact",
    title: "Remember",
    content: "content",
    status: "active",
    visibility: "private",
    sensitivity_level: "normal",
    selected_user_ids: null,
    last_confirmed_at: null,
    confidence: 0.9,
    importance: 0.8,
    source_id: null,
    created_by: "user-1",
    created_at: "2026-06-14T10:00:00.000Z",
    updated_at: "2026-06-14T10:00:00.000Z",
    deleted_at: null,
    version: 1,
    tags: [],
    memory_layer: "semantic",
    memory_kind: null,
    source_trust: "user_confirmed",
    created_from_proposal_id: "proposal-1",
    root_memory_id: null,
    supersedes_memory_id: null,
    project_id: null,
  };

  it("parses current session and message DTOs", () => {
    const session = SessionOutSchema.parse({
      id: "session-1",
      space_id: "space-1",
      user_id: "user-1",
      workspace_id: null,
      title: "Assistant chat",
      status: "active",
      created_at: "2026-06-14T10:00:00.000Z",
      updated_at: "2026-06-14T10:01:00.000Z",
    });
    expect(session.id).toBe("session-1");
    expect(
      SessionPageSchema.parse({
        items: [session],
        total: 1,
        limit: 50,
        offset: 0,
      }).items,
    ).toHaveLength(1);

    expect(
      MessageOutSchema.parse({
        id: "message-1",
        session_id: "session-1",
        space_id: "space-1",
        user_id: "user-1",
        role: "user",
        content: "hello",
        metadata_json: null,
        created_at: "2026-06-14T10:00:01.000Z",
      }).content,
    ).toBe("hello");
  });

  it("parses current session and message write requests", () => {
    expect(
      SessionCreateRequestSchema.parse({
        title: "New chat",
        metadata: { source: "ui" },
      }).title,
    ).toBe("New chat");
    expect(
      MessageCreateRequestSchema.parse({
        role: "user",
        content: "hello",
      }).role,
    ).toBe("user");
  });

  it("parses memory DTOs without exposing secret response fields", () => {
    expect(MemoryOutSchema.parse(memory).id).toBe("memory-1");

    expect(() =>
      MemoryOutSchema.parse({
        id: "memory-1",
        space_id: "space-1",
        scope: "user",
        type: "fact",
        status: "active",
        visibility: "private",
        sensitivity_level: "normal",
        confidence: 1,
        importance: 1,
        created_at: "2026-06-14T10:00:00.000Z",
        updated_at: "2026-06-14T10:00:00.000Z",
        deleted_at: null,
        version: 1,
        secret_ref: "must-not-leak",
      }),
    ).toThrow();
  });

  it("parses the session summary context DTO", () => {
    const parsed = SessionSummaryForContextSchema.parse({
      id: "summary-1",
      session_id: "session-1",
      version: 1,
      summary_text: "Session with one message.",
      condenser_version: "pattern.v1",
    });
    expect(parsed.version).toBe(1);
  });

  it("parses session-summary lookup request and result bodies", () => {
    expect(
      SessionSummaryGetLatestRequestSchema.parse({
        session_id: "session-1",
        space_id: "space-1",
      }).session_id,
    ).toBe("session-1");
    expect(
      SessionSummaryGetLatestResultSchema.parse({
        summary: {
          id: "summary-1",
          session_id: "session-1",
          version: 1,
          summary_text: "Session summary.",
          condenser_version: "pattern.v1",
        },
      }).summary?.id,
    ).toBe("summary-1");
  });

  it("parses chat-turn request/result and prepare-run contracts", () => {
    expect(
      ChatTurnRequestSchema.parse({
        message: "  hello  ",
        session_id: "session-1",
      }).message,
    ).toBe("hello");
    expect(
      ChatTurnResultSchema.parse({
        session_id: "session-1",
        run_id: "run-1",
        ok: true,
        reply: "hi",
      }).reply,
    ).toBe("hi");
    expect(
      ChatTurnPrepareRunRequestSchema.parse({
        agent_id: "agent-1",
        space_id: "space-1",
        user_id: "user-1",
        session_id: "session-1",
        message: "hello",
      }).agent_id,
    ).toBe("agent-1");
    expect(
      ChatTurnPrepareRunResultSchema.parse({
        session_id: "session-1",
        run_id: "run-1",
      }).run_id,
    ).toBe("run-1");
  });

  it("parses memory proposal commands and proposal-create result bodies", () => {
    expect(
      MemoryProposalCommandSchema.parse({
        operation: "create",
        title: "Remember this",
        content: "The user prefers concise summaries.",
        type: "preference",
        scope: "user",
        namespace: "user.default",
        visibility: "private",
        sensitivity_level: "normal",
        actor_user_id: "user-1",
        provenance_entries: [
          {
            source_type: "user_confirmation",
            evidence: { method: "POST", path: "/memory" },
          },
        ],
      }).operation,
    ).toBe("create");
    expect(
      MemoryProposalCommandSchema.parse({
        operation: "update",
        target_memory_id: "memory-1",
        title: "Updated title",
      }).operation,
    ).toBe("update");
    expect(
      MemoryProposalCommandSchema.parse({
        operation: "archive",
        target_memory_id: "memory-1",
      }).operation,
    ).toBe("archive");
    expect(
      MemoryProposalCreateResultSchema.parse({
        proposal_id: "proposal-1",
        proposal_type: "memory_create",
        status: "pending",
      }).proposal_type,
    ).toBe("memory_create");
  });

  it("parses memory read requests, pages, and access-log audit rows", () => {
    expect(
      MemoryReadRequestSchema.parse({
        space_id: "space-1",
        user_id: "user-1",
        query: "preference",
      }).limit,
    ).toBe(50);
    expect(
      MemoryPageSchema.parse({
        items: [memory],
        total: 1,
        limit: 50,
        offset: 0,
      }).items[0].id,
    ).toBe("memory-1");
    expect(
      MemoryReadTraceSchema.parse({
        id: "trace-1",
        space_id: "space-1",
        memory_id: "memory-1",
        user_id: "user-1",
        agent_id: null,
        run_id: "run-1",
        access_type: "context_injection",
        reason: "context.build",
        accessed_at: "2026-06-14T10:00:00.000Z",
      }).access_type,
    ).toBe("context_injection");
  });

  it("parses context build and package contracts", () => {
    const contextPackage = ContextPackageSchema.parse({
      user_memory: [memory],
      recent_session_summary: [
        {
          id: "summary-1",
          session_id: "session-1",
          version: 1,
          summary_text: "Summary.",
          condenser_version: "pattern.v1",
        },
      ],
      evidence_items: [
        {
          id: "evidence-1",
          title: "Evidence",
          trust_level: "high",
        },
      ],
      source_refs: [
        {
          source_type: "memory",
          source_id: "memory-1",
          section: "dynamic_tail",
        },
      ],
      retrieval_trace: { memory_count: 1 },
      token_budget: { max_tokens: 4000 },
    });
    expect(contextPackage.user_memory).toHaveLength(1);

    expect(
      ContextBuildRequestSchema.parse({
        space_id: "space-1",
        user_id: "user-1",
        session_id: "session-1",
        query: "What matters now?",
      }).space_id,
    ).toBe("space-1");
    expect(
      ContextBuildResultSchema.parse({
        package: contextPackage,
        context_snapshot_id: "snapshot-1",
        memory_read_traces: [
          {
            id: "trace-1",
            space_id: "space-1",
            memory_id: "memory-1",
            user_id: "user-1",
            agent_id: null,
            run_id: "run-1",
            access_type: "context_injection",
            reason: null,
            accessed_at: "2026-06-14T10:00:00.000Z",
          },
        ],
      }).context_snapshot_id,
    ).toBe("snapshot-1");
  });

  it("parses context compile request and result contracts", () => {
    const contextPackage = ContextPackageSchema.parse({
      user_memory: [memory],
    });
    expect(
      ContextCompileRequestSchema.parse({
        space_id: "space-1",
        target: "codex_cli",
        task_goal: "Help with the migration.",
        context_package: contextPackage,
        budget_chars: 12000,
      }).target,
    ).toBe("codex_cli");
    expect(
      ContextCompileResultSchema.parse({
        target: "codex_cli",
        task_prompt: "Help with the migration.",
        instruction_file_path: "AGENTS.md",
        total_chars: 1200,
        budget_chars: 12000,
        dropped_sections: [],
        budget_trace: { mandatory_chars: 1200 },
      }).total_chars,
    ).toBe(1200);
  });

  it("parses context snapshot/item audit rows without raw rendered context", () => {
    expect(
      ContextSnapshotAuditSchema.parse({
        id: "snapshot-1",
        space_id: "space-1",
        source_refs_json: [
          {
            source_type: "session_summary",
            source_id: "summary-1",
          },
        ],
        token_estimate: 123,
        relevant_period_start: null,
        relevant_period_end: null,
        prefix_hash: "prefix",
        tail_hash: "tail",
        compiler_version: "context_compiler.v1",
        retrieval_trace_json: [{ stage: "memory" }],
        token_budget_json: { max_tokens: 4000 },
        execution_plane_id: null,
        redactions_json: { count: 0 },
        data_exposure_level: "model_provider",
        rendered_context_uri: null,
        has_compiled_prefix_text: true,
        has_compiled_tail_text: true,
        has_rendered_context_text: false,
        created_at: "2026-06-14T10:00:00.000Z",
      }).has_compiled_prefix_text,
    ).toBe(true);

    expect(
      ContextSnapshotItemAuditSchema.parse({
        id: "item-1",
        context_snapshot_id: "snapshot-1",
        item_type: "memory",
        item_id: "memory-1",
        title: "Remember",
        excerpt: "short excerpt",
        score: 0.9,
        reason: "semantic match",
        token_count: 12,
        metadata_json: { section: "dynamic_tail" },
        created_at: "2026-06-14T10:00:00.000Z",
      }).item_type,
    ).toBe("memory");

    expect(() =>
      ContextSnapshotAuditSchema.parse({
        id: "snapshot-1",
        space_id: "space-1",
        source_refs_json: [],
        rendered_context_text: "raw prompt must not be part of audit DTO",
        created_at: "2026-06-14T10:00:00.000Z",
      }),
    ).toThrow();
  });

  it("parses context engine events and rejects unsafe event metadata", () => {
    expect(
      ContextEngineEventSchema.parse({
        event_type: "context.memory_selected",
        space_id: "space-1",
        session_id: "session-1",
        run_id: "run-1",
        context_snapshot_id: "snapshot-1",
        status: "succeeded",
        metadata_json: { selected_count: 2 },
        created_at: "2026-06-14T10:00:00.000Z",
      }).event_type,
    ).toBe("context.memory_selected");

    expect(() =>
      ContextEngineEventSchema.parse({
        event_type: "context.build_completed",
        space_id: "space-1",
        status: "succeeded",
        metadata_json: { rendered_context: "raw context must not be logged" },
        created_at: "2026-06-14T10:00:00.000Z",
      }),
    ).toThrow();
  });

  it("parses chat context-candidate port request and result", () => {
    ChatContextCandidatesRequestSchema.parse({
      agent_id: "agent-1",
      space_id: "space-1",
      user_id: "user-1",
      session_id: "session-1",
      message: "hello",
    });
    const result = ChatContextCandidatesResultSchema.parse({
      allowed_sources: ["memory", "knowledge_item"],
      max_tokens: 4000,
      max_items: 20,
      context_policy_applied: true,
      items: [
        {
          item_type: "memory",
          item_id: "memory-1",
          title: "A memory",
          excerpt: "excerpt text",
          score: 0.8,
          reason: "approved_memory",
          token_count: 3,
        },
      ],
    });
    expect(result.items[0].metadata).toEqual({});
    expect(result.context_policy_applied).toBe(true);
  });

  it("rejects secret-bearing chat candidate metadata", () => {
    expect(() =>
      ChatContextCandidateItemSchema.parse({
        item_type: "manual_context",
        reason: "explicit_selection",
        metadata: { secret_ref: "ref-1" },
      }),
    ).toThrow();
  });

  it("parses the memory search request with defaults", () => {
    const req = MemorySearchRequestSchema.parse({ query: "ts migration" });
    expect(req.limit).toBe(10);
    expect(req.query).toBe("ts migration");
    const full = MemorySearchRequestSchema.parse({
      query: "x",
      scope: "user",
      type: "fact",
      limit: 5,
      space_id: "space-1",
      user_id: "user-1",
      workspace_id: "ws-1",
    });
    expect(full.type).toBe("fact");
  });

  it("parses chat run-create port request and result", () => {
    ChatRunCreateRequestSchema.parse({
      agent_id: "agent-1",
      space_id: "space-1",
      user_id: "user-1",
      session_id: "session-1",
      prompt: "context preamble\n\nhello",
    });
    const result = ChatRunCreateResultSchema.parse({
      run_id: "run-1",
      context_snapshot_id: "snapshot-1",
    });
    expect(result.run_id).toBe("run-1");
  });
});
