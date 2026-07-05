import type { PluginHostContext, PluginProposalContext } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { addGroupMembership, createGroup } from "./graph";

export const PROPOSAL_TYPE_RESEARCH_ATLAS_CURATION = "research_atlas_curation";

export async function applyResearchAtlasCuration(ctx: PluginProposalContext): Promise<void> {
  const action = requirePayloadString(ctx, "action");
  const spaceId = requireSpaceId(ctx);
  if (action === "create_group") {
    const name = requirePayloadString(ctx, "name");
    const aliases = Array.isArray(ctx.proposal.payload.aliases)
      ? ctx.proposal.payload.aliases.filter((item): item is string => typeof item === "string" && item.trim() !== "")
      : [];
    await createGroup(ctx.db, {
      spaceId,
      name,
      aliases,
      piScholarId: optionalPayloadString(ctx, "pi_scholar_id"),
      confidence: optionalPayloadNumber(ctx, "confidence"),
    });
    return;
  }
  if (action === "add_group_membership") {
    await addGroupMembership(ctx.db, {
      spaceId,
      groupId: requirePayloadString(ctx, "group_id"),
      scholarId: requirePayloadString(ctx, "scholar_id"),
      role: optionalPayloadString(ctx, "role") ?? "unknown",
      source: "agent_proposal",
      confidence: optionalPayloadNumber(ctx, "confidence"),
    });
    return;
  }
  throw new Error("unsupported research atlas curation action");
}

export function registerResearchAtlasProposalAppliers(ctx: PluginHostContext): void {
  ctx.proposals.register(PROPOSAL_TYPE_RESEARCH_ATLAS_CURATION, applyResearchAtlasCuration);
}

function requireSpaceId(ctx: PluginProposalContext): string {
  if (!ctx.proposal.space_id) {
    throw new Error(`${ctx.proposal.proposal_type} requires a space-scoped proposal`);
  }
  return ctx.proposal.space_id;
}

function requirePayloadString(ctx: PluginProposalContext, key: string): string {
  const value = ctx.proposal.payload[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${ctx.proposal.proposal_type} payload requires ${key}`);
  }
  return value.trim();
}

function optionalPayloadString(ctx: PluginProposalContext, key: string): string | null {
  const value = ctx.proposal.payload[key];
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

function optionalPayloadNumber(ctx: PluginProposalContext, key: string): number | null {
  const value = ctx.proposal.payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
