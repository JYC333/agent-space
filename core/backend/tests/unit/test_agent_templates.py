"""Agent Template foundation: factory model, copy-on-create, immutability, seeds.

A template is a reusable factory. Creating an Agent copies the selected
AgentTemplateVersion into a new AgentVersion (copy-on-create). Template updates
never silently change existing Agents. Runtime always loads from AgentVersion.

Also asserts the seeded system catalog (no ``general_chat``; chat is the
``personal_assistant`` agent) and the per-template policy guarantees.
"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy.exc import IntegrityError

from app.agents.template_seeder import seed_system_templates
from app.agents.template_service import AgentTemplateService
from app.models import Agent, AgentTemplate, AgentTemplateVersion, AgentVersion
from app.schemas import (
    AgentTemplateCreate,
    AgentTemplateVersionCreate,
    CreateAgentFromTemplate,
)
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID

SPACE = PERSONAL_SPACE_ID
USER = DEFAULT_USER_ID

# The exact initial system catalog. general_chat is intentionally NOT seeded —
# chat is represented by the personal_assistant agent.
SYSTEM_KEYS = {
    "personal_assistant",
    "activity_reflector",
    "memory_reflector",
    "knowledge_curator",
    "research_reader",
    "coding_reviewer",
}

EXPECTED_META = {
    # personal_assistant is the internal seed spec for the system-managed default
    # Assistant — system_internal, hidden from the public Template Library.
    "personal_assistant": ("assistant", "system_internal", "published"),
    "activity_reflector": ("reflection", "system_public", "published"),
    "memory_reflector": ("memory", "system_public", "published"),
    "knowledge_curator": ("knowledge", "system_public", "published"),
    "research_reader": ("research", "system_public", "published"),
    "coding_reviewer": ("workspace", "system_public", "published"),
}


def _get_system_template(db, key: str) -> AgentTemplate:
    return (
        db.query(AgentTemplate)
        .filter(AgentTemplate.scope == "system", AgentTemplate.key == key)
        .one()
    )


def _version(db, template: AgentTemplate) -> AgentTemplateVersion:
    return db.query(AgentTemplateVersion).filter(
        AgentTemplateVersion.id == template.current_version_id
    ).one()


def _current_version(db, agent: Agent) -> AgentVersion:
    return db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()


# ---------------------------------------------------------------------------
# 1. System templates seed idempotently; exactly the intended set; no general_chat
# ---------------------------------------------------------------------------

def test_system_templates_seed_idempotently(db):
    created_first = seed_system_templates(db)
    assert created_first == len(SYSTEM_KEYS)

    created_again = seed_system_templates(db)
    assert created_again == 0

    keys = {t.key for t in db.query(AgentTemplate).filter(AgentTemplate.scope == "system").all()}
    assert keys == SYSTEM_KEYS
    assert "general_chat" not in keys


def test_seeded_templates_have_expected_metadata(db):
    seed_system_templates(db)
    for key, (category, visibility, status) in EXPECTED_META.items():
        tpl = _get_system_template(db, key)
        assert tpl.category == category, key
        assert tpl.scope == "system", key
        assert tpl.visibility == visibility, key
        assert tpl.status == status, key
        assert tpl.space_id is None and tpl.owner_user_id is None, key
        assert tpl.current_version_id is not None, key


def test_every_template_uses_allowed_output_types(db):
    """Output config uses allowed_output_types — never the misleading default_outputs."""
    seed_system_templates(db)
    for key in SYSTEM_KEYS:
        out = _version(db, _get_system_template(db, key)).output_policy_json
        assert "allowed_output_types" in out, key
        assert isinstance(out["allowed_output_types"], list) and out["allowed_output_types"], key
        assert "default_outputs" not in out, key
        assert "allowed_outputs" not in out, key


# ---------------------------------------------------------------------------
# 2. Copy-on-create: AgentVersion gets a verbatim snapshot of the template version
# ---------------------------------------------------------------------------

def test_create_agent_from_template_copies_snapshot(db):
    seed_system_templates(db)
    tpl = _get_system_template(db, "personal_assistant")
    tv = _version(db, tpl)

    svc = AgentTemplateService(db)
    agent = svc.create_agent_from_template(tpl.id, space_id=SPACE, owner_user_id=USER)

    assert agent.source_template_id == tpl.id
    assert agent.source_template_version_id == tv.id
    assert agent.current_version_id is not None

    av = _current_version(db, agent)
    assert av.system_prompt == tv.system_prompt
    assert av.model_config_json == tv.model_config_json
    assert av.tool_policy_json == tv.tool_policy_json
    assert av.memory_policy_json == tv.memory_policy_json
    assert av.context_policy_json == tv.context_policy_json
    assert av.runtime_policy_json == tv.runtime_policy_json
    assert av.output_policy_json == tv.output_policy_json
    assert av.schedule_config_json == tv.schedule_defaults_json


def test_create_agent_from_template_defaults_to_current_version(db):
    seed_system_templates(db)
    tpl = _get_system_template(db, "personal_assistant")
    agent = AgentTemplateService(db).create_agent_from_template(
        tpl.id, space_id=SPACE, owner_user_id=USER
    )
    assert agent.source_template_version_id == tpl.current_version_id


# ---------------------------------------------------------------------------
# 3. Updating a template does not mutate existing Agents / AgentVersions
# ---------------------------------------------------------------------------

def test_template_update_does_not_mutate_existing_agent(db):
    seed_system_templates(db)
    tpl = _get_system_template(db, "personal_assistant")
    svc = AgentTemplateService(db)

    agent = svc.create_agent_from_template(tpl.id, space_id=SPACE, owner_user_id=USER)
    original_prompt = _current_version(db, agent).system_prompt
    original_version_id = agent.current_version_id

    v2 = svc.create_template_version(
        tpl.id,
        AgentTemplateVersionCreate(system_prompt="COMPLETELY DIFFERENT PROMPT v2"),
        created_by_user_id=USER,
    )
    svc.publish_template_version(tpl.id, v2.id)

    db.refresh(agent)
    assert agent.current_version_id == original_version_id
    assert _current_version(db, agent).system_prompt == original_prompt


def test_runtime_does_not_read_templates(db):
    """No runtime / model-call path may reference AgentTemplate(Version)."""
    backend = pathlib.Path(__file__).resolve().parents[2]
    for rel in ("app/runs/execution.py", "app/runs/policy_inputs.py"):
        src = (backend / rel).read_text()
        assert "AgentTemplate" not in src, f"{rel} must not read AgentTemplate at runtime"


def test_agent_version_is_self_contained_after_template_deleted(db):
    seed_system_templates(db)
    tpl = _get_system_template(db, "personal_assistant")
    svc = AgentTemplateService(db)
    agent = svc.create_agent_from_template(tpl.id, space_id=SPACE, owner_user_id=USER)
    snapshot_prompt = _current_version(db, agent).system_prompt

    db.delete(_get_system_template(db, "personal_assistant"))
    db.commit()
    db.refresh(agent)

    assert agent.source_template_id is None
    assert _current_version(db, agent).system_prompt == snapshot_prompt


# ---------------------------------------------------------------------------
# 4-10. Per-template policy guarantees
# ---------------------------------------------------------------------------

def test_personal_assistant_dynamic_context_no_durable_writes(db):
    """Personal Assistant allows dynamic context categories but no direct durable writes."""
    seed_system_templates(db)
    tv = _version(db, _get_system_template(db, "personal_assistant"))
    ctx = tv.context_policy_json
    out = tv.output_policy_json

    # Dynamic per-run context selection inside a fixed ceiling.
    assert ctx["dynamic_selection"] is True
    allowed = set(ctx["allowed_input_contexts"])
    assert {"approved_memory", "knowledge_items", "sources", "recent_activities",
            "tasks", "ideas", "projects", "workspace_metadata", "recent_runs",
            "recent_proposals", "manual_context"} == allowed
    assert set(ctx["default_input_contexts"]) <= allowed
    assert {"approved_memory", "knowledge_items", "recent_activities"} <= set(ctx["default_input_contexts"])

    # chat is the usual output; structured outputs are proposal-only.
    assert "chat_message" in out["allowed_output_types"]
    assert set(out["allowed_output_types"]) == {
        "chat_message", "task_create_proposal", "idea_create_proposal",
        "memory_update_proposal", "knowledge_item_proposal", "noop",
    }
    assert out["proposal_only"] is True
    # No direct durable writes anywhere.
    assert tv.memory_policy_json["writable_scopes"] == []
    assert tv.memory_policy_json["requires_proposal"] is True
    tool = tv.tool_policy_json
    assert tool["shell"] is False and tool["file_write"] is False
    assert tool["workspace_write"] is False and tool["credential_access"] is False


def test_activity_reflector_model_selected_classification(db):
    """Activity Reflector: model-selected classification, proposal-only durable outputs."""
    seed_system_templates(db)
    tv = _version(db, _get_system_template(db, "activity_reflector"))
    out = tv.output_policy_json

    assert out["classification_mode"] == "model_selects"
    assert out["proposal_only"] is True
    assert out["allow_multiple_outputs_per_run"] is True
    # A single activity should normally produce at most one primary output.
    assert out["allow_multiple_outputs_per_activity"] is False
    # Reflection summary may be required at run level.
    assert "reflection_summary_artifact" in out["required_run_outputs"]
    assert set(out["allowed_output_types"]) == {
        "task_create_proposal", "idea_create_proposal", "memory_update_proposal",
        "knowledge_item_proposal", "reflection_summary_artifact", "archive_suggestion", "noop",
    }
    # Durable changes are proposal-only — no direct memory write, model-only (no tools).
    assert tv.memory_policy_json["writable_scopes"] == []
    assert tv.tool_policy_json["allowed_tools"] == []
    assert tv.tool_policy_json["shell"] is False
    # Daily default schedule defined but disabled; manual runs allowed.
    assert tv.schedule_defaults_json["enabled"] is False
    assert tv.schedule_defaults_json["manual_run_allowed"] is True


def test_memory_reflector_cannot_write_memory(db):
    """Memory Reflector cannot directly write/merge/delete memory — proposals only."""
    seed_system_templates(db)
    tv = _version(db, _get_system_template(db, "memory_reflector"))
    out = tv.output_policy_json

    assert out["proposal_only"] is True
    assert set(out["allowed_output_types"]) == {
        "memory_update_proposal", "memory_merge_proposal", "memory_delete_proposal", "noop",
    }
    # No direct write — long-term changes are proposal-only.
    assert tv.memory_policy_json["writable_scopes"] == []
    assert tv.memory_policy_json["requires_proposal"] is True
    # Reads approved memory + selected activities/conversations per context policy.
    allowed = set(tv.context_policy_json["allowed_input_contexts"])
    assert {"existing_approved_memory", "selected_activities", "selected_conversations"} <= allowed
    assert tv.tool_policy_json["allowed_tools"] == []


def test_knowledge_curator_no_dedicated_source_or_answer_proposal_types(db):
    """Knowledge Curator emits no dedicated source/answer proposal output types.

    ``source`` is not a KnowledgeItem type at all (it is the Source table).
    ``answer`` *is* a canonical KnowledgeItem type, but it is created through the
    generic ``knowledge_item_proposal`` output (item_type=answer), never a special
    ``answer_create_proposal`` output type.
    """
    seed_system_templates(db)
    tv = _version(db, _get_system_template(db, "knowledge_curator"))
    types = set(tv.output_policy_json["allowed_output_types"])

    # No dedicated source/answer create proposal output types exist.
    assert "source_create_proposal" not in types
    assert "answer_create_proposal" not in types
    assert not any("source_create" in t for t in types)
    assert not any("answer" in t for t in types)
    # Relations and source links are the sanctioned representations.
    assert "knowledge_item_relation_create_proposal" in types
    assert "knowledge_item_source_link_proposal" in types
    assert tv.output_policy_json["proposal_only"] is True


def test_research_reader_no_web_search_or_crawl(db):
    """Research Reader has no web search / crawling by default; proposal-only durables."""
    seed_system_templates(db)
    tv = _version(db, _get_system_template(db, "research_reader"))
    tool = tv.tool_policy_json

    assert tool["web_search"] is False
    assert tool["crawl"] is False
    assert tool["allowed_tools"] == []
    # Reads only the selected sources.
    assert "selected_sources" in tv.context_policy_json["allowed_input_contexts"]
    assert tv.output_policy_json["proposal_only"] is True
    assert "source_summary_artifact" in tv.output_policy_json["allowed_output_types"]


def test_coding_reviewer_is_read_only(db):
    """Coding Reviewer is read-only: no file write, no shell, no patch apply."""
    seed_system_templates(db)
    tv = _version(db, _get_system_template(db, "coding_reviewer"))
    tool = tv.tool_policy_json

    assert tool["file_write"] is False
    assert tool["workspace_write"] is False
    assert tool["shell"] is False
    assert tool["patch_apply"] is False
    assert tool["workspace_read"] is True
    # Review/report style outputs only — no code patch output by default.
    types = set(tv.output_policy_json["allowed_output_types"])
    assert types == {
        "review_report_artifact", "architecture_risk_summary",
        "code_change_suggestion", "task_create_proposal", "noop",
    }
    assert not any("patch" in t for t in types)


# ---------------------------------------------------------------------------
# 11-13. Overrides apply to the copy only and cannot bypass hard policy defaults
# ---------------------------------------------------------------------------

def test_overrides_apply_to_copy_only(db):
    seed_system_templates(db)
    tpl = _get_system_template(db, "personal_assistant")
    tv = _version(db, tpl)
    original_tool_policy = dict(tv.tool_policy_json)

    svc = AgentTemplateService(db)
    agent = svc.create_agent_from_template(
        tpl.id,
        overrides=CreateAgentFromTemplate(
            name="My Assistant",
            system_prompt="override prompt",
            model_config_json={"temperature": 0.2},
        ),
        space_id=SPACE,
        owner_user_id=USER,
    )

    assert agent.name == "My Assistant"
    av = _current_version(db, agent)
    assert av.system_prompt == "override prompt"
    assert av.model_config_json["temperature"] == 0.2
    # Hard policy default not bypassable: tool policy is the template's, unchanged.
    assert av.tool_policy_json == original_tool_policy

    db.refresh(tv)
    assert tv.tool_policy_json == original_tool_policy
    assert tv.system_prompt != "override prompt"


def test_template_update_does_not_mutate_existing_agent_version(db):
    """Republishing a template version leaves an already-created AgentVersion untouched."""
    seed_system_templates(db)
    tpl = _get_system_template(db, "memory_reflector")
    svc = AgentTemplateService(db)

    agent = svc.create_agent_from_template(tpl.id, space_id=SPACE, owner_user_id=USER)
    original_version_id = agent.current_version_id
    original_outputs = set(_current_version(db, agent).output_policy_json["allowed_output_types"])

    v2 = svc.create_template_version(
        tpl.id,
        AgentTemplateVersionCreate(
            system_prompt="v2",
            output_policy_json={"proposal_only": True, "allowed_output_types": ["memory_update_proposal"]},
        ),
        created_by_user_id=USER,
    )
    svc.publish_template_version(tpl.id, v2.id)

    db.refresh(agent)
    assert agent.current_version_id == original_version_id
    assert set(_current_version(db, agent).output_policy_json["allowed_output_types"]) == original_outputs


def test_frontend_override_cannot_bypass_hard_safety(db):
    """An override cannot expand allowed outputs/contexts, drop proposal_only, or grant memory write."""
    seed_system_templates(db)
    tpl = _get_system_template(db, "personal_assistant")
    svc = AgentTemplateService(db)

    agent = svc.create_agent_from_template(
        tpl.id,
        overrides=CreateAgentFromTemplate(
            # Attempt to add a disallowed output type + disable proposal-only.
            output_policy_json={
                "proposal_only": False,
                "allowed_output_types": ["chat_message", "shell_exec", "memory_update_proposal"],
            },
            # Attempt to grant direct memory write.
            memory_policy_json={"writable_scopes": ["user"], "requires_proposal": False},
            # Attempt to expand the input-context ceiling.
            context_policy_json={
                "allowed_input_contexts": ["approved_memory", "secret_vault"],
                "default_input_contexts": ["approved_memory", "secret_vault"],
            },
        ),
        space_id=SPACE,
        owner_user_id=USER,
    )
    av = _current_version(db, agent)

    # Output ceiling clamped to the template's set; proposal_only re-stamped.
    assert "shell_exec" not in av.output_policy_json["allowed_output_types"]
    assert av.output_policy_json["proposal_only"] is True
    # Memory write cannot be granted; proposal requirement cannot be dropped.
    assert av.memory_policy_json["writable_scopes"] == []
    assert av.memory_policy_json["requires_proposal"] is True
    # Input-context ceiling cannot be expanded.
    assert "secret_vault" not in av.context_policy_json["allowed_input_contexts"]
    assert "secret_vault" not in av.context_policy_json["default_input_contexts"]


def test_create_from_template_stamps_system_default_model(db):
    """Templates use the system default model; create-from-template resolves it to a
    concrete provider + model on the new AgentVersion, while the template stays model-less."""
    from tests.support import factories

    seed_system_templates(db)
    tpl = _get_system_template(db, "personal_assistant")
    tv = _version(db, tpl)
    assert "model" not in (tv.model_config_json or {})

    provider = factories.create_test_model_provider(
        db, space_id=SPACE, is_default=True, default_model="claude-sonnet-4-6", commit=True
    )

    agent = AgentTemplateService(db).create_agent_from_template(
        tpl.id, space_id=SPACE, owner_user_id=USER
    )
    av = _current_version(db, agent)
    assert av.model_provider_id == provider.id
    assert av.model_name == "claude-sonnet-4-6"
    assert av.model_config_json["model"] == "claude-sonnet-4-6"
    db.refresh(tv)
    assert "model" not in (tv.model_config_json or {})


def test_create_from_template_without_published_version_fails(db):
    svc = AgentTemplateService(db)
    tpl = svc.create_template(
        AgentTemplateCreate(key="draft_only", name="Draft", scope="user"),
        owner_user_id=USER,
        request_space_id=SPACE,
    )
    assert tpl.current_version_id is None
    with pytest.raises(Exception):
        svc.create_agent_from_template(tpl.id, space_id=SPACE, owner_user_id=USER)


# ---------------------------------------------------------------------------
# Default Personal Assistant resolution (chat is an agent, not naked DirectChat)
# ---------------------------------------------------------------------------

def test_default_personal_assistant_resolve_or_create_is_idempotent(db):
    from app.agents.personal_assistant import (
        ensure_default_personal_assistant,
        resolve_default_personal_assistant,
    )

    seed_system_templates(db)
    # Nothing resolves before one is created.
    assert resolve_default_personal_assistant(db, space_id=SPACE) is None

    a1 = ensure_default_personal_assistant(db, space_id=SPACE, owner_user_id=USER)
    a2 = ensure_default_personal_assistant(db, space_id=SPACE, owner_user_id=USER)
    assert a1.id == a2.id  # idempotent

    tpl = _get_system_template(db, "personal_assistant")
    assert a1.source_template_id == tpl.id
    assert resolve_default_personal_assistant(db, space_id=SPACE).id == a1.id


# ---------------------------------------------------------------------------
# Scope constraints for system / user / space templates are enforced
# ---------------------------------------------------------------------------

def _expect_integrity_error(db, obj) -> None:
    sp = db.begin_nested()
    db.add(obj)
    with pytest.raises(IntegrityError):
        db.flush()
    sp.rollback()


def test_scope_constraint_system_requires_no_owner_or_space(db):
    bad = AgentTemplate(
        key="bad_system", name="Bad", scope="system",
        space_id=SPACE, owner_user_id=None,
        visibility="system_public", status="draft",
    )
    _expect_integrity_error(db, bad)


def test_scope_constraint_user_requires_owner(db):
    bad = AgentTemplate(
        key="bad_user", name="Bad", scope="user",
        space_id=None, owner_user_id=None,
        visibility="private", status="draft",
    )
    _expect_integrity_error(db, bad)


def test_scope_constraint_space_requires_space(db):
    bad = AgentTemplate(
        key="bad_space", name="Bad", scope="space",
        space_id=None, owner_user_id=USER,
        visibility="space_shared", status="draft",
    )
    _expect_integrity_error(db, bad)


def test_user_template_key_unique_within_scope(db):
    svc = AgentTemplateService(db)
    svc.create_template(
        AgentTemplateCreate(key="dup", name="One", scope="user"),
        owner_user_id=USER, request_space_id=SPACE,
    )
    with pytest.raises(IntegrityError):
        svc.create_template(
            AgentTemplateCreate(key="dup", name="Two", scope="user"),
            owner_user_id=USER, request_space_id=SPACE,
        )


def test_no_global_default_agent_auto_used(db):
    """Seeding templates creates zero Agents — templates are factories, not agents."""
    seed_system_templates(db)
    assert db.query(Agent).filter(Agent.source_template_id.isnot(None)).count() == 0
