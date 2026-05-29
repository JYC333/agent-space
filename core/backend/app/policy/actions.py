from __future__ import annotations

"""Canonical policy action registry.

Every sensitive action the system can perform must be registered here.
Unknown sensitive actions must not silently fall through as allow — callers
must use require_action_definition() at policy-check integration points.

Action counts (current):
  WIRED_DIRECT     (21): runtime.execute, runtime.use_credential,
                          context.inject_memory, context.render_for_runtime,
                          workspace.write_patch, workspace.read, artifact.persist,
                          proposal.create, proposal.apply, agent.config_update,
                          automation.create, automation.update, automation.fire,
                          intake.connection_manage, intake.item_create,
                          intake.item_update, evidence.create, evidence.update,
                          evidence.link, workspace_intake.configure,
                          context.select_evidence
  WIRED_VIA_PROPOSAL (9): memory.create, memory.update, memory.archive, policy.change,
                           knowledge.create, knowledge.update, knowledge.archive,
                           knowledge.relation_create, knowledge.relation_delete
  RESERVED          (12): context.use_personal_grant, workspace.apply_patch,
                           artifact.export, proposal.approve,
                           memory.read_private, memory.promote_shared,
                           capability.enable, capability.update, tool_binding.enable,
                           evidence.export, deployment.propose, deployment.execute

Action lifecycle states
-----------------------
WIRED_DIRECT
    The action has a real direct PolicyGateway.enforce(action=...)
    enforcement call site in business code.  HardInvariantGuard and PolicyEngine
    are run normally.

WIRED_VIA_PROPOSAL
    The action is not directly checked as a standalone action.  It is protected
    by the proposal.apply gate (PolicyGateway.enforce_proposal_apply) and
    ProposalApplyService.

RESERVED
    The action is registered for vocabulary completeness and fail-closed
    future-proofing, but has no enforcement implementation yet.  PolicyGateway
    always denies RESERVED actions before PolicyEngine runs.
    reason_code="policy_action_not_implemented".

record_failure_mode
-------------------
"best_effort"  — If PolicyDecisionRecord persistence fails, log a warning and
                 allow the action to proceed.  Acceptable for low-risk manual
                 allow decisions and non-mutating dry-run simulations.

"fail_closed"  — If PolicyDecisionRecord persistence fails, raise
                 PolicyAuditPersistError and block the action.
                 Required for: runtime.use_credential, proposal.apply,
                 workspace.write_patch, artifact.persist, policy.change, automation-origin
                 sensitive actions, and critical-risk audit-required decisions.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .decisions import Decision, RiskLevel


class PolicyActionLifecycle(str, Enum):
    """Lifecycle state of a registered policy action."""

    WIRED_DIRECT = "wired_direct"
    WIRED_VIA_PROPOSAL = "wired_via_proposal"
    RESERVED = "reserved"


class RecordFailureMode(str, Enum):
    """Typed failure mode for PolicyDecisionRecord persistence.

    BEST_EFFORT — if persistence fails, log a warning and allow the action to
                  proceed. Acceptable for low-risk manual allow decisions.

    FAIL_CLOSED — if persistence fails, preferred enforcement raises
                  PolicyAuditPersistError and blocks the action. Required for: runtime.use_credential,
                  proposal.apply, workspace.write_patch, artifact.persist, policy.change, and any
                  automation-origin or CRITICAL-risk audit_required decision.
    """

    BEST_EFFORT = "best_effort"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True)
class PolicyActionDefinition:
    action: str
    resource_type: str
    default_risk_level: RiskLevel
    default_decision: Decision
    audit_required: bool
    approval_capability: Optional[str]
    default_required_approver_role: Optional[str]
    current_enforcement_point: str
    description: str
    lifecycle_status: PolicyActionLifecycle = PolicyActionLifecycle.WIRED_DIRECT
    record_failure_mode: RecordFailureMode = RecordFailureMode.BEST_EFFORT


_REGISTRY: dict[str, PolicyActionDefinition] = {}


def _reg(*defs: PolicyActionDefinition) -> None:
    for d in defs:
        if d.action in _REGISTRY:
            raise ValueError(f"Duplicate policy action registration: {d.action!r}")
        _REGISTRY[d.action] = d


_reg(
    # ------------------------------------------------------------------
    # WIRED_DIRECT actions — have real preferred PolicyGateway enforcement
    # call sites in business code.
    # ------------------------------------------------------------------
    PolicyActionDefinition(
        action="runtime.execute",
        resource_type="run",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.runs.execution.RunExecutionService.execute",
        description="Execute a runtime adapter for an agent run.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="runtime.use_credential",
        resource_type="credential",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_credential_use",
        default_required_approver_role="owner",
        current_enforcement_point="app.runs.execution.RunExecutionService.execute",
        description="Allow a runtime adapter to use a space credential.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.FAIL_CLOSED,
    ),
    PolicyActionDefinition(
        action="context.inject_memory",
        resource_type="memory",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=False,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.runs.context_snapshot_populator.ContextSnapshotPopulator.populate",
        description="Inject memory entries into a runtime context package.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="context.render_for_runtime",
        resource_type="context",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=False,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.runs.execution.RunExecutionService.execute",
        description="Render a context package for delivery to a runtime adapter.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="workspace.write_patch",
        resource_type="workspace",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_code_patch",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.code_patch_apply.apply_code_patch_payload",
        description="Apply a code patch to workspace files.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.FAIL_CLOSED,
    ),
    PolicyActionDefinition(
        action="artifact.persist",
        resource_type="artifact",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.runs.artifact_persistence.ArtifactPersistenceService",
        description="Persist an artifact produced by a run.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.FAIL_CLOSED,
    ),
    PolicyActionDefinition(
        action="proposal.create",
        resource_type="proposal",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=False,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point=(
            "app.memory.proposals.ProposalService.create_proposal"
            ", app.memory.proposals.ProposalService.create_user_proposal"
            ", app.runs.code_patch_collector.collect_and_create_code_patch_proposal"
        ),
        description=(
            "Create a proposal for a pending durable change. "
            "Covers user-created memory proposals (memory_create, memory_update, etc.) "
            "and system-created code_patch proposals from CLI runs."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="proposal.apply",
        resource_type="proposal",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_proposal",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept",
        description=(
            "Accept and apply a pending proposal through ProposalApplyService. "
            "The actor must have approval authority for the proposal type and risk level."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.FAIL_CLOSED,
    ),
    PolicyActionDefinition(
        action="agent.config_update",
        resource_type="agent",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability="approve_agent_config_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.agents.agent_service.AgentService.create_config_update_proposal",
        description=(
            "Create an agent_config_update proposal for post-create execution "
            "configuration changes. The durable mutation is still protected by "
            "proposal.apply."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    # ------------------------------------------------------------------
    # WIRED_VIA_PROPOSAL actions — protected by the proposal.apply gate
    # (PolicyGateway.enforce_proposal_apply) and ProposalApplyService.
    # current_enforcement_point documents the proposal apply path.
    # ------------------------------------------------------------------
    PolicyActionDefinition(
        action="memory.create",
        resource_type="memory",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_memory_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Create a new memory entry. Protected via proposal.apply gate and "
            "ProposalApplyService. Must not be called directly through PolicyGateway."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="memory.update",
        resource_type="memory",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_memory_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Update a memory entry. Protected via proposal.apply gate and "
            "ProposalApplyService. Must not be called directly through PolicyGateway."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="memory.archive",
        resource_type="memory",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_memory_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Archive a memory entry. Protected via proposal.apply gate and "
            "ProposalApplyService. Must not be called directly through PolicyGateway."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="policy.change",
        resource_type="policy",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_policy_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Create or supersede a policy version. Protected via proposal.apply gate and "
            "ProposalApplyService. Must not be called directly through PolicyGateway."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
        record_failure_mode=RecordFailureMode.FAIL_CLOSED,
    ),
    # ------------------------------------------------------------------
    PolicyActionDefinition(
        action="knowledge.create",
        resource_type="knowledge",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_knowledge_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Create an active KnowledgeItem after an accepted knowledge_create "
            "proposal. Protected via proposal.apply gate and ProposalApplyService."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
    ),
    PolicyActionDefinition(
        action="knowledge.update",
        resource_type="knowledge",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_knowledge_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Create a new version of an existing KnowledgeItem after an accepted "
            "knowledge_update proposal. Protected via proposal.apply gate and ProposalApplyService."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
    ),
    PolicyActionDefinition(
        action="knowledge.archive",
        resource_type="knowledge",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_knowledge_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Archive a KnowledgeItem after an accepted knowledge_archive proposal. "
            "Protected via proposal.apply gate and ProposalApplyService."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
    ),
    PolicyActionDefinition(
        action="knowledge.relation_create",
        resource_type="knowledge_relation",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_knowledge_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Create a same-space KnowledgeRelation after an accepted "
            "knowledge_relation_create proposal. Protected via proposal.apply gate "
            "and ProposalApplyService."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
    ),
    PolicyActionDefinition(
        action="knowledge.relation_delete",
        resource_type="knowledge_relation",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_knowledge_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.memory.proposals.ProposalService.accept via proposal.apply",
        description=(
            "Remove or archive a KnowledgeRelation after an accepted "
            "knowledge_relation_delete proposal. Protected via proposal.apply gate "
            "and ProposalApplyService."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_VIA_PROPOSAL,
    ),
    # ------------------------------------------------------------------
    # RESERVED actions — registered for vocabulary completeness and
    # fail-closed defence-in-depth.  PolicyGateway always denies reserved
    # actions regardless of default_decision, before PolicyEngine runs.
    # current_enforcement_point="not_implemented" documents human intent.
    # Do not wire these into business code until the feature is built.
    # ------------------------------------------------------------------
    PolicyActionDefinition(
        action="context.use_personal_grant",
        resource_type="personal_memory_grant",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="not_implemented",
        description=(
            "Authorize use of a PersonalMemoryGrant to include cross-space personal "
            "memory in a run context."
        ),
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="workspace.read",
        resource_type="workspace",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=False,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.workspace_console.api",
        description="Read files or metadata from a workspace.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
    ),
    PolicyActionDefinition(
        action="workspace.apply_patch",
        resource_type="workspace",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_code_patch",
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description=(
            "Apply a patch to workspace files via a mechanism other than "
            "workspace.write_patch (e.g. a direct apply path bypassing the proposal)."
        ),
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="artifact.export",
        resource_type="artifact",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description="Export an artifact to a destination outside the originating space.",
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="proposal.approve",
        resource_type="proposal",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_proposal",
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description=(
            "Record an explicit ProposalApproval row for a pending proposal, "
            "separate from the proposal.apply gate."
        ),
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="memory.read_private",
        resource_type="memory",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description=(
            "Read a private memory entry outside the owning user's personal "
            "space run context."
        ),
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="memory.promote_shared",
        resource_type="memory",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_memory_change",
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description="Change a memory entry's visibility from private to space-shared.",
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="capability.enable",
        resource_type="capability",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_capability_change",
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description="Enable a registered capability for agent runs in this space.",
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="capability.update",
        resource_type="capability",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_capability_change",
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description="Update the manifest or configuration of a registered capability.",
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="tool_binding.enable",
        resource_type="tool_binding",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_tool_binding_change",
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description="Enable a tool binding for agent use in this space.",
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="evidence.export",
        resource_type="evidence",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description="Export extracted evidence outside the originating space.",
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    # ------------------------------------------------------------------
    # Automation WIRED_DIRECT actions — wired to AutomationService.
    #
    # Context keys consumed by PolicyEngine rules:
    #   agent_id, trigger_type, trigger_origin.
    # Metadata keys (audit-only, never grant permission):
    #   automation_name, preflight_executable.
    #
    # Automation-origin runs must not directly mutate memory, policy, workspace
    # files, credentials, capabilities, or deployment state. They may produce
    # artifacts/proposals under existing gates. Credential use for automation-
    # origin runs requires REQUIRE_APPROVAL or DENY unless an explicit approved
    # automation credential allowance is implemented in a future phase.
    # No caller may pretend approval by passing approval flags in metadata_json,
    # context, or payload.
    # ------------------------------------------------------------------
    PolicyActionDefinition(
        action="automation.create",
        resource_type="automation",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_automation_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.automation.service.AutomationService.create",
        description=(
            "Create an automation rule that can trigger agent runs on a "
            "schedule or event."
        ),
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.FAIL_CLOSED,
    ),
    PolicyActionDefinition(
        action="automation.fire",
        resource_type="automation",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role="owner",
        current_enforcement_point="app.automation.service.AutomationService.fire",
        description="Manually trigger an automation rule to queue an agent run.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.FAIL_CLOSED,
    ),
    PolicyActionDefinition(
        action="automation.update",
        resource_type="automation",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_automation_change",
        default_required_approver_role="owner",
        current_enforcement_point="app.automation.service.AutomationService.update",
        description="Update an existing automation rule's trigger condition or configuration.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.FAIL_CLOSED,
    ),
    PolicyActionDefinition(
        action="intake.connection_manage",
        resource_type="source_connection",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.intake.api",
        description="Create or update source connections.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="intake.item_create",
        resource_type="intake_item",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.intake.api",
        description="Create raw intake items or extraction jobs without mutating durable memory or knowledge.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="intake.item_update",
        resource_type="intake_item",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.intake.api",
        description="Update intake item triage or read status without changing durable memory or knowledge.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="evidence.create",
        resource_type="evidence",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.intake.api",
        description="Create extracted evidence derived from intake, activity, artifacts, or run records.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="evidence.update",
        resource_type="evidence",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.intake.api",
        description="Update extracted evidence review status, confidence, or metadata.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="evidence.link",
        resource_type="evidence",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.intake.api",
        description="Link evidence to space, workspace, project, user, agent, run, proposal, artifact, memory, knowledge, or task targets.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="workspace_intake.configure",
        resource_type="workspace_intake",
        default_risk_level=RiskLevel.MEDIUM,
        default_decision=Decision.ALLOW,
        audit_required=True,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.intake.api",
        description="Configure workspace intake profiles and workspace source bindings.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="context.select_evidence",
        resource_type="evidence",
        default_risk_level=RiskLevel.LOW,
        default_decision=Decision.ALLOW,
        audit_required=False,
        approval_capability=None,
        default_required_approver_role=None,
        current_enforcement_point="app.memory.context_builder.ContextBuilder.build",
        description="Authorize selecting explicitly linked active evidence for inclusion in a run context snapshot.",
        lifecycle_status=PolicyActionLifecycle.WIRED_DIRECT,
        record_failure_mode=RecordFailureMode.BEST_EFFORT,
    ),
    PolicyActionDefinition(
        action="deployment.propose",
        resource_type="deployment",
        default_risk_level=RiskLevel.HIGH,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_deployment",
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description="Create a deployment proposal for a configuration or infrastructure change.",
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
    PolicyActionDefinition(
        action="deployment.execute",
        resource_type="deployment",
        default_risk_level=RiskLevel.CRITICAL,
        default_decision=Decision.REQUIRE_APPROVAL,
        audit_required=True,
        approval_capability="approve_deployment",
        default_required_approver_role="owner",
        current_enforcement_point="not_implemented",
        description=(
            "Execute a deployment to apply a proposed configuration or "
            "infrastructure change."
        ),
        lifecycle_status=PolicyActionLifecycle.RESERVED,
    ),
)


def get_action_definition(action: str) -> PolicyActionDefinition | None:
    """Return the definition for the given action, or None if not registered."""
    return _REGISTRY.get(action)


class UnknownPolicyActionError(Exception):
    """Raised when a sensitive action is not registered in the canonical action registry."""

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(
            f"Unknown policy action: {action!r}. "
            "All sensitive actions must be registered in the canonical action registry."
        )


def require_action_definition(action: str) -> PolicyActionDefinition:
    """Return the definition for the given action, raising UnknownPolicyActionError if unknown."""
    defn = _REGISTRY.get(action)
    if defn is None:
        raise UnknownPolicyActionError(action)
    return defn


def is_known_action(action: str) -> bool:
    """Return True if action is in the canonical registry."""
    return action in _REGISTRY


def list_action_definitions() -> list[PolicyActionDefinition]:
    """Return all registered action definitions in insertion order."""
    return list(_REGISTRY.values())
