/**
 * Provider module.
 *
 * The control plane owns the route edge for provider reads. With the default
 * `python` authority it forwards to Python and validates against the shared
 * protocol schemas (optionally shadow-comparing); with `ts` authority it
 * serves list/detail/catalog from the DB read port behind the Python
 * identity-introspection port. Provider commands and credential-channel
 * handlers are registered when their authority is `ts`.
 */

import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const providersModule: ControlPlaneModule = {
  name: "providers",
  registerRoutes,
};

export { getProviderConfig, listProviderConfigs } from "./service";
export {
  decryptModelProviderApiKeySecretRefV1,
  encryptModelProviderApiKeySecretRefV1,
  loadOrCreateModelProviderApiKeyMasterKey,
  MODEL_PROVIDER_API_KEY_AUTH_TAG_BYTES,
  MODEL_PROVIDER_API_KEY_MASTER_KEY_BYTES,
  MODEL_PROVIDER_API_KEY_NONCE_BYTES,
  MODEL_PROVIDER_API_KEY_SECRET_REF_V1_PREFIX,
  parseModelProviderApiKeySecretRefV1,
  SecretRefCompatibilityError,
} from "./secretRefCrypto";
export {
  __setProviderCommandStoreForTests,
  orderPoolMembers,
  ProviderCommandNotFoundError,
  ProviderCommandValidationError,
  resolveProviderCommandStore,
  type InvocationTarget,
  type PoolKeyCandidate,
  type PoolOutcome,
  type ProviderCommandStore,
  type ProviderInfo,
  type ProviderTaskChainEntry,
  type RotationStrategy,
} from "./providerCommandStore";
export {
  __setProviderHttpClientForTests,
  buildProviderModelName,
  completeProviderChat,
  completeProviderText,
  ProviderInvocationError,
  type ProviderHttpClient,
} from "./providerInvocation";
export { classifyProviderFailure } from "./providerResilience";
export {
  __setLoginFactoriesForTests,
  runCliLogin,
  sendCliLoginInput,
  type LoginToolResolver,
  type LoginEvent,
  type LoginRuntimeConfig,
  type PtyFactory,
} from "./cliLoginEngine";
export {
  CLI_LOGIN_ADAPTERS,
  cliLoginAdapterFor,
  type CliLoginAdapter,
} from "./cliLoginAdapters";
export { __setMountinfoReaderForTests, resolveHostPath } from "./hostPath";
export {
  readClaudeTokenUsage,
  unsupportedTokenUsage,
  type TokenUsage,
} from "./cliUsageReader";
export { readCodexTokenUsage } from "./codexUsageReader";
export {
  __setProbeFactoryForTests,
  parseQuota,
  probeClaudeQuota,
  type ProbePtyFactory,
  type ProbeToolResolver,
  type QuotaResult,
} from "./cliUsageProbe";
export {
  __setClaudeOAuthUsageHttpClientForTests,
  parseClaudeOAuthUsageResponse,
  probeClaudeOAuthQuota,
  type ClaudeOAuthHttpClient,
} from "./claudeOAuthUsageProbe";
export {
  __setCodexRpcFactoryForTests,
  probeCodexQuota,
  type CodexRpcFactory,
  type CodexRpcHandle,
} from "./codexUsageProbe";
export {
  CLI_USAGE_REFRESH_INTERVAL_MS,
  startCliUsageRefreshScheduler,
  type CliUsageRefreshBroker,
  type CliUsageRefreshScheduler,
} from "./cliUsageScheduler";
