import { lstat, mkdir, readdir, readlink, rm, symlink, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";

export class CodexProviderConfigError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "CodexProviderConfigError";
  }
}

export async function writeCodexProviderConfig(input: {
  tempHome: string | null;
  providerName: string;
  proxyBaseUrl: string;
  leaseToken: string;
  model: string;
  availableModels: string[];
}): Promise<string> {
  if (!input.tempHome) {
    throw new CodexProviderConfigError(
      "codex_temp_home_required",
      "Codex provider configuration requires a run-scoped HOME.",
    );
  }
  const codexDir = await materializeCodexProfileDir(input.tempHome);
  const catalogDir = join(codexDir, "model-catalogs");
  const catalogPath = join(catalogDir, "agent-space-provider.json");
  await mkdir(catalogDir, { recursive: true, mode: 0o700 });
  await writeFile(
    catalogPath,
    JSON.stringify(codexModelCatalog(input.providerName, input.model, input.availableModels), null, 2),
    { encoding: "utf8", mode: 0o600 },
  );
  await writeFile(
    join(codexDir, "config.toml"),
    renderCodexProviderToml({
      providerName: input.providerName,
      proxyBaseUrl: input.proxyBaseUrl,
      leaseToken: input.leaseToken,
      model: input.model,
      catalogPath,
    }),
    { encoding: "utf8", mode: 0o600 },
  );
  return codexDir;
}

async function materializeCodexProfileDir(tempHome: string): Promise<string> {
  const codexDir = join(tempHome, ".codex");
  let sourcePath: string | null = null;
  try {
    const current = await lstat(codexDir);
    if (current.isSymbolicLink()) {
      const target = await readlink(codexDir);
      sourcePath = isAbsolute(target) ? target : resolve(dirname(codexDir), target);
      await rm(codexDir, { recursive: true, force: true });
      await mkdir(codexDir, { recursive: true, mode: 0o700 });
    } else if (!current.isDirectory()) {
      await rm(codexDir, { recursive: true, force: true });
      await mkdir(codexDir, { recursive: true, mode: 0o700 });
    }
  } catch (error) {
    if ((error as { code?: string }).code !== "ENOENT") throw error;
    await mkdir(codexDir, { recursive: true, mode: 0o700 });
  }
  if (sourcePath) await linkCodexProfileContents(sourcePath, codexDir);
  return codexDir;
}

async function linkCodexProfileContents(sourcePath: string, codexDir: string): Promise<void> {
  for (const entry of await readdir(sourcePath, { withFileTypes: true })) {
    if (entry.name === "config.toml" || entry.name === "model-catalogs") continue;
    await symlink(join(sourcePath, entry.name), join(codexDir, entry.name));
  }
}

function renderCodexProviderToml(input: {
  providerName: string;
  proxyBaseUrl: string;
  leaseToken: string;
  model: string;
  catalogPath: string;
}): string {
  return [
    `model = ${tomlString(input.model)}`,
    `model_provider = "agent_space_provider"`,
    `model_catalog_json = ${tomlString(input.catalogPath)}`,
    "",
    `[model_providers.agent_space_provider]`,
    `name = ${tomlString(input.providerName)}`,
    `base_url = ${tomlString(input.proxyBaseUrl)}`,
    `experimental_bearer_token = ${tomlString(input.leaseToken)}`,
    `wire_api = "responses"`,
    "",
  ].join("\n");
}

function codexModelCatalog(
  providerName: string,
  selectedModel: string,
  availableModels: string[],
): Record<string, unknown> {
  const models = Array.from(new Set([selectedModel, ...availableModels].filter(Boolean)));
  return {
    models: models.map((model, index) => ({
      slug: model,
      display_name: model,
      description: providerName,
      default_reasoning_level: "none",
      supported_reasoning_levels: [
        { effort: "none", description: "Reasoning off" },
      ],
      shell_type: "shell_command",
      visibility: "list",
      supported_in_api: true,
      priority: index,
      base_instructions:
        `You are Codex, a coding agent using ${model} through ${providerName}. ` +
        "You and the user share the same workspace and collaborate to achieve the user's goals.",
      supports_reasoning_summaries: false,
      default_reasoning_summary: "none",
      support_verbosity: false,
      truncation_policy: { mode: "bytes", limit: 10000 },
      supports_parallel_tool_calls: true,
      experimental_supported_tools: [],
      input_modalities: ["text", "image"],
    })),
  };
}

function tomlString(value: string): string {
  return JSON.stringify(value);
}
