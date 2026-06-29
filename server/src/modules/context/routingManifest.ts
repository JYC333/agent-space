import type { ContextRoutingManifest, ContextRoutingRule } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};

export const DEFAULT_CONTEXT_ROUTING_MANIFEST: ContextRoutingManifest = {
  version: 1,
  default_agent_doc_paths: [
    ".agent/INDEX.md",
    ".agent/ARCHITECTURE.md",
    ".agent/BOUNDARIES.md",
    ".agent/COMMANDS.md",
    ".agent/GLOSSARY.md",
  ],
  rules: [
    {
      id: "server-context",
      path_glob: "server/src/modules/context/**",
      module_id: "context",
      agent_doc_paths: [".agent/modules/context-compiler.md"],
      context_bundle_id: "runtime-agent",
      priority: 10,
    },
    {
      id: "server-capabilities",
      path_glob: "server/src/modules/capabilities/**",
      module_id: "capabilities",
      agent_doc_paths: [
        ".agent/modules/capability.md",
        ".agent/architecture/CAPABILITY_WORKFLOW_SKILL_SYSTEM.md",
      ],
      context_bundle_id: "capability",
      priority: 20,
    },
    {
      id: "server-context-ops",
      path_glob: "server/src/modules/contextOps/**",
      module_id: "context_ops",
      agent_doc_paths: [".agent/architecture/CONTEXT_AND_RETRIEVAL_LAYER.md"],
      context_bundle_id: "knowledge",
      priority: 30,
    },
    {
      id: "server-memory",
      path_glob: "server/src/modules/memory/**",
      module_id: "memory",
      agent_doc_paths: [
        ".agent/modules/memory.md",
        ".agent/architecture/MEMORY_MODEL.md",
        ".agent/architecture/PROPOSALS.md",
      ],
      context_bundle_id: "memory",
      priority: 40,
    },
    {
      id: "server-knowledge",
      path_glob: "server/src/modules/knowledge/**",
      module_id: "knowledge",
      agent_doc_paths: [
        ".agent/modules/knowledge-base.md",
        ".agent/architecture/CONTEXT_AND_RETRIEVAL_LAYER.md",
      ],
      context_bundle_id: "knowledge",
      priority: 50,
    },
    {
      id: "server-route-registry",
      path_glob: "server/src/gateway/routeRegistry.ts",
      module_id: "module_registry",
      agent_doc_paths: [
        ".agent/architecture/MODULES.md",
        ".agent/architecture/MODULE_DEVELOPMENT_GUIDE.md",
      ],
      context_bundle_id: "module_registry",
      priority: 60,
    },
    {
      id: "frontend-modules",
      path_glob: "apps/web/src/modules/**",
      module_id: "frontend",
      agent_doc_paths: [
        ".agent/architecture/FRONTEND_INFORMATION_ARCHITECTURE.md",
        ".agent/modules/frontend-layout.md",
        ".agent/modules/client-server-protocol.md",
      ],
      context_bundle_id: "frontend-product",
      priority: 70,
    },
  ],
};

export function mergeContextRoutingManifests(
  manifests: readonly (ContextRoutingManifest | null | undefined)[],
): ContextRoutingManifest {
  const rules: ContextRoutingRule[] = [];
  const defaultPaths = new Set<string>();
  let version = 1;
  for (const manifest of manifests) {
    if (!manifest) continue;
    version = Math.max(version, Number(manifest.version) || 1);
    for (const path of manifest.default_agent_doc_paths ?? []) {
      const normalized = normalizeAgentDocPath(path);
      if (normalized) defaultPaths.add(normalized);
    }
    for (const rule of manifest.rules ?? []) {
      const normalizedRule = normalizeRoutingRule(rule);
      if (normalizedRule) rules.push(normalizedRule);
    }
  }
  return {
    version,
    default_agent_doc_paths: [...defaultPaths],
    rules: rules.sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100)),
  };
}

export function selectAgentDocPaths(input: {
  manifest?: ContextRoutingManifest | null;
  touchedFiles?: readonly string[] | null;
}): string[] {
  const manifest = mergeContextRoutingManifests([
    DEFAULT_CONTEXT_ROUTING_MANIFEST,
    input.manifest ?? null,
  ]);
  const selected = new Set<string>();
  for (const path of manifest.default_agent_doc_paths) {
    const normalized = normalizeAgentDocPath(path);
    if (normalized) selected.add(normalized);
  }
  const touched = (input.touchedFiles ?? [])
    .map(normalizeRelativeFilePath)
    .filter((path): path is string => Boolean(path));
  if (touched.length === 0) return [...selected];
  for (const file of touched) {
    for (const rule of manifest.rules) {
      if (!globMatches(rule.path_glob, file)) continue;
      for (const path of rule.agent_doc_paths ?? []) {
        const normalized = normalizeAgentDocPath(path);
        if (normalized) selected.add(normalized);
      }
    }
  }
  return [...selected];
}

export function invalidContextRoutingManifestEntries(manifest: ContextRoutingManifest): string[] {
  const invalid: string[] = [];
  for (const path of manifest.default_agent_doc_paths ?? []) {
    if (!normalizeAgentDocPath(path)) invalid.push(`default_agent_doc_paths:${path}`);
  }
  for (const rule of manifest.rules ?? []) {
    if (!normalizeRelativeFilePath(rule.path_glob)) invalid.push(`rules:${rule.id ?? rule.path_glob}:path_glob`);
    for (const path of rule.agent_doc_paths ?? []) {
      if (!normalizeAgentDocPath(path)) invalid.push(`rules:${rule.id ?? rule.path_glob}:agent_doc_paths:${path}`);
    }
  }
  return invalid;
}

export function normalizeAgentDocPath(path: string): string | null {
  const normalized = normalizeRelativeFilePath(path);
  if (!normalized) return null;
  if (!normalized.startsWith(".agent/")) return null;
  if (!/\.(md|ya?ml)$/i.test(normalized)) return null;
  return normalized;
}

function normalizeRoutingRule(rule: ContextRoutingRule): ContextRoutingRule | null {
  const glob = normalizeRelativeFilePath(rule.path_glob);
  if (!glob) return null;
  const paths = (rule.agent_doc_paths ?? [])
    .map(normalizeAgentDocPath)
    .filter((path): path is string => Boolean(path));
  return {
    ...rule,
    path_glob: glob,
    agent_doc_paths: paths,
    priority: Number.isInteger(rule.priority) ? rule.priority : 100,
  };
}

function normalizeRelativeFilePath(path: string): string | null {
  if (typeof path !== "string") return null;
  const trimmed = path.trim().replace(/\\/g, "/");
  if (!trimmed || trimmed.startsWith("/") || trimmed.includes("\0")) return null;
  const parts: string[] = [];
  for (const part of trimmed.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") return null;
    parts.push(part);
  }
  return parts.join("/");
}

function globMatches(glob: string, file: string): boolean {
  const regex = new RegExp(`^${globToRegex(glob)}$`);
  return regex.test(file);
}

function globToRegex(glob: string): string {
  let out = "";
  for (let index = 0; index < glob.length; index += 1) {
    const char = glob[index]!;
    const next = glob[index + 1];
    if (char === "*" && next === "*") {
      out += ".*";
      index += 1;
    } else if (char === "*") {
      out += "[^/]*";
    } else if (char === "?") {
      out += "[^/]";
    } else {
      out += escapeRegex(char);
    }
  }
  return out;
}

function escapeRegex(value: string): string {
  return value.replace(/[|\\{}()[\]^$+*?.]/g, "\\$&");
}
