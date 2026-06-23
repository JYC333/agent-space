import { completeProviderEmbedding } from "../providers/providerInvocation";
import type { ProviderCommandStore } from "../providers/providerCommandStore";
import type { RetrievalEgressPolicy } from "../retrievalEgress/egressPolicy";
import { RETRIEVAL_EMBEDDING_TASK } from "./config";
import type { RetrievalEmbedder } from "./service";

/**
 * Production embedder. Routes through the `retrieval_embedding` provider task
 * policy (ADR 0010 credential channel) with the configured provider as the
 * safety net, exactly like the other auxiliary model tasks.
 */
export class ProviderEmbedder implements RetrievalEmbedder {
  constructor(
    private readonly store: ProviderCommandStore,
    private readonly providerId: string | null = null,
    private readonly egressPolicy: RetrievalEgressPolicy | null = null,
  ) {}

  async embed(
    spaceId: string,
    texts: string[],
    opts: { dimensions?: number } = {},
  ): Promise<{ vectors: number[][]; model: string }> {
    const result = await completeProviderEmbedding(this.store, spaceId, {
      provider_id: this.providerId,
      inputs: texts,
      task: RETRIEVAL_EMBEDDING_TASK,
      dimensions: opts.dimensions,
      inputType: "document",
      egressPolicy: this.egressPolicy,
    });
    return { vectors: result.vectors, model: result.model };
  }
}
