import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const jobsModule: ServerModule = {
  name: "jobs",
  registerRoutes,
};

export {
  JobHandlerRegistry,
  DuplicateJobHandlerError,
  UnknownJobTypeError,
} from "./handlerRegistry";
export { PgJobQueueRepository, type JobRecord, type EnqueueJobInput } from "./repository";
export { JobWorker } from "./worker";
export { startJobsWorker, buildJobHandlerRegistry, type JobsWorkerHandle } from "./workerRuntime";
export { SchedulerRegistry, startSchedulerRegistry, type ScheduledTask } from "./schedulerRegistry";
