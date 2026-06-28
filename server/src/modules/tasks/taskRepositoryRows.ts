import type { RunRecord } from "../runs/repository";

export interface BoardRow {
  id: string;
  space_id: string;
  workspace_id: string | null;
  project_id: string | null;
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

export interface BoardColumnRow {
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

export interface TaskRow {
  id: string;
  space_id: string;
  workspace_id: string | null;
  project_id: string | null;
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

export interface TaskRunListRow extends RunRecord {
  task_run_id: string;
  task_run_space_id: string;
  task_run_task_id: string;
  task_run_run_id: string;
  task_run_role: string;
  task_run_created_at: unknown;
}

export interface TaskEvaluationRow {
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

export interface TaskArtifactRow {
  id: string;
  space_id: string;
  task_id: string;
  artifact_id: string;
  task_artifact_run_id: string | null;
  role: string;
  created_at: unknown;
  artifact_space_id: string;
  artifact_run_id: string | null;
  proposal_id: string | null;
  artifact_type: string;
  title: string;
  mime_type: string | null;
  visibility: string;
  artifact_created_at: unknown;
}

export interface TaskProposalRow {
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

export const BOARD_COLUMNS = `
  id, space_id, workspace_id, project_id, name, description, board_type, status,
  default_view, sort_order, metadata_json, created_by_user_id,
  created_by_agent_id, created_at, updated_at, deleted_at
`;

export const BOARD_COLUMN_COLUMNS = `
  id, space_id, board_id, name, description, status_key, position,
  wip_limit, is_done_column, is_default_column, metadata_json,
  created_at, updated_at, deleted_at
`;

export const TASK_COLUMNS = `
  id, space_id, workspace_id, project_id, board_id, column_id, parent_task_id,
  title, description, task_type, status, priority, risk_level, visibility,
  created_by_user_id, created_by_agent_id, assigned_user_id, assigned_agent_id,
  claimed_by_user_id, claimed_by_agent_id, source_activity_id, source_run_id,
  source_proposal_id, source_artifact_id, due_at, start_after, completed_at,
  cancelled_at, blocked_reason, max_runs, created_at, updated_at, deleted_at
`;

export const DEFAULT_COLUMNS = [
  { name: "Inbox", status_key: "inbox", position: 0, isDone: false, isDefault: true },
  { name: "Ready", status_key: "ready", position: 1, isDone: false, isDefault: false },
  { name: "In Progress", status_key: "in_progress", position: 2, isDone: false, isDefault: false },
  { name: "Done", status_key: "done", position: 3, isDone: true, isDefault: false },
];
