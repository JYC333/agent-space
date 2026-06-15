import type { FastifyReply, FastifyRequest } from "fastify";
import type { ServerResponse } from "node:http";
import type { ControlPlaneConfig } from "../../config";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import {
  copyPythonAuthorityResponseHeaders,
  errKind,
  requestPythonAuthority,
} from "../../ports/pythonHttp";

/** Runtime string kept in lockstep with `EventType.RunEventAppended`. */
export const RUN_EVENT_APPENDED_TYPE = "run.event_appended";
const STREAM_ERROR_EVENT = "control_plane.error";

interface RunEventsPage {
  items: RunEventDTO[];
  total: number;
  limit: number;
  offset: number;
}

interface RunEventDTO {
  id: string;
  space_id: string;
  run_id: string;
  event_index: number;
  event_type: string;
  status: string;
  step_id?: string | null;
  actor_id?: string | null;
  summary?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  artifact_id?: string | null;
  proposal_id?: string | null;
  created_at: string;
}

interface RunEventAppendedEnvelope {
  event_id: string;
  type: typeof RUN_EVENT_APPENDED_TYPE;
  occurred_at: string;
  space_id: string;
  payload: { event: RunEventDTO };
}

interface StreamOptions {
  fromEventIndex: number;
  tail: boolean;
}

type PageFetchResult =
  | { ok: true; page: RunEventsPage }
  | {
      ok: false;
      statusCode: number;
      headers?: Record<string, string | string[] | undefined>;
      body?: string;
      error: string;
      message: string;
    };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseStreamOptions(request: FastifyRequest): StreamOptions {
  const url = new URL(request.url, "http://control-plane.local");
  const fromParam = url.searchParams.get("from_event_index");
  const lastEventId = request.headers["last-event-id"];
  const rawLastEventId = Array.isArray(lastEventId) ? lastEventId[0] : lastEventId;
  const fromLastEventId =
    rawLastEventId !== undefined && /^\d+$/.test(rawLastEventId)
      ? Number(rawLastEventId) + 1
      : undefined;
  const fromEventIndex =
    fromParam !== null && /^\d+$/.test(fromParam)
      ? Number(fromParam)
      : fromLastEventId ?? 0;
  const tailParam = url.searchParams.get("tail");
  return {
    fromEventIndex,
    tail: tailParam === null || !["0", "false", "no"].includes(tailParam.toLowerCase()),
  };
}

function upstreamEventsPath(
  request: FastifyRequest,
  runId: string,
  offset: number,
  limit: number,
): string {
  const incoming = new URL(request.url, "http://control-plane.local");
  const query = new URLSearchParams();
  query.set("offset", String(offset));
  query.set("limit", String(limit));
  for (const key of ["space_id", "user_id", "event_type", "status"]) {
    const value = incoming.searchParams.get(key);
    if (value !== null) query.set(key, value);
  }
  return `/api/v1/runs/${encodeURIComponent(runId)}/events?${query.toString()}`;
}

async function fetchRunEventsPage(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  runId: string,
  offset: number,
): Promise<PageFetchResult> {
  const path = upstreamEventsPath(
    request,
    runId,
    offset,
    config.runEventStreamPageLimit,
  );
  try {
    const upstream = await requestPythonAuthority(config, request, path);
    const body = await upstream.body.text();
    if (upstream.statusCode < 200 || upstream.statusCode >= 300) {
      return {
        ok: false,
        statusCode: upstream.statusCode,
        headers: upstream.headers,
        body,
        error: "python_authority_rejected_stream",
        message: "Python authority rejected the stream request",
      };
    }
    return { ok: true, page: JSON.parse(body) as RunEventsPage };
  } catch (err) {
    request.log.warn(
      { run_id: runId, offset, reason: errKind(err) },
      "run-event stream source failed",
    );
    return {
      ok: false,
      statusCode: 502,
      error: "python_authority_unavailable",
      message: "Python authority is unavailable",
    };
  }
}

function startSse(reply: FastifyReply, requestId: string): ServerResponse {
  reply.hijack();
  reply.raw.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache, no-transform",
    connection: "keep-alive",
    "x-accel-buffering": "no",
    [REQUEST_ID_HEADER]: requestId,
  });
  reply.raw.write(": connected\n\n");
  return reply.raw;
}

function writeSse(raw: ServerResponse, event: string, data: unknown, id?: string): void {
  if (id !== undefined) raw.write(`id: ${id}\n`);
  raw.write(`event: ${event}\n`);
  raw.write(`data: ${JSON.stringify(data)}\n\n`);
}

function toEnvelope(event: RunEventDTO): RunEventAppendedEnvelope {
  return {
    event_id: event.id,
    type: RUN_EVENT_APPENDED_TYPE,
    occurred_at: event.created_at,
    space_id: event.space_id,
    payload: { event },
  };
}

function sendInitialFailure(
  reply: FastifyReply,
  requestId: string,
  result: Extract<PageFetchResult, { ok: false }>,
): FastifyReply {
  if (result.headers) copyPythonAuthorityResponseHeaders(result.headers, reply);
  if (result.body !== undefined && result.statusCode < 500) {
    reply.header(REQUEST_ID_HEADER, requestId);
    return reply.code(result.statusCode).send(result.body);
  }
  return sendErrorEnvelope(
    reply,
    result.statusCode,
    errorEnvelope(result.error, result.message, requestId),
  );
}

export async function streamRunEvents(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<FastifyReply | void> {
  const runId = (request.params as { runId?: string }).runId;
  const requestId = resolveRequestId(request);
  if (!runId) {
    return sendErrorEnvelope(
      reply,
      400,
      errorEnvelope("missing_run_id", "Missing run id", requestId),
    );
  }

  const options = parseStreamOptions(request);
  let offset = options.fromEventIndex;
  let closed = false;
  request.raw.on("close", () => {
    closed = true;
  });

  let pageResult = await fetchRunEventsPage(config, request, runId, offset);
  if (!pageResult.ok) return sendInitialFailure(reply, requestId, pageResult);

  const raw = startSse(reply, requestId);

  while (!closed) {
    const emitted = pageResult.page.items.length;
    for (const event of pageResult.page.items) {
      writeSse(
        raw,
        RUN_EVENT_APPENDED_TYPE,
        toEnvelope(event),
        String(event.event_index),
      );
      offset = event.event_index + 1;
    }

    if (!options.tail && (offset >= pageResult.page.total || emitted === 0)) break;

    const caughtUp = offset >= pageResult.page.total || emitted === 0;
    if (caughtUp) await sleep(config.runEventStreamPollIntervalMs);
    if (closed) break;

    pageResult = await fetchRunEventsPage(config, request, runId, offset);
    if (!pageResult.ok) {
      writeSse(raw, STREAM_ERROR_EVENT, {
        error: pageResult.error,
        message: pageResult.message,
      });
      break;
    }
  }

  raw.end();
}
