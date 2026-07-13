import { spawn, type ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import { resolveHostPath } from "../providers/cli/hostPath";

const CONTAINER_HOME = "/home/sandbox";

export interface CliExecutionResult {
  returncode: number;
  stdout: string;
  stderr: string;
  timed_out: boolean;
  failure_code?: "timeout" | "stall_timeout" | "docker_sandbox_unavailable";
}

export interface DockerCliExecutionOptions {
  image: string;
  sandbox_cwd: string;
  sandbox_root: string;
  cli_tools_root: string;
  credential_root: string;
  credential_source_path: string | null;
  credential_target_path: string | null;
}

export interface CliProcessRegistry {
  register(runId: string, pid: number): void;
  deregister(runId: string): void;
  terminate(runId: string): boolean;
  forceTerminate?(runId: string): boolean;
  waitForExit?(runId: string, timeoutMs: number): Promise<boolean>;
  touchActivity?(runId: string): void;
}

export interface CliCommandExecutor {
  runCommand(input: {
    command: string[];
    cwd: string | null;
    timeout_seconds: number;
    env: Record<string, string>;
    run_id: string;
    stdin: string | null;
    process_registry?: CliProcessRegistry;
    stall_timeout_seconds?: number;
    docker?: DockerCliExecutionOptions;
  }): Promise<CliExecutionResult>;
}

export class LocalCliProcessRegistry implements CliProcessRegistry {
  private readonly processes = new Map<string, { pid: number; lastActivityAt: number }>();
  private readonly exitWaiters = new Map<string, Set<(exited: boolean) => void>>();

  register(runId: string, pid: number): void {
    this.processes.set(runId, { pid, lastActivityAt: Date.now() });
  }

  deregister(runId: string): void {
    this.processes.delete(runId);
    const waiters = this.exitWaiters.get(runId);
    if (!waiters) return;
    this.exitWaiters.delete(runId);
    for (const resolve of waiters) resolve(true);
  }

  terminate(runId: string): boolean {
    return this.signal(runId, "SIGTERM");
  }

  forceTerminate(runId: string): boolean {
    return this.signal(runId, "SIGKILL");
  }

  waitForExit(runId: string, timeoutMs: number): Promise<boolean> {
    if (!this.processes.has(runId)) return Promise.resolve(true);
    return new Promise((resolve) => {
      const waiters = this.exitWaiters.get(runId) ?? new Set<(exited: boolean) => void>();
      const resolveWithTimer = (exited: boolean) => {
        clearTimeout(timer);
        resolve(exited);
      };
      const timer = setTimeout(() => {
        waiters.delete(resolveWithTimer);
        if (waiters.size === 0) this.exitWaiters.delete(runId);
        resolve(false);
      }, Math.max(0, timeoutMs));
      timer.unref?.();
      waiters.add(resolveWithTimer);
      this.exitWaiters.set(runId, waiters);
    });
  }

  touchActivity(runId: string): void {
    const processInfo = this.processes.get(runId);
    if (processInfo) processInfo.lastActivityAt = Date.now();
  }

  private signal(runId: string, signal: NodeJS.Signals): boolean {
    const processInfo = this.processes.get(runId);
    if (!processInfo) return false;
    try {
      process.kill(-processInfo.pid, signal);
    } catch {
      try {
        process.kill(processInfo.pid, signal);
      } catch {
        return false;
      }
    }
    return true;
  }
}

export class LocalCliCommandExecutor implements CliCommandExecutor {
  async runCommand(input: {
    command: string[];
    cwd: string | null;
    timeout_seconds: number;
    env: Record<string, string>;
    run_id: string;
    stdin: string | null;
    process_registry?: CliProcessRegistry;
    stall_timeout_seconds?: number;
    docker?: DockerCliExecutionOptions;
  }): Promise<CliExecutionResult> {
    return new Promise((resolveResult) => {
      let settled = false;
      let stdout = "";
      let stderr = "";
      let timeoutTimer: ReturnType<typeof setTimeout> | undefined;
      let stallTimer: ReturnType<typeof setTimeout> | undefined;
      let stallEscalationTimer: ReturnType<typeof setTimeout> | undefined;
      let terminationReason: CliExecutionResult["failure_code"];
      const stdin = input.stdin;
      const hasStdin = stdin !== null;
      let proc: ChildProcess;

      const finish = (result: CliExecutionResult) => {
        if (settled) return;
        settled = true;
        if (timeoutTimer) clearTimeout(timeoutTimer);
        if (stallTimer) clearTimeout(stallTimer);
        if (stallEscalationTimer) clearTimeout(stallEscalationTimer);
        input.process_registry?.deregister(input.run_id);
        resolveResult(result);
      };

      const resetStallTimer = () => {
        if (!input.stall_timeout_seconds || input.stall_timeout_seconds <= 0) return;
        if (stallTimer) clearTimeout(stallTimer);
        stallTimer = setTimeout(() => {
          if (settled) return;
          terminationReason = "stall_timeout";
          const terminated = input.process_registry?.terminate(input.run_id) ?? false;
          if (!terminated) {
            try {
              if (proc?.pid) process.kill(-proc.pid, "SIGTERM");
            } catch {
              proc?.kill("SIGTERM");
            }
          }
          stallEscalationTimer = setTimeout(() => {
            if (settled) return;
            const forceKilled = input.process_registry?.forceTerminate?.(input.run_id) ?? false;
            if (!forceKilled) {
              try {
                if (proc?.pid) process.kill(-proc.pid, "SIGKILL");
              } catch {
                proc?.kill("SIGKILL");
              }
            }
          }, 2_000);
          stallEscalationTimer.unref?.();
        }, input.stall_timeout_seconds * 1000);
        stallTimer.unref?.();
      };

      try {
        proc = spawn(input.command[0], input.command.slice(1), {
          cwd: input.cwd ?? undefined,
          env: input.env,
          detached: true,
          shell: false,
          stdio: [hasStdin ? "pipe" : "ignore", "pipe", "pipe"],
        });
      } catch (error) {
        resolveResult({
          returncode: -1,
          stdout: "",
          stderr: error instanceof Error ? error.message : "CLI spawn failed.",
          timed_out: false,
        });
        return;
      }

      input.process_registry?.register(input.run_id, proc.pid ?? -1);
      resetStallTimer();
      proc.stdout?.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf8");
        input.process_registry?.touchActivity?.(input.run_id);
        resetStallTimer();
      });
      proc.stderr?.on("data", (chunk: Buffer) => {
        stderr += chunk.toString("utf8");
        input.process_registry?.touchActivity?.(input.run_id);
        resetStallTimer();
      });
      proc.on("error", (error: Error) => {
        finish({
          returncode: -1,
          stdout,
          stderr: error.message,
          timed_out: Boolean(terminationReason),
          failure_code: terminationReason,
        });
      });
      proc.on("close", (code: number | null) => {
        finish({
          returncode: code ?? -1,
          stdout,
          stderr: terminationReason === "stall_timeout"
            ? stderr || "Command produced no output or activity before the stall timeout."
            : stderr,
          timed_out: Boolean(terminationReason),
          failure_code: terminationReason,
        });
      });
      if (hasStdin) proc.stdin?.end(stdin);

      timeoutTimer = setTimeout(() => {
        if (settled) return;
        terminationReason = "timeout";
        try {
          if (proc.pid) process.kill(-proc.pid, "SIGKILL");
        } catch {
          proc.kill("SIGKILL");
        }
        finish({
          returncode: -1,
          stdout,
          stderr: stderr || "Command timed out.",
          timed_out: true,
          failure_code: "timeout",
        });
      }, input.timeout_seconds * 1000);
      timeoutTimer.unref?.();
    });
  }
}

/**
 * Runs a local CLI in a disposable, rootless sandbox container. The Docker
 * daemon is an execution dependency, never an authority exposed to the CLI:
 * the container receives only the run directory, the selected runtime tool
 * tree, and (optionally) one read-only credential profile.
 */
export class DockerCliCommandExecutor implements CliCommandExecutor {
  constructor(private readonly launcher: CliCommandExecutor = new LocalCliCommandExecutor()) {}

  async runCommand(input: {
    command: string[];
    cwd: string | null;
    timeout_seconds: number;
    env: Record<string, string>;
    run_id: string;
    stdin: string | null;
    process_registry?: CliProcessRegistry;
    stall_timeout_seconds?: number;
    docker?: DockerCliExecutionOptions;
  }): Promise<CliExecutionResult> {
    try {
      const docker = input.docker;
      if (!docker) return failedDockerResult("docker_execution_options_missing");
      const command = buildDockerCommand(input.command, docker, input.env);
      const env = dockerLauncherEnv(input.env);
      const result = await this.launcher.runCommand({
        command,
        cwd: null,
        timeout_seconds: input.timeout_seconds,
        stall_timeout_seconds: input.stall_timeout_seconds,
        env,
        run_id: input.run_id,
        stdin: input.stdin,
        process_registry: input.process_registry,
      });
      if (result.returncode === 125 || (result.returncode === -1 && !result.timed_out)) {
        return { ...result, failure_code: "docker_sandbox_unavailable" };
      }
      return result;
    } catch (error) {
      return failedDockerResult(error instanceof Error ? error.message : "Docker sandbox command construction failed.");
    }
  }
}

function buildDockerCommand(
  command: string[],
  docker: DockerCliExecutionOptions,
  env: Record<string, string>,
): string[] {
  if (command.length === 0) throw new Error("CLI command is empty");
  const sandbox = hostPath(docker.sandbox_cwd, "sandbox_cwd");
  const sandboxRoot = hostPath(docker.sandbox_root, "sandbox_root");
  if (sandbox === sandboxRoot || !isInside(sandbox, sandboxRoot)) {
    throw new Error("sandbox_cwd must be inside the configured sandbox root");
  }
  const tools = hostPath(docker.cli_tools_root, "cli_tools_root");
  const executable = hostPath(command[0], "runtime executable");
  if (!isInside(executable, tools)) {
    throw new Error("runtime executable must be inside the configured runtime tools root");
  }
  const containerExecutable = `/runtime-tools/${relative(tools, executable)}`;
  const containerCommand = [containerExecutable, ...command.slice(1).map((arg) =>
    arg === docker.sandbox_cwd ? "/workspace" : arg,
  )];
  const args = [
    "docker", "run", "--rm", "--init", "--pull=never",
    "--network", "none",
    "--read-only",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges=true",
    "--pids-limit", "256",
    "--memory", "1g",
    "--cpus", "1",
    "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
    "--tmpfs", "/run:rw,noexec,nosuid,size=16m",
    "--tmpfs", "/home/sandbox:rw,noexec,nosuid,size=64m",
    "--workdir", "/workspace",
    "--volume", `${sandbox}:/workspace:rw`,
    "--volume", `${tools}:/runtime-tools:ro`,
  ];
  if (docker.credential_source_path) {
    const credentialSource = hostPath(docker.credential_source_path, "credential_source_path");
    const credentialRoot = hostPath(docker.credential_root, "credential_root");
    if (credentialSource === credentialRoot || !isInside(credentialSource, credentialRoot)) {
      throw new Error("credential source must be inside the managed credential root");
    }
    const target = docker.credential_target_path
      ? containerCredentialTarget(docker.credential_target_path)
      : `${CONTAINER_HOME}/.runtime-profile`;
    args.push("--volume", `${credentialSource}:${target}:ro`);
  }
  args.push("--env", "HOME=/home/sandbox");
  for (const [key, value] of Object.entries(dockerEnv(env))) {
    args.push("--env", `${key}=${value}`);
  }
  args.push(docker.image, ...containerCommand);
  return args;
}

function dockerEnv(env: Record<string, string>): Record<string, string> {
  const safe: Record<string, string> = {};
  for (const [key, value] of Object.entries(env)) {
    if (key === "TERM" || key === "LANG" || key.startsWith("LC_")) safe[key] = value;
  }
  return safe;
}

function dockerLauncherEnv(env: Record<string, string>): Record<string, string> {
  const safe = dockerEnv(env);
  if (env.PATH) safe.PATH = env.PATH;
  return safe;
}

function containerCredentialTarget(target: string): string {
  const normalized = target.replaceAll("\\", "/");
  const base = normalized.startsWith("/home/")
    ? normalized.slice(normalized.indexOf("/", "/home/".length) + 1)
    : normalized.replace(/^\/+/, "");
  if (!base || base.includes("..")) throw new Error("invalid credential target path");
  return `${CONTAINER_HOME}/${base}`;
}

function hostPath(value: string, field: string): string {
  if (!value.startsWith("/")) throw new Error(`${field} must be absolute`);
  return resolveHostPath(resolve(value));
}

function isInside(child: string, parent: string): boolean {
  return child === parent || child.startsWith(`${parent}/`);
}

function relative(parent: string, child: string): string {
  const value = child.slice(parent.length).replace(/^\/+/, "");
  if (!value || value.includes("..")) throw new Error("runtime executable path is invalid");
  return value;
}

function failedDockerResult(message: string): CliExecutionResult {
  return { returncode: -1, stdout: "", stderr: message, timed_out: false };
}
