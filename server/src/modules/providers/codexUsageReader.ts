/**
 * Codex CLI token/cost reader.
 *
 * Codex writes session JSONL files under its CODEX_HOME (`sessions/YYYY/MM/DD`
 * and `archived_sessions`). Following CodexBar's local scanner, we read
 * `event_msg` token_count records, use `turn_context` as the authoritative
 * model marker, and convert cumulative `total_token_usage` records into deltas.
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { unsupportedTokenUsage, type TokenUsage } from "./cliUsageReader";

interface Counts {
  input: number;
  cached: number;
  output: number;
}

interface CodexPricing {
  match: RegExp;
  input: number;
  output: number;
  cacheRead: number;
}

const PER_MILLION = 1_000_000;

// OpenAI list price, USD per 1M tokens. Unknown models still contribute tokens
// but not estimated cost.
const CODEX_PRICING: readonly CodexPricing[] = [
  { match: /^gpt-5(\.1)?-codex$/i, input: 1.25, output: 10, cacheRead: 0.125 },
  { match: /^gpt-5$/i, input: 1.25, output: 10, cacheRead: 0.125 },
  { match: /^gpt-5\.[23]-codex$/i, input: 1.75, output: 14, cacheRead: 0.175 },
  { match: /^gpt-5\.[23]$/i, input: 1.75, output: 14, cacheRead: 0.175 },
];

function emptyCodexUsage(): TokenUsage {
  return { ...unsupportedTokenUsage(), source: "codex_sessions" };
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function normalizeModel(model: string | undefined): string | undefined {
  if (!model) return undefined;
  return model.replace(/^openai\//i, "");
}

function priceFor(model: string | undefined): CodexPricing | null {
  const normalized = normalizeModel(model);
  if (!normalized) return null;
  return CODEX_PRICING.find((p) => p.match.test(normalized)) ?? null;
}

function parseCounts(value: unknown): Counts | null {
  const obj = record(value);
  if (!obj) return null;
  const input = num(obj.input_tokens);
  const cached = num(obj.cached_input_tokens ?? obj.cache_read_input_tokens);
  const output = num(obj.output_tokens);
  if (input === 0 && cached === 0 && output === 0) return null;
  return { input, cached, output };
}

function diffCounts(current: Counts, previous: Counts | null): Counts {
  if (!previous) return current;
  return {
    input: Math.max(0, current.input - previous.input),
    cached: Math.max(0, current.cached - previous.cached),
    output: Math.max(0, current.output - previous.output),
  };
}

function addCost(total: TokenUsage, counts: Counts, model: string | undefined): void {
  const price = priceFor(model);
  if (!price) return;
  const cached = Math.min(counts.cached, counts.input);
  const uncachedInput = Math.max(0, counts.input - cached);
  total.cost_usd +=
    (uncachedInput * price.input + cached * price.cacheRead + counts.output * price.output) /
    PER_MILLION;
}

async function collectJsonl(root: string, depth = 8): Promise<string[]> {
  let entries;
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch {
    return [];
  }
  const files: string[] = [];
  for (const entry of entries) {
    const full = join(root, entry.name);
    if (entry.isDirectory()) {
      if (depth > 0) files.push(...(await collectJsonl(full, depth - 1)));
    } else if (entry.isFile() && entry.name.endsWith(".jsonl")) {
      files.push(full);
    }
  }
  return files;
}

function turnContextModel(payload: Record<string, unknown>): string | undefined {
  const direct = typeof payload.model === "string" ? payload.model : undefined;
  if (direct) return direct;
  const info = record(payload.info);
  return typeof info?.model === "string" ? info.model : undefined;
}

function parseTokenCount(
  payload: Record<string, unknown>,
  previousTotal: Counts | null,
): { counts: Counts | null; total: Counts | null; model: string | undefined } | null {
  if (payload.type !== "token_count") return null;
  const info = record(payload.info);
  if (!info) return null;
  const last = parseCounts(info.last_token_usage);
  const total = parseCounts(info.total_token_usage);
  const counts = last ?? (total ? diffCounts(total, previousTotal) : null);
  const model = typeof info.model === "string" ? info.model : undefined;
  return { counts, total, model };
}

async function readSessionFile(file: string, total: TokenUsage): Promise<boolean> {
  let raw: string;
  try {
    const info = await stat(file);
    if (info.size > 64 * 1024 * 1024) return false;
    raw = await readFile(file, "utf8");
  } catch {
    return false;
  }

  let currentModel: string | undefined;
  let previousTotal: Counts | null = null;
  let contributed = false;

  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    let obj: Record<string, unknown>;
    try {
      obj = JSON.parse(line) as Record<string, unknown>;
    } catch {
      continue;
    }
    const payload = record(obj.payload);
    if (!payload) continue;
    if (obj.type === "turn_context") {
      currentModel = normalizeModel(turnContextModel(payload)) ?? currentModel;
      continue;
    }
    if (obj.type !== "event_msg") continue;
    const parsed = parseTokenCount(payload, previousTotal);
    if (!parsed) continue;
    if (parsed.total) previousTotal = parsed.total;
    if (!parsed.counts) continue;

    const model = normalizeModel(currentModel ?? parsed.model);
    total.input_tokens += parsed.counts.input;
    total.output_tokens += parsed.counts.output;
    total.cache_read_input_tokens += parsed.counts.cached;
    total.message_count += 1;
    contributed = true;
    addCost(total, parsed.counts, model);
  }

  return contributed;
}

export async function readCodexTokenUsage(profileDir: string): Promise<TokenUsage> {
  const roots = [join(profileDir, "sessions"), join(profileDir, "archived_sessions")];
  const files: string[] = [];
  for (const root of roots) files.push(...(await collectJsonl(root)));
  if (files.length === 0) return emptyCodexUsage();

  const total = emptyCodexUsage();
  for (const file of files) {
    if (await readSessionFile(file, total)) total.session_count += 1;
  }

  total.available = total.message_count > 0;
  total.cost_usd = Math.round(total.cost_usd * 1e6) / 1e6;
  return total;
}
