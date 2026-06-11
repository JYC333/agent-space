"""
ContextSnapshotPopulator — builds a ContextPackage and populates the
ContextSnapshot record bound to a Run before adapter execution.

Called by RunExecutionService immediately before the runtime adapter runs,
ensuring every executed Run has a non-empty, auditable ContextSnapshot.

Stable prefix contains: system prompt summary, active policies, core entity
facts, workspace/agent/policy_bundle digests when available.
Dynamic tail contains: task-specific episodic memory, recent activity,
current run prompt.

Both sections have their text serialised, hashed (SHA-256), and stored in
ContextSnapshot DB columns.

Digest integration:
  When active ContextDigest rows exist for the space/workspace/agent, their
  rendered content is injected into stable_prefix (before direct memory rows).
  If no digest exists, falls back to direct MemoryRetriever behaviour.
  Digest usage is recorded in source_refs_json and retrieval_trace_json for
  full auditability, including the underlying source_memory_ids/policy_ids.
"""

from __future__ import annotations

import hashlib
import json
import logging
import traceback
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from ..models import AgentVersion, ContextDigest, ContextSnapshot, Run
from ..schemas import ContextPackage
from ..memory import ContextBuilder

log = logging.getLogger(__name__)

# Compiler version tag stored in each snapshot.
# Bumped from "snapshot.v1" when ContextDigest integration was added: the
# stable_prefix format now contains [digest:<type>:v<N>] blocks when active
# digests are present, replacing the direct [policy:domain:name] rendering.
_COMPILER_VERSION = "context_digest.v1"

# Character budget for the stable prefix (≈50% of DEFAULT_BUDGET_CHARS=128k).
_STABLE_PREFIX_BUDGET_CHARS = 64_000


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _compact_json(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Digest resolution result
# ---------------------------------------------------------------------------


@dataclass
class _DigestBundle:
    """Resolved digests for a single run context."""

    policy_bundle: Optional[ContextDigest] = None
    workspace: Optional[ContextDigest] = None
    agent: Optional[ContextDigest] = None

    @property
    def used(self) -> bool:
        return any(d is not None for d in (self.policy_bundle, self.workspace, self.agent))

    @property
    def all_digests(self) -> list[ContextDigest]:
        return [d for d in (self.policy_bundle, self.workspace, self.agent) if d is not None]

    @property
    def any_dirty(self) -> bool:
        return any(d.status == "dirty" for d in self.all_digests)


def _load_digest_bundle(
    db: Session,
    *,
    space_id: str,
    workspace_id: Optional[str],
    agent_id: Optional[str],
) -> _DigestBundle:
    """Try to load active/dirty digests for the run context."""
    from ..memory import ContextDigestService

    svc = ContextDigestService(db)
    bundle = _DigestBundle()

    # Policy bundle (space-level)
    bundle.policy_bundle = svc.get_active_digest(space_id, "space", None, "policy_bundle")

    # Workspace digest
    if workspace_id:
        bundle.workspace = svc.get_active_digest(space_id, "workspace", workspace_id, "workspace")

    # Agent digest
    if agent_id:
        bundle.agent = svc.get_active_digest(space_id, "agent", agent_id, "agent")

    return bundle


# ---------------------------------------------------------------------------
# Text serialisation helpers
# ---------------------------------------------------------------------------


def _render_stable_prefix(
    pkg: ContextPackage,
    version: AgentVersion,
    digest_bundle: Optional[_DigestBundle] = None,
) -> str:
    """
    Serialise the stable part of the context.

    When digest_bundle contains active digests their rendered content is
    prepended to the stable prefix. Direct memory rows from the retriever are
    still appended for completeness.  Falls back to direct-retrieval rendering
    when no digests are present.
    """
    parts: list[str] = []

    # System prompt from AgentVersion
    if version.system_prompt:
        parts.append(f"[system_prompt]\n{version.system_prompt.strip()}")

    if digest_bundle and digest_bundle.used:
        # Inject digest content blocks.
        for digest in digest_bundle.all_digests:
            if digest.content:
                tag = f"[digest:{digest.digest_type}:v{digest.version}]"
                parts.append(f"{tag}\n{digest.content.strip()}")
    else:
        # Fallback: render active policies directly.
        for p in pkg.active_policies:
            name = p.get("name", p.get("id", "policy"))
            domain = p.get("domain", "")
            pjson = p.get("policy_json", {})
            parts.append(f"[policy:{domain}:{name}]\n{_compact_json(pjson)}")

    # Stable-section memories (always included from direct retrieval).
    stable_ids = {r["source_id"] for r in pkg.stable_prefix_refs if r.get("source_type") == "memory"}
    all_mem_sections = [
        pkg.system_policy,
        pkg.user_memory,
        pkg.workspace_memory,
        pkg.capability_memory,
        pkg.agent_memory,
    ]
    for section in all_mem_sections:
        for mo in section:
            if mo.id in stable_ids:
                title = mo.title or ""
                content = mo.content or ""
                parts.append(f"[memory:{mo.id}:{title}]\n{content}")

    text = "\n\n".join(parts)
    # Truncate to budget to keep prefix hash stable.
    return text[:_STABLE_PREFIX_BUDGET_CHARS]


def _render_dynamic_tail(pkg: ContextPackage, run: Run) -> str:
    """
    Serialise the dynamic part: episodic memories, run prompt.
    """
    parts: list[str] = []

    dynamic_ids = {r["source_id"] for r in pkg.dynamic_tail_refs if r.get("source_type") == "memory"}
    for mo in pkg.relevant_episodes:
        if mo.id in dynamic_ids or not dynamic_ids:
            title = mo.title or ""
            content = mo.content or ""
            parts.append(f"[episode:{mo.id}:{title}]\n{content}")

    if run.prompt:
        parts.append(f"[prompt]\n{run.prompt.strip()}")

    for ev in getattr(pkg, "evidence_items", []) or []:
        title = ev.get("title") or ev.get("id") or "evidence"
        excerpt = ev.get("content_excerpt") or ""
        if excerpt:
            parts.append(f"[evidence:{ev.get('id')}:{title}]\n{excerpt}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# ContextSnapshotPopulator
# ---------------------------------------------------------------------------


class ContextSnapshotPopulator:
    """
    Populates the ContextSnapshot bound to a Run before execution.

    Usage (inside RunExecutionService, before adapter.execute()):

        pkg = ContextSnapshotPopulator(db).populate(run, version)
        # pkg is available if the adapter needs structured context

    The ContextSnapshot DB row is updated in-place (flush, not commit).
    The caller owns the commit boundary.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def populate(
        self,
        run: Run,
        version: AgentVersion,
    ) -> ContextPackage:
        """
        Build ContextPackage, populate ContextSnapshot, return the package.

        The ContextSnapshot is updated in-place (flush only).
        Tries to load active ContextDigests for stable_prefix injection.
        Falls back to direct MemoryRetriever behaviour if no digests exist.
        """
        user_id = run.instructed_by_user_id or "system"
        workspace_id = run.workspace_id

        agent_memory_policy = dict(version.memory_policy_json or {})

        # Policy gate: context.inject_memory — batch-level check before any memory
        # is retrieved and injected into the context package.
        # Does not log memory content; safe metadata only.
        # Decision inputs go in context; audit-only identifiers stay in metadata_json.
        from ..policy import PolicyGateway, PolicyCheckRequest
        PolicyGateway(self.db).enforce(
            PolicyCheckRequest(
                action="context.inject_memory",
                actor_type="run",
                actor_id=str(run.id),
                space_id=run.space_id,
                resource_type="memory",
                run_id=str(run.id),
                context={
                    "trigger_origin": getattr(run, "trigger_origin", "manual") or "manual",
                },
                metadata_json={
                    "agent_id": str(run.agent_id) if run.agent_id else None,
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "data_exposure_level": run.data_exposure_level,
                    "trust_level": run.trust_level,
                    "has_personal_grant_context": bool(
                        getattr(run, "has_personal_grant_context", False)
                    ),
                },
            )
        )

        builder = ContextBuilder(self.db)
        pkg = builder.build(
            space_id=run.space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=run.project_id,
            session_id=run.session_id or None,
            agent_id=run.agent_id,
            run_id=run.id,
            query=run.prompt or None,
            agent_memory_policy=agent_memory_policy or None,
            context_reason=f"run_execution:{run.id}",
        )

        # ── Load digest bundle (best-effort; missing digest = fallback) ──
        _digest_load_error: Optional[str] = None
        try:
            digest_bundle = _load_digest_bundle(
                self.db,
                space_id=run.space_id,
                workspace_id=workspace_id,
                agent_id=run.agent_id,
            )
        except Exception as exc:  # noqa: BLE001
            _digest_load_error = f"{type(exc).__name__}: {exc}"
            log.warning(
                "Run %s: digest load raised unexpected error — falling back to direct retrieval: %s\n%s",
                run.id,
                _digest_load_error,
                traceback.format_exc(),
            )
            digest_bundle = None

        # ── Serialise prefix / tail ──────────────────────────────────────
        stable_text = _render_stable_prefix(pkg, version, digest_bundle)
        tail_text = _render_dynamic_tail(pkg, run)

        prefix_hash = _sha256_text(stable_text)
        tail_hash = _sha256_text(tail_text)

        # ── Token budget accounting ──────────────────────────────────────
        # Target: stable_prefix <= 50% of total context.
        # This is recorded as an audit metric only; truncation/digest enforcement
        # is not yet implemented.  When the prefix exceeds the target a warning is
        # written into token_budget_json so operators can detect the condition.
        stable_chars = len(stable_text)
        tail_chars = len(tail_text)
        total_chars = stable_chars + tail_chars
        stable_prefix_pct = round(stable_chars / max(total_chars, 1) * 100, 1)
        _STABLE_PREFIX_TARGET_PCT = 50.0
        token_budget: dict = {
            "stable_prefix_chars": stable_chars,
            "dynamic_tail_chars": tail_chars,
            "total_chars": total_chars,
            "stable_prefix_budget_chars": _STABLE_PREFIX_BUDGET_CHARS,
            "stable_prefix_pct": stable_prefix_pct,
            "stable_prefix_target_pct": _STABLE_PREFIX_TARGET_PCT,
            "compiler_version": _COMPILER_VERSION,
        }
        if stable_prefix_pct > _STABLE_PREFIX_TARGET_PCT:
            token_budget["stable_prefix_warning"] = (
                f"stable_prefix occupies {stable_prefix_pct}% of total context "
                f"(target <= {_STABLE_PREFIX_TARGET_PCT}%); "
                "truncation and digest-based compaction are not yet implemented"
            )
            log.debug(
                "Run %s: stable_prefix_pct=%.1f%% exceeds target %.1f%%",
                run.id,
                stable_prefix_pct,
                _STABLE_PREFIX_TARGET_PCT,
            )

        # ── Build digest source refs and trace ──────────────────────────
        source_refs = list(pkg.source_refs)

        # Default trace for the no-digest path — distinguish missing vs error.
        if _digest_load_error:
            digest_trace: dict = {
                "digest_used": False,
                "fallback_to_memory_retriever": True,
                "digest_fallback_reason": "load_error",
                "digest_load_error": _digest_load_error,
            }
        else:
            digest_trace = {
                "digest_used": False,
                "fallback_to_memory_retriever": True,
                "digest_fallback_reason": "no_digest_available",
            }

        if digest_bundle and digest_bundle.used:
            digest_ids: list[str] = []
            digest_types: list[str] = []
            digest_versions: list[int] = []

            for digest in digest_bundle.all_digests:
                digest_ids.append(digest.id)
                digest_types.append(digest.digest_type)
                digest_versions.append(digest.version)

                source_refs.append({
                    "source_type": "context_digest",
                    "source_id": digest.id,
                    "digest_type": digest.digest_type,
                    "digest_version": digest.version,
                    "section": "stable_prefix",
                    "source_memory_ids": digest.source_memory_ids_json or [],
                    "source_policy_ids": digest.source_policy_ids_json or [],
                    "source_relation_ids": digest.source_relation_ids_json or [],
                    "source_hash": digest.source_hash,
                    "content_hash": digest.content_hash,
                    "status": digest.status,
                })

            digest_trace = {
                "digest_used": True,
                "digest_ids": digest_ids,
                "digest_types": digest_types,
                "digest_versions": digest_versions,
                "dirty_digest_used": digest_bundle.any_dirty,
                "fallback_to_memory_retriever": False,
                "digest_fallback_reason": None,
            }

        # ── Update retrieval trace with final budget decision ────────────
        retrieval_trace = dict(pkg.retrieval_trace)
        retrieval_trace["token_budget"] = token_budget
        retrieval_trace.update(digest_trace)

        # ── PersonalMemoryGrant resolution ───────────────────────────────
        # Resolve any valid grant for this run.  The returned personal_context_block
        # is ephemeral — it is attached to the in-memory pkg only and MUST NOT be
        # written to compiled_prefix_text, compiled_tail_text, source_refs_json,
        # or any shared artifact.  Only safe grant metadata is added to source_refs.
        from ..personal_memory_grants.resolver import resolve_personal_memory_context_for_run

        grant_result = resolve_personal_memory_context_for_run(self.db, run=run)

        if grant_result.has_personal_context:
            pkg.personal_context_block = grant_result.personal_context_block
            # Add ONLY safe metadata to source_refs (no raw content, no memory IDs,
            # no generated summary text).
            source_refs.append({
                "source_type": "personal_memory_grant",
                "grant_id": grant_result.grant_metadata["grant_id"],
                "granting_user_id": grant_result.grant_metadata["granting_user_id"],
                "personal_space_id": grant_result.grant_metadata["personal_space_id"],
                "target_space_id": grant_result.grant_metadata["target_space_id"],
                "access_mode": grant_result.grant_metadata["access_mode"],
                "memory_count": grant_result.grant_metadata["memory_count"],
                "raw_memory_included": False,
                "personal_summary_persisted": False,
                "section": "ephemeral",
            })
            retrieval_trace["personal_memory_grant"] = {
                "grant_id": grant_result.grant_metadata["grant_id"],
                "access_mode": grant_result.grant_metadata["access_mode"],
                "memory_count": grant_result.grant_metadata["memory_count"],
                "raw_memory_included": False,
                "personal_summary_persisted": False,
            }

            # Persist safe run-level marker so egress guard can detect grant-derived
            # output without re-reading personal memory.  Only safe metadata (no raw content,
            # no generated summary, no memory IDs) is stored.
            from sqlalchemy.orm.attributes import flag_modified
            run.has_personal_grant_context = True
            run.personal_grant_context_json = grant_result.grant_metadata
            flag_modified(run, "personal_grant_context_json")
            self.db.flush()
        else:
            retrieval_trace["personal_memory_grant"] = None

        # ── Populate ContextSnapshot ─────────────────────────────────────
        snap = (
            self.db.query(ContextSnapshot)
            .filter(ContextSnapshot.id == run.context_snapshot_id)
            .first()
        ) if run.context_snapshot_id else None

        if snap is None:
            raise RuntimeError(
                f"Run {run.id} has no ContextSnapshot (context_snapshot_id="
                f"{run.context_snapshot_id!r}); cannot audit run context — "
                "execution blocked to preserve auditability invariant"
            )

        snap.compiled_prefix_text = stable_text
        snap.compiled_tail_text = tail_text
        snap.prefix_hash = prefix_hash
        snap.tail_hash = tail_hash
        snap.source_refs_json = source_refs
        snap.included_evidence_refs_json = [
            r for r in source_refs if r.get("source_type") == "evidence"
        ]
        snap.retrieval_trace_json = [retrieval_trace]
        snap.token_budget_json = token_budget
        snap.compiler_version = _COMPILER_VERSION
        snap.token_estimate = total_chars // 4  # ~4 chars/token approximation

        # Record digest version tags for query-time auditability.
        if digest_bundle:
            if digest_bundle.policy_bundle:
                snap.policy_bundle_version = str(digest_bundle.policy_bundle.version)
            if digest_bundle.workspace:
                snap.workspace_digest_version = str(digest_bundle.workspace.version)

        self.db.add(snap)
        self.db.flush()

        return pkg
