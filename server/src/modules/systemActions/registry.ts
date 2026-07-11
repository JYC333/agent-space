import type { SystemActionDefinition, SystemActionId } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { loadProtocol } from "../providers/protocolRuntime";

let cached: ReadonlyMap<SystemActionId, SystemActionDefinition> | null = null;

export async function loadSystemActionRegistry(): Promise<ReadonlyMap<SystemActionId, SystemActionDefinition>> {
  if (cached) return cached;
  const protocol = await loadProtocol() as { SYSTEM_ACTION_REGISTRY: readonly SystemActionDefinition[] };
  cached = new Map(protocol.SYSTEM_ACTION_REGISTRY.map((definition) => [definition.id as SystemActionId, definition]));
  return cached;
}

export function resetSystemActionRegistryForTests(): void {
  cached = null;
}
