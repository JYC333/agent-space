import { createHash } from "node:crypto";

export function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

export function stableJsonStringify(value: unknown): string {
  return JSON.stringify(canonicalJson(value));
}

export function sha256Json(value: unknown): string {
  return sha256(stableJsonStringify(value));
}

function canonicalJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (!isPlainRecord(value)) return value;

  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) {
    const child = value[key];
    if (child !== undefined) out[key] = canonicalJson(child);
  }
  return out;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
