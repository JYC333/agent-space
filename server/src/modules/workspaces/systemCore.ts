/**
 * System-core workspace registration.
 *
 * On server startup (when ENABLE_SYSTEM_EVOLUTION=true), validates that the
 * agent-space repo clone exists, then registers it as a system_core workspace
 * in the owner's personal space. Idempotent — safe to call on every startup.
 */

import { execFile } from "node:child_process";
import { stat } from "node:fs/promises";
import { promisify } from "node:util";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import type { ServerConfig } from "../../config";
import { getDbPool, type Pool } from "../../db/pool";
import { DeployerSocketClient } from "../deployment/client";

const execFileAsync = promisify(execFile);

export const SYSTEM_CORE_WORKSPACE_ID = "system-core-workspace";

interface SystemCoreDb {
  query<Row = Record<string, unknown>>(
    sql: string,
    params?: readonly unknown[],
  ): Promise<{ rows: Row[] }>;
}

interface Logger {
  info: (msg: string) => void;
  warn: (msg: string) => void;
}

async function isGitRepo(path: string): Promise<boolean> {
  try {
    await execFileAsync("git", ["rev-parse", "--git-dir"], { cwd: path, timeout: 10_000 });
    return true;
  } catch {
    const gitDir = await stat(join(path, ".git")).catch(() => null);
    return Boolean(gitDir?.isDirectory() || gitDir?.isFile());
  }
}

async function findPersonalSpaceId(pool: Pool, userId: string): Promise<string | null> {
  const res = await pool.query<{ space_id: string }>(
    `SELECT m.space_id
       FROM space_memberships m
       JOIN spaces s ON s.id = m.space_id
      WHERE m.user_id = $1 AND m.status = 'active' AND s.type = 'personal'
      ORDER BY m.created_at ASC, m.id ASC
      LIMIT 1`,
    [userId],
  );
  return res.rows[0]?.space_id ?? null;
}

async function ensurePersonalSpace(pool: Pool, userId: string, displayName: string): Promise<string> {
  const existing = await findPersonalSpaceId(pool, userId);
  if (existing) return existing;
  const spaceId = randomUUID();
  await pool.query(
    `INSERT INTO spaces (id, name, type, created_by_user_id, created_at, updated_at)
     VALUES ($1, $2, 'personal', $3, now(), now())
     ON CONFLICT DO NOTHING`,
    [spaceId, `${displayName}'s Personal Space`, userId],
  );
  await pool.query(
    `INSERT INTO space_memberships (id, space_id, user_id, role, status, created_at, updated_at)
     VALUES ($1, $2, $3, 'owner', 'active', now(), now())
     ON CONFLICT DO NOTHING`,
    [randomUUID(), spaceId, userId],
  );
  return spaceId;
}

export async function upsertSystemCoreWorkspace(
  db: SystemCoreDb,
  input: {
    spaceId: string;
    userId: string;
    workspaceDir: string;
    baseBranch: string;
  },
): Promise<"inserted" | "updated"> {
  const existing = await db.query<{ id: string }>(
    `SELECT id FROM workspaces WHERE id = $1 AND space_id = $2 LIMIT 1`,
    [SYSTEM_CORE_WORKSPACE_ID, input.spaceId],
  );

  if (existing.rows[0]) {
    await db.query(
      `UPDATE workspaces
          SET root_path = $1,
              default_branch = $2,
              workspace_type = 'system_core',
              kind = 'repo',
              status = 'active',
              protected = true,
              system_managed = true,
              registered_from = COALESCE(registered_from, 'auto'),
              created_by_user_id = COALESCE(created_by_user_id, $3),
              owner_user_id = COALESCE(owner_user_id, $3),
              updated_at = now()
        WHERE id = $4 AND space_id = $5`,
      [
        input.workspaceDir,
        input.baseBranch,
        input.userId,
        SYSTEM_CORE_WORKSPACE_ID,
        input.spaceId,
      ],
    );
    return "updated";
  }

  await db.query(
    `INSERT INTO workspaces (
       id, space_id, created_by_user_id, owner_user_id, name, description,
       workspace_type, kind, root_path, default_branch,
       status, visibility, protected, system_managed, registered_from,
       created_at, updated_at
     ) VALUES (
       $1, $2, $3, $3, $4, $5,
       'system_core', 'repo', $6, $7,
       'active', 'private', true, true, 'auto',
       now(), now()
     )`,
    [
      SYSTEM_CORE_WORKSPACE_ID,
      input.spaceId,
      input.userId,
      "agent-space",
      "System core: agent-space self-evolution workspace",
      input.workspaceDir,
      input.baseBranch,
    ],
  );
  return "inserted";
}

/**
 * Register the agent-space repo clone as a system_core workspace in the owner's
 * personal space. Errors are logged, never thrown — startup must not fail due to
 * system evolution misconfiguration.
 */
export async function registerSystemCoreWorkspace(
  config: ServerConfig,
  log: Logger,
): Promise<void> {
  if (!config.enableSystemEvolution) return;
  if (!config.databaseUrl) {
    log.warn("[system_core] no database URL configured — skipping");
    return;
  }

  const ownerEmail = config.systemCoreOwnerEmail ?? config.instanceAdminEmail;
  if (!ownerEmail) {
    log.warn(
      "[system_core] ENABLE_SYSTEM_EVOLUTION=true but neither SYSTEM_CORE_OWNER_EMAIL nor INSTANCE_ADMIN_EMAIL is set — skipping",
    );
    return;
  }

  try {
    const pool = getDbPool(config.databaseUrl);

    const userRes = await pool.query<{ id: string; display_name: string }>(
      `SELECT id, display_name FROM users WHERE LOWER(email) = $1 LIMIT 1`,
      [ownerEmail],
    );
    const user = userRes.rows[0];
    if (!user) {
      log.warn(
        `[system_core] owner email '${ownerEmail}' not found — complete login first, then restart`,
      );
      return;
    }

    const spaceId = await ensurePersonalSpace(pool, user.id, user.display_name);
    const workspaceDir = resolve(config.workspaceRoot, spaceId, "agent-space");

    if (!(await isGitRepo(workspaceDir))) {
      log.info(`[system_core] repo not found at ${workspaceDir} — requesting deployer init`);
      const deployer = new DeployerSocketClient(config);
      const result = await deployer.submit("init_agent_space_worktree", {
        WORKSPACE_DIR: workspaceDir,
      });
      if (result.status !== "succeeded") {
        log.warn(`[system_core] deployer init failed: ${result.error ?? result.status} — skipping`);
        return;
      }
    }

    if (!(await isGitRepo(workspaceDir))) {
      log.warn(`[system_core] ${workspaceDir} is still not a valid git repo after init — skipping`);
      return;
    }

    const action = await upsertSystemCoreWorkspace(pool, {
      spaceId,
      userId: user.id,
      workspaceDir,
      baseBranch: config.systemCoreBaseBranch,
    });
    log.info(
      action === "inserted"
        ? `[system_core] registered system_core workspace at ${workspaceDir} in space ${spaceId}`
        : `[system_core] workspace already registered — refreshed active root_path to ${workspaceDir}`,
    );
  } catch (err) {
    log.warn(
      `[system_core] registration failed: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}
