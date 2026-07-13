import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type {
  MessageOut,
  RunJobResult,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ModuleContext } from "../../gateway/routeRegistry";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { introspectIdentity } from "../auth/identity";
import { loadProtocol } from "../providers/protocolRuntime";
import { PgSessionRepository } from "../sessions/repository";
import { enqueueSessionCondense } from "../sessions/condenseJob";
import {
  PgRunRepository,
  RunCreateValidationError,
  type RunChatResultRecord,
} from "../runs/repository";
import { RunOrchestrationService } from "../runs/orchestrationService";
import { RunMaterializationService } from "../runs/materializationService";
import { sharedCliProcessRegistry } from "../runs/processRegistry";
import { runToOut } from "../runs/runReadModel";
import { PgCodePatchCollector, PgWorkspaceManager } from "../workspaces";
import { PgVerificationEngine } from "../runs/verification";
import { RunBudgetExceededError, RunBudgetSourceReferenceError } from "../runs/budgetEnforcement";
import { PgContextSnapshotRepository } from "../memory/contextSnapshotRepository";
import {
  dbPool,
  parsePage,
  query as routeQuery,
  sendRouteError,
} from "../routeUtils/common";
import { PgProposalRepository } from "../proposals/repository";
import { PgAgentChatRepository, PgAgentRepository } from "./repository";
import { loadProjectChatActionPreviews } from "./projectChatActionPreviews";
import { assertProjectReadable } from "../projects/access";
import { getBuiltInWorkflowTemplate } from "../capabilities/workflowRegistry";
import { resolveWorkflowVersionId } from "../capabilities/workflowAssets";
import { workflowContractInput } from "../capabilities/workflowContract";
import {
  ChatContextCandidateCollector,
  ChatContextError,
  ContextPrepareService,
} from "../context";
import { PgRunContextRepository } from "../context/repository";
import {
  buildChatConversationWindow,
  buildChatContext,
  composeChatPrompt,
  conversationWindowToMessages,
  renderConversationWindow,
  renderContextPreamble,
} from "./chatContextBuilder";
import {
  applyAgentIdentityPatch,
  configPatch,
  hasConfigPatch,
  jsonBody,
  nullableBodyString,
  optionalArrayBody,
  optionalBooleanBody,
  optionalRecordBody,
  params,
  recordValue,
  requiredBodyString,
  sendDomainError,
  stringValue,
} from "./agentRouteInputs";

const MAX_MESSAGE_CHARS = 8000;
const PROJECT_CHAT_ACTIONS=["source.connection.propose_create","project.source.propose_bind","source.backfill.propose_start"] as const;
export function projectChatCapabilities(toolPermissions:Record<string,unknown>|undefined){const allowed=Array.isArray(toolPermissions?.allowed_tools)?new Set(toolPermissions.allowed_tools.filter((item):item is string=>typeof item==="string")):new Set<string>();return PROJECT_CHAT_ACTIONS.filter(action=>allowed.has(action));}

interface AgentChatServices {
  agents: Pick<PgAgentChatRepository, "getAgentForChat">;
  sessions: Pick<
    PgSessionRepository,
    | "getSession"
    | "createSession"
    | "addMessage"
    | "listRecentMessagesForContext"
    | "getLatestSummaryForContext"
  >;
  runs: Pick<PgRunRepository, "getChatRunResult" | "createQueuedRun">;
  orchestration: Pick<RunOrchestrationService, "executeRun">;
  context: Pick<ChatContextCandidateCollector, "fetchCandidates">;
  snapshots: Pick<PgContextSnapshotRepository, "persistChatSnapshot">;
  // Enqueues the off-request background LLM session condense (pattern.v1 fallback).
  condense: { enqueue: (input: SessionCondenseEnqueueInput) => Promise<void> };
}

interface SessionCondenseEnqueueInput {
  space_id: string;
  user_id: string;
  session_id: string;
  agent_id?: string | null;
  agent_version_id?: string | null;
}

interface PreparedChatRun {
  run_id: string;
}

type AgentChatServicesFactory = (context: ModuleContext) => AgentChatServices;
type AgentChatIdentity = { spaceId: string; userId: string };
type AgentChatIdentityOverride =
  | AgentChatIdentity
  | ((request: FastifyRequest) => Promise<AgentChatIdentity | null> | AgentChatIdentity | null);

let servicesFactoryOverride: AgentChatServicesFactory | null = null;
let identityOverride: AgentChatIdentityOverride | null = null;

export function __setAgentChatServicesFactoryForTests(
  factory: AgentChatServicesFactory | null,
): void {
  servicesFactoryOverride = factory;
}

export function __setAgentChatIdentityForTests(
  identity: AgentChatIdentityOverride | null,
): void {
  identityOverride = identity;
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const agentRepository = () => PgAgentRepository.fromConfig(context.config);

  app.get("/api/v1/agents/runs", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const q = routeQuery(request);
      const page = parsePage(q);
      const repository = PgRunRepository.fromConfig(context.config);
      const runs = await repository.listRuns({
        space_id: identity.spaceId,
        user_id: identity.userId,
        status: q.status ?? null,
        mode: q.mode ?? null,
        agent_id: q.agent_id ?? null,
        workspace_id: q.workspace_id ?? null,
        project_id: q.project_id ?? null,
        limit: page.limit,
        offset: page.offset,
      });
      return reply.send(runs.map((run) => runToOut(run)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/runs/:runId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const repository = PgRunRepository.fromConfig(context.config);
      const run = await repository.getVisibleRun(identity.spaceId, identity.userId, params(request).runId ?? "");
      if (!run) {
        return reply.code(404).send({ detail: "Run not found in this space" });
      }
      return reply.send(runToOut(run));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/:agentId/runs", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const q = routeQuery(request);
      const page = parsePage(q);
      const repository = PgRunRepository.fromConfig(context.config);
      const runs = await repository.listRuns({
        space_id: identity.spaceId,
        user_id: identity.userId,
        status: q.status ?? null,
        mode: q.mode ?? null,
        agent_id: params(request).agentId ?? "",
        workspace_id: q.workspace_id ?? null,
        project_id: q.project_id ?? null,
        limit: page.limit,
        offset: page.offset,
      });
      return reply.send(runs.map((run) => runToOut(run)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/:agentId/proposals", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const q = routeQuery(request);
      const page = parsePage(q);
      const agentId = params(request).agentId ?? "";
      const agent = await agentRepository().getVisible(identity.spaceId, identity.userId, agentId);
      if (!agent) return reply.code(404).send({ detail: "Agent not found" });
      const status = q.status === "all" ? null : q.status ?? "pending";
      const proposalRepository = new PgProposalRepository(dbPool(context.config));
      return reply.send(await proposalRepository.listVisible(identity.spaceId, identity.userId, {
        status,
        agentId,
        limit: page.limit,
        offset: page.offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const q = routeQuery(request);
      const page = parsePage(q);
      const agents = await agentRepository().list(identity.spaceId, identity.userId, {
        createdByUserId: q.created_by_user_id ?? null,
        visibility: q.visibility ?? null,
        status: q.status ?? "active",
        limit: page.limit,
        offset: page.offset,
      });
      return reply.send(agents);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/agents", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const body = jsonBody(request);
      const agent = await agentRepository().create({
        spaceId: identity.spaceId,
        userId: identity.userId,
        name: requiredBodyString(body, "name"),
        description: nullableBodyString(body, "description") ?? null,
        visibility: nullableBodyString(body, "visibility") ?? "private",
        roleInstruction: nullableBodyString(body, "role_instruction") ?? null,
        systemPrompt: nullableBodyString(body, "system_prompt") ?? null,
        defaultModelProviderId: nullableBodyString(body, "default_model_provider_id") ?? null,
        defaultModel: nullableBodyString(body, "default_model") ?? null,
        adapterType: nullableBodyString(body, "adapter_type") ?? null,
        modelConfigJson: optionalRecordBody(body, "model_config_json"),
        runtimeConfigJson: optionalRecordBody(body, "runtime_config_json"),
        contextPolicyJson: optionalRecordBody(body, "context_policy_json"),
        memoryPolicyJson: optionalRecordBody(body, "memory_policy_json"),
        capabilitiesJson: optionalArrayBody(body, "capabilities_json"),
        toolPermissionsJson: optionalRecordBody(body, "tool_permissions_json"),
        runtimePolicyJson: optionalRecordBody(body, "runtime_policy_json"),
      });
      return reply.code(201).send(agent);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/default-assistant", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const agent = await agentRepository().getDefaultAssistant(identity.spaceId);
      if (!agent) return reply.code(404).send({ detail: "No default Assistant in this space" });
      return reply.send(agent);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/agents/default-assistant", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await agentRepository().ensureDefaultAssistant(identity.spaceId, identity.userId));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/default-assistant/settings", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await agentRepository().getAssistantSettings(identity.spaceId));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/agents/default-assistant/settings", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await agentRepository().updateAssistantSettings(identity.spaceId, jsonBody(request), {
          actorUserId: identity.userId,
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/:agentId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const agent = await agentRepository().getVisible(identity.spaceId, identity.userId, params(request).agentId ?? "");
      if (!agent) return reply.code(404).send({ detail: "Agent not found" });
      return reply.send(agent);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/agents/:agentId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const body = jsonBody(request);
      const repo = agentRepository();
      const agentId = params(request).agentId ?? "";
      let agent = await applyAgentIdentityPatch(repo, identity.spaceId, identity.userId, agentId, body);
      if (hasConfigPatch(body)) {
        agent = await repo.updateConfig(identity.spaceId, agentId, configPatch(body, identity.userId));
      }
      if (!agent) {
        agent = await repo.get(identity.spaceId, agentId);
        if (!agent) return reply.code(404).send({ detail: "Agent not found" });
      }
      return reply.send(agent);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/agents/:agentId/config", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const agent = await agentRepository().updateConfig(
        identity.spaceId,
        params(request).agentId ?? "",
        configPatch(jsonBody(request), identity.userId),
      );
      return reply.send(agent);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/:agentId/runtime-profiles", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const profiles = await agentRepository().listRuntimeProfiles(
        identity.spaceId,
        params(request).agentId ?? "",
      );
      return reply.send(profiles);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/agents/:agentId/runtime-profiles", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const body = jsonBody(request);
      const profile = await agentRepository().createRuntimeProfile(
        identity.spaceId,
        params(request).agentId ?? "",
        {
          name: requiredBodyString(body, "name"),
          adapterType: requiredBodyString(body, "adapter_type"),
          modelProviderId: nullableBodyString(body, "model_provider_id"),
          modelName: nullableBodyString(body, "model_name"),
          credentialProfileId: nullableBodyString(body, "credential_profile_id"),
          runtimeConfigJson: optionalRecordBody(body, "runtime_config_json"),
          runtimePolicyJson: optionalRecordBody(body, "runtime_policy_json"),
          enabled: optionalBooleanBody(body, "enabled"),
          isDefault: optionalBooleanBody(body, "is_default"),
        },
      );
      return reply.code(201).send(profile);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/agents/:agentId/runtime-profiles/:profileId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const body = jsonBody(request);
      const profile = await agentRepository().updateRuntimeProfile(
        identity.spaceId,
        params(request).agentId ?? "",
        params(request).profileId ?? "",
        {
          name: Object.hasOwn(body, "name") ? requiredBodyString(body, "name") : undefined,
          adapterType: Object.hasOwn(body, "adapter_type")
            ? requiredBodyString(body, "adapter_type")
            : undefined,
          modelProviderId: Object.hasOwn(body, "model_provider_id")
            ? nullableBodyString(body, "model_provider_id")
            : undefined,
          modelName: Object.hasOwn(body, "model_name")
            ? nullableBodyString(body, "model_name")
            : undefined,
          credentialProfileId: Object.hasOwn(body, "credential_profile_id")
            ? nullableBodyString(body, "credential_profile_id")
            : undefined,
          runtimeConfigJson: optionalRecordBody(body, "runtime_config_json"),
          runtimePolicyJson: optionalRecordBody(body, "runtime_policy_json"),
          enabled: optionalBooleanBody(body, "enabled"),
          isDefault: optionalBooleanBody(body, "is_default"),
        },
      );
      return reply.send(profile);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/:agentId/current-version", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const version = await agentRepository().getCurrentVersion(
        identity.spaceId,
        params(request).agentId ?? "",
      );
      if (!version) return reply.code(404).send({ detail: "Agent has no current version" });
      return reply.send(version);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/:agentId/versions", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const versions = await agentRepository().listVersions(
        identity.spaceId,
        params(request).agentId ?? "",
      );
      return reply.send(versions);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/agents/:agentId/versions/:versionId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const version = await agentRepository().getVersion(
        identity.spaceId,
        p.agentId ?? "",
        p.versionId ?? "",
      );
      return reply.send(version);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/agents/:agentId/versions/:versionId/restore", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const agent = await agentRepository().restoreVersion(
        identity.spaceId,
        p.agentId ?? "",
        p.versionId ?? "",
        identity.userId,
      );
      return reply.send(agent);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  const createRun = async (request: FastifyRequest, reply: FastifyReply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const agentId = params(request).agentId ?? "";
    const body = jsonBody(request);
    const repository = PgRunRepository.fromConfig(context.config);
    try {
      const contextArtifactIds = optionalStringArrayBody(body, "context_artifact_ids");
      const workspaceId = stringValue(body.workspace_id);
      const projectId = stringValue(body.project_id);
      const workflowTemplateId = stringValue(body.workflow_template_id);
      const workflowTemplate = workflowTemplateId ? getBuiltInWorkflowTemplate(workflowTemplateId) : null;
      if (workflowTemplateId && !workflowTemplate) {
        throw new RunCreateValidationError(`Workflow template '${workflowTemplateId}' not found`, 422);
      }
      const workflowVersionId = workflowTemplate
        ? await resolveWorkflowVersionId(dbPool(context.config), {
            spaceId: identity.spaceId,
            userId: identity.userId,
            projectId,
            agentId,
            workflowId: workflowTemplate.id,
          })
        : null;
      await validateContextArtifactAttachments(context, identity, contextArtifactIds ?? [], workspaceId, projectId);
      const run = await repository.createQueuedRunWithBudgetAdmission({
        agent_id: agentId,
        space_id: identity.spaceId,
        user_id: identity.userId,
        mode: stringValue(body.mode) ?? "live",
        run_type: stringValue(body.run_type) ?? "agent",
        trigger_origin: stringValue(body.trigger_origin) ?? "manual",
        session_id: stringValue(body.session_id),
        workspace_id: workspaceId,
        project_id: projectId,
        prompt: stringValue(body.prompt),
        instruction: stringValue(body.instruction),
        scheduled_at: stringValue(body.scheduled_at),
        parent_run_id: stringValue(body.parent_run_id),
        runtime_profile_id: stringValue(body.runtime_profile_id),
        capability_id: stringValue(body.capability_id),
        capabilities_json: optionalArrayBody(body, "capabilities_json"),
        context_artifact_ids: contextArtifactIds,
        workflow_version_id: workflowVersionId,
        contract_snapshot: workflowTemplate
          ? workflowContractInput({
              template: workflowTemplate,
              workflowVersionId,
              config: optionalRecordBody(body, "workflow_config_json") ?? {},
              projectId,
              workspaceId,
            })
          : undefined,
      });
      return reply.code(201).send(runToOut(run));
    } catch (error) {
      if (error instanceof RunCreateValidationError) {
        return reply.code(error.statusCode).send({ detail: error.message });
      }
      if (error instanceof RunBudgetExceededError || error instanceof RunBudgetSourceReferenceError) {
        return sendRouteError(reply, error);
      }
      throw error;
    }
  };
  app.post("/api/v1/agents/:agentId/runs", createRun);
  app.post("/api/v1/agents/:agentId/run", createRun);

  app.post("/api/v1/agents/:agentId/chat", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const agentId = params(request).agentId ?? "";
    const body = jsonBody(request);
    const rawMessage = typeof body.message === "string" ? body.message.trim() : "";
    if (!rawMessage) return reply.code(422).send({ detail: "message must not be empty" });
    if (rawMessage.length > MAX_MESSAGE_CHARS) {
      return reply.code(422).send({
        detail: `message exceeds ${MAX_MESSAGE_CHARS} characters`,
      });
    }

    try {
      const protocol = await loadProtocol();
      const req = protocol.ChatTurnRequestSchema.parse({
        ...body,
        message: rawMessage,
      });
      const services = agentChatServices(context);
      let projectContextPreamble:string|null=null;
      if(req.project_id){const database=dbPool(context.config);await assertProjectReadable(database,identity.spaceId,req.project_id,identity.userId);const project=await database.query<{name:string;description:string|null;current_focus:string|null}>(`SELECT name,description,current_focus FROM projects WHERE id=$1 AND space_id=$2 AND deleted_at IS NULL`,[req.project_id,identity.spaceId]);const row=project.rows[0];if(!row)return reply.code(404).send({detail:"Project not found"});projectContextPreamble=[`Project: ${row.name}`,row.description?`Description: ${row.description}`:null,row.current_focus?`Current focus: ${row.current_focus}`:null].filter(Boolean).join("\n");}
      const agent = await services.agents.getAgentForChat(identity.spaceId, agentId);
      if (!agent) {
        return reply
          .code(404)
          .send({ detail: `Agent '${agentId}' not found in this space` });
      }
      if (!agent.current_version_id) {
        return reply
          .code(400)
          .send({ detail: `Agent '${agentId}' has no current version` });
      }

      const session = req.session_id
        ? await services.sessions.getSession(identity.spaceId, identity.userId, req.session_id)
        : await services.sessions.createSession(identity.spaceId, identity.userId, {
            title: `${agent.name || "Assistant"} chat`,
            projectId:req.project_id,
          });
      if (!session) return reply.code(404).send({ detail: "session not found in this space" });
      if((session.project_id??null)!==(req.project_id??null))return reply.code(409).send({detail:"session belongs to a different Project context"});

      const userMessage = await services.sessions.addMessage(
        identity.spaceId,
        identity.userId,
        session.id,
        { role: "user", content: rawMessage },
      );
      if (!userMessage) return reply.code(404).send({ detail: "session not found in this space" });

      const prepared = await prepareChatRun(services, {
        agentId: agent.id,
        agentVersionId: agent.current_version_id,
        spaceId: identity.spaceId,
        userId: identity.userId,
        sessionId: session.id,
        message: rawMessage,
        currentMessage: userMessage,
        projectId:req.project_id,
        projectContextPreamble,
        projectActionCapabilities:projectChatCapabilities(agent.tool_permissions_json),
      });

      const result = await services.orchestration.executeRun({
        run_id: prepared.run_id,
        space_id: identity.spaceId,
        worker_id: `chat:${resolveRequestId(request)}`,
        command_source: "http",
      });
      const run = await services.runs.getChatRunResult(identity.spaceId, prepared.run_id);
      const outcome = chatOutcome(run, result);
      const actionPreviews=req.project_id?await loadProjectChatActionPreviews(dbPool(context.config),identity.spaceId,prepared.run_id):[];
      if (!outcome.ok) {
        if(req.project_id)await services.sessions.addMessage(identity.spaceId,identity.userId,session.id,{role:"assistant",content:outcome.error,metadata:{run_id:prepared.run_id,action_previews:actionPreviews}});
        return reply.send(
          protocol.ChatTurnResultSchema.parse({
            session_id: session.id,
            run_id: prepared.run_id,
            ok: false,
            error: outcome.error,
            error_code: outcome.errorCode,
            ...(req.project_id?{action_previews:actionPreviews}:{}),
          }),
        );
      }

      const replyText = outcome.reply.trim();
      const assistantMessage = await services.sessions.addMessage(
        identity.spaceId,
        identity.userId,
        session.id,
        {
          role: "assistant",
          content: replyText,
          metadata: { run_id: prepared.run_id,...(req.project_id?{action_previews:actionPreviews}:{}) },
        },
      );
      if (!assistantMessage) {
        return reply.code(404).send({ detail: "session not found in this space" });
      }
      // Best-effort: enqueue the background session condense now that this turn
      // is durable, so the next turn's conversation window can use the summary.
      // It runs the LLM condenser off the request path (pattern.v1 fallback);
      // SessionSummary is regenerable derived context, so an enqueue failure must
      // never fail the chat turn the user already got a reply for.
      try {
        await services.condense.enqueue({
          space_id: identity.spaceId,
          user_id: identity.userId,
          session_id: session.id,
          agent_id: agent.id,
          agent_version_id: agent.current_version_id,
        });
      } catch (condenseError) {
        request.log?.warn?.(
          { err: condenseError, session_id: session.id },
          "session condense enqueue failed (non-fatal)",
        );
      }
      return reply.send(
        protocol.ChatTurnResultSchema.parse({
          session_id: session.id,
          run_id: prepared.run_id,
          ok: true,
          reply: replyText,
          ...(req.project_id?{action_previews:actionPreviews}:{}),
        }),
      );
    } catch (error) {
      if (error instanceof ChatContextError) {
        return reply.code(error.statusCode).send(error.body);
      }
      if (error instanceof RunCreateValidationError) {
        return reply.code(error.statusCode).send({ detail: error.message });
      }
      return sendDomainError(reply, error);
    }
  });
}

async function validateContextArtifactAttachments(
  context: ModuleContext,
  identity: { spaceId: string; userId: string },
  artifactIds: readonly string[],
  workspaceId?: string | null,
  projectId?: string | null,
): Promise<void> {
  if (artifactIds.length === 0) return;
  const selections = await PgRunContextRepository
    .fromConfig(context.config)
    .selectArtifactAttachments({
      spaceId: identity.spaceId,
      userId: identity.userId,
      workspaceId: workspaceId ?? null,
      projectId: projectId ?? null,
      artifactIds,
    });
  const blocked = selections.find((selection) => (recordValue(selection.item) ?? {}).approved === false);
  if (!blocked) return;
  const reason = stringValue((recordValue(blocked.item) ?? {}).rejection_reason) ?? "artifact is not attachable";
  throw new RunCreateValidationError(`context_artifact_ids invalid: ${reason}`, 422);
}

function optionalStringArrayBody(
  body: Record<string, unknown>,
  key: string,
): string[] | null | undefined {
  const value = optionalArrayBody(body, key);
  if (value === undefined || value === null) return value;
  if (value.length > 8) {
    throw new RunCreateValidationError(`${key} must contain at most 8 items`, 422);
  }
  return value.map((item) => {
    if (typeof item !== "string" || !item.trim()) {
      throw new RunCreateValidationError(`${key} must contain non-empty strings`, 422);
    }
    return item.trim();
  });
}

/**
 * Resolve the queued run for a chat turn.
 *
 * The server owns chat context build natively: collect per-source
 * candidates (native server DB reads) → budget/dedup loop → compose prompt →
 * server run creation + snapshot persistence.
 */
async function prepareChatRun(
  services: AgentChatServices,
  input: {
    agentId: string;
    agentVersionId: string | null | undefined;
    spaceId: string;
    userId: string;
    sessionId: string;
    message: string;
    currentMessage: MessageOut;
    projectId?:string|null;
    projectContextPreamble?:string|null;
    projectActionCapabilities?:string[];
  },
): Promise<PreparedChatRun> {
  const [candidates, recentMessages, sessionSummary] = await Promise.all([
    services.context.fetchCandidates({
      agent_id: input.agentId,
      space_id: input.spaceId,
      user_id: input.userId,
      session_id: input.sessionId,
      message: input.message,
      project_id:input.projectId,
    }),
    services.sessions.listRecentMessagesForContext(
      input.spaceId,
      input.userId,
      input.sessionId,
      80,
    ),
    services.sessions.getLatestSummaryForContext(input.spaceId, input.sessionId),
  ]);
  if (!recentMessages) {
    throw new ChatContextError("session not found in this space", 404);
  }
  const conversationWindow = buildChatConversationWindow({
    messages: recentMessages,
    currentMessage: input.currentMessage,
    summary: sessionSummary,
  });
  const bundle = buildChatContext(candidates);
  const retrievedPreamble = renderContextPreamble(bundle.items);
  const contextPreamble=[input.projectContextPreamble,retrievedPreamble].filter(Boolean).join("\n\n");
  const projectTokenEstimate=Math.ceil((input.projectContextPreamble?.length??0)/4);
  const composedPrompt = composeChatPrompt(
    contextPreamble,
    renderConversationWindow(conversationWindow),
  );

  const created = await services.runs.createQueuedRun({
    agent_id: input.agentId,
    space_id: input.spaceId,
    user_id: input.userId,
    mode: "live",
    run_type: "agent",
    trigger_origin: "manual",
    session_id: input.sessionId,
    project_id:input.projectId??null,
    capabilities_json:input.projectId?input.projectActionCapabilities:undefined,
    prompt: composedPrompt,
    model_override_json: {
      messages: conversationWindowToMessages(conversationWindow),
      chat_context_preamble: contextPreamble || null,
      conversation_window_version: conversationWindow.version,
    },
  });

  if (created.context_snapshot_id) {
    await services.snapshots.persistChatSnapshot({
      contextSnapshotId: created.context_snapshot_id,
      spaceId: input.spaceId,
      runId: created.id,
      userId: input.userId,
      agentId: created.agent_id ?? input.agentId,
      tokenEstimate: bundle.token_count + conversationWindow.token_count+projectTokenEstimate,
      // Mirrors the ContextRequest persisted by the legacy prepare-run path
      // (request defaults, not policy-resolved).
      requestJson: {
        space_id: input.spaceId,
        user_id: input.userId,
        agent_version_id: input.agentVersionId ?? null,
        session_id: input.sessionId,
        workspace_id: null,
        project_id: input.projectId??null,
        run_id: created.id,
        user_message_id: input.currentMessage.id,
        user_message: input.message,
        manual_context: [],
        max_tokens: 4000,
        max_items: 20,
        conversation_window: conversationWindow.trace,
      },
      retrievalTraceJson: {
        project_context:input.projectId?{project_id:input.projectId,included:Boolean(input.projectContextPreamble)}:null,
        chat_context: bundle.retrieval_trace,
        conversation_window: conversationWindow.trace,
      },
      tokenBudgetJson: {
        chat_context: {
          token_count: bundle.token_count+projectTokenEstimate,
          max_tokens: candidates.max_tokens,
          max_items: candidates.max_items,
          truncated: bundle.truncated,
        },
        conversation_window: conversationWindow.trace,
      },
      items: bundle.items,
    });
  }

  return { run_id: created.id };
}

function agentChatServices(context: ModuleContext): AgentChatServices {
  if (servicesFactoryOverride) return servicesFactoryOverride(context);
  const runRepository = PgRunRepository.fromConfig(context.config);
  const materializer = RunMaterializationService.fromConfig(context.config);
  const contextPreparer = new ContextPrepareService(context.config);
  const services: AgentChatServices = {
    agents: PgAgentChatRepository.fromConfig(context.config),
    sessions: PgSessionRepository.fromConfig(context.config),
    runs: runRepository,
    context: ChatContextCandidateCollector.fromConfig(context.config),
    snapshots: PgContextSnapshotRepository.fromConfig(context.config),
    condense: {
      enqueue: (input) => enqueueSessionCondense(context.config, input),
    },
    orchestration: new RunOrchestrationService(context.config, runRepository, {
      materializer,
      contextPreparer,
      workspaceManager: PgWorkspaceManager.fromConfig(context.config),
      codePatchCollector: PgCodePatchCollector.fromConfig(context.config),
      verificationEngine: PgVerificationEngine.fromConfig(context.config),
      processRegistry: sharedCliProcessRegistry,
    }),
  };
  return services;
}

async function resolveIdentity(
  context: ModuleContext,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<AgentChatIdentity | null> {
  if (identityOverride) {
    return typeof identityOverride === "function"
      ? identityOverride(request)
      : identityOverride;
  }
  const requestId = resolveRequestId(request);
  reply.header(REQUEST_ID_HEADER, requestId);
  const identity = await introspectIdentity(context.config, request);
  if (identity.ok) return { spaceId: identity.spaceId, userId: identity.userId };
  if (identity.reason === "denied") {
    reply.code(identity.statusCode);
    reply.header("content-type", "application/json");
    reply.send(identity.body);
    return null;
  }
  await sendErrorEnvelope(
    reply,
    502,
    errorEnvelope(
      identity.reason === "contract_violation"
        ? "introspect_contract_violation"
        : "identity_unavailable",
      "Identity introspection failed",
      requestId,
    ),
  );
  return null;
}

function chatOutcome(
  run: RunChatResultRecord | null,
  result: RunJobResult,
): { ok: true; reply: string } | { ok: false; error: string; errorCode: string } {
  if (!run) {
    return {
      ok: false,
      error: "Run not found after server execution",
      errorCode: "run_not_found",
    };
  }
  const status = run?.status || result.status || "unknown";
  if (status !== "succeeded") {
    const errorJson = recordValue(run?.error_json);
    const errorCode =
      stringValue(errorJson?.error_code) || result.error_code || "run_failed";
    const error =
      stringValue(errorJson?.error_text) ||
      stringValue(errorJson?.error) ||
      result.error ||
      `The assistant run ended with status '${status}'.`;
    return { ok: false, error, errorCode };
  }
  const outputJson = recordValue(run?.output_json);
  return { ok: true, reply: stringValue(outputJson?.output_text) ?? "" };
}
