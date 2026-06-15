import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { RunJobResult } from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ModuleContext } from "../../gateway/routeRegistry";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { introspectIdentity } from "../providers/identity";
import { loadProtocol } from "../providers/protocolRuntime";
import { PgSessionRepository } from "../sessions/repository";
import { PgRunRepository, type RunChatResultRecord } from "../runs/repository";
import { RunOrchestrationService } from "../runs/orchestrationService";
import { RunPythonContextPortClient } from "../runs/pythonContextPorts";
import { RunMaterializationService } from "../runs/materializationService";
import { sharedCliProcessRegistry } from "../runs/processRegistry";
import { PgContextSnapshotRepository } from "../memory/contextSnapshotRepository";
import { PgAgentChatRepository } from "./repository";
import {
  ChatTurnPreparationClient,
  ChatTurnPreparationError,
} from "./pythonChatTurnPrep";
import {
  ChatContextPortClient,
  ChatContextPortError,
} from "./pythonChatContextPorts";
import {
  buildChatContext,
  composeChatPrompt,
  renderContextPreamble,
} from "./chatContextBuilder";

const MAX_MESSAGE_CHARS = 8000;

interface AgentChatServices {
  agents: Pick<PgAgentChatRepository, "getAgentForChat">;
  sessions: Pick<PgSessionRepository, "getSession" | "createSession" | "addMessage">;
  runs: Pick<PgRunRepository, "getChatRunResult">;
  orchestration: Pick<RunOrchestrationService, "executeRun">;
  preparation: Pick<ChatTurnPreparationClient, "prepareRun">;
  /** Stage 6 slice 4: present when `contextAuthority === "ts"`. */
  context?: Pick<ChatContextPortClient, "fetchCandidates" | "createRun">;
  /** Stage 6 slice 4: present when `contextAuthority === "ts"`. */
  snapshots?: Pick<PgContextSnapshotRepository, "persistChatSnapshot">;
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
  if (context.config.chatTurnAuthority !== "ts") return;

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
          });
      if (!session) return reply.code(404).send({ detail: "session not found in this space" });

      const userMessage = await services.sessions.addMessage(
        identity.spaceId,
        identity.userId,
        session.id,
        { role: "user", content: rawMessage },
      );
      if (!userMessage) return reply.code(404).send({ detail: "session not found in this space" });

      const prepared = await prepareChatRun(context, services, {
        agentId: agent.id,
        agentVersionId: agent.current_version_id,
        spaceId: identity.spaceId,
        userId: identity.userId,
        sessionId: session.id,
        message: rawMessage,
      });

      const result = await services.orchestration.executeRun({
        run_id: prepared.run_id,
        space_id: identity.spaceId,
        worker_id: `chat:${resolveRequestId(request)}`,
        command_source: "http",
      });
      const run = await services.runs.getChatRunResult(identity.spaceId, prepared.run_id);
      const outcome = chatOutcome(run, result);
      if (!outcome.ok) {
        return reply.send(
          protocol.ChatTurnResultSchema.parse({
            session_id: session.id,
            run_id: prepared.run_id,
            ok: false,
            error: outcome.error,
            error_code: outcome.errorCode,
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
          metadata: { run_id: prepared.run_id },
        },
      );
      if (!assistantMessage) {
        return reply.code(404).send({ detail: "session not found in this space" });
      }
      return reply.send(
        protocol.ChatTurnResultSchema.parse({
          session_id: session.id,
          run_id: prepared.run_id,
          ok: true,
          reply: replyText,
        }),
      );
    } catch (error) {
      if (
        error instanceof ChatTurnPreparationError ||
        error instanceof ChatContextPortError
      ) {
        return reply.code(error.statusCode).send(error.body);
      }
      return sendDomainError(reply, error);
    }
  });
}

/**
 * Resolve the queued run for a chat turn.
 *
 * `python` context authority delegates context build + run creation to the
 * combined Python `prepare-run` port. `ts` authority (Stage 6 slice 4) makes the
 * control plane own the build: fetch per-source candidates (Python read port) →
 * TS budget/dedup loop → compose prompt → Python `create-run` → TS-owned
 * snapshot persistence. Either way the caller gets just `{ run_id }`.
 */
async function prepareChatRun(
  context: ModuleContext,
  services: AgentChatServices,
  input: {
    agentId: string;
    agentVersionId: string | null | undefined;
    spaceId: string;
    userId: string;
    sessionId: string;
    message: string;
  },
): Promise<PreparedChatRun> {
  if (context.config.contextAuthority !== "ts") {
    const prepared = await services.preparation.prepareRun({
      agent_id: input.agentId,
      space_id: input.spaceId,
      user_id: input.userId,
      session_id: input.sessionId,
      message: input.message,
    });
    return { run_id: prepared.run_id };
  }

  if (!services.context || !services.snapshots) {
    throw new ChatContextPortError(
      "TS context assembly requires the chat-context port and snapshot repository",
      500,
    );
  }

  const candidates = await services.context.fetchCandidates({
    agent_id: input.agentId,
    space_id: input.spaceId,
    user_id: input.userId,
    session_id: input.sessionId,
    message: input.message,
  });
  const bundle = buildChatContext(candidates);
  const composedPrompt = composeChatPrompt(
    renderContextPreamble(bundle.items),
    input.message,
  );

  const created = await services.context.createRun({
    agent_id: input.agentId,
    space_id: input.spaceId,
    user_id: input.userId,
    session_id: input.sessionId,
    prompt: composedPrompt,
  });

  if (created.context_snapshot_id) {
    await services.snapshots.persistChatSnapshot({
      contextSnapshotId: created.context_snapshot_id,
      spaceId: input.spaceId,
      tokenEstimate: bundle.token_count,
      // Mirrors the ContextRequest the Python prepare-run path serialized into
      // context_snapshots.request_json (request defaults, not policy-resolved).
      requestJson: {
        space_id: input.spaceId,
        user_id: input.userId,
        agent_version_id: input.agentVersionId ?? null,
        session_id: input.sessionId,
        workspace_id: null,
        project_id: null,
        run_id: created.run_id,
        user_message: input.message,
        manual_context: [],
        max_tokens: 4000,
        max_items: 20,
      },
      items: bundle.items,
    });
  }

  return { run_id: created.run_id };
}

function agentChatServices(context: ModuleContext): AgentChatServices {
  if (servicesFactoryOverride) return servicesFactoryOverride(context);
  const runRepository = PgRunRepository.fromConfig(context.config);
  const contextPorts = new RunPythonContextPortClient(context.config);
  const materializer = new RunMaterializationService(contextPorts);
  const services: AgentChatServices = {
    agents: PgAgentChatRepository.fromConfig(context.config),
    sessions: PgSessionRepository.fromConfig(context.config),
    runs: runRepository,
    preparation: new ChatTurnPreparationClient(context.config),
    orchestration: new RunOrchestrationService(context.config, runRepository, {
      materializer,
      contextPorts,
      processRegistry: sharedCliProcessRegistry,
    }),
  };
  if (context.config.contextAuthority === "ts") {
    services.context = new ChatContextPortClient(context.config);
    services.snapshots = PgContextSnapshotRepository.fromConfig(context.config);
  }
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
        : "python_authority_unavailable",
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
      error: "Run not found after TS execution",
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

function params(request: FastifyRequest): Record<string, string | undefined> {
  return request.params as Record<string, string | undefined>;
}

function jsonBody(request: FastifyRequest): Record<string, unknown> {
  const text = request.body instanceof Buffer ? request.body.toString("utf8") : "";
  if (!text) return {};
  const parsed = JSON.parse(text) as unknown;
  return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
    ? (parsed as Record<string, unknown>)
    : {};
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function sendDomainError(reply: FastifyReply, error: unknown): FastifyReply {
  const message = error instanceof Error ? error.message : "Request failed";
  return reply.code(400).send({ detail: message });
}
