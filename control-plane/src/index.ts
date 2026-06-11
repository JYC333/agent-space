/**
 * Control-plane entrypoint.
 *
 * Loads + validates config (fail-fast), builds the server, and listens. Python
 * remains the sole authority; this process only serves TS-owned control-plane
 * routes and proxies everything else under `/api/v1/*` to the legacy Python
 * backend via the temporary fallback proxy.
 */

import { buildServer } from "./server";
import {
  collectConfigDiagnostics,
  ConfigError,
  createConfigSnapshot,
  describeConfig,
  loadConfig,
} from "./config";

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
    throw err;
  }

  const app = buildServer(config);
  for (const diagnostic of collectConfigDiagnostics(process.env)) {
    app.log.warn(`[control-plane] config [${diagnostic.code}]: ${diagnostic.message}`);
  }
  const snapshot = createConfigSnapshot(config);
  app.log.info(
    `[control-plane] starting (${describeConfig(config)}) ` +
      `config_schema=${snapshot.schema_version} config_hash=${snapshot.content_hash.slice(0, 12)}`,
  );

  const shutdown = async (signal: string): Promise<void> => {
    app.log.info(`[control-plane] received ${signal}, shutting down`);
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
}

void main();
