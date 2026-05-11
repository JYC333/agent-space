"""
Shared protocol definitions for the deployer Unix socket interface.

The same file is importable by both the deployer process and the backend client.
Wire format: one JSON object per line (newline-delimited JSON).
"""
from __future__ import annotations
from typing import Literal

# ── Core deployment jobs ──────────────────────────────────────────────────────

CoreJobType = Literal[
    "rebuild_agent_space",   # docker compose build + up -d backend frontend
    "restart_agent_space",   # docker compose restart backend frontend
    "health_check",          # curl /health on backend
]

# ── Self-evolution jobs ───────────────────────────────────────────────────────

SelfEvolutionJobType = Literal[
    "init_agent_space_worktree",       # clone canonical repo into worktree dir
    "create_system_worktree",         # create a git worktree for self-evolution
    "collect_system_diff",            # collect git status/diff from worktree
    "run_system_tests",               # run allowlisted tests from worktree
    "run_test_deploy",                # deploy test compose from worktree
    "merge_approved_system_patch",    # merge approved patch into canonical repo
    "run_prod_deploy",                # deploy prod compose from canonical repo
    "cleanup_system_worktree",       # remove a self-evolution worktree
]

JobType = CoreJobType | SelfEvolutionJobType

ALLOWED_JOB_TYPES: set[str] = {
    *[v for v in CoreJobType.__args__],
    *[v for v in SelfEvolutionJobType.__args__],
}
