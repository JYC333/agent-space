/**
 * Recommended max output (completion) tokens for known models.
 *
 * `max_tokens` caps the completion, not the context window. Reasoning models
 * spend their thinking inside the same completion budget, so a small cap
 * silently starves outputs: the model burns the whole budget thinking and is
 * truncated before the answer starts (observed as MiniMax-M3 emitting stub
 * synthesis tool calls under an 8k cap, and refine failing schema validation
 * under 1800). This registry is the single source for per-model output
 * guidance. A recommendation is only a default: an explicit caller budget is
 * part of the run/request contract and must never be widened here.
 */
const MODEL_RECOMMENDED_MAX_OUTPUT_TOKENS: Array<{ pattern: RegExp; maxOutputTokens: number }> = [
  // MiniMax M3 official guidance: recommended max output 131072 (hard cap 524288).
  { pattern: /(^|\/)minimax-m3/i, maxOutputTokens: 131_072 },
];

export function recommendedMaxOutputTokens(model: string | null | undefined): number | null {
  if (typeof model !== "string" || !model.trim()) return null;
  const trimmed = model.trim();
  const match = MODEL_RECOMMENDED_MAX_OUTPUT_TOKENS.find((entry) => entry.pattern.test(trimmed));
  return match?.maxOutputTokens ?? null;
}

/**
 * Effective completion budget for a request. Explicit caller limits always
 * win; model guidance is used only when the caller leaves the budget unset.
 */
export function effectiveMaxOutputTokens(model: string | null | undefined, requested: number | null | undefined): number | null {
  if (requested !== null && requested !== undefined) return requested;
  return recommendedMaxOutputTokens(model);
}
