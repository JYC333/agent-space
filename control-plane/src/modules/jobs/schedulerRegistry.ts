export interface ScheduledTask {
  name: string;
  intervalSeconds: number;
  run: () => Promise<void>;
  runOnStart?: boolean;
  awaitRunOnStart?: boolean;
}

export interface SchedulerLogger {
  warn(message: string): void;
  error(message: string): void;
}

export interface SchedulerHandle {
  readonly started: Promise<void>;
  readonly taskNames: readonly string[];
  stop(): Promise<void>;
}

export class SchedulerRegistry implements SchedulerHandle {
  private readonly tasks = new Map<string, ScheduledTask>();
  private readonly loops = new Map<string, Promise<void>>();
  private readonly sleepers = new Map<ReturnType<typeof setTimeout>, () => void>();
  private running = false;
  private stopping = false;
  private stopPromise: Promise<void> | null = null;
  private startPromise: Promise<void> = Promise.resolve();

  constructor(private readonly log?: SchedulerLogger) {}

  get started(): Promise<void> {
    return this.startPromise;
  }

  get taskNames(): readonly string[] {
    return Array.from(this.tasks.keys());
  }

  register(task: ScheduledTask): void {
    validateTask(task);
    if (this.running) {
      throw new Error("cannot register scheduled tasks after start");
    }
    if (this.tasks.has(task.name)) {
      throw new Error(`scheduled task already registered: ${task.name}`);
    }
    this.tasks.set(task.name, task);
  }

  start(): Promise<void> {
    if (this.running) return this.startPromise;
    this.running = true;
    this.stopping = false;
    this.stopPromise = null;
    this.startPromise = this.startInternal();
    return this.startPromise;
  }

  async stop(): Promise<void> {
    if (!this.running && this.stopPromise) return this.stopPromise;
    if (!this.running) return;
    this.stopping = true;
    for (const wake of Array.from(this.sleepers.values())) wake();
    this.stopPromise = Promise.allSettled([
      this.startPromise,
      ...this.loops.values(),
    ]).then(() => {
      this.loops.clear();
      this.running = false;
      this.stopping = false;
    });
    return this.stopPromise;
  }

  private async startInternal(): Promise<void> {
    for (const task of this.tasks.values()) {
      if (this.stopping) return;
      const runOnStart = task.runOnStart ?? true;
      if (runOnStart && task.awaitRunOnStart) {
        await this.runOnce(task);
        if (this.stopping) return;
        this.loops.set(task.name, this.runLoop(task, task.intervalSeconds));
      } else {
        this.loops.set(task.name, this.runLoop(task, runOnStart ? 0 : task.intervalSeconds));
      }
    }
  }

  private async runOnce(task: ScheduledTask): Promise<void> {
    if (this.stopping) return;
    try {
      await task.run();
    } catch (error) {
      this.log?.error(
        `[scheduler:${task.name}] ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  private sleep(ms: number): Promise<void> {
    if (this.stopping) return Promise.resolve();
    return new Promise((resolveSleep) => {
      const timer = setTimeout(() => {
        this.sleepers.delete(timer);
        resolveSleep();
      }, ms);
      timer.unref?.();
      this.sleepers.set(timer, () => {
        clearTimeout(timer);
        this.sleepers.delete(timer);
        resolveSleep();
      });
    });
  }

  private async runLoop(task: ScheduledTask, initialDelaySeconds: number): Promise<void> {
    if (initialDelaySeconds > 0) {
      await this.sleep(initialDelaySeconds * 1000);
    }
    while (!this.stopping) {
      await this.runOnce(task);
      if (!this.stopping) await this.sleep(task.intervalSeconds * 1000);
    }
  }
}

export function startSchedulerRegistry(
  tasks: ScheduledTask[],
  log?: SchedulerLogger,
): SchedulerHandle {
  const registry = new SchedulerRegistry(log);
  for (const task of tasks) {
    registry.register(task);
  }
  void registry.start();
  return registry;
}

function validateTask(task: ScheduledTask): void {
  if (!task.name) {
    throw new Error("scheduled task name is required");
  }
  if (task.intervalSeconds <= 0) {
    throw new Error(`scheduled task ${task.name} requires a positive interval`);
  }
  if (task.awaitRunOnStart && !(task.runOnStart ?? true)) {
    throw new Error("awaitRunOnStart requires runOnStart");
  }
}
