from __future__ import annotations

"""AgentTemplateService — the clean Agent Template foundation.

A template is a reusable *factory*, never a runtime object. Creating an Agent
from a template copies the selected AgentTemplateVersion into a fresh, immutable
AgentVersion (copy-on-create). Template updates never mutate existing Agents.

There is no inheritance, no runtime merging, and no dynamic parent-template
lookup. No runtime / model-call path ever reads an AgentTemplate or
AgentTemplateVersion — execution always loads Agent.current_version_id →
AgentVersion.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from ..models import Agent, AgentTemplate, AgentTemplateVersion
from ..schemas import (
    AgentTemplateCreate,
    AgentTemplateVersionCreate,
    AgentVersionCreate,
    CreateAgentFromTemplate,
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _next_version_label(existing: list[str]) -> str:
    max_n = 0
    for label in existing:
        if label.startswith("v"):
            try:
                max_n = max(max_n, int(label[1:]))
            except ValueError:
                pass
    return f"v{max_n + 1}"


class AgentTemplateService:
    def __init__(self, db: DBSession):
        self.db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, template_id: str) -> AgentTemplate | None:
        return self.db.query(AgentTemplate).filter(AgentTemplate.id == template_id).first()

    def get_or_404(self, template_id: str) -> AgentTemplate:
        tpl = self.get(template_id)
        if not tpl:
            raise HTTPException(status_code=404, detail=f"AgentTemplate '{template_id}' not found")
        return tpl

    def list_visible(
        self,
        *,
        space_id: str,
        user_id: str | None = None,
        category: str | None = None,
        status: str | None = "published",
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentTemplate]:
        """Templates a caller may pick from: system_public + this space + own user templates.

        ``system_internal`` templates (the seed spec for the system-managed default
        Assistant) are never returned — they are not user-facing reusable templates.
        """
        q = self.db.query(AgentTemplate)
        from sqlalchemy import or_

        visibility_filter = or_(
            AgentTemplate.scope == "system",
            AgentTemplate.space_id == space_id,
            (AgentTemplate.owner_user_id == user_id) if user_id else False,  # type: ignore[arg-type]
        )
        q = q.filter(visibility_filter)
        q = q.filter(AgentTemplate.visibility != "system_internal")
        if category:
            q = q.filter(AgentTemplate.category == category)
        if status:
            q = q.filter(AgentTemplate.status == status)
        return q.order_by(AgentTemplate.created_at.desc()).offset(offset).limit(limit).all()

    def get_version_or_404(self, template_id: str, version_id: str) -> AgentTemplateVersion:
        v = (
            self.db.query(AgentTemplateVersion)
            .filter(
                AgentTemplateVersion.id == version_id,
                AgentTemplateVersion.template_id == template_id,
            )
            .first()
        )
        if not v:
            raise HTTPException(status_code=404, detail="AgentTemplateVersion not found for this template")
        return v

    def list_versions(self, template_id: str) -> list[AgentTemplateVersion]:
        return (
            self.db.query(AgentTemplateVersion)
            .filter(AgentTemplateVersion.template_id == template_id)
            .order_by(AgentTemplateVersion.created_at.desc())
            .all()
        )

    # ------------------------------------------------------------------
    # Template / version authoring
    # ------------------------------------------------------------------

    def create_template(
        self,
        data: AgentTemplateCreate,
        *,
        owner_user_id: str | None,
        request_space_id: str,
    ) -> AgentTemplate:
        scope = data.scope
        space_id = data.space_id or request_space_id

        if scope == "space":
            tpl_space_id, tpl_owner = space_id, None
            if not tpl_space_id:
                raise HTTPException(status_code=400, detail="space templates require a space_id")
        elif scope == "user":
            tpl_space_id, tpl_owner = None, owner_user_id
            if not tpl_owner:
                raise HTTPException(status_code=400, detail="user templates require an owner_user_id")
        else:  # pragma: no cover — schema restricts scope to space|user
            raise HTTPException(status_code=400, detail="system templates cannot be created via the API")

        tpl = AgentTemplate(
            id=_new_id(),
            key=data.key,
            name=data.name,
            description=data.description,
            category=data.category,
            scope=scope,
            space_id=tpl_space_id,
            owner_user_id=tpl_owner,
            visibility=data.visibility,
            status="draft",
        )
        self.db.add(tpl)
        self.db.flush()

        if data.initial_version is not None:
            self._add_version(tpl, data.initial_version, created_by_user_id=owner_user_id)

        self.db.commit()
        self.db.refresh(tpl)
        return tpl

    def create_template_version(
        self,
        template_id: str,
        data: AgentTemplateVersionCreate,
        *,
        created_by_user_id: str | None,
    ) -> AgentTemplateVersion:
        tpl = self.get_or_404(template_id)
        version = self._add_version(tpl, data, created_by_user_id=created_by_user_id)
        self.db.commit()
        self.db.refresh(version)
        return version

    def _add_version(
        self,
        tpl: AgentTemplate,
        data: AgentTemplateVersionCreate,
        *,
        created_by_user_id: str | None,
    ) -> AgentTemplateVersion:
        existing = [v.version for v in tpl.versions]
        label = data.version or _next_version_label(existing)
        if label in existing:
            raise HTTPException(status_code=409, detail=f"template version '{label}' already exists")
        version = AgentTemplateVersion(
            id=_new_id(),
            template_id=tpl.id,
            version=label,
            system_prompt=data.system_prompt,
            model_config_json=dict(data.model_config_json),
            context_policy_json=dict(data.context_policy_json),
            memory_policy_json=dict(data.memory_policy_json),
            tool_policy_json=dict(data.tool_policy_json),
            runtime_policy_json=dict(data.runtime_policy_json),
            output_policy_json=dict(data.output_policy_json),
            schedule_defaults_json=dict(data.schedule_defaults_json),
            output_schema_json=dict(data.output_schema_json),
            created_by_user_id=created_by_user_id,
        )
        self.db.add(version)
        self.db.flush()
        return version

    def publish_template_version(self, template_id: str, version_id: str) -> AgentTemplateVersion:
        tpl = self.get_or_404(template_id)
        version = self.get_version_or_404(template_id, version_id)
        if version.published_at is None:
            version.published_at = datetime.now(UTC)
        tpl.status = "published"
        tpl.current_version_id = version.id
        tpl.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(version)
        return version

    # ------------------------------------------------------------------
    # Copy-on-create: Agent from Template
    # ------------------------------------------------------------------

    # Hard-safety snapshots that create-from-template overrides can NEVER touch;
    # always copied verbatim from the template version.
    _LOCKED_POLICY_FIELDS = (
        "tool_policy_json",
        "runtime_policy_json",
    )

    def _resolve_default_model(
        self, space_id: str, model_config: dict
    ) -> tuple[str | None, str | None]:
        """Resolve the space's system default model into a concrete (provider_id, model).

        Returns (None, None) when no default provider is configured. An explicit
        ``model_config["model"]`` override takes precedence over the provider's
        default model; either way the chosen model is written back into model_config.
        """
        from ..models import ModelProvider
        from ..providers import _mp_is_default

        default_provider = next(
            (
                r
                for r in self.db.query(ModelProvider)
                .filter(ModelProvider.space_id == space_id, ModelProvider.enabled.is_(True))
                .all()
                if _mp_is_default(r)
            ),
            None,
        )
        if default_provider is None:
            return None, None

        model = model_config.get("model") or default_provider.default_model
        if not model:
            return default_provider.id, None
        model_config["model"] = model
        return default_provider.id, model

    def create_agent_from_template(
        self,
        template_id: str,
        *,
        version_id: str | None = None,
        overrides: CreateAgentFromTemplate | None = None,
        space_id: str,
        owner_user_id: str | None,
        agent_kind: str = "standard",
    ) -> Agent:
        from .version_service import AgentVersionService

        overrides = overrides or CreateAgentFromTemplate()
        tpl = self.get_or_404(template_id)

        # 1. Resolve the source template version (default = template.current_version_id).
        resolved_version_id = version_id or overrides.template_version_id or tpl.current_version_id
        if not resolved_version_id:
            raise HTTPException(
                status_code=400,
                detail="template has no current_version_id; publish a version or pass template_version_id",
            )
        tv = self.get_version_or_404(tpl.id, resolved_version_id)

        # The system-managed default Assistant is space/system-owned, not owned by an
        # ordinary user (owner may be None); every other agent must have a real owner.
        if agent_kind == "system_assistant":
            owner = owner_user_id
        else:
            if owner_user_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="create_agent_from_template requires owner_user_id for non-system agents",
                )
            owner = owner_user_id

        # 2. Create the Agent with provenance pointers (provenance ONLY).
        agent = Agent(
            id=_new_id(),
            space_id=space_id,
            owner_user_id=owner,
            name=overrides.name or tpl.name,
            description=overrides.description if overrides.description is not None else tpl.description,
            status="active",
            visibility="private",
            agent_kind=agent_kind,
            source_template_id=tpl.id,
            source_template_version_id=tv.id,
        )
        self.db.add(agent)
        self.db.flush()

        # 3. Copy all runtime-relevant config from the template version into a new
        #    AgentVersion snapshot. 4. Apply allowed overrides to the COPY only.
        model_config = dict(tv.model_config_json or {})
        if overrides.model_config_json:
            model_config.update(overrides.model_config_json)

        # Templates carry no hardcoded model ("system default"). Resolve the space's
        # default model provider now and stamp the concrete model + provider onto the
        # new AgentVersion. An explicit override model (model_config_json.model) wins.
        # When no default provider is configured we leave the binding empty; the
        # frontend blocks creation and prompts the user to set a default model first.
        model_provider_id, model_name = self._resolve_default_model(space_id, model_config)

        schedule_config = dict(tv.schedule_defaults_json or {})
        if overrides.schedule_config_json:
            schedule_config.update(overrides.schedule_config_json)

        system_prompt = overrides.system_prompt if overrides.system_prompt is not None else tv.system_prompt

        # Configurable policy overrides applied to the COPY only, with the same
        # safety re-stamping as the owner config edit. Tool/runtime policy is locked.
        from .policy_safety import (
            merge_context_policy_safe,
            merge_memory_policy_safe,
            merge_output_policy_safe,
        )

        context_policy = dict(tv.context_policy_json or {})
        if overrides.context_policy_json is not None:
            context_policy = merge_context_policy_safe(tv.context_policy_json, overrides.context_policy_json)

        memory_policy = dict(tv.memory_policy_json or {})
        if overrides.memory_policy_json is not None:
            memory_policy = merge_memory_policy_safe(tv.memory_policy_json, overrides.memory_policy_json)

        output_policy = dict(tv.output_policy_json or {})
        if overrides.output_policy_json is not None:
            output_policy = merge_output_policy_safe(tv.output_policy_json, overrides.output_policy_json)

        output_schema = (
            dict(overrides.output_schema_json)
            if overrides.output_schema_json is not None
            else dict(tv.output_schema_json or {})
        )

        version_data = AgentVersionCreate(
            system_prompt=system_prompt,
            model_provider_id=model_provider_id,
            model_name=model_name,
            model_config_json=model_config,
            context_policy_json=context_policy,
            memory_policy_json=memory_policy,
            output_policy_json=output_policy,
            output_schema_json=output_schema,
            # Locked hard-safety snapshots — copied verbatim, never overridable.
            tool_policy_json=dict(tv.tool_policy_json or {}),
            runtime_policy_json=dict(tv.runtime_policy_json or {}),
            schedule_config_json=schedule_config,
        )
        version = AgentVersionService(self.db).create(
            agent_id=agent.id,
            space_id=space_id,
            data=version_data,
            label="v1",
        )

        # 5. Point the Agent at its new runtime version.
        agent.current_version_id = version.id
        self.db.commit()
        self.db.refresh(agent)
        return agent
