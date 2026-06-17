/**
 * CLI credential profile broker.
 *
 * This mirrors the durable broker behavior: discover managed CLI login-state
 * profiles, grant one profile to one run, and never expose credential file
 * contents through public APIs.
 */

import { mkdir, readdir, readFile, rm, stat, symlink, unlink, writeFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import YAML from "yaml";
import type { FastifyBaseLogger, FastifyReply } from "fastify";
import type { ServerConfig } from "../../config";
import { resolveHostPath } from "./hostPath";
import { runCliLogin, sendCliLoginInput } from "./cliLoginEngine";
import { CLI_LOGIN_ADAPTERS, cliLoginAdapterFor } from "./cliLoginAdapters";
import { readClaudeTokenUsage, unsupportedTokenUsage, type TokenUsage } from "./cliUsageReader";
import { readCodexTokenUsage } from "./codexUsageReader";
import { probeClaudeQuota, type QuotaResult } from "./cliUsageProbe";
import { probeClaudeOAuthQuota } from "./claudeOAuthUsageProbe";
import { probeCodexQuota } from "./codexUsageProbe";
import { CLI_USAGE_REFRESH_INTERVAL_MS } from "./cliUsageScheduler";
import { RuntimeToolRegistry } from "../runtimeTools";

export interface CredentialProfile {
  id: string;
  runtime: string;
  name: string;
  source_path: string;
  target_path: string;
  readonly: boolean;
  notes: string;
}

/** Subscription quota snapshot from the cached runtime-specific usage probe. */
export interface QuotaUsage {
  available: boolean;
  session_pct: number | null;
  session_resets: string | null;
  week_pct: number | null;
  week_resets: string | null;
  checked_at: string | null;
  error: string | null;
}

export interface CliUsageEntry {
  runtime: string;
  label: string;
  tokens: TokenUsage;
  quota: QuotaUsage | null;
}

export interface CliUsageAutoRefreshSettings {
  enabled: boolean;
  interval_ms: number;
  updated_at: string | null;
}

export interface CredentialGrant {
  granted: boolean;
  profile_id: string | null;
  runtime: string;
  executor_mode: "worktree" | "docker";
  readonly: boolean;
  temp_home: string | null;
  host_source_path: string | null;
  target_path: string | null;
  env: Record<string, string>;
  fallback_reason: string | null;
}

function defaultTargetPath(runtime: string): string {
  return cliLoginAdapterFor(runtime)?.target_path ?? `/home/agent/.${runtime}`;
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function fileCount(path: string): Promise<number> {
  try {
    return (await readdir(path)).length;
  } catch {
    return 0;
  }
}

function cleanComponent(value: string, field: string): string {
  if (!/^[A-Za-z0-9_.-]+$/.test(value)) {
    throw new Error(`${field} may contain only letters, numbers, dot, underscore, and dash`);
  }
  return value;
}

function sse(event: Record<string, unknown>): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

type CliCredentialBrokerLogger = Pick<FastifyBaseLogger, "info" | "warn">;

function errorSummary(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export class CliCredentialBroker {
  constructor(private config: ServerConfig, private logger?: CliCredentialBrokerLogger) {}

  private get credentialsRoot(): string {
    return join(this.config.agentSpaceHome, "secrets", "cli-credentials");
  }

  private get configPath(): string {
    return join(this.config.agentSpaceHome, "config", "cli-credentials.yaml");
  }

  private get runtimeHomesRoot(): string {
    return join(this.config.agentSpaceHome, "cache", "runtime-homes");
  }

  /** Transient HOME the interactive login writes into, kept under aspace so the
   * vendor CLI never touches the operator's real ~/.<runtime>. */
  private get loginHomesRoot(): string {
    return join(this.config.agentSpaceHome, "cache", "login-homes");
  }

  async listProfiles(runtime?: string | null): Promise<CredentialProfile[]> {
    const profiles = await this.loadProfiles();
    const all = [...profiles.values()];
    return runtime ? all.filter((p) => p.runtime === runtime) : all;
  }

  async getProfile(profileId: string): Promise<CredentialProfile | null> {
    return (await this.loadProfiles()).get(profileId) ?? null;
  }

  async getDefaultProfile(runtime: string): Promise<CredentialProfile | null> {
    const profiles = await this.loadProfiles();
    const exact = profiles.get(`${runtime}/default`);
    if (exact && (await exists(exact.source_path))) return exact;
    for (const profile of profiles.values()) {
      if (profile.runtime === runtime && (await exists(profile.source_path))) {
        return profile;
      }
    }
    return null;
  }

  async profileOut(profile: CredentialProfile): Promise<Record<string, unknown>> {
    return { ...profile, source_exists: await exists(profile.source_path) };
  }

  async detectProfile(profileId: string): Promise<Record<string, unknown>> {
    const profile = await this.getProfile(profileId);
    if (!profile) throw new Error(`Profile '${profileId}' not found`);
    const sourceExists = await exists(profile.source_path);
    const count = sourceExists ? await fileCount(profile.source_path) : 0;
    return {
      profile_id: profileId,
      source_path: profile.source_path,
      exists: sourceExists,
      non_empty: count > 0,
      file_count: count,
      target_path: profile.target_path,
      readonly: profile.readonly,
    };
  }

  listLoginMethods(): Record<string, unknown>[] {
    return CLI_LOGIN_ADAPTERS.map((cfg) => ({
      runtime: cfg.runtime,
      method: cfg.method,
      label: cfg.label,
      hint_cli: cfg.hint_cli ?? "",
      supports_cli: Boolean(cfg.command),
    }));
  }

  async status(): Promise<Record<string, unknown>[]> {
    const result: Record<string, unknown>[] = [];
    for (const cfg of CLI_LOGIN_ADAPTERS) {
      const profile = await this.getDefaultProfile(cfg.runtime);
      const sourceExists = profile !== null && (await exists(profile.source_path));
      const count = sourceExists && profile ? await fileCount(profile.source_path) : 0;
      result.push({
        runtime: cfg.runtime,
        label: cfg.label,
        method: cfg.method,
        profile_id: profile?.id ?? null,
        logged_in: sourceExists && count > 0,
        file_count: count,
      });
    }
    return result;
  }

  /**
   * Per-runtime usage for the Credentials panel: cumulative token usage parsed
   * from local CLI transcripts/sessions (offline). `quota` is filled by the
   * cached runtime-specific probe and stays null for runtimes/builds without it.
   */
  async cliUsage(): Promise<CliUsageEntry[]> {
    const result: CliUsageEntry[] = [];
    for (const cfg of CLI_LOGIN_ADAPTERS) {
      const profile = await this.getDefaultProfile(cfg.runtime);
      let tokens: TokenUsage = unsupportedTokenUsage();
      let quota: QuotaResult | null = null;
      if (cfg.runtime === "claude_code" && profile) {
        tokens = await readClaudeTokenUsage(profile.source_path);
        quota = await this.readQuotaCache(cfg.runtime); // last probed value; UI refreshes on demand
      } else if (cfg.runtime === "codex_cli" && profile) {
        tokens = await readCodexTokenUsage(profile.source_path);
        quota = await this.readQuotaCache(cfg.runtime);
      }
      result.push({ runtime: cfg.runtime, label: cfg.label, tokens, quota });
    }
    return result;
  }

  /**
   * Run the live quota probe for a runtime, persist it to the cache, and return
   * the combined (tokens + fresh quota) entry. Runtimes without a quota adapter
   * return token usage with quota=null.
   */
  async refreshCliQuota(runtime: string): Promise<CliUsageEntry> {
    const cfg = cliLoginAdapterFor(runtime);
    if (!cfg) throw new Error(`Unknown runtime: ${runtime}`);
    const profile = await this.getDefaultProfile(runtime);
    let tokens: TokenUsage = unsupportedTokenUsage();
    let quota: QuotaResult | null = null;

    if (runtime === "claude_code") {
      if (profile) tokens = await readClaudeTokenUsage(profile.source_path);
      if (!profile) {
        this.logger?.info(
          { runtime, source: "none" },
          "Claude usage quota probe skipped: no CLI credential profile",
        );
        quota = {
          available: false,
          session_pct: null,
          session_resets: null,
          week_pct: null,
          week_resets: null,
          checked_at: null,
          error: "Log in to Claude Code before reading usage.",
        };
      } else {
        try {
          this.logger?.info(
            {
              runtime,
              profile_id: profile.id,
              source: "claude_oauth_usage_api",
            },
            "Claude usage quota probe starting",
          );
          quota = await probeClaudeOAuthQuota(profile.source_path);
          this.logger?.info(
            {
              runtime,
              profile_id: profile.id,
              source: "claude_oauth_usage_api",
              available: quota.available,
              session_pct: quota.session_pct,
              week_pct: quota.week_pct,
            },
            "Claude usage quota probe succeeded",
          );
        } catch (oauthError) {
          this.logger?.warn(
            {
              runtime,
              profile_id: profile.id,
              source: "claude_oauth_usage_api",
              fallback_source: "claude_pty_usage_fallback",
              error: errorSummary(oauthError),
            },
            "Claude OAuth usage probe failed; falling back to PTY usage probe",
          );
          // HOME with .claude symlinked to the profile, so the CLI fallback
          // authenticates with managed credentials and never touches host HOME.
          const probeHome = await this.createTempHome("usage-probe", profile);
          try {
            quota = await probeClaudeQuota(probeHome, new RuntimeToolRegistry(this.config));
            if (quota.available) {
              this.logger?.info(
                {
                  runtime,
                  profile_id: profile.id,
                  source: "claude_pty_usage_fallback",
                  available: quota.available,
                  session_pct: quota.session_pct,
                  week_pct: quota.week_pct,
                  error: quota.error,
                },
                "Claude PTY usage fallback probe succeeded",
              );
            } else {
              this.logger?.warn(
                {
                  runtime,
                  profile_id: profile.id,
                  source: "claude_pty_usage_fallback",
                  available: quota.available,
                  error: quota.error,
                },
                "Claude PTY usage fallback probe returned no quota",
              );
            }
          } catch (ptyError) {
            this.logger?.warn(
              {
                runtime,
                profile_id: profile.id,
                source: "claude_pty_usage_fallback",
                error: errorSummary(ptyError),
              },
              "Claude PTY usage fallback probe failed",
            );
            throw ptyError;
          }
        }
      }
      quota.checked_at = new Date().toISOString();
      await this.writeQuotaCache(runtime, quota);
    } else if (runtime === "codex_cli") {
      if (profile) tokens = await readCodexTokenUsage(profile.source_path);
      if (!profile) {
        quota = {
          available: false,
          session_pct: null,
          session_resets: null,
          week_pct: null,
          week_resets: null,
          checked_at: null,
          error: "Log in to Codex CLI before reading usage.",
        };
      } else {
        const probeHome = await this.createTempHome("usage-probe-codex", profile);
        quota = await probeCodexQuota(
          profile.source_path,
          probeHome,
          new RuntimeToolRegistry(this.config),
        );
      }
      quota.checked_at = new Date().toISOString();
      await this.writeQuotaCache(runtime, quota);
    }
    return { runtime, label: cfg.label, tokens, quota };
  }

  async refreshStaleCliQuota(runtime: string, maxAgeMs: number): Promise<CliUsageEntry | null> {
    const cfg = cliLoginAdapterFor(runtime);
    if (!cfg) throw new Error(`Unknown runtime: ${runtime}`);
    if (runtime !== "claude_code" && runtime !== "codex_cli") return null;

    const cached = await this.readQuotaCache(runtime);
    const checkedAt = cached?.checked_at ? Date.parse(cached.checked_at) : Number.NaN;
    if (Number.isFinite(checkedAt) && Date.now() - checkedAt < maxAgeMs) {
      return null;
    }
    return this.refreshCliQuota(runtime);
  }

  private quotaCachePath(runtime: string): string {
    return join(this.config.agentSpaceHome, "cache", "cli-quota", `${runtime}.json`);
  }

  private get legacyClaudeQuotaCachePath(): string {
    return join(this.config.agentSpaceHome, "cache", "quota-cache.json");
  }

  private get usageAutoRefreshSettingsPath(): string {
    return join(this.config.agentSpaceHome, "config", "cli-usage-auto-refresh.json");
  }

  async cliUsageAutoRefreshSettings(): Promise<CliUsageAutoRefreshSettings> {
    try {
      const raw = JSON.parse(await readFile(this.usageAutoRefreshSettingsPath, "utf8")) as Record<string, unknown>;
      return {
        enabled: typeof raw.enabled === "boolean" ? raw.enabled : true,
        interval_ms: CLI_USAGE_REFRESH_INTERVAL_MS,
        updated_at: typeof raw.updated_at === "string" ? raw.updated_at : null,
      };
    } catch {
      return {
        enabled: true,
        interval_ms: CLI_USAGE_REFRESH_INTERVAL_MS,
        updated_at: null,
      };
    }
  }

  async setCliUsageAutoRefresh(enabled: boolean): Promise<CliUsageAutoRefreshSettings> {
    const settings: CliUsageAutoRefreshSettings = {
      enabled,
      interval_ms: CLI_USAGE_REFRESH_INTERVAL_MS,
      updated_at: new Date().toISOString(),
    };
    await mkdir(dirname(this.usageAutoRefreshSettingsPath), { recursive: true });
    await writeFile(this.usageAutoRefreshSettingsPath, JSON.stringify(settings), "utf8");
    return settings;
  }

  async isCliUsageAutoRefreshEnabled(): Promise<boolean> {
    return (await this.cliUsageAutoRefreshSettings()).enabled;
  }

  private async readQuotaCache(runtime: string): Promise<QuotaResult | null> {
    try {
      return JSON.parse(await readFile(this.quotaCachePath(runtime), "utf8")) as QuotaResult;
    } catch {
      if (runtime !== "claude_code") return null;
      try {
        return JSON.parse(await readFile(this.legacyClaudeQuotaCachePath, "utf8")) as QuotaResult;
      } catch {
        return null;
      }
    }
  }

  private async writeQuotaCache(runtime: string, quota: QuotaResult): Promise<void> {
    try {
      await mkdir(dirname(this.quotaCachePath(runtime)), { recursive: true });
      await writeFile(this.quotaCachePath(runtime), JSON.stringify(quota), "utf8");
    } catch {
      // Best-effort cache; a probe is still returned to the caller.
    }
  }

  async resolveProfile(
    runtime: string,
    profileId?: string | null,
    requireExisting = true,
  ): Promise<CredentialProfile | null> {
    const profile = profileId ? await this.getProfile(profileId) : await this.getDefaultProfile(runtime);
    if (!profile) return null;
    if (requireExisting && !(await exists(profile.source_path))) return null;
    return profile;
  }

  async grantForRun(
    runId: string,
    runtime: string,
    executorMode: "worktree" | "docker",
    profileId?: string | null,
  ): Promise<CredentialGrant> {
    const profile = await this.resolveProfile(runtime, profileId, true);
    if (!profile) {
      return {
        granted: false,
        profile_id: null,
        runtime,
        executor_mode: executorMode,
        readonly: false,
        temp_home: null,
        host_source_path: null,
        target_path: null,
        env: {},
        fallback_reason: "no_profile_configured",
      };
    }
    if (executorMode === "docker") {
      return {
        granted: true,
        profile_id: profile.id,
        runtime,
        executor_mode: "docker",
        readonly: profile.readonly,
        temp_home: null,
        // The sandbox launcher mounts this through the HOST Docker daemon.
        host_source_path: resolveHostPath(profile.source_path),
        target_path: profile.target_path,
        env: {},
        fallback_reason: null,
      };
    }
    const tempHome = await this.createTempHome(runId, profile);
    return {
      granted: true,
      profile_id: profile.id,
      runtime,
      executor_mode: "worktree",
      readonly: false,
      temp_home: tempHome,
      host_source_path: null,
      target_path: null,
      env: { HOME: tempHome },
      fallback_reason: null,
    };
  }

  async cleanupRunHome(runId: string): Promise<void> {
    await rm(join(this.runtimeHomesRoot, cleanComponent(runId, "run_id")), {
      recursive: true,
      force: true,
    });
  }

  async streamLogin(runtime: string, reply: FastifyReply): Promise<void> {
    reply.raw.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      "x-accel-buffering": "no",
    });
    const profileDir = join(this.credentialsRoot, runtime, "default");
    // Only known runtimes reach a real login; a clean component keeps the
    // login HOME path inside aspace even if an unknown runtime slips through.
    const adapter = cliLoginAdapterFor(runtime);
    const safeRuntime = adapter ? cleanComponent(runtime, "runtime") : "_invalid";
    const loginHome = join(this.loginHomesRoot, safeRuntime);
    const tools = new RuntimeToolRegistry(this.config);
    await runCliLogin(runtime, adapter, profileDir, (event) => {
      reply.raw.write(sse(event));
    }, undefined, tools, loginHome);
    reply.raw.end();
  }

  sendLoginInput(runtime: string, input: string): boolean {
    return sendCliLoginInput(runtime, input);
  }

  private async loadProfiles(): Promise<Map<string, CredentialProfile>> {
    const profiles = new Map<string, CredentialProfile>();
    try {
      const raw = await readFile(this.configPath, "utf8");
      const parsed = YAML.parse(raw) as
        | { profiles?: Record<string, Record<string, Partial<CredentialProfile>>> }
        | null;
      for (const [runtime, named] of Object.entries(parsed?.profiles ?? {})) {
        for (const [name, spec] of Object.entries(named ?? {})) {
          const id = `${runtime}/${name}`;
          profiles.set(id, {
            id,
            runtime,
            name,
            source_path: spec.source_path ?? "",
            target_path: spec.target_path ?? defaultTargetPath(runtime),
            readonly: Boolean(spec.readonly),
            notes: spec.notes ?? "",
          });
        }
      }
    } catch (error) {
      const code = (error as { code?: string }).code;
      if (code !== "ENOENT") throw error;
    }

    try {
      for (const runtimeDir of await readdir(this.credentialsRoot, { withFileTypes: true })) {
        if (!runtimeDir.isDirectory()) continue;
        for (const profileDir of await readdir(join(this.credentialsRoot, runtimeDir.name), {
          withFileTypes: true,
        })) {
          if (!profileDir.isDirectory()) continue;
          const id = `${runtimeDir.name}/${profileDir.name}`;
          if (!profiles.has(id)) {
            profiles.set(id, {
              id,
              runtime: runtimeDir.name,
              name: profileDir.name,
              source_path: join(this.credentialsRoot, runtimeDir.name, profileDir.name),
              target_path: defaultTargetPath(runtimeDir.name),
              readonly: false,
              notes: "",
            });
          }
        }
      }
    } catch (error) {
      const code = (error as { code?: string }).code;
      if (code !== "ENOENT") throw error;
    }
    return profiles;
  }

  private async createTempHome(runId: string, profile: CredentialProfile): Promise<string> {
    const tempHome = join(this.runtimeHomesRoot, cleanComponent(runId, "run_id"));
    await mkdir(tempHome, { recursive: true, mode: 0o700 });
    const linkName = basename(profile.target_path || `.${profile.runtime}`);
    const linkPath = join(tempHome, linkName);
    try {
      await unlink(linkPath);
    } catch {
      // absent is fine; a stale broken symlink throws the same way as a file.
    }
    await symlink(profile.source_path, linkPath);
    const claudeJson = join(profile.source_path, ".claude.json");
    if (await exists(claudeJson)) {
      const claudeJsonLink = join(tempHome, ".claude.json");
      try {
        await unlink(claudeJsonLink);
      } catch {}
      await symlink(claudeJson, claudeJsonLink);
    }
    return tempHome;
  }
}
