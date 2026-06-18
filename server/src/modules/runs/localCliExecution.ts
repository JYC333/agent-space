import { spawn } from "node:child_process";

export interface CliExecutionResult {
  returncode: number;
  stdout: string;
  stderr: string;
  timed_out: boolean;
}

export interface CliProcessRegistry {
  register(runId: string, pid: number): void;
  deregister(runId: string): void;
  terminate(runId: string): boolean;
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
  }): Promise<CliExecutionResult>;
}

export class LocalCliProcessRegistry implements CliProcessRegistry {
  private readonly processes = new Map<string, number>();

  register(runId: string, pid: number): void {
    this.processes.set(runId, pid);
  }

  deregister(runId: string): void {
    this.processes.delete(runId);
  }

  terminate(runId: string): boolean {
    const pid = this.processes.get(runId);
    if (!pid) return false;
    try {
      process.kill(-pid, "SIGTERM");
    } catch {
      try {
        process.kill(pid, "SIGTERM");
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
  }): Promise<CliExecutionResult> {
    return new Promise((resolveResult) => {
      let settled = false;
      let stdout = "";
      let stderr = "";
      const stdin = input.stdin;
      const hasStdin = stdin !== null;
      let proc;
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
      proc.stdout?.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf8");
      });
      proc.stderr?.on("data", (chunk: Buffer) => {
        stderr += chunk.toString("utf8");
      });
      proc.on("error", (error: Error) => {
        if (settled) return;
        settled = true;
        input.process_registry?.deregister(input.run_id);
        clearTimeout(timer);
        resolveResult({ returncode: -1, stdout, stderr: error.message, timed_out: false });
      });
      proc.on("close", (code: number | null) => {
        if (settled) return;
        settled = true;
        input.process_registry?.deregister(input.run_id);
        clearTimeout(timer);
        resolveResult({ returncode: code ?? -1, stdout, stderr, timed_out: false });
      });
      if (hasStdin) proc.stdin?.end(stdin);

      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        try {
          if (proc.pid) process.kill(-proc.pid, "SIGKILL");
        } catch {
          proc.kill("SIGKILL");
        }
        input.process_registry?.deregister(input.run_id);
        resolveResult({
          returncode: -1,
          stdout,
          stderr: stderr || "Command timed out.",
          timed_out: true,
        });
      }, input.timeout_seconds * 1000);
    });
  }
}
