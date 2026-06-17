/**
 * Canonical action registry access.
 *
 * The registry data is owned by the shared protocol package
 * (`POLICY_ACTION_REGISTRY`). Because the server is CommonJS and the
 * protocol is ESM, the data is loaded once through the cached dynamic import and
 * indexed into a Map.
 */

import { loadProtocol } from "../providers/protocolRuntime";

import type { PolicyActionDefinition } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};

export type { PolicyActionDefinition };

export class UnknownPolicyActionError extends Error {
  readonly action: string;
  constructor(action: string) {
    super(
      `Unknown policy action: ${JSON.stringify(action)}. All sensitive actions must be registered in the canonical action registry.`,
    );
    this.action = action;
    this.name = "UnknownPolicyActionError";
  }
}

let cached: Promise<ReadonlyMap<string, PolicyActionDefinition>> | null = null;

export function loadActionRegistry(): Promise<
  ReadonlyMap<string, PolicyActionDefinition>
> {
  cached ??= (async () => {
    const { POLICY_ACTION_REGISTRY } = await loadProtocol();
    const map = new Map<string, PolicyActionDefinition>();
    for (const def of POLICY_ACTION_REGISTRY) {
      map.set(def.action, def);
    }
    return map;
  })();
  return cached;
}

export function getActionDefinition(
  registry: ReadonlyMap<string, PolicyActionDefinition>,
  action: string,
): PolicyActionDefinition | undefined {
  return registry.get(action);
}

export function requireActionDefinition(
  registry: ReadonlyMap<string, PolicyActionDefinition>,
  action: string,
): PolicyActionDefinition {
  const defn = registry.get(action);
  if (defn === undefined) throw new UnknownPolicyActionError(action);
  return defn;
}
