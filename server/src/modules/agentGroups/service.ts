import type { ServerConfig } from "../../config";
import { getDbPool, type Pool, type PoolClient } from "../../db/pool";
import { loadActionRegistry } from "../policy/actionRegistry";
import { enforce, type EnforceResult } from "../policy/service";
import { HttpError, withDbTransaction } from "../routeUtils/common";
import { PgJobQueueRepository } from "../jobs/repository";
import { PgRunRepository, type RunRecord } from "../runs/repository";
import {
  type AgentCapabilitySnapshotRecord,
  type AgentRunGroupRecord,
  type AgentRunMessageRecord,
  type RunDelegationRecord,
  PgAgentGroupRepository,
} from "./repository";

import type { PolicyCheckRequest } from "@agent-space/protocol" with { "resolution-mode": "import" };

export interface AgentGroupIdentity {
  spaceId: string;
  userId: string;
}

export interface CreateAgentGroupInput {
  space_id: string;
  title: string;
  goal?: string | null;
  manager_agent_id: string;
  member_agent_ids: string[];
  budget_json?: Record<string, unknown> | null;
  context_policy_json?: Record<string, unknown> | null;
}

export interface UpdateAgentGroupInput {
  space_id: string;
  group_id: string;
  title?: string | null;
  goal?: string | null;
}

export interface SendAgentGroupMessageInput {
  space_id: string;
  group_id: string;
  content: string;
  parent_message_id?: string | null;
  routing_mode?: "direct" | "agent_coordination" | null;
  recipient_segments?: AgentGroupMessageRecipientSegment[] | null;
  metadata_json?: Record<string, unknown> | null;
}

export interface AgentGroupMessageRecipientSegment {
  recipient_agent_ids: string[];
  content: string;
}

export interface SpawnChildRunInput {
  space_id: string;
  group_id: string;
  parent_run_id: string;
  root_run_id: string;
  requesting_agent_id: string;
  target_agent_id: string;
  manager_user_id: string;
  request_message_id?: string | null;
  instruction: string;
  reason?: string | null;
  budget_json?: Record<string, unknown> | null;
  context_policy_json?: Record<string, unknown> | null;
}

export interface AgentGroupTimeline {
  group: AgentRunGroupRecord;
  members: Awaited<ReturnType<PgAgentGroupRepository["listMembers"]>>;
  messages: AgentRunMessageRecord[];
  delegations: RunDelegationRecord[];
}

const MAX_DELEGATION_DEPTH = 3;
const MAX_PARENT_FANOUT = 8;
const MAX_GROUP_CONCURRENCY = 4;

type PolicyEnforcer = (
  config: Pick<ServerConfig, "databaseUrl">,
  registry: Awaited<ReturnType<typeof loadActionRegistry>>,
  req: PolicyCheckRequest,
) => Promise<EnforceResult>;

export class AgentGroupRunService {
  constructor(
    private readonly config: ServerConfig,
    private readonly pool: Pool,
    private readonly policyEnforcer: PolicyEnforcer = enforce,
  ) {}

  static fromConfig(config: ServerConfig): AgentGroupRunService {
    if (!config.databaseUrl) {
      throw new HttpError(502, "SERVER_DATABASE_URL is required");
    }
    return new AgentGroupRunService(config, getDbPool(config.databaseUrl));
  }

  async createGroup(identity: AgentGroupIdentity, input: CreateAgentGroupInput): Promise<{
    group: AgentRunGroupRecord;
    members: AgentGroupTimeline["members"];
  }> {
    assertIdentitySpace(identity, input.space_id);
    const managerAgentId = requiredTrimmed(input.manager_agent_id, "manager_agent_id");
    const memberAgentIds = uniqueIds([managerAgentId, ...input.member_agent_ids]);
    if (memberAgentIds.length === 0) {
      throw new HttpError(422, "member_agent_ids is required");
    }

    return withDbTransaction(this.pool, async (client) => {
      const repos = this.repos(client);
      await assertAgentsActive(repos.groups, input.space_id, identity.userId, memberAgentIds);
      const capabilitySnapshots = new Map(
        (await repos.groups.listAgentCapabilitySnapshots(input.space_id, identity.userId, memberAgentIds))
          .map((snapshot) => [snapshot.id, snapshot]),
      );

      const budgetLimits = delegationBudgetLimits(input.budget_json ?? {});
      const policySnapshot = {
        action: "run.spawn_child",
        max_depth: budgetLimits.max_depth,
        max_fanout: budgetLimits.max_fanout,
        max_concurrency: budgetLimits.max_concurrency,
        context_policy_json: input.context_policy_json ?? {},
      };
      const group = await repos.groups.createGroup({
        space_id: input.space_id,
        manager_user_id: identity.userId,
        manager_agent_id: managerAgentId,
        title: requiredTrimmed(input.title, "title"),
        goal: optionalTrimmed(input.goal),
        budget_json: input.budget_json ?? {},
        policy_snapshot_json: policySnapshot,
      });

      for (const agentId of memberAgentIds) {
        await repos.groups.createMember({
          space_id: input.space_id,
          group_id: group.id,
          agent_id: agentId,
          role: agentId === managerAgentId ? "manager" : "worker",
          capabilities_json: memberCapabilitySnapshot(capabilitySnapshots.get(agentId)),
          context_policy_json: input.context_policy_json ?? {},
        });
      }

      return {
        group,
        members: await repos.groups.listMembers(input.space_id, group.id),
      };
    });
  }

  async listGroups(identity: AgentGroupIdentity, input: {
    status?: string | null;
    limit: number;
    offset: number;
  }): Promise<{ items: AgentRunGroupRecord[]; total: number; limit: number; offset: number }> {
    const repo = new PgAgentGroupRepository(this.pool);
    const filters = {
      space_id: identity.spaceId,
      manager_user_id: identity.userId,
      status: input.status ?? null,
    };
    const [items, total] = await Promise.all([
      repo.listGroups({ ...filters, limit: input.limit, offset: input.offset }),
      repo.countGroups(filters),
    ]);
    return { items, total, limit: input.limit, offset: input.offset };
  }

  async getGroup(identity: AgentGroupIdentity, groupId: string): Promise<{
    group: AgentRunGroupRecord;
    members: AgentGroupTimeline["members"];
  }> {
    const repo = new PgAgentGroupRepository(this.pool);
    const group = await this.requireManagedGroup(repo, identity, groupId);
    return {
      group,
      members: await repo.listMembers(identity.spaceId, groupId),
    };
  }

  async updateGroup(identity: AgentGroupIdentity, input: UpdateAgentGroupInput): Promise<{
    group: AgentRunGroupRecord;
  }> {
    assertIdentitySpace(identity, input.space_id);
    return withDbTransaction(this.pool, async (client) => {
      const repo = new PgAgentGroupRepository(client);
      await this.requireManagedGroup(repo, identity, input.group_id);
      const title = input.title === undefined ? undefined : requiredTrimmed(input.title ?? "", "title");
      const goal = input.goal === undefined ? undefined : optionalTrimmed(input.goal);
      const group = await repo.updateGroupDetails({
        space_id: input.space_id,
        group_id: input.group_id,
        title,
        goal,
      });
      if (!group) {
        throw new HttpError(404, "Agent group not found in this space");
      }
      return { group };
    });
  }

  async sendUserMessage(identity: AgentGroupIdentity, input: SendAgentGroupMessageInput): Promise<{
    message: AgentRunMessageRecord;
  }> {
    assertIdentitySpace(identity, input.space_id);
    return withDbTransaction(this.pool, async (client) => {
      const repos = this.repos(client);
      const group = await repos.groups.lockGroup(input.space_id, input.group_id);
      if (!group || group.manager_user_id !== identity.userId) {
        throw new HttpError(404, "Agent group not found in this space");
      }
      if (group.status !== "active") {
        throw new HttpError(409, `Agent group is not active (current status: ${group.status})`);
      }
      if (!group.manager_agent_id) {
        throw new HttpError(409, "Agent group has no manager agent");
      }
      const content = requiredTrimmed(input.content, "content");
      const routingMode = input.routing_mode ?? "direct";
      const routingSegments = messageRecipientSegmentsForInput(input, group.manager_agent_id, content);
      const allRecipientAgentIds = uniqueIds(routingSegments.flatMap((segment) => segment.recipient_agent_ids));
      const plannedRecipientRunCount = routingSegments.reduce(
        (count, segment) => count + segment.recipient_agent_ids.length,
        0,
      );
      for (const recipientAgentId of allRecipientAgentIds) {
        await assertActiveGroupMember(
          repos.groups,
          input.space_id,
          group.id,
          recipientAgentId,
          identity.userId,
          "recipient_segments.recipient_agent_ids",
        );
      }
      const recipientSnapshots = plannedRecipientRunCount > 1
        ? new Map(
          (await repos.groups.listAgentCapabilitySnapshots(input.space_id, identity.userId, allRecipientAgentIds))
            .map((snapshot) => [snapshot.id, snapshot]),
        )
        : new Map<string, AgentCapabilitySnapshotRecord>();
      const groupPolicy = recordValue(group.policy_snapshot_json);
      const contextPolicy = recordValue(groupPolicy.context_policy_json);
      let rootRunId: string;
      const recipientRuns: Array<{
        run: RunRecord;
        segment_index: number;
      }> = [];

      if (group.root_run_id) {
        const rootRun = await repos.runs.getVisibleRun(
          input.space_id,
          identity.userId,
          group.root_run_id,
        );
        if (!rootRun || rootRun.run_group_id !== group.id) {
          throw new HttpError(409, "Agent group root run is not available");
        }
        rootRunId = group.root_run_id;
        for (let segmentIndex = 0; segmentIndex < routingSegments.length; segmentIndex += 1) {
          const segment = routingSegments[segmentIndex]!;
          for (const recipientAgentId of segment.recipient_agent_ids) {
            const run = await repos.runs.createGroupedAgentRun({
              agent_id: recipientAgentId,
              space_id: input.space_id,
              user_id: identity.userId,
              parent_run_id: rootRunId,
              root_run_id: rootRunId,
              run_group_id: group.id,
              workspace_id: rootRun.workspace_id,
              session_id: rootRun.session_id,
              project_id: rootRun.project_id,
              prompt: segment.content,
              instruction: optionalTrimmedOrNull(group.goal),
              model_override_json: roomTurnModelOverride({
                content,
                routingMode,
                routingSegments,
                currentSegmentIndex: segmentIndex,
                currentRecipientAgentId: recipientAgentId,
                plannedRecipientRunCount,
                recipientSnapshots,
              }),
              budget_json: group.budget_json,
              context_policy_json: contextPolicy,
            });
            recipientRuns.push({ run, segment_index: segmentIndex });
          }
        }
      } else {
        const firstSegment = routingSegments[0];
        const firstRecipientAgentId = firstSegment?.recipient_agent_ids[0];
        if (!firstSegment || !firstRecipientAgentId) {
          throw new HttpError(422, "recipient_segments is required");
        }
        const rootRun = await repos.runs.createQueuedRun({
          agent_id: firstRecipientAgentId,
          space_id: input.space_id,
          user_id: identity.userId,
          mode: "live",
          run_type: "agent",
          trigger_origin: "manual",
          prompt: firstSegment.content,
          instruction: optionalTrimmedOrNull(group.goal),
          model_override_json: roomTurnModelOverride({
            content,
            routingMode,
            routingSegments,
            currentSegmentIndex: 0,
            currentRecipientAgentId: firstRecipientAgentId,
            plannedRecipientRunCount,
            recipientSnapshots,
          }),
        });
        const linkedRootRun = await repos.runs.linkRunToGroupRoot({
          space_id: input.space_id,
          run_id: rootRun.id,
          run_group_id: group.id,
        });
        if (!linkedRootRun) {
          throw new HttpError(409, "Root run could not be linked to the agent group");
        }
        await repos.groups.updateGroupRootRun({
          space_id: input.space_id,
          group_id: group.id,
          root_run_id: linkedRootRun.id,
        });
        rootRunId = linkedRootRun.id;
        recipientRuns.push({ run: linkedRootRun, segment_index: 0 });
        for (let segmentIndex = 0; segmentIndex < routingSegments.length; segmentIndex += 1) {
          const segment = routingSegments[segmentIndex]!;
          for (let recipientIndex = 0; recipientIndex < segment.recipient_agent_ids.length; recipientIndex += 1) {
            if (segmentIndex === 0 && recipientIndex === 0) continue;
            const recipientAgentId = segment.recipient_agent_ids[recipientIndex]!;
            const run = await repos.runs.createGroupedAgentRun({
              agent_id: recipientAgentId,
              space_id: input.space_id,
              user_id: identity.userId,
              parent_run_id: rootRunId,
              root_run_id: rootRunId,
              run_group_id: group.id,
              workspace_id: linkedRootRun.workspace_id,
              session_id: linkedRootRun.session_id,
              project_id: linkedRootRun.project_id,
              prompt: segment.content,
              instruction: optionalTrimmedOrNull(group.goal),
              model_override_json: roomTurnModelOverride({
                content,
                routingMode,
                routingSegments,
                currentSegmentIndex: segmentIndex,
                currentRecipientAgentId: recipientAgentId,
                plannedRecipientRunCount,
                recipientSnapshots,
              }),
              budget_json: group.budget_json,
              context_policy_json: contextPolicy,
            });
            recipientRuns.push({ run, segment_index: segmentIndex });
          }
        }
      }

      const primaryRun = recipientRuns[0]?.run;
      if (!primaryRun) {
        throw new HttpError(422, "recipient_segments is required");
      }
      const routingSegmentsWithRuns = routingSegments.map((segment, index) => ({
        recipient_agent_ids: segment.recipient_agent_ids,
        content: segment.content,
        recipient_run_ids: recipientRuns
          .filter((entry) => entry.segment_index === index)
          .map((entry) => entry.run.id),
      }));
      const message = await repos.groups.createMessage({
        space_id: input.space_id,
        group_id: input.group_id,
        run_id: primaryRun.id,
        parent_message_id: input.parent_message_id ?? null,
        sender_actor_ref_json: { actor_type: "user", user_id: identity.userId },
        sender_user_id: identity.userId,
        message_type: "user_instruction",
        content,
        mentions_json: allRecipientAgentIds.map((agentId) => ({ agent_id: agentId })),
        metadata_json: {
          ...(input.metadata_json ?? {}),
          routing_mode: routingMode,
          routing_segments: routingSegmentsWithRuns,
          root_run_id: rootRunId,
          recipient_agent_id: allRecipientAgentIds[0],
          recipient_agent_ids: allRecipientAgentIds,
          recipient_run_id: primaryRun.id,
          recipient_run_ids: recipientRuns.map((entry) => entry.run.id),
        },
      });

      for (const { run: recipientRun } of recipientRuns) {
        const jobPayload: Record<string, unknown> = {
          run_id: recipientRun.id,
          run_group_id: group.id,
          root_run_id: rootRunId,
          trigger_origin: "manual",
        };
        if (recipientRun.parent_run_id) jobPayload.parent_run_id = recipientRun.parent_run_id;

        await repos.jobs.enqueue({
          job_type: "agent_run",
          space_id: input.space_id,
          user_id: identity.userId,
          agent_id: recipientRun.agent_id,
          workspace_id: recipientRun.workspace_id ?? null,
          payload: jobPayload,
        });
      }

      return { message };
    });
  }

  async spawnChildRun(identity: AgentGroupIdentity, input: SpawnChildRunInput): Promise<{
    delegation: RunDelegationRecord;
    child_run_id: string | null;
    policy_decision_record_id: string | null;
  }> {
    assertIdentitySpace(identity, input.space_id);
    if (input.manager_user_id !== identity.userId) {
      throw new HttpError(403, "manager_user_id must match the authenticated user");
    }
    return withDbTransaction(this.pool, async (client) =>
      this.spawnChildRunInTransaction(this.repos(client), identity, input),
    );
  }

  async spawnChildRunAuthorized(
    identity: AgentGroupIdentity,
    input: SpawnChildRunInput,
    policy: EnforceResult,
  ) {
    assertIdentitySpace(identity, input.space_id);
    if (input.manager_user_id !== identity.userId) throw new HttpError(403, "manager_user_id must match the authenticated user");
    return withDbTransaction(this.pool, async (client) =>
      this.spawnChildRunInTransaction(this.repos(client), identity, input, policy),
    );
  }

  async preflightSpawnChildRunPolicy(
    identity: AgentGroupIdentity,
    input: SpawnChildRunInput,
  ): Promise<EnforceResult> {
    assertIdentitySpace(identity, input.space_id);
    if (input.manager_user_id !== identity.userId) {
      throw new HttpError(403, "manager_user_id must match the authenticated user");
    }
    return withDbTransaction(this.pool, async (client) => {
      const repos = this.repos(client);
      const group = await repos.groups.lockGroup(input.space_id, input.group_id);
      if (!group || group.manager_user_id !== identity.userId) throw new HttpError(404, "Agent group not found in this space");
      if (group.status !== "active") throw new HttpError(409, `Agent group is not active (current status: ${group.status})`);
      if (!group.root_run_id || input.root_run_id !== group.root_run_id) throw new HttpError(409, "root_run_id must match the agent group root run");
      const parentRun = await repos.runs.getVisibleRun(input.space_id, identity.userId, input.parent_run_id);
      if (!parentRun || parentRun.run_group_id !== group.id) throw new HttpError(404, "Parent run not found in this agent group");
      if (parentRun.agent_id !== input.requesting_agent_id) throw new HttpError(403, "requesting_agent_id must match the parent run agent");
      if ((parentRun.root_run_id ?? parentRun.id) !== group.root_run_id) throw new HttpError(409, "Parent run does not belong to the group root lineage");
      await assertAgentsExist(repos.groups, input.space_id, identity.userId, [input.requesting_agent_id, input.target_agent_id]);
      return this.enforceSpawnPolicy(repos.groups, group, parentRun, input);
    });
  }

  async getTimeline(identity: AgentGroupIdentity, groupId: string, page: {
    limit: number;
    offset: number;
  }): Promise<AgentGroupTimeline> {
    const repo = new PgAgentGroupRepository(this.pool);
    const group = await this.requireManagedGroup(repo, identity, groupId);
    const [members, messages, delegations] = await Promise.all([
      repo.listMembers(identity.spaceId, groupId),
      repo.listMessages({
        space_id: identity.spaceId,
        group_id: groupId,
        limit: page.limit,
        offset: page.offset,
      }),
      repo.listDelegations(identity.spaceId, groupId),
    ]);
    return { group, members, messages, delegations };
  }

  async getTrace(identity: AgentGroupIdentity, groupId: string): Promise<{
    group: AgentRunGroupRecord;
    members: AgentGroupTimeline["members"];
    root_run_id: string | null;
    timeline: AgentGroupTimeline;
    child_run_ids: string[];
    artifact_ids: string[];
    proposal_ids: string[];
    policy_decision_record_ids: string[];
  }> {
    const repo = new PgAgentGroupRepository(this.pool);
    const timeline = await this.getTimeline(identity, groupId, { limit: 200, offset: 0 });
    const runIds = await repo.listRunIdsForGroup(identity.spaceId, groupId, identity.userId);
    const childRunIds = runIds.filter((runId) => runId !== timeline.group.root_run_id);
    const [artifactIds, proposalIds, policyDecisionRecordIds] = await Promise.all([
      repo.listArtifactIdsForRuns(identity.spaceId, identity.userId, runIds),
      repo.listProposalIdsForRuns(identity.spaceId, identity.userId, runIds),
      repo.listPolicyDecisionRecordIdsForGroup(identity.spaceId, groupId),
    ]);
    return {
      group: timeline.group,
      members: timeline.members,
      root_run_id: timeline.group.root_run_id,
      timeline,
      child_run_ids: childRunIds,
      artifact_ids: artifactIds,
      proposal_ids: proposalIds,
      policy_decision_record_ids: policyDecisionRecordIds,
    };
  }

  async changeStatus(
    identity: AgentGroupIdentity,
    groupId: string,
    status: "active" | "paused" | "cancelled",
  ): Promise<AgentRunGroupRecord> {
    return withDbTransaction(this.pool, async (client) => {
      const repo = new PgAgentGroupRepository(client);
      await this.requireManagedGroup(repo, identity, groupId);
      const updated = await repo.updateGroupStatus({
        space_id: identity.spaceId,
        group_id: groupId,
        status,
      });
      if (!updated) {
        throw new HttpError(409, "Agent group status could not be changed");
      }
      return updated;
    });
  }

  private repos(client: PoolClient): {
    groups: PgAgentGroupRepository;
    runs: PgRunRepository;
    jobs: PgJobQueueRepository;
  } {
    return {
      groups: new PgAgentGroupRepository(client),
      runs: new PgRunRepository(client),
      jobs: new PgJobQueueRepository(client),
    };
  }

  private async requireManagedGroup(
    repo: PgAgentGroupRepository,
    identity: AgentGroupIdentity,
    groupId: string,
  ): Promise<AgentRunGroupRecord> {
    const group = await repo.getGroup(identity.spaceId, groupId);
    if (!group || group.manager_user_id !== identity.userId) {
      throw new HttpError(404, "Agent group not found in this space");
    }
    return group;
  }

  private async spawnChildRunInTransaction(
    repos: {
      groups: PgAgentGroupRepository;
      runs: PgRunRepository;
      jobs: PgJobQueueRepository;
    },
    identity: AgentGroupIdentity,
    input: SpawnChildRunInput,
    preflightPolicy?: EnforceResult,
  ): Promise<{
    delegation: RunDelegationRecord;
    child_run_id: string | null;
    policy_decision_record_id: string | null;
  }> {
    const group = await repos.groups.lockGroup(input.space_id, input.group_id);
    if (!group || group.manager_user_id !== identity.userId) {
      throw new HttpError(404, "Agent group not found in this space");
    }
    if (group.status !== "active") {
      throw new HttpError(409, `Agent group is not active (current status: ${group.status})`);
    }
    if (!group.root_run_id || input.root_run_id !== group.root_run_id) {
      throw new HttpError(409, "root_run_id must match the agent group root run");
    }

    const parentRun = await repos.runs.getVisibleRun(
      input.space_id,
      identity.userId,
      input.parent_run_id,
    );
    if (!parentRun || parentRun.run_group_id !== group.id) {
      throw new HttpError(404, "Parent run not found in this agent group");
    }
    if (parentRun.agent_id !== input.requesting_agent_id) {
      throw new HttpError(403, "requesting_agent_id must match the parent run agent");
    }
    if ((parentRun.root_run_id ?? parentRun.id) !== group.root_run_id) {
      throw new HttpError(409, "Parent run does not belong to the group root lineage");
    }

    await assertAgentsExist(repos.groups, input.space_id, identity.userId, [
      input.requesting_agent_id,
      input.target_agent_id,
    ]);
    if (input.request_message_id) {
      const requestMessage = await repos.groups.getMessage(
        input.space_id,
        input.request_message_id,
      );
      if (!requestMessage || requestMessage.group_id !== input.group_id) {
        throw new HttpError(422, "request_message_id must belong to this agent group");
      }
      if (requestMessage.run_id && requestMessage.run_id !== input.parent_run_id) {
        throw new HttpError(422, "request_message_id must belong to the parent run");
      }
      if (
        requestMessage.sender_agent_id &&
        requestMessage.sender_agent_id !== input.requesting_agent_id
      ) {
        throw new HttpError(422, "request_message_id sender must match requesting_agent_id");
      }
    }

    // Policy preflight is deliberately before every domain write. The
    // delegation/message rows below are the authorized (or denied-evidence)
    // execution phase and reuse this durable decision.
    const policy = preflightPolicy ?? await this.enforceSpawnPolicy(repos.groups, group, parentRun, input);
    if (policy.status === "error") {
      throw new HttpError(503, policy.message ?? "Policy audit failed for child run delegation");
    }

    const requestMessageId = input.request_message_id ?? (await repos.groups.createMessage({
      space_id: input.space_id,
      group_id: input.group_id,
      run_id: input.parent_run_id,
      sender_actor_ref_json: {
        actor_type: "agent",
        agent_id: input.requesting_agent_id,
        requested_by_user_id: identity.userId,
      },
      sender_agent_id: input.requesting_agent_id,
      message_type: "delegation_request",
      content: input.instruction,
      mentions_json: [{ agent_id: input.target_agent_id }],
      metadata_json: { reason: input.reason ?? null },
    })).id;

    const delegation = await repos.groups.createDelegation({
      space_id: input.space_id,
      group_id: input.group_id,
      parent_run_id: input.parent_run_id,
      request_message_id: requestMessageId,
      requesting_agent_id: input.requesting_agent_id,
      target_agent_id: input.target_agent_id,
      requested_by_user_id: identity.userId,
      instruction: requiredTrimmed(input.instruction, "instruction"),
      reason: input.reason ?? null,
      budget_json: input.budget_json ?? {},
      context_policy_json: input.context_policy_json ?? {},
    });

    await repos.runs.appendRunEvent({
      run_id: input.parent_run_id,
      space_id: input.space_id,
      event_type: "delegation_requested",
      status: "pending",
      summary: "Child run delegation requested",
      metadata_json: {
        group_id: input.group_id,
        delegation_id: delegation.id,
        target_agent_id: input.target_agent_id,
      },
    });

    if (policy.status !== "allow") {
      const denied = await repos.groups.updateDelegationAfterPolicy({
        space_id: input.space_id,
        delegation_id: delegation.id,
        status: "policy_denied",
        policy_decision_record_id: policy.policy_decision_record_id ?? null,
      });
      await repos.runs.appendRunEvent({
        run_id: input.parent_run_id,
        space_id: input.space_id,
        event_type: "delegation_policy_denied",
        status: "failed",
        summary: policy.message ?? "Child run delegation denied by policy",
        metadata_json: {
          group_id: input.group_id,
          delegation_id: delegation.id,
          policy_decision_record_id: policy.policy_decision_record_id ?? null,
          reason_code: policy.decision?.reason_code ?? null,
        },
      });
      return {
        delegation: denied,
        child_run_id: null,
        policy_decision_record_id: policy.policy_decision_record_id ?? null,
      };
    }

    const childRun = await repos.runs.createDelegatedChildRun({
      agent_id: input.target_agent_id,
      space_id: input.space_id,
      user_id: identity.userId,
      parent_run_id: input.parent_run_id,
      root_run_id: input.root_run_id,
      run_group_id: input.group_id,
      delegation_id: delegation.id,
      instructed_by_agent_id: input.requesting_agent_id,
      workspace_id: parentRun.workspace_id,
      session_id: parentRun.session_id,
      project_id: parentRun.project_id,
      instruction: input.instruction,
      budget_json: input.budget_json ?? {},
      context_policy_json: input.context_policy_json ?? {},
    });
    const queued = await repos.groups.updateDelegationAfterPolicy({
      space_id: input.space_id,
      delegation_id: delegation.id,
      status: "queued",
      child_run_id: childRun.id,
      policy_decision_record_id: policy.policy_decision_record_id ?? null,
    });
    await repos.runs.appendRunEvent({
      run_id: input.parent_run_id,
      space_id: input.space_id,
      event_type: "delegation_queued",
      status: "succeeded",
      summary: "Child run delegation queued",
      metadata_json: {
        group_id: input.group_id,
        delegation_id: delegation.id,
        child_run_id: childRun.id,
        policy_decision_record_id: policy.policy_decision_record_id ?? null,
      },
    });
    await repos.jobs.enqueue({
      job_type: "agent_run",
      space_id: input.space_id,
      user_id: identity.userId,
      agent_id: input.target_agent_id,
      workspace_id: childRun.workspace_id ?? null,
      payload: {
        run_id: childRun.id,
        run_group_id: input.group_id,
        delegation_id: delegation.id,
        parent_run_id: input.parent_run_id,
        root_run_id: input.root_run_id,
        instructed_by_agent_id: input.requesting_agent_id,
        trigger_origin: "delegation",
      },
    });

    return {
      delegation: queued,
      child_run_id: childRun.id,
      policy_decision_record_id: policy.policy_decision_record_id ?? null,
    };
  }

  private async enforceSpawnPolicy(
    repo: PgAgentGroupRepository,
    group: AgentRunGroupRecord,
    parentRun: RunRecord,
    input: SpawnChildRunInput,
  ): Promise<EnforceResult> {
    const registry = await loadActionRegistry();
    const [requestingMember, targetMember, depth, fanoutCount, concurrencyCount] =
      await Promise.all([
        repo.getMemberWithAgentStatus({
          space_id: input.space_id,
          group_id: input.group_id,
          agent_id: input.requesting_agent_id,
          user_id: group.manager_user_id,
        }),
        repo.getMemberWithAgentStatus({
          space_id: input.space_id,
          group_id: input.group_id,
          agent_id: input.target_agent_id,
          user_id: group.manager_user_id,
        }),
        repo.runDepth({ space_id: input.space_id, run_id: input.parent_run_id }),
        repo.countDelegationsForParent({
          space_id: input.space_id,
          parent_run_id: input.parent_run_id,
        }),
        repo.countActiveDelegationsForGroup({
          space_id: input.space_id,
          group_id: input.group_id,
        }),
      ]);
    const widening = authorityWidening(parentRun, input.context_policy_json ?? {});
    const limits = delegationBudgetLimits(group.budget_json);
    const req: PolicyCheckRequest = {
      action: "run.spawn_child",
      actor_type: "agent",
      actor_id: input.requesting_agent_id,
      actor_ref: {
        agent_id: input.requesting_agent_id,
        requested_by_user_id: input.manager_user_id,
      },
      space_id: input.space_id,
      resource_space_id: input.space_id,
      resource_type: "run",
      resource_id: input.parent_run_id,
      run_id: input.parent_run_id,
      context: {
        group_id: input.group_id,
        parent_run_id: input.parent_run_id,
        root_run_id: input.root_run_id,
        requesting_agent_id: input.requesting_agent_id,
        target_agent_id: input.target_agent_id,
        manager_user_id: input.manager_user_id,
        group_status: group.status,
        requesting_agent_status: requestingMember?.agent_status ?? "missing",
        target_agent_status: targetMember?.agent_status ?? "missing",
        requesting_member_status: requestingMember?.status ?? "missing",
        target_member_status: targetMember?.status ?? "missing",
        depth: depth + 1,
        max_depth: limits.max_depth,
        fanout_count: fanoutCount,
        max_fanout: limits.max_fanout,
        concurrency_count: concurrencyCount,
        max_concurrency: limits.max_concurrency,
        group_budget_json: group.budget_json ?? {},
        requested_budget_json: input.budget_json ?? {},
        ...widening,
        trigger_origin: "delegation",
      },
      metadata_json: {
        group_id: input.group_id,
        delegation_id: null,
        parent_run_id: input.parent_run_id,
        root_run_id: input.root_run_id,
        requesting_agent_id: input.requesting_agent_id,
        target_agent_id: input.target_agent_id,
      },
      force_record: true,
    };
    return this.policyEnforcer(this.config, registry, req);
  }
}

async function assertAgentsActive(
  repo: PgAgentGroupRepository,
  spaceId: string,
  userId: string,
  agentIds: readonly string[],
): Promise<void> {
  const statuses = await repo.listAgentStatuses(spaceId, userId, agentIds);
  const byId = new Map(statuses.map((row) => [row.id, row.status]));
  for (const agentId of agentIds) {
    const status = byId.get(agentId);
    if (!status) throw new HttpError(404, `Agent '${agentId}' not found in this space`);
    if (status !== "active") {
      throw new HttpError(409, `Agent '${agentId}' is not active`);
    }
  }
}

async function assertActiveGroupMember(
  repo: PgAgentGroupRepository,
  spaceId: string,
  groupId: string,
  agentId: string,
  userId: string,
  fieldName: string,
): Promise<void> {
  const member = await repo.getMemberWithAgentStatus({
    space_id: spaceId,
    group_id: groupId,
    agent_id: agentId,
    user_id: userId,
  });
  if (!member) {
    throw new HttpError(422, `${fieldName} must be a member of this agent group`);
  }
  if (member.status !== "active") {
    throw new HttpError(409, `${fieldName} is not active in this agent group`);
  }
  if (member.agent_status !== "active") {
    throw new HttpError(409, `${fieldName} agent is not active`);
  }
}

async function assertAgentsExist(
  repo: PgAgentGroupRepository,
  spaceId: string,
  userId: string,
  agentIds: readonly string[],
): Promise<void> {
  const statuses = await repo.listAgentStatuses(spaceId, userId, uniqueIds(agentIds));
  const existing = new Set(statuses.map((row) => row.id));
  for (const agentId of agentIds) {
    if (!existing.has(agentId)) {
      throw new HttpError(404, `Agent '${agentId}' not found in this space`);
    }
  }
}

function messageRecipientSegmentsForInput(
  input: SendAgentGroupMessageInput,
  managerAgentId: string,
  fullContent: string,
): AgentGroupMessageRecipientSegment[] {
  const routingMode = input.routing_mode ?? "direct";
  if (routingMode === "agent_coordination") {
    return [{
      recipient_agent_ids: [requiredTrimmed(managerAgentId, "manager_agent_id")],
      content: fullContent,
    }];
  }
  if (routingMode !== "direct") {
    throw new HttpError(422, "routing_mode must be direct or agent_coordination");
  }
  const rawSegments = input.recipient_segments?.length
    ? input.recipient_segments
    : [{ recipient_agent_ids: [managerAgentId], content: fullContent }];
  const segments = rawSegments.map((segment, index) => ({
    recipient_agent_ids: uniqueIds(segment.recipient_agent_ids)
      .map((id) => requiredTrimmed(id, `recipient_segments[${index}].recipient_agent_ids`)),
    content: requiredTrimmed(segment.content, `recipient_segments[${index}].content`),
  })).filter((segment) => segment.recipient_agent_ids.length > 0);
  if (segments.length === 0) throw new HttpError(422, "recipient_segments is required");
  return segments;
}

function roomTurnModelOverride(input: {
  content: string;
  routingMode: "direct" | "agent_coordination" | null;
  routingSegments: readonly AgentGroupMessageRecipientSegment[];
  currentSegmentIndex: number;
  currentRecipientAgentId: string;
  plannedRecipientRunCount: number;
  recipientSnapshots: ReadonlyMap<string, AgentCapabilitySnapshotRecord>;
}): Record<string, unknown> | null {
  if (input.plannedRecipientRunCount <= 1) return null;
  return {
    chat_context_preamble: roomTurnContextPreamble(input),
  };
}

function roomTurnContextPreamble(input: {
  content: string;
  routingMode: "direct" | "agent_coordination" | null;
  routingSegments: readonly AgentGroupMessageRecipientSegment[];
  currentSegmentIndex: number;
  currentRecipientAgentId: string;
  plannedRecipientRunCount: number;
  recipientSnapshots: ReadonlyMap<string, AgentCapabilitySnapshotRecord>;
}): string {
  const segmentLines = input.routingSegments.map((segment, index) => {
    const labels = segment.recipient_agent_ids
      .map((agentId) => agentLabel(agentId, input.recipientSnapshots))
      .join(", ");
    const marker = index === input.currentSegmentIndex &&
      segment.recipient_agent_ids.includes(input.currentRecipientAgentId)
      ? " (this run)"
      : "";
    return `${index + 1}. ${labels}${marker}\n   Task: ${segment.content}`;
  });
  const currentSegment = input.routingSegments[input.currentSegmentIndex];
  const currentTask = currentSegment?.content ?? "";
  return [
    "Room turn routing context:",
    "The user's message was split into multiple auditable recipient runs in the same room turn.",
    "Your run prompt may contain only your own segment; use this context to understand whether your answer depends on sibling room runs.",
    `Routing mode: ${input.routingMode ?? "direct"}`,
    `Original user message:\n${input.content}`,
    `Current recipient: ${agentLabel(input.currentRecipientAgentId, input.recipientSnapshots)}`,
    currentTask ? `Current segment task:\n${currentTask}` : null,
    `Recipient segments:\n${segmentLines.join("\n")}`,
    "If your task requires outputs, conclusions, comparisons, validation, or a combined response from other recipient segments in this same user turn, call agent.wait_for_results with scope=current_turn before answering.",
    "If you can answer from your own segment alone, answer normally.",
    "When a waited run resumes, use the completed agent results provided to the continuation prompt. Do not say sibling results are unavailable before using the wait tool.",
  ].filter((part): part is string => typeof part === "string" && part.length > 0).join("\n\n");
}

function agentLabel(
  agentId: string,
  snapshots: ReadonlyMap<string, AgentCapabilitySnapshotRecord>,
): string {
  const name = snapshots.get(agentId)?.name?.trim();
  return name && name.length > 0 ? name : agentId;
}

function memberCapabilitySnapshot(
  snapshot: AgentCapabilitySnapshotRecord | undefined,
): Record<string, unknown> {
  if (!snapshot) return {};
  return {
    agent_id: snapshot.id,
    name: snapshot.name,
    ...(snapshot.description ? { description: snapshot.description } : {}),
    ...(snapshot.role_instruction ? { role_instruction: snapshot.role_instruction } : {}),
    capabilities: Array.isArray(snapshot.capabilities_json) ? snapshot.capabilities_json : [],
  };
}

export function authorityWidening(
  parentRun: Pick<RunRecord, "workspace_id" | "project_id" | "model_provider_id">,
  contextPolicy: Record<string, unknown>,
): {
  context_widens_authority: boolean;
  workspace_scope_widens: boolean;
  project_scope_widens: boolean;
  credential_scope_widens: boolean;
  memory_scope_widens: boolean;
  durable_write_scope_widens: boolean;
} {
  const workspaceScopeWidens = valuesForKey(contextPolicy, "workspace_id").some((value) =>
    widensNullableId(parentRun.workspace_id, value),
  );
  const projectScopeWidens = valuesForKey(contextPolicy, "project_id").some((value) =>
    widensNullableId(parentRun.project_id, value),
  );
  const credentialScopeWidens =
    hasAnyKeyWithValue(contextPolicy, [
      "credential_id",
      "credential_profile_id",
      "provider_credential_id",
    ]) ||
    valuesForKey(contextPolicy, "model_provider_id").some((value) =>
      widensNullableId(parentRun.model_provider_id, value),
    );
  const memoryScopeWidens =
    hasBooleanTrue(contextPolicy, ["include_personal_memory", "personal_memory"]) ||
    valuesForKey(contextPolicy, "memory_scope").some((value) =>
      ["all", "private", "personal"].includes(String(value ?? "")),
    );
  const durableWriteScopeWidens =
    hasBooleanTrue(contextPolicy, [
      "memory_write",
      "knowledge_write",
      "direct_memory_write",
      "direct_knowledge_write",
      "write_memory",
      "write_knowledge",
    ]) ||
    hasAnyNonEmptyValue(contextPolicy, [
      "writable_scopes",
      "write_scopes",
      "memory_writable_scopes",
      "knowledge_writable_scopes",
    ]) ||
    hasBooleanFalse(contextPolicy, ["requires_proposal", "proposal_only"]);
  return {
    context_widens_authority:
      workspaceScopeWidens ||
      projectScopeWidens ||
      credentialScopeWidens ||
      memoryScopeWidens ||
      durableWriteScopeWidens,
    workspace_scope_widens: workspaceScopeWidens,
    project_scope_widens: projectScopeWidens,
    credential_scope_widens: credentialScopeWidens,
    memory_scope_widens: memoryScopeWidens,
    durable_write_scope_widens: durableWriteScopeWidens,
  };
}

function widensNullableId(parentValue: string | null | undefined, requested: unknown): boolean {
  if (typeof requested !== "string" || !requested.trim()) return false;
  return requested !== parentValue;
}

function delegationBudgetLimits(budget: Record<string, unknown> | null): {
  max_depth: number;
  max_fanout: number;
  max_concurrency: number;
} {
  return {
    max_depth: boundedBudgetLimit(budget, "max_depth", MAX_DELEGATION_DEPTH),
    max_fanout: boundedBudgetLimit(budget, "max_fanout", MAX_PARENT_FANOUT),
    max_concurrency: boundedBudgetLimit(budget, "max_concurrency", MAX_GROUP_CONCURRENCY),
  };
}

function boundedBudgetLimit(
  budget: Record<string, unknown> | null,
  key: string,
  defaultLimit: number,
): number {
  const value = budget?.[key];
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) return defaultLimit;
  return Math.min(value, defaultLimit);
}

function valuesForKey(value: unknown, key: string): unknown[] {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap((item) => valuesForKey(item, key));
  const record = value as Record<string, unknown>;
  return [
    ...(Object.prototype.hasOwnProperty.call(record, key) ? [record[key]] : []),
    ...Object.values(record).flatMap((item) => valuesForKey(item, key)),
  ];
}

function hasAnyKeyWithValue(value: unknown, keys: readonly string[]): boolean {
  return keys.some((key) =>
    valuesForKey(value, key).some((candidate) => typeof candidate === "string" && candidate !== ""),
  );
}

function hasAnyNonEmptyValue(value: unknown, keys: readonly string[]): boolean {
  return keys.some((key) =>
    valuesForKey(value, key).some((candidate) => {
      if (typeof candidate === "string") return candidate.trim() !== "";
      if (Array.isArray(candidate)) return candidate.length > 0;
      if (candidate && typeof candidate === "object") return Object.keys(candidate).length > 0;
      return candidate !== null && candidate !== undefined && candidate !== false;
    }),
  );
}

function hasBooleanTrue(value: unknown, keys: readonly string[]): boolean {
  return keys.some((key) => valuesForKey(value, key).some((candidate) => candidate === true));
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function hasBooleanFalse(value: unknown, keys: readonly string[]): boolean {
  return keys.some((key) => valuesForKey(value, key).some((candidate) => candidate === false));
}

function assertIdentitySpace(identity: AgentGroupIdentity, requestSpaceId: string): void {
  if (identity.spaceId !== requestSpaceId) {
    throw new HttpError(403, "space_id must match the authenticated space");
  }
}

function uniqueIds(ids: readonly string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of ids) {
    const id = raw.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

function requiredTrimmed(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new HttpError(422, `${field} is required`);
  return normalized;
}

function optionalTrimmed(value: string | null | undefined): string {
  return value?.trim() ?? "";
}

export function optionalTrimmedOrNull(value: string | null | undefined): string | null {
  const normalized = optionalTrimmed(value);
  return normalized || null;
}
