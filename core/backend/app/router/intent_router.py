from __future__ import annotations
"""
IntentRouter — routes user input to the appropriate agent, capability, and workspace.

Current status: STUB — explicit slash-command routing only.

Today: slash-command routing
    /memory reflect       → system.memory-curator-agent + memory.reflect
    /agent run <name>     → AgentService.run(agent_name)
    /capabilities list    → CapabilityRegistry.list_capabilities()

Future: LLM-based classification
    - Embedding search to select capability
    - LLM intent classifier
    - All routes still pass through PolicyEngine before dispatch

All routing decisions must call PolicyEngine.check() before execution.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RoutingDecision:
    agent_id: Optional[str] = None
    capability_id: Optional[str] = None
    workspace_id: Optional[str] = None
    space_id: Optional[str] = None
    action: Optional[str] = None
    params: dict = field(default_factory=dict)


class IntentRouter:
    """
    Parses explicit slash commands.
    Returns None for anything that doesn't match — callers fall back to default.
    """

    def route(
        self,
        message: str,
        space_id: str,
        user_id: str,
        workspace_id: Optional[str] = None,
    ) -> Optional[RoutingDecision]:
        stripped = message.strip()
        if stripped.startswith("/"):
            return self._parse_command(stripped, space_id, workspace_id)
        return None

    def _parse_command(
        self, command: str, space_id: str, workspace_id: Optional[str]
    ) -> Optional[RoutingDecision]:
        parts = command.lstrip("/").split()
        if not parts:
            return None

        match parts:
            case ["memory", "reflect", *_]:
                return RoutingDecision(
                    agent_id="system.memory-curator-agent",
                    capability_id="memory.reflect",
                    space_id=space_id,
                    workspace_id=workspace_id,
                    action="runtime.execute",
                )
            case ["agent", "run", agent_name, *rest]:
                return RoutingDecision(
                    agent_id=agent_name,
                    space_id=space_id,
                    workspace_id=workspace_id,
                    action="runtime.execute",
                    params={"extra": rest},
                )
            case ["capabilities", "list"]:
                return RoutingDecision(
                    space_id=space_id,
                    action="capabilities.list",
                )

        return None
