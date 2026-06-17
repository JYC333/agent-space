import { randomUUID } from "node:crypto";
import { mkdir, readdir, readFile, stat } from "node:fs/promises";
import { isAbsolute, join, relative, resolve } from "node:path";
import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import { loadActionRegistry } from "../policy/actionRegistry";
import { enforce } from "../policy/service";
import { HttpError, type Queryable, type SpaceUserIdentity } from "../routeUtils/common";
import {
  diffTouchesSecretLikePath,
  looksSecretLikePath,
  redactSecretLikeDiff,
  validatePath,
} from "./pathPolicy";
import { isGitRepo, runGit } from "./git";

const MAX_DEPTH = 5;
const MAX_FILES = 500;
const MAX_FILE_BYTES = 1_048_576;
const MAX_DIFF_BYTES = 512 * 1024;

const IGNORE_DIRS = new Set([
  ".git",
  "__pycache__",
  "node_modules",
  ".venv",
  "venv",
  ".tox",
  "dist",
  "build",
  ".next",
  ".nuxt",
  "coverage",
]);
const SHOW_HIDDEN = new Set([
  ".gitignore",
  ".env.example",
  ".env.dev.example",
  ".env.test.example",
  ".env.prod.example",
  ".claude",
  ".editorconfig",
]);

export interface WorkspaceRow {
  id: string;
  space_id: string;
  created_by_user_id: string | null;
  name: string;
  slug: string | null;
  description: string | null;
  workspace_type: string;
  kind: string;
  repo_url: string | null;
  root_path: string | null;
  default_branch: string | null;
  visibility: string;
  status: string;
  protected: boolean;
  system_managed: boolean;
  registered_from: string | null;
  metadata_json: Record<string, unknown> | null;
  allow_external_root: boolean;
  created_at: unknown;
  updated_at: unknown;
}

export interface WorkspaceOut {
  id: string;
  owner_space_id: string;
  created_by_user_id: string;
  name: string;
  slug: string | null;
  description: string | null;
  workspace_type: string;
  kind: string;
  repo_url: string | null;
  root_path: string | null;
  default_branch: string | null;
  visibility: string;
  status: string;
  protected: boolean;
  system_managed: boolean;
  registered_from: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface WorkspacePage {
  items: WorkspaceOut[];
  total: number;
  limit: number;
  offset: number;
}

export interface FileNode {
  name: string;
  path: string;
  type: "file" | "dir";
  size?: number;
  children?: FileNode[];
}

export interface FileContent {
  path: string;
  content: string;
  size: number;
  line_count: number;
}

export interface GitStatus {
  is_repo: boolean;
  branch: string | null;
  files: Array<{ path: string; status: string }>;
}

export class PgWorkspaceRepository {
  constructor(
    private readonly db: Queryable,
    private readonly config: ServerConfig,
  ) {}

  static fromConfig(config: ServerConfig): PgWorkspaceRepository {
    if (!config.databaseUrl) {
      throw new HttpError(502, "Workspace repository requires SERVER_DATABASE_URL");
    }
    return new PgWorkspaceRepository(getDbPool(config.databaseUrl), config);
  }

  async list(identity: SpaceUserIdentity, filters: { status: string | null; limit: number; offset: number }): Promise<WorkspacePage> {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    if (filters.status) {
      params.push(filters.status);
      clauses.push(`status = $${params.length}`);
    }
    const where = `WHERE ${clauses.join(" AND ")}`;
    const total = await this.db.query<{ total: string | number }>(
      `SELECT count(id)::text AS total FROM workspaces ${where}`,
      params,
    );
    const rows = await this.db.query<WorkspaceRow>(
      `${workspaceSelect()} ${where}
        ORDER BY updated_at DESC
        LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return {
      items: rows.rows.map(workspaceToOut),
      total: numberValue(total.rows[0]?.total) ?? 0,
      limit: filters.limit,
      offset: filters.offset,
    };
  }

  async create(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<WorkspaceOut> {
    const name = requiredText(body.name, "name");
    const workspaceType = optionalText(body.workspace_type) ?? "project";
    if (workspaceType === "system_core") {
      throw new HttpError(
        400,
        "system_core workspaces cannot be created through the UI; set ENABLE_SYSTEM_EVOLUTION=true to register one",
      );
    }
    const duplicate = await this.db.query<{ id: string }>(
      `SELECT id FROM workspaces
        WHERE space_id = $1 AND name = $2 AND status = 'active'
        LIMIT 1`,
      [identity.spaceId, name],
    );
    if (duplicate.rows[0]) {
      throw new HttpError(409, `A workspace named '${name}' already exists`);
    }

    const id = randomUUID();
    const rootPath = optionalText(body.root_path) ?? await this.createDefaultWorkspaceDir(identity.spaceId, name);
    const now = new Date().toISOString();
    const row = await this.db.query<WorkspaceRow>(
      `INSERT INTO workspaces (
         id, space_id, created_by_user_id, name, description, workspace_type,
         kind, repo_url, root_path, default_branch, metadata_json, status,
         visibility, protected, system_managed, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8, $9, $10, $11::jsonb, 'active',
         'private', false, false, $12, $12
       )
       RETURNING ${workspaceColumns()}`,
      [
        id,
        identity.spaceId,
        identity.userId,
        name,
        optionalText(body.description),
        workspaceType,
        optionalText(body.kind) ?? "project",
        optionalText(body.repo_url),
        rootPath,
        optionalText(body.default_branch),
        JSON.stringify(optionalObject(body.metadata_json)),
        now,
      ],
    );
    return workspaceToOut(row.rows[0]!);
  }

  async scan(identity: SpaceUserIdentity): Promise<{ created: WorkspaceOut[]; marked_stale: string[] }> {
    const existing = await this.db.query<WorkspaceRow>(
      `${workspaceSelect()} WHERE space_id = $1 AND status = 'active'`,
      [identity.spaceId],
    );
    const knownPaths = new Set<string>();
    const staleNames: string[] = [];
    for (const row of existing.rows) {
      const root = workspaceAbsoluteRoot(row, this.config.workspaceRoot);
      const info = await stat(root).catch(() => null);
      if (info?.isDirectory()) {
        knownPaths.add(resolve(root));
      } else {
        staleNames.push(row.name);
      }
    }
    if (staleNames.length > 0) {
      await this.db.query(
        `UPDATE workspaces
            SET status = 'stale', updated_at = $3
          WHERE space_id = $1 AND status = 'active' AND name = ANY($2::text[])`,
        [identity.spaceId, staleNames, new Date().toISOString()],
      );
    }

    const spaceRoot = resolve(this.config.workspaceRoot, identity.spaceId);
    const entries = await readdir(spaceRoot, { withFileTypes: true }).catch(() => []);
    const created: WorkspaceOut[] = [];
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const path = resolve(spaceRoot, entry.name);
      if (knownPaths.has(path)) continue;
      const exists = await this.db.query<{ id: string }>(
        `SELECT id FROM workspaces
          WHERE space_id = $1 AND root_path = $2 AND status = 'active'
          LIMIT 1`,
        [identity.spaceId, path],
      );
      if (exists.rows[0]) continue;
      const now = new Date().toISOString();
      const row = await this.db.query<WorkspaceRow>(
        `INSERT INTO workspaces (
           id, space_id, created_by_user_id, name, kind, workspace_type, root_path,
           status, visibility, protected, system_managed, created_at, updated_at
         ) VALUES (
           $1, $2, $3, $4, 'project', 'project', $5,
           'active', 'private', false, false, $6, $6
         )
         RETURNING ${workspaceColumns()}`,
        [randomUUID(), identity.spaceId, identity.userId, entry.name, path, now],
      );
      created.push(workspaceToOut(row.rows[0]!));
    }
    return { created, marked_stale: staleNames };
  }

  async get(identity: SpaceUserIdentity, workspaceId: string): Promise<WorkspaceOut | null> {
    const row = await this.getWorkspace(identity.spaceId, workspaceId, false);
    return row ? workspaceToOut(row) : null;
  }

  async update(identity: SpaceUserIdentity, workspaceId: string, body: Record<string, unknown>): Promise<WorkspaceOut | null> {
    const existing = await this.getWorkspace(identity.spaceId, workspaceId, false);
    if (!existing) return null;
    const allowed = [
      "name",
      "description",
      "kind",
      "repo_url",
      "root_path",
      "default_branch",
      "status",
      "visibility",
      "metadata_json",
    ];
    const sets: string[] = [];
    const params: unknown[] = [workspaceId, identity.spaceId];
    for (const key of allowed) {
      if (!(key in body)) continue;
      params.push(key === "metadata_json" ? JSON.stringify(optionalObject(body[key])) : body[key] ?? null);
      sets.push(`${key} = $${params.length}${key === "metadata_json" ? "::jsonb" : ""}`);
    }
    if (sets.length === 0) return workspaceToOut(existing);
    params.push(new Date().toISOString());
    const row = await this.db.query<WorkspaceRow>(
      `UPDATE workspaces
          SET ${sets.join(", ")}, updated_at = $${params.length}
        WHERE id = $1 AND space_id = $2
        RETURNING ${workspaceColumns()}`,
      params,
    );
    return row.rows[0] ? workspaceToOut(row.rows[0]) : null;
  }

  async archive(identity: SpaceUserIdentity, workspaceId: string): Promise<boolean> {
    const result = await this.db.query(
      `UPDATE workspaces
          SET status = 'archived', updated_at = $3
        WHERE id = $1 AND space_id = $2`,
      [workspaceId, identity.spaceId, new Date().toISOString()],
    );
    return (result.rowCount ?? 0) > 0;
  }

  async listConsoleWorkspaces(identity: SpaceUserIdentity): Promise<{ items: Array<Record<string, unknown>> }> {
    const rows = await this.db.query<WorkspaceRow>(
      `${workspaceSelect()}
        WHERE space_id = $1 AND status = 'active'
        ORDER BY updated_at DESC`,
      [identity.spaceId],
    );
    return {
      items: rows.rows.map((w) => ({
        id: w.id,
        name: w.name,
        root_path: w.root_path,
        kind: w.kind,
        description: w.description,
      })),
    };
  }

  async getTree(identity: SpaceUserIdentity, workspaceId: string): Promise<FileNode> {
    const ws = await this.requireActiveWorkspace(identity.spaceId, workspaceId);
    await this.enforceWorkspaceRead(ws, identity.userId, "tree");
    const root = workspaceAbsoluteRoot(ws, this.config.workspaceRoot);
    const info = await stat(root).catch(() => null);
    if (!info?.isDirectory()) throw new HttpError(404, "Workspace directory not found on disk");
    return buildTree(root, root, 0, { count: 0 });
  }

  async getFile(identity: SpaceUserIdentity, workspaceId: string, requestedPath: string): Promise<FileContent> {
    const ws = await this.requireActiveWorkspace(identity.spaceId, workspaceId);
    const root = workspaceAbsoluteRoot(ws, this.config.workspaceRoot);
    const safe = validatePath({
      path: resolve(root, requestedPath),
      allowedRoot: root,
      mode: "read",
      workspaceType: ws.workspace_type,
    });
    const info = await stat(safe).catch(() => null);
    if (!info) throw new HttpError(404, "File not found");
    if (!info.isFile()) throw new HttpError(400, "Path is a directory");
    const relPath = relative(root, safe).split("\\").join("/");
    await this.enforceWorkspaceRead(ws, identity.userId, "file", relPath);
    if (info.size > MAX_FILE_BYTES) {
      throw new HttpError(413, "File too large to display (max 1 MiB)");
    }
    const content = await readFile(safe, "utf8");
    return {
      path: requestedPath,
      content,
      size: info.size,
      line_count: content.split(/\n/).length,
    };
  }

  async getGitStatus(identity: SpaceUserIdentity, workspaceId: string): Promise<GitStatus> {
    const ws = await this.requireActiveWorkspace(identity.spaceId, workspaceId);
    await this.enforceWorkspaceRead(ws, identity.userId, "git_status");
    const root = workspaceAbsoluteRoot(ws, this.config.workspaceRoot);
    if (!await isGitRepo(root)) return { is_repo: false, branch: null, files: [] };
    const branch = (await runGit(["rev-parse", "--abbrev-ref", "HEAD"], root, 10_000)).stdout.trim() || null;
    const raw = await runGit(["status", "--porcelain"], root, 10_000);
    return { is_repo: true, branch, files: parsePorcelain(raw.stdout) };
  }

  async getGitDiff(
    identity: SpaceUserIdentity,
    workspaceId: string,
    requestedPath: string | null,
  ): Promise<{ diff: string; path: string | null; truncated: boolean; redacted: boolean }> {
    const ws = await this.requireActiveWorkspace(identity.spaceId, workspaceId);
    const root = workspaceAbsoluteRoot(ws, this.config.workspaceRoot);
    let relPath: string | null = null;
    if (requestedPath) {
      const safe = validatePath({
        path: resolve(root, requestedPath),
        allowedRoot: root,
        mode: "read",
        workspaceType: ws.workspace_type,
      });
      relPath = relative(root, safe).split("\\").join("/");
    }
    await this.enforceWorkspaceRead(ws, identity.userId, "git_diff", relPath);
    const args = requestedPath ? ["diff", "HEAD", "--", relPath ?? requestedPath] : ["diff", "HEAD", "--"];
    let diff = (await runGit(args, root, 15_000)).stdout;
    if (!diff) {
      diff = (await runGit(requestedPath ? ["diff", "--", relPath ?? requestedPath] : ["diff", "--"], root, 15_000)).stdout;
    }
    if (diffTouchesSecretLikePath(diff)) {
      throw new HttpError(403, "Diff includes blocked path");
    }
    const redacted = redactSecretLikeDiff(diff);
    diff = redacted.diff;
    const encoded = Buffer.from(diff, "utf8");
    const truncated = encoded.length > MAX_DIFF_BYTES;
    if (truncated) diff = encoded.subarray(0, MAX_DIFF_BYTES).toString("utf8");
    return { diff, path: requestedPath, truncated, redacted: redacted.redacted };
  }

  async getWorkspace(spaceId: string, workspaceId: string, activeOnly = true): Promise<WorkspaceRow | null> {
    const result = await this.db.query<WorkspaceRow>(
      `${workspaceSelect()}
        WHERE id = $1 AND space_id = $2 ${activeOnly ? "AND status = 'active'" : ""}
        LIMIT 1`,
      [workspaceId, spaceId],
    );
    return result.rows[0] ?? null;
  }

  private async requireActiveWorkspace(spaceId: string, workspaceId: string): Promise<WorkspaceRow> {
    const ws = await this.getWorkspace(spaceId, workspaceId, true);
    if (!ws) throw new HttpError(404, "Workspace not found");
    return ws;
  }

  private async createDefaultWorkspaceDir(spaceId: string, name: string): Promise<string> {
    const spaceRoot = resolve(this.config.workspaceRoot, spaceId);
    await mkdir(spaceRoot, { recursive: true });
    const base = folderName(name);
    let candidate = resolve(spaceRoot, base);
    for (let i = 1; await stat(candidate).catch(() => null); i += 1) {
      candidate = resolve(spaceRoot, `${base}-${i}`);
    }
    await mkdir(candidate, { recursive: true });
    return candidate;
  }

  private async enforceWorkspaceRead(
    ws: WorkspaceRow,
    userId: string,
    readKind: string,
    relativePath: string | null = null,
  ): Promise<void> {
    const auditReasons = workspaceReadAuditReasons(ws, readKind, relativePath);
    const registry = await loadActionRegistry();
    const result = await enforce(this.config, registry, {
      action: "workspace.read",
      actor_type: "user",
      actor_id: userId,
      space_id: ws.space_id,
      resource_type: "workspace",
      resource_id: ws.id,
      resource_space_id: ws.space_id,
      context: {
        read_kind: readKind,
        relative_path: relativePath,
        workspace_type: ws.workspace_type,
        workspace_visibility: ws.visibility,
        workspace_protected: Boolean(ws.protected),
        workspace_system_managed: Boolean(ws.system_managed),
        workspace_external_root: Boolean(ws.allow_external_root),
        audit_reasons: auditReasons,
      },
      metadata_json: {
        read_kind: readKind,
        relative_path: relativePath,
        workspace_type: ws.workspace_type,
        workspace_visibility: ws.visibility,
        audit_reasons: auditReasons,
      },
      force_record: auditReasons.length > 0,
    });
    if (result.status === "allow") return;
    if (result.status === "error") {
      throw new HttpError(500, result.message ?? "Workspace read policy audit failed");
    }
    throw new HttpError(403, result.message ?? "Workspace read denied by policy");
  }
}

export function workspaceAbsoluteRoot(
  ws: Pick<WorkspaceRow, "id" | "root_path">,
  workspaceRoot: string,
): string {
  if (ws.root_path) {
    return isAbsolute(ws.root_path)
      ? resolve(ws.root_path)
      : resolve(workspaceRoot, ws.root_path);
  }
  return resolve(workspaceRoot, ws.id);
}

export function workspaceToOut(row: WorkspaceRow): WorkspaceOut {
  return {
    id: row.id,
    owner_space_id: row.space_id,
    created_by_user_id: row.created_by_user_id ?? "",
    name: row.name,
    slug: row.slug,
    description: row.description,
    workspace_type: row.workspace_type,
    kind: row.kind,
    repo_url: row.repo_url,
    root_path: row.root_path,
    default_branch: row.default_branch,
    visibility: row.visibility,
    status: row.status,
    protected: Boolean(row.protected),
    system_managed: Boolean(row.system_managed),
    registered_from: row.registered_from,
    metadata_json: row.metadata_json,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

function workspaceColumns(): string {
  return `id, space_id, created_by_user_id, name, slug, description, workspace_type,
          kind, repo_url, root_path, default_branch, visibility, status,
          protected, system_managed, registered_from, metadata_json,
          allow_external_root, created_at, updated_at`;
}

function workspaceSelect(): string {
  return `SELECT ${workspaceColumns()} FROM workspaces`;
}

async function buildTree(root: string, nodePath: string, depth: number, counter: { count: number }): Promise<FileNode> {
  const info = await stat(nodePath);
  const rel = nodePath === root ? "." : relative(root, nodePath).split("\\").join("/");
  const node: FileNode = {
    name: nodePath === root ? root.split(/[\\/]/).pop() || root : nodePath.split(/[\\/]/).pop() || nodePath,
    path: rel,
    type: info.isDirectory() ? "dir" : "file",
  };
  if (info.isFile()) {
    node.size = info.size;
    return node;
  }
  if (!info.isDirectory() || depth >= MAX_DEPTH || counter.count >= MAX_FILES) {
    return node;
  }
  const entries = await readdir(nodePath, { withFileTypes: true }).catch(() => []);
  const children: FileNode[] = [];
  for (const entry of entries.sort((a, b) => Number(a.isFile()) - Number(b.isFile()) || a.name.localeCompare(b.name))) {
    if (entry.isDirectory() && IGNORE_DIRS.has(entry.name)) continue;
    if (entry.name.startsWith(".") && !SHOW_HIDDEN.has(entry.name)) continue;
    counter.count += 1;
    if (counter.count > MAX_FILES) break;
    children.push(await buildTree(root, join(nodePath, entry.name), depth + 1, counter));
  }
  node.children = children;
  return node;
}

function parsePorcelain(output: string): Array<{ path: string; status: string }> {
  const result: Array<{ path: string; status: string }> = [];
  for (const line of output.split(/\r?\n/)) {
    if (line.length < 3) continue;
    const xy = line.slice(0, 2);
    const path = line.slice(3).trim();
    let status = "modified";
    if (xy.includes("?")) status = "untracked";
    else if (xy.includes("R")) status = "renamed";
    else if (xy.includes("D")) status = "deleted";
    else if (xy.includes("A")) status = "added";
    result.push({ path, status });
  }
  return result;
}

function workspaceReadAuditReasons(
  ws: WorkspaceRow,
  readKind: string,
  relativePath: string | null,
): string[] {
  const reasons: string[] = [];
  if (ws.workspace_type === "system_core" || ws.system_managed) reasons.push("system_core");
  if (ws.allow_external_root) reasons.push("external_root");
  if (ws.protected || ws.visibility === "restricted") reasons.push("restricted_workspace");
  if (readKind === "git_diff" && relativePath === null) reasons.push("full_diff");
  if (looksSecretLikePath(relativePath)) reasons.push("secret_like_path");
  return reasons;
}

function folderName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "workspace";
}

function requiredText(value: unknown, field: string): string {
  const text = optionalText(value);
  if (!text) throw new HttpError(422, `${field} is required`);
  return text;
}

function optionalText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text || null;
}

function optionalObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function dateIso(value: unknown): string {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "string") return new Date(value).toISOString();
  return new Date(0).toISOString();
}
