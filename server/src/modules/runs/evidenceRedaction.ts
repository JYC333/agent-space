const FORBIDDEN_EVIDENCE_KEYS = new Set([
  "api_key",
  "secret_ref",
  "encrypted_key",
  "credential_secret_ref",
  "authorization",
  "cookie",
  "access_token",
  "refresh_token",
  "id_token",
  "password",
  "private_key",
  "rendered_context",
  "context_text",
  "private_memory_text",
  "raw_private_memory",
  "raw_memory_text",
  "full_patch",
  "patch",
  "diff",
  "file_content",
  "raw_file_content",
  "stdout",
  "stderr",
]);

const SECRET_VALUE_PATTERNS = [
  /\bsk-[A-Za-z0-9_-]{12,}\b/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b/gi,
  /\b(api[_-]?key|token|password)\s*[:=]\s*["']?[^"',\s}]+/gi,
];

/** Maximum size for persisted free-form evidence text. */
export const MAX_EVIDENCE_TEXT_CHARS = 32_000;

/** Applies only the secret-pattern substitutions, with no length truncation. */
export function redactSecretPatterns(value: string): string {
  let out = value;
  for (const pattern of SECRET_VALUE_PATTERNS) {
    out = out.replace(pattern, "[REDACTED_SECRET]");
  }
  return out;
}

export function redactEvidenceText(value: string | null | undefined): string | null {
  if (value == null) return null;
  const out = redactSecretPatterns(value);
  return out.length > MAX_EVIDENCE_TEXT_CHARS
    ? `${out.slice(0, MAX_EVIDENCE_TEXT_CHARS)}...[truncated]`
    : out;
}

export function sanitizeEvidenceJson(value: unknown): unknown {
  if (value == null) return null;
  if (typeof value === "string") return redactEvidenceText(value);
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) return value.map((item) => sanitizeEvidenceJson(item));
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) {
      if (FORBIDDEN_EVIDENCE_KEYS.has(key.toLowerCase())) {
        out[key] = "[REDACTED_EVIDENCE_FIELD]";
      } else {
        out[key] = sanitizeEvidenceJson(child);
      }
    }
    return out;
  }
  return null;
}

export function sanitizeErrorJson(value: unknown): unknown {
  return sanitizeEvidenceJson(value ?? {});
}
