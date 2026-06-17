import { randomUUID } from "node:crypto";
import type { Pool } from "../../db/pool";
import {
  HttpError,
  canReadByVisibility,
  countFromRow,
  dateIso,
  numberValue,
  optionalObject,
  optionalString,
  page,
  requiredString,
  toDbDate,
  withDbTransaction,
  type SpaceUserIdentity,
  type Queryable,
} from "../routeUtils/common";
import { PgRunRepository, type RunRecord } from "../runs/repository";
import { runToOut } from "../runs/runReadModel";

interface BoardRow {
  id: string;
  space_id: string;
  workspace_id: string | null;
  name: string;
  description: string | null;
  board_type: string;
  status: string;
  default_view: string | null;
  sort_order: number | null;
  metadata_json: unknown;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_at: unknown;
  updated_at: unknown;
  deleted_at: unknown;
}

interface BoardColumnRow {
  id: string;
  space_id: string;
  board_id: string;
  name: string;
  description: string | null;
  status_key: string;
  position: number;
  wip_limit: number | null;
  is_done_column: boolean;
  is_default_column: boolean;
  metadata_json: unknown;
  created_at: unknown;
  updated_at: unknown;
  deleted_at: unknown;
}

interface TaskRow {
  id: string;
  space_id: string;
  workspace_id: string | null;
  board_id: string | null;
  column_id: string | null;
  parent_task_id: string | null;
  title: string;
  description: string | null;
  task_type: string;
  status: string;
  priority: string;
  risk_level: string;
  visibility: string;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  assigned_user_id: string | null;
  assigned_agent_id: string | null;
  claimed_by_user_id: string | null;
  claimed_by_agent_id: string | null;
  source_activity_id: string | null;
  source_run_id: string | null;
  source_proposal_id: string | null;
  source_artifact_id: string | null;
  due_at: unknown;
  start_after: unknown;
  completed_at: unknown;
  cancelled_at: unknown;
  blocked_reason: string | null;
  max_runs: number | null;
  created_at: unknown;
  updated_at: unknown;
  deleted_at: unknown;
}

interface TaskRunListRow extends RunRecord {
  task_run_id: string;
  task_run_space_id: string;
  task_run_task_id: string;
  task_run_run_id: string;
  task_run_role: string;
  task_run_created_at: unknown;
}

interface TaskEvaluationRow {
  id: string;
  space_id: string;
  task_id: string;
  run_id: string | null;
  run_evaluation_id: string | null;
  evaluator_type: string;
  evaluator_user_id: string | null;
  evaluator_agent_id: string | null;
  score: number | null;
  confidence: number | null;
  summary: string | null;
  checklist_json: unknown;
  known_issues_json: unknown;
  evidence_artifact_ids: unknown;
  recommendation: string | null;
  created_at: unknown;
}

interface TaskArtifactRow {
  id: string;
  space_id: string;
  task_id: string;
  artifact_id: string;
  role: string;
  created_at: unknown;
  artifact_space_id: string;
  run_id: string | null;
  proposal_id: string | null;
  artifact_type: string;
  title: string;
  mime_type: string | null;
  visibility: string;
  artifact_created_at: unknown;
}

interface TaskProposalRow {
  id: string;
  space_id: string;
  task_id: string;
  proposal_id: string;
  role: string;
  created_at: unknown;
  proposal_space_id: string;
  proposal_type: string;
  status: string;
  title: string;
  visibility: string;
  proposal_created_at: unknown;
  preview: boolean;
  urgency: string;
  review_deadline: unknown;
  expires_at: unknown;
  created_by_run_id: string | null;
}

const BOARD_COLUMNS = `
  id, space_id, workspace_id, name, description, board_type, status,
  default_view, sort_order, metadata_json, created_by_user_id,
  created_by_agent_id, created_at, updated_at, deleted_at
`;

const BOARD_COLUMN_COLUMNS = `
  id, space_id, board_id, name, description, status_key, position,
  wip_limit, is_done_column, is_default_column, metadata_json,
  created_at, updated_at, deleted_at
`;

const TASK_COLUMNS = `
  id, space_id, workspace_id, board_id, column_id, parent_task_id,
  title, description, task_type, status, priority, risk_level, visibility,
  created_by_user_id, created_by_agent_id, assigned_user_id, assigned_agent_id,
  claimed_by_user_id, claimed_by_agent_id, source_activity_id, source_run_id,
  source_proposal_id, source_artifact_id, due_at, start_after, completed_at,
  cancelled_at, blocked_reason, max_runs, created_at, updated_at, deleted_at
`;

const DEFAULT_COLUMNS = [
  { name: "Inbox", status_key: "inbox", position: 0, isDone: false, isDefault: true },
  { name: "Ready", status_key: "ready", position: 1, isDone: false, isDefault: false },
  { name: "In Progress", status_key: "in_progress", position: 2, isDone: false, isDefault: false },
  { name: "Done", status_key: "done", position: 3, isDone: true, isDefault: false },
];

export class PgTaskRepository {
  constructor(private readonly pool: Pool) {}

  async listBoards(identity: SpaceUserIdentity, filters: { workspaceId: string | null; status: string | null; limit: number; offset: number }) {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    const add = (value: unknown) => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.workspaceId) clauses.push(`workspace_id = ${add(filters.workspaceId)}`);
    if (filters.status) clauses.push(`status = ${add(filters.status)}`);
    else clauses.push("deleted_at IS NULL");
    const where = `WHERE ${clauses.join(" AND ")}`;
    const total = await this.pool.query<{ total: string }>(`SELECT count(*)::text AS total FROM boards ${where}`, params);
    const rows = await this.pool.query<BoardRow>(
      `SELECT ${BOARD_COLUMNS} FROM boards ${where}
       ORDER BY COALESCE(sort_order, 2147483647), updated_at DESC, id DESC
       LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(boardOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async createBoard(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    return withDbTransaction(this.pool, async (client) => {
      const now = new Date().toISOString();
      const boardId = randomUUID();
      await client.query(
        `INSERT INTO boards (
           id, space_id, workspace_id, name, description, board_type, status,
           default_view, sort_order, metadata_json, created_by_user_id,
           created_at, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::int, $10::jsonb, $11, $12, $12)`,
        [
          boardId,
          identity.spaceId,
          optionalString(body.workspace_id),
          requiredString(body.name, "name"),
          optionalString(body.description),
          optionalString(body.board_type) ?? "workspace",
          optionalString(body.status) ?? "active",
          optionalString(body.default_view),
          numberValue(body.sort_order),
          JSON.stringify(optionalObject(body.metadata_json)),
          identity.userId,
          now,
        ],
      );
      if (body.create_default_columns !== false) {
        for (const column of DEFAULT_COLUMNS) {
          await client.query(
            `INSERT INTO board_columns (
               id, space_id, board_id, name, status_key, position,
               is_done_column, is_default_column, metadata_json, created_at, updated_at
             ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, '{}'::jsonb, $9, $9)`,
            [
              randomUUID(),
              identity.spaceId,
              boardId,
              column.name,
              column.status_key,
              column.position,
              column.isDone,
              column.isDefault,
              now,
            ],
          );
        }
      }
      return (await this.getBoardFrom(client, identity, boardId))!;
    });
  }

  async getBoard(identity: SpaceUserIdentity, boardId: string) {
    return this.getBoardFrom(this.pool, identity, boardId);
  }

  async updateBoard(identity: SpaceUserIdentity, boardId: string, body: Record<string, unknown>) {
    if (!(await this.getBoard(identity, boardId))) throw new HttpError(404, "Board not found");
    const now = new Date().toISOString();
    await this.pool.query(
      `UPDATE boards SET
         name = COALESCE($3, name),
         description = CASE WHEN $4::boolean THEN $5 ELSE description END,
         board_type = COALESCE($6, board_type),
         status = COALESCE($7, status),
         default_view = CASE WHEN $8::boolean THEN $9 ELSE default_view END,
         sort_order = CASE WHEN $10::boolean THEN $11::int ELSE sort_order END,
         metadata_json = CASE WHEN $12::boolean THEN $13::jsonb ELSE metadata_json END,
         deleted_at = CASE WHEN $14::boolean THEN $15::timestamptz ELSE deleted_at END,
         updated_at = $16
       WHERE space_id = $1 AND id = $2`,
      [
        identity.spaceId,
        boardId,
        optionalString(body.name),
        Object.hasOwn(body, "description"),
        optionalString(body.description),
        optionalString(body.board_type),
        optionalString(body.status),
        Object.hasOwn(body, "default_view"),
        optionalString(body.default_view),
        Object.hasOwn(body, "sort_order"),
        numberValue(body.sort_order),
        Object.hasOwn(body, "metadata_json"),
        JSON.stringify(optionalObject(body.metadata_json)),
        Object.hasOwn(body, "deleted_at"),
        toDbDate(body.deleted_at),
        now,
      ],
    );
    return (await this.getBoard(identity, boardId))!;
  }

  async listBoardTasks(identity: SpaceUserIdentity, boardId: string, limit: number, offset: number) {
    if (!(await this.getBoard(identity, boardId))) throw new HttpError(404, "Board not found");
    return this.listTasks(identity, { boardId, workspaceId: null, status: null, assignedToMe: false, q: null, limit, offset });
  }

  async listTasks(identity: SpaceUserIdentity, filters: {
    boardId: string | null;
    workspaceId: string | null;
    status: string | null;
    assignedToMe: boolean;
    q: string | null;
    limit: number;
    offset: number;
  }) {
    const built = buildTaskWhere(identity, filters);
    const total = await this.pool.query<{ total: string }>(`SELECT count(*)::text AS total FROM tasks t ${built.where}`, built.params);
    const rows = await this.pool.query<TaskRow>(
      `SELECT ${TASK_COLUMNS} FROM tasks t ${built.where}
       ORDER BY t.updated_at DESC, t.id DESC
       LIMIT $${built.params.length + 1} OFFSET $${built.params.length + 2}`,
      [...built.params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(taskOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async listMyTasks(identity: SpaceUserIdentity, filters: { status: string | null; limit: number; offset: number }) {
    const params: unknown[] = [identity.userId];
    const clauses = [
      "sm.user_id = $1",
      "sm.status = 'active'",
      "t.deleted_at IS NULL",
      "(t.visibility IN ('space_shared', 'workspace_shared') OR t.created_by_user_id = $1 OR t.assigned_user_id = $1 OR t.claimed_by_user_id = $1)",
      "(t.assigned_user_id = $1 OR t.claimed_by_user_id = $1 OR t.created_by_user_id = $1)",
    ];
    if (filters.status) {
      params.push(filters.status);
      clauses.push(`t.status = $${params.length}`);
    }
    const where = `WHERE ${clauses.join(" AND ")}`;
    const total = await this.pool.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM tasks t JOIN space_memberships sm ON sm.space_id = t.space_id ${where}`,
      params,
    );
    const rows = await this.pool.query<TaskRow>(
      `SELECT t.${TASK_COLUMNS.trim().replace(/,\s*/g, ", t.")}
         FROM tasks t
         JOIN space_memberships sm ON sm.space_id = t.space_id
        ${where}
        ORDER BY t.updated_at DESC, t.id DESC
        LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(taskOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async createTask(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    const now = new Date().toISOString();
    const result = await this.pool.query<TaskRow>(
      `INSERT INTO tasks (
         id, space_id, workspace_id, board_id, column_id, parent_task_id,
         title, description, task_type, status, priority, risk_level, visibility,
         created_by_user_id, assigned_user_id, assigned_agent_id,
         source_activity_id, source_run_id, source_proposal_id, source_artifact_id,
         acceptance_criteria_json, definition_of_done, required_outputs_json,
         due_at, start_after, max_runs, max_cost, max_duration_seconds,
         policy_json, metadata_json, tags, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8, $9, $10, $11, $12, $13,
         $14, $15, $16,
         $17, $18, $19, $20,
         $21::jsonb, $22, $23::jsonb,
         $24::timestamptz, $25::timestamptz, $26::int, $27::float, $28::int,
         $29::jsonb, $30::jsonb, $31::jsonb, $32, $32
       ) RETURNING ${TASK_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        optionalString(body.workspace_id),
        optionalString(body.board_id),
        optionalString(body.column_id),
        optionalString(body.parent_task_id),
        requiredString(body.title, "title"),
        optionalString(body.description),
        optionalString(body.task_type) ?? "general",
        optionalString(body.status) ?? "inbox",
        optionalString(body.priority) ?? "normal",
        optionalString(body.risk_level) ?? "low",
        optionalString(body.visibility) ?? "space_shared",
        identity.userId,
        optionalString(body.assigned_user_id),
        optionalString(body.assigned_agent_id),
        optionalString(body.source_activity_id),
        optionalString(body.source_run_id),
        optionalString(body.source_proposal_id),
        optionalString(body.source_artifact_id),
        JSON.stringify(optionalObject(body.acceptance_criteria_json)),
        optionalString(body.definition_of_done),
        JSON.stringify(Array.isArray(body.required_outputs_json) ? body.required_outputs_json : null),
        toDbDate(body.due_at),
        toDbDate(body.start_after),
        numberValue(body.max_runs),
        numberValue(body.max_cost),
        numberValue(body.max_duration_seconds),
        JSON.stringify(optionalObject(body.policy_json)),
        JSON.stringify(optionalObject(body.metadata_json)),
        JSON.stringify(Array.isArray(body.tags) ? body.tags : null),
        now,
      ],
    );
    return taskOut(result.rows[0]!);
  }

  async getTask(identity: SpaceUserIdentity, taskId: string) {
    const row = await getVisibleTaskRow(this.pool, identity, taskId);
    return row ? taskOut(row) : null;
  }

  async updateTask(identity: SpaceUserIdentity, taskId: string, body: Record<string, unknown>) {
    if (!(await getVisibleTaskRow(this.pool, identity, taskId))) throw new HttpError(404, "Task not found");
    const now = new Date().toISOString();
    await this.pool.query(
      `UPDATE tasks SET
         title = COALESCE($3, title),
         description = CASE WHEN $4::boolean THEN $5 ELSE description END,
         workspace_id = CASE WHEN $6::boolean THEN $7 ELSE workspace_id END,
         board_id = CASE WHEN $8::boolean THEN $9 ELSE board_id END,
         column_id = CASE WHEN $10::boolean THEN $11 ELSE column_id END,
         parent_task_id = CASE WHEN $12::boolean THEN $13 ELSE parent_task_id END,
         task_type = COALESCE($14, task_type),
         status = COALESCE($15, status),
         priority = COALESCE($16, priority),
         risk_level = COALESCE($17, risk_level),
         assigned_user_id = CASE WHEN $18::boolean THEN $19 ELSE assigned_user_id END,
         assigned_agent_id = CASE WHEN $20::boolean THEN $21 ELSE assigned_agent_id END,
         claimed_by_user_id = CASE WHEN $22::boolean THEN $23 ELSE claimed_by_user_id END,
         claimed_by_agent_id = CASE WHEN $24::boolean THEN $25 ELSE claimed_by_agent_id END,
         completed_at = CASE WHEN $26::boolean THEN $27::timestamptz ELSE completed_at END,
         cancelled_at = CASE WHEN $28::boolean THEN $29::timestamptz ELSE cancelled_at END,
         blocked_reason = CASE WHEN $30::boolean THEN $31 ELSE blocked_reason END,
         due_at = CASE WHEN $32::boolean THEN $33::timestamptz ELSE due_at END,
         start_after = CASE WHEN $34::boolean THEN $35::timestamptz ELSE start_after END,
         estimated_effort = CASE WHEN $36::boolean THEN $37 ELSE estimated_effort END,
         actual_effort = CASE WHEN $38::boolean THEN $39 ELSE actual_effort END,
         max_runs = CASE WHEN $40::boolean THEN $41::int ELSE max_runs END,
         max_cost = CASE WHEN $42::boolean THEN $43::float ELSE max_cost END,
         max_duration_seconds = CASE WHEN $44::boolean THEN $45::int ELSE max_duration_seconds END,
         policy_json = CASE WHEN $46::boolean THEN $47::jsonb ELSE policy_json END,
         metadata_json = CASE WHEN $48::boolean THEN $49::jsonb ELSE metadata_json END,
         tags = CASE WHEN $50::boolean THEN $51::jsonb ELSE tags END,
         deleted_at = CASE WHEN $52::boolean THEN $53::timestamptz ELSE deleted_at END,
         updated_at = $54
       WHERE space_id = $1 AND id = $2`,
      [
        identity.spaceId,
        taskId,
        optionalString(body.title),
        Object.hasOwn(body, "description"),
        optionalString(body.description),
        Object.hasOwn(body, "workspace_id"),
        optionalString(body.workspace_id),
        Object.hasOwn(body, "board_id"),
        optionalString(body.board_id),
        Object.hasOwn(body, "column_id"),
        optionalString(body.column_id),
        Object.hasOwn(body, "parent_task_id"),
        optionalString(body.parent_task_id),
        optionalString(body.task_type),
        optionalString(body.status),
        optionalString(body.priority),
        optionalString(body.risk_level),
        Object.hasOwn(body, "assigned_user_id"),
        optionalString(body.assigned_user_id),
        Object.hasOwn(body, "assigned_agent_id"),
        optionalString(body.assigned_agent_id),
        Object.hasOwn(body, "claimed_by_user_id"),
        optionalString(body.claimed_by_user_id),
        Object.hasOwn(body, "claimed_by_agent_id"),
        optionalString(body.claimed_by_agent_id),
        Object.hasOwn(body, "completed_at"),
        toDbDate(body.completed_at),
        Object.hasOwn(body, "cancelled_at"),
        toDbDate(body.cancelled_at),
        Object.hasOwn(body, "blocked_reason"),
        optionalString(body.blocked_reason),
        Object.hasOwn(body, "due_at"),
        toDbDate(body.due_at),
        Object.hasOwn(body, "start_after"),
        toDbDate(body.start_after),
        Object.hasOwn(body, "estimated_effort"),
        optionalString(body.estimated_effort),
        Object.hasOwn(body, "actual_effort"),
        optionalString(body.actual_effort),
        Object.hasOwn(body, "max_runs"),
        numberValue(body.max_runs),
        Object.hasOwn(body, "max_cost"),
        numberValue(body.max_cost),
        Object.hasOwn(body, "max_duration_seconds"),
        numberValue(body.max_duration_seconds),
        Object.hasOwn(body, "policy_json"),
        JSON.stringify(optionalObject(body.policy_json)),
        Object.hasOwn(body, "metadata_json"),
        JSON.stringify(optionalObject(body.metadata_json)),
        Object.hasOwn(body, "tags"),
        JSON.stringify(Array.isArray(body.tags) ? body.tags : null),
        Object.hasOwn(body, "deleted_at"),
        toDbDate(body.deleted_at),
        now,
      ],
    );
    return (await this.getTask(identity, taskId))!;
  }

  async createTaskRun(identity: SpaceUserIdentity, taskId: string, body: Record<string, unknown>) {
    return withDbTransaction(this.pool, async (client) => {
      const task = await getVisibleTaskRow(client, identity, taskId);
      if (!task) throw new HttpError(404, "Task not found");
      if (task.max_runs !== null) {
        const existing = await client.query<{ total: string }>(
          `SELECT count(*)::text AS total FROM task_runs WHERE space_id = $1 AND task_id = $2`,
          [identity.spaceId, taskId],
        );
        if (countFromRow(existing.rows[0]) >= task.max_runs) throw new HttpError(409, "Task max_runs exceeded");
      }
      const agentId = optionalString(body.agent_id) ?? task.assigned_agent_id;
      if (!agentId) throw new HttpError(422, "agent_id is required when task has no assigned_agent_id");
      const run = await new PgRunRepository(client).createQueuedRun({
        agent_id: agentId,
        space_id: identity.spaceId,
        user_id: identity.userId,
        mode: optionalString(body.mode) ?? "live",
        run_type: optionalString(body.run_type) ?? "agent",
        trigger_origin: optionalString(body.trigger_origin) ?? "manual",
        session_id: optionalString(body.session_id),
        workspace_id: optionalString(body.workspace_id) ?? task.workspace_id,
        project_id: null,
        prompt: optionalString(body.prompt),
        instruction: optionalString(body.instruction) ?? defaultTaskInstruction(task),
        scheduled_at: toDbDate(body.scheduled_at),
        parent_run_id: optionalString(body.parent_run_id),
        adapter_type: optionalString(body.adapter_type),
      });
      const now = new Date().toISOString();
      await client.query(`UPDATE runs SET task_id = $3, updated_at = $4 WHERE space_id = $1 AND id = $2`, [identity.spaceId, run.id, taskId, now]);
      await client.query(
        `INSERT INTO task_runs (id, space_id, task_id, run_id, role, created_at)
         VALUES ($1, $2, $3, $4, $5, $6)
         ON CONFLICT (task_id, run_id) DO NOTHING`,
        [randomUUID(), identity.spaceId, taskId, run.id, optionalString(body.role) ?? "primary", now],
      );
      if (body.set_task_in_progress !== false && !["done", "cancelled"].includes(task.status)) {
        await client.query(`UPDATE tasks SET status = 'in_progress', updated_at = $3 WHERE space_id = $1 AND id = $2`, [identity.spaceId, taskId, now]);
      }
      return runToOut(run);
    });
  }

  async listTaskRuns(identity: SpaceUserIdentity, taskId: string, limit: number, offset: number) {
    if (!(await getVisibleTaskRow(this.pool, identity, taskId))) throw new HttpError(404, "Task not found");
    const total = await this.pool.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM task_runs WHERE space_id = $1 AND task_id = $2`,
      [identity.spaceId, taskId],
    );
    const rows = await this.pool.query<TaskRunListRow>(
      `SELECT tr.id AS task_run_id, tr.space_id AS task_run_space_id, tr.task_id AS task_run_task_id,
              tr.run_id AS task_run_run_id, tr.role AS task_run_role, tr.created_at AS task_run_created_at,
              r.id, r.space_id, r.agent_id, r.agent_version_id, r.context_snapshot_id, r.run_type,
              r.status, r.mode, r.prompt, r.instruction, r.workspace_id, r.session_id,
              r.parent_run_id, r.project_id, r.scheduled_at, r.adapter_type, r.capability_id,
              r.model_provider_id, r.model_override_json, r.required_sandbox_level, r.trigger_origin,
              r.instructed_by_user_id, r.error_message, r.error_json, r.output_json, r.usage_json,
              r.started_at, r.ended_at, r.created_at, r.updated_at, r.visibility
        FROM task_runs tr
         JOIN runs r ON r.id = tr.run_id AND r.space_id = tr.space_id
        WHERE tr.space_id = $1 AND tr.task_id = $2
        ORDER BY tr.created_at DESC, tr.id DESC
        LIMIT $3 OFFSET $4`,
      [identity.spaceId, taskId, limit, offset],
    );
    return page(
      rows.rows.map((row) => ({ link: taskRunOutFromList(row), run: runToOut(row) })),
      countFromRow(total.rows[0]),
      limit,
      offset,
    );
  }

  async listTaskArtifacts(identity: SpaceUserIdentity, taskId: string, limit: number, offset: number) {
    if (!(await getVisibleTaskRow(this.pool, identity, taskId))) throw new HttpError(404, "Task not found");
    const total = await this.pool.query<{ total: string }>(
      `SELECT count(*)::text AS total
         FROM task_artifacts ta
         JOIN artifacts a ON a.id = ta.artifact_id AND a.space_id = ta.space_id
        WHERE ta.space_id = $1 AND ta.task_id = $2
          AND (a.visibility IN ('space_shared', 'workspace_shared', 'public_template') OR a.owner_user_id IS NULL OR a.owner_user_id = $3)`,
      [identity.spaceId, taskId, identity.userId],
    );
    const rows = await this.pool.query<TaskArtifactRow>(
      `SELECT ta.id, ta.space_id, ta.task_id, ta.artifact_id, ta.role, ta.created_at,
              a.space_id AS artifact_space_id, a.run_id, a.proposal_id, a.artifact_type,
              a.title, a.mime_type, a.visibility, a.created_at AS artifact_created_at
         FROM task_artifacts ta
         JOIN artifacts a ON a.id = ta.artifact_id AND a.space_id = ta.space_id
        WHERE ta.space_id = $1 AND ta.task_id = $2
          AND (a.visibility IN ('space_shared', 'workspace_shared', 'public_template') OR a.owner_user_id IS NULL OR a.owner_user_id = $3)
        ORDER BY ta.created_at DESC, ta.id DESC
        LIMIT $4 OFFSET $5`,
      [identity.spaceId, taskId, identity.userId, limit, offset],
    );
    return page(rows.rows.map(taskArtifactOut), countFromRow(total.rows[0]), limit, offset);
  }

  async listTaskProposals(identity: SpaceUserIdentity, taskId: string, limit: number, offset: number) {
    if (!(await getVisibleTaskRow(this.pool, identity, taskId))) throw new HttpError(404, "Task not found");
    const total = await this.pool.query<{ total: string }>(
      `SELECT count(*)::text AS total
         FROM task_proposals tp
         JOIN proposals p ON p.id = tp.proposal_id AND p.space_id = tp.space_id
         LEFT JOIN runs r ON r.id = p.created_by_run_id AND r.space_id = p.space_id
        WHERE tp.space_id = $1 AND tp.task_id = $2
          AND (p.visibility = 'space_shared' OR p.created_by_user_id = $3 OR r.instructed_by_user_id = $3)`,
      [identity.spaceId, taskId, identity.userId],
    );
    const rows = await this.pool.query<TaskProposalRow>(
      `SELECT tp.id, tp.space_id, tp.task_id, tp.proposal_id, tp.role, tp.created_at,
              p.space_id AS proposal_space_id, p.proposal_type, p.status, p.title,
              p.visibility, p.created_at AS proposal_created_at, p.preview, p.urgency,
              p.review_deadline, p.expires_at, p.created_by_run_id
         FROM task_proposals tp
         JOIN proposals p ON p.id = tp.proposal_id AND p.space_id = tp.space_id
         LEFT JOIN runs r ON r.id = p.created_by_run_id AND r.space_id = p.space_id
        WHERE tp.space_id = $1 AND tp.task_id = $2
          AND (p.visibility = 'space_shared' OR p.created_by_user_id = $3 OR r.instructed_by_user_id = $3)
        ORDER BY tp.created_at DESC, tp.id DESC
        LIMIT $4 OFFSET $5`,
      [identity.spaceId, taskId, identity.userId, limit, offset],
    );
    return page(rows.rows.map(taskProposalOut), countFromRow(total.rows[0]), limit, offset);
  }

  async listTaskEvaluations(identity: SpaceUserIdentity, taskId: string, limit: number, offset: number) {
    if (!(await getVisibleTaskRow(this.pool, identity, taskId))) throw new HttpError(404, "Task not found");
    const total = await this.pool.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM task_evaluations WHERE space_id = $1 AND task_id = $2`,
      [identity.spaceId, taskId],
    );
    const rows = await this.pool.query<TaskEvaluationRow>(
      `SELECT id, space_id, task_id, run_id, run_evaluation_id, evaluator_type,
              evaluator_user_id, evaluator_agent_id, score, confidence, summary,
              checklist_json, known_issues_json, evidence_artifact_ids,
              recommendation, created_at
         FROM task_evaluations
        WHERE space_id = $1 AND task_id = $2
        ORDER BY created_at DESC, id DESC
        LIMIT $3 OFFSET $4`,
      [identity.spaceId, taskId, limit, offset],
    );
    return page(rows.rows.map(taskEvaluationOut), countFromRow(total.rows[0]), limit, offset);
  }

  async createTaskEvaluation(identity: SpaceUserIdentity, taskId: string, body: Record<string, unknown>) {
    if (!(await getVisibleTaskRow(this.pool, identity, taskId))) throw new HttpError(404, "Task not found");
    const score = bounded01(body.score, "score");
    const confidence = bounded01(body.confidence, "confidence");
    const runId = optionalString(body.run_id);
    if (runId) {
      const link = await this.pool.query<{ id: string }>(
        `SELECT id FROM task_runs WHERE space_id = $1 AND task_id = $2 AND run_id = $3`,
        [identity.spaceId, taskId, runId],
      );
      if (!link.rows[0]) throw new HttpError(422, "run_id must be linked to the task through TaskRun");
    }
    const evidenceArtifactIds = Array.isArray(body.evidence_artifact_ids)
      ? body.evidence_artifact_ids.filter((value): value is string => typeof value === "string")
      : null;
    if (evidenceArtifactIds?.length) {
      const distinct = [...new Set(evidenceArtifactIds)];
      const linked = await this.pool.query<{ total: string }>(
        `SELECT count(DISTINCT ta.artifact_id)::text AS total
           FROM task_artifacts ta
           JOIN artifacts a ON a.id = ta.artifact_id AND a.space_id = ta.space_id
          WHERE ta.space_id = $1 AND ta.task_id = $2 AND ta.artifact_id::text = ANY($3::text[])`,
        [identity.spaceId, taskId, distinct],
      );
      if (countFromRow(linked.rows[0]) !== distinct.length) {
        throw new HttpError(422, "evidence_artifact_ids must be linked to the task through TaskArtifact");
      }
    }
    const now = new Date().toISOString();
    const result = await this.pool.query<TaskEvaluationRow>(
      `INSERT INTO task_evaluations (
         id, space_id, task_id, run_id, evaluator_type, evaluator_user_id,
         score, confidence, summary, checklist_json, known_issues_json,
         evidence_artifact_ids, recommendation, created_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7::float, $8::float, $9, $10::jsonb, $11::jsonb, $12::jsonb, $13, $14)
       RETURNING id, space_id, task_id, run_id, run_evaluation_id, evaluator_type,
                 evaluator_user_id, evaluator_agent_id, score, confidence, summary,
                 checklist_json, known_issues_json, evidence_artifact_ids,
                 recommendation, created_at`,
      [
        randomUUID(),
        identity.spaceId,
        taskId,
        runId,
        requiredString(body.evaluator_type, "evaluator_type"),
        identity.userId,
        score,
        confidence,
        optionalString(body.summary),
        JSON.stringify(optionalObject(body.checklist_json)),
        JSON.stringify(Array.isArray(body.known_issues_json) ? body.known_issues_json : null),
        JSON.stringify(evidenceArtifactIds),
        optionalString(body.recommendation),
        now,
      ],
    );
    return taskEvaluationOut(result.rows[0]!);
  }

  private async getBoardFrom(db: Queryable, identity: SpaceUserIdentity, boardId: string) {
    const row = await db.query<BoardRow>(`SELECT ${BOARD_COLUMNS} FROM boards WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`, [identity.spaceId, boardId]);
    const board = row.rows[0];
    if (!board) return null;
    const columns = await db.query<BoardColumnRow>(
      `SELECT ${BOARD_COLUMN_COLUMNS} FROM board_columns WHERE space_id = $1 AND board_id = $2 AND deleted_at IS NULL ORDER BY position, id`,
      [identity.spaceId, boardId],
    );
    return { ...boardOut(board), columns: columns.rows.map(boardColumnOut) };
  }
}

async function getVisibleTaskRow(db: Queryable, identity: SpaceUserIdentity, taskId: string): Promise<TaskRow | null> {
  const result = await db.query<TaskRow>(`SELECT ${TASK_COLUMNS} FROM tasks WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`, [identity.spaceId, taskId]);
  const row = result.rows[0];
  if (!row) return null;
  if (!canReadByVisibility(row.visibility, identity.userId, [row.created_by_user_id, row.assigned_user_id, row.claimed_by_user_id])) return null;
  return row;
}

function buildTaskWhere(identity: SpaceUserIdentity, filters: { boardId: string | null; workspaceId: string | null; status: string | null; assignedToMe: boolean; q: string | null }) {
  const params: unknown[] = [identity.spaceId, identity.userId];
  const clauses = [
    "t.space_id = $1",
    "t.deleted_at IS NULL",
    "(t.visibility IN ('space_shared', 'workspace_shared') OR t.created_by_user_id = $2 OR t.assigned_user_id = $2 OR t.claimed_by_user_id = $2)",
  ];
  const add = (value: unknown) => {
    params.push(value);
    return `$${params.length}`;
  };
  if (filters.boardId) clauses.push(`t.board_id = ${add(filters.boardId)}`);
  if (filters.workspaceId) clauses.push(`t.workspace_id = ${add(filters.workspaceId)}`);
  if (filters.status) clauses.push(`t.status = ${add(filters.status)}`);
  if (filters.assignedToMe) clauses.push("(t.assigned_user_id = $2 OR t.claimed_by_user_id = $2)");
  if (filters.q) clauses.push(`(t.title ILIKE ${add(`%${filters.q}%`)} OR t.description ILIKE $${params.length})`);
  return { where: `WHERE ${clauses.join(" AND ")}`, params };
}

function boardOut(row: BoardRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    workspace_id: row.workspace_id,
    name: row.name,
    description: row.description,
    board_type: row.board_type,
    status: row.status,
    default_view: row.default_view,
    sort_order: row.sort_order,
    metadata_json: row.metadata_json ?? null,
    created_by_user_id: row.created_by_user_id,
    created_by_agent_id: row.created_by_agent_id,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
    deleted_at: dateIso(row.deleted_at),
  };
}

function boardColumnOut(row: BoardColumnRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    board_id: row.board_id,
    name: row.name,
    description: row.description,
    status_key: row.status_key,
    position: row.position,
    wip_limit: row.wip_limit,
    is_done_column: Boolean(row.is_done_column),
    is_default_column: Boolean(row.is_default_column),
    metadata_json: row.metadata_json ?? null,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
    deleted_at: dateIso(row.deleted_at),
  };
}

function taskOut(row: TaskRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    workspace_id: row.workspace_id,
    board_id: row.board_id,
    column_id: row.column_id,
    parent_task_id: row.parent_task_id,
    title: row.title,
    description: row.description,
    task_type: row.task_type,
    status: row.status,
    priority: row.priority,
    risk_level: row.risk_level,
    visibility: row.visibility,
    created_by_user_id: row.created_by_user_id,
    created_by_agent_id: row.created_by_agent_id,
    assigned_user_id: row.assigned_user_id,
    assigned_agent_id: row.assigned_agent_id,
    claimed_by_user_id: row.claimed_by_user_id,
    claimed_by_agent_id: row.claimed_by_agent_id,
    source_activity_id: row.source_activity_id,
    source_run_id: row.source_run_id,
    source_proposal_id: row.source_proposal_id,
    source_artifact_id: row.source_artifact_id,
    due_at: dateIso(row.due_at),
    start_after: dateIso(row.start_after),
    completed_at: dateIso(row.completed_at),
    cancelled_at: dateIso(row.cancelled_at),
    blocked_reason: row.blocked_reason,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
    deleted_at: dateIso(row.deleted_at),
  };
}

function taskRunOutFromList(row: TaskRunListRow) {
  return {
    id: row.task_run_id,
    space_id: row.task_run_space_id,
    task_id: row.task_run_task_id,
    run_id: row.task_run_run_id,
    role: row.task_run_role,
    created_at: dateIso(row.task_run_created_at),
  };
}

function taskArtifactOut(row: TaskArtifactRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    task_id: row.task_id,
    artifact_id: row.artifact_id,
    role: row.role,
    created_at: dateIso(row.created_at),
    artifact: {
      id: row.artifact_id,
      space_id: row.artifact_space_id,
      run_id: row.run_id,
      proposal_id: row.proposal_id,
      artifact_type: row.artifact_type,
      title: row.title,
      mime_type: row.mime_type,
      visibility: row.visibility,
      created_at: dateIso(row.artifact_created_at),
    },
  };
}

function taskProposalOut(row: TaskProposalRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    task_id: row.task_id,
    proposal_id: row.proposal_id,
    role: row.role,
    created_at: dateIso(row.created_at),
    proposal: {
      id: row.proposal_id,
      space_id: row.proposal_space_id,
      proposal_type: row.proposal_type,
      status: row.status,
      title: row.title,
      visibility: row.visibility,
      created_at: dateIso(row.proposal_created_at),
      preview: Boolean(row.preview),
      urgency: row.urgency,
      review_deadline: dateIso(row.review_deadline),
      expires_at: dateIso(row.expires_at),
      expired: Boolean(row.expires_at && new Date(row.expires_at as string).getTime() < Date.now() && row.status === "pending"),
      created_by_run_id: row.created_by_run_id,
    },
  };
}

function taskEvaluationOut(row: TaskEvaluationRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    task_id: row.task_id,
    run_id: row.run_id,
    run_evaluation_id: row.run_evaluation_id,
    evaluator_type: row.evaluator_type,
    evaluator_user_id: row.evaluator_user_id,
    evaluator_agent_id: row.evaluator_agent_id,
    score: row.score,
    confidence: row.confidence,
    summary: row.summary,
    checklist_json: row.checklist_json ?? null,
    known_issues_json: row.known_issues_json ?? null,
    evidence_artifact_ids: row.evidence_artifact_ids ?? null,
    recommendation: row.recommendation,
    created_at: dateIso(row.created_at),
  };
}

function defaultTaskInstruction(task: TaskRow): string {
  const details = [task.description, task.blocked_reason ? `Blocked: ${task.blocked_reason}` : null].filter(Boolean).join("\n\n");
  return details ? `Task: ${task.title}\n\n${details}` : `Task: ${task.title}`;
}

function bounded01(value: unknown, field: string): number | null {
  const parsed = numberValue(value);
  if (parsed === null) return null;
  if (parsed < 0 || parsed > 1) throw new HttpError(422, `${field} must be between 0 and 1`);
  return parsed;
}
