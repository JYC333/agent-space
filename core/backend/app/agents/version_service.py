from datetime import datetime, UTC
from ulid import ULID
from sqlalchemy.orm import Session as DBSession
from fastapi import HTTPException

from ..models import Agent, AgentVersion
from ..schemas import AgentVersionCreate, AgentVersionOut
from ..config import settings


def _new_id() -> str:
    return str(ULID())


def _next_version_label(existing_labels: list[str]) -> str:
    """Derive the next version label from an ordered list of existing labels."""
    if not existing_labels:
        return "v1"
    # Find the highest numeric suffix
    max_n = 0
    for label in existing_labels:
        if label.startswith("v"):
            try:
                n = int(label[1:])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f"v{max_n + 1}"


class AgentVersionService:
    def __init__(self, db: DBSession):
        self.db = db

    def create(
        self,
        agent_id: str,
        space_id: str,
        data: AgentVersionCreate,
        label: str | None = None,
    ) -> AgentVersion:
        # Determine version label
        if label:
            version_label = label
        else:
            existing = self.list_for_agent(agent_id, space_id)
            version_label = _next_version_label([v.version_label for v in existing])

        version = AgentVersion(
            id=_new_id(),
            agent_id=agent_id,
            space_id=space_id,
            version_label=version_label,
            model_provider_id=data.model_provider_id,
            model_name=data.model_name,
            runtime_adapter_id=data.runtime_adapter_id,
            system_prompt=data.system_prompt,
            model_config_json=data.model_config_json,
            runtime_config_json=data.runtime_config_json,
            context_policy_json=data.context_policy_json,
            memory_policy_json=data.memory_policy_json,
            capabilities_json=data.capabilities_json,
            tool_permissions_json=data.tool_permissions_json,
            runtime_policy_json=data.runtime_policy_json,
        )
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)
        return version

    def list_for_agent(self, agent_id: str, space_id: str) -> list[AgentVersion]:
        return (
            self.db.query(AgentVersion)
            .filter(AgentVersion.agent_id == agent_id, AgentVersion.space_id == space_id)
            .order_by(AgentVersion.created_at.desc())
            .all()
        )

    def get_or_404(self, version_id: str) -> AgentVersion:
        v = self.db.query(AgentVersion).filter(AgentVersion.id == version_id).first()
        if not v:
            raise HTTPException(status_code=404, detail=f"AgentVersion '{version_id}' not found")
        return v

    def get_version_for_agent(
        self, version_id: str, agent_id: str, space_id: str
    ) -> AgentVersion:
        v = self.get_or_404(version_id)
        if v.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="AgentVersion not found for this agent")
        if v.space_id != space_id:
            raise HTTPException(status_code=404, detail="AgentVersion not found in this space")
        return v

    def _validate_version_ownership(self, version_id: str, agent_id: str, space_id: str) -> None:
        """Raise 404 if version does not belong to the given agent/space."""
        v = self.get_or_404(version_id)
        if v.agent_id != agent_id or v.space_id != space_id:
            raise HTTPException(status_code=404, detail="AgentVersion not found for this agent in this space")