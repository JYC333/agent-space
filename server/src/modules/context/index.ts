/**
 * `context` module — native server context assembly.
 *
 * The chat slice owns chat context candidate collection. The full-run slice
 * owns `context.prepare` snapshot population and vendor runtime file rendering.
 * The public `/context/build` route serves a read-only preview package for the
 * frontend Context Preview screen.
 */

import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const contextModule: ServerModule = {
  name: "context",
  registerRoutes,
};

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
