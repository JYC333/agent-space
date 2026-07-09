import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const promptsModule: ServerModule = { name: "prompts", registerRoutes };

export { __setPromptRepositoryFactoryForTests } from "./routes";
export { PromptRepository } from "./repository";
export { loadPromptManifests, syncBuiltinPrompts } from "./builtins";
export type { PromptManifest, PromptSyncResult } from "./builtins";
export { resolvePrompt } from "./resolver";
export type { ResolvePromptInput } from "./resolver";
export { missingRequiredVariables, renderPromptMessages, renderPromptTemplate } from "./renderer";
export { promptProvenanceOf, withPromptProvenance } from "./provenance";
export type { PromptProvenance } from "./provenance";
