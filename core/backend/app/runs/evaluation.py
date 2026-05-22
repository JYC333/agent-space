"""RunEvaluationService — append-only deterministic harness-level evaluation.

Each call to evaluate() creates a new RunEvaluation row. Existing evaluations are
never deleted or overwritten. get_latest() returns the most recent row for a run.

Evidence sources (harness-boundary only):
  - Run.status / error_json / output_json / exit_code / source / trigger_origin
  - Run.required_sandbox_level / observability_level / data_exposure_level
  - Ordered RunSteps (step_type, status, error_type)
  - ContextSnapshot token_budget_json / retrieval_trace_json
  - Produced Artifacts (trust_level)
  - Created Proposals (risk_level, payload_json validation/patch signals)
  - ValidationRecipe / WorkspaceProfile when available
  - output_json.materialization_errors

Hard rules:
  - No LLM-as-judge.
  - No parsing vendor CLI internal tool calls.
  - No auto-apply of any Proposal.
  - No writes to MemoryEntry, Policy, Proposal, TaskEvaluation, or RunReflection.
  - No mutation of Run, Artifact, or Proposal rows.
  - CLI runtimes evaluated through harness-level evidence only.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import (
    Artifact,
    ContextSnapshot,
    Proposal,
    Run,
    RunEvaluation,
    RunStep,
    Task,
    TaskRun,
    ValidationRecipe,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constrained value sets (exported for tests)
# ---------------------------------------------------------------------------

OUTCOME_STATUSES = frozenset({"passed", "failed", "partial", "unknown"})
FAILURE_LAYERS = frozenset({
    "context", "sandbox", "runtime", "tool", "validation",
    "policy", "task_spec", "orchestration", "evaluator", "unknown",
})
TRAJECTORY_STATUSES = frozenset({"acceptable", "incomplete", "unsafe", "insufficient_evidence"})

_EVALUATOR_TYPE = "deterministic_harness"
_EVALUATOR_VERSION = "harness_eval.v1"

_NON_TERMINAL = frozenset({"queued", "running", "waiting_for_review"})
_ADAPTER_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
_TERMINAL_STEP_TYPES = frozenset({"completed", "failed", "cancelled"})

# Materialization error codes that force incomplete trajectory
_INCOMPLETE_PATCH_ERRORS = frozenset({"code_patch_incomplete", "code_patch_skipped_files", "code_patch_collection_error"})
# Materialization error codes that cause partial outcome on an otherwise-succeeded run
_PARTIAL_OUTCOME_MAT_ERRORS = frozenset({
    "code_patch_incomplete", "code_patch_skipped_files",
    "code_patch_collection_error", "runtime_output_artifact",
    "produced_artifact_ingestion_error",
})

# ---------------------------------------------------------------------------
# Canonical exact error-code → (failure_layer, failure_reason_code) mapping.
# This mapping runs BEFORE any string heuristics.
# ---------------------------------------------------------------------------

_EXACT_ERROR_CODE_MAP: dict[str, tuple[str, str]] = {
    # context
    "context_snapshot_population_failed": ("context", "context_snapshot_population_failed"),
    # sandbox
    "sandbox_required": ("sandbox", "sandbox_required"),
    "critical_runtime_requires_unimplemented_one_shot_docker": (
        "sandbox", "critical_runtime_requires_unimplemented_one_shot_docker",
    ),
    # policy — file_access must map to policy, not sandbox, regardless of "worktree" substring
    "file_access_adapter_requires_worktree_policy": (
        "policy", "file_access_adapter_requires_worktree_policy",
    ),
    "automation_preflight_dirty_workspace": ("policy", "automation_preflight_dirty_workspace"),
    "automation_preflight_no_credential_profile": ("policy", "automation_preflight_no_credential_profile"),
    "automation_preflight_invalid_runtime_policy": ("policy", "automation_preflight_invalid_runtime_policy"),
    "credentials_missing": ("policy", "credentials_missing"),
    # task_spec
    "automation_preflight_no_adapter": ("task_spec", "automation_preflight_no_adapter"),
    "automation_preflight_no_workspace": ("task_spec", "automation_preflight_no_workspace"),
    "automation_preflight_workspace_not_git_repo": ("task_spec", "automation_preflight_workspace_not_git_repo"),
    # runtime
    "adapter_runtime_error": ("runtime", "adapter_runtime_error"),
    "runtime_removed": ("runtime", "runtime_removed"),
    # orchestration
    "duplicate_execution": ("orchestration", "duplicate_execution"),
    "run_cancelled": ("orchestration", "run_cancelled"),
    # validation
    "validation_failed": ("validation", "validation_failed"),
    "validation_command_failed": ("validation", "validation_command_failed"),
    "code_patch_validation_failed": ("validation", "code_patch_validation_failed"),
    # tool
    "code_patch_collection_error": ("tool", "code_patch_collection_error"),
    "produced_artifact_ingestion_error": ("tool", "produced_artifact_ingestion_error"),
}


def _new_id() -> str:
    from ulid import ULID
    return str(ULID())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_mat_error_code(entry: "str | dict") -> Optional[str]:
    """Extract the canonical error code from a materialization error entry.

    RunExecutionService writes strings like:
      "code_patch_skipped_files: a.png (binary) — skipped"
      "code_patch_collection_error: Traceback (most recent call last)..."

    For strings: split on the first ':', strip, return the prefix as the code.
    For dicts: read error_code, type, or code key.
    Returns None if no code can be extracted.
    """
    if isinstance(entry, str):
        code = entry.split(":", 1)[0].strip()
        return code if code else None
    if isinstance(entry, dict):
        ec = entry.get("error_code") or entry.get("type") or entry.get("code")
        return str(ec) if ec else None
    return None


def _sanitize_dict_for_evidence(d: dict) -> dict:
    """Return a copy of d safe for JSON serialization.

    Only non-serializable leaf values are converted to strings — the dict
    structure and all serializable values are preserved as-is.
    """
    import json

    result: dict = {}
    for k, v in d.items():
        sk = str(k) if not isinstance(k, str) else k
        try:
            json.dumps(v)
            result[sk] = v
        except (TypeError, ValueError):
            result[sk] = str(v)
    return result


# ---------------------------------------------------------------------------
# Context snapshot requirements
# ---------------------------------------------------------------------------

def requires_context_snapshot(run: Run) -> bool:
    """Return True if this run type is expected to produce a ContextSnapshot."""
    return run.source not in ("manual_import", "remote_import")


# ---------------------------------------------------------------------------
# Error code collection
# ---------------------------------------------------------------------------

def _collect_error_codes(
    run: Run,
    steps: list[RunStep],
    proposals: list[Proposal],
) -> list[str]:
    """Collect all error/reason codes from run evidence, deduped, order-preserved."""
    codes: list[str] = []

    # From run.error_json
    err = run.error_json or {}
    if isinstance(err, dict):
        for key in ("error_code", "code"):
            v = err.get(key)
            if v and isinstance(v, str):
                codes.append(v)

    # From run.output_json top-level error_code
    out = run.output_json or {}
    if isinstance(out, dict):
        v = out.get("error_code")
        if v and isinstance(v, str):
            codes.append(v)

        # From output_json.materialization_errors — normalize before appending
        mat = out.get("materialization_errors") or []
        if isinstance(mat, list):
            for e in mat:
                code = _normalize_mat_error_code(e)
                if code:
                    codes.append(code)

    # From failed RunStep.error_type
    for s in steps:
        if s.status == "failed" and s.error_type:
            codes.append(s.error_type)

    # From proposal validation and patch signals
    for prop in proposals:
        payload = prop.payload_json or {}
        if not isinstance(payload, dict):
            continue
        val = payload.get("validation") or {}
        if isinstance(val, dict):
            if val.get("status") == "failed":
                codes.append("validation_failed")
            commands = val.get("commands") or val.get("results") or []
            if isinstance(commands, list):
                for cmd in commands:
                    if isinstance(cmd, dict) and cmd.get("status") == "failed":
                        codes.append("validation_command_failed")
        if payload.get("incomplete_patch") or payload.get("patch_incomplete"):
            codes.append("code_patch_incomplete")
        skipped = payload.get("skipped_changes") or payload.get("skipped_files")
        if skipped:
            codes.append("code_patch_skipped_files")

    # Synthesize run_cancelled for cancelled runs so rule_trace shows exact mapping
    if getattr(run, "status", None) == "cancelled":
        codes.append("run_cancelled")

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _exact_error_map(codes: list[str]) -> Optional[tuple[str, str]]:
    """Return (layer, reason_code) for the first code with a canonical mapping."""
    for code in codes:
        mapping = _EXACT_ERROR_CODE_MAP.get(code)
        if mapping:
            return mapping
    return None


# ---------------------------------------------------------------------------
# Evidence gathering — builds the structured evidence_json dict
# ---------------------------------------------------------------------------

def _gather_context_evidence(
    run: Run,
    context_snapshot: Optional[ContextSnapshot],
) -> dict:
    if not context_snapshot:
        return {
            "has_snapshot": False,
            "snapshot_id": None,
            "token_budget": {},
            "retrieval_trace_shape": "missing",
            "warnings": [],
        }

    warnings: list[str] = []
    budget = context_snapshot.token_budget_json or {}
    token_budget: dict = {}
    if isinstance(budget, dict):
        # Real shape: stable_prefix_chars, dynamic_tail_chars, total_chars,
        # stable_prefix_budget_chars, stable_prefix_pct, stable_prefix_target_pct,
        # stable_prefix_warning, compiler_version
        for k in (
            "stable_prefix_chars", "dynamic_tail_chars", "total_chars",
            "stable_prefix_budget_chars", "stable_prefix_pct",
            "stable_prefix_target_pct", "stable_prefix_warning", "compiler_version",
        ):
            if k in budget:
                token_budget[k] = budget[k]
        if budget.get("stable_prefix_warning"):
            warnings.append("stable_prefix_warning")

    trace = context_snapshot.retrieval_trace_json
    if trace is None:
        trace_shape = "missing"
    elif isinstance(trace, list):
        trace_shape = "list"
    elif isinstance(trace, dict):
        trace_shape = "dict"
    else:
        trace_shape = "missing"

    return {
        "has_snapshot": True,
        "snapshot_id": context_snapshot.id,
        "token_budget": token_budget,
        "retrieval_trace_shape": trace_shape,
        "warnings": warnings,
    }


def _gather_materialization_evidence(
    run: Run,
    proposals: list[Proposal],
) -> dict:
    out = run.output_json or {}
    mat_errors: list[str] = []    # original strings, preserved for audit
    mat_codes: list[str] = []     # normalized codes, used for classification
    code_patch_warnings: list[str] = []

    if isinstance(out, dict):
        raw = out.get("materialization_errors") or []
        if isinstance(raw, list):
            for e in raw:
                # Preserve original for audit — strings stay strings, dicts stay dicts
                if isinstance(e, str):
                    mat_errors.append(e)
                elif isinstance(e, dict):
                    mat_errors.append(_sanitize_dict_for_evidence(e))
                # Normalized code for classification
                code = _normalize_mat_error_code(e)
                if code and code not in mat_codes:
                    mat_codes.append(code)
        # output_json top-level patch signals
        if out.get("incomplete_patch") or out.get("patch_incomplete"):
            if "code_patch_incomplete" not in code_patch_warnings:
                code_patch_warnings.append("code_patch_incomplete")

    for prop in proposals:
        payload = prop.payload_json or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("incomplete_patch") or payload.get("patch_incomplete"):
            if "code_patch_incomplete" not in code_patch_warnings:
                code_patch_warnings.append("code_patch_incomplete")
        skipped = payload.get("skipped_changes") or payload.get("skipped_files")
        if skipped and "code_patch_skipped_files" not in code_patch_warnings:
            code_patch_warnings.append("code_patch_skipped_files")

    return {"errors": mat_errors, "codes": mat_codes, "code_patch_warnings": code_patch_warnings}


def _gather_evidence_json(
    run: Run,
    steps: list[RunStep],
    artifacts: list[Artifact],
    proposals: list[Proposal],
    context_snapshot: Optional[ContextSnapshot],
    task: Optional[Task],
    validation_recipe: Optional[ValidationRecipe],
    error_codes: list[str],
) -> dict:
    """Build the canonical structured evidence_json dict."""

    # Steps
    step_types = [s.step_type for s in steps]
    failed_steps = [
        {
            "step_type": s.step_type,
            "status": s.status,
            "error_type": s.error_type,
            "error_message": (s.error_message or "")[:256],
        }
        for s in steps if s.status == "failed"
    ]

    # adapter_started with terminal status counts as adapter completed from harness perspective
    has_adapter_started = "adapter_started" in step_types
    adapter_started_terminal = False
    if has_adapter_started:
        for s in steps:
            if s.step_type == "adapter_started" and s.status in _ADAPTER_TERMINAL_STATUSES:
                adapter_started_terminal = True
                break
    has_adapter_completed_step = "adapter_completed" in step_types
    has_terminal_step = any(st in _TERMINAL_STEP_TYPES for st in step_types)

    # Artifacts
    low_trust_count = sum(1 for a in artifacts if a.trust_level == "low")

    # Proposals
    high_risk_count = sum(
        1 for p in proposals if (p.risk_level or "low") in ("high", "critical")
    )
    incomplete_patch = False
    validation_failed_prop = False
    for prop in proposals:
        payload = prop.payload_json or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("incomplete_patch") or payload.get("patch_incomplete"):
            incomplete_patch = True
        val = payload.get("validation") or {}
        if isinstance(val, dict) and val.get("status") == "failed":
            validation_failed_prop = True

    # Validation recipe
    recipe_id = None
    recipe_status = "unknown"
    recipe_signals: list[str] = []
    if validation_recipe:
        recipe_id = validation_recipe.id
        validation_steps_failed = any(
            s.status == "failed" and s.step_type in ("validation_started", "validation_completed")
            for s in steps
        )
        if validation_steps_failed:
            recipe_status = "failed"
            recipe_signals.append("validation_step_failed")
        else:
            recipe_status = "skipped"

    mat_ev = _gather_materialization_evidence(run, proposals)

    return {
        "run": {
            "status": run.status,
            "exit_code": run.exit_code,
            "has_error_json": bool(run.error_json),
            "error_codes": error_codes,
            "trigger_origin": run.trigger_origin,
            "source": run.source,
            "required_sandbox_level": run.required_sandbox_level,
            "observability_level": run.observability_level,
            "data_exposure_level": run.data_exposure_level,
        },
        "steps": {
            "count": len(steps),
            "types": step_types,
            "failed": failed_steps,
            "adapter_started_terminal": adapter_started_terminal,
            "has_terminal_step": has_terminal_step,
        },
        "context": _gather_context_evidence(run, context_snapshot),
        "artifacts": {
            "count": len(artifacts),
            "low_trust_count": low_trust_count,
        },
        "proposals": {
            "count": len(proposals),
            "high_risk_count": high_risk_count,
            "incomplete_patch": incomplete_patch,
            "validation_failed": validation_failed_prop,
        },
        "validation": {
            "recipe_id": recipe_id,
            "status": recipe_status,
            "signals": recipe_signals,
        },
        "materialization": mat_ev,
    }


# ---------------------------------------------------------------------------
# Classification pipeline — explicit ordered rules, rule_trace accumulated
# ---------------------------------------------------------------------------

def _classify_outcome(ev: dict) -> tuple[str, list[str]]:
    """
    A. Determine outcome_status via explicit ordered rules.
    Returns (outcome_status, rule_trace).
    """
    trace: list[str] = []
    run_ev = ev["run"]
    status = run_ev["status"]
    exit_code = run_ev["exit_code"]
    has_error_json = run_ev.get("has_error_json", False)
    props = ev["proposals"]
    mat = ev["materialization"]
    mat_codes = mat.get("codes", [])
    code_patch_warnings = mat["code_patch_warnings"]

    # A1: non-terminal run
    if status in _NON_TERMINAL:
        trace.append("A1:non_terminal:match")
        return "unknown", trace
    trace.append("A1:non_terminal:skip")

    # A2: status=failed
    if status == "failed":
        trace.append("A2:status_failed:match")
        return "failed", trace
    trace.append("A2:status_failed:skip")

    # A3: status=cancelled (run_cancelled synthesized into error_codes for exact layer mapping)
    if status == "cancelled":
        trace.append("A3:status_cancelled:match")
        return "failed", trace
    trace.append("A3:status_cancelled:skip")

    # A4: exit_code != 0
    if exit_code is not None and exit_code != 0:
        trace.append(f"A4:exit_code={exit_code}:match")
        return "failed", trace
    trace.append("A4:exit_code:skip")

    # A5: error_json present (any non-null error_json indicates run-level error)
    if has_error_json:
        trace.append("A5:has_error_json:match")
        return "failed", trace
    trace.append("A5:has_error_json:skip")

    # A6: status=degraded
    if status == "degraded":
        trace.append("A6:status_degraded:match")
        return "partial", trace
    trace.append("A6:status_degraded:skip")

    # A7: succeeded + validation failed proposal
    if props["validation_failed"]:
        trace.append("A7:validation_failed_proposal:match")
        return "partial", trace
    trace.append("A7:validation_failed_proposal:skip")

    # A8: succeeded + incomplete patch or materialization partial signals
    if (
        props["incomplete_patch"]
        or code_patch_warnings
        or any(e in _PARTIAL_OUTCOME_MAT_ERRORS for e in mat_codes)
    ):
        trace.append("A8:partial_signal_on_succeeded:match")
        return "partial", trace
    trace.append("A8:partial_signal:skip")

    # A9: succeeded
    if status == "succeeded":
        trace.append("A9:succeeded:match")
        return "passed", trace
    trace.append("A9:succeeded:skip")

    trace.append("A10:unknown:match")
    return "unknown", trace


def _classify_failure_layer(
    ev: dict,
    outcome: str,
    error_codes: list[str],
    run_source: Optional[str],
) -> tuple[Optional[str], Optional[str], list[str]]:
    """
    B. Determine failure_layer and failure_reason_code.
    Exact error-code mapping runs before all heuristics.
    Returns (failure_layer, failure_reason_code, rule_trace).
    """
    trace: list[str] = []

    # B1: no layer for passed or unknown outcomes
    if outcome in ("passed", "unknown"):
        trace.append(f"B1:outcome={outcome}:skip_layer")
        return None, None, trace

    # B2: exact error-code mapping — must run before string heuristics
    exact = _exact_error_map(error_codes)
    if exact:
        layer, reason = exact
        trace.append(f"B2:exact_code={reason}:match→{layer}")
        return layer, reason, trace
    trace.append("B2:exact_code:skip")

    ctx = ev["context"]
    props = ev["proposals"]
    steps_ev = ev["steps"]
    mat = ev["materialization"]

    # B3: context hard failure — missing snapshot on a run that requires one
    if not ctx["has_snapshot"]:
        if run_source not in ("manual_import", "remote_import"):
            trace.append("B3:missing_context_snapshot:match→context")
            return "context", "context_snapshot_missing", trace
        trace.append("B3:missing_context_snapshot:skip(source_exempt)")
    else:
        trace.append("B3:context_snapshot_present:skip")

    # B4: validation hard failure
    if props["validation_failed"]:
        trace.append("B4:validation_failed_proposal:match→validation")
        return "validation", "validation_failed", trace
    validation_step_failed = any(
        fs.get("step_type") in ("validation_started", "validation_completed")
        for fs in steps_ev["failed"]
    )
    if validation_step_failed:
        trace.append("B4:validation_step_failed:match→validation")
        return "validation", "validation_failed", trace
    if outcome == "failed" and (
        "code_patch_incomplete" in mat["code_patch_warnings"]
        or "code_patch_skipped_files" in mat["code_patch_warnings"]
    ):
        trace.append("B4:code_patch_warning_on_failure:match→validation")
        return "validation", "code_patch_validation_failed", trace
    trace.append("B4:validation:skip")

    # B5: policy — only via exact code map (handled in B2); high_risk_proposal is trajectory signal
    trace.append("B5:policy:skip(handled_by_B2)")

    # B6: sandbox — "sandbox" substring in failed step error_type (heuristic, after exact map)
    for fs in steps_ev["failed"]:
        et = (fs.get("error_type") or "").lower()
        em = (fs.get("error_message") or "").lower()
        if "sandbox" in et or "sandbox" in em:
            trace.append(f"B6:sandbox_in_step_error:match→sandbox")
            return "sandbox", "sandbox_required", trace
    trace.append("B6:sandbox:skip")

    # B7: task_spec — only via exact code map (handled in B2)
    trace.append("B7:task_spec:skip(handled_by_B2)")

    # B8: orchestration — adapter_started exists but is not in terminal state and no adapter_completed
    has_adapter_started = "adapter_started" in steps_ev["types"]
    adapter_started_terminal = steps_ev["adapter_started_terminal"]
    has_adapter_completed = "adapter_completed" in steps_ev["types"]
    missing_adapter_completion = (
        has_adapter_started
        and not adapter_started_terminal
        and not has_adapter_completed
    )
    if missing_adapter_completion:
        trace.append("B8:missing_adapter_completion:match→orchestration")
        return "orchestration", "orchestration_incomplete", trace
    trace.append("B8:orchestration:skip")

    # B9: runtime — adapter step failed or non-zero exit code
    adapter_started_failed = any(
        fs.get("step_type") == "adapter_started" for fs in steps_ev["failed"]
    )
    adapter_completed_failed = any(
        fs.get("step_type") == "adapter_completed" for fs in steps_ev["failed"]
    )
    run_ev = ev["run"]
    if adapter_completed_failed or adapter_started_failed:
        trace.append("B9:adapter_step_failed:match→runtime")
        return "runtime", "adapter_runtime_error", trace
    if run_ev["exit_code"] is not None and run_ev["exit_code"] != 0:
        trace.append(f"B9:exit_code={run_ev['exit_code']}:match→runtime")
        return "runtime", "adapter_runtime_error", trace
    trace.append("B9:runtime:skip")

    # B10: tool — "tool" in failed step error_type, or tool mat error
    for fs in steps_ev["failed"]:
        et = (fs.get("error_type") or "").lower()
        if "tool" in et:
            trace.append("B10:tool_in_step_error:match→tool")
            return "tool", "tool_error", trace
    if any(e == "code_patch_collection_error" for e in mat.get("codes", [])):
        trace.append("B10:code_patch_collection_error_in_mat:match→tool")
        return "tool", "code_patch_collection_error", trace
    trace.append("B10:tool:skip")

    trace.append("B11:no_signal:match→unknown")
    return "unknown", "unknown", trace


def _classify_trajectory(ev: dict, outcome: str) -> tuple[str, list[str]]:
    """
    C. Determine trajectory_status.
    Returns (trajectory_status, rule_trace).
    Note: trajectory_status does not alone imply failure_layer.
    A run can be outcome_status=passed and trajectory_status=unsafe.
    """
    trace: list[str] = []
    steps_ev = ev["steps"]
    props = ev["proposals"]
    artifacts_ev = ev["artifacts"]
    mat = ev["materialization"]
    ctx = ev["context"]

    # C1: no useful evidence
    no_steps = steps_ev["count"] == 0
    no_snapshot = not ctx["has_snapshot"]
    no_artifacts = artifacts_ev["count"] == 0
    no_proposals = props["count"] == 0
    if no_steps and no_snapshot and no_artifacts and no_proposals:
        trace.append("C1:no_useful_evidence:match→insufficient_evidence")
        return "insufficient_evidence", trace
    trace.append("C1:has_some_evidence:skip")

    # C2: unsafe — high-risk proposals or low-trust artifacts
    if props["high_risk_count"] > 0:
        trace.append("C2:high_risk_proposal:match→unsafe")
        return "unsafe", trace
    if artifacts_ev["low_trust_count"] > 0:
        trace.append("C2:low_trust_artifact:match→unsafe")
        return "unsafe", trace
    trace.append("C2:unsafe:skip")

    # C3: incomplete — patch signals, adapter not completed, missing terminal step
    mat_codes = mat.get("codes", [])
    code_patch_warnings = mat["code_patch_warnings"]
    if (
        props["incomplete_patch"]
        or code_patch_warnings
        or any(e in _INCOMPLETE_PATCH_ERRORS for e in mat_codes)
    ):
        trace.append("C3:incomplete_patch_signal:match→incomplete")
        return "incomplete", trace

    # adapter_started exists but not in terminal state and no separate adapter_completed
    has_adapter_started = "adapter_started" in steps_ev["types"]
    adapter_started_terminal = steps_ev["adapter_started_terminal"]
    has_adapter_completed = "adapter_completed" in steps_ev["types"]
    missing_adapter_completion = (
        has_adapter_started
        and not adapter_started_terminal
        and not has_adapter_completed
    )
    if missing_adapter_completion:
        trace.append("C3:missing_adapter_completion:match→incomplete")
        return "incomplete", trace

    # has steps but no terminal step
    if steps_ev["count"] > 0 and not steps_ev["has_terminal_step"]:
        trace.append("C3:missing_terminal_step:match→incomplete")
        return "incomplete", trace
    trace.append("C3:incomplete:skip")

    trace.append("C4:acceptable:match")
    return "acceptable", trace


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class RunEvaluationService:
    """Append-only deterministic harness-level run evaluation.

    evaluate() always creates a new RunEvaluation row — never deletes old ones.
    get_latest() returns the most recent row for a run.
    list_for_run() returns all rows, newest first.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def evaluate(self, run_id: str, *, space_id: str) -> RunEvaluation:
        """Evaluate a run and append a new RunEvaluation row.

        Raises ValueError if the run is not found.
        Never deletes or overwrites existing evaluations.
        On internal classification error, appends an evaluator-error row.
        """
        run = (
            self.db.query(Run)
            .filter(Run.id == run_id, Run.space_id == space_id)
            .first()
        )
        if not run:
            raise ValueError(f"Run '{run_id}' not found in space '{space_id}'")

        try:
            evaluation = self._run_evaluation(run)
        except Exception:
            log.exception("RunEvaluationService internal error for run=%s", run_id)
            evaluation = self._error_evaluation(run)

        self.db.add(evaluation)
        self.db.flush()
        return evaluation

    def get_latest(self, run_id: str, *, space_id: str) -> Optional[RunEvaluation]:
        """Return the most recent evaluation for a run, or None."""
        return (
            self.db.query(RunEvaluation)
            .filter(RunEvaluation.run_id == run_id, RunEvaluation.space_id == space_id)
            .order_by(RunEvaluation.evaluated_at.desc(), RunEvaluation.id.desc())
            .first()
        )

    def list_for_run(self, run_id: str, *, space_id: str) -> list[RunEvaluation]:
        """Return all evaluations for a run, newest first."""
        return (
            self.db.query(RunEvaluation)
            .filter(RunEvaluation.run_id == run_id, RunEvaluation.space_id == space_id)
            .order_by(RunEvaluation.evaluated_at.desc(), RunEvaluation.id.desc())
            .all()
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_evaluation(self, run: Run) -> RunEvaluation:
        steps = list(run.steps)
        artifacts = list(run.artifacts)
        proposals = list(run.proposals)
        context_snapshot: Optional[ContextSnapshot] = (
            run.context_snapshot if run.context_snapshot_id else None
        )

        task_run: Optional[TaskRun] = (
            self.db.query(TaskRun).filter(TaskRun.run_id == run.id).first()
        )
        task: Optional[Task] = None
        if task_run:
            task = self.db.query(Task).filter(Task.id == task_run.task_id).first()

        validation_recipe: Optional[ValidationRecipe] = None
        if run.workspace_id:
            from ..models import WorkspaceProfile
            profile = (
                self.db.query(WorkspaceProfile)
                .filter(WorkspaceProfile.workspace_id == run.workspace_id)
                .first()
            )
            if profile and profile.validation_recipe_id:
                validation_recipe = (
                    self.db.query(ValidationRecipe)
                    .filter(ValidationRecipe.id == profile.validation_recipe_id)
                    .first()
                )

        error_codes = _collect_error_codes(run, steps, proposals)
        ev = _gather_evidence_json(
            run=run,
            steps=steps,
            artifacts=artifacts,
            proposals=proposals,
            context_snapshot=context_snapshot,
            task=task,
            validation_recipe=validation_recipe,
            error_codes=error_codes,
        )

        outcome, outcome_trace = _classify_outcome(ev)
        layer, reason_code, layer_trace = _classify_failure_layer(
            ev, outcome, error_codes, run.source
        )
        trajectory, trajectory_trace = _classify_trajectory(ev, outcome)

        rule_trace = outcome_trace + layer_trace + trajectory_trace

        return RunEvaluation(
            id=_new_id(),
            space_id=run.space_id,
            run_id=run.id,
            evaluator_type=_EVALUATOR_TYPE,
            evaluator_version=_EVALUATOR_VERSION,
            outcome_status=outcome,
            failure_layer=layer,
            failure_reason_code=reason_code,
            trajectory_status=trajectory,
            evidence_json=ev,
            rule_trace_json=rule_trace,
            evaluated_at=_utcnow(),
        )

    def _error_evaluation(self, run: Run) -> RunEvaluation:
        return RunEvaluation(
            id=_new_id(),
            space_id=run.space_id,
            run_id=run.id,
            evaluator_type=_EVALUATOR_TYPE,
            evaluator_version=_EVALUATOR_VERSION,
            outcome_status="unknown",
            failure_layer="evaluator",
            failure_reason_code="evaluator_error",
            trajectory_status="insufficient_evidence",
            evidence_json={"evaluator_error": True},
            rule_trace_json=["evaluator_error"],
            notes="Evaluation raised an internal error.",
            evaluated_at=_utcnow(),
        )
