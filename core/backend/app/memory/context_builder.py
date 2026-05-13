from __future__ import annotations
"""
ContextBuilder — assembles a context package from active memories.

The package is injected at the start of an agent run.
space_id and user_id are required — this builder is a hard security boundary.

If agent_memory_policy is provided, only the scopes listed in
readable_scopes are fetched; this enforces per-agent memory isolation.

Memories are filtered with ``read_auth.can_read_memory``. System policy rows are
only loaded in the explicit system branch (include_system_scope). Each memory
included in the package is recorded in ``memory_access_logs`` with
access_type ``context_injection``, and aggregate counters on ``MemoryEntry``
are updated.

Context attachments (file, git_diff, url, memory_entry, etc.) are resolved
and security-scanned here before being handed off to ContextCompiler.
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

log = logging.getLogger(__name__)

# All scopes the system knows about — in priority order
_ALL_SCOPES = ["system", "space", "user", "workspace", "capability", "agent"]


# ---------------------------------------------------------------------------
# Attachment resolvers
# ---------------------------------------------------------------------------

def _resolve_file(ref: dict, workspace_path: str | None) -> tuple[str | None, str | None]:
    """Resolve a file attachment. Returns (content, error_reason)."""
    path_str = ref.get("path", "")
    if not path_str:
        return None, "missing path"

    # Security: reject sensitive paths before touching the filesystem
    if scan_path(path_str):
        return None, f"path blocked by security policy: {path_str}"

    base = Path(workspace_path) if workspace_path else Path.cwd()
    # Resolve relative to workspace; reject any path that escapes
    try:
        target = (base / path_str).resolve()
        base_resolved = base.resolve()
        target.relative_to(base_resolved)  # raises ValueError if outside base
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

    return "\n".join(lines[:200]), None  # cap at 200 entries


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
        # URL fetching is intentionally not implemented here — callers should
        # pre-resolve URLs and pass resolved_content directly.
        error = "url attachments must be pre-resolved by the caller"
    elif att_type in ("memory_entry", "activity_record", "wiki_page", "proposal", "run_artifact"):
        # These are resolved via DB lookups in ContextBuilder, not here
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
    def __init__(self, db: Session):
        self.db = db
        self.store = MemoryStore(db)

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
                    m = self.store.get(memory_id)
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

        readable_scopes: set[str] = set(_ALL_SCOPES)
        if agent_memory_policy:
            declared = agent_memory_policy.get("readable_scopes")
            if declared is not None:
                readable_scopes = set(declared)

        max_each = settings.context_max_memories

        system_policy = []
        if "system" in readable_scopes:
            system_policy = self.store.get_by_scope(
                space_id=space_id,
                user_id=user_id,
                scope="system",
                limit=5,
            )

        user_memory = []
        if "user" in readable_scopes:
            user_memory = self.store.get_by_scope(
                space_id=space_id,
                user_id=user_id,
                scope="user",
                limit=max_each,
            )

        workspace_memory = []
        if workspace_id and "workspace" in readable_scopes:
            workspace_memory = self.store.get_by_scope(
                space_id=space_id,
                user_id=user_id,
                scope="workspace",
                workspace_id=workspace_id,
                limit=max_each,
            )

        capability_memory = []
        if capability_id and "capability" in readable_scopes:
            capability_memory = self.store.get_by_scope(
                space_id=space_id,
                user_id=user_id,
                scope="capability",
                limit=10,
            )

        agent_memory = []
        if "agent" in readable_scopes:
            agent_memory = self.store.get_by_scope(
                space_id=space_id,
                user_id=user_id,
                scope="agent",
                limit=10,
            )

        relevant_episodes = []
        if "user" in readable_scopes or "workspace" in readable_scopes:
            relevant_episodes = self.store.list(
                space_id=space_id,
                user_id=user_id,
                workspace_id=workspace_id,
                memory_type="episodic",
                limit=settings.context_max_episodes,
            )

        if query and ("user" in readable_scopes):
            search_results = self.store.search(
                query=query,
                space_id=space_id,
                user_id=user_id,
                workspace_id=workspace_id,
                limit=10,
            )
            existing_ids = {m.id for m in user_memory}
            for m in search_results:
                if m.id not in existing_ids:
                    user_memory.append(m)
                    existing_ids.add(m.id)
            user_memory = sorted(
                user_memory,
                key=lambda m: (m.importance, m.confidence),
                reverse=True,
            )[:max_each]

        _ = session_id  # reserved for future session-summary persistence (not in canonical schema yet)
        recent_summaries: list[dict] = []

        all_fetched = (
            system_policy + user_memory + workspace_memory +
            capability_memory + agent_memory + relevant_episodes
        )
        self._record_access(
            all_fetched,
            user_id,
            space_id,
            workspace_id,
            agent_id,
            run_id,
            context_reason,
        )

        def _outs(rows: list, *, include_system: bool) -> list[MemoryOut]:
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

        # Resolve context attachments
        resolved_attachments: list[dict] = []
        if attachments:
            # First pass: DB-backed types
            db_resolved = self._resolve_db_attachments(
                attachments,
                space_id,
                user_id,
                workspace_id,
                agent_id,
                run_id,
                context_reason,
            )
            # Second pass: filesystem/git types
            for att in db_resolved:
                if att.get("resolved_content") is None and att.get("approved", True):
                    att = resolve_attachment(att, workspace_path)
                resolved_attachments.append(att)

        return ContextPackage(
            user_memory=_outs(user_memory, include_system=False),
            workspace_memory=_outs(workspace_memory, include_system=False),
            capability_memory=_outs(capability_memory, include_system=False),
            agent_memory=_outs(agent_memory, include_system=False),
            system_policy=_outs(system_policy, include_system=True),
            recent_session_summary=recent_summaries,
            relevant_episodes=_outs(relevant_episodes, include_system=False),
            attachments=resolved_attachments,
        )
