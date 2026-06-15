import type { FastifyReply, FastifyRequest } from "fastify";
import type { ControlPlaneConfig } from "../../config";
import { forwardPythonAuthorityResponse } from "../../ports/pythonHttp";

export function forwardReadModel(config: ControlPlaneConfig) {
  return async (request: FastifyRequest, reply: FastifyReply): Promise<FastifyReply> =>
    forwardPythonAuthorityResponse(config, request, reply);
}
