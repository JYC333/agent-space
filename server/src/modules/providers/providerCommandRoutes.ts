import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ServerConfig } from "../../config";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { checkInternalToken } from "../../gateway/internalAuth";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { introspectIdentity } from "../auth/identity";
import { loadProtocol } from "./protocolRuntime";
import { resolveProviderCommandStore } from "./providerCommandStore";
import type {
  ModelProviderCreateInput,
  ModelProviderUpdateInput,
  ProviderPoolConfigUpdateInput,
  ProviderPoolCredentialAddInput,
  ProviderTaskChainEntry,
  RotationStrategy,
} from "./providerCommandStore";
import {
  completeProviderChat,
  completeProviderText,
  listProviderModels,
  ProviderInvocationError,
} from "./providerInvocation";
import type { ProviderChatRequestBody } from "./providerInvocation";
import { CliCredentialBroker } from "./cliCredentialBroker";
import { startCliUsageRefreshScheduler } from "./cliUsageScheduler";

function params(request: FastifyRequest): Record<string, string | undefined> {
  return request.params as Record<string, string | undefined>;
}

function query(request: FastifyRequest): Record<string, string | undefined> {
  return request.query as Record<string, string | undefined>;
}

function bodyText(request: FastifyRequest): string {
  return request.body instanceof Buffer ? request.body.toString("utf8") : "";
}

function jsonBody(request: FastifyRequest): unknown {
  const text = bodyText(request);
  return text ? JSON.parse(text) : {};
}

async function resolveIdentity(
  config: ServerConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<{ spaceId: string } | null> {
  const requestId = resolveRequestId(request);
  reply.header(REQUEST_ID_HEADER, requestId);
  const identity = await introspectIdentity(config, request);
  if (identity.ok) return { spaceId: identity.spaceId };
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

function sendDomainError(reply: FastifyReply, error: unknown): FastifyReply {
  const statusCode =
    error && typeof error === "object" && "statusCode" in error
      ? Number((error as { statusCode: unknown }).statusCode)
      : 400;
  const message = error instanceof Error ? error.message : "Request failed";
  return reply.code(Number.isInteger(statusCode) ? statusCode : 400).send({ detail: message });
}

async function parseWith<T>(
  schemaName: string,
  value: unknown,
): Promise<T> {
  const protocol = await loadProtocol();
  const schema = (protocol as unknown as Record<string, { parse(v: unknown): T }>)[schemaName];
  return schema.parse(value);
}

export function registerProviderCommandRoutes(
  app: FastifyInstance,
  config: ServerConfig,
): void {
  const broker = new CliCredentialBroker(config, app.log);
  const usageScheduler = startCliUsageRefreshScheduler(broker, {
    isEnabled: () => broker.isCliUsageAutoRefreshEnabled(),
    logger: app.log,
  });
  app.addHook("onClose", async () => {
    usageScheduler.stop();
  });

  app.post("/api/v1/providers", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const body = await parseWith<ModelProviderCreateInput>(
        "ModelProviderCreateRequestSchema",
        jsonBody(request),
      );
      const value = await resolveProviderCommandStore(config).createProvider(
        identity.spaceId,
        body,
      );
      return reply.code(201).send(value);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.patch("/api/v1/providers/:configId", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const body = await parseWith<ModelProviderUpdateInput>(
        "ModelProviderUpdateRequestSchema",
        jsonBody(request),
      );
      const value = await resolveProviderCommandStore(config).updateProvider(
        identity.spaceId,
        params(request).configId ?? "",
        body,
      );
      return reply.send(value);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.delete("/api/v1/providers/:configId", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      await resolveProviderCommandStore(config).deleteProvider(
        identity.spaceId,
        params(request).configId ?? "",
      );
      return reply.code(204).send();
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.get("/api/v1/providers/:configId/models", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const value = await listProviderModels(
        resolveProviderCommandStore(config),
        identity.spaceId,
        params(request).configId ?? "",
      );
      return reply.send(value);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/api/v1/providers/:configId/test", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const store = resolveProviderCommandStore(config);
      const target = await store.getInvocationTarget(
        identity.spaceId,
        params(request).configId ?? "",
      );
      const models = await store.listConfiguredModels(identity.spaceId, target.provider.id);
      const model = target.provider.default_model || models[0];
      if (!model) return reply.send({ success: false, message: "No models configured" });
      const result = await completeProviderChat(store, identity.spaceId, {
        provider_id: target.provider.id,
        model,
        messages: [{ role: "user", content: "Hi" }],
        max_tokens: 5,
      });
      return reply.send({
        success: true,
        message: "Connection successful",
        model: result.model,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Connection failed";
      return reply.send({ success: false, message });
    }
  });

  // ----- Credential pool management ---------------------------------------

  app.get("/api/v1/providers/:configId/credentials", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await resolveProviderCommandStore(config).listPool(
          identity.spaceId,
          params(request).configId ?? "",
        ),
      );
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/api/v1/providers/:configId/credentials", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const body = await parseWith<ProviderPoolCredentialAddInput>(
        "ProviderPoolCredentialAddRequestSchema",
        jsonBody(request),
      );
      const member = await resolveProviderCommandStore(config).addPoolCredential(
        identity.spaceId,
        params(request).configId ?? "",
        body,
      );
      return reply.code(201).send(member);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.delete("/api/v1/providers/:configId/credentials/:memberId", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      await resolveProviderCommandStore(config).removePoolCredential(
        identity.spaceId,
        params(request).configId ?? "",
        params(request).memberId ?? "",
      );
      return reply.code(204).send();
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.patch("/api/v1/providers/:configId/credentials/config", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const body = await parseWith<{
        rotation_strategy?: RotationStrategy;
        fallback_provider_ids?: string[];
      }>("ProviderPoolConfigUpdateRequestSchema", jsonBody(request));
      return reply.send(
        await resolveProviderCommandStore(config).updatePoolConfig(
          identity.spaceId,
          params(request).configId ?? "",
          body as ProviderPoolConfigUpdateInput,
        ),
      );
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  // ----- Per-auxiliary-task provider chains --------------------------------

  app.get("/api/v1/providers/task-policies", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    return reply.send(
      await resolveProviderCommandStore(config).listTaskPolicies(identity.spaceId),
    );
  });

  app.put("/api/v1/providers/task-policies/:task", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const body = await parseWith<{ chain: ProviderTaskChainEntry[]; enabled?: boolean }>(
        "ProviderTaskPolicyPutRequestSchema",
        jsonBody(request),
      );
      return reply.send(
        await resolveProviderCommandStore(config).putTaskPolicy(
          identity.spaceId,
          params(request).task ?? "",
          body.chain,
          body.enabled,
        ),
      );
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.delete("/api/v1/providers/task-policies/:task", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      await resolveProviderCommandStore(config).deleteTaskPolicy(
        identity.spaceId,
        params(request).task ?? "",
      );
      return reply.code(204).send();
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/api/v1/providers/chat", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const body = await parseWith<ProviderChatRequestBody>(
        "ProviderChatRequestSchema",
        jsonBody(request),
      );
      return reply.send(
        await completeProviderChat(resolveProviderCommandStore(config), identity.spaceId, body),
      );
    } catch (error) {
      if (error instanceof ProviderInvocationError) {
        return reply.code(error.statusCode).send({ detail: error.message });
      }
      return sendDomainError(reply, error);
    }
  });

  app.get("/api/v1/credentials/cli/profiles", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    const runtime = query(request).runtime;
    const profiles = await broker.listProfiles(runtime);
    return reply.send(await Promise.all(profiles.map((p) => broker.profileOut(p))));
  });

  app.get("/api/v1/credentials/cli/profiles/:runtime/:name", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    const profileId = `${params(request).runtime}/${params(request).name}`;
    const profile = await broker.getProfile(profileId);
    if (!profile) return reply.code(404).send({ detail: `Profile '${profileId}' not found` });
    return reply.send(await broker.profileOut(profile));
  });

  app.post("/api/v1/credentials/cli/profiles/:runtime/:name/detect", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await broker.detectProfile(`${params(request).runtime}/${params(request).name}`));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.get("/api/v1/credentials/cli/methods", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    return reply.send(broker.listLoginMethods());
  });

  app.get("/api/v1/credentials/cli/login/stream", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    await broker.streamLogin(query(request).runtime ?? "", reply);
    return reply;
  });

  app.post("/api/v1/credentials/cli/login/input", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const body = await parseWith<{ input: string }>(
        "CliLoginInputRequestSchema",
        jsonBody(request),
      );
      if (!broker.sendLoginInput(query(request).runtime ?? "", body.input)) {
        return reply
          .code(404)
          .send({ detail: `No active login session for runtime '${query(request).runtime ?? ""}'` });
      }
      return reply.send({ status: "sent" });
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.get("/api/v1/credentials/cli/status", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    return reply.send(await broker.status());
  });

  app.get("/api/v1/credentials/cli/usage", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    return reply.send(await broker.cliUsage());
  });

  app.get("/api/v1/credentials/cli/usage/auto-refresh", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    return reply.send(await broker.cliUsageAutoRefreshSettings());
  });

  app.put("/api/v1/credentials/cli/usage/auto-refresh", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      const body = await parseWith<{ enabled: boolean }>(
        "CliUsageAutoRefreshUpdateRequestSchema",
        jsonBody(request),
      );
      return reply.send(await broker.setCliUsageAutoRefresh(body.enabled));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/api/v1/credentials/cli/usage/refresh", async (request, reply) => {
    const identity = await resolveIdentity(config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await broker.refreshCliQuota(query(request).runtime ?? ""));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/internal/providers-credentials/providers/complete-text", async (request, reply) => {
    if (!checkInternalToken(config, request)) return reply.code(401).send({ detail: "Unauthorized" });
    try {
      const body = await parseWith<{
        space_id: string;
        provider_id: string;
        model?: string | null;
        system: string;
        user: string;
        max_tokens?: number;
        task?: string | null;
      }>("ProviderCompletionInternalRequestSchema", jsonBody(request));
      return reply.send(
        await completeProviderText(resolveProviderCommandStore(config), body.space_id, {
          provider_id: body.provider_id,
          model: body.model,
          system: body.system,
          user: body.user,
          max_tokens: body.max_tokens,
          task: body.task,
        }),
      );
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/internal/providers-credentials/credentials/runtime/resolve", async (request, reply) => {
    if (!checkInternalToken(config, request)) return reply.code(401).send({ detail: "Unauthorized" });
    try {
      const body = await parseWith<
        | { kind: "model_provider_api_key"; space_id: string; provider_id: string }
        | { kind: "credential_api_key"; space_id: string; credential_id: string }
        | {
            kind: "cli_profile";
            runtime: string;
            profile_id?: string | null;
            require_existing?: boolean;
          }
      >("RuntimeCredentialResolveRequestSchema", jsonBody(request));
      if (body.kind === "model_provider_api_key") {
        return reply.send({
          kind: "model_provider_api_key",
          provider_id: body.provider_id,
          api_key: await resolveProviderCommandStore(config).resolveProviderApiKey(
            body.space_id,
            body.provider_id,
          ),
        });
      }
      if (body.kind === "credential_api_key") {
        return reply.send({
          kind: "credential_api_key",
          credential_id: body.credential_id,
          api_key: await resolveProviderCommandStore(config).resolveCredentialApiKey(
            body.space_id,
            body.credential_id,
          ),
        });
      }
      const profile = await broker.resolveProfile(
        body.runtime,
        body.profile_id,
        body.require_existing ?? true,
      );
      if (!profile) return reply.code(404).send({ detail: "Credential profile not found" });
      return reply.send({
        kind: "cli_profile",
        profile_id: profile.id,
        runtime: profile.runtime,
        source_path: profile.source_path,
        target_path: profile.target_path,
        readonly: profile.readonly,
      });
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/internal/providers-credentials/credentials/cli/grant", async (request, reply) => {
    if (!checkInternalToken(config, request)) return reply.code(401).send({ detail: "Unauthorized" });
    try {
      const body = await parseWith<{
        run_id: string;
        runtime: string;
        executor_mode: "worktree" | "docker";
        profile_id?: string | null;
      }>("CliCredentialGrantRequestSchema", jsonBody(request));
      return reply.send(
        await broker.grantForRun(
          body.run_id,
          body.runtime,
          body.executor_mode,
          body.profile_id,
        ),
      );
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/internal/providers-credentials/credentials/cli/audit", async (request, reply) => {
    if (!checkInternalToken(config, request)) return reply.code(401).send({ detail: "Unauthorized" });
    try {
      const body = await parseWith<{
        space_id: string;
        run_id?: string | null;
        runtime_adapter_type?: string | null;
        credential_profile_id?: string | null;
        trigger_origin?: string | null;
        fallback_used?: boolean;
        fallback_reason?: string | null;
        broker_error?: boolean;
        cleanup_status?: string;
        action?: string;
      }>("CliCredentialAuditRequestSchema", jsonBody(request));
      const eventId = await resolveProviderCommandStore(config).recordCliCredentialUsage(body);
      return reply.send({ status: "recorded", event_id: eventId });
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });
}
