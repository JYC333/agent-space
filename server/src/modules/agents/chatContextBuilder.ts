/**
 * Chat-path context assembly.
 *
 * Owns the cumulative budget/dedup loop and compact context preamble rendering.
 *
 * Per-source candidate reads (memory/knowledge/source/activity/workspace/project)
 * are produced by the native `ChatContextCandidateCollector`, already excerpted,
 * scored, and token-counted in priority order. This module applies only the
 * cumulative `max_items` / `max_tokens` / dedup selection and builds the audit
 * `retrieval_trace`, so the final selection remains stable over the frozen
 * compatibility fixture (`chat_context_build_contract.json`).
 */

import type {
  ChatContextCandidateItem,
  ChatContextCandidatesResult,
} from "@agent-space/protocol" with { "resolution-mode": "import" };

export interface ChatContextBundle {
  items: ChatContextCandidateItem[];
  token_count: number;
  truncated: boolean;
  retrieval_trace: Record<string, unknown>;
}

/**
 * Apply the cumulative budget/dedup loop over priority-ordered candidates.
 *
 * Scan candidates in order, stop once `max_tokens` or `max_items` is reached,
 * dedup by `(item_type, item_id)` (null-id items are never deduped against each
 * other), and sum `token_count`.
 */
export function buildChatContext(
  candidates: ChatContextCandidatesResult,
): ChatContextBundle {
  const items: ChatContextCandidateItem[] = [];
  const seen = new Set<string>();
  let totalTokens = 0;

  const maxTokens = candidates.max_tokens;
  const maxItems = candidates.max_items;

  candidates.items.forEach((item) => {
    if (totalTokens >= maxTokens || items.length >= maxItems) return;
    // Null/empty item_id falls back to a per-item unique key, so such items
    // never dedup together.
    const key = item.item_id ? `${item.item_type}::${item.item_id}` : null;
    if (key && seen.has(key)) return;
    if (key) seen.add(key);
    items.push(item);
    totalTokens += item.token_count ?? 0;
  });

  // `forEach` cannot break, so the cap is re-checked per item above. Once the
  // cap is hit every later item is skipped.
  const truncated = totalTokens >= maxTokens || items.length >= maxItems;

  return {
    items,
    token_count: totalTokens,
    truncated,
    retrieval_trace: {
      allowed_sources: candidates.allowed_sources,
      context_policy_applied: candidates.context_policy_applied,
      item_count: items.length,
      total_tokens: totalTokens,
      truncated,
      max_tokens: maxTokens,
      max_items: maxItems,
    },
  };
}

/** Compact bullet list of selected items. */
export function renderContextPreamble(
  items: readonly ChatContextCandidateItem[],
): string {
  if (items.length === 0) return "";
  const lines = [
    "[Context from your space — use it if relevant; do not repeat it verbatim.]",
  ];
  for (const it of items) {
    const title = (it.title || it.item_type || "item").trim();
    const excerpt = (it.excerpt || "").trim();
    lines.push(
      excerpt
        ? `- (${it.item_type}) ${title}: ${excerpt}`
        : `- (${it.item_type}) ${title}`,
    );
  }
  return lines.join("\n");
}

/** Compose the runtime prompt: preamble + blank line + message, or just the message. */
export function composeChatPrompt(preamble: string, message: string): string {
  return preamble ? `${preamble}\n\n${message}` : message;
}
