const STRUCTURED_OUTPUT_PROVIDER_TYPES = new Set([
  "openai",
  "openrouter",
  "other",
  "anthropic",
  "ollama",
]);

export function providerSupportsStructuredOutput(providerType: string): boolean {
  return STRUCTURED_OUTPUT_PROVIDER_TYPES.has(providerType);
}

/**
 * Models whose OpenAI-compatible gateway corrupts forced tool-call arguments
 * (MiniMax: XML round-trip stringifies scalars, wraps arrays in `item`, and
 * hoists array-element fragments to the top level). For these, structured
 * output goes through response_format plus prompt constraints only; the text
 * normalization pipeline handles reasoning envelopes and fences.
 */
const STRUCTURED_TOOL_CALL_UNRELIABLE_MODELS: RegExp[] = [/(^|\/)minimax/i];

export function modelStructuredToolCallUnreliable(model: string | null | undefined): boolean {
  if (typeof model !== "string" || !model.trim()) return false;
  const trimmed = model.trim();
  return STRUCTURED_TOOL_CALL_UNRELIABLE_MODELS.some((pattern) => pattern.test(trimmed));
}
