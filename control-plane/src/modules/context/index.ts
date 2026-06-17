/**
 * `context` module — native TS context assembly.
 *
 * The chat slice owns chat context candidate collection (the per-source reads
 * the Python `context-candidates` port previously served). The full-run slice
 * owns `context.prepare` snapshot population and vendor runtime file rendering.
 * This module registers no routes; chat and run orchestration consume it
 * directly.
 */

export {
  ChatContextCandidateCollector,
  ChatContextError,
} from "./chatCandidateCollector";
export {
  ContextPrepareError,
  ContextPrepareService,
  type ContextPrepareInput,
  type ContextPrepareResult,
} from "./prepareService";
export { ContextCompiler, type CompiledContext } from "./compiler";
export {
  PgChatCandidateRepository,
  excerpt,
  tokenCount,
  type CandidateRow,
  type ContextPolicy,
} from "./candidateRepository";
