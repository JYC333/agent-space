import { createHash } from "node:crypto";
import { sourceConnectorRegistry, type CompiledSourceQuery } from "./sourceConnectorRegistry";

export class SourceChannelQueryCompiler {
  compile(connectorKey: string, input: Record<string, unknown>): CompiledSourceQuery {
    return sourceConnectorRegistry.get(connectorKey).compileQuery(input);
  }

  fingerprint(input: {
    providerKey: string;
    connectorKey: string;
    compiled: CompiledSourceQuery;
  }): string {
    return createHash("sha256")
      .update(stableJson({
        provider: input.providerKey,
        connector: input.connectorKey,
        ...input.compiled.fingerprintInput,
      }))
      .digest("hex");
  }
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (!value || typeof value !== "object") return JSON.stringify(value) ?? "null";
  return `{${Object.keys(value as Record<string, unknown>).sort().map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(",")}}`;
}
