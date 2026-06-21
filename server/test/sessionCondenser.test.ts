import { describe, expect, it } from "vitest";
import {
  buildCondensePrompt,
  buildLlmSummary,
  buildPatternSummary,
  LLM_CONDENSER_VERSION,
  resolveCondenserProfile,
  SESSION_CONDENSER_VERSION,
  type CondenserMessage,
} from "../src/modules/sessions/condenser";

function message(id: string, role: string, content: string): CondenserMessage {
  return { id, role, content };
}

describe("buildPatternSummary (pattern.v1)", () => {
  it("returns null when no message has content", () => {
    expect(buildPatternSummary([])).toBeNull();
    expect(
      buildPatternSummary([message("m-1", "user", "   "), message("m-2", "assistant", "")]),
    ).toBeNull();
  });

  it("is a pure function of its input", () => {
    const input = [
      message("m-1", "user", "How do I deploy the server safely?"),
      message("m-2", "assistant", "Use the compose deploy command."),
      message("m-3", "user", "What about database backups?"),
    ];
    expect(buildPatternSummary(input)).toEqual(buildPatternSummary(input));
  });

  it("captures role counts, keywords, range and token estimates", () => {
    const body = buildPatternSummary([
      message("m-1", "user", "deploy deploy deploy the server"),
      message("m-2", "assistant", "backup database backup"),
      message("m-3", "user", "deploy database again"),
    ]);
    expect(body).not.toBeNull();
    expect(body!.source_first_message_id).toBe("m-1");
    expect(body!.source_last_message_id).toBe("m-3");
    expect(body!.source_message_count).toBe(3);
    expect(body!.token_estimate_before).toBeGreaterThan(0);
    expect(body!.token_estimate_after).toBeGreaterThan(0);

    const json = body!.summary_json as {
      condenser_version: string;
      role_counts: Record<string, number>;
      top_keywords: string[];
      source_range: { message_count: number };
    };
    expect(json.condenser_version).toBe(SESSION_CONDENSER_VERSION);
    expect(json.role_counts).toEqual({ user: 2, assistant: 1 });
    expect(json.source_range.message_count).toBe(3);
    // "deploy" is the most frequent non-stopword token.
    expect(json.top_keywords[0]).toBe("deploy");
    expect(json.top_keywords).toContain("database");
  });

  it("renders a readable summary header and highlights", () => {
    const body = buildPatternSummary([
      message("m-1", "user", "First question about the roadmap"),
      message("m-2", "assistant", "Answer about the roadmap"),
    ]);
    expect(body!.summary_text).toContain("Earlier conversation condensed (2 messages");
    expect(body!.summary_text).toContain("1 from user");
    expect(body!.summary_text).toContain("Highlights:");
    expect(body!.summary_text).toContain("- user: First question about the roadmap");
  });

  it("truncates long highlight content", () => {
    const long = "x".repeat(400);
    const body = buildPatternSummary([message("m-1", "user", long)]);
    const highlightLine = body!.summary_text
      .split("\n")
      .find((line) => line.startsWith("- user:"));
    expect(highlightLine).toBeDefined();
    expect(highlightLine!.endsWith("…")).toBe(true);
    expect(highlightLine!.length).toBeLessThan(long.length);
  });
});

describe("resolveCondenserProfile", () => {
  it("accepts known profiles and defaults unknown/empty to adaptive", () => {
    expect(resolveCondenserProfile("coding")).toBe("coding");
    expect(resolveCondenserProfile("project")).toBe("project");
    expect(resolveCondenserProfile("general")).toBe("general");
    expect(resolveCondenserProfile("adaptive")).toBe("adaptive");
    expect(resolveCondenserProfile("nonsense")).toBe("adaptive");
    expect(resolveCondenserProfile(null)).toBe("adaptive");
    expect(resolveCondenserProfile(undefined)).toBe("adaptive");
  });
});

describe("buildCondensePrompt", () => {
  const turns = [
    message("m-1", "user", "deploy the server"),
    message("m-2", "assistant", "use compose"),
  ];

  it("always enforces factual + same-language rules and includes the transcript", () => {
    const prompt = buildCondensePrompt({ messages: turns });
    expect(prompt.system).toContain("strictly factual");
    expect(prompt.system).toContain("same language as the conversation");
    expect(prompt.user).toContain("user: deploy the server");
    expect(prompt.user).toContain("assistant: use compose");
  });

  it("selects scenario-specific instructions per profile", () => {
    expect(buildCondensePrompt({ profile: "coding", messages: turns }).system).toContain(
      "coding assistant",
    );
    expect(buildCondensePrompt({ profile: "coding", messages: turns }).user).toContain(
      "completed steps vs. remaining steps",
    );
    expect(buildCondensePrompt({ profile: "project", messages: turns }).user).toContain(
      "project objective",
    );
    // Unknown profile falls back to the adaptive default.
    const adaptive = buildCondensePrompt({ profile: "nope", messages: turns });
    expect(adaptive.user).toContain("When the conversation involves coding or a project");
  });

  it("uses per-agent custom prompt overrides while keeping shared guardrails", () => {
    const prompt = buildCondensePrompt({
      config: {
        profile: "coding",
        custom_system: "Summarize for this specific agent.",
        custom_instructions: "Preserve only goals, decisions, and next actions.",
      },
      messages: turns,
    });

    expect(prompt.system).toContain("Summarize for this specific agent.");
    expect(prompt.system).toContain("strictly factual");
    expect(prompt.system).toContain("same language as the conversation");
    expect(prompt.system).not.toContain("coding assistant");
    expect(prompt.user).toContain("Preserve only goals, decisions, and next actions.");
    expect(prompt.user).not.toContain("completed steps vs. remaining steps");
    expect(prompt.user).toContain("user: deploy the server");
  });

  it("switches to incremental update mode when a prior summary is given", () => {
    const prompt = buildCondensePrompt({
      priorSummary: "User wants to deploy.",
      messages: turns,
    });
    expect(prompt.user).toContain("Existing summary:");
    expect(prompt.user).toContain("User wants to deploy.");
    expect(prompt.user).toContain("New turns:");
  });
});

describe("buildLlmSummary", () => {
  it("wraps LLM text as llm.v1 with source range from the covered slice", () => {
    const body = buildLlmSummary(
      [
        message("m-1", "user", "first"),
        message("m-2", "assistant", "second"),
      ],
      "  The user is setting up deployment.  ",
    );
    expect(body).not.toBeNull();
    expect(body!.condenser_version).toBe(LLM_CONDENSER_VERSION);
    expect(body!.summary_text).toBe("The user is setting up deployment.");
    expect(body!.source_first_message_id).toBe("m-1");
    expect(body!.source_last_message_id).toBe("m-2");
    expect(body!.source_message_count).toBe(2);
  });

  it("returns null for empty LLM text so the caller falls back to pattern.v1", () => {
    expect(buildLlmSummary([message("m-1", "user", "hi")], "   ")).toBeNull();
    expect(buildLlmSummary([], "anything")).toBeNull();
  });
});
