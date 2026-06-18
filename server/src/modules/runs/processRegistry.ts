import { LocalCliProcessRegistry } from "./localCliExecution";

/**
 * Process-wide CLI process registry. Execute paths (HTTP route, internal
 * route, job worker) register spawned CLI subprocesses here so a cancel from
 * any other request or the worker can SIGTERM them. This only reaches processes
 * spawned by this OS process.
 */
export const sharedCliProcessRegistry = new LocalCliProcessRegistry();
