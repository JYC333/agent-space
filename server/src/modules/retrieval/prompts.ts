import { randomUUID } from "node:crypto";
import type {
  RetrievalPromptTask,
  SpaceRetrievalPromptUpdate,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { Queryable } from "../routeUtils/common";
import {
  DEFAULT_QUERY_REWRITE_SYSTEM_PROMPT,
  DEFAULT_QUERY_REWRITE_USER_TEMPLATE,
} from "./queryRewriteProvider/prompt";

export interface SpaceRetrievalPromptOut {
  space_id: string;
  task: RetrievalPromptTask;
  system_prompt: string;
  user_template: string;
  default_system_prompt: string;
  default_user_template: string;
  created_at: string;
  updated_at: string;
}

export interface ResolvedRetrievalPrompt {
  task: RetrievalPromptTask;
  systemPrompt: string;
  userTemplate: string;
}

interface SpaceRetrievalPromptRow {
  space_id: string;
  task: RetrievalPromptTask;
  system_prompt: string;
  user_template: string;
  created_at: Date | string;
  updated_at: Date | string;
}

export function defaultPromptFor(task: RetrievalPromptTask): {
  systemPrompt: string;
  userTemplate: string;
} {
  if (task === "query_rewrite") {
    return {
      systemPrompt: DEFAULT_QUERY_REWRITE_SYSTEM_PROMPT,
      userTemplate: DEFAULT_QUERY_REWRITE_USER_TEMPLATE,
    };
  }
  return assertNever(task);
}

export async function readSpaceRetrievalPrompt(
  db: Queryable,
  spaceId: string,
  task: RetrievalPromptTask,
): Promise<ResolvedRetrievalPrompt> {
  const row = await selectPromptRow(db, spaceId, task);
  const defaults = defaultPromptFor(task);
  return {
    task,
    systemPrompt: row?.system_prompt ?? defaults.systemPrompt,
    userTemplate: row?.user_template ?? defaults.userTemplate,
  };
}

export async function getOrCreateSpaceRetrievalPrompt(
  db: Queryable,
  spaceId: string,
  task: RetrievalPromptTask,
): Promise<SpaceRetrievalPromptOut> {
  const defaults = defaultPromptFor(task);
  await db.query(
    `INSERT INTO space_retrieval_prompts (
        id, space_id, task, system_prompt, user_template, created_at, updated_at
      )
      VALUES ($1, $2, $3, $4, $5, now(), now())
      ON CONFLICT (space_id, task) DO NOTHING`,
    [randomUUID(), spaceId, task, defaults.systemPrompt, defaults.userTemplate],
  );
  const row = await selectPromptRow(db, spaceId, task);
  if (!row) throw new Error("space retrieval prompt row was not created");
  return outFromRow(row);
}

export async function updateSpaceRetrievalPrompt(
  db: Queryable,
  spaceId: string,
  task: RetrievalPromptTask,
  patch: SpaceRetrievalPromptUpdate,
): Promise<SpaceRetrievalPromptOut> {
  await getOrCreateSpaceRetrievalPrompt(db, spaceId, task);
  const current = await selectPromptRow(db, spaceId, task);
  if (!current) throw new Error("space retrieval prompt row was not found");
  const nextSystem = patch.system_prompt ?? current.system_prompt;
  const nextUser = patch.user_template ?? current.user_template;
  const updated = await db.query<SpaceRetrievalPromptRow>(
    `UPDATE space_retrieval_prompts
        SET system_prompt = $3,
            user_template = $4,
            updated_at = now()
      WHERE space_id = $1 AND task = $2
      RETURNING space_id, task, system_prompt, user_template, created_at, updated_at`,
    [spaceId, task, nextSystem, nextUser],
  );
  return outFromRow(updated.rows[0]!);
}

async function selectPromptRow(
  db: Queryable,
  spaceId: string,
  task: RetrievalPromptTask,
): Promise<SpaceRetrievalPromptRow | null> {
  const result = await db.query<SpaceRetrievalPromptRow>(
    `SELECT space_id, task, system_prompt, user_template, created_at, updated_at
       FROM space_retrieval_prompts
      WHERE space_id = $1 AND task = $2
      LIMIT 1`,
    [spaceId, task],
  );
  return result.rows[0] ?? null;
}

function outFromRow(row: SpaceRetrievalPromptRow): SpaceRetrievalPromptOut {
  const defaults = defaultPromptFor(row.task);
  return {
    space_id: row.space_id,
    task: row.task,
    system_prompt: row.system_prompt,
    user_template: row.user_template,
    default_system_prompt: defaults.systemPrompt,
    default_user_template: defaults.userTemplate,
    created_at: asIso(row.created_at),
    updated_at: asIso(row.updated_at),
  };
}

function asIso(value: Date | string): string {
  if (value instanceof Date) return value.toISOString();
  return new Date(value).toISOString();
}

function assertNever(value: never): never {
  throw new Error(`Unsupported retrieval prompt task: ${String(value)}`);
}
