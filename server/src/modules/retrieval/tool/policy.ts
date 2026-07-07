import type { RetrievalObjectType, RetrievalSearchMode } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};
import { loadActionRegistry } from "../../policy/actionRegistry";
import { enforce } from "../../policy/service";

export type RetrievalToolPolicyAction =
  | "retrieval.search"
  | "retrieval.brief"
  | "memory.retrieval.search"
  | "memory.retrieval.brief"
  | "project_public_summary.search"
  | "project_public_summary.brief"
  | "intake.retrieval.search"
  | "intake.retrieval.brief";

export interface RetrievalToolPolicyActor {
  spaceId: string;
  instructedByUserId: string;
  agentId?: string | null;
  runId?: string | null;
}

export interface RetrievalToolPolicyInput {
  databaseUrl?: string | null;
  actor: RetrievalToolPolicyActor;
  action: RetrievalToolPolicyAction;
  domain: string;
  domainEnabled: boolean;
  mode?: RetrievalSearchMode;
  maxResults?: number;
  objectTypes?: RetrievalObjectType[];
  objectKinds?: string[];
  includeTrace?: boolean;
  surface?: string | null;
  sourcePolicyDenied?: boolean;
  egressPolicyDenied?: boolean;
}

export async function enforceRetrievalToolCallPolicy(
  input: RetrievalToolPolicyInput,
): Promise<void> {
  if (!input.databaseUrl) return;
  const registry = await loadActionRegistry();
  const actorId = input.actor.agentId ?? input.actor.runId ?? input.actor.instructedByUserId;
  const result = await enforce(
    { databaseUrl: input.databaseUrl },
    registry,
    {
      action: input.action,
      force_record: false,
      actor_type: input.actor.agentId ? "agent" : "user",
      actor_id: actorId,
      actor_ref: {
        service: "retrieval_tool",
        run_id: input.actor.runId ?? null,
        instructed_by_user_id: input.actor.instructedByUserId,
      },
      space_id: input.actor.spaceId,
      resource_type: "retrieval_tool",
      resource_id: input.action,
      run_id: input.actor.runId ?? null,
      context: {
        tool_name: input.action,
        domain: input.domain,
        domain_enabled: input.domainEnabled,
        instructed_by_user_id: input.actor.instructedByUserId,
        source_policy_denied: input.sourcePolicyDenied === true,
        egress_policy_denied: input.egressPolicyDenied === true,
      },
      metadata_json: {
        surface: input.surface ?? "retrieval_tool",
        tool_name: input.action,
        domain: input.domain,
        mode: input.mode ?? null,
        max_results: input.maxResults ?? null,
        object_type_count: input.objectTypes?.length ?? null,
        object_kind_count: input.objectKinds?.length ?? null,
        include_trace: input.includeTrace ?? null,
        source_policy_denied: input.sourcePolicyDenied === true,
        egress_policy_denied: input.egressPolicyDenied === true,
      },
    },
  );
  if (result.status !== "allow") {
    throw new Error(result.message ?? "Retrieval tool policy denied the call.");
  }
}
