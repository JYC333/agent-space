/**
 * Hybrid-retrieval (Phase 2, step 8) reranking configuration.
 *
 * The reranker is a space-setting-gated, skippable LLM stage. It routes through the same
 * provider task-policy + credential channel (ADR 0010) as the other auxiliary
 * model tasks, under a dedicated task name so a space can point it at a cheaper
 * / faster model than chat.
 */

/** Provider task policy used to route reranking (ADR 0010 channel). */
export const RETRIEVAL_RERANK_TASK = "retrieval_rerank";

/** Max tokens for the reranker's JSON scoring response. */
export const DEFAULT_RERANK_MAX_TOKENS = 700;

/**
 * Per-candidate text budget sent to the reranker. Bounds the prompt size so a
 * large window of long documents cannot blow up the provider payload; the
 * reranker only needs a representative snippet to judge relevance.
 */
export const RERANK_SNIPPET_MAX_CHARS = 600;
