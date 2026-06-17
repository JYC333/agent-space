import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { readClaudeTokenUsage, readCodexTokenUsage } from "../src/modules/providers";

let tempDir: string | undefined;

afterEach(async () => {
  if (tempDir) await rm(tempDir, { recursive: true, force: true });
  tempDir = undefined;
});

function assistantLine(opts: {
  model: string;
  id?: string;
  requestId?: string;
  input?: number;
  output?: number;
  cacheWrite?: number;
  cacheRead?: number;
}): string {
  return JSON.stringify({
    type: "assistant",
    requestId: opts.requestId,
    message: {
      id: opts.id,
      role: "assistant",
      model: opts.model,
      usage: {
        input_tokens: opts.input ?? 0,
        output_tokens: opts.output ?? 0,
        cache_creation_input_tokens: opts.cacheWrite ?? 0,
        cache_read_input_tokens: opts.cacheRead ?? 0,
      },
    },
  });
}

describe("readClaudeTokenUsage", () => {
  it("sums usage across transcripts, dedupes replayed messages, and estimates cost", async () => {
    tempDir = await mkdtemp(join(tmpdir(), "aspace-usage-"));
    const proj = join(tempDir, "projects", "-app-server");
    await mkdir(proj, { recursive: true });

    await writeFile(
      join(proj, "session-a.jsonl"),
      [
        // a user line (no usage) is ignored
        JSON.stringify({ type: "user", message: { role: "user", content: "hi" } }),
        assistantLine({ model: "claude-sonnet-4-6", id: "m1", requestId: "r1", input: 1000, output: 500, cacheRead: 2000 }),
        assistantLine({ model: "claude-opus-4-8", id: "m2", requestId: "r2", input: 100, output: 50 }),
        "not json — must be skipped",
        "",
      ].join("\n"),
    );
    await writeFile(
      join(proj, "session-b.jsonl"),
      [
        // replay of m1/r1 from a resumed session — must not double count
        assistantLine({ model: "claude-sonnet-4-6", id: "m1", requestId: "r1", input: 1000, output: 500, cacheRead: 2000 }),
        assistantLine({ model: "claude-haiku-4-5", id: "m3", requestId: "r3", input: 10, output: 5, cacheWrite: 40 }),
      ].join("\n"),
    );

    const usage = await readClaudeTokenUsage(tempDir);

    expect(usage.available).toBe(true);
    expect(usage.source).toBe("transcripts");
    expect(usage.message_count).toBe(3); // m1 (once), m2, m3
    expect(usage.session_count).toBe(2);
    expect(usage.input_tokens).toBe(1000 + 100 + 10);
    expect(usage.output_tokens).toBe(500 + 50 + 5);
    expect(usage.cache_read_input_tokens).toBe(2000);
    expect(usage.cache_creation_input_tokens).toBe(40);

    // cost = sonnet(1000 in@3 + 500 out@15 + 2000 cacheRead@0.3)/1e6
    //      + opus(100 in@15 + 50 out@75)/1e6
    //      + haiku(10 in@0.8 + 5 out@4 + 40 cacheWrite@1.0)/1e6
    const expected =
      (1000 * 3 + 500 * 15 + 2000 * 0.3) / 1e6 +
      (100 * 15 + 50 * 75) / 1e6 +
      (10 * 0.8 + 5 * 4 + 40 * 1.0) / 1e6;
    expect(usage.cost_usd).toBeCloseTo(Math.round(expected * 1e6) / 1e6, 9);
  });

  it("returns an unavailable (not error) result when no transcripts exist", async () => {
    tempDir = await mkdtemp(join(tmpdir(), "aspace-usage-"));
    const usage = await readClaudeTokenUsage(tempDir);
    expect(usage.available).toBe(false);
    expect(usage.source).toBe("transcripts");
    expect(usage.input_tokens).toBe(0);
    expect(usage.message_count).toBe(0);
  });

  it("reads transcripts under sessions/ as well as projects/", async () => {
    tempDir = await mkdtemp(join(tmpdir(), "aspace-usage-"));
    const sess = join(tempDir, "sessions");
    await mkdir(sess, { recursive: true });
    await writeFile(join(sess, "s.jsonl"), assistantLine({ model: "claude-sonnet-4-6", id: "x", input: 7, output: 3 }));
    const usage = await readClaudeTokenUsage(tempDir);
    expect(usage.available).toBe(true);
    expect(usage.input_tokens).toBe(7);
    expect(usage.output_tokens).toBe(3);
  });
});

function codexLine(value: Record<string, unknown>): string {
  return JSON.stringify(value);
}

describe("readCodexTokenUsage", () => {
  it("sums Codex token_count deltas from sessions and estimates cost", async () => {
    tempDir = await mkdtemp(join(tmpdir(), "aspace-codex-usage-"));
    const day = join(tempDir, "sessions", "2026", "06", "14");
    await mkdir(day, { recursive: true });
    const model = "openai/gpt-5.2-codex";

    await writeFile(
      join(day, "session.jsonl"),
      [
        codexLine({
          type: "turn_context",
          payload: { model },
        }),
        codexLine({
          type: "event_msg",
          payload: {
            type: "token_count",
            info: {
              model,
              total_token_usage: {
                input_tokens: 100,
                cached_input_tokens: 20,
                output_tokens: 10,
              },
            },
          },
        }),
        codexLine({
          type: "event_msg",
          payload: {
            type: "token_count",
            info: {
              model,
              total_token_usage: {
                input_tokens: 160,
                cached_input_tokens: 40,
                output_tokens: 16,
              },
            },
          },
        }),
      ].join("\n"),
    );

    const usage = await readCodexTokenUsage(tempDir);

    expect(usage.available).toBe(true);
    expect(usage.source).toBe("codex_sessions");
    expect(usage.session_count).toBe(1);
    expect(usage.message_count).toBe(2);
    expect(usage.input_tokens).toBe(160);
    expect(usage.cache_read_input_tokens).toBe(40);
    expect(usage.cache_creation_input_tokens).toBe(0);
    expect(usage.output_tokens).toBe(16);

    // gpt-5.2-codex: input $1.75/M, cached input $0.175/M, output $14/M.
    const expected = ((160 - 40) * 1.75 + 40 * 0.175 + 16 * 14) / 1e6;
    expect(usage.cost_usd).toBeCloseTo(Math.round(expected * 1e6) / 1e6, 9);
  });

  it("returns an unavailable Codex-session result when no sessions exist", async () => {
    tempDir = await mkdtemp(join(tmpdir(), "aspace-codex-usage-"));
    const usage = await readCodexTokenUsage(tempDir);
    expect(usage.available).toBe(false);
    expect(usage.source).toBe("codex_sessions");
    expect(usage.input_tokens).toBe(0);
  });
});
