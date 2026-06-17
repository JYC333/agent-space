import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  dbPool,
  jsonBody,
  optionalString,
  parsePage,
  params,
  query,
  resolveIdentity,
  sendRouteError,
} from "../routeUtils/common";
import { PgKnowledgeRepository } from "./repository";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => new PgKnowledgeRepository(dbPool(context.config));

  app.get("/api/v1/knowledge", knowledgeHealth(context));
  app.get("/api/v1/knowledge/", knowledgeHealth(context));

  app.get("/api/v1/knowledge/summary", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().summary(identity));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/items", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(
        await repository().listItems(identity, {
          itemType: optionalString(q.item_type),
          status: optionalString(q.status) ?? "active",
          visibility: optionalString(q.visibility),
          projectId: optionalString(q.project_id),
          workspaceId: optionalString(q.workspace_id),
          q: optionalString(q.q),
          limit,
          offset,
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/knowledge/items/proposals", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(202).send(await repository().proposeCreate(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/items/:itemId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const item = await repository().getItem(identity, params(request).itemId ?? "");
      if (!item) return reply.code(404).send({ detail: "Knowledge item not found" });
      return reply.send(item);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/items/:itemId/relations", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().itemRelations(identity, params(request).itemId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/items/:itemId/backlinks", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository().entityLinks(identity, {
          target_type: "knowledge_item",
          target_id: params(request).itemId ?? "",
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/knowledge/items/:itemId/proposals", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(202)
        .send(await repository().proposeUpdate(identity, params(request).itemId ?? "", jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/knowledge/items/:itemId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(202)
        .send(await repository().proposeArchive(identity, params(request).itemId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/knowledge/relations/proposals", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(202).send(await repository().proposeRelation(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/knowledge/relations/:relationId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(202)
        .send(await repository().proposeRelationArchive(identity, params(request).relationId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/sources", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(
        await repository().listSources(identity, {
          sourceType: optionalString(q.source_type),
          status: optionalString(q.status),
          q: optionalString(q.q),
          limit,
          offset,
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/knowledge/sources", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().createSource(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/sources/:sourceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const source = await repository().getSource(identity, params(request).sourceId ?? "");
      if (!source) return reply.code(404).send({ detail: "Source not found" });
      return reply.send(source);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/knowledge/sources/:sourceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository().updateSource(identity, params(request).sourceId ?? "", jsonBody(request)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/knowledge/sources/:sourceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().archiveSource(identity, params(request).sourceId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/sources/:sourceId/items", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listSourceItems(identity, params(request).sourceId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/items/:itemId/sources", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listItemSources(identity, params(request).itemId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/knowledge/items/:itemId/sources", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(await repository().createItemSource(identity, params(request).itemId ?? "", jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/knowledge/items/:itemId/sources/:linkId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      await repository().deleteItemSource(identity, params(request).itemId ?? "", params(request).linkId ?? "");
      return reply.code(204).send();
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/entity-links", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().entityLinks(identity, query(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/notes", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(
        await repository().listNotes(identity, {
          status: optionalString(q.status),
          projectId: optionalString(q.project_id),
          collectionId: optionalString(q.collection_id),
          q: optionalString(q.q),
          limit,
          offset,
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/notes/collections", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listNoteCollections(identity));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/notes/collections", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().createNoteCollection(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/notes/collections/:collectionId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository().updateNoteCollection(
          identity,
          params(request).collectionId ?? "",
          jsonBody(request),
        ),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/notes/collections/:collectionId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      await repository().deleteNoteCollection(identity, params(request).collectionId ?? "");
      return reply.code(204).send();
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/knowledge/notes/deleted/purge", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().purgeDeletedNotes(identity));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/knowledge/notes", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().createNote(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/notes/:noteId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const note = await repository().getNote(identity, params(request).noteId ?? "");
      if (!note) return reply.code(404).send({ detail: "Note not found" });
      return reply.send(note);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/knowledge/notes/:noteId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository().updateNote(identity, params(request).noteId ?? "", jsonBody(request)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/knowledge/notes/:noteId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().deleteNote(identity, params(request).noteId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/notes/:noteId/links", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().noteLinks(identity, params(request).noteId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/knowledge/notes/:noteId/backlinks", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().noteLinks(identity, params(request).noteId ?? "", true));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/knowledge/notes/:noteId/links", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(await repository().createNoteLink(identity, params(request).noteId ?? "", jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/knowledge/notes/:noteId/links/:linkId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      await repository().deleteNoteLink(identity, params(request).noteId ?? "", params(request).linkId ?? "");
      return reply.code(204).send();
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}

function knowledgeHealth(context: ModuleContext) {
  return async (request: FastifyRequest, reply: FastifyReply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    return reply.send({ ok: true });
  };
}
