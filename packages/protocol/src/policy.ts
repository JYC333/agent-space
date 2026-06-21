/**
 * Policy enforcement wire contracts.
 *
 * Shared policy decision surface: the canonical action registry,
 * decision/request shapes, durable-audit envelope, and the `PolicyGateBlocked`
 * error taxonomy.
 *
 * Schemas only — no enforcement authority lives here. The authority is the
 * server `policy` module.
 * Field names mirror the API JSON (snake_case).
 */

import { z } from "zod";
import { IdSchema, ISODateTimeSchema, SecretResponseGuards } from "./common.js";

// ---------------------------------------------------------------------------
// Core enums (decisions.py / actions.py)
// ---------------------------------------------------------------------------

export const POLICY_DECISION_VALUES = [
  "allow",
  "deny",
  "require_approval",
] as const;
export type PolicyDecisionValue = (typeof POLICY_DECISION_VALUES)[number];
export const PolicyDecisionEnum = z.enum(POLICY_DECISION_VALUES);

export const POLICY_RISK_LEVEL_VALUES = [
  "low",
  "medium",
  "high",
  "critical",
] as const;
export type PolicyRiskLevel = (typeof POLICY_RISK_LEVEL_VALUES)[number];
export const PolicyRiskLevelEnum = z.enum(POLICY_RISK_LEVEL_VALUES);

export const POLICY_ACTION_LIFECYCLE_VALUES = [
  "wired_direct",
  "wired_via_proposal",
  "reserved",
] as const;
export type PolicyActionLifecycle =
  (typeof POLICY_ACTION_LIFECYCLE_VALUES)[number];
export const PolicyActionLifecycleEnum = z.enum(
  POLICY_ACTION_LIFECYCLE_VALUES,
);

export const POLICY_RECORD_FAILURE_MODE_VALUES = [
  "best_effort",
  "fail_closed",
] as const;
export type PolicyRecordFailureMode =
  (typeof POLICY_RECORD_FAILURE_MODE_VALUES)[number];
export const PolicyRecordFailureModeEnum = z.enum(
  POLICY_RECORD_FAILURE_MODE_VALUES,
);

// ---------------------------------------------------------------------------
// Canonical action registry
//
// This is the durable shared contract: every enforcement point must use the
// same action metadata. The registry is data and is validated by tests.
// ---------------------------------------------------------------------------

export const PolicyActionDefinitionSchema = z
  .object({
    action: z.string().min(1),
    resource_type: z.string().min(1),
    default_risk_level: PolicyRiskLevelEnum,
    default_decision: PolicyDecisionEnum,
    audit_required: z.boolean(),
    approval_capability: z.string().nullable(),
    default_required_approver_role: z.string().nullable(),
    current_enforcement_point: z.string(),
    description: z.string(),
    lifecycle_status: PolicyActionLifecycleEnum,
    record_failure_mode: PolicyRecordFailureModeEnum,
  })
  .strict();
export type PolicyActionDefinition = z.infer<
  typeof PolicyActionDefinitionSchema
>;

/**
 * The canonical registry, in insertion order. `description` is intentionally
 * omitted from the enforcement contract surface (it is human documentation, not
 * a decision input), but carried so audits and docs share the same labels.
 */
export const POLICY_ACTION_REGISTRY: readonly PolicyActionDefinition[] = [
  // ---- WIRED_DIRECT ----
  {
    action: "runtime.execute",
    resource_type: "run",
    default_risk_level: "medium",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point:
      "server/src/modules/runs/orchestrationService.ts",
    description: "Execute a runtime adapter for an agent run.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "runtime.use_credential",
    resource_type: "credential",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_credential_use",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/runs/orchestrationService.ts",
    description: "Allow a runtime adapter to use a space credential.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "fail_closed",
  },
  {
    action: "context.inject_memory",
    resource_type: "memory",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: false,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point:
      "server/src/modules/context/prepareService.ts",
    description: "Inject memory entries into a runtime context package.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "context.render_for_runtime",
    resource_type: "context",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: false,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point:
      "server/src/modules/context/prepareService.ts",
    description:
      "Render a context package for delivery to a runtime adapter.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "workspace.write_patch",
    resource_type: "workspace",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_code_patch",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/workspaces/codePatch.ts",
    description: "Apply a code patch to workspace files.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "fail_closed",
  },
  {
    action: "artifact.persist",
    resource_type: "artifact",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point:
      "server/src/modules/runs/materializationService.ts",
    description: "Persist an artifact produced by a run.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "fail_closed",
  },
  {
    action: "proposal.create",
    resource_type: "proposal",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: false,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point:
      "server/src/modules/memory/proposalRepository.ts, server/src/modules/runs/materializationService.ts, server/src/modules/workspaces/codePatch.ts",
    description:
      "Create a proposal for a pending durable change. Covers user-created memory proposals (memory_create, memory_update, etc.) and system-created code_patch proposals from CLI runs.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "proposal.apply",
    resource_type: "proposal",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_proposal",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts",
    description:
      "Accept and apply a pending proposal through ProposalApplyService. The actor must have approval authority for the proposal type and risk level.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "fail_closed",
  },
  {
    action: "agent.config_update",
    resource_type: "agent",
    default_risk_level: "high",
    default_decision: "allow",
    audit_required: true,
    approval_capability: "approve_agent_config_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/agents/routes.ts",
    description:
      "Create an agent_config_update proposal for post-create execution configuration changes. The durable mutation is still protected by proposal.apply.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  // ---- WIRED_VIA_PROPOSAL ----
  {
    action: "memory.create",
    resource_type: "memory",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_memory_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Create a new memory entry. Protected via proposal.apply gate and ProposalApplyService. Must not be called directly through PolicyGateway.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "best_effort",
  },
  {
    action: "memory.update",
    resource_type: "memory",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_memory_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Update a memory entry. Protected via proposal.apply gate and ProposalApplyService. Must not be called directly through PolicyGateway.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "best_effort",
  },
  {
    action: "memory.archive",
    resource_type: "memory",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_memory_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Archive a memory entry. Protected via proposal.apply gate and ProposalApplyService. Must not be called directly through PolicyGateway.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "best_effort",
  },
  {
    action: "policy.change",
    resource_type: "policy",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_policy_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Create or supersede a policy version. Protected via proposal.apply gate and ProposalApplyService. Must not be called directly through PolicyGateway.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "fail_closed",
  },
  {
    action: "knowledge.create",
    resource_type: "knowledge",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_knowledge_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Create an active KnowledgeItem after an accepted knowledge_create proposal. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "best_effort",
  },
  {
    action: "knowledge.update",
    resource_type: "knowledge",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_knowledge_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Create a new version of an existing KnowledgeItem after an accepted knowledge_update proposal. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "best_effort",
  },
  {
    action: "knowledge.archive",
    resource_type: "knowledge",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_knowledge_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Archive a KnowledgeItem after an accepted knowledge_archive proposal. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "best_effort",
  },
  {
    action: "knowledge.relation_create",
    resource_type: "knowledge_relation",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_knowledge_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Create a same-space KnowledgeItemRelation after an accepted knowledge_relation_create proposal. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "best_effort",
  },
  {
    action: "knowledge.relation_delete",
    resource_type: "knowledge_relation",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_knowledge_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Remove or archive a KnowledgeItemRelation after an accepted knowledge_relation_delete proposal. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "best_effort",
  },
  {
    action: "skill.import",
    resource_type: "skill_package",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_capability_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Approve an imported Open Skill package as reviewed source material. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "fail_closed",
  },
  {
    action: "skill.convert",
    resource_type: "skill_package",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_capability_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Convert a reviewed Open Skill package into a disabled draft capability. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "fail_closed",
  },
  {
    action: "capability.enable",
    resource_type: "capability",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_capability_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Enable a registered capability for agent runs in this space. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "fail_closed",
  },
  {
    action: "capability.disable",
    resource_type: "capability",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_capability_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Disable a registered capability for agent runs in this space. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "fail_closed",
  },
  {
    action: "capability.update",
    resource_type: "capability",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_capability_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Update the manifest or configuration of a registered capability. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "fail_closed",
  },
  {
    action: "runtime_skill.binding_update",
    resource_type: "runtime_skill_binding",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_capability_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/proposals/applyService.ts via proposal.apply",
    description:
      "Update a runtime skill binding for a capability version. Protected via proposal.apply gate and ProposalApplyService.",
    lifecycle_status: "wired_via_proposal",
    record_failure_mode: "fail_closed",
  },
  // ---- RESERVED + remaining WIRED_DIRECT (insertion order) ----
  {
    action: "context.use_personal_grant",
    resource_type: "personal_memory_grant",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point: "not_implemented",
    description:
      "Authorize use of a PersonalMemoryGrant to include cross-space personal memory in a run context.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "workspace.read",
    resource_type: "workspace",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: false,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point:
      "server/src/modules/workspaces/routes.ts",
    description: "Read files or metadata from a workspace.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "workspace.apply_patch",
    resource_type: "workspace",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_code_patch",
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description:
      "Apply a patch to workspace files via a mechanism other than workspace.write_patch (e.g. a direct apply path bypassing the proposal).",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "artifact.export",
    resource_type: "artifact",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description:
      "Export an artifact to a destination outside the originating space.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "proposal.approve",
    resource_type: "proposal",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_proposal",
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description:
      "Record an explicit ProposalApproval row for a pending proposal, separate from the proposal.apply gate.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "memory.read_private",
    resource_type: "memory",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description:
      "Read a private memory entry outside the owning user's personal space run context.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "memory.promote_shared",
    resource_type: "memory",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_memory_change",
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description:
      "Change a memory entry's visibility from private to space-shared.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "runtime_skill.render",
    resource_type: "runtime_skill_binding",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_capability_change",
    default_required_approver_role: "owner",
    current_enforcement_point: "server/src/modules/context/prepareService.ts",
    description:
      "Render a runtime-bound Open Skill for an adapter execution context.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "runtime_skill.execute",
    resource_type: "runtime_skill_binding",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_capability_change",
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description:
      "Execute a runtime-bound Open Skill through an adapter-native skill mechanism.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "tool_binding.enable",
    resource_type: "tool_binding",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_tool_binding_change",
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description: "Enable a tool binding for agent use in this space.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "evidence.export",
    resource_type: "evidence",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description: "Export extracted evidence outside the originating space.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  // ---- Automation WIRED_DIRECT ----
  {
    action: "automation.create",
    resource_type: "automation",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_automation_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/automations/service.ts",
    description:
      "Create an automation rule that can trigger agent runs on a schedule or event.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "fail_closed",
  },
  {
    action: "automation.fire",
    resource_type: "automation",
    default_risk_level: "medium",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/automations/service.ts",
    description: "Manually trigger an automation rule to queue an agent run.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "fail_closed",
  },
  {
    action: "automation.update",
    resource_type: "automation",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_automation_change",
    default_required_approver_role: "owner",
    current_enforcement_point:
      "server/src/modules/automations/service.ts",
    description:
      "Update an existing automation rule's trigger condition or configuration.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "fail_closed",
  },
  {
    action: "intake.connection_manage",
    resource_type: "source_connection",
    default_risk_level: "medium",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point: "server/src/modules/intake/routes.ts",
    description: "Create or update source connections.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "intake.item_create",
    resource_type: "intake_item",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point: "server/src/modules/intake/routes.ts",
    description:
      "Create raw intake items or extraction jobs without mutating durable memory or knowledge.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "intake.item_update",
    resource_type: "intake_item",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point: "server/src/modules/intake/routes.ts",
    description:
      "Update intake item triage or read status without changing durable memory or knowledge.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "evidence.create",
    resource_type: "evidence",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point: "server/src/modules/intake/routes.ts",
    description:
      "Create extracted evidence derived from intake, activity, artifacts, or run records.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "evidence.update",
    resource_type: "evidence",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point: "server/src/modules/intake/routes.ts",
    description:
      "Update extracted evidence review status, confidence, or metadata.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "evidence.link",
    resource_type: "evidence",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point: "server/src/modules/intake/routes.ts",
    description:
      "Link evidence to space, workspace, project, user, agent, run, proposal, artifact, memory, knowledge, or task targets.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "workspace_intake.configure",
    resource_type: "workspace_intake",
    default_risk_level: "medium",
    default_decision: "allow",
    audit_required: true,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point: "server/src/modules/intake/routes.ts",
    description:
      "Configure workspace intake profiles and workspace source bindings.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "context.select_evidence",
    resource_type: "evidence",
    default_risk_level: "low",
    default_decision: "allow",
    audit_required: false,
    approval_capability: null,
    default_required_approver_role: null,
    current_enforcement_point:
      "server/src/modules/context/prepareService.ts",
    description:
      "Authorize selecting explicitly linked active evidence for inclusion in a run context snapshot.",
    lifecycle_status: "wired_direct",
    record_failure_mode: "best_effort",
  },
  {
    action: "deployment.propose",
    resource_type: "deployment",
    default_risk_level: "high",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_deployment",
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description:
      "Create a deployment proposal for a configuration or infrastructure change.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
  {
    action: "deployment.execute",
    resource_type: "deployment",
    default_risk_level: "critical",
    default_decision: "require_approval",
    audit_required: true,
    approval_capability: "approve_deployment",
    default_required_approver_role: "owner",
    current_enforcement_point: "not_implemented",
    description:
      "Execute a deployment to apply a proposed configuration or infrastructure change.",
    lifecycle_status: "reserved",
    record_failure_mode: "best_effort",
  },
] as const;

// ---------------------------------------------------------------------------
// Enforcement request (PolicyCheckRequest, gateway.py)
//
// `context` carries bounded decision inputs (flattened into the guard ctx);
// `metadata_json` is audit-only; `payload` is only scanned by hard invariants.
// None of these may carry secrets — the broker/runtime channels own those.
// ---------------------------------------------------------------------------

const JsonRecordSchema = z.record(z.string(), z.unknown());

export const PolicyCheckRequestSchema = z
  .object({
    action: z.string().min(1),
    actor_type: z.string().nullish(),
    actor_id: IdSchema.nullish(),
    actor_ref: JsonRecordSchema.nullish(),
    space_id: IdSchema.nullish(),
    resource_type: z.string().nullish(),
    resource_id: z.string().nullish(),
    resource_space_id: IdSchema.nullish(),
    run_id: IdSchema.nullish(),
    proposal_id: IdSchema.nullish(),
    context: JsonRecordSchema.nullish(),
    payload: JsonRecordSchema.nullish(),
    metadata_json: JsonRecordSchema.nullish(),
    force_record: z.boolean().default(false),
  })
  .strict();
export type PolicyCheckRequest = z.infer<typeof PolicyCheckRequestSchema>;

// ---------------------------------------------------------------------------
// Proposal-apply gate request (PolicyPort.enforce_proposal_apply)
// ---------------------------------------------------------------------------

export const PolicyProposalApplyRequestSchema = z
  .object({
    user_id: IdSchema,
    space_id: IdSchema,
    proposal_id: IdSchema,
    proposal_type: z.string().min(1),
    risk_level: PolicyRiskLevelEnum.nullish(),
    membership_role: z.string().nullish(),
    supported_proposal_types: z.array(z.string().min(1)),
    // The proposal payload is scanned only for approval-proof flags by the hard
    // invariant guard; it is never a decision input otherwise and must be
    // secret-free.
    payload: JsonRecordSchema.nullish(),
    metadata_json: JsonRecordSchema.nullish(),
  })
  .strict();
export type PolicyProposalApplyRequest = z.infer<
  typeof PolicyProposalApplyRequestSchema
>;

// ---------------------------------------------------------------------------
// Decision result (PolicyDecision, decisions.py)
// ---------------------------------------------------------------------------

export const PolicyDecisionSchema = z
  .object({
    decision: PolicyDecisionEnum,
    message: z.string(),
    risk_level: PolicyRiskLevelEnum.default("low"),
    reason_code: z.string().nullish(),
    required_approver_role: z.string().nullish(),
    policy_rule_id: z.string().nullish(),
    policy_source: z.string().default("builtin"),
    policy_id: z.string().nullish(),
    actor_type: z.string().nullish(),
    actor_id: IdSchema.nullish(),
    actor_ref: JsonRecordSchema.nullish(),
    space_id: IdSchema.nullish(),
    action: z.string().nullish(),
    resource_type: z.string().nullish(),
    resource_id: z.string().nullish(),
    audit_code: z.string().nullish(),
    approval_capability: z.string().nullish(),
    proposal_type: z.string().nullish(),
    metadata_json: JsonRecordSchema.nullish(),
    created_at: ISODateTimeSchema.nullish(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type PolicyDecision = z.infer<typeof PolicyDecisionSchema>;

// ---------------------------------------------------------------------------
// Durable audit envelope (audit.py PolicyAuditEnvelope → PolicyDecisionRecord)
//
// This is the sanitized, audit-only record the gateway persists. metadata_json
// is post-sanitization (no credentials/raw memory/patch bodies/stdout-stderr).
// ---------------------------------------------------------------------------

export const PolicyAuditEnvelopeSchema = z
  .object({
    space_id: IdSchema.nullish(),
    actor_type: z.string().nullish(),
    actor_id: IdSchema.nullish(),
    actor_ref_json: JsonRecordSchema.nullish(),
    action: z.string(),
    resource_type: z.string().nullish(),
    resource_id: z.string().nullish(),
    decision: PolicyDecisionEnum,
    risk_level: PolicyRiskLevelEnum,
    required_approver_role: z.string().nullish(),
    approval_capability: z.string().nullish(),
    policy_rule_id: z.string().nullish(),
    policy_source: z.string().nullish(),
    policy_id: z.string().nullish(),
    audit_code: z.string().nullish(),
    run_id: IdSchema.nullish(),
    proposal_id: IdSchema.nullish(),
    metadata_json: JsonRecordSchema.nullish(),
    created_at: ISODateTimeSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type PolicyAuditEnvelope = z.infer<typeof PolicyAuditEnvelopeSchema>;

// ---------------------------------------------------------------------------
// Error taxonomy (exceptions.py — PolicyGateBlocked / PolicyAuditPersistError)
//
// `enforce` returns a PolicyDecision on ALLOW and raises a gate-block on
// DENY / REQUIRE_APPROVAL; an independent fail-closed audit write failure is a
// distinct error so a sensitive action does not proceed without durable audit.
// ---------------------------------------------------------------------------

export const POLICY_ENFORCE_ERROR_CODES = [
  "policy_denied",
  "policy_requires_approval",
  "policy_audit_persist_failed",
  "unknown_policy_action",
  "policy_action_not_implemented",
  "unauthorized_internal_port",
  "policy_invalid_request",
] as const;
export type PolicyEnforceErrorCode =
  (typeof POLICY_ENFORCE_ERROR_CODES)[number];
export const PolicyEnforceErrorCodeEnum = z.enum(POLICY_ENFORCE_ERROR_CODES);

export const PolicyEnforceResultSchema = z
  .object({
    status: z.enum(["allow", "blocked", "error"]),
    decision: PolicyDecisionSchema.nullish(),
    error_code: PolicyEnforceErrorCodeEnum.nullish(),
    message: z.string().nullish(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type PolicyEnforceResult = z.infer<typeof PolicyEnforceResultSchema>;
