from __future__ import annotations
"""
ContextCompiler — translates a ContextPackage dict into a CLI-specific instruction file.

Sits between ContextBuilder and CLI adapters:

    ContextBuilder  → ContextPackage dict
    ContextCompiler → writes CLAUDE.md / AGENTS.md / SOUL.md / etc. to sandbox dir
    CLI Adapter runs with just the task prompt

Design principles:
  - Generated files are written to the sandbox, never to the real workspace.
  - Vendor files (CLAUDE.md, AGENTS.md, SOUL.md) are ephemeral generated outputs.
    agent-space's MemoryStore + ContextBuilder are the source of truth.
  - Raw memory dumps are never emitted; only title + content per memory item.
  - Security scanning runs before any content is included.
  - Token/character budget is enforced with priority-ordered truncation.
  - Trust labels annotate the origin of each context section.
  - .agent/ docs are loaded progressively — INDEX.md always, module docs only
    when the task touches relevant files/modules.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .security import SecurityScanResult, scan_content, scan_attachment

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Character / token budget
# Approximate: 1 token ≈ 4 characters for English prose / code.
# Default budget is ~32k tokens worth of characters.
# ---------------------------------------------------------------------------

DEFAULT_BUDGET_CHARS = 128_000   # ~32k tokens

# Section priorities — lower number = higher priority = last to be dropped
_SECTION_PRIORITY = {
    "task":           0,
    "system_policy":  1,
    "user_context":   2,
    "project_docs":   3,
    "workspace":      4,
    "capability":     5,
    "agent":          6,
    "attachments":    7,
    "episodes":       8,
    "session":        9,
    "tools":          10,
    "sandbox":        11,
    "validation":     12,
    "constraints":    13,
    "output_format":  14,
}

_MAX_PER_SCOPE = 5
_MAX_EPISODES = 3
_MAX_SESSION_SUMMARIES = 2


# ---------------------------------------------------------------------------
# Sandbox hook payloads
# ---------------------------------------------------------------------------

_SANDBOX_HOOK_SCRIPT = """\
#!/usr/bin/env bash
# PostToolUse hook — injected by ContextCompiler into each sandboxed agent run.
# Reminds the agent to update .agent/ docs when structural files are modified.
set -euo pipefail
input=$(cat)
file_path=$(python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
" 2>/dev/null <<< "$input")
[[ -z "$file_path" ]] && exit 0
basename_file=$(basename "$file_path")
declare -A DOC_MAP
DOC_MAP["models.py"]="modules/space.md, modules/agents.md, modules/memory.md, modules/proposals.md, GLOSSARY.md"
DOC_MAP["schemas.py"]="modules/space.md, modules/agents.md, modules/memory.md"
DOC_MAP["runner.py"]="modules/agents.md, modules/sandbox.md"
DOC_MAP["sandbox_manager.py"]="modules/sandbox.md"
DOC_MAP["context_builder.py"]="modules/memory.md, modules/context-compiler.md"
DOC_MAP["context_compiler.py"]="modules/context-compiler.md"
DOC_MAP["agent_service.py"]="modules/agents.md"
DOC_MAP["seeder.py"]="modules/agents.md"
DOC_MAP["engine.py"]="modules/policy.md"
DOC_MAP["rules.py"]="modules/policy.md, BOUNDARIES.md"
DOC_MAP["path_policy.py"]="modules/sandbox.md, modules/workspace-console.md"
DOC_MAP["reflector.py"]="modules/memory.md, modules/proposals.md"
DOC_MAP["evolver.py"]="modules/memory.md"
DOC_MAP["proposals.py"]="modules/proposals.md, modules/memory.md"
relevant_docs="${DOC_MAP[$basename_file]:-}"
if [[ -n "$relevant_docs" ]]; then
    echo ""
    echo "DOCS SYNC: '$basename_file' edited inside sandbox."
    echo "Include in your output which .agent/ docs need updating:"
    IFS=',' read -ra docs <<< "$relevant_docs"
    for doc in "${docs[@]}"; do echo "  .agent/${doc# }"; done
    echo "(Docs in the real workspace cannot be edited from this sandbox — note them in your output.)"
fi
exit 0
"""

_SANDBOX_CLAUDE_SETTINGS = json.dumps({
    "hooks": {
        "PostToolUse": [
            {
                "matcher": "Edit|Write",
                "hooks": [{"type": "command", "command": "bash .claude/hooks/check-docs-sync.sh"}],
            }
        ]
    }
}, indent=2)


# ---------------------------------------------------------------------------
# .agent/ file map
# ---------------------------------------------------------------------------

# Files that are always loaded when present (root context)
_AGENT_ROOT_DOCS = [
    "INDEX.md",
    "ARCHITECTURE.md",
    "BOUNDARIES.md",
    "COMMANDS.md",
    "GLOSSARY.md",
]

# File-to-module mapping for progressive loading
# Key: filename pattern; Value: list of .agent/modules/*.md to load
_FILE_TO_MODULE_DOCS: dict[str, list[str]] = {
    "models.py":          ["space.md", "agents.md", "memory.md", "proposals.md"],
    "schemas.py":         ["space.md", "agents.md", "memory.md"],
    "runner.py":          ["agents.md", "sandbox.md"],
    "sandbox_manager.py": ["sandbox.md"],
    "context_builder.py": ["memory.md", "context-compiler.md"],
    "context_compiler.py":["context-compiler.md"],
    "agent_service.py":   ["agents.md"],
    "engine.py":          ["policy.md"],
    "rules.py":           ["policy.md"],
    "path_policy.py":     ["sandbox.md"],
    "reflector.py":       ["memory.md", "proposals.md"],
    "evolver.py":         ["memory.md"],
    "proposals.py":       ["proposals.md", "memory.md"],
    "activity":           ["activity-inbox.md"],
    "credentials":        ["credentials.md"],
    "capabilities":       ["capabilities.md"],
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class TargetFormat(str, Enum):
    claude    = "claude"
    codex_cli = "codex_cli"
    cursor    = "cursor"
    generic   = "generic"
    soul      = "soul"      # identity/persona file for agents that support it
    prompt    = "prompt"    # generic prompt.md for adapters with no convention


_INSTRUCTION_FILENAME: dict[TargetFormat, str] = {
    TargetFormat.claude:    "CLAUDE.md",
    TargetFormat.codex_cli: "AGENTS.md",
    TargetFormat.cursor:  ".cursorrules",
    TargetFormat.generic: "CONTEXT.md",
    TargetFormat.soul:    "SOUL.md",
    TargetFormat.prompt:  "prompt.md",
}

_VENDOR_FILE_HEADER = """\
<!-- ⚠️  GENERATED FILE — DO NOT EDIT MANUALLY
     This file is compiled from agent-space context at run start.
     Source of truth: agent-space MemoryStore + .agent/ docs.
     Changes here are NOT persisted. Use the agent-space UI to update memory.
-->

"""


@dataclass
class CompiledContext:
    task_prompt: str
    instruction_file_path: str | None
    target: TargetFormat
    total_chars: int = 0
    budget_chars: int = DEFAULT_BUDGET_CHARS
    scan_result: SecurityScanResult | None = None
    # Names of sections that were dropped to fit budget
    dropped_sections: list[str] = field(default_factory=list)

    @property
    def budget_used_pct(self) -> float:
        if not self.budget_chars:
            return 0.0
        return round(self.total_chars / self.budget_chars * 100, 1)


# ---------------------------------------------------------------------------
# ContextCompiler
# ---------------------------------------------------------------------------

class ContextCompiler:
    """
    Compiles a serialised ContextPackage into a CLI instruction file.

    Steps performed on every compile() call:
      1. Load .agent/ root docs (INDEX.md etc.) from workspace_path if present.
      2. Load relevant .agent/modules/*.md based on touched_files hint.
      3. Security-scan every memory item and attachment before inclusion.
      4. Render all sections, annotated with trust labels.
      5. Apply character budget — lowest priority sections dropped first.
      6. Write the instruction file to sandbox_dir.
      7. Write sandbox hooks.

    Usage (inside an adapter's run()):

        compiled = ContextCompiler().compile(
            context=context_package_dict,
            target=TargetFormat.claude,
            task_goal=prompt,
            sandbox_dir=self.executor.sandbox_dir,
            workspace_path="/host/workspaces/my-project",
            touched_files=["runner.py", "models.py"],
        )
    """

    def compile(
        self,
        context: dict,
        target: TargetFormat,
        task_goal: str,
        sandbox_dir: str | None = None,
        workspace_path: str | None = None,
        *,
        touched_files: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        sandbox_policy: dict | None = None,
        validation_commands: list[str] | None = None,
        constraints: list[str] | None = None,
        output_format: str | None = None,
        attachments: list[dict] | None = None,
        budget_chars: int = DEFAULT_BUDGET_CHARS,
    ) -> CompiledContext:
        """
        Compile context into an instruction file written to sandbox_dir.
        Returns a CompiledContext whose task_prompt should be passed to the CLI.
        instruction_file_path is None when sandbox_dir is omitted.
        """
        agent_docs = self._load_agent_docs(workspace_path, touched_files)

        # Security-scan all memory items before they enter the rendered output
        filtered_context, scan_result = self._scan_context(context)

        sections = self._build_sections(
            context=filtered_context,
            task_goal=task_goal,
            agent_docs=agent_docs,
            attachments=attachments or [],
            allowed_tools=allowed_tools,
            sandbox_policy=sandbox_policy,
            validation_commands=validation_commands,
            constraints=constraints,
            output_format=output_format,
        )

        markdown, dropped = self._apply_budget(sections, budget_chars)
        full_markdown = _VENDOR_FILE_HEADER + markdown
        total_chars = len(full_markdown)

        instruction_file_path: str | None = None
        if sandbox_dir:
            sandbox = Path(sandbox_dir)
            sandbox.mkdir(parents=True, exist_ok=True)

            filename = _INSTRUCTION_FILENAME[target]
            inst_path = sandbox / filename
            inst_path.write_text(full_markdown, encoding="utf-8")
            instruction_file_path = str(inst_path)

            # For claude target: also write a minimal SOUL.md (agent identity)
            if target == TargetFormat.claude:
                soul_content = self._render_soul(context)
                if soul_content:
                    (sandbox / "SOUL.md").write_text(
                        _VENDOR_FILE_HEADER + soul_content, encoding="utf-8"
                    )

            # Sandbox hooks
            hooks_dir = sandbox / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            (sandbox / ".claude" / "settings.json").write_text(
                _SANDBOX_CLAUDE_SETTINGS, encoding="utf-8"
            )
            hook_script = hooks_dir / "check-docs-sync.sh"
            hook_script.write_text(_SANDBOX_HOOK_SCRIPT, encoding="utf-8")
            hook_script.chmod(0o755)

            if scan_result and not scan_result.passed:
                log.warning(
                    "ContextCompiler security scan: %s — some items were redacted",
                    scan_result.summary(),
                )

        return CompiledContext(
            task_prompt=task_goal,
            instruction_file_path=instruction_file_path,
            target=target,
            total_chars=total_chars,
            budget_chars=budget_chars,
            scan_result=scan_result,
            dropped_sections=dropped,
        )

    # ------------------------------------------------------------------
    # .agent/ progressive loading
    # ------------------------------------------------------------------

    def _load_agent_docs(
        self,
        workspace_path: str | None,
        touched_files: list[str] | None,
    ) -> dict[str, str]:
        """
        Load .agent/ docs from workspace_path.
        Always loads root docs (INDEX.md etc.).
        Loads module-specific docs only when relevant to touched_files.
        Returns {relative_path: content} mapping.
        """
        if not workspace_path:
            return {}

        agent_dir = Path(workspace_path) / ".agent"
        if not agent_dir.is_dir():
            return {}

        docs: dict[str, str] = {}

        # Root context — always loaded
        for name in _AGENT_ROOT_DOCS:
            path = agent_dir / name
            if path.is_file():
                try:
                    docs[f".agent/{name}"] = path.read_text(encoding="utf-8")
                except OSError:
                    pass

        # context-bundles.yaml — load bundle tags if present
        bundles_path = agent_dir / "context-bundles.yaml"
        bundle_modules: set[str] = set()
        if bundles_path.is_file():
            try:
                import yaml  # type: ignore
                raw = yaml.safe_load(bundles_path.read_text(encoding="utf-8")) or {}
                for _bundle_name, bundle_def in raw.items():
                    files_in_bundle = bundle_def.get("files", [])
                    for tf in (touched_files or []):
                        if any(tf.endswith(f) for f in files_in_bundle):
                            bundle_modules.update(bundle_def.get("modules", []))
            except Exception:
                pass

        # Module-specific docs based on touched files
        relevant_modules: set[str] = set(bundle_modules)
        for tf in (touched_files or []):
            basename = Path(tf).name
            for pattern, module_docs in _FILE_TO_MODULE_DOCS.items():
                if basename == pattern or pattern in tf:
                    relevant_modules.update(module_docs)

        modules_dir = agent_dir / "modules"
        if modules_dir.is_dir():
            for mod_name in relevant_modules:
                mod_path = modules_dir / mod_name
                if mod_path.is_file():
                    try:
                        docs[f".agent/modules/{mod_name}"] = mod_path.read_text(encoding="utf-8")
                    except OSError:
                        pass

        return docs

    # ------------------------------------------------------------------
    # Security scanning
    # ------------------------------------------------------------------

    def _scan_context(
        self, context: dict
    ) -> tuple[dict, SecurityScanResult]:
        """
        Scan every memory item in the context package.
        Items that fail scanning are replaced with a redaction notice.
        Returns (cleaned_context, merged_scan_result).
        """
        all_secrets: list[str] = []
        all_injections: list[str] = []
        cleaned: dict = {}

        for section_key, items in context.items():
            if not isinstance(items, list):
                cleaned[section_key] = items
                continue

            clean_items: list = []
            for item in items:
                if not isinstance(item, dict):
                    clean_items.append(item)
                    continue

                combined = f"{item.get('title', '')} {item.get('content', '')}"
                result = scan_content(combined, source_label=item.get("id", ""))

                if result.passed:
                    clean_items.append(item)
                else:
                    all_secrets.extend(result.secrets_found)
                    all_injections.extend(result.injection_risks)
                    clean_items.append({
                        "title": item.get("title", "redacted"),
                        "content": f"[REDACTED: security scan flagged this item ({result.summary()})]",
                        "_redacted": True,
                    })

            cleaned[section_key] = clean_items

        merged = SecurityScanResult(
            passed=not all_secrets and not all_injections,
            secrets_found=list(set(all_secrets)),
            injection_risks=all_injections[:5],
        )
        return cleaned, merged

    # ------------------------------------------------------------------
    # Section building
    # ------------------------------------------------------------------

    def _build_sections(
        self,
        context: dict,
        task_goal: str,
        agent_docs: dict[str, str],
        attachments: list[dict],
        allowed_tools: list[str] | None,
        sandbox_policy: dict | None,
        validation_commands: list[str] | None,
        constraints: list[str] | None,
        output_format: str | None,
    ) -> list[tuple[str, str, int]]:
        """
        Build ordered list of (section_name, markdown_text, priority).
        Lower priority number = higher importance = last to be dropped.
        """
        sections: list[tuple[str, str, int]] = []

        def add(name: str, text: str) -> None:
            priority = _SECTION_PRIORITY.get(name, 99)
            sections.append((name, text, priority))

        # Task goal — always present
        add("task", f"# Task\n\n{task_goal}")

        # System policy
        system_text = self._render_memories(context.get("system_policy", []), trust="system")
        if system_text:
            add("system_policy", f"# System Policy\n\n{system_text}")

        # User context
        user_text = self._render_memories(context.get("user_memory", []), trust="user")
        if user_text:
            add("user_context", f"# User Context\n\n{user_text}")

        # .agent/ project docs (always-loaded root docs first, then modules)
        if agent_docs:
            doc_parts: list[str] = []
            # Root docs
            for key, content in agent_docs.items():
                if "/modules/" not in key:
                    doc_parts.append(f"### {key}\n\n{content.strip()}")
            if doc_parts:
                add("project_docs", "# Project Docs\n\n" + "\n\n---\n\n".join(doc_parts))
            # Module docs
            mod_parts: list[str] = []
            for key, content in agent_docs.items():
                if "/modules/" in key:
                    mod_parts.append(f"### {key}\n\n{content.strip()}")
            if mod_parts:
                add("project_docs", "# Module Docs\n\n" + "\n\n---\n\n".join(mod_parts))

        # Workspace + capability memories
        ws_mems = context.get("workspace_memory", []) + context.get("capability_memory", [])
        project_text = self._render_memories(ws_mems, limit=_MAX_PER_SCOPE, trust="workspace")
        if project_text:
            add("workspace", f"# Project Context\n\n{project_text}")

        # Agent memories
        agent_text = self._render_memories(context.get("agent_memory", []), trust="agent")
        if agent_text:
            add("agent", f"# Agent Context\n\n{agent_text}")

        # Context attachments
        if attachments:
            att_lines = self._render_attachments(attachments)
            if att_lines:
                add("attachments", f"# Attached Context\n\n{att_lines}")

        # Episodic memories
        episodic_text = self._render_memories(
            context.get("relevant_episodes", []),
            limit=_MAX_EPISODES,
            trust="episodic",
        )
        if episodic_text:
            add("episodes", f"# Recent Activity\n\n{episodic_text}")

        # Session summaries
        summaries = context.get("recent_session_summary", [])
        summary_items: list[str] = []
        for s in summaries[:_MAX_SESSION_SUMMARIES]:
            text = s.get("summary", "").strip() if isinstance(s, dict) else str(s).strip()
            if text:
                summary_items.append(f"- {text}")
        if summary_items:
            add("session", "# Session History\n\n" + "\n".join(summary_items))

        # Allowed tools
        if allowed_tools:
            tools_list = "\n".join(f"- {t}" for t in allowed_tools)
            add("tools", f"# Allowed Tools\n\n{tools_list}")

        # Sandbox policy
        if sandbox_policy:
            policy_lines: list[str] = []
            risk = sandbox_policy.get("risk_level", "medium")
            if risk != "low":
                policy_lines.append(f"- Running inside an isolated sandbox (risk_level={risk})")
            max_time = sandbox_policy.get("max_run_time_seconds")
            if max_time:
                policy_lines.append(f"- Time limit: {max_time}s")
            if not sandbox_policy.get("can_delegate", True):
                policy_lines.append("- Sub-agent delegation is not permitted")
            if policy_lines:
                add("sandbox", "# Sandbox Policy\n\n" + "\n".join(policy_lines))

        # Validation commands
        if validation_commands:
            cmds = "\n".join(f"- `{c}`" for c in validation_commands)
            add("validation", f"# Validation\n\nRun before finishing:\n\n{cmds}")

        # Constraints
        if constraints:
            items = "\n".join(f"- {c}" for c in constraints)
            add("constraints", f"# Constraints\n\n{items}")

        # Expected output format
        if output_format:
            add("output_format", f"# Expected Output\n\n{output_format}")

        return sections

    # ------------------------------------------------------------------
    # Budget enforcement
    # ------------------------------------------------------------------

    def _apply_budget(
        self,
        sections: list[tuple[str, str, int]],
        budget_chars: int,
    ) -> tuple[str, list[str]]:
        """
        Join sections into markdown, dropping lowest-priority sections if the
        total would exceed budget_chars.
        Returns (markdown, list_of_dropped_section_names).
        """
        # Sort by priority ascending (most important first) for budget decisions
        ordered = sorted(sections, key=lambda x: x[2])

        kept: list[tuple[str, str, int]] = []
        total = 0
        dropped: list[str] = []

        for name, text, priority in ordered:
            if total + len(text) <= budget_chars:
                kept.append((name, text, priority))
                total += len(text) + 8  # separator
            else:
                dropped.append(name)
                log.debug("ContextCompiler: dropped section %r (budget %d/%d)", name, total, budget_chars)

        if dropped:
            notice = f"\n\n> **Note:** {len(dropped)} context section(s) omitted to stay within token budget."
        else:
            notice = ""

        # Re-sort kept sections by their original priority for natural reading order
        kept_sorted = sorted(kept, key=lambda x: x[2])
        markdown = "\n\n---\n\n".join(text for _, text, _ in kept_sorted)
        return markdown + notice, dropped

    # ------------------------------------------------------------------
    # SOUL.md — agent identity / persona file
    # ------------------------------------------------------------------

    def _render_soul(self, context: dict) -> str:
        """
        Render a minimal SOUL.md from agent-scoped memories.
        Only included when there is actual agent identity content.
        """
        agent_mems = context.get("agent_memory", [])
        identity_items = [
            m for m in agent_mems
            if isinstance(m, dict) and m.get("type") in ("preference", "procedural")
        ]
        if not identity_items:
            return ""

        lines = ["# Agent Identity\n"]
        lines.append("This file describes the agent's identity and operating preferences.\n")
        for m in identity_items[:8]:
            title = (m.get("title") or "").strip()
            content = (m.get("content") or "").strip()
            if content:
                lines.append(f"- **{title}**: {content}" if title else f"- {content}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_memories(
        memories: list,
        limit: int = _MAX_PER_SCOPE,
        trust: str = "memory",
    ) -> str:
        """Render up to `limit` memory items as markdown bullets with trust labels."""
        items: list[str] = []
        for m in memories[:limit]:
            if not isinstance(m, dict):
                continue
            title = (m.get("title") or "").strip()
            content = (m.get("content") or "").strip()
            if not content:
                continue
            label = f" `[{trust}]`" if trust else ""
            if title:
                items.append(f"- **{title}**{label}: {content}")
            else:
                items.append(f"- {content}{label}")
        return "\n".join(items)

    @staticmethod
    def _render_attachments(attachments: list[dict]) -> str:
        """Render approved context attachments."""
        lines: list[str] = []
        for att in attachments:
            if not att.get("approved", True):
                reason = att.get("rejection_reason", "security policy")
                lines.append(f"- [attachment blocked: {reason}]")
                continue
            label = att.get("label") or att.get("attachment_type", "attachment")
            content = att.get("resolved_content", "").strip()
            att_type = att.get("attachment_type", "")
            if content:
                # Use fenced code block for file/diff attachments
                if att_type in ("file", "file_range", "git_diff", "staged_diff", "recent_commits"):
                    lines.append(f"**{label}** `[{att_type}]`:\n```\n{content}\n```")
                else:
                    lines.append(f"**{label}** `[{att_type}]`: {content}")
            elif att.get("ref_json"):
                ref_str = json.dumps(att["ref_json"])
                lines.append(f"- **{label}** `[{att_type}]` (unresolved): {ref_str}")
        return "\n\n".join(lines)
