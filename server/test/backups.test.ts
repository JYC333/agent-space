import { describe, expect, it, vi } from "vitest";
import { chmod, mkdir, mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { BackupPolicyError, enforceBackupPolicy } from "../src/modules/backups/guard";
import { BackupService } from "../src/modules/backups/service";
import { loadConfig } from "../src/config";

describe("backup policy guard", () => {
  it("fails fast in prod when backups are disabled and unacknowledged", () => {
    const config = loadConfig({
      AGENT_SPACE_ENV: "prod",
      BACKUP_ENABLED: "false",
      BACKUP_ACCEPT_NO_BACKUP: "false",
    });
    expect(() => enforceBackupPolicy(config, { warn: vi.fn() })).toThrow(BackupPolicyError);
  });

  it("allows prod startup when BACKUP_ACCEPT_NO_BACKUP=true and logs a warning", () => {
    const warn = vi.fn();
    const config = loadConfig({
      AGENT_SPACE_ENV: "prod",
      BACKUP_ENABLED: "false",
      BACKUP_ACCEPT_NO_BACKUP: "true",
    });
    expect(() => enforceBackupPolicy(config, { warn })).not.toThrow();
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("BACKUP DISABLED in prod"));
  });

  it("logs a warning when non-prod backups are disabled", () => {
    const warn = vi.fn();
    const config = loadConfig({
      AGENT_SPACE_ENV: "dev",
      BACKUP_ENABLED: "false",
    });
    enforceBackupPolicy(config, { warn });
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("Automatic backups are DISABLED"));
  });
});

describe("BackupService lock handling", () => {
  it("removes stale lock files before pruning", async () => {
    const root = await mkdtemp(join(tmpdir(), "aspace-backup-lock-"));
    try {
      const home = join(root, "home");
      const backupRoot = join(root, "backups");
      await mkdir(home, { recursive: true });
      await mkdir(backupRoot, { recursive: true });
      const lockPath = join(backupRoot, ".backup.lock");
      await writeFile(lockPath, "acquired_at=2020-01-01T00:00:00.000Z\n");

      const service = new BackupService(
        loadConfig({
          AGENT_SPACE_HOME: home,
          BACKUP_ROOT: backupRoot,
          BACKUP_RETENTION_COUNT: "2",
        }),
      );

      await expect(service.pruneOldBackups()).resolves.toEqual([]);
      await expect(pathExists(lockPath)).resolves.toBe(false);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("tightens existing backup root permissions before pruning", async () => {
    const root = await mkdtemp(join(tmpdir(), "aspace-backup-mode-"));
    try {
      const home = join(root, "home");
      const backupRoot = join(root, "backups");
      await mkdir(home, { recursive: true });
      await mkdir(backupRoot, { recursive: true, mode: 0o777 });
      await chmod(backupRoot, 0o777);

      const service = new BackupService(
        loadConfig({
          AGENT_SPACE_HOME: home,
          BACKUP_ROOT: backupRoot,
          BACKUP_RETENTION_COUNT: "2",
        }),
      );

      await service.pruneOldBackups();
      const mode = (await stat(backupRoot)).mode & 0o777;
      expect(mode).toBe(0o700);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("skips prune when another live process owns the lock", async () => {
    const root = await mkdtemp(join(tmpdir(), "aspace-backup-lock-"));
    try {
      const home = join(root, "home");
      const backupRoot = join(root, "backups");
      await mkdir(home, { recursive: true });
      await mkdir(backupRoot, { recursive: true });
      const lockPath = join(backupRoot, ".backup.lock");
      await writeFile(lockPath, `pid=${process.pid} acquired_at=${new Date().toISOString()}\n`);

      const service = new BackupService(
        loadConfig({
          AGENT_SPACE_HOME: home,
          BACKUP_ROOT: backupRoot,
          BACKUP_RETENTION_COUNT: "2",
        }),
      );

      await expect(service.pruneOldBackups()).resolves.toEqual([]);
      await expect(pathExists(lockPath)).resolves.toBe(true);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

async function pathExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}
