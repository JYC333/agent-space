import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import {
  access,
  lstat,
  mkdir,
  readFile,
  readlink,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import type { ControlPlaneConfig } from "../../config";

export interface RuntimeToolDefinition {
  runtime: string;
  label: string;
  source: "npm";
  package_name: string;
  bin_name: string;
  bin_relative_path: string;
  package_json_relative_path: string;
  default_version: string;
}

export interface RuntimeToolManifest {
  schema_version: 1;
  runtime: string;
  source: "npm";
  package_name: string;
  requested_version: string;
  version: string;
  bin_name: string;
  bin_relative_path: string;
  installed_at: string;
}

export interface RuntimeToolStatus {
  runtime: string;
  label: string;
  source: "npm";
  package_name: string;
  bin_name: string;
  installed: boolean;
  active_version: string | null;
  executable_path: string | null;
  executable_exists: boolean;
  manifest: RuntimeToolManifest | null;
  warnings: string[];
}

export interface RuntimeToolInstallInput {
  version?: string | null;
  activate?: boolean;
  force?: boolean;
}

export interface RuntimeToolInstallResult extends RuntimeToolStatus {
  installed_version: string;
  activated: boolean;
}

export interface RuntimeToolLatest {
  runtime: string;
  package_name: string;
  latest_version: string | null;
}

export interface ResolvedRuntimeTool {
  runtime: string;
  executable_path: string;
  version: string;
  source: "npm";
  package_name: string;
}

export interface RuntimeToolResolverPort {
  resolveForExecution(runtime: string): Promise<ResolvedRuntimeTool>;
}

export interface RuntimeToolInstallRunner {
  run(input: { package_ref: string; prefix: string; cache_dir: string }): Promise<void>;
}

export const RUNTIME_TOOL_DEFINITIONS: Record<string, RuntimeToolDefinition> = {
  claude_code: {
    runtime: "claude_code",
    label: "Claude Code",
    source: "npm",
    package_name: "@anthropic-ai/claude-code",
    bin_name: "claude",
    bin_relative_path: join("node_modules", ".bin", "claude"),
    package_json_relative_path: join("node_modules", "@anthropic-ai", "claude-code", "package.json"),
    default_version: "latest",
  },
  codex_cli: {
    runtime: "codex_cli",
    label: "Codex CLI",
    source: "npm",
    package_name: "@openai/codex",
    bin_name: "codex",
    bin_relative_path: join("node_modules", ".bin", "codex"),
    package_json_relative_path: join("node_modules", "@openai", "codex", "package.json"),
    default_version: "latest",
  },
};

const INSTALL_OUTPUT_LIMIT = 12_000;
const NPM_INSTALL_TIMEOUT_MS = 5 * 60 * 1000;
const LATEST_VERSION_TIMEOUT_MS = 10_000;
const VERSION_REF_RE = /^[A-Za-z0-9_.@+-]+$/;
const COMPONENT_RE = /^[A-Za-z0-9_.-]+$/;

export class RuntimeToolError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly statusCode = 400,
  ) {
    super(message);
    this.name = "RuntimeToolError";
  }
}

function definitionFor(runtime: string): RuntimeToolDefinition {
  const definition = RUNTIME_TOOL_DEFINITIONS[runtime];
  if (!definition) {
    throw new RuntimeToolError(
      "runtime_tool_not_allowlisted",
      `Runtime tool '${runtime}' is not allowlisted.`,
      404,
    );
  }
  return definition;
}

function cleanComponent(value: string, field: string): string {
  if (!COMPONENT_RE.test(value)) {
    throw new RuntimeToolError(
      "invalid_runtime_tool_component",
      `${field} may contain only letters, numbers, dot, underscore, and dash.`,
      400,
    );
  }
  return value;
}

function validateVersionRef(value: string): string {
  if (!VERSION_REF_RE.test(value)) {
    throw new RuntimeToolError(
      "invalid_runtime_tool_version",
      "version may contain only letters, numbers, dot, underscore, dash, plus, and @.",
      400,
    );
  }
  return value;
}

async function exists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

async function executableExists(path: string): Promise<boolean> {
  try {
    await access(path, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function isWithinRoot(root: string, candidate: string): boolean {
  const rel = relative(resolve(root), resolve(candidate));
  return rel === "" || (!rel.startsWith("..") && !rel.startsWith("/"));
}

function boundedAppend(current: string, chunk: Buffer): string {
  if (current.length >= INSTALL_OUTPUT_LIMIT) return current;
  const next = current + chunk.toString("utf8");
  return next.length > INSTALL_OUTPUT_LIMIT
    ? `${next.slice(0, INSTALL_OUTPUT_LIMIT)}\n[TRUNCATED]`
    : next;
}

function packageRef(definition: RuntimeToolDefinition, version: string): string {
  return `${definition.package_name}@${version}`;
}

function codexNativePackageName(): string | null {
  if (process.platform !== "linux") return null;
  if (process.arch === "x64") return "@openai/codex-linux-x64";
  if (process.arch === "arm64") return "@openai/codex-linux-arm64";
  return null;
}

function codexNativePackagePath(versionRoot: string): string | null {
  const packageName = codexNativePackageName();
  if (!packageName) return null;
  const [scope, name] = packageName.split("/");
  return join(versionRoot, "node_modules", scope, name);
}

async function readJsonFile<T>(path: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(path, "utf8")) as T;
  } catch {
    return null;
  }
}

async function runNpmInstall(input: {
  package_ref: string;
  prefix: string;
  cache_dir: string;
}): Promise<void> {
  await mkdir(input.cache_dir, { recursive: true, mode: 0o700 });
  const args = [
    "install",
    "--prefix",
    input.prefix,
    "--omit=dev",
    "--include=optional",
    "--no-audit",
    "--no-fund",
    "--cache",
    input.cache_dir,
    input.package_ref,
  ];
  const safeEnv: Record<string, string> = {};
  for (const key of ["PATH", "HOME", "LANG", "TERM"]) {
    const value = process.env[key];
    if (value) safeEnv[key] = value;
  }
  for (const [key, value] of Object.entries(process.env)) {
    if (value && key.startsWith("LC_")) safeEnv[key] = value;
  }
  await new Promise<void>((resolvePromise, reject) => {
    let output = "";
    let settled = false;
    let proc;
    try {
      proc = spawn("npm", args, {
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
        env: safeEnv,
      });
    } catch (error) {
      reject(error);
      return;
    }
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      proc.kill("SIGKILL");
      reject(
        new RuntimeToolError(
          "runtime_tool_install_timeout",
          "Runtime tool install timed out.",
          504,
        ),
      );
    }, NPM_INSTALL_TIMEOUT_MS);
    proc.stdout?.on("data", (chunk: Buffer) => {
      output = boundedAppend(output, chunk);
    });
    proc.stderr?.on("data", (chunk: Buffer) => {
      output = boundedAppend(output, chunk);
    });
    proc.on("error", (error: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
    proc.on("close", (code: number | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code === 0) return resolvePromise();
      reject(
        new RuntimeToolError(
          "runtime_tool_install_failed",
          output.trim() || `npm install exited with ${code ?? -1}.`,
          502,
        ),
      );
    });
  });
}

export class RuntimeToolRegistry implements RuntimeToolResolverPort {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly runner: RuntimeToolInstallRunner = { run: runNpmInstall },
  ) {}

  listDefinitions(): RuntimeToolDefinition[] {
    return Object.values(RUNTIME_TOOL_DEFINITIONS);
  }

  async listStatus(): Promise<RuntimeToolStatus[]> {
    return Promise.all(this.listDefinitions().map((definition) => this.status(definition.runtime)));
  }

  async status(runtime: string): Promise<RuntimeToolStatus> {
    const definition = definitionFor(runtime);
    const root = this.runtimeRoot(definition.runtime);
    const activePath = join(root, "active");
    const warnings: string[] = [];
    let activeVersion: string | null = null;
    let manifest: RuntimeToolManifest | null = null;
    let executablePath: string | null = null;
    let executableOk = false;

    try {
      const stat = await lstat(activePath);
      if (!stat.isSymbolicLink()) {
        warnings.push("active path exists but is not a symlink");
      } else {
        const target = await readlink(activePath);
        if (!target.startsWith("versions/")) {
          warnings.push("active symlink target is invalid");
        } else {
          activeVersion = cleanComponent(target.slice("versions/".length), "active_version");
        }
        if (!activeVersion) {
          return {
            runtime: definition.runtime,
            label: definition.label,
            source: definition.source,
            package_name: definition.package_name,
            bin_name: definition.bin_name,
            installed: false,
            active_version: null,
            executable_path: null,
            executable_exists: false,
            manifest: null,
            warnings,
          };
        }
        const versionRoot = this.versionRoot(definition.runtime, activeVersion);
        manifest = await this.readManifest(definition.runtime, activeVersion);
        executablePath = resolve(versionRoot, definition.bin_relative_path);
        executableOk = await executableExists(executablePath);
        if (!executableOk) warnings.push("active executable is missing or not executable");
        const nativePackagePath = definition.runtime === "codex_cli"
          ? codexNativePackagePath(versionRoot)
          : null;
        if (nativePackagePath && !(await exists(nativePackagePath))) {
          executableOk = false;
          warnings.push(`${codexNativePackageName()} is missing; reinstall the Codex runtime tool.`);
        }
      }
    } catch (error) {
      const code = (error as { code?: string }).code;
      if (code !== "ENOENT") warnings.push(error instanceof Error ? error.message : String(error));
    }

    return {
      runtime: definition.runtime,
      label: definition.label,
      source: definition.source,
      package_name: definition.package_name,
      bin_name: definition.bin_name,
      installed: executableOk,
      active_version: activeVersion,
      executable_path: executablePath,
      executable_exists: executableOk,
      manifest,
      warnings,
    };
  }

  /**
   * Look up the package's current published version from the npm registry — the
   * same registry `install` pulls from — so the UI can tell whether an update is
   * available. Network call; surfaces a 502 RuntimeToolError when unreachable.
   */
  async latestVersion(runtime: string): Promise<RuntimeToolLatest> {
    const definition = definitionFor(runtime);
    const url = `https://registry.npmjs.org/${definition.package_name}/latest`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), LATEST_VERSION_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: { accept: "application/json" },
      });
      if (!response.ok) {
        throw new RuntimeToolError(
          "runtime_tool_latest_failed",
          `npm registry returned ${response.status}.`,
          502,
        );
      }
      const body = (await response.json()) as { version?: unknown };
      return {
        runtime: definition.runtime,
        package_name: definition.package_name,
        latest_version: typeof body.version === "string" ? body.version : null,
      };
    } catch (error) {
      if (error instanceof RuntimeToolError) throw error;
      throw new RuntimeToolError(
        "runtime_tool_latest_failed",
        "Could not reach the npm registry to check for updates.",
        502,
      );
    } finally {
      clearTimeout(timer);
    }
  }

  async resolveForExecution(runtime: string): Promise<ResolvedRuntimeTool> {
    const definition = definitionFor(runtime);
    const status = await this.status(runtime);
    if (!status.installed || !status.executable_path || !status.active_version) {
      throw new RuntimeToolError(
        "cli_tool_not_installed",
        `Runtime tool '${runtime}' is not installed.`,
        409,
      );
    }
    const root = this.runtimeRoot(runtime);
    const resolved = resolve(status.executable_path);
    if (!isWithinRoot(root, resolved)) {
      throw new RuntimeToolError(
        "runtime_tool_path_escape",
        "Runtime tool executable escapes its installation root.",
        500,
      );
    }
    return {
      runtime,
      executable_path: resolved,
      version: status.active_version,
      source: definition.source,
      package_name: definition.package_name,
    };
  }

  async install(runtime: string, input: RuntimeToolInstallInput = {}): Promise<RuntimeToolInstallResult> {
    const definition = definitionFor(runtime);
    const requestedVersion = validateVersionRef(input.version?.trim() || definition.default_version);
    const runtimeRoot = this.runtimeRoot(runtime);
    const tmpRoot = join(runtimeRoot, ".tmp");
    const tmpDir = join(tmpRoot, `install-${Date.now()}-${randomUUID()}`);
    await mkdir(tmpRoot, { recursive: true, mode: 0o700 });
    try {
      await this.runner.run({
        package_ref: packageRef(definition, requestedVersion),
        prefix: tmpDir,
        cache_dir: join(this.config.agentSpaceHome, "cache", "npm"),
      });
      const packageJson = await readJsonFile<{ version?: string }>(
        join(tmpDir, definition.package_json_relative_path),
      );
      const installedVersion = cleanComponent(
        packageJson?.version ?? requestedVersion,
        "installed_version",
      );
      const binPath = join(tmpDir, definition.bin_relative_path);
      if (!(await executableExists(binPath))) {
        throw new RuntimeToolError(
          "runtime_tool_binary_missing",
          `Installed package did not provide executable '${definition.bin_name}'.`,
          502,
        );
      }
      const nativePackagePath = definition.runtime === "codex_cli"
        ? codexNativePackagePath(tmpDir)
        : null;
      if (nativePackagePath && !(await exists(nativePackagePath))) {
        throw new RuntimeToolError(
          "runtime_tool_optional_dependency_missing",
          `${codexNativePackageName()} was not installed. Reinstall Codex with optional npm dependencies enabled.`,
          502,
        );
      }
      const target = this.versionRoot(runtime, installedVersion);
      if (await exists(target)) {
        if (!input.force) {
          await rm(tmpDir, { recursive: true, force: true });
          if (input.activate !== false) await this.activate(runtime, installedVersion);
          const status = await this.status(runtime);
          return { ...status, installed_version: installedVersion, activated: input.activate !== false };
        }
        await rm(target, { recursive: true, force: true });
      }
      await mkdir(dirname(target), { recursive: true, mode: 0o700 });
      await writeFile(
        join(tmpDir, "tool.json"),
        `${JSON.stringify(
          {
            schema_version: 1,
            runtime,
            source: definition.source,
            package_name: definition.package_name,
            requested_version: requestedVersion,
            version: installedVersion,
            bin_name: definition.bin_name,
            bin_relative_path: definition.bin_relative_path,
            installed_at: new Date().toISOString(),
          } satisfies RuntimeToolManifest,
          null,
          2,
        )}\n`,
        { mode: 0o600 },
      );
      await rename(tmpDir, target);
      if (input.activate !== false) await this.activate(runtime, installedVersion);
      const status = await this.status(runtime);
      return { ...status, installed_version: installedVersion, activated: input.activate !== false };
    } catch (error) {
      await rm(tmpDir, { recursive: true, force: true }).catch(() => undefined);
      throw error;
    }
  }

  async activate(runtime: string, version: string): Promise<RuntimeToolStatus> {
    const definition = definitionFor(runtime);
    const cleanVersion = cleanComponent(version, "version");
    const versionRoot = this.versionRoot(runtime, cleanVersion);
    const executablePath = join(versionRoot, definition.bin_relative_path);
    if (!(await executableExists(executablePath))) {
      throw new RuntimeToolError(
        "runtime_tool_version_not_installed",
        `Runtime tool '${runtime}' version '${version}' is not installed or is not executable.`,
        404,
      );
    }
    const runtimeRoot = this.runtimeRoot(runtime);
    await mkdir(runtimeRoot, { recursive: true, mode: 0o700 });
    const tmpLink = join(runtimeRoot, `.active-${randomUUID()}`);
    await symlink(join("versions", cleanVersion), tmpLink);
    await rename(tmpLink, join(runtimeRoot, "active"));
    return this.status(runtime);
  }

  private runtimeRoot(runtime: string): string {
    return resolve(this.config.cliToolsRoot, cleanComponent(runtime, "runtime"));
  }

  private versionRoot(runtime: string, version: string): string {
    return resolve(this.runtimeRoot(runtime), "versions", cleanComponent(version, "version"));
  }

  private async readManifest(runtime: string, version: string): Promise<RuntimeToolManifest | null> {
    return readJsonFile<RuntimeToolManifest>(join(this.versionRoot(runtime, version), "tool.json"));
  }
}
