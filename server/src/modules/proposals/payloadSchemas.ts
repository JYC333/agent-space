import { z } from "zod";

// Base for every proposal payload: at minimum a literal proposal_type.
// All schemas use .passthrough() so unknown optional fields from agents are tolerated.

const memoryCreate = z
  .object({ proposal_type: z.literal("memory_create") })
  .passthrough();

const memoryUpdate = z
  .object({
    proposal_type: z.literal("memory_update"),
    target_memory_id: z.string().min(1),
  })
  .passthrough();

const memoryArchive = z
  .object({
    proposal_type: z.literal("memory_archive"),
    target_memory_id: z.string().min(1),
  })
  .passthrough();

const policyChange = z
  .object({ proposal_type: z.literal("policy_change") })
  .passthrough();

const skillImportApprove = z
  .object({ proposal_type: z.literal("skill_import_approve") })
  .passthrough();

const capabilityInstall = z
  .object({ proposal_type: z.literal("capability_install") })
  .passthrough();

const capabilityUpdate = z
  .object({ proposal_type: z.literal("capability_update") })
  .passthrough();

const capabilityEnable = z
  .object({ proposal_type: z.literal("capability_enable") })
  .passthrough();

const capabilityDisable = z
  .object({ proposal_type: z.literal("capability_disable") })
  .passthrough();

const runtimeSkillBindingUpdate = z
  .object({ proposal_type: z.literal("runtime_skill_binding_update") })
  .passthrough();

const knowledgeCreate = z
  .object({
    proposal_type: z.literal("knowledge_create"),
    knowledge_kind: z.string().min(1),
    title: z.string().min(1),
    content: z.string(),
  })
  .passthrough();

const knowledgeUpdate = z
  .object({
    proposal_type: z.literal("knowledge_update"),
    target_item_id: z.string().min(1),
    title: z.string().min(1),
    content: z.string(),
  })
  .passthrough();

const knowledgeArchive = z
  .object({
    proposal_type: z.literal("knowledge_archive"),
    target_item_id: z.string().min(1),
  })
  .passthrough();

const claimCreate = z
  .object({
    proposal_type: z.literal("claim_create"),
    claim_kind: z.string().min(1),
    claim_text: z.string().min(1),
  })
  .passthrough();

const claimUpdate = z
  .object({
    proposal_type: z.literal("claim_update"),
    target_claim_id: z.string().min(1),
  })
  .passthrough();

const claimArchive = z
  .object({
    proposal_type: z.literal("claim_archive"),
    target_claim_id: z.string().min(1),
  })
  .passthrough();

const objectRelationCreate = z
  .object({
    proposal_type: z.literal("object_relation_create"),
    from_object_id: z.string().min(1),
    to_object_id: z.string().min(1),
    relation_type: z.string().min(1),
  })
  .passthrough();

const objectRelationDelete = z
  .object({
    proposal_type: z.literal("object_relation_delete"),
    relation_id: z.string().min(1),
  })
  .passthrough();

const objectKindCreate = z
  .object({
    proposal_type: z.literal("object_kind_create"),
    key: z.string().min(1),
    label: z.string().min(1),
    base_object_type: z.string().min(1),
  })
  .passthrough();

const objectKindUpdate = z
  .object({
    proposal_type: z.literal("object_kind_update"),
    target_kind_id: z.string().min(1),
  })
  .passthrough();

const objectKindDeprecate = z
  .object({
    proposal_type: z.literal("object_kind_deprecate"),
    target_kind_id: z.string().min(1),
  })
  .passthrough();

const objectKindArchive = z
  .object({
    proposal_type: z.literal("object_kind_archive"),
    target_kind_id: z.string().min(1),
  })
  .passthrough();

const followUpTask = z
  .object({ proposal_type: z.literal("follow_up_task") })
  .passthrough();

const codePatch = z
  .object({ proposal_type: z.literal("code_patch") })
  .passthrough();

const claimCandidatePacket = z
  .object({ proposal_type: z.literal("claim_candidate_packet") })
  .passthrough();

const relationDiscoveryPacket = z
  .object({ proposal_type: z.literal("relation_discovery_packet") })
  .passthrough();

const retrievalDiagnosticsPacket = z
  .object({ proposal_type: z.literal("retrieval_diagnostics_packet") })
  .passthrough();

const retrievalMaintenancePacket = z
  .object({ proposal_type: z.literal("retrieval_maintenance_packet") })
  .passthrough();

const memoryMaintenancePacket = z
  .object({ proposal_type: z.literal("memory_maintenance_packet") })
  .passthrough();

export const ProposalPayloadSchema = z.discriminatedUnion("proposal_type", [
  memoryCreate,
  memoryUpdate,
  memoryArchive,
  policyChange,
  skillImportApprove,
  capabilityInstall,
  capabilityUpdate,
  capabilityEnable,
  capabilityDisable,
  runtimeSkillBindingUpdate,
  knowledgeCreate,
  knowledgeUpdate,
  knowledgeArchive,
  claimCreate,
  claimUpdate,
  claimArchive,
  objectRelationCreate,
  objectRelationDelete,
  objectKindCreate,
  objectKindUpdate,
  objectKindDeprecate,
  objectKindArchive,
  followUpTask,
  codePatch,
  claimCandidatePacket,
  relationDiscoveryPacket,
  retrievalDiagnosticsPacket,
  retrievalMaintenancePacket,
  memoryMaintenancePacket,
]);

export type ProposalPayload = z.infer<typeof ProposalPayloadSchema>;

export class ProposalPayloadValidationError extends Error {
  readonly statusCode = 422;
  constructor(
    readonly proposalType: string,
    readonly issues: z.ZodIssue[],
  ) {
    super(
      `proposal payload validation failed for type ${JSON.stringify(proposalType)}: ` +
        issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
    );
    this.name = "ProposalPayloadValidationError";
  }
}

export function validateProposalPayload(
  proposalType: string,
  payload: Record<string, unknown> | null,
): void {
  const raw = { ...(payload ?? {}), proposal_type: proposalType };
  const result = ProposalPayloadSchema.safeParse(raw);
  if (!result.success) {
    throw new ProposalPayloadValidationError(proposalType, result.error.issues);
  }
}
