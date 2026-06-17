/**
 * Control-plane entrypoint.
 *
 * Loads + validates config (fail-fast), builds the server, and listens. This
 * process serves TS-owned control-plane routes and proxies unowned `/api/v1/*`
 * paths to the Python backend via the temporary fallback proxy. When the database
 * is configured, it also runs the unified TS jobs worker and in-process schedulers.
 */

import { buildServer } from "./server";
import {
  collectConfigDiagnostics,
  ConfigError,
  createConfigSnapshot,
  describeConfig,
  loadConfig,
} from "./config";
import { startBackgroundServices } from "./modules/jobs/backgroundServices";
import { enforceBackupPolicy, BackupPolicyError } from "./modules/backups/guard";

async function main(): Promise<void> {
  let config;
  try {
    config = loadConfig(process.env);
  } catch (err) {
    if (err instanceof ConfigError) {
      // Print to stderr without a stack trace or secrets, then exit non-zero.
      process.stderr.write(
        `[control-plane] invalid configuration [${err.code}]: ${err.message}\n`,
      );
      process.exit(1);
    }
    if (err instanceof BackupPolicyError) {
      process.stderr.write(`[control-plane] backup policy: ${err.message}\n`);
      process.exit(1);
    }
    throw err;
  }

  try {
    enforceBackupPolicy(config);
  } catch (err) {
    if (err instanceof BackupPolicyError) {
      process.stderr.write(`[control-plane] backup policy: ${err.message}\n`);
      process.exit(1);
    }
    throw err;
  }

  const app = buildServer(config);
  for (const diagnostic of collectConfigDiagnostics(process.env, config)) {
    app.log.warn(`[control-plane] config [${diagnostic.code}]: ${diagnostic.message}`);
  }
  const snapshot = createConfigSnapshot(config);
  app.log.info(
    `[control-plane] starting (${describeConfig(config)}) ` +
      `config_schema=${snapshot.schema_version} config_hash=${snapshot.content_hash.slice(0, 12)}`,
  );

  let background: ReturnType<typeof startBackgroundServices> | null = null;

  const shutdown = async (signal: string): Promise<void> => {
    app.log.info(`[control-plane] received ${signal}, shutting down`);
    if (background) {
      await background.worker?.stop();
      await background.scheduler.stop();
    }
    await app.close();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));

  try {
    await app.listen({ host: config.host, port: config.port });
  } catch (err) {
    app.log.error(err, "[control-plane] failed to start");
    process.exit(1);
  }

  background = startBackgroundServices(config, {
    info: (message) => app.log.info(message),
    warn: (message) => app.log.warn(message),
    error: (message) => app.log.error(message),
  });
  if (background.worker) {
    app.log.info(`[control-plane] jobs worker active (${background.worker.worker_id})`);
  }
}

void main();
