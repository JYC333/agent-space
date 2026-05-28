from __future__ import annotations
"""
ContextBuilder — assembles a ContextPackage from the MemoryRetriever pipeline.

space_id and user_id are required — this builder is a hard security boundary.

Memory boundary: ContextBuilder uses space_id as a hard memory boundary. Cross-space
reads are not allowed — all memory retrieval is scoped to the provided space_id. User-private
memory inclusion is controlled by user_id: private memories are included only when
user_id matches MemoryEntry.owner_user_id. Do not add cross-space memory reads in this
module. Cross-space authorization requires PersonalMemoryGrant — see docs/PERSONAL_MEMORY_GRANT.md.

Memory retrieval is fully delegated to MemoryRetriever, which enforces hard
filters (space/scope/visibility/status/deleted_at/agent permission) before any
ranking or fallback.

Each memory injected into the package is recorded in memory_access_logs
(access_type=context_injection) and last_retrieved_at is updated.

Context attachments (file, git_diff, etc.) are resolved and security-scanned
here before being handed to ContextCompiler.
"""

import logging
import subprocess
from pathlib import Path
from sqlalchemy.orm import Session

from ..config import settings
from ..schemas import ContextPackage, MemoryOut
from .store import MemoryStore
from .serialization import memory_entry_to_out
from .access_log import record_memory_access
from .read_auth import can_read_memory, summary_only_redact_content
from .security import scan_content, scan_attachment, scan_path
from .retriever import MemoryRetriever, _assign_section

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Attachment resolvers
# ---------------------------------------------------------------------------

def _resolve_file(ref: dict, workspace_path: str | None) -> tuple[str | None, str | None]:
    """Resolve a file attachment. Returns (content, error_reason)."""
    path_str = ref.get("path", "")
    if not path_str:
        return None, "missing path"

    if scan_path(path_str):
        return None, f"path blocked by security policy: {path_str}"

    base = Path(workspace_path) if workspace_path else Path.cwd()
    try:
        target = (base / path_str).resolve()
        base_resolved = base.resolve()
        target.relative_to(base_resolved)
    except ValueError:
        return None, f"path traversal rejected: {path_str}"

    if not target.is_file():
        return None, f"file not found: {path_str}"

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return None, str(e)

    scan = scan_attachment(str(target), content)
    if not scan.passed:
        return None, f"security scan: {scan.summary()}"

    return content, None


def _resolve_file_range(ref: dict, workspace_path: str | None) -> tuple[str | None, str | None]:
    content, err = _resolve_file(ref, workspace_path)
    if err:
        return None, err
    start = max(0, int(ref.get("start", 1)) - 1)
    end = int(ref.get("end", 9999999))
    lines = (content or "").splitlines()
    selected = "\n".join(lines[start:end])
    return selected, None


def _resolve_git_diff(ref: dict, workspace_path: str | None) -> tuple[str | None, str | None]:
    base_ref = ref.get("base", "HEAD~1")
    head_ref = ref.get("head", "HEAD")
    cwd = workspace_path or "."
    try:
        result = subprocess.run(
            ["git", "diff", base_ref, head_ref],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None, f"git diff failed: {result.stderr.strip()[:200]}"
        diff = result.stdout[:8000]
        scan = scan_content(diff, source_label="git_diff")
        if not scan.passed:
            return None, f"security scan: {scan.summary()}"
        return diff, None
    except Exception as e:
        return None, str(e)


def _resolve_staged_diff(ref: dict, workspace_path: str | None) -> tuple[str | None, str | None]:
    cwd = workspace_path or "."
    try:
        result = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        diff = result.stdout[:8000]
        scan = scan_content(diff, source_label="staged_diff")
        if not scan.passed:
            return None, f"security scan: {scan.summary()}"
        return diff, None
    except Exception as e:
        return None, str(e)


def _resolve_recent_commits(ref: dict, workspace_path: str | None) -> tuple[str | None, str | None]:
    count = max(1, min(int(ref.get("count", 5)), 20))
    cwd = workspace_path or "."
    try:
        result = subprocess.run(
            ["git", "log", f"-{count}", "--oneline"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip(), None
    except Exception as e:
        return None, str(e)


def _resolve_folder_tree(ref: dict, workspace_path: str | None) -> tuple[str | None, str | None]:
    path_str = ref.get("path", ".")
    if scan_path(path_str):
        return None, f"path blocked: {path_str}"
    base = Path(workspace_path) if workspace_path else Path.cwd()
    try:
        target = (base / path_str).resolve()
        base.resolve().relative_to  # noqa — used below
        target.relative_to(base.resolve())
    except ValueError:
        return None, f"path traversal rejected: {path_str}"

    depth = int(ref.get("depth", 2))
    lines: list[str] = []

    def _walk(p: Path, indent: int) -> None:
        if indent > depth:
            return
        for child in sorted(p.iterdir()):
            if child.name.startswith(".") and indent > 0:
                continue
            prefix = "  " * indent
            if child.is_dir():
                lines.append(f"{prefix}{child.name}/")
                _walk(child, indent + 1)
            else:
                lines.append(f"{prefix}{child.name}")

    try:
        _walk(target, 0)
    except PermissionError as e:
        return None, str(e)

    return "\n".join(lines[:200]), None


# ---------------------------------------------------------------------------
# Attachment dispatch
# ---------------------------------------------------------------------------

def resolve_attachment(att: dict, workspace_path: str | None = None) -> dict:
    """
    Resolve a single ContextAttachment dict.
    Mutates a copy: sets resolved_content or marks approved=False + rejection_reason.
    """
    att = dict(att)
    att_type = att.get("attachment_type", "")
    ref = att.get("ref_json", {})

    content: str | None = None
    error: str | None = None

    if att_type == "file":
        content, error = _resolve_file(ref, workspace_path)
    elif att_type == "file_range":
        content, error = _resolve_file_range(ref, workspace_path)
    elif att_type == "folder_tree":
        content, error = _resolve_folder_tree(ref, workspace_path)
    elif att_type == "git_diff":
        content, error = _resolve_git_diff(ref, workspace_path)
    elif att_type == "staged_diff":
        content, error = _resolve_staged_diff(ref, workspace_path)
    elif att_type == "recent_commits":
        content, error = _resolve_recent_commits(ref, workspace_path)
    elif att_type == "url":
        error = "url attachments must be pre-resolved by the caller"
    elif att_type in ("memory_entry", "activity_record", "knowledge_item", "proposal", "run_artifact"):
        pass
    else:
        error = f"unknown attachment_type: {att_type}"

    if error:
        att["approved"] = False
        att["rejection_reason"] = error
    elif content is not None:
        att["resolved_content"] = content
        att["approved"] = True

    return att


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------

class ContextBuilder:
    """
    Assembles a ContextPackage using MemoryRetriever for policy-aware retrieval.

    Uses MemoryRetriever which enforces hard filters before any ranking.
    """

    def __init__(self, db: Session):
        self.db = db
        self.store = MemoryStore(db)
        self._retriever = MemoryRetriever(db)

    def _record_access(
        self,
        memories: list,
        user_id: str,
        space_id: str,
        workspace_id: str | None,
        agent_id: str | None,
        run_id: str | None,
        reason: str | None,
    ) -> None:
        """Persist memory read audit rows and bump aggregate counters."""
        if not memories:
            return
        for m in memories:
            record_memory_access(
                self.db,
                m,
                space_id=space_id,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                access_type="context_injection",
                reason=reason,
            )
        self.db.commit()

    def _to_out(self, m, *, user_id: str, space_id: str, workspace_id: str | None, include_system: bool):
        return memory_entry_to_out(
            m,
            viewer_user_id=user_id,
            space_id=space_id,
            workspace_id=workspace_id,
            include_system_scope=include_system,
        )

    def _resolve_db_attachments(
        self,
        attachments: list[dict],
        space_id: str,
        user_id: str,
        workspace_id: str | None,
        agent_id: str | None,
        run_id: str | None,
        context_reason: str | None,
    ) -> list[dict]:
        """
        Resolve DB-backed attachment types: memory_entry, activity_record, proposal.
        Other types are left for resolve_attachment() (filesystem/git).
        """
        resolved: list[dict] = []
        memory_reads: list = []
        for att in attachments:
            att = dict(att)
            att_type = att.get("attachment_type", "")
            ref = att.get("ref_json", {})

            if att_type == "memory_entry":
                memory_id = ref.get("memory_id")
                if memory_id:
                    m = self.store.get_for_space(space_id, memory_id)
                    if m and can_read_memory(
                        m,
                        user_id=user_id,
                        space_id=space_id,
                        workspace_id=workspace_id,
                        include_system_scope=(m.scope_type == "system"),
                    ):
                        if summary_only_redact_content(m, viewer_user_id=user_id):
                            body = "[summary only]"
                        else:
                            body = m.content
                        title = m.title or "(untitled)"
                        att["resolved_content"] = f"**{title}**: {body}"
                        att["label"] = att.get("label") or m.title
                        memory_reads.append(m)
                    else:
                        att["approved"] = False
                        att["rejection_reason"] = "memory not found or access denied"

            elif att_type == "activity_record":
                from ..models import ActivityRecord
                activity_id = ref.get("activity_id")
                if activity_id:
                    rec = (
                        self.db.query(ActivityRecord)
                        .filter(ActivityRecord.id == activity_id, ActivityRecord.space_id == space_id)
                        .first()
                    )
                    if rec:
                        title_part = f"**{rec.title}**: " if rec.title else ""
                        att["resolved_content"] = f"{title_part}{rec.content}"
                    else:
                        att["approved"] = False
                        att["rejection_reason"] = "activity record not found"

            resolved.append(att)
        if memory_reads:
            self._record_access(
                memory_reads,
                user_id,
                space_id,
                workspace_id,
                agent_id,
                run_id,
                context_reason,
            )
        return resolved

    def build(
        self,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        task_type: str | None = None,
        capability_id: str | None = None,
        session_id: str | None = None,
        query: str | None = None,
        # Optional: restrict retrieval to the agent's declared readable_scopes
        agent_memory_policy: dict | None = None,
        # Optional: agent performing this run (recorded in access logs)
        agent_id: str | None = None,
        run_id: str | None = None,
        context_reason: str | None = None,
        # Optional: structured context attachments
        attachments: list[dict] | None = None,
        # Optional: workspace filesystem path for attachment resolution
        workspace_path: str | None = None,
    ) -> ContextPackage:
        if not space_id:
            raise ValueError("space_id is required — context builder is a space boundary")
        if not user_id:
            raise ValueError("user_id is required — context builder requires an explicit user")

        _ = task_type  # reserved
        _ = capability_id  # reserved

        include_system_scope = (
            agent_memory_policy is None
            or "system" in (agent_memory_policy.get("readable_scopes") or [])
        )

        # ── MemoryRetriever pipeline ─────────────────────────────────────
        result = self._retriever.retrieve(
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            query=query,
            agent_memory_policy=agent_memory_policy,
            max_memories=settings.context_max_memories,
            include_system_scope=include_system_scope,
        )

        memories = result.memories
        active_policies = result.active_policies
        source_refs = list(result.source_refs)
        retrieval_trace = result.retrieval_trace
        token_budget = result.token_budget

        # ── Log access for all injected memories ────────────────────────
        self._record_access(
            memories,
            user_id,
            space_id,
            workspace_id,
            agent_id,
            run_id,
            context_reason,
        )

        # ── Serialise memories into MemoryOut objects ────────────────────
        def _to_out_list(rows, *, include_system: bool) -> list[MemoryOut]:
            out: list[MemoryOut] = []
            for m in rows:
                mo = self._to_out(
                    m,
                    user_id=user_id,
                    space_id=space_id,
                    workspace_id=workspace_id,
                    include_system=include_system,
                )
                if mo is not None:
                    out.append(mo)
            return out

        # Partition memories by scope for ContextCompiler section rendering.
        user_memory = [m for m in memories if m.scope_type == "user"]
        workspace_memory = [m for m in memories if m.scope_type == "workspace"]
        capability_memory = [m for m in memories if m.scope_type == "capability"]
        agent_memory = [m for m in memories if m.scope_type == "agent"]
        system_policy_mem = [m for m in memories if m.scope_type == "system"]
        relevant_episodes = [
            m for m in memories
            if m.memory_layer == "episodic" and m.scope_type not in ("system",)
        ]

        # ── Resolve context attachments ──────────────────────────────────
        resolved_attachments: list[dict] = []
        if attachments:
            db_resolved = self._resolve_db_attachments(
                attachments, space_id, user_id, workspace_id, agent_id, run_id, context_reason,
            )
            for att in db_resolved:
                if att.get("resolved_content") is None and att.get("approved", True):
                    att = resolve_attachment(att, workspace_path)
                resolved_attachments.append(att)

        # ── Stable prefix / dynamic tail split ──────────────────────────
        stable_prefix_refs = [r for r in source_refs if r.get("section") == "stable_prefix"]
        dynamic_tail_refs = [r for r in source_refs if r.get("section") == "dynamic_tail"]

        # Include policy refs in stable prefix refs.
        stable_prefix_refs += [r for r in source_refs if r.get("source_type") == "policy"]

        # ── Active policies as serialisable dicts ────────────────────────
        active_policy_dicts = [
            {
                "id": p.id,
                "name": p.name,
                "domain": p.domain,
                "policy_key": p.policy_key,
                "enforcement_mode": p.enforcement_mode,
                "priority": p.priority,
                "policy_json": p.policy_json,
            }
            for p in active_policies
        ]

        # ── Latest active session summary ────────────────────────────────
        recent_session_summary: list[dict] = []
        session_summary_trace: dict = {
            "session_summary_used": False,
            "session_summary_id": None,
            "session_summary_version": None,
            "session_summary_fallback_reason": None,
        }
        if session_id:
            try:
                from ..sessions.condenser import SessionCondenser
                summary = SessionCondenser(self.db).get_latest(session_id, space_id)
                if summary is not None:
                    recent_session_summary = [{
                        "summary": summary.summary_text,
                        "session_id": session_id,
                        "version": summary.version,
                        "condenser_version": summary.condenser_version,
                    }]
                    # Source ref — session_summary lives in the dynamic tail
                    summary_ref = {
                        "source_type": "session_summary",
                        "source_id": summary.id,
                        "session_id": session_id,
                        "version": summary.version,
                        "section": "dynamic_tail",
                        "derived_context": True,
                    }
                    dynamic_tail_refs.append(summary_ref)
                    source_refs.append(summary_ref)
                    session_summary_trace = {
                        "session_summary_used": True,
                        "session_summary_id": summary.id,
                        "session_summary_version": summary.version,
                        "session_summary_fallback_reason": None,
                    }
                else:
                    session_summary_trace["session_summary_fallback_reason"] = "no_active_summary"
            except Exception as exc:  # noqa: BLE001
                log.warning("ContextBuilder: session summary lookup failed: %s", exc)
                session_summary_trace["session_summary_fallback_reason"] = f"lookup_error:{type(exc).__name__}"

        retrieval_trace = dict(retrieval_trace) if retrieval_trace else {}
        retrieval_trace["session_summary"] = session_summary_trace

        return ContextPackage(
            user_memory=_to_out_list(user_memory, include_system=False),
            workspace_memory=_to_out_list(workspace_memory, include_system=False),
            capability_memory=_to_out_list(capability_memory, include_system=False),
            agent_memory=_to_out_list(agent_memory, include_system=False),
            system_policy=_to_out_list(system_policy_mem, include_system=True),
            recent_session_summary=recent_session_summary,
            relevant_episodes=_to_out_list(relevant_episodes, include_system=False),
            attachments=resolved_attachments,
            active_policies=active_policy_dicts,
            stable_prefix_refs=stable_prefix_refs,
            dynamic_tail_refs=dynamic_tail_refs,
            source_refs=source_refs,
            retrieval_trace=retrieval_trace,
            token_budget=token_budget,
        )
