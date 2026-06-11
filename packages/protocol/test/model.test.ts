/**
 * Canonical model contract tests — request/message/usage shapes and the
 * streaming event union. Contracts only: these verify shapes parse/reject,
 * not any client behaviour (none exists in this package).
 */

import { describe, it, expect } from "vitest";
import {
  CanonicalMessageSchema,
  CanonicalModelEventSchema,
  CanonicalModelRequestSchema,
  CanonicalUsageSchema,
  isModelRole,
  ModelEventType,
  type CanonicalModelEvent,
} from "../src/index";

describe("canonical model request", () => {
  it("parses a minimal request and a tool-bearing request", () => {
    expect(
      CanonicalModelRequestSchema.parse({
        model: "claude-sonnet-4-6",
        messages: [{ role: "user", content: "hi" }],
      }).model,
    ).toBe("claude-sonnet-4-6");

    const withTools = CanonicalModelRequestSchema.parse({
      model: "gpt-4o",
      messages: [
        { role: "system", content: "be helpful" },
        {
          role: "assistant",
          content: null,
          tool_calls: [{ id: "c1", name: "search", arguments_json: '{"q":"x"}' }],
        },
        { role: "tool", content: "result", tool_call_id: "c1", name: "search" },
      ],
      tools: [{ name: "search", description: "find things", input_schema: { type: "object" } }],
      max_tokens: 1024,
      stream: true,
    });
    expect(withTools.messages).toHaveLength(3);
  });

  it("rejects an empty message list and a missing model", () => {
    expect(CanonicalModelRequestSchema.safeParse({ model: "m", messages: [] }).success).toBe(
      false,
    );
    expect(
      CanonicalModelRequestSchema.safeParse({ messages: [{ role: "user", content: "x" }] })
        .success,
    ).toBe(false);
  });

  it("keeps role permissive but exports the documented value guard", () => {
    expect(
      CanonicalMessageSchema.safeParse({ role: "future_role", content: "x" }).success,
    ).toBe(true);
    expect(isModelRole("assistant")).toBe(true);
    expect(isModelRole("future_role")).toBe(false);
  });
});

describe("canonical usage", () => {
  it("mirrors the Python facade field names and allows partial reporting", () => {
    expect(
      CanonicalUsageSchema.parse({ input_tokens: 10, output_tokens: 5, total_tokens: 15 }),
    ).toEqual({ input_tokens: 10, output_tokens: 5, total_tokens: 15 });
    expect(CanonicalUsageSchema.parse({})).toEqual({});
    expect(CanonicalUsageSchema.safeParse({ input_tokens: -1 }).success).toBe(false);
  });
});

describe("canonical model stream events", () => {
  it("parses every event variant through the discriminated union", () => {
    const events: CanonicalModelEvent[] = [
      { type: ModelEventType.MessageStart, model: "claude-sonnet-4-6" },
      { type: ModelEventType.TextDelta, delta: "Hel" },
      { type: ModelEventType.ToolCallDelta, index: 0, id: "c1", name: "search" },
      { type: ModelEventType.ToolCallDelta, index: 0, arguments_delta: '{"q":' },
      { type: ModelEventType.Usage, usage: { input_tokens: 10, output_tokens: 5 } },
      { type: ModelEventType.MessageStop, finish_reason: "stop" },
      { type: ModelEventType.Error, error: { code: "provider_error", message: "boom" } },
    ];
    for (const event of events) {
      expect(CanonicalModelEventSchema.parse(event)).toEqual(event);
    }
  });

  it("rejects unknown event types and malformed payloads", () => {
    expect(
      CanonicalModelEventSchema.safeParse({ type: "model.unknown", delta: "x" }).success,
    ).toBe(false);
    expect(
      CanonicalModelEventSchema.safeParse({ type: ModelEventType.TextDelta }).success,
    ).toBe(false);
    expect(
      CanonicalModelEventSchema.safeParse({
        type: ModelEventType.Error,
        error: { code: "x" },
      }).success,
    ).toBe(false);
  });
});
