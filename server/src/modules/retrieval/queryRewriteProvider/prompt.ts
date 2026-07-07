import { QUERY_REWRITE_MAX_VARIANTS, QUERY_REWRITE_MAX_VARIANT_CHARS } from "./config";

/**
 * Prompt construction + response parsing for the LLM query rewriter. The model
 * is asked to produce a few intent-preserving rephrasings of the query (synonyms,
 * expanded acronyms, related terms) as a JSON array of strings. Parsing is
 * defensive — any non-JSON or empty result yields `null`, and the caller then
 * searches the original query alone.
 */

export interface QueryRewritePrompt {
  system: string;
  user: string;
}

export const DEFAULT_QUERY_REWRITE_SYSTEM_PROMPT = [
  "You expand a search query into a few alternative phrasings that preserve the",
  "user's intent: synonyms, expanded acronyms, and closely related terms.",
  "",
  `Respond with ONLY a JSON array of up to ${QUERY_REWRITE_MAX_VARIANTS} short strings,`,
  "e.g. [\"alternative one\", \"alternative two\"].",
  "Do NOT repeat the original query. Do NOT add prose, markdown, or code fences.",
  "If no useful rephrasing exists, return [].",
].join("\n");

export const DEFAULT_QUERY_REWRITE_USER_TEMPLATE = [
  "Query: {query}",
  "",
  "Return the JSON array now.",
].join("\n");

export interface QueryRewritePromptTemplate {
  systemPrompt?: string | null;
  userTemplate?: string | null;
}

export function renderQueryRewriteUserTemplate(template: string, query: string): string {
  return template.replaceAll("{query}", query.trim());
}

export function buildQueryRewritePrompt(
  query: string,
  template: QueryRewritePromptTemplate = {},
): QueryRewritePrompt {
  const system = template.systemPrompt?.trim() || DEFAULT_QUERY_REWRITE_SYSTEM_PROMPT;
  const userTemplate = template.userTemplate?.trim() || DEFAULT_QUERY_REWRITE_USER_TEMPLATE;
  return { system, user: renderQueryRewriteUserTemplate(userTemplate, query) };
}

/**
 * Parse the rewrite JSON. Tolerates surrounding prose/code fences by extracting
 * the outermost array. Keeps only non-empty trimmed strings, truncates overlong
 * ones, dedupes, and caps the count. Returns `null` when nothing usable parses.
 */
export function parseQueryRewriteVariants(text: string): string[] | null {
  const json = extractJsonArray(text);
  if (!json) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return null;
  }
  if (!Array.isArray(parsed)) return null;
  const seen = new Set<string>();
  const variants: string[] = [];
  for (const entry of parsed) {
    if (typeof entry !== "string") continue;
    const trimmed = entry.trim().slice(0, QUERY_REWRITE_MAX_VARIANT_CHARS).trim();
    if (!trimmed) continue;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    variants.push(trimmed);
    if (variants.length >= QUERY_REWRITE_MAX_VARIANTS) break;
  }
  return variants.length ? variants : null;
}

function extractJsonArray(text: string): string | null {
  const start = text.indexOf("[");
  const end = text.lastIndexOf("]");
  if (start < 0 || end <= start) return null;
  return text.slice(start, end + 1);
}
