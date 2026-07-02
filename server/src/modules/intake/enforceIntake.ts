import type { ModuleContext } from "../../gateway/routeRegistry";
import { enforce } from "../policy";
import { loadActionRegistry } from "../policy/actionRegistry";
import type { SpaceUserIdentity } from "../routeUtils/common";

/** Shared policy gate for every intake route (built-in and Custom Source). */
export async function enforceIntake(
  context: ModuleContext,
  identity: SpaceUserIdentity,
  action: string,
  resourceType: string,
  resourceId?: string,
): Promise<{ blocked: boolean; reply403: Record<string, string> | null }> {
  const registry = await loadActionRegistry();
  const result = await enforce(context.config, registry, {
    action,
    actor_type: "user",
    actor_id: identity.userId,
    space_id: identity.spaceId,
    resource_type: resourceType,
    resource_id: resourceId ?? null,
    force_record: false,
  });
  if (result.status === "blocked") {
    return { blocked: true, reply403: { detail: result.message ?? "Policy denied" } };
  }
  return { blocked: false, reply403: null };
}
