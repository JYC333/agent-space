/**
 * Runtime access to `@agent-space/protocol`.
 *
 * The control plane compiles to CommonJS while the protocol package ships ESM,
 * so the schemas are loaded through a cached dynamic `import()` — the one
 * mechanism CommonJS on node:20 has for consuming ESM. All provider validation
 * goes through these shared Zod schemas; there are no hand-rolled mirrors.
 */

import type * as Protocol from "@agent-space/protocol" with { "resolution-mode": "import" };

export type ProtocolModule = typeof Protocol;

let cached: Promise<ProtocolModule> | null = null;

export function loadProtocol(): Promise<ProtocolModule> {
  cached ??= import("@agent-space/protocol");
  return cached;
}
