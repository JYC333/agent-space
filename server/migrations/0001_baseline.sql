-- server/migrations/0001_baseline.sql
-- Generated from server/src/db/schema via drizzle-kit; custom extension/domain primitives are preserved because Drizzle cannot emit them.

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE DOMAIN public.retrieval_object_type AS character varying(64)
	CONSTRAINT retrieval_object_type_allowed CHECK (((VALUE)::text = ANY (ARRAY[('knowledge_item'::character varying)::text, ('note'::character varying)::text, ('source'::character varying)::text, ('claim'::character varying)::text, ('memory_entry'::character varying)::text, ('project_public_summary'::character varying)::text, ('source_item'::character varying)::text, ('extracted_evidence'::character varying)::text])));

CREATE TABLE "academic_papers" (
	"object_id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"doi" varchar(256),
	"arxiv_id" varchar(64),
	"pmid" varchar(32),
	"openalex_id" varchar(64),
	"publication_date" timestamp with time zone,
	"venue" varchar(512),
	"paper_type" varchar(32) DEFAULT 'article' NOT NULL,
	"cited_by_count" integer,
	"reference_count" integer,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "academic_papers_object_id_space_id_key" UNIQUE("object_id","space_id"),
	CONSTRAINT "ck_academic_papers_paper_type" CHECK ((paper_type)::text = ANY (ARRAY[('article'::character varying)::text, ('preprint'::character varying)::text, ('conference_paper'::character varying)::text, ('book_chapter'::character varying)::text, ('thesis'::character varying)::text, ('report'::character varying)::text, ('other'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "activity_records" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_run_id" varchar(36),
	"session_id" varchar(36),
	"user_id" varchar(36),
	"workspace_id" varchar(36),
	"agent_id" varchar(36),
	"source_task_id" varchar(36),
	"source_url" text,
	"activity_type" varchar(64) NOT NULL,
	"title" varchar(512),
	"content" text,
	"payload_json" jsonb NOT NULL,
	"occurred_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"status" varchar(32) DEFAULT 'raw' NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"source_kind" varchar(64),
	"source_trust" varchar(32),
	"source_integrity_json" jsonb,
	"entity_refs_json" jsonb,
	"subject_user_id" varchar(36),
	"processed_at" timestamp with time zone,
	"discarded_at" timestamp with time zone,
	"visibility" varchar(32) DEFAULT 'space_shared' NOT NULL,
	"owner_user_id" varchar(36),
	"project_id" varchar(36),
	"aggregate_key" varchar(128),
	CONSTRAINT "ck_activity_records_source_kind" CHECK ((source_kind IS NULL) OR ((source_kind)::text = ANY (ARRAY[('user_capture'::character varying)::text, ('chat_message'::character varying)::text, ('external_chat'::character varying)::text, ('file_import'::character varying)::text, ('web_capture'::character varying)::text, ('run_event'::character varying)::text, ('workspace_event'::character varying)::text, ('system_event'::character varying)::text, ('external_source'::character varying)::text, ('source'::character varying)::text]))),
	CONSTRAINT "ck_activity_records_source_trust" CHECK ((source_trust IS NULL) OR ((source_trust)::text = ANY (ARRAY[('user_confirmed'::character varying)::text, ('internal_system'::character varying)::text, ('trusted_external'::character varying)::text, ('untrusted_external'::character varying)::text, ('agent_inferred'::character varying)::text]))),
	CONSTRAINT "ck_activity_records_status" CHECK ((status)::text = ANY (ARRAY[('raw'::character varying)::text, ('processed'::character varying)::text, ('proposals_generated'::character varying)::text, ('failed'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "agent_run_group_members" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"group_id" varchar(36) NOT NULL,
	"agent_id" varchar(36) NOT NULL,
	"role" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"capabilities_json" jsonb,
	"context_policy_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_agent_run_group_members_group_agent" UNIQUE("agent_id","group_id"),
	CONSTRAINT "ck_agent_run_group_members_role" CHECK ((role)::text = ANY (ARRAY[('manager'::character varying)::text, ('planner'::character varying)::text, ('worker'::character varying)::text, ('reviewer'::character varying)::text, ('curator'::character varying)::text, ('observer'::character varying)::text])),
	CONSTRAINT "ck_agent_run_group_members_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('disabled'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "agent_run_groups" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"root_run_id" varchar(36),
	"manager_user_id" varchar(36) NOT NULL,
	"manager_agent_id" varchar(36),
	"title" text NOT NULL,
	"goal" text NOT NULL,
	"status" varchar(32) NOT NULL,
	"budget_json" jsonb,
	"policy_snapshot_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"ended_at" timestamp with time zone,
	CONSTRAINT "uq_agent_run_groups_space_id_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_agent_run_groups_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('paused'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "agent_run_messages" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"group_id" varchar(36) NOT NULL,
	"run_id" varchar(36),
	"parent_message_id" varchar(36),
	"sender_actor_ref_json" jsonb NOT NULL,
	"sender_user_id" varchar(36),
	"sender_agent_id" varchar(36),
	"message_type" varchar(32) NOT NULL,
	"content" text NOT NULL,
	"mentions_json" jsonb,
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_agent_run_messages_space_id_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_agent_run_messages_message_type" CHECK ((message_type)::text = ANY (ARRAY[('user_instruction'::character varying)::text, ('agent_message'::character varying)::text, ('delegation_request'::character varying)::text, ('delegation_result'::character varying)::text, ('system_event'::character varying)::text, ('review_note'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "run_delegations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"group_id" varchar(36) NOT NULL,
	"parent_run_id" varchar(36) NOT NULL,
	"child_run_id" varchar(36),
	"request_message_id" varchar(36),
	"requesting_agent_id" varchar(36) NOT NULL,
	"target_agent_id" varchar(36) NOT NULL,
	"requested_by_user_id" varchar(36),
	"policy_decision_record_id" varchar(36),
	"status" varchar(32) NOT NULL,
	"instruction" text NOT NULL,
	"reason" text,
	"budget_json" jsonb,
	"context_policy_json" jsonb,
	"result_summary" text,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"completed_at" timestamp with time zone,
	CONSTRAINT "uq_run_delegations_space_id_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_run_delegations_status" CHECK ((status)::text = ANY (ARRAY[('requested'::character varying)::text, ('policy_denied'::character varying)::text, ('queued'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "actors" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"actor_type" varchar(32) NOT NULL,
	"user_id" varchar(36),
	"agent_id" varchar(36),
	"service_name" varchar(128),
	"display_name" varchar(256),
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"metadata_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_actors_actor_type" CHECK ((actor_type)::text = ANY (ARRAY[('user'::character varying)::text, ('agent'::character varying)::text, ('system'::character varying)::text, ('automation'::character varying)::text, ('connector'::character varying)::text, ('integration'::character varying)::text, ('service'::character varying)::text, ('job'::character varying)::text])),
	CONSTRAINT "ck_actors_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('disabled'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "agent_runtime_profiles" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"agent_id" varchar(36) NOT NULL,
	"name" varchar(128) NOT NULL,
	"adapter_type" varchar(64) NOT NULL,
	"model_provider_id" varchar(36),
	"model_name" varchar(256),
	"credential_profile_id" varchar(36),
	"runtime_config_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"runtime_policy_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"is_default" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_agent_runtime_profiles_agent_name" UNIQUE("agent_id","name")
);
--> statement-breakpoint
CREATE TABLE "agent_versions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"agent_id" varchar(36) NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"version_label" varchar(64) NOT NULL,
	"model_provider_id" varchar(36),
	"model_name" varchar(256),
	"system_prompt" text,
	"prompt_provenance_json" jsonb,
	"model_config_json" jsonb NOT NULL,
	"runtime_config_json" jsonb NOT NULL,
	"context_policy_json" jsonb NOT NULL,
	"memory_policy_json" jsonb NOT NULL,
	"capabilities_json" jsonb NOT NULL,
	"tool_permissions_json" jsonb NOT NULL,
	"runtime_policy_json" jsonb NOT NULL,
	"tool_policy_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"output_policy_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"schedule_config_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"output_schema_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"source_proposal_id" varchar(36),
	"source_activity_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"published_at" timestamp with time zone,
	"archived_at" timestamp with time zone,
	CONSTRAINT "uq_agent_versions_agent_label" UNIQUE("agent_id","version_label")
);
--> statement-breakpoint
CREATE TABLE "agents" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36),
	"name" varchar(256) NOT NULL,
	"description" text,
	"role_instruction" text,
	"status" varchar(32) NOT NULL,
	"agent_kind" varchar(32) DEFAULT 'standard' NOT NULL,
	"current_version_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"visibility" varchar(32) NOT NULL,
	CONSTRAINT "uq_agents_space_id_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_agents_agent_kind" CHECK ((agent_kind)::text = ANY (ARRAY[('standard'::character varying)::text, ('system_assistant'::character varying)::text, ('system_evolver'::character varying)::text, ('system_source_post_processor'::character varying)::text])),
	CONSTRAINT "ck_agents_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('inactive'::character varying)::text, ('archived'::character varying)::text, ('disabled'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "cli_credential_events" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"run_id" varchar(36),
	"runtime_adapter_type" varchar(64),
	"credential_profile_id" varchar(128),
	"credential_source" varchar(32) NOT NULL,
	"trigger_origin" varchar(64),
	"fallback_used" boolean NOT NULL,
	"fallback_reason" varchar(128),
	"broker_error" boolean NOT NULL,
	"cleanup_status" varchar(32) NOT NULL,
	"action" varchar(64) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_cli_credential_events_credential_source" CHECK ((credential_source)::text = ANY (ARRAY[('profile'::character varying)::text, ('container_default'::character varying)::text, ('none'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "cli_credential_profiles" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"owner_user_id" varchar(36) NOT NULL,
	"runtime" varchar(64) NOT NULL,
	"name" varchar(128) NOT NULL,
	"source_path" text NOT NULL,
	"target_path" text NOT NULL,
	"readonly" boolean NOT NULL,
	"notes" text NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_cli_credential_profiles_owner_runtime_name" UNIQUE("name","owner_user_id","runtime")
);
--> statement-breakpoint
CREATE TABLE "cli_credential_space_grants" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"profile_id" varchar(36) NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36) NOT NULL,
	"granted_by_user_id" varchar(36),
	"enabled" boolean NOT NULL,
	"is_default" boolean NOT NULL,
	"network_profile_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_cli_credential_space_grants_profile_space" UNIQUE("profile_id","space_id")
);
--> statement-breakpoint
CREATE TABLE "artifacts" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"run_id" varchar(36),
	"proposal_id" varchar(36),
	"artifact_type" varchar(64) NOT NULL,
	"title" varchar(512) NOT NULL,
	"content" text,
	"storage_ref" varchar(1024),
	"storage_path" varchar(1024),
	"mime_type" varchar(256),
	"exportable" boolean DEFAULT true NOT NULL,
	"export_formats_json" jsonb NOT NULL,
	"canonical_format" varchar(64),
	"preview" boolean DEFAULT false NOT NULL,
	"relevant_period_start" timestamp with time zone,
	"relevant_period_end" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"metadata_json" jsonb,
	"visibility" varchar(32) DEFAULT 'space_shared' NOT NULL,
	"owner_user_id" varchar(36),
	"trust_level" varchar(32),
	"project_id" varchar(36),
	"workspace_id" varchar(36),
	CONSTRAINT "ck_artifacts_storage_path_relative" CHECK ((storage_path IS NULL) OR ((storage_path)::text !~~ '/%'::text)),
	CONSTRAINT "ck_artifacts_trust_level" CHECK ((trust_level IS NULL) OR ((trust_level)::text = ANY (ARRAY[('high'::character varying)::text, ('medium'::character varying)::text, ('low'::character varying)::text, ('unknown'::character varying)::text]))),
	CONSTRAINT "ck_artifacts_workspace_shared_workspace" CHECK (((visibility)::text <> 'workspace_shared'::text) OR (workspace_id IS NOT NULL))
);
--> statement-breakpoint
CREATE TABLE "auth_accounts" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"provider" varchar(32) NOT NULL,
	"provider_user_id" varchar(256) NOT NULL,
	"email" varchar(256) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_auth_accounts_provider_user" UNIQUE("provider","provider_user_id")
);
--> statement-breakpoint
CREATE TABLE "user_sessions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"token_hash" varchar(128) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"last_seen_at" timestamp with time zone,
	CONSTRAINT "user_sessions_token_hash_key" UNIQUE("token_hash")
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"email" varchar(256),
	"display_name" varchar(256) NOT NULL,
	"avatar_url" text,
	"status" varchar(32) NOT NULL,
	"last_login_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "automation_credential_grants" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"automation_id" varchar(36) NOT NULL,
	"granted_by_user_id" varchar(36) NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"revoked_at" timestamp with time zone,
	"revoked_by_user_id" varchar(36),
	CONSTRAINT "ck_automation_credential_grants_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('revoked'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "automation_runs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"automation_id" varchar(36) NOT NULL,
	"run_id" varchar(36) NOT NULL,
	"triggered_by_user_id" varchar(36),
	"trigger_type" varchar(64) DEFAULT 'manual' NOT NULL,
	"preflight_snapshot_json" jsonb,
	"trigger_context_json" jsonb,
	"created_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "automations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36) NOT NULL,
	"agent_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36),
	"project_id" varchar(36),
	"name" varchar(256) NOT NULL,
	"description" text,
	"trigger_type" varchar(64) DEFAULT 'manual' NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"preflight_snapshot_json" jsonb,
	"config_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_automations_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('paused'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_automations_trigger_type" CHECK ((trigger_type)::text = ANY (ARRAY[('manual'::character varying)::text, ('schedule'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "capability_enablements" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36),
	"agent_id" varchar(36),
	"user_id" varchar(36),
	"capability_key" varchar(128) NOT NULL,
	"capability_version_id" varchar(36),
	"enabled" boolean NOT NULL,
	"config_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_capability_enablements_config_object" CHECK (jsonb_typeof(config_json) = 'object'::text),
	CONSTRAINT "ck_capability_enablements_single_scope" CHECK (((((project_id IS NOT NULL))::integer + ((agent_id IS NOT NULL))::integer) + ((user_id IS NOT NULL))::integer) <= 1)
);
--> statement-breakpoint
CREATE TABLE "capability_overlays" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"capability_key" varchar(128) NOT NULL,
	"scope_type" varchar(32) NOT NULL,
	"scope_id" varchar(128),
	"base_version_id" varchar(36),
	"overlay_type" varchar(64) NOT NULL,
	"patch_json" jsonb NOT NULL,
	"status" varchar(32) NOT NULL,
	"proposal_id" varchar(36),
	"metadata_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "capability_runtime_bindings" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"capability_key" varchar(128) NOT NULL,
	"capability_version_id" varchar(36),
	"runtime_adapter_type" varchar(64) NOT NULL,
	"render_mode" varchar(32) NOT NULL,
	"binding_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_capability_runtime_bindings_binding_object" CHECK (jsonb_typeof(binding_json) = 'object'::text),
	CONSTRAINT "ck_capability_runtime_bindings_render_mode" CHECK ((render_mode)::text = ANY (ARRAY[('render_skill'::character varying)::text, ('inline_prompt'::character varying)::text, ('native_executor'::character varying)::text, ('mcp_tool'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "capability_versions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"capability_key" varchar(128) NOT NULL,
	"scope_type" varchar(32) NOT NULL,
	"scope_id" varchar(128),
	"parent_version_id" varchar(36),
	"version" varchar(64) NOT NULL,
	"source" varchar(32) NOT NULL,
	"artifact_uri" varchar(1024),
	"content_ref" varchar(1024),
	"content_hash" varchar(128),
	"status" varchar(32) NOT NULL,
	"proposal_id" varchar(36),
	"metadata_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "project_workflow_profiles" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"workflow_template_id" varchar(128) NOT NULL,
	"name" varchar(256) NOT NULL,
	"enabled" boolean NOT NULL,
	"config_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_workflow_profiles_config_object" CHECK (jsonb_typeof(config_json) = 'object'::text)
);
--> statement-breakpoint
CREATE TABLE "skill_local_overlays" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"skill_package_id" varchar(36) NOT NULL,
	"scope_type" varchar(32) NOT NULL,
	"scope_id" varchar(128),
	"overlay_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"status" varchar(32) NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_skill_local_overlays_overlay_object" CHECK (jsonb_typeof(overlay_json) = 'object'::text),
	CONSTRAINT "ck_skill_local_overlays_scope_id" CHECK ((((scope_type)::text = 'space'::text) AND (scope_id IS NULL)) OR (((scope_type)::text <> 'space'::text) AND (scope_id IS NOT NULL))),
	CONSTRAINT "ck_skill_local_overlays_scope_type" CHECK ((scope_type)::text = ANY (ARRAY[('space'::character varying)::text, ('project'::character varying)::text, ('workspace'::character varying)::text, ('agent'::character varying)::text, ('user'::character varying)::text])),
	CONSTRAINT "ck_skill_local_overlays_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "skill_package_files" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"skill_package_id" varchar(36) NOT NULL,
	"path" text NOT NULL,
	"kind" varchar(64) NOT NULL,
	"content_hash" varchar(128),
	"content_type" varchar(256),
	"byte_length" integer,
	"storage_ref" text,
	"included" boolean DEFAULT true NOT NULL,
	"executable" boolean DEFAULT false NOT NULL,
	"risk_flags_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_skill_package_files_byte_length" CHECK ((byte_length IS NULL) OR (byte_length >= 0)),
	CONSTRAINT "ck_skill_package_files_path_nonempty" CHECK (length(path) > 0),
	CONSTRAINT "ck_skill_package_files_risk_flags_object" CHECK (jsonb_typeof(risk_flags_json) = 'object'::text)
);
--> statement-breakpoint
CREATE TABLE "skill_packages" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"source_id" varchar(36) NOT NULL,
	"package_name" varchar(256) NOT NULL,
	"version" varchar(64),
	"license" varchar(128),
	"raw_storage_ref" text,
	"manifest_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"normalized_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"risk_level" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_skill_packages_manifest_object" CHECK (jsonb_typeof(manifest_json) = 'object'::text),
	CONSTRAINT "ck_skill_packages_normalized_object" CHECK (jsonb_typeof(normalized_json) = 'object'::text),
	CONSTRAINT "ck_skill_packages_risk_level" CHECK ((risk_level)::text = ANY (ARRAY[('low'::character varying)::text, ('medium'::character varying)::text, ('high'::character varying)::text, ('critical'::character varying)::text])),
	CONSTRAINT "ck_skill_packages_status" CHECK ((status)::text = ANY (ARRAY[('imported'::character varying)::text, ('reviewed'::character varying)::text, ('rejected'::character varying)::text, ('converted'::character varying)::text, ('archived'::character varying)::text, ('superseded'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "skill_sources" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"source_type" varchar(32) NOT NULL,
	"url" text,
	"repo" varchar(512),
	"path" text,
	"ref" varchar(256),
	"commit_sha" varchar(128),
	"content_hash" varchar(128) NOT NULL,
	"fetched_at" timestamp with time zone NOT NULL,
	"created_by_user_id" varchar(36),
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_skill_sources_content_hash_nonempty" CHECK (length((content_hash)::text) > 0),
	CONSTRAINT "ck_skill_sources_metadata_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text),
	CONSTRAINT "ck_skill_sources_source_type" CHECK ((source_type)::text = ANY (ARRAY[('github'::character varying)::text, ('registry'::character varying)::text, ('local_workspace'::character varying)::text, ('upload'::character varying)::text, ('builtin'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "card_review_states" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"card_id" varchar(36) NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"due_at" timestamp with time zone,
	"stability" double precision,
	"difficulty" double precision,
	"elapsed_days" double precision,
	"scheduled_days" double precision,
	"reps" integer NOT NULL,
	"lapses" integer NOT NULL,
	"state" varchar(32),
	"last_reviewed_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_card_review_states_card_user" UNIQUE("card_id","user_id"),
	CONSTRAINT "ck_card_review_states_state" CHECK ((state IS NULL) OR ((state)::text = ANY (ARRAY[('new'::character varying)::text, ('learning'::character varying)::text, ('review'::character varying)::text, ('relearning'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "card_reviews" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"card_id" varchar(36) NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"rating" varchar(16) NOT NULL,
	"reviewed_at" timestamp with time zone NOT NULL,
	"review_state_snapshot_json" jsonb,
	"duration_ms" integer,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_card_reviews_rating" CHECK ((rating)::text = ANY (ARRAY[('again'::character varying)::text, ('hard'::character varying)::text, ('good'::character varying)::text, ('easy'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "cards" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"card_type" varchar(32) NOT NULL,
	"front" text NOT NULL,
	"back" text NOT NULL,
	"source_type" varchar(32),
	"source_id" varchar(36),
	"status" varchar(32) NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"archived_at" timestamp with time zone,
	"metadata_json" jsonb,
	CONSTRAINT "ck_cards_card_type" CHECK ((card_type)::text = ANY (ARRAY[('basic'::character varying)::text, ('cloze'::character varying)::text])),
	CONSTRAINT "ck_cards_source_type" CHECK ((source_type IS NULL) OR ((source_type)::text = ANY (ARRAY[('note'::character varying)::text, ('knowledge_item'::character varying)::text, ('source'::character varying)::text, ('activity'::character varying)::text, ('run'::character varying)::text, ('proposal'::character varying)::text]))),
	CONSTRAINT "ck_cards_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('active'::character varying)::text, ('suspended'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "context_artifact_revocations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"artifact_id" varchar(36) NOT NULL,
	"scope_type" varchar(16) NOT NULL,
	"scope_id" varchar(36) NOT NULL,
	"reason" text,
	"created_by_user_id" varchar(36),
	"deleted_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"deleted_at" timestamp with time zone,
	CONSTRAINT "ck_context_artifact_revocations_scope_type" CHECK ((scope_type)::text = ANY (ARRAY[('workspace'::character varying)::text, ('project'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "context_digests" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"scope_type" varchar(32) NOT NULL,
	"scope_id" varchar(36),
	"digest_type" varchar(32) NOT NULL,
	"version" integer DEFAULT 1 NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"content" text,
	"source_memory_ids_json" jsonb,
	"source_policy_ids_json" jsonb,
	"source_relation_ids_json" jsonb,
	"source_hash" varchar(128),
	"content_hash" varchar(128),
	"dirty_since" timestamp with time zone,
	"dirty_reason_json" jsonb,
	"dirty_count" integer DEFAULT 0 NOT NULL,
	"generated_at" timestamp with time zone,
	"created_from_run_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_context_digests_digest_type" CHECK ((digest_type)::text = ANY (ARRAY[('policy_bundle'::character varying)::text, ('workspace'::character varying)::text, ('agent'::character varying)::text])),
	CONSTRAINT "ck_context_digests_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('dirty'::character varying)::text, ('superseded'::character varying)::text, ('disabled'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "context_profiles" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"scope_type" varchar(32) NOT NULL,
	"scope_id" varchar(128),
	"status" varchar(32) NOT NULL,
	"version" integer DEFAULT 1 NOT NULL,
	"context_pack_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"routing_manifest_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_context_profiles_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_context_profiles_context_pack_object" CHECK (jsonb_typeof(context_pack_json) = 'object'::text),
	CONSTRAINT "ck_context_profiles_routing_manifest_object" CHECK (jsonb_typeof(routing_manifest_json) = 'object'::text),
	CONSTRAINT "ck_context_profiles_scope_id" CHECK ((((scope_type)::text = 'space'::text) AND (scope_id IS NULL)) OR (((scope_type)::text <> 'space'::text) AND (scope_id IS NOT NULL))),
	CONSTRAINT "ck_context_profiles_scope_type" CHECK ((scope_type)::text = ANY (ARRAY[('space'::character varying)::text, ('project'::character varying)::text, ('workspace'::character varying)::text, ('agent'::character varying)::text, ('user'::character varying)::text])),
	CONSTRAINT "ck_context_profiles_version_positive" CHECK (version >= 1)
);
--> statement-breakpoint
CREATE TABLE "context_snapshot_items" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"context_snapshot_id" varchar(36) NOT NULL,
	"item_type" varchar(32) NOT NULL,
	"item_id" varchar(36),
	"title" varchar(512),
	"excerpt" text,
	"score" double precision,
	"reason" varchar(256),
	"token_count" integer,
	"metadata_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_context_snapshot_items_item_type" CHECK ((item_type)::text = ANY (ARRAY[('memory'::character varying)::text, ('knowledge_item'::character varying)::text, ('source'::character varying)::text, ('activity_record'::character varying)::text, ('project_public_summary'::character varying)::text, ('task'::character varying)::text, ('idea'::character varying)::text, ('project'::character varying)::text, ('workspace'::character varying)::text, ('run'::character varying)::text, ('proposal'::character varying)::text, ('artifact'::character varying)::text, ('manual_context'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "context_snapshots" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_refs_json" jsonb NOT NULL,
	"compiled_summary" text,
	"token_estimate" integer,
	"relevant_period_start" timestamp with time zone,
	"relevant_period_end" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"compiled_prefix_text" text,
	"compiled_tail_text" text,
	"compiled_prefix_ref" varchar(1024),
	"compiled_tail_ref" varchar(1024),
	"prefix_hash" varchar(128),
	"tail_hash" varchar(128),
	"compiler_version" varchar(64),
	"retrieval_trace_json" jsonb,
	"token_budget_json" jsonb,
	"policy_bundle_version" varchar(64),
	"memory_digest_version" varchar(64),
	"workspace_digest_version" varchar(64),
	"included_memory_refs_json" jsonb,
	"included_evidence_refs_json" jsonb,
	"included_file_refs_json" jsonb,
	"included_doc_refs_json" jsonb,
	"redactions_json" jsonb,
	"data_exposure_level" varchar(64),
	"rendered_context_uri" varchar(1024),
	"rendered_context_text" text,
	"agent_id" varchar(36),
	"session_id" varchar(36),
	"run_id" varchar(36),
	"request_json" jsonb,
	CONSTRAINT "ck_context_snapshots_data_exposure_level" CHECK ((data_exposure_level IS NULL) OR ((data_exposure_level)::text = ANY (ARRAY[('local_only'::character varying)::text, ('model_provider'::character varying)::text, ('vendor_platform'::character varying)::text, ('third_party_tools'::character varying)::text, ('unknown'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "evolution_experiences" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"strategy_asset_id" varchar(36),
	"target_id" varchar(36),
	"source_run_id" varchar(36),
	"source_proposal_id" varchar(36),
	"experience_key" varchar(160) NOT NULL,
	"summary" text NOT NULL,
	"trigger_signals_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"outcome_status" varchar(32) NOT NULL,
	"confidence_score" double precision DEFAULT 0.5 NOT NULL,
	"blast_radius_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"validation_trace_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"execution_trace_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"lessons_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"anti_patterns_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"environment_fingerprint_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"provenance_type" varchar(32) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_evolution_experiences_confidence_score" CHECK ((confidence_score >= (0)::double precision) AND (confidence_score <= (1)::double precision)),
	CONSTRAINT "ck_evolution_experiences_outcome_status" CHECK ((outcome_status)::text = ANY (ARRAY[('success'::character varying)::text, ('failed'::character varying)::text, ('partial'::character varying)::text, ('unknown'::character varying)::text])),
	CONSTRAINT "ck_evolution_experiences_provenance_type" CHECK ((provenance_type)::text = ANY (ARRAY[('run_observed'::character varying)::text, ('proposal_accepted'::character varying)::text, ('imported'::character varying)::text, ('user_authored'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "evolution_selector_decisions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"target_id" varchar(36) NOT NULL,
	"run_id" varchar(36),
	"selected_strategy_asset_id" varchar(36),
	"candidate_strategy_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"input_signal_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"decision_reason" text,
	"score_trace_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"rejected_reasons_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "evolution_signals" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"target_id" varchar(36) NOT NULL,
	"signal_type" varchar(128) NOT NULL,
	"source_type" varchar(64) NOT NULL,
	"source_id" varchar(128),
	"severity" varchar(32) NOT NULL,
	"summary" text,
	"payload_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "evolution_strategy_assets" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"strategy_key" varchar(128) NOT NULL,
	"name" varchar(256) NOT NULL,
	"description" text,
	"category" varchar(32) NOT NULL,
	"target_type" varchar(64) NOT NULL,
	"status" varchar(32) DEFAULT 'draft' NOT NULL,
	"risk_level" varchar(32) NOT NULL,
	"signals_match_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"preconditions_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"strategy_steps_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"constraints_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"validation_policy_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"tool_policy_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"routing_hint_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"provenance_type" varchar(32) NOT NULL,
	"source_ref_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"success_count" integer DEFAULT 0 NOT NULL,
	"failure_count" integer DEFAULT 0 NOT NULL,
	"confidence_score" double precision DEFAULT 0.5 NOT NULL,
	"last_selected_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_evolution_strategy_assets_category" CHECK ((category)::text = ANY (ARRAY[('repair'::character varying)::text, ('optimize'::character varying)::text, ('innovate'::character varying)::text, ('maintain'::character varying)::text, ('harden'::character varying)::text, ('review'::character varying)::text])),
	CONSTRAINT "ck_evolution_strategy_assets_confidence_score" CHECK ((confidence_score >= (0)::double precision) AND (confidence_score <= (1)::double precision)),
	CONSTRAINT "ck_evolution_strategy_assets_counts" CHECK ((success_count >= 0) AND (failure_count >= 0)),
	CONSTRAINT "ck_evolution_strategy_assets_provenance_type" CHECK ((provenance_type)::text = ANY (ARRAY[('built_in'::character varying)::text, ('user_authored'::character varying)::text, ('imported'::character varying)::text, ('evolved'::character varying)::text, ('distilled'::character varying)::text])),
	CONSTRAINT "ck_evolution_strategy_assets_risk_level" CHECK ((risk_level)::text = ANY (ARRAY[('low'::character varying)::text, ('medium'::character varying)::text, ('high'::character varying)::text, ('critical'::character varying)::text])),
	CONSTRAINT "ck_evolution_strategy_assets_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('active'::character varying)::text, ('disabled'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_evolution_strategy_assets_target_type" CHECK ((target_type)::text = ANY (ARRAY[('agent_version'::character varying)::text, ('capability'::character varying)::text, ('runtime_skill_binding'::character varying)::text, ('memory'::character varying)::text, ('knowledge'::character varying)::text, ('workflow'::character varying)::text, ('workspace'::character varying)::text, ('system'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "evolution_targets" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"target_type" varchar(64) NOT NULL,
	"target_ref_type" varchar(64),
	"target_ref_id" varchar(128),
	"capability_key" varchar(128),
	"current_version_id" varchar(36),
	"risk_level" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"engine_policy_json" jsonb NOT NULL,
	"metadata_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "run_reflections" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"run_id" varchar(36) NOT NULL,
	"source" varchar(32) DEFAULT 'native' NOT NULL,
	"what_changed" text,
	"what_worked" text,
	"what_failed" text,
	"reusable_rules_json" jsonb,
	"reusable_commands_json" jsonb,
	"workspace_facts_json" jsonb,
	"memory_candidates_json" jsonb,
	"capability_candidates_json" jsonb,
	"policy_candidates_json" jsonb,
	"validation_candidates_json" jsonb,
	"follow_up_tasks_json" jsonb,
	"confidence" double precision,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_run_reflections_source" CHECK ((source)::text = ANY (ARRAY[('native'::character varying)::text, ('external_import'::character varying)::text, ('manual'::character varying)::text, ('evaluator'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "evolvable_asset_evaluation_runs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"asset_id" varchar(36) NOT NULL,
	"candidate_version_id" varchar(36) NOT NULL,
	"baseline_version_id" varchar(36),
	"evolution_target_id" varchar(36),
	"run_id" varchar(36),
	"eval_suite_ref_json" jsonb NOT NULL,
	"evaluator_version" varchar(64) NOT NULL,
	"model_provider_ref_json" jsonb,
	"status" varchar(16) DEFAULT 'queued' NOT NULL,
	"metrics_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"blockers_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"output_artifact_id" varchar(36),
	"report_artifact_id" varchar(36),
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_evolvable_asset_evaluation_runs_status" CHECK ((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('passed'::character varying)::text, ('failed'::character varying)::text, ('blocked'::character varying)::text, ('cancelled'::character varying)::text])),
	CONSTRAINT "ck_evolvable_asset_evaluation_runs_metrics_object" CHECK (jsonb_typeof(metrics_json) = 'object'::text),
	CONSTRAINT "ck_evolvable_asset_evaluation_runs_blockers_array" CHECK (jsonb_typeof(blockers_json) = 'array'::text)
);
--> statement-breakpoint
CREATE TABLE "evolvable_asset_pins" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"asset_id" varchar(36) NOT NULL,
	"scope_type" varchar(16) NOT NULL,
	"scope_id" varchar(36) NOT NULL,
	"version_id" varchar(36) NOT NULL,
	"status" varchar(16) DEFAULT 'active' NOT NULL,
	"pinned_by_user_id" varchar(36),
	"reason" text,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_evolvable_asset_pins_scope_type" CHECK ((scope_type)::text = ANY (ARRAY[('space'::character varying)::text, ('project'::character varying)::text, ('user'::character varying)::text, ('agent'::character varying)::text])),
	CONSTRAINT "ck_evolvable_asset_pins_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "evolvable_asset_versions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"asset_id" varchar(36) NOT NULL,
	"space_id" varchar(36),
	"scope_type" varchar(16) NOT NULL,
	"scope_id" varchar(36),
	"parent_version_id" varchar(36),
	"version" integer NOT NULL,
	"status" varchar(16) DEFAULT 'draft' NOT NULL,
	"source" varchar(16) NOT NULL,
	"content_ref" varchar(1024),
	"content_hash" varchar(128),
	"content_json" jsonb,
	"eval_summary_json" jsonb,
	"promotion_proposal_id" varchar(36),
	"created_by_user_id" varchar(36),
	"approved_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_evolvable_asset_versions_scope_type" CHECK ((scope_type)::text = ANY (ARRAY[('system'::character varying)::text, ('space'::character varying)::text, ('project'::character varying)::text, ('user'::character varying)::text, ('agent'::character varying)::text])),
	CONSTRAINT "ck_evolvable_asset_versions_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('candidate'::character varying)::text, ('testing'::character varying)::text, ('approved'::character varying)::text, ('deprecated'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_evolvable_asset_versions_source" CHECK ((source)::text = ANY (ARRAY[('built_in'::character varying)::text, ('user_authored'::character varying)::text, ('evolved'::character varying)::text, ('imported'::character varying)::text, ('generated'::character varying)::text])),
	CONSTRAINT "ck_evolvable_asset_versions_version_positive" CHECK (version > 0)
);
--> statement-breakpoint
CREATE TABLE "evolvable_assets" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"asset_type" varchar(32) NOT NULL,
	"asset_key" varchar(160) NOT NULL,
	"display_name" varchar(256) NOT NULL,
	"description" text,
	"owner_scope_type" varchar(16) NOT NULL,
	"owner_scope_id" varchar(36),
	"status" varchar(16) DEFAULT 'active' NOT NULL,
	"current_system_version_id" varchar(36),
	"default_eval_suite_ref_json" jsonb,
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_evolvable_assets_asset_type" CHECK ((asset_type)::text = ANY (ARRAY[('prompt_template'::character varying)::text, ('workflow_template'::character varying)::text, ('capability'::character varying)::text, ('agent_config'::character varying)::text, ('runtime_skill_binding'::character varying)::text, ('source_post_processing_rule'::character varying)::text])),
	CONSTRAINT "ck_evolvable_assets_owner_scope_type" CHECK ((owner_scope_type)::text = ANY (ARRAY[('system'::character varying)::text, ('space'::character varying)::text, ('project'::character varying)::text, ('user'::character varying)::text, ('agent'::character varying)::text])),
	CONSTRAINT "ck_evolvable_assets_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('disabled'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_evolvable_assets_metadata_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text)
);
--> statement-breakpoint
CREATE TABLE "graph_view_states" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"scope_key" varchar(128) NOT NULL,
	"state_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_graph_view_states_scope" UNIQUE("scope_key","space_id","user_id"),
	CONSTRAINT "ck_graph_view_states_state_object" CHECK (jsonb_typeof(state_json) = 'object'::text)
);
--> statement-breakpoint
CREATE TABLE "job_events" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"job_id" varchar(36) NOT NULL,
	"event_type" varchar(32) NOT NULL,
	"message" text NOT NULL,
	"data" jsonb,
	"created_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "jobs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"job_type" varchar(128) NOT NULL,
	"status" varchar(32) NOT NULL,
	"priority" integer NOT NULL,
	"payload_json" jsonb NOT NULL,
	"result_json" jsonb,
	"error" text,
	"attempts" integer NOT NULL,
	"max_attempts" integer NOT NULL,
	"scheduled_at" timestamp with time zone DEFAULT now() NOT NULL,
	"claimed_by" varchar(64),
	"claimed_at" timestamp with time zone,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"heartbeat_at" timestamp with time zone,
	"user_id" varchar(36),
	"workspace_id" varchar(36),
	"agent_id" varchar(36),
	CONSTRAINT "ck_jobs_attempts_nonneg" CHECK (attempts >= 0),
	CONSTRAINT "ck_jobs_max_attempts_positive" CHECK (max_attempts > 0),
	CONSTRAINT "ck_jobs_status" CHECK ((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('claimed'::character varying)::text, ('running'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "claim_sources" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"claim_id" varchar(36) NOT NULL,
	"source_object_id" varchar(36),
	"source_ref_type" varchar(64),
	"source_ref_id" varchar(36),
	"source_connection_id" varchar(36),
	"source_policy_snapshot_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"locator" varchar(1024),
	"quote_excerpt" text,
	"evidence_role" varchar(32) NOT NULL,
	"source_trust" varchar(32),
	"confidence" double precision,
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_claim_sources_confidence" CHECK ((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
	CONSTRAINT "ck_claim_sources_evidence_role" CHECK ((evidence_role)::text = ANY (ARRAY[('supports'::character varying)::text, ('contradicts'::character varying)::text, ('mentions'::character varying)::text, ('derived_from'::character varying)::text, ('cites'::character varying)::text, ('summarizes'::character varying)::text])),
	CONSTRAINT "ck_claim_sources_metadata_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text),
	CONSTRAINT "ck_claim_sources_policy_snapshot_object" CHECK (jsonb_typeof(source_policy_snapshot_json) = 'object'::text),
	CONSTRAINT "ck_claim_sources_has_source" CHECK ((source_object_id IS NOT NULL) OR ((source_ref_type IS NOT NULL) AND (source_ref_id IS NOT NULL)) OR (source_connection_id IS NOT NULL)),
	CONSTRAINT "ck_claim_sources_source_ref" CHECK (((source_ref_type IS NULL) AND (source_ref_id IS NULL)) OR ((source_ref_type IS NOT NULL) AND (source_ref_id IS NOT NULL))),
	CONSTRAINT "ck_claim_sources_source_ref_connection" CHECK ((source_ref_type IS NULL) OR (source_connection_id IS NOT NULL)),
	CONSTRAINT "ck_claim_sources_source_ref_type" CHECK ((source_ref_type IS NULL) OR ((source_ref_type)::text = ANY (ARRAY[('activity'::character varying)::text, ('artifact'::character varying)::text, ('run_event'::character varying)::text, ('extracted_evidence'::character varying)::text, ('source_snapshot'::character varying)::text, ('external_pointer'::character varying)::text, ('source_item'::character varying)::text]))),
	CONSTRAINT "ck_claim_sources_source_trust" CHECK ((source_trust IS NULL) OR ((source_trust)::text = ANY (ARRAY[('trusted'::character varying)::text, ('normal'::character varying)::text, ('untrusted'::character varying)::text, ('unknown'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "claims" (
	"object_id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"subject_object_id" varchar(36),
	"subject_text" text,
	"claim_kind" varchar(32) NOT NULL,
	"claim_text" text NOT NULL,
	"normalized_claim_hash" varchar(128) NOT NULL,
	"holder_object_id" varchar(36),
	"holder_type" varchar(64),
	"holder_id" varchar(128),
	"confidence" double precision,
	"confidence_method" varchar(32) NOT NULL,
	"resolution_state" varchar(32) NOT NULL,
	"valid_from" timestamp with time zone,
	"valid_until" timestamp with time zone,
	"observed_at" timestamp with time zone,
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_from_proposal_id" varchar(36),
	"approved_by_user_id" varchar(36),
	CONSTRAINT "claims_object_id_space_id_key" UNIQUE("object_id","space_id"),
	CONSTRAINT "ck_claims_claim_kind" CHECK ((claim_kind)::text = ANY (ARRAY[('fact'::character varying)::text, ('hypothesis'::character varying)::text, ('belief'::character varying)::text, ('preference'::character varying)::text, ('commitment'::character varying)::text, ('question'::character varying)::text, ('interpretation'::character varying)::text, ('instruction'::character varying)::text, ('metric'::character varying)::text, ('relationship'::character varying)::text, ('event'::character varying)::text])),
	CONSTRAINT "ck_claims_claim_text" CHECK (btrim(claim_text) <> ''::text),
	CONSTRAINT "ck_claims_confidence" CHECK ((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
	CONSTRAINT "ck_claims_confidence_method" CHECK ((confidence_method)::text = ANY (ARRAY[('human_confirmed'::character varying)::text, ('source_extracted'::character varying)::text, ('llm_extracted'::character varying)::text, ('inferred'::character varying)::text, ('imported'::character varying)::text])),
	CONSTRAINT "ck_claims_holder_ref" CHECK (((holder_object_id IS NOT NULL) AND (holder_type IS NULL) AND (holder_id IS NULL)) OR ((holder_object_id IS NULL) AND (((holder_type IS NULL) AND (holder_id IS NULL)) OR ((holder_type IS NOT NULL) AND (holder_id IS NOT NULL))))),
	CONSTRAINT "ck_claims_metadata_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text),
	CONSTRAINT "ck_claims_resolution_state" CHECK ((resolution_state)::text = ANY (ARRAY[('unreviewed'::character varying)::text, ('confirmed'::character varying)::text, ('contradicted'::character varying)::text, ('stale'::character varying)::text, ('needs_source'::character varying)::text])),
	CONSTRAINT "ck_claims_subject" CHECK ((subject_object_id IS NOT NULL) OR ((subject_text IS NOT NULL) AND (btrim(subject_text) <> ''::text))),
	CONSTRAINT "ck_claims_valid_range" CHECK ((valid_from IS NULL) OR (valid_until IS NULL) OR (valid_from <= valid_until))
);
--> statement-breakpoint
CREATE TABLE "evidence_links" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"evidence_id" varchar(36) NOT NULL,
	"target_type" varchar(64) NOT NULL,
	"target_id" varchar(36),
	"link_type" varchar(64) NOT NULL,
	"status" varchar(32) NOT NULL,
	"confidence" double precision,
	"reason" varchar(1024),
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_by_run_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_evidence_links_link_type" CHECK ((link_type)::text = ANY (ARRAY[('supports'::character varying)::text, ('contradicts'::character varying)::text, ('derived_from'::character varying)::text, ('mentions'::character varying)::text, ('context_candidate'::character varying)::text, ('used_in_context'::character varying)::text])),
	CONSTRAINT "ck_evidence_links_status" CHECK ((status)::text = ANY (ARRAY[('candidate'::character varying)::text, ('active'::character varying)::text, ('rejected'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_evidence_links_target_type" CHECK ((target_type)::text = ANY (ARRAY[('space'::character varying)::text, ('workspace'::character varying)::text, ('project'::character varying)::text, ('user'::character varying)::text, ('agent'::character varying)::text, ('run'::character varying)::text, ('proposal'::character varying)::text, ('artifact'::character varying)::text, ('knowledge'::character varying)::text, ('memory'::character varying)::text, ('task'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "extracted_evidence" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_item_id" varchar(36),
	"extraction_job_id" varchar(36),
	"source_snapshot_id" varchar(36),
	"source_object_type" varchar(64),
	"source_object_id" varchar(36),
	"evidence_type" varchar(64) NOT NULL,
	"title" varchar(1024) NOT NULL,
	"content_excerpt" varchar(4096),
	"content_hash" varchar(128),
	"artifact_id" varchar(36),
	"source_uri" text,
	"source_title" varchar(1024),
	"source_author" varchar(512),
	"occurred_at" timestamp with time zone,
	"trust_level" varchar(32) NOT NULL,
	"extraction_method" varchar(64) NOT NULL,
	"confidence" double precision,
	"status" varchar(32) NOT NULL,
	"metadata_json" jsonb,
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_by_run_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"deleted_at" timestamp with time zone,
	CONSTRAINT "ck_extracted_evidence_evidence_type" CHECK ((evidence_type)::text = ANY (ARRAY[('document'::character varying)::text, ('excerpt'::character varying)::text, ('event'::character varying)::text, ('log'::character varying)::text, ('artifact'::character varying)::text, ('claim'::character varying)::text, ('summary'::character varying)::text])),
	CONSTRAINT "ck_extracted_evidence_status" CHECK ((status)::text = ANY (ARRAY[('candidate'::character varying)::text, ('active'::character varying)::text, ('rejected'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_extracted_evidence_trust_level" CHECK ((trust_level)::text = ANY (ARRAY[('trusted'::character varying)::text, ('normal'::character varying)::text, ('untrusted'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "knowledge_item_sources" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"knowledge_item_id" varchar(36) NOT NULL,
	"source_id" varchar(36) NOT NULL,
	"relation_type" varchar(32) NOT NULL,
	"locator" varchar(1024),
	"quote" text,
	"note" text,
	"confidence" double precision,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_knowledge_item_sources_confidence" CHECK ((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
	CONSTRAINT "ck_knowledge_item_sources_relation_type" CHECK ((relation_type)::text = ANY (ARRAY[('derived_from'::character varying)::text, ('supported_by'::character varying)::text, ('cites'::character varying)::text, ('summarizes'::character varying)::text, ('mentions'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "knowledge_items" (
	"object_id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"root_item_id" varchar(36),
	"supersedes_item_id" varchar(36),
	"knowledge_kind" varchar(32) NOT NULL,
	"slug" varchar(512),
	"aliases_json" jsonb,
	"content" text NOT NULL,
	"content_json" jsonb,
	"content_format" varchar(32) NOT NULL,
	"content_schema_version" integer NOT NULL,
	"plain_text" text,
	"verification_status" varchar(32) NOT NULL,
	"reflection_status" varchar(32) NOT NULL,
	"tags_json" jsonb NOT NULL,
	"confidence" double precision,
	"created_from_proposal_id" varchar(36),
	"approved_by_user_id" varchar(36),
	"redirect_to_item_id" varchar(36),
	"version" integer NOT NULL,
	"deprecated_at" timestamp with time zone,
	CONSTRAINT "knowledge_items_object_id_space_id_key" UNIQUE("object_id","space_id"),
	CONSTRAINT "ck_knowledge_items_confidence" CHECK ((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
	CONSTRAINT "ck_knowledge_items_content_format" CHECK ((content_format)::text = ANY (ARRAY[('markdown'::character varying)::text, ('plain'::character varying)::text, ('prosemirror_json'::character varying)::text])),
	CONSTRAINT "ck_knowledge_items_knowledge_kind" CHECK ((knowledge_kind)::text = ANY (ARRAY[('concept'::character varying)::text, ('lesson'::character varying)::text, ('procedure'::character varying)::text, ('decision'::character varying)::text, ('question'::character varying)::text, ('answer'::character varying)::text, ('summary'::character varying)::text])),
	CONSTRAINT "ck_knowledge_items_reflection_status" CHECK ((reflection_status)::text = ANY (ARRAY[('unreviewed'::character varying)::text, ('reviewed'::character varying)::text, ('distilled'::character varying)::text])),
	CONSTRAINT "ck_knowledge_items_verification_status" CHECK ((verification_status)::text = ANY (ARRAY[('unverified'::character varying)::text, ('needs_review'::character varying)::text, ('verified'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "note_collection_items" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"collection_id" varchar(36) NOT NULL,
	"note_id" varchar(36) NOT NULL,
	"sort_order" integer NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_note_collection_items_collection_note" UNIQUE("collection_id","note_id","space_id")
);
--> statement-breakpoint
CREATE TABLE "note_collections" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"parent_id" varchar(36),
	"name" varchar(256) NOT NULL,
	"system_role" varchar(32) NOT NULL,
	"sort_order" integer NOT NULL,
	"is_system" boolean NOT NULL,
	"is_hidden" boolean NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "note_collections_id_space_id_key" UNIQUE("id","space_id"),
	CONSTRAINT "ck_note_collections_not_self_parent" CHECK ((parent_id IS NULL) OR ((parent_id)::text <> (id)::text)),
	CONSTRAINT "ck_note_collections_system_role" CHECK ((system_role)::text = ANY (ARRAY[('normal'::character varying)::text, ('inbox'::character varying)::text, ('archive'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "note_links" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"from_object_id" varchar(36) NOT NULL,
	"from_object_type" "retrieval_object_type" NOT NULL,
	"to_object_id" varchar(36) NOT NULL,
	"to_object_type" "retrieval_object_type" NOT NULL,
	"link_type" varchar(64) NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"confidence" double precision,
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_note_links_confidence" CHECK ((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
	CONSTRAINT "ck_note_links_has_note_endpoint" CHECK (((from_object_type)::text = 'note'::text) OR ((to_object_type)::text = 'note'::text)),
	CONSTRAINT "ck_note_links_link_type" CHECK ((link_type)::text = ANY (ARRAY[('related_to'::character varying)::text, ('references'::character varying)::text, ('depends_on'::character varying)::text, ('part_of'::character varying)::text, ('source_for'::character varying)::text, ('derived_from'::character varying)::text, ('about'::character varying)::text, ('supports'::character varying)::text, ('contradicts'::character varying)::text, ('supersedes'::character varying)::text, ('refines'::character varying)::text, ('same_as'::character varying)::text, ('explains'::character varying)::text, ('prerequisite_of'::character varying)::text, ('example_of'::character varying)::text, ('applies_to'::character varying)::text, ('summarizes'::character varying)::text, ('updates'::character varying)::text])),
	CONSTRAINT "ck_note_links_metadata_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text),
	CONSTRAINT "ck_note_links_no_self" CHECK ((from_object_id)::text <> (to_object_id)::text),
	CONSTRAINT "ck_note_links_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "notes" (
	"object_id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"content_json" jsonb,
	"content_format" varchar(32) NOT NULL,
	"content_schema_version" integer NOT NULL,
	"plain_text" text,
	"created_from_activity_id" varchar(36),
	CONSTRAINT "notes_object_id_space_id_key" UNIQUE("object_id","space_id"),
	CONSTRAINT "ck_notes_content_format" CHECK ((content_format)::text = ANY (ARRAY[('markdown'::character varying)::text, ('plain'::character varying)::text, ('prosemirror_json'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "object_relations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"from_object_id" varchar(36) NOT NULL,
	"to_object_id" varchar(36) NOT NULL,
	"relation_type" varchar(64) NOT NULL,
	"status" varchar(32) NOT NULL,
	"confidence" double precision,
	"evidence_summary" text,
	"source_claim_id" varchar(36),
	"source_object_id" varchar(36),
	"source_proposal_id" varchar(36),
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_object_relations_confidence" CHECK ((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
	CONSTRAINT "ck_object_relations_metadata_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text),
	CONSTRAINT "ck_object_relations_no_self" CHECK ((from_object_id)::text <> (to_object_id)::text),
	CONSTRAINT "ck_object_relations_relation_type" CHECK ((relation_type)::text = ANY (ARRAY[('related_to'::character varying)::text, ('references'::character varying)::text, ('depends_on'::character varying)::text, ('part_of'::character varying)::text, ('source_for'::character varying)::text, ('derived_from'::character varying)::text, ('about'::character varying)::text, ('supports'::character varying)::text, ('contradicts'::character varying)::text, ('supersedes'::character varying)::text, ('refines'::character varying)::text, ('same_as'::character varying)::text, ('affiliated_with'::character varying)::text, ('cites'::character varying)::text, ('authored_by'::character varying)::text])),
	CONSTRAINT "ck_object_relations_status" CHECK ((status)::text = ANY (ARRAY[('candidate'::character varying)::text, ('active'::character varying)::text, ('rejected'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "sources" (
	"object_id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_type" varchar(64) NOT NULL,
	"uri" text,
	"content_ref" varchar(1024),
	"raw_text" text,
	"summary" text,
	"metadata_json" jsonb NOT NULL,
	"source_activity_id" varchar(36),
	CONSTRAINT "sources_object_id_space_id_key" UNIQUE("object_id","space_id"),
	CONSTRAINT "ck_sources_source_type" CHECK ((source_type)::text = ANY (ARRAY[('activity_record'::character varying)::text, ('chat_capture'::character varying)::text, ('webpage'::character varying)::text, ('article'::character varying)::text, ('paper'::character varying)::text, ('pdf'::character varying)::text, ('file'::character varying)::text, ('email'::character varying)::text, ('manual_reference'::character varying)::text, ('external_note'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "space_object_kind_relation_hints" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"object_kind_id" varchar(36) NOT NULL,
	"endpoint_object_type" "retrieval_object_type" NOT NULL,
	"endpoint_object_kind_id" varchar(36),
	"relation_type" varchar(64) NOT NULL,
	"direction" varchar(16) DEFAULT 'from' NOT NULL,
	"confidence_default" double precision DEFAULT 0.55 NOT NULL,
	"required" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_space_object_kind_relation_hints_confidence" CHECK ((confidence_default >= (0)::double precision) AND (confidence_default <= (1)::double precision)),
	CONSTRAINT "ck_space_object_kind_relation_hints_direction" CHECK ((direction)::text = ANY (ARRAY[('from'::character varying)::text, ('to'::character varying)::text, ('either'::character varying)::text])),
	CONSTRAINT "ck_space_object_kind_relation_hints_relation_type" CHECK ((relation_type)::text = ANY (ARRAY[('related_to'::character varying)::text, ('explains'::character varying)::text, ('depends_on'::character varying)::text, ('prerequisite_of'::character varying)::text, ('part_of'::character varying)::text, ('example_of'::character varying)::text, ('applies_to'::character varying)::text, ('supports'::character varying)::text, ('contradicts'::character varying)::text, ('derived_from'::character varying)::text, ('summarizes'::character varying)::text, ('updates'::character varying)::text, ('references'::character varying)::text, ('source_for'::character varying)::text, ('about'::character varying)::text, ('supersedes'::character varying)::text, ('refines'::character varying)::text, ('same_as'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "space_object_kinds" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"key" varchar(64) NOT NULL,
	"label" varchar(160) NOT NULL,
	"description" text,
	"base_object_type" "retrieval_object_type" NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"version" integer DEFAULT 1 NOT NULL,
	"field_schema_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"extraction_policy_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"retrieval_policy_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"ui_config_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_from_proposal_id" varchar(36),
	"updated_from_proposal_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "space_object_kinds_space_base_key_key" UNIQUE("base_object_type","key","space_id"),
	CONSTRAINT "ck_space_object_kinds_extraction_policy_object" CHECK (jsonb_typeof(extraction_policy_json) = 'object'::text),
	CONSTRAINT "ck_space_object_kinds_field_schema_object" CHECK (jsonb_typeof(field_schema_json) = 'object'::text),
	CONSTRAINT "ck_space_object_kinds_key" CHECK ((key)::text ~ '^[a-z][a-z0-9_]{0,63}$'::text),
	CONSTRAINT "ck_space_object_kinds_key_by_base_object_type" CHECK (CASE (base_object_type)::text
    WHEN 'knowledge_item'::text THEN ((key)::text = ANY (ARRAY[('concept'::character varying)::text, ('lesson'::character varying)::text, ('procedure'::character varying)::text, ('decision'::character varying)::text, ('question'::character varying)::text, ('answer'::character varying)::text, ('summary'::character varying)::text]))
    WHEN 'note'::text THEN ((key)::text = 'note'::text)
    WHEN 'source'::text THEN ((key)::text = ANY (ARRAY[('activity_record'::character varying)::text, ('chat_capture'::character varying)::text, ('webpage'::character varying)::text, ('article'::character varying)::text, ('paper'::character varying)::text, ('pdf'::character varying)::text, ('file'::character varying)::text, ('email'::character varying)::text, ('manual_reference'::character varying)::text, ('external_note'::character varying)::text]))
    WHEN 'claim'::text THEN ((key)::text = ANY (ARRAY[('fact'::character varying)::text, ('hypothesis'::character varying)::text, ('belief'::character varying)::text, ('preference'::character varying)::text, ('commitment'::character varying)::text, ('question'::character varying)::text, ('interpretation'::character varying)::text, ('instruction'::character varying)::text, ('metric'::character varying)::text, ('relationship'::character varying)::text, ('event'::character varying)::text]))
    WHEN 'memory_entry'::text THEN ((key)::text = ANY (ARRAY[('preference'::character varying)::text, ('semantic'::character varying)::text, ('episodic'::character varying)::text, ('procedural'::character varying)::text, ('project'::character varying)::text]))
    WHEN 'project_public_summary'::text THEN ((key)::text = 'project_public_summary'::text)
    WHEN 'source_item'::text THEN ((key)::text = ANY (ARRAY[('external_url'::character varying)::text, ('feed_entry'::character varying)::text, ('activity_record'::character varying)::text, ('artifact'::character varying)::text, ('run_event'::character varying)::text, ('file'::character varying)::text, ('document'::character varying)::text, ('log'::character varying)::text]))
    WHEN 'extracted_evidence'::text THEN ((key)::text = ANY (ARRAY[('document'::character varying)::text, ('excerpt'::character varying)::text, ('event'::character varying)::text, ('log'::character varying)::text, ('artifact'::character varying)::text, ('claim'::character varying)::text, ('summary'::character varying)::text]))
    ELSE false
END),
	CONSTRAINT "ck_space_object_kinds_retrieval_policy_object" CHECK (jsonb_typeof(retrieval_policy_json) = 'object'::text),
	CONSTRAINT "ck_space_object_kinds_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('active'::character varying)::text, ('deprecated'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_space_object_kinds_ui_config_object" CHECK (jsonb_typeof(ui_config_json) = 'object'::text),
	CONSTRAINT "ck_space_object_kinds_version_positive" CHECK (version >= 1)
);
--> statement-breakpoint
CREATE TABLE "space_objects" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"object_type" varchar(32) NOT NULL,
	"title" varchar(512) NOT NULL,
	"summary" text,
	"status" varchar(32) NOT NULL,
	"visibility" varchar(32) DEFAULT 'space_shared' NOT NULL,
	"owner_user_id" varchar(36),
	"primary_project_id" varchar(36),
	"workspace_id" varchar(36),
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_by_run_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"archived_at" timestamp with time zone,
	"deleted_at" timestamp with time zone,
	CONSTRAINT "space_objects_id_space_id_key" UNIQUE("id","space_id"),
	CONSTRAINT "ck_space_objects_object_type" CHECK ((object_type)::text = ANY (ARRAY[('knowledge_item'::character varying)::text, ('note'::character varying)::text, ('source'::character varying)::text, ('project'::character varying)::text, ('person'::character varying)::text, ('organization'::character varying)::text, ('relationship'::character varying)::text, ('asset'::character varying)::text, ('event'::character varying)::text, ('task'::character varying)::text, ('document'::character varying)::text, ('claim'::character varying)::text])),
	CONSTRAINT "ck_space_objects_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('active'::character varying)::text, ('disputed'::character varying)::text, ('superseded'::character varying)::text, ('rejected'::character varying)::text, ('archived'::character varying)::text, ('deleted'::character varying)::text, ('raw'::character varying)::text, ('processing'::character varying)::text, ('processed'::character varying)::text, ('error'::character varying)::text])),
	CONSTRAINT "ck_space_objects_status_by_type" CHECK (CASE (object_type)::text
    WHEN 'knowledge_item'::text THEN ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('active'::character varying)::text, ('superseded'::character varying)::text, ('archived'::character varying)::text, ('deleted'::character varying)::text]))
    WHEN 'note'::text THEN ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text, ('deleted'::character varying)::text]))
    WHEN 'source'::text THEN ((status)::text = ANY (ARRAY[('raw'::character varying)::text, ('processing'::character varying)::text, ('processed'::character varying)::text, ('archived'::character varying)::text, ('error'::character varying)::text]))
    WHEN 'claim'::text THEN ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('disputed'::character varying)::text, ('superseded'::character varying)::text, ('rejected'::character varying)::text, ('archived'::character varying)::text]))
    ELSE true
END),
	CONSTRAINT "ck_space_objects_visibility" CHECK ((visibility)::text = ANY (ARRAY[('private'::character varying)::text, ('space_shared'::character varying)::text, ('workspace_shared'::character varying)::text, ('restricted'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "memory_access_logs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"memory_id" varchar(36) NOT NULL,
	"user_id" varchar(36),
	"agent_id" varchar(36),
	"run_id" varchar(36),
	"access_type" varchar(64) NOT NULL,
	"reason" text,
	"accessed_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "memory_entries" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"scope_type" varchar(32) NOT NULL,
	"memory_type" varchar(32) NOT NULL,
	"content" text NOT NULL,
	"status" varchar(32) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"valid_from" timestamp with time zone,
	"valid_to" timestamp with time zone,
	"subject_user_id" varchar(36),
	"owner_user_id" varchar(36),
	"sensitivity_level" varchar(32) DEFAULT 'normal' NOT NULL,
	"selected_user_ids" jsonb,
	"last_confirmed_at" timestamp with time zone,
	"workspace_id" varchar(36),
	"agent_id" varchar(36),
	"namespace" varchar(255),
	"title" varchar(512),
	"visibility" varchar(32) NOT NULL,
	"confidence" double precision NOT NULL,
	"importance" double precision NOT NULL,
	"source_id" varchar(36),
	"created_by" varchar(64),
	"approved_by" varchar(64),
	"deleted_at" timestamp with time zone,
	"version" integer NOT NULL,
	"access_count" integer NOT NULL,
	"last_accessed_at" timestamp with time zone,
	"tags" jsonb,
	"memory_layer" varchar(32),
	"event_time" timestamp with time zone,
	"event_type" varchar(64),
	"last_retrieved_at" timestamp with time zone,
	"root_memory_id" varchar(36),
	"supersedes_memory_id" varchar(36),
	"source_trust" varchar(32),
	"created_from_proposal_id" varchar(36),
	"project_id" varchar(36),
	CONSTRAINT "ck_memory_entries_memory_layer" CHECK ((memory_layer IS NULL) OR ((memory_layer)::text = ANY (ARRAY[('episodic'::character varying)::text, ('semantic'::character varying)::text]))),
	CONSTRAINT "ck_memory_entries_sensitivity_level" CHECK ((sensitivity_level)::text = ANY (ARRAY[('normal'::character varying)::text, ('sensitive'::character varying)::text, ('restricted'::character varying)::text, ('highly_restricted'::character varying)::text])),
	CONSTRAINT "ck_memory_entries_source_trust" CHECK ((source_trust IS NULL) OR ((source_trust)::text = ANY (ARRAY[('user_confirmed'::character varying)::text, ('internal_system'::character varying)::text, ('trusted_external'::character varying)::text, ('untrusted_external'::character varying)::text, ('agent_inferred'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "memory_maintenance_jobs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36) NOT NULL,
	"status" varchar(32) DEFAULT 'pending' NOT NULL,
	"review_scope" varchar(32) DEFAULT 'private' NOT NULL,
	"scan_options_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"cursor" varchar(256),
	"total_scanned" integer DEFAULT 0 NOT NULL,
	"total_findings" integer DEFAULT 0 NOT NULL,
	"last_report_artifact_id" varchar(36),
	"last_packet_proposal_id" varchar(36),
	"error_message" text,
	"run_after" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"completed_at" timestamp with time zone,
	CONSTRAINT "ck_memory_maintenance_jobs_total_scanned" CHECK (total_scanned >= 0),
	CONSTRAINT "ck_memory_maintenance_jobs_status" CHECK ((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('running'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text])),
	CONSTRAINT "ck_memory_maintenance_jobs_review_scope" CHECK ((review_scope)::text = ANY (ARRAY[('private'::character varying)::text, ('space_ops'::character varying)::text])),
	CONSTRAINT "ck_memory_maintenance_jobs_total_findings" CHECK (total_findings >= 0)
);
--> statement-breakpoint
CREATE TABLE "memory_relations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_type" varchar(64) NOT NULL,
	"source_id" varchar(36) NOT NULL,
	"target_type" varchar(64) NOT NULL,
	"target_id" varchar(36) NOT NULL,
	"relation_type" varchar(64) NOT NULL,
	"confidence" double precision,
	"evidence_json" jsonb,
	"created_from_proposal_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_memory_relations_relation_type" CHECK ((relation_type)::text = ANY (ARRAY[('derived_from'::character varying)::text, ('supersedes'::character varying)::text, ('contradicts'::character varying)::text, ('related_to'::character varying)::text, ('caused_by'::character varying)::text, ('supports'::character varying)::text, ('applies_to'::character varying)::text, ('mentions'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "provenance_links" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"target_type" varchar(64) NOT NULL,
	"target_id" varchar(36) NOT NULL,
	"source_type" varchar(64) NOT NULL,
	"source_id" varchar(36) NOT NULL,
	"source_trust" varchar(32),
	"evidence_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_provenance_links_source_trust" CHECK ((source_trust IS NULL) OR ((source_trust)::text = ANY (ARRAY[('user_confirmed'::character varying)::text, ('internal_system'::character varying)::text, ('trusted_external'::character varying)::text, ('untrusted_external'::character varying)::text, ('agent_inferred'::character varying)::text]))),
	CONSTRAINT "ck_provenance_links_source_type" CHECK ((source_type)::text = ANY (ARRAY[('activity'::character varying)::text, ('proposal'::character varying)::text, ('memory'::character varying)::text, ('artifact'::character varying)::text, ('run_step'::character varying)::text, ('external_source'::character varying)::text, ('user_confirmation'::character varying)::text, ('source_item'::character varying)::text, ('source_snapshot'::character varying)::text, ('extracted_evidence'::character varying)::text, ('run_event'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "participation_records" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"personal_space_id" varchar(36) NOT NULL,
	"source_space_id" varchar(36) NOT NULL,
	"source_object_type" varchar(64) NOT NULL,
	"source_object_id" varchar(36) NOT NULL,
	"role" varchar(64) NOT NULL,
	"occurred_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "personal_memory_grant_events" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"grant_id" varchar(36) NOT NULL,
	"event_type" varchar(64) NOT NULL,
	"actor_user_id" varchar(36),
	"run_id" varchar(36),
	"proposal_id" varchar(36),
	"source_space_id" varchar(36),
	"target_space_id" varchar(36),
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_personal_memory_grant_events_event_type" CHECK ((event_type)::text = ANY (ARRAY[('created'::character varying)::text, ('previewed'::character varying)::text, ('consuming'::character varying)::text, ('used'::character varying)::text, ('revoked'::character varying)::text, ('expired'::character varying)::text, ('failed'::character varying)::text, ('denied'::character varying)::text, ('egress_proposal_created'::character varying)::text, ('egress_approved'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "personal_memory_grants" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"granting_user_id" varchar(36) NOT NULL,
	"personal_space_id" varchar(36) NOT NULL,
	"target_space_id" varchar(36) NOT NULL,
	"target_run_id" varchar(36) NOT NULL,
	"target_agent_id" varchar(36),
	"grant_scope" varchar(32) NOT NULL,
	"access_mode" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"memory_filter_json" jsonb,
	"read_expires_at" timestamp with time zone NOT NULL,
	"egress_review_expires_at" timestamp with time zone,
	"consume_started_at" timestamp with time zone,
	"revoked_at" timestamp with time zone,
	"used_at" timestamp with time zone,
	"failed_at" timestamp with time zone,
	"failure_stage" varchar(64),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_personal_memory_grants_access_mode" CHECK ((access_mode)::text = 'summary_only'::text),
	CONSTRAINT "ck_personal_memory_grants_grant_scope" CHECK ((grant_scope)::text = 'run'::text),
	CONSTRAINT "ck_personal_memory_grants_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('consuming'::character varying)::text, ('used'::character varying)::text, ('revoked'::character varying)::text, ('expired'::character varying)::text, ('failed'::character varying)::text])),
	CONSTRAINT "ck_personal_memory_grants_target_agent_id_null" CHECK (target_agent_id IS NULL)
);
--> statement-breakpoint
CREATE TABLE "code_patch_snapshots" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"proposal_id" varchar(36) NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36) NOT NULL,
	"files_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"status" varchar(32) DEFAULT 'available' NOT NULL,
	"rolled_back_by_user_id" varchar(36),
	"rolled_back_at" timestamp with time zone,
	CONSTRAINT "ck_code_patch_snapshots_status" CHECK ((status)::text = ANY (ARRAY[('available'::character varying)::text, ('rolled_back'::character varying)::text, ('pruned'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "official_plugin_enablements" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"user_id" varchar(36),
	"plugin_id" varchar(128) NOT NULL,
	"enabled" boolean NOT NULL,
	"visible" boolean DEFAULT true NOT NULL,
	"settings_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"enabled_at" timestamp with time zone,
	"enabled_by_user_id" varchar(36),
	"disabled_at" timestamp with time zone,
	"disabled_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "official_plugin_enablements_settings_is_object" CHECK (jsonb_typeof(settings_json) = 'object'::text),
	CONSTRAINT "official_plugin_enablements_plugin_id_non_empty" CHECK ((plugin_id)::text <> ''::text),
	CONSTRAINT "official_plugin_enablements_scope_check" CHECK (((space_id IS NOT NULL) AND (user_id IS NULL)) OR ((space_id IS NULL) AND (user_id IS NOT NULL)))
);
--> statement-breakpoint
CREATE TABLE "official_plugin_events" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"plugin_id" varchar(128) NOT NULL,
	"event_type" varchar(64) NOT NULL,
	"actor_user_id" varchar(36),
	"target_user_id" varchar(36),
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "official_plugin_events_event_type_non_empty" CHECK ((event_type)::text <> ''::text),
	CONSTRAINT "official_plugin_events_metadata_is_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text),
	CONSTRAINT "official_plugin_events_plugin_id_non_empty" CHECK ((plugin_id)::text <> ''::text)
);
--> statement-breakpoint
CREATE TABLE "plugin_installs" (
	"id" varchar(36) PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"plugin_id" varchar(64) NOT NULL,
	"installed_version" varchar(32) NOT NULL,
	"status" varchar(16) DEFAULT 'active' NOT NULL,
	"source" varchar(16) DEFAULT 'official' NOT NULL,
	"installed_at" timestamp with time zone DEFAULT now() NOT NULL,
	"installed_by_user_id" varchar(36),
	"package_hash" text,
	"manifest_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	CONSTRAINT "plugin_installs_plugin_id_unique" UNIQUE("plugin_id"),
	CONSTRAINT "plugin_installs_plugin_id_nonempty" CHECK (length(TRIM(BOTH FROM (plugin_id)::text)) > 0),
	CONSTRAINT "plugin_installs_source_valid" CHECK ((source)::text = ANY ((ARRAY['built_in'::character varying, 'official'::character varying, 'local'::character varying])::text[])),
	CONSTRAINT "plugin_installs_status_valid" CHECK ((status)::text = ANY ((ARRAY['active'::character varying, 'disabled'::character varying, 'removed'::character varying])::text[]))
);
--> statement-breakpoint
CREATE TABLE "plugin_migrations" (
	"id" varchar(36) PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"plugin_id" varchar(64) NOT NULL,
	"plugin_version" varchar(32) NOT NULL,
	"migration_id" varchar(128) NOT NULL,
	"checksum" text,
	"applied_at" timestamp with time zone DEFAULT now() NOT NULL,
	"status" varchar(16) DEFAULT 'applied' NOT NULL,
	"error_message" text,
	CONSTRAINT "plugin_migrations_unique" UNIQUE("migration_id","plugin_id"),
	CONSTRAINT "plugin_migrations_status_valid" CHECK ((status)::text = ANY ((ARRAY['applied'::character varying, 'failed'::character varying])::text[]))
);
--> statement-breakpoint
CREATE TABLE "policies" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"name" varchar(256) NOT NULL,
	"domain" varchar(64) NOT NULL,
	"policy_json" jsonb NOT NULL,
	"enabled" boolean NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"policy_key" varchar(256),
	"policy_version" integer DEFAULT 1 NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"enforcement_mode" varchar(32),
	"priority" integer DEFAULT 0 NOT NULL,
	"rule_json" jsonb,
	"applies_to_json" jsonb,
	"supersedes_policy_id" varchar(36),
	"created_from_proposal_id" varchar(36),
	CONSTRAINT "ck_policies_enforcement_mode" CHECK ((enforcement_mode IS NULL) OR ((enforcement_mode)::text = ANY (ARRAY[('allow'::character varying)::text, ('deny'::character varying)::text, ('require_approval'::character varying)::text, ('allow_with_log'::character varying)::text]))),
	CONSTRAINT "ck_policies_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('active'::character varying)::text, ('superseded'::character varying)::text, ('disabled'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "policy_decision_records" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"actor_type" varchar(64),
	"actor_id" varchar(36),
	"actor_ref_json" jsonb,
	"action" varchar(128) NOT NULL,
	"resource_type" varchar(64),
	"resource_id" varchar(256),
	"decision" varchar(32) NOT NULL,
	"risk_level" varchar(32) NOT NULL,
	"required_approver_role" varchar(32),
	"approval_capability" varchar(128),
	"policy_rule_id" varchar(128),
	"policy_source" varchar(64),
	"policy_id" varchar(36),
	"audit_code" varchar(128),
	"run_id" varchar(36),
	"proposal_id" varchar(36),
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_policy_decision_records_space_id_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_policy_decision_records_decision" CHECK ((decision)::text = ANY (ARRAY[('allow'::character varying)::text, ('deny'::character varying)::text, ('require_approval'::character varying)::text])),
	CONSTRAINT "ck_policy_decision_records_risk_level" CHECK ((risk_level)::text = ANY (ARRAY[('low'::character varying)::text, ('medium'::character varying)::text, ('high'::character varying)::text, ('critical'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "prompt_deployment_refs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36),
	"asset_id" varchar(36) NOT NULL,
	"scope_type" varchar(16) NOT NULL,
	"scope_id" varchar(36),
	"label" varchar(64) NOT NULL,
	"version_id" varchar(36) NOT NULL,
	"status" varchar(16) DEFAULT 'active' NOT NULL,
	"promoted_by_user_id" varchar(36),
	"promoted_from_proposal_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_prompt_deployment_refs_label" CHECK ((label)::text ~ '^[a-z][a-z0-9_.-]{0,63}$'::text),
	CONSTRAINT "ck_prompt_deployment_refs_scope_type" CHECK ((scope_type)::text = ANY (ARRAY[('system'::character varying)::text, ('space'::character varying)::text, ('project'::character varying)::text, ('user'::character varying)::text, ('agent'::character varying)::text])),
	CONSTRAINT "ck_prompt_deployment_refs_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_prompt_deployment_refs_scope_id" CHECK ((((scope_type)::text = 'system'::text) AND (scope_id IS NULL)) OR (((scope_type)::text <> 'system'::text) AND (scope_id IS NOT NULL))),
	CONSTRAINT "ck_prompt_deployment_refs_space_id" CHECK ((((scope_type)::text = 'system'::text) AND (space_id IS NULL)) OR (((scope_type)::text <> 'system'::text) AND (space_id IS NOT NULL)))
);
--> statement-breakpoint
CREATE TABLE "project_corpus_items" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"object_id" varchar(36),
	"source_item_id" varchar(36),
	"evidence_id" varchar(36),
	"source_connection_id" varchar(36),
	"source_decision_id" varchar(36),
	"role" varchar(32) DEFAULT 'candidate' NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"triage_status" varchar(32) DEFAULT 'new' NOT NULL,
	"triage_confirmed_by_user" boolean DEFAULT false NOT NULL,
	"read_status" varchar(32) DEFAULT 'unread' NOT NULL,
	"relevance" varchar(32),
	"confidence" double precision,
	"reason" text,
	"added_by_user_id" varchar(36),
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"last_reviewed_at" timestamp with time zone,
	"last_read_at" timestamp with time zone,
	CONSTRAINT "uq_project_corpus_items_id_space_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_project_corpus_items_confidence" CHECK ((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
	CONSTRAINT "ck_project_corpus_items_has_target" CHECK (object_id IS NOT NULL OR source_item_id IS NOT NULL OR evidence_id IS NOT NULL),
	CONSTRAINT "ck_project_corpus_items_metadata_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text),
	CONSTRAINT "ck_project_corpus_items_read_status" CHECK ((read_status)::text = ANY (ARRAY[('unread'::character varying)::text, ('skimmed'::character varying)::text, ('read'::character varying)::text, ('discussed'::character varying)::text])),
	CONSTRAINT "ck_project_corpus_items_relevance" CHECK ((relevance IS NULL) OR ((relevance)::text = ANY (ARRAY[('relevant'::character varying)::text, ('maybe'::character varying)::text, ('not_relevant'::character varying)::text]))),
	CONSTRAINT "ck_project_corpus_items_role" CHECK ((role)::text = ANY (ARRAY[('candidate'::character varying)::text, ('reference'::character varying)::text, ('primary'::character varying)::text, ('related'::character varying)::text, ('background'::character varying)::text])),
	CONSTRAINT "ck_project_corpus_items_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_project_corpus_items_triage_status" CHECK ((triage_status)::text = ANY (ARRAY[('new'::character varying)::text, ('relevant'::character varying)::text, ('maybe'::character varying)::text, ('excluded'::character varying)::text, ('included'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "project_experiment_campaigns" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36) NOT NULL,
	"name" varchar(256) NOT NULL,
	"research_question" text,
	"hypothesis_scope" text,
	"status" varchar(16) DEFAULT 'draft' NOT NULL,
	"editable_scope_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"protected_scope_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"setup_commands_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"run_command" text,
	"metric_parser_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"time_budget_seconds" integer,
	"timeout_seconds" integer,
	"resource_budget_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"baseline_run_id" varchar(36),
	"best_run_id" varchar(36),
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_project_experiment_campaigns_id_space_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_project_experiment_campaigns_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('active'::character varying)::text, ('paused'::character varying)::text, ('completed'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_project_experiment_campaigns_editable_scope_array" CHECK (jsonb_typeof(editable_scope_json) = 'array'::text),
	CONSTRAINT "ck_project_experiment_campaigns_protected_scope_array" CHECK (jsonb_typeof(protected_scope_json) = 'array'::text),
	CONSTRAINT "ck_project_experiment_campaigns_setup_commands_array" CHECK (jsonb_typeof(setup_commands_json) = 'array'::text)
);
--> statement-breakpoint
CREATE TABLE "project_experiment_provenance" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"campaign_id" varchar(36),
	"experiment_key" varchar(160) NOT NULL,
	"planned_summary" text,
	"executed_summary" text,
	"negative_results" text,
	"limitations" text,
	"repro_lock_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"linked_artifact_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"linked_run_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_experiment_provenance_linked_artifact_ids_array" CHECK (jsonb_typeof(linked_artifact_ids_json) = 'array'::text),
	CONSTRAINT "ck_project_experiment_provenance_linked_run_ids_array" CHECK (jsonb_typeof(linked_run_ids_json) = 'array'::text)
);
--> statement-breakpoint
CREATE TABLE "project_experiment_runs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"campaign_id" varchar(36) NOT NULL,
	"run_id" varchar(36),
	"workspace_id" varchar(36) NOT NULL,
	"is_baseline" boolean DEFAULT false NOT NULL,
	"hypothesis" text,
	"patch_summary" text,
	"commit_ref" varchar(128),
	"status" varchar(16) DEFAULT 'queued' NOT NULL,
	"metrics_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"primary_metric_name" varchar(128),
	"primary_metric_value" double precision,
	"decision_reason" text,
	"artifact_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_project_experiment_runs_id_space_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_project_experiment_runs_status" CHECK ((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('keep'::character varying)::text, ('discard'::character varying)::text, ('crash'::character varying)::text, ('cancelled'::character varying)::text])),
	CONSTRAINT "ck_project_experiment_runs_metrics_object" CHECK (jsonb_typeof(metrics_json) = 'object'::text),
	CONSTRAINT "ck_project_experiment_runs_artifact_ids_array" CHECK (jsonb_typeof(artifact_ids_json) = 'array'::text)
);
--> statement-breakpoint
CREATE TABLE "project_research_artifact_links" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"workflow_id" varchar(36),
	"stage_key" varchar(64),
	"artifact_id" varchar(36) NOT NULL,
	"artifact_type" varchar(32) NOT NULL,
	"created_by_user_id" varchar(36),
	"created_by_run_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_research_artifact_links_artifact_type" CHECK ((artifact_type)::text = ANY (ARRAY[('rq_brief'::character varying)::text, ('methodology_blueprint'::character varying)::text, ('search_strategy'::character varying)::text, ('annotated_bibliography'::character varying)::text, ('literature_matrix'::character varying)::text, ('synthesis_report'::character varying)::text, ('integrity_report'::character varying)::text, ('outline'::character varying)::text, ('draft'::character varying)::text, ('review_package'::character varying)::text, ('revision_plan'::character varying)::text, ('final_export'::character varying)::text, ('process_summary'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "project_research_checkpoints" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"workflow_id" varchar(36) NOT NULL,
	"stage_key" varchar(64) NOT NULL,
	"checkpoint_type" varchar(32) NOT NULL,
	"status" varchar(16) DEFAULT 'pending' NOT NULL,
	"machine_result_json" jsonb,
	"user_decision" varchar(16),
	"decision_reason" text,
	"decided_by_user_id" varchar(36),
	"decided_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_research_checkpoints_checkpoint_type" CHECK ((checkpoint_type)::text = ANY (ARRAY[('profile_approval'::character varying)::text, ('screening_gate'::character varying)::text, ('integrity_gate'::character varying)::text, ('manuscript_gate'::character varying)::text, ('review_gate'::character varying)::text, ('other'::character varying)::text])),
	CONSTRAINT "ck_project_research_checkpoints_status" CHECK ((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('approved'::character varying)::text, ('rejected'::character varying)::text, ('waived'::character varying)::text])),
	CONSTRAINT "ck_project_research_checkpoints_user_decision" CHECK ((user_decision IS NULL) OR ((user_decision)::text = ANY (ARRAY[('approved'::character varying)::text, ('rejected'::character varying)::text, ('waived'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "project_research_claim_links" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"workflow_id" varchar(36),
	"claim_id" varchar(36) NOT NULL,
	"support_status" varchar(32) DEFAULT 'unsupported' NOT NULL,
	"planned_experiment_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"citation_anchors_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"unresolved_gap" boolean DEFAULT false NOT NULL,
	"gap_reason" text,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_research_claim_links_support_status" CHECK ((support_status)::text = ANY (ARRAY[('unsupported'::character varying)::text, ('supported'::character varying)::text, ('partial'::character varying)::text, ('gap_declared'::character varying)::text])),
	CONSTRAINT "ck_project_research_claim_links_planned_experiment_ids_array" CHECK (jsonb_typeof(planned_experiment_ids_json) = 'array'::text),
	CONSTRAINT "ck_project_research_claim_links_citation_anchors_array" CHECK (jsonb_typeof(citation_anchors_json) = 'array'::text)
);
--> statement-breakpoint
CREATE TABLE "project_research_profiles" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"preset_key" varchar(64) DEFAULT 'academic_research' NOT NULL,
	"research_question" text,
	"working_title" varchar(512),
	"domain" varchar(128),
	"output_type" varchar(32),
	"paper_type" varchar(32),
	"citation_style" varchar(32),
	"target_venue" varchar(256),
	"language" varchar(16) DEFAULT 'en' NOT NULL,
	"experiment_intake_declaration" varchar(32) DEFAULT 'undecided' NOT NULL,
	"status" varchar(16) DEFAULT 'draft' NOT NULL,
	"approved_by_user_id" varchar(36),
	"approved_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_research_profiles_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('approved'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_project_research_profiles_output_type" CHECK ((output_type IS NULL) OR ((output_type)::text = ANY (ARRAY[('paper'::character varying)::text, ('thesis'::character varying)::text, ('report'::character varying)::text, ('review'::character varying)::text, ('proposal'::character varying)::text, ('other'::character varying)::text]))),
	CONSTRAINT "ck_project_research_profiles_paper_type" CHECK ((paper_type IS NULL) OR ((paper_type)::text = ANY (ARRAY[('empirical'::character varying)::text, ('theory'::character varying)::text, ('survey'::character varying)::text, ('review'::character varying)::text, ('position'::character varying)::text, ('case_study'::character varying)::text, ('other'::character varying)::text]))),
	CONSTRAINT "ck_project_research_profiles_citation_style" CHECK ((citation_style IS NULL) OR ((citation_style)::text = ANY (ARRAY[('apa'::character varying)::text, ('mla'::character varying)::text, ('chicago'::character varying)::text, ('ieee'::character varying)::text, ('acm'::character varying)::text, ('vancouver'::character varying)::text, ('other'::character varying)::text]))),
	CONSTRAINT "ck_project_research_profiles_experiment_intake" CHECK ((experiment_intake_declaration)::text = ANY (ARRAY[('none'::character varying)::text, ('code_experiments'::character varying)::text, ('human_study'::character varying)::text, ('both'::character varying)::text, ('undecided'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "project_research_screening_criteria" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"include_keywords_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"exclude_keywords_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"methods_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"date_range_start" timestamp with time zone,
	"date_range_end" timestamp with time zone,
	"venues_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"required_evidence_fields_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_research_screening_criteria_include_keywords_array" CHECK (jsonb_typeof(include_keywords_json) = 'array'::text),
	CONSTRAINT "ck_project_research_screening_criteria_exclude_keywords_array" CHECK (jsonb_typeof(exclude_keywords_json) = 'array'::text),
	CONSTRAINT "ck_project_research_screening_criteria_methods_array" CHECK (jsonb_typeof(methods_json) = 'array'::text),
	CONSTRAINT "ck_project_research_screening_criteria_venues_array" CHECK (jsonb_typeof(venues_json) = 'array'::text),
	CONSTRAINT "ck_project_research_screening_criteria_evidence_fields_array" CHECK (jsonb_typeof(required_evidence_fields_json) = 'array'::text),
	CONSTRAINT "ck_project_research_screening_criteria_date_range" CHECK ((date_range_start IS NULL) OR (date_range_end IS NULL) OR (date_range_start <= date_range_end))
);
--> statement-breakpoint
CREATE TABLE "project_research_workflows" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"workflow_type" varchar(32) NOT NULL,
	"current_stage" varchar(64),
	"status" varchar(16) DEFAULT 'active' NOT NULL,
	"mode" varchar(16) DEFAULT 'manual' NOT NULL,
	"state_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"started_by_user_id" varchar(36),
	"started_run_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_project_research_workflows_id_space_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_project_research_workflows_workflow_type" CHECK ((workflow_type)::text = ANY (ARRAY[('literature_review'::character varying)::text, ('empirical_paper'::character varying)::text, ('theory_paper'::character varying)::text, ('paper_review'::character varying)::text, ('revision'::character varying)::text])),
	CONSTRAINT "ck_project_research_workflows_status" CHECK ((status)::text = ANY (ARRAY[('not_started'::character varying)::text, ('active'::character varying)::text, ('paused'::character varying)::text, ('completed'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_project_research_workflows_mode" CHECK ((mode)::text = ANY (ARRAY[('manual'::character varying)::text, ('agent_assisted'::character varying)::text, ('autonomous'::character varying)::text])),
	CONSTRAINT "ck_project_research_workflows_state_object" CHECK (jsonb_typeof(state_json) = 'object'::text)
);
--> statement-breakpoint
CREATE TABLE "project_members" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"role" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_members_role" CHECK ((role)::text = ANY (ARRAY[('owner'::character varying)::text, ('member'::character varying)::text, ('viewer'::character varying)::text])),
	CONSTRAINT "ck_project_members_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('invited'::character varying)::text, ('revoked'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "project_public_summaries" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"summary_text" text NOT NULL,
	"topics_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"highlights_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"source_refs_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"redaction_version" varchar(64) NOT NULL,
	"review_status" varchar(32) DEFAULT 'pending' NOT NULL,
	"updated_by_user_id" varchar(36),
	"generated_by_run_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_project_public_summaries_highlights_array" CHECK (jsonb_typeof(highlights_json) = 'array'::text),
	CONSTRAINT "ck_project_public_summaries_review_status" CHECK ((review_status)::text = ANY (ARRAY[('draft'::character varying)::text, ('approved'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_project_public_summaries_source_refs_array" CHECK (jsonb_typeof(source_refs_json) = 'array'::text),
	CONSTRAINT "ck_project_public_summaries_topics_array" CHECK (jsonb_typeof(topics_json) = 'array'::text)
);
--> statement-breakpoint
CREATE TABLE "projects" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36),
	"name" varchar(256) NOT NULL,
	"description" text,
	"status" varchar(32) NOT NULL,
	"current_focus" text,
	"settings_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"archived_at" timestamp with time zone,
	"deleted_at" timestamp with time zone,
	CONSTRAINT "uq_projects_space_id_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_projects_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text, ('deleted'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "proposal_approvals" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"proposal_id" varchar(36) NOT NULL,
	"approval_type" varchar(64) NOT NULL,
	"approver_user_id" varchar(36) NOT NULL,
	"grant_id" varchar(36),
	"target_space_id" varchar(36),
	"status" varchar(32) NOT NULL,
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"revoked_at" timestamp with time zone,
	CONSTRAINT "ck_proposal_approvals_approval_type" CHECK ((approval_type)::text = 'egress_granting_user'::text),
	CONSTRAINT "ck_proposal_approvals_status" CHECK ((status)::text = ANY (ARRAY[('approved'::character varying)::text, ('revoked'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "proposals" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"created_by_run_id" varchar(36),
	"proposal_type" varchar(64) NOT NULL,
	"status" varchar(32) NOT NULL,
	"risk_level" varchar(32) NOT NULL,
	"urgency" varchar(32) NOT NULL,
	"preview" boolean DEFAULT false NOT NULL,
	"title" varchar(512) NOT NULL,
	"summary" text,
	"payload_json" jsonb NOT NULL,
	"review_deadline" timestamp with time zone,
	"expires_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"reviewed_at" timestamp with time zone,
	"reviewed_by" varchar(36),
	"workspace_id" varchar(36),
	"rationale" text,
	"created_by_agent_id" varchar(36),
	"created_by_user_id" varchar(36),
	"required_approver_role" varchar(64),
	"visibility" varchar(32) DEFAULT 'space_shared' NOT NULL,
	"project_id" varchar(36),
	CONSTRAINT "ck_proposals_risk_level" CHECK ((risk_level)::text = ANY (ARRAY[('low'::character varying)::text, ('medium'::character varying)::text, ('high'::character varying)::text, ('critical'::character varying)::text])),
	CONSTRAINT "ck_proposals_urgency" CHECK ((urgency)::text = ANY (ARRAY[('low'::character varying)::text, ('normal'::character varying)::text, ('high'::character varying)::text, ('critical'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "credentials" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36),
	"name" varchar(256) NOT NULL,
	"credential_type" varchar(64) NOT NULL,
	"secret_ref" text NOT NULL,
	"scopes_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "model_provider_credentials" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"provider_id" varchar(36) NOT NULL,
	"credential_id" varchar(36) NOT NULL,
	"position" integer NOT NULL,
	"enabled" boolean NOT NULL,
	"healthy" boolean NOT NULL,
	"cooldown_until" timestamp with time zone,
	"last_failure_class" varchar(32),
	"request_count" bigint NOT NULL,
	"failure_count" bigint NOT NULL,
	"last_used_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_model_provider_credentials_provider_credential" UNIQUE("credential_id","provider_id"),
	CONSTRAINT "ck_model_provider_credentials_failure_class" CHECK (((last_failure_class)::text = ANY (ARRAY[('rate_limit'::character varying)::text, ('payment_required'::character varying)::text, ('unauthorized'::character varying)::text, ('quota_exhausted'::character varying)::text, ('transient'::character varying)::text, ('permanent'::character varying)::text])) OR (last_failure_class IS NULL))
);
--> statement-breakpoint
CREATE TABLE "model_provider_space_grants" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"provider_id" varchar(36) NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36),
	"granted_by_user_id" varchar(36),
	"enabled" boolean NOT NULL,
	"is_default" boolean NOT NULL,
	"network_profile_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_model_provider_space_grants_provider_space" UNIQUE("provider_id","space_id")
);
--> statement-breakpoint
CREATE TABLE "model_providers" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36),
	"name" varchar(128) NOT NULL,
	"provider_type" varchar(64) NOT NULL,
	"base_url" varchar(512),
	"network_profile_id" varchar(36),
	"default_model" varchar(256),
	"enabled" boolean NOT NULL,
	"credential_id" varchar(36),
	"capabilities_json" jsonb NOT NULL,
	"config_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "network_profiles" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"name" varchar(128) NOT NULL,
	"mode" varchar(32) NOT NULL,
	"proxy_url" varchar(512),
	"no_proxy" text,
	"enabled" boolean NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_network_profiles_mode" CHECK ((mode)::text = ANY (ARRAY[('direct'::character varying)::text, ('http_proxy'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "provider_task_policies" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"task" varchar(64) NOT NULL,
	"chain_json" jsonb NOT NULL,
	"enabled" boolean NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_provider_task_policies_space_task" UNIQUE("space_id","task")
);
--> statement-breakpoint
CREATE TABLE "relation_affiliations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"person_object_id" varchar(36) NOT NULL,
	"organization_object_id" varchar(36) NOT NULL,
	"role" varchar(128),
	"title" varchar(256),
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"start_date" timestamp with time zone,
	"end_date" timestamp with time zone,
	"confidence" double precision,
	"source" varchar(32) DEFAULT 'manual' NOT NULL,
	"object_relation_id" varchar(36),
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_relation_affiliations_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('past'::character varying)::text, ('unknown'::character varying)::text])),
	CONSTRAINT "ck_relation_affiliations_source" CHECK ((source)::text = ANY (ARRAY[('manual'::character varying)::text, ('import'::character varying)::text, ('source_sync'::character varying)::text, ('agent'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "relation_identities" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"object_id" varchar(36) NOT NULL,
	"id_type" varchar(32) NOT NULL,
	"id_value" varchar(512) NOT NULL,
	"is_primary" boolean DEFAULT false NOT NULL,
	"confidence" double precision,
	"source" varchar(32) DEFAULT 'manual' NOT NULL,
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_relation_identities_id_type" CHECK ((id_type)::text = ANY (ARRAY[('email'::character varying)::text, ('url'::character varying)::text, ('phone'::character varying)::text, ('orcid'::character varying)::text, ('github'::character varying)::text, ('twitter'::character varying)::text, ('linkedin'::character varying)::text, ('other'::character varying)::text])),
	CONSTRAINT "ck_relation_identities_source" CHECK ((source)::text = ANY (ARRAY[('manual'::character varying)::text, ('import'::character varying)::text, ('source_sync'::character varying)::text, ('agent'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "relation_notes" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"object_id" varchar(36) NOT NULL,
	"body" text NOT NULL,
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "relation_organizations" (
	"object_id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"org_type" varchar(32) DEFAULT 'other' NOT NULL,
	"homepage_url" text,
	"parent_organization_object_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "relation_organizations_object_id_space_id_key" UNIQUE("object_id","space_id"),
	CONSTRAINT "ck_relation_organizations_org_type" CHECK ((org_type)::text = ANY (ARRAY[('company'::character varying)::text, ('university'::character varying)::text, ('lab'::character varying)::text, ('research_group'::character varying)::text, ('nonprofit'::character varying)::text, ('government'::character varying)::text, ('community'::character varying)::text, ('family'::character varying)::text, ('other'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "relation_people" (
	"object_id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"pronouns" varchar(32),
	"headline" varchar(256),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "relation_people_object_id_space_id_key" UNIQUE("object_id","space_id")
);
--> statement-breakpoint
CREATE TABLE "relation_source_links" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"object_id" varchar(36) NOT NULL,
	"link_type" varchar(32) NOT NULL,
	"activity_id" varchar(36),
	"source_item_id" varchar(36),
	"evidence_id" varchar(36),
	"external_ref" text,
	"note" text,
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_relation_source_links_link_type" CHECK ((link_type)::text = ANY (ARRAY[('activity'::character varying)::text, ('source_item'::character varying)::text, ('evidence'::character varying)::text, ('external'::character varying)::text, ('import'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "retrieval_aliases" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"retrieval_object_id" varchar(36) NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"object_type" "retrieval_object_type" NOT NULL,
	"object_id" varchar(36) NOT NULL,
	"alias" text NOT NULL,
	"normalized_alias" text NOT NULL,
	"alias_kind" varchar(32) NOT NULL,
	"confidence" double precision NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_retrieval_aliases_confidence" CHECK ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))
);
--> statement-breakpoint
CREATE TABLE "retrieval_chunks" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"retrieval_object_id" varchar(36) NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"object_type" "retrieval_object_type" NOT NULL,
	"object_id" varchar(36) NOT NULL,
	"chunk_index" integer NOT NULL,
	"plain_text" text NOT NULL,
	"tsv" "tsvector",
	"content_hash" varchar(64) NOT NULL,
	"embedding" vector,
	"embedding_model" varchar(128),
	"embedding_dimensions" integer,
	"embedding_generated_at" timestamp with time zone,
	"embedding_claim_id" varchar(64),
	"embedding_claimed_at" timestamp with time zone,
	"embedding_attempts" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_retrieval_chunks_embedding_dimensions" CHECK (((embedding IS NULL) AND (embedding_dimensions IS NULL)) OR ((embedding IS NOT NULL) AND (embedding_dimensions = vector_dims(embedding)) AND (embedding_dimensions >= 1) AND (embedding_dimensions <= 4096)))
);
--> statement-breakpoint
CREATE TABLE "retrieval_edges" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"from_object_type" "retrieval_object_type" NOT NULL,
	"from_object_id" varchar(36) NOT NULL,
	"to_object_type" "retrieval_object_type" NOT NULL,
	"to_object_id" varchar(36) NOT NULL,
	"relation_type" varchar(64) NOT NULL,
	"edge_origin" varchar(64) NOT NULL,
	"edge_status" varchar(32) NOT NULL,
	"confidence" double precision NOT NULL,
	"evidence_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_retrieval_edges_confidence" CHECK ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)),
	CONSTRAINT "ck_retrieval_edges_status" CHECK ((edge_status)::text = ANY (ARRAY[('derived'::character varying)::text, ('suggested'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "retrieval_feedback_events" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"actor_user_id" varchar(36) NOT NULL,
	"surface" varchar(64) NOT NULL,
	"query_hash" varchar(64) NOT NULL,
	"object_type" "retrieval_object_type" NOT NULL,
	"object_id" varchar(36) NOT NULL,
	"signal_type" varchar(32) NOT NULL,
	"dwell_ms" integer,
	"metadata_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_retrieval_feedback_events_dwell_ms" CHECK ((dwell_ms IS NULL) OR (dwell_ms >= 0)),
	CONSTRAINT "ck_retrieval_feedback_events_signal_type" CHECK ((signal_type)::text = ANY (ARRAY[('opened'::character varying)::text, ('dwell'::character varying)::text, ('used'::character varying)::text, ('explicit_relevant'::character varying)::text, ('accepted'::character varying)::text, ('pinned'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "retrieval_objects" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"object_type" "retrieval_object_type" NOT NULL,
	"object_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36),
	"owner_user_id" varchar(36),
	"visibility" varchar(32),
	"status" varchar(32) NOT NULL,
	"title" varchar(512) NOT NULL,
	"slug" varchar(512),
	"object_kind" varchar(64),
	"content_hash" varchar(64) NOT NULL,
	"source_connection_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"indexed_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"source_updated_at" timestamp with time zone,
	CONSTRAINT "ck_retrieval_objects_source_connections_array" CHECK (jsonb_typeof(source_connection_ids_json) = 'array'::text)
);
--> statement-breakpoint
CREATE TABLE "external_run_records" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"run_id" varchar(36) NOT NULL,
	"vendor" varchar(64) NOT NULL,
	"vendor_run_id" varchar(256),
	"runtime_adapter_type" varchar(64),
	"external_url" text,
	"observability_level" varchar(64) DEFAULT 'black_box' NOT NULL,
	"data_exposure_level" varchar(64) DEFAULT 'unknown' NOT NULL,
	"trace_available" boolean DEFAULT false NOT NULL,
	"raw_summary" text,
	"raw_output_uri" varchar(1024),
	"imported_diff_uri" varchar(1024),
	"imported_artifacts_json" jsonb,
	"imported_logs_uri" varchar(1024),
	"status" varchar(32) DEFAULT 'imported' NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_external_run_records_data_exposure_level" CHECK ((data_exposure_level)::text = ANY (ARRAY[('local_only'::character varying)::text, ('model_provider'::character varying)::text, ('vendor_platform'::character varying)::text, ('third_party_tools'::character varying)::text, ('unknown'::character varying)::text])),
	CONSTRAINT "ck_external_run_records_observability_level" CHECK ((observability_level)::text = ANY (ARRAY[('full_trace'::character varying)::text, ('structured_events'::character varying)::text, ('artifacts_only'::character varying)::text, ('final_output_only'::character varying)::text, ('black_box'::character varying)::text])),
	CONSTRAINT "ck_external_run_records_vendor" CHECK ((vendor)::text = ANY (ARRAY[('openai'::character varying)::text, ('anthropic'::character varying)::text, ('cursor'::character varying)::text, ('opencode'::character varying)::text, ('manual'::character varying)::text, ('other'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "run_evaluations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"run_id" varchar(36) NOT NULL,
	"evaluator_type" varchar(64) DEFAULT 'deterministic_harness' NOT NULL,
	"evaluator_version" varchar(64) DEFAULT 'harness_eval.v1' NOT NULL,
	"outcome_status" varchar(32) NOT NULL,
	"failure_layer" varchar(32),
	"failure_reason_code" varchar(128),
	"trajectory_status" varchar(32) NOT NULL,
	"evidence_json" jsonb,
	"rule_trace_json" jsonb,
	"notes" text,
	"evaluated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_run_evaluations_failure_layer" CHECK ((failure_layer IS NULL) OR ((failure_layer)::text = ANY (ARRAY[('context'::character varying)::text, ('sandbox'::character varying)::text, ('runtime'::character varying)::text, ('tool'::character varying)::text, ('validation'::character varying)::text, ('policy'::character varying)::text, ('task_spec'::character varying)::text, ('orchestration'::character varying)::text, ('evaluator'::character varying)::text, ('unknown'::character varying)::text]))),
	CONSTRAINT "ck_run_evaluations_outcome_status" CHECK ((outcome_status)::text = ANY (ARRAY[('passed'::character varying)::text, ('failed'::character varying)::text, ('partial'::character varying)::text, ('unknown'::character varying)::text])),
	CONSTRAINT "ck_run_evaluations_trajectory_status" CHECK ((trajectory_status)::text = ANY (ARRAY[('acceptable'::character varying)::text, ('incomplete'::character varying)::text, ('unsafe'::character varying)::text, ('insufficient_evidence'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "run_events" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"run_id" varchar(36) NOT NULL,
	"step_id" varchar(36),
	"actor_id" varchar(36),
	"event_index" integer NOT NULL,
	"event_type" varchar(64) NOT NULL,
	"status" varchar(32) NOT NULL,
	"summary" text,
	"error_code" varchar(128),
	"error_message" text,
	"workspace_id" varchar(36),
	"artifact_id" varchar(36),
	"proposal_id" varchar(36),
	"data_exposure_level" varchar(64),
	"trust_level" varchar(32),
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_run_events_space_run_event_index" UNIQUE("event_index","run_id","space_id"),
	CONSTRAINT "ck_run_events_data_exposure_level" CHECK ((data_exposure_level IS NULL) OR ((data_exposure_level)::text = ANY (ARRAY[('local_only'::character varying)::text, ('model_provider'::character varying)::text, ('vendor_platform'::character varying)::text, ('third_party_tools'::character varying)::text, ('unknown'::character varying)::text]))),
	CONSTRAINT "ck_run_events_event_type" CHECK ((event_type)::text = ANY (ARRAY[('context_compiled'::character varying)::text, ('runtime_selected'::character varying)::text, ('credential_granted'::character varying)::text, ('sandbox_created'::character varying)::text, ('policy_checked'::character varying)::text, ('adapter_invoked'::character varying)::text, ('adapter_completed'::character varying)::text, ('artifact_ingested'::character varying)::text, ('patch_collected'::character varying)::text, ('validation_started'::character varying)::text, ('validation_completed'::character varying)::text, ('proposal_created'::character varying)::text, ('evaluation_created'::character varying)::text, ('run_finalized'::character varying)::text, ('delegation_requested'::character varying)::text, ('delegation_policy_denied'::character varying)::text, ('delegation_queued'::character varying)::text, ('delegation_started'::character varying)::text, ('delegation_completed'::character varying)::text])),
	CONSTRAINT "ck_run_events_status" CHECK ((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text, ('skipped'::character varying)::text, ('warning'::character varying)::text, ('cancelled'::character varying)::text])),
	CONSTRAINT "ck_run_events_trust_level" CHECK ((trust_level IS NULL) OR ((trust_level)::text = ANY (ARRAY[('high'::character varying)::text, ('medium'::character varying)::text, ('low'::character varying)::text, ('unknown'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "run_execution_locks" (
	"run_id" varchar(36) PRIMARY KEY NOT NULL,
	"locked_at" timestamp with time zone NOT NULL,
	"worker_id" varchar(64) NOT NULL,
	"job_id" varchar(36)
);
--> statement-breakpoint
CREATE TABLE "run_finalizations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"run_id" varchar(36) NOT NULL,
	"finalizer_version" varchar(64) DEFAULT 'post_run_finalization.v1' NOT NULL,
	"status" varchar(32) NOT NULL,
	"run_evaluation_id" varchar(36),
	"task_evaluation_id" varchar(36),
	"outcome_status" varchar(32),
	"failure_layer" varchar(32),
	"failure_reason_code" varchar(128),
	"trajectory_status" varchar(32),
	"skipped_reasons_json" jsonb,
	"error_json" jsonb,
	"metadata_json" jsonb,
	"finalized_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_run_finalizations_run_version" UNIQUE("finalizer_version","run_id"),
	CONSTRAINT "ck_run_finalizations_failure_layer" CHECK ((failure_layer IS NULL) OR ((failure_layer)::text = ANY (ARRAY[('context'::character varying)::text, ('sandbox'::character varying)::text, ('runtime'::character varying)::text, ('tool'::character varying)::text, ('validation'::character varying)::text, ('policy'::character varying)::text, ('task_spec'::character varying)::text, ('orchestration'::character varying)::text, ('evaluator'::character varying)::text, ('unknown'::character varying)::text]))),
	CONSTRAINT "ck_run_finalizations_outcome_status" CHECK ((outcome_status IS NULL) OR ((outcome_status)::text = ANY (ARRAY[('passed'::character varying)::text, ('failed'::character varying)::text, ('partial'::character varying)::text, ('unknown'::character varying)::text]))),
	CONSTRAINT "ck_run_finalizations_status" CHECK ((status)::text = ANY (ARRAY[('completed'::character varying)::text, ('failed'::character varying)::text])),
	CONSTRAINT "ck_run_finalizations_trajectory_status" CHECK ((trajectory_status IS NULL) OR ((trajectory_status)::text = ANY (ARRAY[('acceptable'::character varying)::text, ('incomplete'::character varying)::text, ('unsafe'::character varying)::text, ('insufficient_evidence'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "run_steps" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"run_id" varchar(36) NOT NULL,
	"parent_step_id" varchar(36),
	"actor_id" varchar(36) NOT NULL,
	"step_index" integer NOT NULL,
	"step_type" varchar(64) NOT NULL,
	"status" varchar(32) NOT NULL,
	"title" varchar(512),
	"workspace_id" varchar(36),
	"session_id" varchar(36),
	"task_id" varchar(36),
	"artifact_id" varchar(36),
	"proposal_id" varchar(36),
	"started_at" timestamp with time zone,
	"ended_at" timestamp with time zone,
	"input_summary" text,
	"output_summary" text,
	"error_type" varchar(128),
	"error_message" text,
	"metadata_json" jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_run_steps_run_step_index" UNIQUE("run_id","step_index"),
	CONSTRAINT "ck_run_steps_status" CHECK ((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text, ('skipped'::character varying)::text, ('cancelled'::character varying)::text])),
	CONSTRAINT "ck_run_steps_step_type" CHECK ((step_type)::text = ANY (ARRAY[('run_created'::character varying)::text, ('queued'::character varying)::text, ('context_prepared'::character varying)::text, ('runtime_selected'::character varying)::text, ('adapter_started'::character varying)::text, ('adapter_completed'::character varying)::text, ('artifact_created'::character varying)::text, ('proposal_created'::character varying)::text, ('failed'::character varying)::text, ('completed'::character varying)::text, ('validation_started'::character varying)::text, ('validation_completed'::character varying)::text, ('cancelled'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "runs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"agent_id" varchar(36) NOT NULL,
	"agent_version_id" varchar(36) NOT NULL,
	"runtime_profile_id" varchar(36),
	"context_snapshot_id" varchar(36),
	"workspace_id" varchar(36),
	"session_id" varchar(36),
	"working_dir_id" varchar(36),
	"parent_run_id" varchar(36),
	"root_run_id" varchar(36),
	"run_group_id" varchar(36),
	"delegation_id" varchar(36),
	"instructed_by" varchar(128),
	"instructed_by_user_id" varchar(36),
	"instructed_by_agent_id" varchar(36),
	"run_type" varchar(32) NOT NULL,
	"trigger_origin" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"mode" varchar(32) NOT NULL,
	"prompt" text,
	"instruction" text,
	"scheduled_at" timestamp with time zone,
	"started_at" timestamp with time zone,
	"ended_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"model_provider_id" varchar(36),
	"error_message" text,
	"error_json" jsonb,
	"output_json" jsonb,
	"usage_json" jsonb,
	"adapter_type" varchar(64),
	"capability_id" varchar(128),
	"capabilities_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"model_selection_mode" varchar(32) DEFAULT 'cli_default' NOT NULL,
	"model_override_json" jsonb,
	"runtime_profile_snapshot_json" jsonb,
	"permission_snapshot_json" jsonb,
	"required_sandbox_level" varchar(32) DEFAULT 'none' NOT NULL,
	"sandbox_path" text,
	"runtime_seconds" double precision,
	"usage_accuracy" varchar(32) NOT NULL,
	"estimated_input_tokens" integer,
	"estimated_output_tokens" integer,
	"estimated_cost" double precision,
	"exit_code" integer,
	"visibility" varchar(32) DEFAULT 'space_shared' NOT NULL,
	"has_personal_grant_context" boolean DEFAULT false NOT NULL,
	"personal_grant_context_json" jsonb,
	"source" varchar(32),
	"observability_level" varchar(64),
	"data_exposure_level" varchar(64),
	"trust_level" varchar(32),
	"externality_level" varchar(32),
	"project_id" varchar(36),
	CONSTRAINT "uq_runs_space_id_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_runs_data_exposure_level" CHECK ((data_exposure_level IS NULL) OR ((data_exposure_level)::text = ANY (ARRAY[('local_only'::character varying)::text, ('model_provider'::character varying)::text, ('vendor_platform'::character varying)::text, ('third_party_tools'::character varying)::text, ('unknown'::character varying)::text]))),
	CONSTRAINT "ck_runs_externality_level" CHECK ((externality_level IS NULL) OR ((externality_level)::text = ANY (ARRAY[('native'::character varying)::text, ('local_external'::character varying)::text, ('remote_external'::character varying)::text, ('hybrid'::character varying)::text, ('manual'::character varying)::text]))),
	CONSTRAINT "ck_runs_mode" CHECK ((mode)::text = ANY (ARRAY[('live'::character varying)::text, ('dry_run'::character varying)::text])),
	CONSTRAINT "ck_runs_observability_level" CHECK ((observability_level IS NULL) OR ((observability_level)::text = ANY (ARRAY[('full_trace'::character varying)::text, ('structured_events'::character varying)::text, ('artifacts_only'::character varying)::text, ('final_output_only'::character varying)::text, ('black_box'::character varying)::text]))),
	CONSTRAINT "ck_runs_required_sandbox_level" CHECK ((required_sandbox_level)::text = ANY (ARRAY[('none'::character varying)::text, ('dry_run'::character varying)::text, ('ephemeral'::character varying)::text, ('worktree'::character varying)::text, ('one_shot_docker'::character varying)::text])),
	CONSTRAINT "ck_runs_run_type" CHECK ((run_type)::text = ANY (ARRAY[('agent'::character varying)::text, ('system'::character varying)::text, ('workflow'::character varying)::text, ('validation'::character varying)::text, ('reflection'::character varying)::text, ('export'::character varying)::text, ('evolution'::character varying)::text])),
	CONSTRAINT "ck_runs_source" CHECK ((source IS NULL) OR ((source)::text = ANY (ARRAY[('managed'::character varying)::text, ('ide_assist'::character varying)::text, ('manual_import'::character varying)::text, ('remote_import'::character varying)::text, ('scheduled'::character varying)::text, ('webhook'::character varying)::text]))),
	CONSTRAINT "ck_runs_status" CHECK ((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('degraded'::character varying)::text, ('failed'::character varying)::text, ('cancelled'::character varying)::text, ('waiting_for_review'::character varying)::text, ('waiting_for_dependency'::character varying)::text])),
	CONSTRAINT "ck_runs_trigger_origin" CHECK ((trigger_origin)::text = ANY (ARRAY[('manual'::character varying)::text, ('automation'::character varying)::text, ('job'::character varying)::text, ('system'::character varying)::text, ('delegation'::character varying)::text])),
	CONSTRAINT "ck_runs_trust_level" CHECK ((trust_level IS NULL) OR ((trust_level)::text = ANY (ARRAY[('high'::character varying)::text, ('medium'::character varying)::text, ('low'::character varying)::text, ('unknown'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "task_evaluations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"task_id" varchar(36) NOT NULL,
	"run_id" varchar(36),
	"run_evaluation_id" varchar(36),
	"evaluator_type" varchar(32) NOT NULL,
	"evaluator_user_id" varchar(36),
	"evaluator_agent_id" varchar(36),
	"score" double precision,
	"confidence" double precision,
	"summary" text,
	"checklist_json" jsonb,
	"known_issues_json" jsonb,
	"evidence_artifact_ids" jsonb,
	"recommendation" varchar(64),
	"created_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "task_runs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"task_id" varchar(36) NOT NULL,
	"run_id" varchar(36) NOT NULL,
	"role" varchar(32) DEFAULT 'primary' NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_task_runs_task_run" UNIQUE("run_id","task_id")
);
--> statement-breakpoint
CREATE TABLE "runtime_tool_bindings" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36),
	"agent_id" varchar(36),
	"capability_id" varchar(128),
	"runtime_adapter_type" varchar(64) NOT NULL,
	"external_type" varchar(64) NOT NULL,
	"external_ref" varchar(512) NOT NULL,
	"display_name" varchar(256) NOT NULL,
	"required_scopes_json" jsonb,
	"credential_ref" varchar(256),
	"data_exposure_level" varchar(64) DEFAULT 'unknown' NOT NULL,
	"observability_level" varchar(64) DEFAULT 'black_box' NOT NULL,
	"side_effect_level" varchar(32) DEFAULT 'none' NOT NULL,
	"approval_required" boolean DEFAULT true NOT NULL,
	"enabled" boolean DEFAULT false NOT NULL,
	"notes" text,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_runtime_tool_bindings_data_exposure_level" CHECK ((data_exposure_level)::text = ANY (ARRAY[('local_only'::character varying)::text, ('model_provider'::character varying)::text, ('vendor_platform'::character varying)::text, ('third_party_tools'::character varying)::text, ('unknown'::character varying)::text])),
	CONSTRAINT "ck_runtime_tool_bindings_external_type" CHECK ((external_type)::text = ANY (ARRAY[('codex_plugin'::character varying)::text, ('claude_skill'::character varying)::text, ('claude_hook'::character varying)::text, ('mcp_server'::character varying)::text, ('app_integration'::character varying)::text, ('cli_tool'::character varying)::text])),
	CONSTRAINT "ck_runtime_tool_bindings_observability_level" CHECK ((observability_level)::text = ANY (ARRAY[('full_trace'::character varying)::text, ('structured_events'::character varying)::text, ('artifacts_only'::character varying)::text, ('final_output_only'::character varying)::text, ('black_box'::character varying)::text])),
	CONSTRAINT "ck_runtime_tool_bindings_side_effect_level" CHECK ((side_effect_level)::text = ANY (ARRAY[('none'::character varying)::text, ('local_files'::character varying)::text, ('external_read'::character varying)::text, ('external_write'::character varying)::text, ('sensitive'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "space_runtime_tool_policies" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"runtime" varchar(64) NOT NULL,
	"enabled" boolean DEFAULT false NOT NULL,
	"default_version" varchar(128),
	"allowed_versions_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"updated_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_space_runtime_tool_policies_space_runtime" UNIQUE("runtime","space_id")
);
--> statement-breakpoint
CREATE TABLE "scheduler_tasks" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"task_type" varchar(128) NOT NULL,
	"task_key" varchar(256) NOT NULL,
	"scope_type" varchar(32) NOT NULL,
	"scope_id" varchar(128) NOT NULL,
	"space_id" varchar(36),
	"user_id" varchar(36),
	"status" varchar(32) NOT NULL,
	"next_run_at" timestamp with time zone,
	"last_run_at" timestamp with time zone,
	"state_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_scheduler_tasks_type_key" UNIQUE("task_key","task_type"),
	CONSTRAINT "ck_scheduler_tasks_scope_type" CHECK ((scope_type)::text = ANY (ARRAY[('instance'::character varying)::text, ('space'::character varying)::text, ('user'::character varying)::text, ('space_user'::character varying)::text])),
	CONSTRAINT "ck_scheduler_tasks_state_json_object" CHECK (jsonb_typeof(state_json) = 'object'::text),
	CONSTRAINT "ck_scheduler_tasks_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('paused'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "messages" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"session_id" varchar(36) NOT NULL,
	"user_id" varchar(36),
	"role" varchar(32) NOT NULL,
	"content" text NOT NULL,
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_messages_role" CHECK ((role)::text = ANY (ARRAY[('user'::character varying)::text, ('assistant'::character varying)::text, ('system'::character varying)::text, ('tool'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "session_summaries" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"session_id" varchar(36) NOT NULL,
	"user_id" varchar(36),
	"version" integer NOT NULL,
	"status" varchar(32) NOT NULL,
	"summary_text" text NOT NULL,
	"source_message_count" integer NOT NULL,
	"source_first_message_id" varchar(36),
	"source_last_message_id" varchar(36),
	"summary_json" jsonb,
	"token_estimate_before" integer,
	"token_estimate_after" integer,
	"condenser_version" varchar(64) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_session_summaries_session_version" UNIQUE("session_id","version"),
	CONSTRAINT "ck_session_summaries_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('superseded'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "sessions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"user_id" varchar(36),
	"agent_id" varchar(36),
	"workspace_id" varchar(36),
	"title" varchar(512),
	"status" varchar(32) NOT NULL,
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "settings" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"scope_type" varchar(32) NOT NULL,
	"scope_id" varchar(128) NOT NULL,
	"settings_key" varchar(128) NOT NULL,
	"settings_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"updated_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_settings_scope_key" UNIQUE("scope_id","scope_type","settings_key"),
	CONSTRAINT "ck_settings_json_object" CHECK (jsonb_typeof(settings_json) = 'object'::text),
	CONSTRAINT "ck_settings_scope_type" CHECK ((scope_type)::text = ANY (ARRAY[('instance'::character varying)::text, ('space'::character varying)::text, ('user'::character varying)::text, ('space_user'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_pointers" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"owner_space_id" varchar(36) NOT NULL,
	"source_space_id" varchar(36) NOT NULL,
	"source_object_type" varchar(64) NOT NULL,
	"source_object_id" varchar(36) NOT NULL,
	"access_mode" varchar(32) NOT NULL,
	"granted_by_user_id" varchar(36),
	"expires_at" timestamp with time zone,
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_source_pointers_access_mode" CHECK ((access_mode)::text = ANY (ARRAY[('read'::character varying)::text, ('subscribe'::character varying)::text, ('federated'::character varying)::text])),
	CONSTRAINT "ck_source_pointers_metadata_object" CHECK (jsonb_typeof(metadata_json) = 'object'::text),
	CONSTRAINT "ck_source_pointers_source_object_type" CHECK ((source_object_type)::text = ANY (ARRAY[('memory_entry'::character varying)::text, ('artifact'::character varying)::text, ('activity_record'::character varying)::text, ('run'::character varying)::text, ('proposal'::character varying)::text, ('knowledge_item'::character varying)::text, ('note'::character varying)::text, ('source'::character varying)::text, ('claim'::character varying)::text, ('project'::character varying)::text, ('workspace'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "extraction_jobs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"connection_id" varchar(36),
	"source_item_id" varchar(36),
	"source_snapshot_id" varchar(36),
	"source_object_type" varchar(64),
	"source_object_id" varchar(36),
	"job_type" varchar(64) NOT NULL,
	"status" varchar(32) NOT NULL,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"items_seen" integer,
	"items_created" integer,
	"items_updated" integer,
	"error_code" varchar(64),
	"error_message" varchar(512),
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_extraction_jobs_job_type" CHECK ((job_type)::text = ANY (ARRAY[('connection_scan'::character varying)::text, ('manual_url'::character varying)::text, ('extract_text'::character varying)::text, ('snapshot'::character varying)::text, ('normalize_activity'::character varying)::text, ('normalize_artifact'::character varying)::text, ('normalize_run_event'::character varying)::text])),
	CONSTRAINT "ck_extraction_jobs_status" CHECK ((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text, ('skipped'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "reader_annotations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_item_id" varchar(36),
	"artifact_id" varchar(36),
	"source_snapshot_id" varchar(36),
	"annotation_type" varchar(32) NOT NULL,
	"quote_text" text NOT NULL,
	"anchor_json" jsonb NOT NULL,
	"color" varchar(32),
	"label" varchar(128),
	"visibility" varchar(32) DEFAULT 'private' NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"anchor_state" varchar(32) DEFAULT 'unverified' NOT NULL,
	"created_by_user_id" varchar(36) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_reader_annotations_annotation_type" CHECK ((annotation_type)::text = ANY (ARRAY[('highlight'::character varying)::text, ('comment'::character varying)::text, ('excerpt'::character varying)::text, ('bookmark'::character varying)::text])),
	CONSTRAINT "ck_reader_annotations_visibility" CHECK ((visibility)::text = ANY (ARRAY[('private'::character varying)::text, ('space_shared'::character varying)::text])),
	CONSTRAINT "ck_reader_annotations_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_reader_annotations_anchor_state" CHECK ((anchor_state)::text = ANY (ARRAY[('verified'::character varying)::text, ('unverified'::character varying)::text])),
	CONSTRAINT "ck_reader_annotations_one_target" CHECK (((((source_item_id IS NOT NULL))::integer + ((artifact_id IS NOT NULL))::integer) + ((source_snapshot_id IS NOT NULL))::integer) = 1),
	CONSTRAINT "ck_reader_annotations_anchor_json" CHECK (jsonb_typeof(anchor_json) = 'object'::text)
);
--> statement-breakpoint
CREATE TABLE "reader_comment_threads" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"annotation_id" varchar(36) NOT NULL,
	"status" varchar(32) DEFAULT 'open' NOT NULL,
	"created_by_user_id" varchar(36) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_reader_comment_threads_status" CHECK ((status)::text = ANY (ARRAY[('open'::character varying)::text, ('resolved'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "reader_comments" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"thread_id" varchar(36) NOT NULL,
	"body" text NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"created_by_user_id" varchar(36) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_reader_comments_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_connection_user_subscriptions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_connection_id" varchar(36) NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"status" varchar(32) NOT NULL,
	"library_enabled" boolean DEFAULT true NOT NULL,
	"digest_enabled" boolean DEFAULT true NOT NULL,
	"recommended_by_user_id" varchar(36),
	"recommendation_message" text,
	"last_notified_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_source_connection_user_subscriptions_status" CHECK ((status)::text = ANY (ARRAY[('subscribed'::character varying)::text, ('pending'::character varying)::text, ('dismissed'::character varying)::text, ('muted'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_connections" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"connector_id" varchar(36) NOT NULL,
	"owner_user_id" varchar(36) NOT NULL,
	"credential_id" varchar(36),
	"visibility" varchar(32) DEFAULT 'private' NOT NULL,
	"name" varchar(512) NOT NULL,
	"endpoint_url" text,
	"status" varchar(32) NOT NULL,
	"fetch_frequency" varchar(32) NOT NULL,
	"capture_policy" varchar(64) NOT NULL,
	"trust_level" varchar(32) NOT NULL,
	"topic_hints_json" jsonb,
	"consent_json" jsonb NOT NULL,
	"policy_json" jsonb NOT NULL,
	"config_json" jsonb NOT NULL,
	"schedule_rule_json" jsonb,
	"handler_kind" varchar(32) DEFAULT 'built_in' NOT NULL,
	"active_handler_version_id" varchar(36),
	"active_recipe_version_id" varchar(36),
	"repair_status" varchar(32) DEFAULT 'ok' NOT NULL,
	"last_handler_run_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"deleted_at" timestamp with time zone,
	CONSTRAINT "source_connections_id_space_id_key" UNIQUE("id","space_id"),
	CONSTRAINT "ck_source_connections_capture_policy" CHECK ((capture_policy)::text = ANY (ARRAY[('reference_only'::character varying)::text, ('extract_text'::character varying)::text, ('archive_original'::character varying)::text])),
	CONSTRAINT "ck_source_connections_fetch_frequency" CHECK ((fetch_frequency)::text = ANY (ARRAY[('manual'::character varying)::text, ('hourly'::character varying)::text, ('daily'::character varying)::text, ('weekly'::character varying)::text])),
	CONSTRAINT "ck_source_connections_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('paused'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_source_connections_trust_level" CHECK ((trust_level)::text = ANY (ARRAY[('trusted'::character varying)::text, ('normal'::character varying)::text, ('untrusted'::character varying)::text])),
	CONSTRAINT "ck_source_connections_handler_kind" CHECK ((handler_kind)::text = ANY (ARRAY[('built_in'::character varying)::text, ('generated_custom'::character varying)::text, ('recipe'::character varying)::text])),
	CONSTRAINT "ck_source_connections_repair_status" CHECK ((repair_status)::text = ANY (ARRAY[('ok'::character varying)::text, ('repair_required'::character varying)::text, ('repair_pending'::character varying)::text, ('disabled'::character varying)::text])),
	CONSTRAINT "ck_source_connections_visibility" CHECK ((visibility)::text = ANY (ARRAY[('private'::character varying)::text, ('space_discoverable'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_connectors" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"connector_key" varchar(128) NOT NULL,
	"display_name" varchar(256) NOT NULL,
	"connector_type" varchar(64) NOT NULL,
	"ingestion_mode" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"capabilities_json" jsonb NOT NULL,
	"config_schema_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "source_connectors_connector_key_key" UNIQUE("connector_key"),
	CONSTRAINT "ck_source_connectors_connector_type" CHECK ((connector_type)::text = ANY (ARRAY[('external_feed'::character varying)::text, ('external_url'::character varying)::text, ('internal_activity'::character varying)::text, ('internal_artifact'::character varying)::text, ('internal_run'::character varying)::text, ('file'::character varying)::text, ('document'::character varying)::text])),
	CONSTRAINT "ck_source_connectors_ingestion_mode" CHECK ((ingestion_mode)::text = ANY (ARRAY[('pull'::character varying)::text, ('manual'::character varying)::text, ('internal'::character varying)::text])),
	CONSTRAINT "ck_source_connectors_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('disabled'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_handler_runs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_connection_id" varchar(36) NOT NULL,
	"handler_version_id" varchar(36) NOT NULL,
	"extraction_job_id" varchar(36),
	"status" varchar(32) NOT NULL,
	"input_artifact_id" varchar(36),
	"output_artifact_id" varchar(36),
	"logs_artifact_id" varchar(36),
	"failure_class" varchar(64),
	"failure_detail_json" jsonb,
	"validation_result_json" jsonb,
	"resource_usage_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	CONSTRAINT "ck_source_handler_runs_status" CHECK ((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text, ('validation_failed'::character varying)::text, ('blocked'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_handler_versions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_connection_id" varchar(36) NOT NULL,
	"version_number" integer NOT NULL,
	"language" varchar(32) NOT NULL,
	"entrypoint" varchar(512) NOT NULL,
	"handler_artifact_id" varchar(36),
	"manifest_json" jsonb NOT NULL,
	"input_schema_json" jsonb,
	"output_schema_json" jsonb,
	"policy_envelope_json" jsonb NOT NULL,
	"requested_capabilities_json" jsonb,
	"checksum" varchar(128) NOT NULL,
	"status" varchar(32) NOT NULL,
	"created_by_user_id" varchar(36),
	"created_by_run_id" varchar(36),
	"proposal_id" varchar(36),
	"test_result_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"activated_at" timestamp with time zone,
	"superseded_at" timestamp with time zone,
	CONSTRAINT "uq_source_handler_versions_connection_version" UNIQUE("source_connection_id","version_number"),
	CONSTRAINT "ck_source_handler_versions_language" CHECK ((language)::text = ANY (ARRAY[('typescript_node'::character varying)::text, ('declarative_pipeline_v1'::character varying)::text])),
	CONSTRAINT "ck_source_handler_versions_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('test_failed'::character varying)::text, ('pending_approval'::character varying)::text, ('active'::character varying)::text, ('superseded'::character varying)::text, ('disabled'::character varying)::text])),
	CONSTRAINT "ck_source_handler_versions_version_number" CHECK (version_number > 0)
);
--> statement-breakpoint
CREATE TABLE "source_item_user_states" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_item_id" varchar(36) NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"library_status" varchar(32) DEFAULT 'new' NOT NULL,
	"read_status" varchar(32) DEFAULT 'unread' NOT NULL,
	"first_opened_at" timestamp with time zone,
	"last_opened_at" timestamp with time zone,
	"progress_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_source_item_user_states_library_status" CHECK ((library_status)::text = ANY (ARRAY[('new'::character varying)::text, ('triaged'::character varying)::text, ('selected'::character varying)::text, ('ignored'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_source_item_user_states_read_status" CHECK ((read_status)::text = ANY (ARRAY[('unread'::character varying)::text, ('skimmed'::character varying)::text, ('read'::character varying)::text, ('discussed'::character varying)::text])),
	CONSTRAINT "ck_source_item_user_states_progress_json" CHECK (jsonb_typeof(progress_json) = 'object'::text)
);
--> statement-breakpoint
CREATE TABLE "source_items" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"connection_id" varchar(36),
	"item_type" varchar(64) NOT NULL,
	"source_object_type" varchar(64),
	"source_object_id" varchar(36),
	"created_by_user_id" varchar(36),
	"title" varchar(1024) NOT NULL,
	"source_uri" text,
	"canonical_uri" text,
	"source_domain" varchar(256),
	"source_external_id" varchar(512),
	"author" varchar(512),
	"occurred_at" timestamp with time zone,
	"first_seen_at" timestamp with time zone NOT NULL,
	"last_seen_at" timestamp with time zone NOT NULL,
	"content_hash" varchar(128),
	"excerpt" varchar(2048),
	"content_state" varchar(64) NOT NULL,
	"retention_policy" varchar(32) NOT NULL,
	"relevance_score" double precision,
	"novelty_score" double precision,
	"raw_artifact_id" varchar(36),
	"extracted_artifact_id" varchar(36),
	"summary_artifact_id" varchar(36),
	"search_index_ref" varchar(1024),
	"embedding_index_ref" varchar(1024),
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"deleted_at" timestamp with time zone,
	CONSTRAINT "ck_source_items_content_state" CHECK ((content_state)::text = ANY (ARRAY[('metadata_only'::character varying)::text, ('excerpt_saved'::character varying)::text, ('content_queued'::character varying)::text, ('content_saved'::character varying)::text, ('snapshot_queued'::character varying)::text, ('snapshot_saved'::character varying)::text, ('extraction_failed'::character varying)::text, ('content_unavailable'::character varying)::text])),
	CONSTRAINT "ck_source_items_item_type" CHECK ((item_type)::text = ANY (ARRAY[('external_url'::character varying)::text, ('feed_entry'::character varying)::text, ('activity_record'::character varying)::text, ('artifact'::character varying)::text, ('run_event'::character varying)::text, ('file'::character varying)::text, ('document'::character varying)::text, ('log'::character varying)::text])),
	CONSTRAINT "ck_source_items_retention_policy" CHECK ((retention_policy)::text = ANY (ARRAY[('metadata_only'::character varying)::text, ('summary_only'::character varying)::text, ('full_text'::character varying)::text, ('full_snapshot'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_post_processing_item_decisions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_connection_id" varchar(36) NOT NULL,
	"rule_id" varchar(36),
	"run_id" varchar(36) NOT NULL,
	"project_id" varchar(36),
	"source_item_id" varchar(36) NOT NULL,
	"relevance" varchar(32) NOT NULL,
	"confidence" double precision,
	"reason" text,
	"matched_context_refs_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"review_status" varchar(32) DEFAULT 'pending' NOT NULL,
	"action_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_source_post_processing_item_decisions_action_object" CHECK (jsonb_typeof(action_json) = 'object'::text),
	CONSTRAINT "ck_source_post_processing_item_decisions_confidence" CHECK ((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
	CONSTRAINT "ck_source_post_processing_item_decisions_refs_array" CHECK (jsonb_typeof(matched_context_refs_json) = 'array'::text),
	CONSTRAINT "ck_source_post_processing_item_decisions_relevance" CHECK ((relevance)::text = ANY (ARRAY[('relevant'::character varying)::text, ('maybe'::character varying)::text, ('not_relevant'::character varying)::text])),
	CONSTRAINT "ck_source_post_processing_item_decisions_review_status" CHECK ((review_status)::text = ANY (ARRAY[('pending'::character varying)::text, ('accepted'::character varying)::text, ('ignored'::character varying)::text, ('queued'::character varying)::text, ('proposed'::character varying)::text, ('rerun'::character varying)::text, ('dismissed'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_post_processing_rules" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_connection_id" varchar(36) NOT NULL,
	"agent_id" varchar(36) NOT NULL,
	"project_id" varchar(36),
	"name" varchar(256) NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"trigger_type" varchar(32) DEFAULT 'items_materialized' NOT NULL,
	"trigger_config_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"input_config_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"actions_json" jsonb DEFAULT '{"batch_digest":true}'::jsonb NOT NULL,
	"cursor_json" jsonb,
	"last_fired_at" timestamp with time zone,
	"created_by_user_id" varchar(36) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_source_post_processing_rules_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('paused'::character varying)::text, ('archived'::character varying)::text])),
	CONSTRAINT "ck_source_post_processing_rules_trigger_type" CHECK ((trigger_type)::text = ANY (ARRAY[('items_materialized'::character varying)::text, ('schedule'::character varying)::text, ('manual'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_post_processing_runs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"rule_id" varchar(36),
	"source_connection_id" varchar(36) NOT NULL,
	"agent_id" varchar(36) NOT NULL,
	"project_id" varchar(36),
	"agent_run_id" varchar(36),
	"triggered_by_user_id" varchar(36),
	"trigger_type" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"input_item_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"input_evidence_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"output_artifact_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"output_proposal_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"output_job_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"cursor_before_json" jsonb,
	"cursor_after_json" jsonb,
	"retrieval_context_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"item_decisions_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"summary" text,
	"error_json" jsonb,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_source_post_processing_runs_status" CHECK ((status)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text, ('succeeded'::character varying)::text, ('failed'::character varying)::text, ('skipped'::character varying)::text])),
	CONSTRAINT "ck_source_post_processing_runs_trigger_type" CHECK ((trigger_type)::text = ANY (ARRAY[('items_materialized'::character varying)::text, ('schedule'::character varying)::text, ('manual'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "source_recipe_versions" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_connection_id" varchar(36) NOT NULL,
	"version_number" integer NOT NULL,
	"recipe_json" jsonb NOT NULL,
	"policy_envelope_json" jsonb NOT NULL,
	"primitive_versions_json" jsonb,
	"status" varchar(32) NOT NULL,
	"created_by_user_id" varchar(36),
	"proposal_id" varchar(36),
	"test_result_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"activated_at" timestamp with time zone,
	"superseded_at" timestamp with time zone,
	CONSTRAINT "uq_source_recipe_versions_connection_version" UNIQUE("source_connection_id","version_number"),
	CONSTRAINT "ck_source_recipe_versions_status" CHECK ((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('test_failed'::character varying)::text, ('pending_approval'::character varying)::text, ('active'::character varying)::text, ('superseded'::character varying)::text, ('disabled'::character varying)::text])),
	CONSTRAINT "ck_source_recipe_versions_version_number" CHECK (version_number > 0)
);
--> statement-breakpoint
CREATE TABLE "source_snapshots" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"source_item_id" varchar(36),
	"connection_id" varchar(36),
	"snapshot_type" varchar(32) NOT NULL,
	"artifact_id" varchar(36),
	"content_hash" varchar(128),
	"source_uri" text,
	"capture_method" varchar(64) NOT NULL,
	"trust_level" varchar(32) NOT NULL,
	"metadata_json" jsonb,
	"captured_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_source_snapshots_capture_method" CHECK ((capture_method)::text = ANY (ARRAY[('manual'::character varying)::text, ('connection_scan'::character varying)::text, ('full_text'::character varying)::text, ('snapshot'::character varying)::text, ('internal'::character varying)::text, ('custom_source_handler'::character varying)::text, ('source_recipe'::character varying)::text])),
	CONSTRAINT "ck_source_snapshots_snapshot_type" CHECK ((snapshot_type)::text = ANY (ARRAY[('metadata'::character varying)::text, ('raw'::character varying)::text, ('extracted'::character varying)::text, ('summary'::character varying)::text])),
	CONSTRAINT "ck_source_snapshots_trust_level" CHECK ((trust_level)::text = ANY (ARRAY[('trusted'::character varying)::text, ('normal'::character varying)::text, ('untrusted'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "space_invitations" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"invited_email" varchar(256) NOT NULL,
	"role" varchar(32) NOT NULL,
	"token_hash" varchar(128) NOT NULL,
	"status" varchar(32) NOT NULL,
	"invited_by_user_id" varchar(36) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"accepted_at" timestamp with time zone,
	"expires_at" timestamp with time zone NOT NULL,
	CONSTRAINT "space_invitations_token_hash_key" UNIQUE("token_hash"),
	CONSTRAINT "ck_space_invitations_role" CHECK ((role)::text = ANY (ARRAY[('owner'::character varying)::text, ('admin'::character varying)::text, ('reviewer'::character varying)::text, ('member'::character varying)::text, ('guest'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "space_memberships" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"user_id" varchar(36) NOT NULL,
	"role" varchar(32) NOT NULL,
	"status" varchar(32) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_space_memberships_space_user" UNIQUE("space_id","user_id"),
	CONSTRAINT "ck_space_memberships_role" CHECK ((role)::text = ANY (ARRAY[('owner'::character varying)::text, ('admin'::character varying)::text, ('reviewer'::character varying)::text, ('member'::character varying)::text, ('guest'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "spaces" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"name" varchar(256) NOT NULL,
	"type" varchar(32) NOT NULL,
	"created_by_user_id" varchar(36),
	"snapshot_retention_days_default" integer,
	"snapshot_max_count_default" integer,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_spaces_type" CHECK ((type)::text = ANY (ARRAY[('personal'::character varying)::text, ('household'::character varying)::text, ('team'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "board_columns" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"board_id" varchar(36) NOT NULL,
	"name" varchar(256) NOT NULL,
	"description" text,
	"status_key" varchar(64) NOT NULL,
	"position" integer DEFAULT 0 NOT NULL,
	"wip_limit" integer,
	"is_done_column" boolean DEFAULT false NOT NULL,
	"is_default_column" boolean DEFAULT false NOT NULL,
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"deleted_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "boards" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36),
	"project_id" varchar(36),
	"name" varchar(512) NOT NULL,
	"description" text,
	"board_type" varchar(64) DEFAULT 'workspace' NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"default_view" varchar(64),
	"sort_order" integer,
	"metadata_json" jsonb,
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"deleted_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "task_artifacts" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"task_id" varchar(36) NOT NULL,
	"artifact_id" varchar(36) NOT NULL,
	"run_id" varchar(36),
	"role" varchar(32) DEFAULT 'output' NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_task_artifacts_task_artifact" UNIQUE("artifact_id","task_id")
);
--> statement-breakpoint
CREATE TABLE "task_dependencies" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"task_id" varchar(36) NOT NULL,
	"depends_on_task_id" varchar(36) NOT NULL,
	"dependency_type" varchar(32) DEFAULT 'requires' NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_task_dependencies_task_depends" UNIQUE("depends_on_task_id","task_id")
);
--> statement-breakpoint
CREATE TABLE "task_proposals" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"task_id" varchar(36) NOT NULL,
	"proposal_id" varchar(36) NOT NULL,
	"role" varchar(32) DEFAULT 'main_change' NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_task_proposals_task_proposal" UNIQUE("proposal_id","task_id")
);
--> statement-breakpoint
CREATE TABLE "tasks" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36),
	"project_id" varchar(36),
	"board_id" varchar(36),
	"column_id" varchar(36),
	"parent_task_id" varchar(36),
	"title" varchar(512) NOT NULL,
	"description" text,
	"task_type" varchar(64) DEFAULT 'general' NOT NULL,
	"status" varchar(64) DEFAULT 'inbox' NOT NULL,
	"priority" varchar(32) DEFAULT 'normal' NOT NULL,
	"risk_level" varchar(32) DEFAULT 'low' NOT NULL,
	"created_by_user_id" varchar(36),
	"created_by_agent_id" varchar(36),
	"assigned_user_id" varchar(36),
	"assigned_agent_id" varchar(36),
	"claimed_by_user_id" varchar(36),
	"claimed_by_agent_id" varchar(36),
	"source_activity_id" varchar(36),
	"source_run_id" varchar(36),
	"source_proposal_id" varchar(36),
	"source_artifact_id" varchar(36),
	"acceptance_criteria_json" jsonb,
	"definition_of_done" text,
	"required_outputs_json" jsonb,
	"due_at" timestamp with time zone,
	"start_after" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"cancelled_at" timestamp with time zone,
	"blocked_reason" text,
	"estimated_effort" varchar(64),
	"actual_effort" varchar(64),
	"max_runs" integer,
	"max_cost" double precision,
	"max_duration_seconds" integer,
	"policy_json" jsonb,
	"metadata_json" jsonb,
	"tags" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"deleted_at" timestamp with time zone,
	"visibility" varchar(32) DEFAULT 'space_shared' NOT NULL
);
--> statement-breakpoint
CREATE TABLE "validation_recipes" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36),
	"name" varchar(256) NOT NULL,
	"task_type" varchar(64),
	"risk_level" varchar(32) DEFAULT 'low' NOT NULL,
	"commands_json" jsonb NOT NULL,
	"required_checks_json" jsonb NOT NULL,
	"artifact_expectations_json" jsonb,
	"timeout_seconds" integer,
	"requires_clean_git_state" boolean DEFAULT false NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "ck_validation_recipes_risk_level" CHECK ((risk_level)::text = ANY (ARRAY[('low'::character varying)::text, ('medium'::character varying)::text, ('high'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "project_source_bindings" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"source_connection_id" varchar(36) NOT NULL,
	"binding_key" varchar(128) DEFAULT 'default' NOT NULL,
	"status" varchar(32) NOT NULL,
	"priority" integer NOT NULL,
	"delivery_scope" varchar(32) DEFAULT 'project_members' NOT NULL,
	"collection_notifications_enabled" boolean DEFAULT true NOT NULL,
	"filters_json" jsonb NOT NULL,
	"routing_policy_json" jsonb NOT NULL,
	"extraction_policy_json" jsonb NOT NULL,
	"created_by_user_id" varchar(36),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_project_source_bindings_project_connection" UNIQUE("binding_key","project_id","source_connection_id","space_id"),
	CONSTRAINT "ck_project_source_bindings_delivery_scope" CHECK ((delivery_scope)::text = ANY (ARRAY[('project_members'::character varying)::text, ('source_subscribers'::character varying)::text])),
	CONSTRAINT "ck_project_source_bindings_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('paused'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "project_source_item_links" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"project_source_binding_id" varchar(36) NOT NULL,
	"source_connection_id" varchar(36),
	"source_item_id" varchar(36) NOT NULL,
	"status" varchar(32) DEFAULT 'active' NOT NULL,
	"matched_at" timestamp with time zone NOT NULL,
	"match_reason" text,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_project_source_item_links_binding_item" UNIQUE("project_source_binding_id","project_id","source_item_id","space_id"),
	CONSTRAINT "ck_project_source_item_links_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('archived'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "project_workspaces" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"project_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36) NOT NULL,
	"role" varchar(64) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_project_workspaces_project_workspace_role" UNIQUE("project_id","role","space_id","workspace_id"),
	CONSTRAINT "ck_project_workspaces_role" CHECK ((role)::text = ANY (ARRAY[('primary_codebase'::character varying)::text, ('capability_library'::character varying)::text, ('docs'::character varying)::text, ('data'::character varying)::text, ('deployment'::character varying)::text, ('reference'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "working_dirs" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"scope" varchar(16) NOT NULL,
	"session_id" varchar(36),
	"project_id" varchar(36),
	"rel_path" varchar(1024) NOT NULL,
	"status" varchar(16) DEFAULT 'active' NOT NULL,
	"metadata_json" jsonb,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"last_used_at" timestamp with time zone,
	"cleaned_at" timestamp with time zone,
	CONSTRAINT "ck_working_dirs_owner" CHECK ((((scope)::text = 'session'::text) AND (session_id IS NOT NULL) AND (project_id IS NULL)) OR (((scope)::text = 'project'::text) AND (project_id IS NOT NULL) AND (session_id IS NULL))),
	CONSTRAINT "ck_working_dirs_scope" CHECK ((scope)::text = ANY (ARRAY[('session'::character varying)::text, ('project'::character varying)::text])),
	CONSTRAINT "ck_working_dirs_status" CHECK ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('cleaning'::character varying)::text, ('cleaned'::character varying)::text]))
);
--> statement-breakpoint
CREATE TABLE "workspace_profiles" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"workspace_id" varchar(36) NOT NULL,
	"repo_type" varchar(64),
	"tech_stack_json" jsonb,
	"important_paths_json" jsonb,
	"forbidden_paths_json" jsonb,
	"test_commands_json" jsonb,
	"build_commands_json" jsonb,
	"architecture_boundaries_json" jsonb,
	"current_focus" text,
	"known_failures_json" jsonb,
	"validation_recipe_id" varchar(36),
	"cloud_allowed" boolean DEFAULT false NOT NULL,
	"max_data_exposure_level" varchar(64),
	"min_observability_level" varchar(64),
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_workspace_profiles_workspace" UNIQUE("workspace_id"),
	CONSTRAINT "ck_workspace_profiles_max_data_exposure_level" CHECK ((max_data_exposure_level IS NULL) OR ((max_data_exposure_level)::text = ANY (ARRAY[('local_only'::character varying)::text, ('model_provider'::character varying)::text, ('vendor_platform'::character varying)::text, ('third_party_tools'::character varying)::text, ('unknown'::character varying)::text]))),
	CONSTRAINT "ck_workspace_profiles_min_observability_level" CHECK ((min_observability_level IS NULL) OR ((min_observability_level)::text = ANY (ARRAY[('full_trace'::character varying)::text, ('structured_events'::character varying)::text, ('artifacts_only'::character varying)::text, ('final_output_only'::character varying)::text, ('black_box'::character varying)::text])))
);
--> statement-breakpoint
CREATE TABLE "workspaces" (
	"id" varchar(36) PRIMARY KEY NOT NULL,
	"space_id" varchar(36) NOT NULL,
	"name" varchar(256) NOT NULL,
	"description" text,
	"root_path" varchar(1024),
	"repo_url" text,
	"status" varchar(32) NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	"created_by_user_id" varchar(36),
	"slug" varchar(256),
	"workspace_type" varchar(32) NOT NULL,
	"kind" varchar(32) NOT NULL,
	"default_branch" varchar(256),
	"visibility" varchar(32) NOT NULL,
	"protected" boolean NOT NULL,
	"system_managed" boolean NOT NULL,
	"registered_from" varchar(32),
	"metadata_json" jsonb,
	"allow_external_root" boolean DEFAULT false NOT NULL,
	"snapshot_retention_days" integer,
	"snapshot_max_count" integer,
	CONSTRAINT "uq_workspaces_space_id_id" UNIQUE("id","space_id"),
	CONSTRAINT "ck_workspaces_workspace_type" CHECK ((workspace_type)::text = ANY (ARRAY['project'::text, 'repo'::text, 'knowledge_base'::text, 'personal'::text, 'team'::text, 'system_core'::text])),
	CONSTRAINT "ck_workspaces_status" CHECK ((status)::text = ANY (ARRAY['active'::text, 'archived'::text, 'stale'::text])),
	CONSTRAINT "ck_workspaces_visibility" CHECK ((visibility)::text = ANY (ARRAY['private'::text, 'space_shared'::text, 'workspace_shared'::text, 'restricted'::text]))
);
--> statement-breakpoint
ALTER TABLE "academic_papers" ADD CONSTRAINT "academic_papers_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "academic_papers" ADD CONSTRAINT "academic_papers_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."sources"("object_id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "activity_records_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "activity_records_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "activity_records_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."sessions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "activity_records_source_run_id_fkey" FOREIGN KEY ("source_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "activity_records_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "activity_records_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "activity_records_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "fk_activity_records_project_id_projects" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "fk_activity_records_source_task_id_tasks" FOREIGN KEY ("source_task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "activity_records" ADD CONSTRAINT "fk_activity_records_subject_user_id_users" FOREIGN KEY ("subject_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_group_members" ADD CONSTRAINT "agent_run_group_members_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_group_members" ADD CONSTRAINT "agent_run_group_members_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."agent_run_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_group_members" ADD CONSTRAINT "agent_run_group_members_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_group_members" ADD CONSTRAINT "fk_agent_run_group_members_agent_same_space" FOREIGN KEY ("agent_id","space_id") REFERENCES "public"."agents"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_group_members" ADD CONSTRAINT "fk_agent_run_group_members_group_same_space" FOREIGN KEY ("group_id","space_id") REFERENCES "public"."agent_run_groups"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_groups" ADD CONSTRAINT "agent_run_groups_manager_agent_id_fkey" FOREIGN KEY ("manager_agent_id") REFERENCES "public"."agents"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_groups" ADD CONSTRAINT "agent_run_groups_manager_user_id_fkey" FOREIGN KEY ("manager_user_id") REFERENCES "public"."users"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_groups" ADD CONSTRAINT "agent_run_groups_root_run_id_fkey" FOREIGN KEY ("root_run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_groups" ADD CONSTRAINT "agent_run_groups_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_groups" ADD CONSTRAINT "fk_agent_run_groups_manager_agent_same_space" FOREIGN KEY ("manager_agent_id","space_id") REFERENCES "public"."agents"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_groups" ADD CONSTRAINT "fk_agent_run_groups_root_run_same_space" FOREIGN KEY ("root_run_id","space_id") REFERENCES "public"."runs"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "agent_run_messages_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."agent_run_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "agent_run_messages_parent_message_id_fkey" FOREIGN KEY ("parent_message_id") REFERENCES "public"."agent_run_messages"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "agent_run_messages_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "agent_run_messages_sender_agent_id_fkey" FOREIGN KEY ("sender_agent_id") REFERENCES "public"."agents"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "agent_run_messages_sender_user_id_fkey" FOREIGN KEY ("sender_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "agent_run_messages_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "fk_agent_run_messages_group_same_space" FOREIGN KEY ("group_id","space_id") REFERENCES "public"."agent_run_groups"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "fk_agent_run_messages_parent_same_space" FOREIGN KEY ("parent_message_id","space_id") REFERENCES "public"."agent_run_messages"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "fk_agent_run_messages_run_same_space" FOREIGN KEY ("run_id","space_id") REFERENCES "public"."runs"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_run_messages" ADD CONSTRAINT "fk_agent_run_messages_sender_agent_same_space" FOREIGN KEY ("sender_agent_id","space_id") REFERENCES "public"."agents"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_child_run_id_fkey" FOREIGN KEY ("child_run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "public"."agent_run_groups"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_parent_run_id_fkey" FOREIGN KEY ("parent_run_id") REFERENCES "public"."runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_policy_decision_record_id_fkey" FOREIGN KEY ("policy_decision_record_id") REFERENCES "public"."policy_decision_records"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_request_message_id_fkey" FOREIGN KEY ("request_message_id") REFERENCES "public"."agent_run_messages"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_requested_by_user_id_fkey" FOREIGN KEY ("requested_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_requesting_agent_id_fkey" FOREIGN KEY ("requesting_agent_id") REFERENCES "public"."agents"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "run_delegations_target_agent_id_fkey" FOREIGN KEY ("target_agent_id") REFERENCES "public"."agents"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "fk_run_delegations_child_run_same_space" FOREIGN KEY ("child_run_id","space_id") REFERENCES "public"."runs"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "fk_run_delegations_group_same_space" FOREIGN KEY ("group_id","space_id") REFERENCES "public"."agent_run_groups"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "fk_run_delegations_parent_run_same_space" FOREIGN KEY ("parent_run_id","space_id") REFERENCES "public"."runs"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "fk_run_delegations_policy_decision_same_space" FOREIGN KEY ("policy_decision_record_id","space_id") REFERENCES "public"."policy_decision_records"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "fk_run_delegations_request_message_same_space" FOREIGN KEY ("request_message_id","space_id") REFERENCES "public"."agent_run_messages"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "fk_run_delegations_requesting_agent_same_space" FOREIGN KEY ("requesting_agent_id","space_id") REFERENCES "public"."agents"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_delegations" ADD CONSTRAINT "fk_run_delegations_target_agent_same_space" FOREIGN KEY ("target_agent_id","space_id") REFERENCES "public"."agents"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "actors" ADD CONSTRAINT "actors_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "actors" ADD CONSTRAINT "actors_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "actors" ADD CONSTRAINT "actors_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_runtime_profiles" ADD CONSTRAINT "agent_runtime_profiles_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_runtime_profiles" ADD CONSTRAINT "agent_runtime_profiles_credential_profile_id_fkey" FOREIGN KEY ("credential_profile_id") REFERENCES "public"."cli_credential_profiles"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_runtime_profiles" ADD CONSTRAINT "agent_runtime_profiles_model_provider_id_fkey" FOREIGN KEY ("model_provider_id") REFERENCES "public"."model_providers"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_runtime_profiles" ADD CONSTRAINT "agent_runtime_profiles_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_versions" ADD CONSTRAINT "agent_versions_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_versions" ADD CONSTRAINT "agent_versions_model_provider_id_fkey" FOREIGN KEY ("model_provider_id") REFERENCES "public"."model_providers"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_versions" ADD CONSTRAINT "agent_versions_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_versions" ADD CONSTRAINT "fk_agent_versions_source_activity_id_activity_records" FOREIGN KEY ("source_activity_id") REFERENCES "public"."activity_records"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agent_versions" ADD CONSTRAINT "fk_agent_versions_source_proposal_id_proposals" FOREIGN KEY ("source_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agents" ADD CONSTRAINT "agents_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agents" ADD CONSTRAINT "agents_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "agents" ADD CONSTRAINT "fk_agents_current_version_id_agent_versions" FOREIGN KEY ("current_version_id") REFERENCES "public"."agent_versions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_credential_events" ADD CONSTRAINT "cli_credential_events_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_credential_events" ADD CONSTRAINT "cli_credential_events_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_credential_profiles" ADD CONSTRAINT "cli_credential_profiles_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_credential_space_grants" ADD CONSTRAINT "cli_credential_space_grants_granted_by_user_id_fkey" FOREIGN KEY ("granted_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_credential_space_grants" ADD CONSTRAINT "cli_credential_space_grants_network_profile_id_fkey" FOREIGN KEY ("network_profile_id") REFERENCES "public"."network_profiles"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_credential_space_grants" ADD CONSTRAINT "cli_credential_space_grants_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_credential_space_grants" ADD CONSTRAINT "cli_credential_space_grants_profile_id_fkey" FOREIGN KEY ("profile_id") REFERENCES "public"."cli_credential_profiles"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_credential_space_grants" ADD CONSTRAINT "cli_credential_space_grants_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "fk_artifacts_project_id_projects" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "auth_accounts" ADD CONSTRAINT "auth_accounts_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_sessions" ADD CONSTRAINT "user_sessions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automation_credential_grants" ADD CONSTRAINT "automation_credential_grants_automation_id_fkey" FOREIGN KEY ("automation_id") REFERENCES "public"."automations"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automation_credential_grants" ADD CONSTRAINT "automation_credential_grants_granted_by_user_id_fkey" FOREIGN KEY ("granted_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automation_credential_grants" ADD CONSTRAINT "automation_credential_grants_revoked_by_user_id_fkey" FOREIGN KEY ("revoked_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automation_credential_grants" ADD CONSTRAINT "automation_credential_grants_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automation_runs" ADD CONSTRAINT "automation_runs_automation_id_fkey" FOREIGN KEY ("automation_id") REFERENCES "public"."automations"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automation_runs" ADD CONSTRAINT "automation_runs_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automation_runs" ADD CONSTRAINT "automation_runs_triggered_by_user_id_fkey" FOREIGN KEY ("triggered_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automations" ADD CONSTRAINT "automations_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automations" ADD CONSTRAINT "automations_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automations" ADD CONSTRAINT "automations_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automations" ADD CONSTRAINT "automations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "automations" ADD CONSTRAINT "automations_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "capability_enablements" ADD CONSTRAINT "capability_enablements_capability_version_id_fkey" FOREIGN KEY ("capability_version_id") REFERENCES "public"."capability_versions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "capability_overlays" ADD CONSTRAINT "capability_overlays_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "capability_overlays" ADD CONSTRAINT "fk_capability_overlays_base_version_id" FOREIGN KEY ("base_version_id") REFERENCES "public"."capability_versions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "capability_runtime_bindings" ADD CONSTRAINT "capability_runtime_bindings_capability_version_id_fkey" FOREIGN KEY ("capability_version_id") REFERENCES "public"."capability_versions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "capability_versions" ADD CONSTRAINT "capability_versions_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "capability_versions" ADD CONSTRAINT "fk_capability_versions_parent_version_id" FOREIGN KEY ("parent_version_id") REFERENCES "public"."capability_versions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "skill_local_overlays" ADD CONSTRAINT "skill_local_overlays_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "skill_local_overlays" ADD CONSTRAINT "skill_local_overlays_skill_package_id_fkey" FOREIGN KEY ("skill_package_id") REFERENCES "public"."skill_packages"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "skill_local_overlays" ADD CONSTRAINT "skill_local_overlays_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "skill_package_files" ADD CONSTRAINT "skill_package_files_skill_package_id_fkey" FOREIGN KEY ("skill_package_id") REFERENCES "public"."skill_packages"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "skill_packages" ADD CONSTRAINT "skill_packages_source_id_fkey" FOREIGN KEY ("source_id") REFERENCES "public"."skill_sources"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_review_states" ADD CONSTRAINT "card_review_states_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "public"."cards"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_review_states" ADD CONSTRAINT "card_review_states_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_reviews" ADD CONSTRAINT "card_reviews_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "public"."cards"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_reviews" ADD CONSTRAINT "card_reviews_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards" ADD CONSTRAINT "cards_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cards" ADD CONSTRAINT "cards_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_artifact_revocations" ADD CONSTRAINT "context_artifact_revocations_artifact_id_fkey" FOREIGN KEY ("artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_artifact_revocations" ADD CONSTRAINT "context_artifact_revocations_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_artifact_revocations" ADD CONSTRAINT "context_artifact_revocations_deleted_by_user_id_fkey" FOREIGN KEY ("deleted_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_artifact_revocations" ADD CONSTRAINT "context_artifact_revocations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_digests" ADD CONSTRAINT "context_digests_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_profiles" ADD CONSTRAINT "context_profiles_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_profiles" ADD CONSTRAINT "context_profiles_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_snapshot_items" ADD CONSTRAINT "context_snapshot_items_context_snapshot_id_fkey" FOREIGN KEY ("context_snapshot_id") REFERENCES "public"."context_snapshots"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_snapshots" ADD CONSTRAINT "context_snapshots_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_snapshots" ADD CONSTRAINT "fk_context_snapshots_agent_id_agents" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_snapshots" ADD CONSTRAINT "fk_context_snapshots_run_id_runs" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "context_snapshots" ADD CONSTRAINT "fk_context_snapshots_session_id_sessions" FOREIGN KEY ("session_id") REFERENCES "public"."sessions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_experiences" ADD CONSTRAINT "evolution_experiences_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_experiences" ADD CONSTRAINT "evolution_experiences_strategy_asset_id_fkey" FOREIGN KEY ("strategy_asset_id") REFERENCES "public"."evolution_strategy_assets"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_experiences" ADD CONSTRAINT "evolution_experiences_target_id_fkey" FOREIGN KEY ("target_id") REFERENCES "public"."evolution_targets"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_experiences" ADD CONSTRAINT "evolution_experiences_source_run_id_fkey" FOREIGN KEY ("source_run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_experiences" ADD CONSTRAINT "evolution_experiences_source_proposal_id_fkey" FOREIGN KEY ("source_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_selector_decisions" ADD CONSTRAINT "evolution_selector_decisions_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_selector_decisions" ADD CONSTRAINT "evolution_selector_decisions_target_id_fkey" FOREIGN KEY ("target_id") REFERENCES "public"."evolution_targets"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_selector_decisions" ADD CONSTRAINT "evolution_selector_decisions_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_selector_decisions" ADD CONSTRAINT "evolution_selector_decisions_selected_strategy_asset_id_fkey" FOREIGN KEY ("selected_strategy_asset_id") REFERENCES "public"."evolution_strategy_assets"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_signals" ADD CONSTRAINT "evolution_signals_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_signals" ADD CONSTRAINT "evolution_signals_target_id_fkey" FOREIGN KEY ("target_id") REFERENCES "public"."evolution_targets"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_strategy_assets" ADD CONSTRAINT "evolution_strategy_assets_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_targets" ADD CONSTRAINT "evolution_targets_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolution_targets" ADD CONSTRAINT "fk_evolution_targets_current_version_id" FOREIGN KEY ("current_version_id") REFERENCES "public"."capability_versions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_reflections" ADD CONSTRAINT "run_reflections_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_reflections" ADD CONSTRAINT "run_reflections_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_asset_id_fkey" FOREIGN KEY ("asset_id") REFERENCES "public"."evolvable_assets"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_candidate_version_id_fkey" FOREIGN KEY ("candidate_version_id") REFERENCES "public"."evolvable_asset_versions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_baseline_version_id_fkey" FOREIGN KEY ("baseline_version_id") REFERENCES "public"."evolvable_asset_versions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_evolution_target_id_fkey" FOREIGN KEY ("evolution_target_id") REFERENCES "public"."evolution_targets"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_output_artifact_id_fkey" FOREIGN KEY ("output_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_report_artifact_id_fkey" FOREIGN KEY ("report_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_evaluation_runs" ADD CONSTRAINT "evolvable_asset_evaluation_runs_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_pins" ADD CONSTRAINT "evolvable_asset_pins_asset_id_fkey" FOREIGN KEY ("asset_id") REFERENCES "public"."evolvable_assets"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_pins" ADD CONSTRAINT "evolvable_asset_pins_version_id_fkey" FOREIGN KEY ("version_id") REFERENCES "public"."evolvable_asset_versions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_pins" ADD CONSTRAINT "evolvable_asset_pins_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_pins" ADD CONSTRAINT "evolvable_asset_pins_pinned_by_user_id_fkey" FOREIGN KEY ("pinned_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_versions" ADD CONSTRAINT "evolvable_asset_versions_asset_id_fkey" FOREIGN KEY ("asset_id") REFERENCES "public"."evolvable_assets"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_versions" ADD CONSTRAINT "evolvable_asset_versions_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_versions" ADD CONSTRAINT "evolvable_asset_versions_parent_version_id_fkey" FOREIGN KEY ("parent_version_id") REFERENCES "public"."evolvable_asset_versions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_versions" ADD CONSTRAINT "evolvable_asset_versions_promotion_proposal_id_fkey" FOREIGN KEY ("promotion_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_versions" ADD CONSTRAINT "evolvable_asset_versions_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_asset_versions" ADD CONSTRAINT "evolvable_asset_versions_approved_by_user_id_fkey" FOREIGN KEY ("approved_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_assets" ADD CONSTRAINT "evolvable_assets_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evolvable_assets" ADD CONSTRAINT "evolvable_assets_current_system_version_id_fkey" FOREIGN KEY ("current_system_version_id") REFERENCES "public"."evolvable_asset_versions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "graph_view_states" ADD CONSTRAINT "graph_view_states_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "graph_view_states" ADD CONSTRAINT "graph_view_states_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "job_events" ADD CONSTRAINT "job_events_job_id_fkey" FOREIGN KEY ("job_id") REFERENCES "public"."jobs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claim_sources" ADD CONSTRAINT "claim_sources_claim_id_fkey" FOREIGN KEY ("claim_id","space_id") REFERENCES "public"."claims"("object_id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claim_sources" ADD CONSTRAINT "claim_sources_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claim_sources" ADD CONSTRAINT "claim_sources_source_connection_id_fkey" FOREIGN KEY ("source_connection_id","space_id") REFERENCES "public"."source_connections"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claim_sources" ADD CONSTRAINT "claim_sources_source_object_id_fkey" FOREIGN KEY ("source_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claim_sources" ADD CONSTRAINT "claim_sources_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claims" ADD CONSTRAINT "claims_approved_by_user_id_fkey" FOREIGN KEY ("approved_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claims" ADD CONSTRAINT "claims_created_from_proposal_id_fkey" FOREIGN KEY ("created_from_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claims" ADD CONSTRAINT "claims_holder_object_id_fkey" FOREIGN KEY ("holder_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claims" ADD CONSTRAINT "claims_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claims" ADD CONSTRAINT "claims_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "claims" ADD CONSTRAINT "claims_subject_object_id_fkey" FOREIGN KEY ("subject_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_links" ADD CONSTRAINT "evidence_links_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_links" ADD CONSTRAINT "evidence_links_created_by_run_id_fkey" FOREIGN KEY ("created_by_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_links" ADD CONSTRAINT "evidence_links_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_links" ADD CONSTRAINT "evidence_links_evidence_id_fkey" FOREIGN KEY ("evidence_id") REFERENCES "public"."extracted_evidence"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_links" ADD CONSTRAINT "evidence_links_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extracted_evidence" ADD CONSTRAINT "extracted_evidence_artifact_id_fkey" FOREIGN KEY ("artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extracted_evidence" ADD CONSTRAINT "extracted_evidence_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extracted_evidence" ADD CONSTRAINT "extracted_evidence_created_by_run_id_fkey" FOREIGN KEY ("created_by_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extracted_evidence" ADD CONSTRAINT "extracted_evidence_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extracted_evidence" ADD CONSTRAINT "extracted_evidence_extraction_job_id_fkey" FOREIGN KEY ("extraction_job_id") REFERENCES "public"."extraction_jobs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extracted_evidence" ADD CONSTRAINT "extracted_evidence_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extracted_evidence" ADD CONSTRAINT "extracted_evidence_source_snapshot_id_fkey" FOREIGN KEY ("source_snapshot_id") REFERENCES "public"."source_snapshots"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extracted_evidence" ADD CONSTRAINT "extracted_evidence_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_item_sources" ADD CONSTRAINT "knowledge_item_sources_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_item_sources" ADD CONSTRAINT "knowledge_item_sources_knowledge_item_id_fkey" FOREIGN KEY ("knowledge_item_id","space_id") REFERENCES "public"."knowledge_items"("object_id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_item_sources" ADD CONSTRAINT "knowledge_item_sources_source_id_fkey" FOREIGN KEY ("source_id","space_id") REFERENCES "public"."sources"("object_id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_item_sources" ADD CONSTRAINT "knowledge_item_sources_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_items" ADD CONSTRAINT "fk_knowledge_items_redirect_to_item_id_knowledge_items" FOREIGN KEY ("redirect_to_item_id","space_id") REFERENCES "public"."knowledge_items"("object_id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_items" ADD CONSTRAINT "fk_knowledge_items_root_item_id_knowledge_items" FOREIGN KEY ("root_item_id","space_id") REFERENCES "public"."knowledge_items"("object_id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_items" ADD CONSTRAINT "fk_knowledge_items_supersedes_item_id_knowledge_items" FOREIGN KEY ("supersedes_item_id","space_id") REFERENCES "public"."knowledge_items"("object_id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_items" ADD CONSTRAINT "knowledge_items_approved_by_user_id_fkey" FOREIGN KEY ("approved_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_items" ADD CONSTRAINT "knowledge_items_created_from_proposal_id_fkey" FOREIGN KEY ("created_from_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_items" ADD CONSTRAINT "knowledge_items_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_items" ADD CONSTRAINT "knowledge_items_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_collection_items" ADD CONSTRAINT "note_collection_items_collection_id_space_id_fkey" FOREIGN KEY ("collection_id","space_id") REFERENCES "public"."note_collections"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_collection_items" ADD CONSTRAINT "note_collection_items_note_id_space_id_fkey" FOREIGN KEY ("note_id","space_id") REFERENCES "public"."notes"("object_id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_collection_items" ADD CONSTRAINT "note_collection_items_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_collections" ADD CONSTRAINT "note_collections_parent_id_space_id_fkey" FOREIGN KEY ("parent_id","space_id") REFERENCES "public"."note_collections"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_collections" ADD CONSTRAINT "note_collections_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_links" ADD CONSTRAINT "note_links_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_links" ADD CONSTRAINT "note_links_from_object_id_fkey" FOREIGN KEY ("from_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_links" ADD CONSTRAINT "note_links_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "note_links" ADD CONSTRAINT "note_links_to_object_id_fkey" FOREIGN KEY ("to_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "notes" ADD CONSTRAINT "notes_created_from_activity_id_fkey" FOREIGN KEY ("created_from_activity_id") REFERENCES "public"."activity_records"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "notes" ADD CONSTRAINT "notes_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "notes" ADD CONSTRAINT "notes_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "object_relations" ADD CONSTRAINT "object_relations_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "object_relations" ADD CONSTRAINT "object_relations_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "object_relations" ADD CONSTRAINT "object_relations_from_object_id_fkey" FOREIGN KEY ("from_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "object_relations" ADD CONSTRAINT "object_relations_source_claim_id_fkey" FOREIGN KEY ("source_claim_id","space_id") REFERENCES "public"."claims"("object_id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "object_relations" ADD CONSTRAINT "object_relations_source_object_id_fkey" FOREIGN KEY ("source_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "object_relations" ADD CONSTRAINT "object_relations_source_proposal_id_fkey" FOREIGN KEY ("source_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "object_relations" ADD CONSTRAINT "object_relations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "object_relations" ADD CONSTRAINT "object_relations_to_object_id_fkey" FOREIGN KEY ("to_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sources" ADD CONSTRAINT "sources_source_activity_id_fkey" FOREIGN KEY ("source_activity_id") REFERENCES "public"."activity_records"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sources" ADD CONSTRAINT "sources_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sources" ADD CONSTRAINT "sources_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_object_kind_relation_hints" ADD CONSTRAINT "space_object_kind_relation_hints_endpoint_kind_fkey" FOREIGN KEY ("endpoint_object_kind_id") REFERENCES "public"."space_object_kinds"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_object_kind_relation_hints" ADD CONSTRAINT "space_object_kind_relation_hints_object_kind_fkey" FOREIGN KEY ("object_kind_id") REFERENCES "public"."space_object_kinds"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_object_kind_relation_hints" ADD CONSTRAINT "space_object_kind_relation_hints_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_object_kinds" ADD CONSTRAINT "space_object_kinds_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_object_kinds" ADD CONSTRAINT "space_object_kinds_created_from_proposal_id_fkey" FOREIGN KEY ("created_from_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_object_kinds" ADD CONSTRAINT "space_object_kinds_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_object_kinds" ADD CONSTRAINT "space_object_kinds_updated_from_proposal_id_fkey" FOREIGN KEY ("updated_from_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_objects" ADD CONSTRAINT "space_objects_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_objects" ADD CONSTRAINT "space_objects_created_by_run_id_fkey" FOREIGN KEY ("created_by_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_objects" ADD CONSTRAINT "space_objects_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_objects" ADD CONSTRAINT "space_objects_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_objects" ADD CONSTRAINT "space_objects_primary_project_id_fkey" FOREIGN KEY ("primary_project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_objects" ADD CONSTRAINT "space_objects_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_objects" ADD CONSTRAINT "space_objects_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_access_logs" ADD CONSTRAINT "memory_access_logs_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_access_logs" ADD CONSTRAINT "memory_access_logs_memory_id_fkey" FOREIGN KEY ("memory_id") REFERENCES "public"."memory_entries"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_access_logs" ADD CONSTRAINT "memory_access_logs_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_access_logs" ADD CONSTRAINT "memory_access_logs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_access_logs" ADD CONSTRAINT "memory_access_logs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "fk_memory_entries_project_id_projects" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "fk_memory_entries_root_memory_id_memory_entries" FOREIGN KEY ("root_memory_id") REFERENCES "public"."memory_entries"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "fk_memory_entries_supersedes_memory_id_memory_entries" FOREIGN KEY ("supersedes_memory_id") REFERENCES "public"."memory_entries"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "memory_entries_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "memory_entries_created_from_proposal_id_fkey" FOREIGN KEY ("created_from_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "memory_entries_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "memory_entries_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "memory_entries_subject_user_id_fkey" FOREIGN KEY ("subject_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_entries" ADD CONSTRAINT "memory_entries_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_maintenance_jobs" ADD CONSTRAINT "memory_maintenance_jobs_last_packet_proposal_id_fkey" FOREIGN KEY ("last_packet_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_maintenance_jobs" ADD CONSTRAINT "memory_maintenance_jobs_last_report_artifact_id_fkey" FOREIGN KEY ("last_report_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_maintenance_jobs" ADD CONSTRAINT "memory_maintenance_jobs_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_maintenance_jobs" ADD CONSTRAINT "memory_maintenance_jobs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_relations" ADD CONSTRAINT "memory_relations_created_from_proposal_id_fkey" FOREIGN KEY ("created_from_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "memory_relations" ADD CONSTRAINT "memory_relations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "provenance_links" ADD CONSTRAINT "provenance_links_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "participation_records" ADD CONSTRAINT "participation_records_personal_space_id_fkey" FOREIGN KEY ("personal_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "participation_records" ADD CONSTRAINT "participation_records_source_space_id_fkey" FOREIGN KEY ("source_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "participation_records" ADD CONSTRAINT "participation_records_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grant_events" ADD CONSTRAINT "personal_memory_grant_events_actor_user_id_fkey" FOREIGN KEY ("actor_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grant_events" ADD CONSTRAINT "personal_memory_grant_events_grant_id_fkey" FOREIGN KEY ("grant_id") REFERENCES "public"."personal_memory_grants"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grant_events" ADD CONSTRAINT "personal_memory_grant_events_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grant_events" ADD CONSTRAINT "personal_memory_grant_events_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grant_events" ADD CONSTRAINT "personal_memory_grant_events_source_space_id_fkey" FOREIGN KEY ("source_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grant_events" ADD CONSTRAINT "personal_memory_grant_events_target_space_id_fkey" FOREIGN KEY ("target_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grants" ADD CONSTRAINT "personal_memory_grants_granting_user_id_fkey" FOREIGN KEY ("granting_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grants" ADD CONSTRAINT "personal_memory_grants_personal_space_id_fkey" FOREIGN KEY ("personal_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grants" ADD CONSTRAINT "personal_memory_grants_target_agent_id_fkey" FOREIGN KEY ("target_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grants" ADD CONSTRAINT "personal_memory_grants_target_run_id_fkey" FOREIGN KEY ("target_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "personal_memory_grants" ADD CONSTRAINT "personal_memory_grants_target_space_id_fkey" FOREIGN KEY ("target_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "policies" ADD CONSTRAINT "fk_policies_created_from_proposal_id_proposals" FOREIGN KEY ("created_from_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "policies" ADD CONSTRAINT "fk_policies_supersedes_policy_id_policies" FOREIGN KEY ("supersedes_policy_id") REFERENCES "public"."policies"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "policies" ADD CONSTRAINT "policies_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_deployment_refs" ADD CONSTRAINT "prompt_deployment_refs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_deployment_refs" ADD CONSTRAINT "prompt_deployment_refs_asset_id_fkey" FOREIGN KEY ("asset_id") REFERENCES "public"."evolvable_assets"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_deployment_refs" ADD CONSTRAINT "prompt_deployment_refs_version_id_fkey" FOREIGN KEY ("version_id") REFERENCES "public"."evolvable_asset_versions"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_deployment_refs" ADD CONSTRAINT "prompt_deployment_refs_promoted_by_user_id_fkey" FOREIGN KEY ("promoted_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "prompt_deployment_refs" ADD CONSTRAINT "prompt_deployment_refs_promoted_from_proposal_id_fkey" FOREIGN KEY ("promoted_from_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_corpus_items" ADD CONSTRAINT "project_corpus_items_added_by_user_id_fkey" FOREIGN KEY ("added_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_corpus_items" ADD CONSTRAINT "project_corpus_items_evidence_id_fkey" FOREIGN KEY ("evidence_id") REFERENCES "public"."extracted_evidence"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_corpus_items" ADD CONSTRAINT "project_corpus_items_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_corpus_items" ADD CONSTRAINT "project_corpus_items_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_corpus_items" ADD CONSTRAINT "project_corpus_items_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_corpus_items" ADD CONSTRAINT "project_corpus_items_source_decision_id_fkey" FOREIGN KEY ("source_decision_id") REFERENCES "public"."source_post_processing_item_decisions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_corpus_items" ADD CONSTRAINT "project_corpus_items_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_corpus_items" ADD CONSTRAINT "project_corpus_items_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_campaigns" ADD CONSTRAINT "project_experiment_campaigns_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_campaigns" ADD CONSTRAINT "project_experiment_campaigns_workspace_id_fkey" FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_campaigns" ADD CONSTRAINT "project_experiment_campaigns_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_campaigns" ADD CONSTRAINT "project_experiment_campaigns_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_campaigns" ADD CONSTRAINT "project_experiment_campaigns_baseline_run_id_fkey" FOREIGN KEY ("baseline_run_id") REFERENCES "public"."project_experiment_runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_campaigns" ADD CONSTRAINT "project_experiment_campaigns_best_run_id_fkey" FOREIGN KEY ("best_run_id") REFERENCES "public"."project_experiment_runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_provenance" ADD CONSTRAINT "project_experiment_provenance_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_provenance" ADD CONSTRAINT "project_experiment_provenance_campaign_id_fkey" FOREIGN KEY ("campaign_id") REFERENCES "public"."project_experiment_campaigns"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_provenance" ADD CONSTRAINT "project_experiment_provenance_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_provenance" ADD CONSTRAINT "project_experiment_provenance_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_runs" ADD CONSTRAINT "project_experiment_runs_campaign_id_fkey" FOREIGN KEY ("campaign_id","space_id") REFERENCES "public"."project_experiment_campaigns"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_runs" ADD CONSTRAINT "project_experiment_runs_workspace_id_fkey" FOREIGN KEY ("workspace_id") REFERENCES "public"."workspaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_runs" ADD CONSTRAINT "project_experiment_runs_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_runs" ADD CONSTRAINT "project_experiment_runs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_experiment_runs" ADD CONSTRAINT "project_experiment_runs_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_artifact_links" ADD CONSTRAINT "project_research_artifact_links_workflow_id_fkey" FOREIGN KEY ("workflow_id") REFERENCES "public"."project_research_workflows"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_artifact_links" ADD CONSTRAINT "project_research_artifact_links_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_artifact_links" ADD CONSTRAINT "project_research_artifact_links_artifact_id_fkey" FOREIGN KEY ("artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_artifact_links" ADD CONSTRAINT "project_research_artifact_links_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_artifact_links" ADD CONSTRAINT "project_research_artifact_links_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_artifact_links" ADD CONSTRAINT "project_research_artifact_links_created_by_run_id_fkey" FOREIGN KEY ("created_by_run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_checkpoints" ADD CONSTRAINT "project_research_checkpoints_workflow_id_fkey" FOREIGN KEY ("workflow_id","space_id") REFERENCES "public"."project_research_workflows"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_checkpoints" ADD CONSTRAINT "project_research_checkpoints_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_checkpoints" ADD CONSTRAINT "project_research_checkpoints_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_checkpoints" ADD CONSTRAINT "project_research_checkpoints_decided_by_user_id_fkey" FOREIGN KEY ("decided_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_claim_links" ADD CONSTRAINT "project_research_claim_links_claim_id_fkey" FOREIGN KEY ("claim_id","space_id") REFERENCES "public"."claims"("object_id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_claim_links" ADD CONSTRAINT "project_research_claim_links_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_claim_links" ADD CONSTRAINT "project_research_claim_links_workflow_id_fkey" FOREIGN KEY ("workflow_id") REFERENCES "public"."project_research_workflows"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_claim_links" ADD CONSTRAINT "project_research_claim_links_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_claim_links" ADD CONSTRAINT "project_research_claim_links_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_profiles" ADD CONSTRAINT "project_research_profiles_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_profiles" ADD CONSTRAINT "project_research_profiles_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_profiles" ADD CONSTRAINT "project_research_profiles_approved_by_user_id_fkey" FOREIGN KEY ("approved_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_screening_criteria" ADD CONSTRAINT "project_research_screening_criteria_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_screening_criteria" ADD CONSTRAINT "project_research_screening_criteria_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_workflows" ADD CONSTRAINT "project_research_workflows_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_workflows" ADD CONSTRAINT "project_research_workflows_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_workflows" ADD CONSTRAINT "project_research_workflows_started_by_user_id_fkey" FOREIGN KEY ("started_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_research_workflows" ADD CONSTRAINT "project_research_workflows_started_run_id_fkey" FOREIGN KEY ("started_run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_members" ADD CONSTRAINT "project_members_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_members" ADD CONSTRAINT "project_members_space_project_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_members" ADD CONSTRAINT "project_members_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_members" ADD CONSTRAINT "project_members_space_membership_fkey" FOREIGN KEY ("space_id","user_id") REFERENCES "public"."space_memberships"("space_id","user_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_public_summaries" ADD CONSTRAINT "project_public_summaries_generated_by_run_id_fkey" FOREIGN KEY ("generated_by_run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_public_summaries" ADD CONSTRAINT "project_public_summaries_space_project_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_public_summaries" ADD CONSTRAINT "project_public_summaries_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_public_summaries" ADD CONSTRAINT "project_public_summaries_updated_by_user_id_fkey" FOREIGN KEY ("updated_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "projects" ADD CONSTRAINT "projects_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "projects" ADD CONSTRAINT "projects_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposal_approvals" ADD CONSTRAINT "proposal_approvals_approver_user_id_fkey" FOREIGN KEY ("approver_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposal_approvals" ADD CONSTRAINT "proposal_approvals_grant_id_fkey" FOREIGN KEY ("grant_id") REFERENCES "public"."personal_memory_grants"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposal_approvals" ADD CONSTRAINT "proposal_approvals_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposal_approvals" ADD CONSTRAINT "proposal_approvals_target_space_id_fkey" FOREIGN KEY ("target_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposals" ADD CONSTRAINT "fk_proposals_project_id_projects" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposals" ADD CONSTRAINT "proposals_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposals" ADD CONSTRAINT "proposals_created_by_run_id_fkey" FOREIGN KEY ("created_by_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposals" ADD CONSTRAINT "proposals_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposals" ADD CONSTRAINT "proposals_reviewed_by_fkey" FOREIGN KEY ("reviewed_by") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposals" ADD CONSTRAINT "proposals_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proposals" ADD CONSTRAINT "proposals_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "credentials" ADD CONSTRAINT "credentials_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "credentials" ADD CONSTRAINT "credentials_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_provider_credentials" ADD CONSTRAINT "model_provider_credentials_credential_id_fkey" FOREIGN KEY ("credential_id") REFERENCES "public"."credentials"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_provider_credentials" ADD CONSTRAINT "model_provider_credentials_provider_id_fkey" FOREIGN KEY ("provider_id") REFERENCES "public"."model_providers"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_provider_credentials" ADD CONSTRAINT "model_provider_credentials_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_provider_space_grants" ADD CONSTRAINT "model_provider_space_grants_granted_by_user_id_fkey" FOREIGN KEY ("granted_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_provider_space_grants" ADD CONSTRAINT "model_provider_space_grants_network_profile_id_fkey" FOREIGN KEY ("network_profile_id") REFERENCES "public"."network_profiles"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_provider_space_grants" ADD CONSTRAINT "model_provider_space_grants_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_provider_space_grants" ADD CONSTRAINT "model_provider_space_grants_provider_id_fkey" FOREIGN KEY ("provider_id") REFERENCES "public"."model_providers"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_provider_space_grants" ADD CONSTRAINT "model_provider_space_grants_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_providers" ADD CONSTRAINT "model_providers_credential_id_fkey" FOREIGN KEY ("credential_id") REFERENCES "public"."credentials"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_providers" ADD CONSTRAINT "model_providers_network_profile_id_fkey" FOREIGN KEY ("network_profile_id") REFERENCES "public"."network_profiles"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_providers" ADD CONSTRAINT "model_providers_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_providers" ADD CONSTRAINT "model_providers_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "network_profiles" ADD CONSTRAINT "network_profiles_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "provider_task_policies" ADD CONSTRAINT "provider_task_policies_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_affiliations" ADD CONSTRAINT "relation_affiliations_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_affiliations" ADD CONSTRAINT "relation_affiliations_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_affiliations" ADD CONSTRAINT "relation_affiliations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_affiliations" ADD CONSTRAINT "relation_affiliations_person_object_id_fkey" FOREIGN KEY ("person_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_affiliations" ADD CONSTRAINT "relation_affiliations_organization_object_id_fkey" FOREIGN KEY ("organization_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_affiliations" ADD CONSTRAINT "relation_affiliations_object_relation_id_fkey" FOREIGN KEY ("object_relation_id") REFERENCES "public"."object_relations"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_identities" ADD CONSTRAINT "relation_identities_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_identities" ADD CONSTRAINT "relation_identities_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_identities" ADD CONSTRAINT "relation_identities_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_identities" ADD CONSTRAINT "relation_identities_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_notes" ADD CONSTRAINT "relation_notes_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_notes" ADD CONSTRAINT "relation_notes_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_notes" ADD CONSTRAINT "relation_notes_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_notes" ADD CONSTRAINT "relation_notes_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_organizations" ADD CONSTRAINT "relation_organizations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_organizations" ADD CONSTRAINT "relation_organizations_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_organizations" ADD CONSTRAINT "relation_organizations_parent_object_id_fkey" FOREIGN KEY ("parent_organization_object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_people" ADD CONSTRAINT "relation_people_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_people" ADD CONSTRAINT "relation_people_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_source_links" ADD CONSTRAINT "relation_source_links_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_source_links" ADD CONSTRAINT "relation_source_links_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_source_links" ADD CONSTRAINT "relation_source_links_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_source_links" ADD CONSTRAINT "relation_source_links_object_id_fkey" FOREIGN KEY ("object_id","space_id") REFERENCES "public"."space_objects"("id","space_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_source_links" ADD CONSTRAINT "relation_source_links_activity_id_fkey" FOREIGN KEY ("activity_id") REFERENCES "public"."activity_records"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_source_links" ADD CONSTRAINT "relation_source_links_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "relation_source_links" ADD CONSTRAINT "relation_source_links_evidence_id_fkey" FOREIGN KEY ("evidence_id") REFERENCES "public"."extracted_evidence"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "retrieval_aliases" ADD CONSTRAINT "retrieval_aliases_retrieval_object_id_fkey" FOREIGN KEY ("retrieval_object_id") REFERENCES "public"."retrieval_objects"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "retrieval_aliases" ADD CONSTRAINT "retrieval_aliases_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "retrieval_chunks" ADD CONSTRAINT "retrieval_chunks_retrieval_object_id_fkey" FOREIGN KEY ("retrieval_object_id") REFERENCES "public"."retrieval_objects"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "retrieval_chunks" ADD CONSTRAINT "retrieval_chunks_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "retrieval_edges" ADD CONSTRAINT "retrieval_edges_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "retrieval_feedback_events" ADD CONSTRAINT "retrieval_feedback_events_actor_user_id_fkey" FOREIGN KEY ("actor_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "retrieval_feedback_events" ADD CONSTRAINT "retrieval_feedback_events_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "retrieval_objects" ADD CONSTRAINT "retrieval_objects_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "external_run_records" ADD CONSTRAINT "external_run_records_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "external_run_records" ADD CONSTRAINT "external_run_records_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_evaluations" ADD CONSTRAINT "run_evaluations_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_evaluations" ADD CONSTRAINT "run_evaluations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_events" ADD CONSTRAINT "run_events_actor_id_fkey" FOREIGN KEY ("actor_id") REFERENCES "public"."actors"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_events" ADD CONSTRAINT "run_events_artifact_id_fkey" FOREIGN KEY ("artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_events" ADD CONSTRAINT "run_events_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_events" ADD CONSTRAINT "run_events_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_events" ADD CONSTRAINT "run_events_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_events" ADD CONSTRAINT "run_events_step_id_fkey" FOREIGN KEY ("step_id") REFERENCES "public"."run_steps"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_events" ADD CONSTRAINT "run_events_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_execution_locks" ADD CONSTRAINT "fk_run_execution_locks_job_id_jobs" FOREIGN KEY ("job_id") REFERENCES "public"."jobs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_execution_locks" ADD CONSTRAINT "run_execution_locks_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_finalizations" ADD CONSTRAINT "run_finalizations_run_evaluation_id_fkey" FOREIGN KEY ("run_evaluation_id") REFERENCES "public"."run_evaluations"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_finalizations" ADD CONSTRAINT "run_finalizations_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_finalizations" ADD CONSTRAINT "run_finalizations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_finalizations" ADD CONSTRAINT "run_finalizations_task_evaluation_id_fkey" FOREIGN KEY ("task_evaluation_id") REFERENCES "public"."task_evaluations"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "fk_run_steps_task_id_tasks" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "run_steps_actor_id_fkey" FOREIGN KEY ("actor_id") REFERENCES "public"."actors"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "run_steps_artifact_id_fkey" FOREIGN KEY ("artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "run_steps_parent_step_id_fkey" FOREIGN KEY ("parent_step_id") REFERENCES "public"."run_steps"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "run_steps_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "run_steps_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "run_steps_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."sessions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "run_steps_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_steps" ADD CONSTRAINT "run_steps_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "fk_runs_project_id_projects" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "fk_runs_working_dir_id" FOREIGN KEY ("working_dir_id") REFERENCES "public"."working_dirs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_agent_version_id_fkey" FOREIGN KEY ("agent_version_id") REFERENCES "public"."agent_versions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_context_snapshot_id_fkey" FOREIGN KEY ("context_snapshot_id") REFERENCES "public"."context_snapshots"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_delegation_id_fkey" FOREIGN KEY ("delegation_id") REFERENCES "public"."run_delegations"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_instructed_by_agent_id_fkey" FOREIGN KEY ("instructed_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_instructed_by_user_id_fkey" FOREIGN KEY ("instructed_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_model_provider_id_fkey" FOREIGN KEY ("model_provider_id") REFERENCES "public"."model_providers"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_runtime_profile_id_fkey" FOREIGN KEY ("runtime_profile_id") REFERENCES "public"."agent_runtime_profiles"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_parent_run_id_fkey" FOREIGN KEY ("parent_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_root_run_id_fkey" FOREIGN KEY ("root_run_id") REFERENCES "public"."runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_run_group_id_fkey" FOREIGN KEY ("run_group_id") REFERENCES "public"."agent_run_groups"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."sessions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "runs_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "fk_runs_delegation_same_space" FOREIGN KEY ("delegation_id","space_id") REFERENCES "public"."run_delegations"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "fk_runs_instructed_by_agent_same_space" FOREIGN KEY ("instructed_by_agent_id","space_id") REFERENCES "public"."agents"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "fk_runs_parent_run_same_space" FOREIGN KEY ("parent_run_id","space_id") REFERENCES "public"."runs"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "fk_runs_root_run_same_space" FOREIGN KEY ("root_run_id","space_id") REFERENCES "public"."runs"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runs" ADD CONSTRAINT "fk_runs_run_group_same_space" FOREIGN KEY ("run_group_id","space_id") REFERENCES "public"."agent_run_groups"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_evaluations" ADD CONSTRAINT "task_evaluations_evaluator_agent_id_fkey" FOREIGN KEY ("evaluator_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_evaluations" ADD CONSTRAINT "task_evaluations_evaluator_user_id_fkey" FOREIGN KEY ("evaluator_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_evaluations" ADD CONSTRAINT "task_evaluations_run_evaluation_id_fkey" FOREIGN KEY ("run_evaluation_id") REFERENCES "public"."run_evaluations"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_evaluations" ADD CONSTRAINT "task_evaluations_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_evaluations" ADD CONSTRAINT "task_evaluations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_evaluations" ADD CONSTRAINT "task_evaluations_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_runs" ADD CONSTRAINT "task_runs_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_runs" ADD CONSTRAINT "task_runs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_runs" ADD CONSTRAINT "task_runs_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runtime_tool_bindings" ADD CONSTRAINT "runtime_tool_bindings_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runtime_tool_bindings" ADD CONSTRAINT "runtime_tool_bindings_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runtime_tool_bindings" ADD CONSTRAINT "runtime_tool_bindings_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_runtime_tool_policies" ADD CONSTRAINT "space_runtime_tool_policies_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_runtime_tool_policies" ADD CONSTRAINT "space_runtime_tool_policies_updated_by_user_id_fkey" FOREIGN KEY ("updated_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "scheduler_tasks" ADD CONSTRAINT "scheduler_tasks_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "scheduler_tasks" ADD CONSTRAINT "scheduler_tasks_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "messages" ADD CONSTRAINT "messages_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."sessions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "messages" ADD CONSTRAINT "messages_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "messages" ADD CONSTRAINT "messages_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "session_summaries" ADD CONSTRAINT "fk_session_summaries_source_first_message_id_messages" FOREIGN KEY ("source_first_message_id") REFERENCES "public"."messages"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "session_summaries" ADD CONSTRAINT "fk_session_summaries_source_last_message_id_messages" FOREIGN KEY ("source_last_message_id") REFERENCES "public"."messages"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "session_summaries" ADD CONSTRAINT "session_summaries_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."sessions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "session_summaries" ADD CONSTRAINT "session_summaries_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "session_summaries" ADD CONSTRAINT "session_summaries_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "settings" ADD CONSTRAINT "settings_updated_by_user_id_fkey" FOREIGN KEY ("updated_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_pointers" ADD CONSTRAINT "source_pointers_granted_by_user_id_fkey" FOREIGN KEY ("granted_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_pointers" ADD CONSTRAINT "source_pointers_owner_space_id_fkey" FOREIGN KEY ("owner_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_pointers" ADD CONSTRAINT "source_pointers_source_space_id_fkey" FOREIGN KEY ("source_space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extraction_jobs" ADD CONSTRAINT "extraction_jobs_connection_id_fkey" FOREIGN KEY ("connection_id") REFERENCES "public"."source_connections"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extraction_jobs" ADD CONSTRAINT "extraction_jobs_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extraction_jobs" ADD CONSTRAINT "extraction_jobs_source_snapshot_id_fkey" FOREIGN KEY ("source_snapshot_id") REFERENCES "public"."source_snapshots"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "extraction_jobs" ADD CONSTRAINT "extraction_jobs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_annotations" ADD CONSTRAINT "reader_annotations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_annotations" ADD CONSTRAINT "reader_annotations_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_annotations" ADD CONSTRAINT "reader_annotations_artifact_id_fkey" FOREIGN KEY ("artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_annotations" ADD CONSTRAINT "reader_annotations_source_snapshot_id_fkey" FOREIGN KEY ("source_snapshot_id") REFERENCES "public"."source_snapshots"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_annotations" ADD CONSTRAINT "reader_annotations_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_comment_threads" ADD CONSTRAINT "reader_comment_threads_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_comment_threads" ADD CONSTRAINT "reader_comment_threads_annotation_id_fkey" FOREIGN KEY ("annotation_id") REFERENCES "public"."reader_annotations"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_comment_threads" ADD CONSTRAINT "reader_comment_threads_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_comments" ADD CONSTRAINT "reader_comments_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_comments" ADD CONSTRAINT "reader_comments_thread_id_fkey" FOREIGN KEY ("thread_id") REFERENCES "public"."reader_comment_threads"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reader_comments" ADD CONSTRAINT "reader_comments_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connection_user_subscriptions" ADD CONSTRAINT "source_connection_user_subscriptions_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connection_user_subscriptions" ADD CONSTRAINT "source_connection_user_subscriptions_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connection_user_subscriptions" ADD CONSTRAINT "source_connection_user_subscriptions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connection_user_subscriptions" ADD CONSTRAINT "source_connection_user_subscriptions_recommended_by_user_id_fke" FOREIGN KEY ("recommended_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connections" ADD CONSTRAINT "source_connections_connector_id_fkey" FOREIGN KEY ("connector_id") REFERENCES "public"."source_connectors"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connections" ADD CONSTRAINT "source_connections_credential_id_fkey" FOREIGN KEY ("credential_id") REFERENCES "public"."credentials"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connections" ADD CONSTRAINT "source_connections_owner_user_id_fkey" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connections" ADD CONSTRAINT "source_connections_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connections" ADD CONSTRAINT "source_connections_active_handler_version_id_fkey" FOREIGN KEY ("active_handler_version_id") REFERENCES "public"."source_handler_versions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connections" ADD CONSTRAINT "source_connections_last_handler_run_id_fkey" FOREIGN KEY ("last_handler_run_id") REFERENCES "public"."source_handler_runs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_connections" ADD CONSTRAINT "source_connections_active_recipe_version_id_fkey" FOREIGN KEY ("active_recipe_version_id") REFERENCES "public"."source_recipe_versions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_runs" ADD CONSTRAINT "source_handler_runs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_runs" ADD CONSTRAINT "source_handler_runs_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_runs" ADD CONSTRAINT "source_handler_runs_handler_version_id_fkey" FOREIGN KEY ("handler_version_id") REFERENCES "public"."source_handler_versions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_runs" ADD CONSTRAINT "source_handler_runs_extraction_job_id_fkey" FOREIGN KEY ("extraction_job_id") REFERENCES "public"."extraction_jobs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_runs" ADD CONSTRAINT "source_handler_runs_input_artifact_id_fkey" FOREIGN KEY ("input_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_runs" ADD CONSTRAINT "source_handler_runs_output_artifact_id_fkey" FOREIGN KEY ("output_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_runs" ADD CONSTRAINT "source_handler_runs_logs_artifact_id_fkey" FOREIGN KEY ("logs_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_versions" ADD CONSTRAINT "source_handler_versions_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_versions" ADD CONSTRAINT "source_handler_versions_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_versions" ADD CONSTRAINT "source_handler_versions_handler_artifact_id_fkey" FOREIGN KEY ("handler_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_versions" ADD CONSTRAINT "source_handler_versions_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_versions" ADD CONSTRAINT "source_handler_versions_created_by_run_id_fkey" FOREIGN KEY ("created_by_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_handler_versions" ADD CONSTRAINT "source_handler_versions_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_item_user_states" ADD CONSTRAINT "source_item_user_states_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_item_user_states" ADD CONSTRAINT "source_item_user_states_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_item_user_states" ADD CONSTRAINT "source_item_user_states_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_items" ADD CONSTRAINT "fk_source_items_extracted_artifact_id_artifacts" FOREIGN KEY ("extracted_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_items" ADD CONSTRAINT "fk_source_items_raw_artifact_id_artifacts" FOREIGN KEY ("raw_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_items" ADD CONSTRAINT "fk_source_items_summary_artifact_id_artifacts" FOREIGN KEY ("summary_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_items" ADD CONSTRAINT "source_items_connection_id_fkey" FOREIGN KEY ("connection_id") REFERENCES "public"."source_connections"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_items" ADD CONSTRAINT "source_items_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_items" ADD CONSTRAINT "source_items_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_item_decisions" ADD CONSTRAINT "source_post_processing_item_decisions_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_item_decisions" ADD CONSTRAINT "source_post_processing_item_decisions_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_item_decisions" ADD CONSTRAINT "source_post_processing_item_decisions_rule_id_fkey" FOREIGN KEY ("rule_id") REFERENCES "public"."source_post_processing_rules"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_item_decisions" ADD CONSTRAINT "source_post_processing_item_decisions_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."source_post_processing_runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_item_decisions" ADD CONSTRAINT "source_post_processing_item_decisions_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_item_decisions" ADD CONSTRAINT "source_post_processing_item_decisions_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_rules" ADD CONSTRAINT "source_post_processing_rules_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_rules" ADD CONSTRAINT "source_post_processing_rules_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_rules" ADD CONSTRAINT "source_post_processing_rules_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_rules" ADD CONSTRAINT "source_post_processing_rules_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_rules" ADD CONSTRAINT "source_post_processing_rules_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_runs" ADD CONSTRAINT "source_post_processing_runs_agent_id_fkey" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_runs" ADD CONSTRAINT "source_post_processing_runs_agent_run_id_fkey" FOREIGN KEY ("agent_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_runs" ADD CONSTRAINT "source_post_processing_runs_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_runs" ADD CONSTRAINT "source_post_processing_runs_rule_id_fkey" FOREIGN KEY ("rule_id") REFERENCES "public"."source_post_processing_rules"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_runs" ADD CONSTRAINT "source_post_processing_runs_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_runs" ADD CONSTRAINT "source_post_processing_runs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_post_processing_runs" ADD CONSTRAINT "source_post_processing_runs_triggered_by_user_id_fkey" FOREIGN KEY ("triggered_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_recipe_versions" ADD CONSTRAINT "source_recipe_versions_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_recipe_versions" ADD CONSTRAINT "source_recipe_versions_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_recipe_versions" ADD CONSTRAINT "source_recipe_versions_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_recipe_versions" ADD CONSTRAINT "source_recipe_versions_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_snapshots" ADD CONSTRAINT "source_snapshots_artifact_id_fkey" FOREIGN KEY ("artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_snapshots" ADD CONSTRAINT "source_snapshots_connection_id_fkey" FOREIGN KEY ("connection_id") REFERENCES "public"."source_connections"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_snapshots" ADD CONSTRAINT "source_snapshots_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "source_snapshots" ADD CONSTRAINT "source_snapshots_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_invitations" ADD CONSTRAINT "fk_space_invitations_invited_by_user_id_users" FOREIGN KEY ("invited_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_invitations" ADD CONSTRAINT "space_invitations_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_memberships" ADD CONSTRAINT "space_memberships_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "space_memberships" ADD CONSTRAINT "space_memberships_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "spaces" ADD CONSTRAINT "fk_spaces_created_by_user_id_users" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "board_columns" ADD CONSTRAINT "board_columns_board_id_fkey" FOREIGN KEY ("board_id") REFERENCES "public"."boards"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "board_columns" ADD CONSTRAINT "board_columns_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "boards" ADD CONSTRAINT "boards_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "boards" ADD CONSTRAINT "boards_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "boards" ADD CONSTRAINT "boards_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "boards" ADD CONSTRAINT "boards_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "boards" ADD CONSTRAINT "boards_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_artifacts" ADD CONSTRAINT "task_artifacts_artifact_id_fkey" FOREIGN KEY ("artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_artifacts" ADD CONSTRAINT "task_artifacts_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_artifacts" ADD CONSTRAINT "task_artifacts_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_artifacts" ADD CONSTRAINT "task_artifacts_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_dependencies" ADD CONSTRAINT "task_dependencies_depends_on_task_id_fkey" FOREIGN KEY ("depends_on_task_id") REFERENCES "public"."tasks"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_dependencies" ADD CONSTRAINT "task_dependencies_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_dependencies" ADD CONSTRAINT "task_dependencies_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_proposals" ADD CONSTRAINT "task_proposals_proposal_id_fkey" FOREIGN KEY ("proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_proposals" ADD CONSTRAINT "task_proposals_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_proposals" ADD CONSTRAINT "task_proposals_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_assigned_agent_id_fkey" FOREIGN KEY ("assigned_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_assigned_user_id_fkey" FOREIGN KEY ("assigned_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_board_id_fkey" FOREIGN KEY ("board_id") REFERENCES "public"."boards"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_claimed_by_agent_id_fkey" FOREIGN KEY ("claimed_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_claimed_by_user_id_fkey" FOREIGN KEY ("claimed_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_column_id_fkey" FOREIGN KEY ("column_id") REFERENCES "public"."board_columns"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_created_by_agent_id_fkey" FOREIGN KEY ("created_by_agent_id") REFERENCES "public"."agents"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_parent_task_id_fkey" FOREIGN KEY ("parent_task_id") REFERENCES "public"."tasks"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_source_activity_id_fkey" FOREIGN KEY ("source_activity_id") REFERENCES "public"."activity_records"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_source_artifact_id_fkey" FOREIGN KEY ("source_artifact_id") REFERENCES "public"."artifacts"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_source_proposal_id_fkey" FOREIGN KEY ("source_proposal_id") REFERENCES "public"."proposals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_source_run_id_fkey" FOREIGN KEY ("source_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "validation_recipes" ADD CONSTRAINT "validation_recipes_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "validation_recipes" ADD CONSTRAINT "validation_recipes_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_bindings" ADD CONSTRAINT "project_source_bindings_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_bindings" ADD CONSTRAINT "project_source_bindings_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_bindings" ADD CONSTRAINT "project_source_bindings_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_bindings" ADD CONSTRAINT "project_source_bindings_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_item_links" ADD CONSTRAINT "project_source_item_links_binding_id_fkey" FOREIGN KEY ("project_source_binding_id") REFERENCES "public"."project_source_bindings"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_item_links" ADD CONSTRAINT "project_source_item_links_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_item_links" ADD CONSTRAINT "project_source_item_links_source_connection_id_fkey" FOREIGN KEY ("source_connection_id") REFERENCES "public"."source_connections"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_item_links" ADD CONSTRAINT "project_source_item_links_source_item_id_fkey" FOREIGN KEY ("source_item_id") REFERENCES "public"."source_items"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_source_item_links" ADD CONSTRAINT "project_source_item_links_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_workspaces" ADD CONSTRAINT "project_workspaces_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_workspaces" ADD CONSTRAINT "project_workspaces_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "project_workspaces" ADD CONSTRAINT "project_workspaces_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "working_dirs" ADD CONSTRAINT "working_dirs_project_id_fkey" FOREIGN KEY ("project_id","space_id") REFERENCES "public"."projects"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "working_dirs" ADD CONSTRAINT "working_dirs_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."sessions"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "working_dirs" ADD CONSTRAINT "working_dirs_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workspace_profiles" ADD CONSTRAINT "workspace_profiles_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workspace_profiles" ADD CONSTRAINT "workspace_profiles_validation_recipe_id_fkey" FOREIGN KEY ("validation_recipe_id") REFERENCES "public"."validation_recipes"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workspace_profiles" ADD CONSTRAINT "workspace_profiles_workspace_id_fkey" FOREIGN KEY ("workspace_id","space_id") REFERENCES "public"."workspaces"("id","space_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workspaces" ADD CONSTRAINT "workspaces_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workspaces" ADD CONSTRAINT "workspaces_space_id_fkey" FOREIGN KEY ("space_id") REFERENCES "public"."spaces"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "ix_academic_papers_space_id" ON "academic_papers" USING btree ("space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_academic_papers_space_doi" ON "academic_papers" USING btree ("space_id","doi") WHERE (doi IS NOT NULL);--> statement-breakpoint
CREATE UNIQUE INDEX "uq_academic_papers_space_arxiv_id" ON "academic_papers" USING btree ("space_id","arxiv_id") WHERE (arxiv_id IS NOT NULL);--> statement-breakpoint
CREATE INDEX "ix_activity_records_activity_type" ON "activity_records" USING btree ("activity_type");--> statement-breakpoint
CREATE INDEX "ix_activity_records_agent_id" ON "activity_records" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_owner_user_id" ON "activity_records" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_project_id" ON "activity_records" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_session_id" ON "activity_records" USING btree ("session_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_source_kind" ON "activity_records" USING btree ("source_kind");--> statement-breakpoint
CREATE INDEX "ix_activity_records_source_run_id" ON "activity_records" USING btree ("source_run_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_source_task_id" ON "activity_records" USING btree ("source_task_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_source_trust" ON "activity_records" USING btree ("source_trust");--> statement-breakpoint
CREATE INDEX "ix_activity_records_space_id" ON "activity_records" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_status" ON "activity_records" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_activity_records_subject_user_id" ON "activity_records" USING btree ("subject_user_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_user_id" ON "activity_records" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_activity_records_workspace_id" ON "activity_records" USING btree ("workspace_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_activity_records_space_aggregate_key" ON "activity_records" USING btree ("space_id","aggregate_key") WHERE (aggregate_key IS NOT NULL);--> statement-breakpoint
CREATE INDEX "ix_agent_run_group_members_agent" ON "agent_run_group_members" USING btree ("space_id","agent_id");--> statement-breakpoint
CREATE INDEX "ix_agent_run_group_members_group" ON "agent_run_group_members" USING btree ("space_id","group_id");--> statement-breakpoint
CREATE INDEX "ix_agent_run_groups_manager_user_updated" ON "agent_run_groups" USING btree ("space_id","manager_user_id","updated_at");--> statement-breakpoint
CREATE INDEX "ix_agent_run_groups_root_run" ON "agent_run_groups" USING btree ("space_id","root_run_id");--> statement-breakpoint
CREATE INDEX "ix_agent_run_groups_status_updated" ON "agent_run_groups" USING btree ("space_id","status","updated_at");--> statement-breakpoint
CREATE INDEX "ix_agent_run_messages_group_created" ON "agent_run_messages" USING btree ("space_id","group_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_agent_run_messages_run_created" ON "agent_run_messages" USING btree ("space_id","run_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_agent_run_messages_sender_agent_created" ON "agent_run_messages" USING btree ("space_id","sender_agent_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_run_delegations_child_run" ON "run_delegations" USING btree ("space_id","child_run_id");--> statement-breakpoint
CREATE INDEX "ix_run_delegations_group_created" ON "run_delegations" USING btree ("space_id","group_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_run_delegations_parent_run" ON "run_delegations" USING btree ("space_id","parent_run_id");--> statement-breakpoint
CREATE INDEX "ix_run_delegations_requesting_agent_created" ON "run_delegations" USING btree ("space_id","requesting_agent_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_run_delegations_status_updated" ON "run_delegations" USING btree ("space_id","status","updated_at");--> statement-breakpoint
CREATE INDEX "ix_run_delegations_target_agent_created" ON "run_delegations" USING btree ("space_id","target_agent_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_actors_actor_type" ON "actors" USING btree ("actor_type");--> statement-breakpoint
CREATE INDEX "ix_actors_agent_id" ON "actors" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_actors_service_name" ON "actors" USING btree ("service_name");--> statement-breakpoint
CREATE INDEX "ix_actors_space_id" ON "actors" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_actors_status" ON "actors" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_actors_user_id" ON "actors" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_agent_runtime_profiles_agent_id" ON "agent_runtime_profiles" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_agent_runtime_profiles_credential_profile_id" ON "agent_runtime_profiles" USING btree ("credential_profile_id");--> statement-breakpoint
CREATE INDEX "ix_agent_runtime_profiles_model_provider_id" ON "agent_runtime_profiles" USING btree ("model_provider_id");--> statement-breakpoint
CREATE INDEX "ix_agent_runtime_profiles_space_id" ON "agent_runtime_profiles" USING btree ("space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_agent_runtime_profiles_default_per_agent" ON "agent_runtime_profiles" USING btree ("agent_id") WHERE (is_default = true);--> statement-breakpoint
CREATE INDEX "ix_agent_versions_agent_id" ON "agent_versions" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_agent_versions_model_provider_id" ON "agent_versions" USING btree ("model_provider_id");--> statement-breakpoint
CREATE INDEX "ix_agent_versions_source_activity_id" ON "agent_versions" USING btree ("source_activity_id");--> statement-breakpoint
CREATE INDEX "ix_agent_versions_source_proposal_id" ON "agent_versions" USING btree ("source_proposal_id");--> statement-breakpoint
CREATE INDEX "ix_agent_versions_space_id" ON "agent_versions" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_agents_agent_kind" ON "agents" USING btree ("agent_kind");--> statement-breakpoint
CREATE INDEX "ix_agents_current_version_id" ON "agents" USING btree ("current_version_id");--> statement-breakpoint
CREATE INDEX "ix_agents_owner_user_id" ON "agents" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_agents_space_id" ON "agents" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_agents_status" ON "agents" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_agents_system_assistant_per_space" ON "agents" USING btree ("space_id") WHERE (((agent_kind)::text = 'system_assistant'::text) AND ((status)::text = 'active'::text));--> statement-breakpoint
CREATE UNIQUE INDEX "uq_agents_system_evolver_per_space" ON "agents" USING btree ("space_id") WHERE (((agent_kind)::text = 'system_evolver'::text) AND ((status)::text = 'active'::text));--> statement-breakpoint
CREATE UNIQUE INDEX "uq_agents_system_source_post_processor_per_space" ON "agents" USING btree ("space_id") WHERE (((agent_kind)::text = 'system_source_post_processor'::text) AND ((status)::text = 'active'::text));--> statement-breakpoint
CREATE INDEX "ix_cli_credential_events_run_id" ON "cli_credential_events" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_cli_credential_events_space_id" ON "cli_credential_events" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_cli_credential_profiles_owner_user_id" ON "cli_credential_profiles" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_cli_credential_profiles_runtime" ON "cli_credential_profiles" USING btree ("runtime");--> statement-breakpoint
CREATE INDEX "ix_cli_credential_space_grants_network_profile_id" ON "cli_credential_space_grants" USING btree ("network_profile_id");--> statement-breakpoint
CREATE INDEX "ix_cli_credential_space_grants_owner_user_id" ON "cli_credential_space_grants" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_cli_credential_space_grants_space_id" ON "cli_credential_space_grants" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_artifacts_artifact_type" ON "artifacts" USING btree ("artifact_type");--> statement-breakpoint
CREATE INDEX "ix_artifacts_owner_user_id" ON "artifacts" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_artifacts_project_id" ON "artifacts" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_artifacts_proposal_id" ON "artifacts" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_artifacts_run_id" ON "artifacts" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_artifacts_space_id" ON "artifacts" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_artifacts_workspace_id" ON "artifacts" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_auth_accounts_user_id" ON "auth_accounts" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_user_sessions_user_id" ON "user_sessions" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_users_email" ON "users" USING btree ("email");--> statement-breakpoint
CREATE INDEX "ix_users_status" ON "users" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_automation_credential_grants_automation_id" ON "automation_credential_grants" USING btree ("automation_id");--> statement-breakpoint
CREATE INDEX "ix_automation_credential_grants_granted_by_user_id" ON "automation_credential_grants" USING btree ("granted_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_automation_credential_grants_lookup" ON "automation_credential_grants" USING btree ("space_id","automation_id","status");--> statement-breakpoint
CREATE INDEX "ix_automation_credential_grants_space_id" ON "automation_credential_grants" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_automation_credential_grants_status" ON "automation_credential_grants" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_automation_runs_automation_created" ON "automation_runs" USING btree ("automation_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_automation_runs_automation_id" ON "automation_runs" USING btree ("automation_id");--> statement-breakpoint
CREATE INDEX "ix_automation_runs_run_id" ON "automation_runs" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_automation_runs_triggered_by_user_id" ON "automation_runs" USING btree ("triggered_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_automations_agent_id" ON "automations" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_automations_owner_user_id" ON "automations" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_automations_space_id" ON "automations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_automations_space_project" ON "automations" USING btree ("space_id","project_id");--> statement-breakpoint
CREATE INDEX "ix_automations_status" ON "automations" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_automations_workspace_id" ON "automations" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_capability_enablements_agent_id" ON "capability_enablements" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_capability_enablements_capability_key" ON "capability_enablements" USING btree ("capability_key");--> statement-breakpoint
CREATE INDEX "ix_capability_enablements_project_id" ON "capability_enablements" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_capability_enablements_space_id" ON "capability_enablements" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_capability_enablements_user_id" ON "capability_enablements" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_capability_enablements_agent" ON "capability_enablements" USING btree ("space_id","agent_id","capability_key") WHERE ((agent_id IS NOT NULL) AND (project_id IS NULL) AND (user_id IS NULL));--> statement-breakpoint
CREATE UNIQUE INDEX "uq_capability_enablements_project" ON "capability_enablements" USING btree ("space_id","project_id","capability_key") WHERE ((project_id IS NOT NULL) AND (agent_id IS NULL) AND (user_id IS NULL));--> statement-breakpoint
CREATE UNIQUE INDEX "uq_capability_enablements_space" ON "capability_enablements" USING btree ("space_id","capability_key") WHERE ((project_id IS NULL) AND (agent_id IS NULL) AND (user_id IS NULL));--> statement-breakpoint
CREATE UNIQUE INDEX "uq_capability_enablements_user" ON "capability_enablements" USING btree ("space_id","user_id","capability_key") WHERE ((user_id IS NOT NULL) AND (project_id IS NULL) AND (agent_id IS NULL));--> statement-breakpoint
CREATE INDEX "ix_capability_overlays_base_version_id" ON "capability_overlays" USING btree ("base_version_id");--> statement-breakpoint
CREATE INDEX "ix_capability_overlays_capability_key" ON "capability_overlays" USING btree ("capability_key");--> statement-breakpoint
CREATE INDEX "ix_capability_overlays_key_scope_status" ON "capability_overlays" USING btree ("capability_key","scope_type","scope_id","status");--> statement-breakpoint
CREATE INDEX "ix_capability_overlays_overlay_type" ON "capability_overlays" USING btree ("overlay_type");--> statement-breakpoint
CREATE INDEX "ix_capability_overlays_proposal_id" ON "capability_overlays" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_capability_overlays_scope_id" ON "capability_overlays" USING btree ("scope_id");--> statement-breakpoint
CREATE INDEX "ix_capability_overlays_scope_type" ON "capability_overlays" USING btree ("scope_type");--> statement-breakpoint
CREATE INDEX "ix_capability_overlays_status" ON "capability_overlays" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_capability_runtime_bindings_capability_key" ON "capability_runtime_bindings" USING btree ("capability_key");--> statement-breakpoint
CREATE INDEX "ix_capability_runtime_bindings_space_id" ON "capability_runtime_bindings" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_capability_runtime_bindings_version_id" ON "capability_runtime_bindings" USING btree ("capability_version_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_capability_runtime_bindings_scope_runtime" ON "capability_runtime_bindings" USING btree (COALESCE(space_id, '__global__'::character varying),capability_key,COALESCE(capability_version_id, '__none__'::character varying),runtime_adapter_type,render_mode);--> statement-breakpoint
CREATE INDEX "ix_capability_versions_capability_key" ON "capability_versions" USING btree ("capability_key");--> statement-breakpoint
CREATE INDEX "ix_capability_versions_key_scope_status" ON "capability_versions" USING btree ("capability_key","scope_type","scope_id","status");--> statement-breakpoint
CREATE INDEX "ix_capability_versions_parent_version_id" ON "capability_versions" USING btree ("parent_version_id");--> statement-breakpoint
CREATE INDEX "ix_capability_versions_proposal_id" ON "capability_versions" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_capability_versions_scope_id" ON "capability_versions" USING btree ("scope_id");--> statement-breakpoint
CREATE INDEX "ix_capability_versions_scope_type" ON "capability_versions" USING btree ("scope_type");--> statement-breakpoint
CREATE INDEX "ix_capability_versions_source" ON "capability_versions" USING btree ("source");--> statement-breakpoint
CREATE INDEX "ix_capability_versions_status" ON "capability_versions" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_project_workflow_profiles_space_project" ON "project_workflow_profiles" USING btree ("space_id","project_id");--> statement-breakpoint
CREATE INDEX "ix_project_workflow_profiles_template" ON "project_workflow_profiles" USING btree ("workflow_template_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_project_workflow_profiles_name" ON "project_workflow_profiles" USING btree ("space_id","project_id","workflow_template_id","name");--> statement-breakpoint
CREATE INDEX "ix_skill_local_overlays_package_scope" ON "skill_local_overlays" USING btree ("space_id","skill_package_id","scope_type","scope_id");--> statement-breakpoint
CREATE INDEX "ix_skill_local_overlays_scope" ON "skill_local_overlays" USING btree ("space_id","scope_type","scope_id");--> statement-breakpoint
CREATE INDEX "ix_skill_local_overlays_status" ON "skill_local_overlays" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_skill_local_overlays_active_scope" ON "skill_local_overlays" USING btree (space_id,skill_package_id,scope_type,COALESCE(scope_id, ''::character varying)) WHERE ((status)::text = 'active'::text);--> statement-breakpoint
CREATE INDEX "ix_skill_package_files_kind" ON "skill_package_files" USING btree ("kind");--> statement-breakpoint
CREATE INDEX "ix_skill_package_files_package_id" ON "skill_package_files" USING btree ("skill_package_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ux_skill_package_files_package_path" ON "skill_package_files" USING btree ("skill_package_id","path");--> statement-breakpoint
CREATE INDEX "ix_skill_packages_risk_level" ON "skill_packages" USING btree ("risk_level");--> statement-breakpoint
CREATE INDEX "ix_skill_packages_source_id" ON "skill_packages" USING btree ("source_id");--> statement-breakpoint
CREATE INDEX "ix_skill_packages_space_id" ON "skill_packages" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_skill_packages_status" ON "skill_packages" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_skill_sources_content_hash" ON "skill_sources" USING btree ("content_hash");--> statement-breakpoint
CREATE INDEX "ix_skill_sources_source_type" ON "skill_sources" USING btree ("source_type");--> statement-breakpoint
CREATE INDEX "ix_skill_sources_space_id" ON "skill_sources" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_card_review_states_card_id" ON "card_review_states" USING btree ("card_id");--> statement-breakpoint
CREATE INDEX "ix_card_review_states_user_due" ON "card_review_states" USING btree ("user_id","due_at");--> statement-breakpoint
CREATE INDEX "ix_card_reviews_card_id" ON "card_reviews" USING btree ("card_id");--> statement-breakpoint
CREATE INDEX "ix_card_reviews_rating" ON "card_reviews" USING btree ("rating");--> statement-breakpoint
CREATE INDEX "ix_card_reviews_user_reviewed_at" ON "card_reviews" USING btree ("user_id","reviewed_at");--> statement-breakpoint
CREATE INDEX "ix_cards_card_type" ON "cards" USING btree ("card_type");--> statement-breakpoint
CREATE INDEX "ix_cards_created_at" ON "cards" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "ix_cards_source" ON "cards" USING btree ("source_type","source_id");--> statement-breakpoint
CREATE INDEX "ix_cards_source_id" ON "cards" USING btree ("source_id");--> statement-breakpoint
CREATE INDEX "ix_cards_source_type" ON "cards" USING btree ("source_type");--> statement-breakpoint
CREATE INDEX "ix_cards_space_id" ON "cards" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_cards_status" ON "cards" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_context_artifact_revocations_artifact_id" ON "context_artifact_revocations" USING btree ("artifact_id");--> statement-breakpoint
CREATE INDEX "ix_context_artifact_revocations_space_scope" ON "context_artifact_revocations" USING btree ("space_id","scope_type","scope_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_context_artifact_revocations_active_scope" ON "context_artifact_revocations" USING btree ("space_id","artifact_id","scope_type","scope_id") WHERE (deleted_at IS NULL);--> statement-breakpoint
CREATE INDEX "ix_context_digests_digest_type" ON "context_digests" USING btree ("digest_type");--> statement-breakpoint
CREATE INDEX "ix_context_digests_scope_id" ON "context_digests" USING btree ("scope_id");--> statement-breakpoint
CREATE INDEX "ix_context_digests_scope_type" ON "context_digests" USING btree ("scope_type");--> statement-breakpoint
CREATE INDEX "ix_context_digests_source_hash" ON "context_digests" USING btree ("source_hash");--> statement-breakpoint
CREATE INDEX "ix_context_digests_space_id" ON "context_digests" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_context_digests_status" ON "context_digests" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_context_digests_current_scope" ON "context_digests" USING btree (space_id,scope_type,COALESCE(scope_id, ''::character varying),digest_type) WHERE ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('dirty'::character varying)::text]));--> statement-breakpoint
CREATE INDEX "ix_context_profiles_scope" ON "context_profiles" USING btree ("space_id","scope_type","scope_id");--> statement-breakpoint
CREATE INDEX "ix_context_profiles_status" ON "context_profiles" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_context_profiles_active_scope" ON "context_profiles" USING btree (space_id,scope_type,COALESCE(scope_id, ''::character varying)) WHERE ((status)::text = 'active'::text);--> statement-breakpoint
CREATE INDEX "ix_context_snapshot_items_context_snapshot_id" ON "context_snapshot_items" USING btree ("context_snapshot_id");--> statement-breakpoint
CREATE INDEX "ix_context_snapshot_items_item_type" ON "context_snapshot_items" USING btree ("item_type");--> statement-breakpoint
CREATE INDEX "ix_context_snapshots_agent_id" ON "context_snapshots" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_context_snapshots_run_id" ON "context_snapshots" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_context_snapshots_session_id" ON "context_snapshots" USING btree ("session_id");--> statement-breakpoint
CREATE INDEX "ix_context_snapshots_space_id" ON "context_snapshots" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_experiences_space_source_run" ON "evolution_experiences" USING btree ("space_id","source_run_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_experiences_space_strategy_created" ON "evolution_experiences" USING btree ("space_id","strategy_asset_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE UNIQUE INDEX "uq_evolution_experiences_space_key" ON "evolution_experiences" USING btree ("space_id","experience_key");--> statement-breakpoint
CREATE INDEX "ix_evolution_selector_decisions_space_run" ON "evolution_selector_decisions" USING btree ("space_id","run_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_selector_decisions_space_target_created" ON "evolution_selector_decisions" USING btree ("space_id","target_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "ix_evolution_signals_severity" ON "evolution_signals" USING btree ("severity");--> statement-breakpoint
CREATE INDEX "ix_evolution_signals_signal_type" ON "evolution_signals" USING btree ("signal_type");--> statement-breakpoint
CREATE INDEX "ix_evolution_signals_source_id" ON "evolution_signals" USING btree ("source_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_signals_source_type" ON "evolution_signals" USING btree ("source_type");--> statement-breakpoint
CREATE INDEX "ix_evolution_signals_space_id" ON "evolution_signals" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_signals_space_target_type_created" ON "evolution_signals" USING btree ("space_id","target_id","signal_type","created_at");--> statement-breakpoint
CREATE INDEX "ix_evolution_signals_target_id" ON "evolution_signals" USING btree ("target_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_strategy_assets_space_status_category_target" ON "evolution_strategy_assets" USING btree ("space_id","status","category","target_type");--> statement-breakpoint
CREATE INDEX "ix_evolution_strategy_assets_strategy_key" ON "evolution_strategy_assets" USING btree ("strategy_key");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_evolution_strategy_assets_space_key" ON "evolution_strategy_assets" USING btree ("space_id","strategy_key") WHERE (space_id IS NOT NULL);--> statement-breakpoint
CREATE UNIQUE INDEX "uq_evolution_strategy_assets_system_key" ON "evolution_strategy_assets" USING btree ("strategy_key") WHERE (space_id IS NULL);--> statement-breakpoint
CREATE INDEX "ix_evolution_targets_capability_key" ON "evolution_targets" USING btree ("capability_key");--> statement-breakpoint
CREATE INDEX "ix_evolution_targets_current_version_id" ON "evolution_targets" USING btree ("current_version_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_targets_risk_level" ON "evolution_targets" USING btree ("risk_level");--> statement-breakpoint
CREATE INDEX "ix_evolution_targets_space_id" ON "evolution_targets" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_targets_space_type_ref_status" ON "evolution_targets" USING btree ("space_id","target_type","target_ref_id","status");--> statement-breakpoint
CREATE INDEX "ix_evolution_targets_status" ON "evolution_targets" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_evolution_targets_target_ref_id" ON "evolution_targets" USING btree ("target_ref_id");--> statement-breakpoint
CREATE INDEX "ix_evolution_targets_target_type" ON "evolution_targets" USING btree ("target_type");--> statement-breakpoint
CREATE INDEX "ix_run_reflections_run_id" ON "run_reflections" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_run_reflections_space_id" ON "run_reflections" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_evaluation_runs_space_id" ON "evolvable_asset_evaluation_runs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_evaluation_runs_asset_id" ON "evolvable_asset_evaluation_runs" USING btree ("asset_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_evaluation_runs_candidate_version_id" ON "evolvable_asset_evaluation_runs" USING btree ("candidate_version_id");--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_pins_space_id" ON "evolvable_asset_pins" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_pins_asset_id" ON "evolvable_asset_pins" USING btree ("asset_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_evolvable_asset_pins_active_scope" ON "evolvable_asset_pins" USING btree ("space_id","asset_id","scope_type","scope_id") WHERE (status)::text = 'active'::text;--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_versions_asset_id" ON "evolvable_asset_versions" USING btree ("asset_id");--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_versions_space_id" ON "evolvable_asset_versions" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_versions_scope" ON "evolvable_asset_versions" USING btree ("asset_id","scope_type","scope_id","status");--> statement-breakpoint
CREATE INDEX "ix_evolvable_asset_versions_parent_version_id" ON "evolvable_asset_versions" USING btree ("parent_version_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_evolvable_asset_versions_asset_version" ON "evolvable_asset_versions" USING btree ("asset_id","version");--> statement-breakpoint
CREATE INDEX "ix_evolvable_assets_space_id" ON "evolvable_assets" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evolvable_assets_asset_type" ON "evolvable_assets" USING btree ("asset_type");--> statement-breakpoint
CREATE INDEX "ix_evolvable_assets_current_system_version_id" ON "evolvable_assets" USING btree ("current_system_version_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_evolvable_assets_space_key" ON "evolvable_assets" USING btree ("space_id","asset_key") WHERE (space_id IS NOT NULL);--> statement-breakpoint
CREATE UNIQUE INDEX "uq_evolvable_assets_system_key" ON "evolvable_assets" USING btree ("asset_key") WHERE (space_id IS NULL);--> statement-breakpoint
CREATE INDEX "ix_graph_view_states_scope_key" ON "graph_view_states" USING btree ("scope_key");--> statement-breakpoint
CREATE INDEX "ix_graph_view_states_space_user" ON "graph_view_states" USING btree ("space_id","user_id");--> statement-breakpoint
CREATE INDEX "ix_job_events_job_id" ON "job_events" USING btree ("job_id");--> statement-breakpoint
CREATE INDEX "ix_jobs_agent_id" ON "jobs" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_jobs_claim_pending" ON "jobs" USING btree ("priority" DESC NULLS FIRST,"scheduled_at") WHERE ((status)::text = 'pending'::text);--> statement-breakpoint
CREATE INDEX "ix_jobs_job_type" ON "jobs" USING btree ("job_type");--> statement-breakpoint
CREATE INDEX "ix_jobs_space_id" ON "jobs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_jobs_status" ON "jobs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_jobs_type_claim_pending" ON "jobs" USING btree ("job_type","priority" DESC NULLS FIRST,"scheduled_at") WHERE ((status)::text = 'pending'::text);--> statement-breakpoint
CREATE INDEX "ix_jobs_user_id" ON "jobs" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_jobs_workspace_id" ON "jobs" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_claim_sources_claim_id" ON "claim_sources" USING btree ("claim_id");--> statement-breakpoint
CREATE INDEX "ix_claim_sources_source_connection_id" ON "claim_sources" USING btree ("source_connection_id");--> statement-breakpoint
CREATE INDEX "ix_claim_sources_source_object_id" ON "claim_sources" USING btree ("source_object_id");--> statement-breakpoint
CREATE INDEX "ix_claim_sources_space_id" ON "claim_sources" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_claims_claim_kind" ON "claims" USING btree ("claim_kind");--> statement-breakpoint
CREATE INDEX "ix_claims_created_from_proposal_id" ON "claims" USING btree ("created_from_proposal_id");--> statement-breakpoint
CREATE INDEX "ix_claims_holder_object_id" ON "claims" USING btree ("holder_object_id");--> statement-breakpoint
CREATE INDEX "ix_claims_normalized_claim_hash" ON "claims" USING btree ("normalized_claim_hash");--> statement-breakpoint
CREATE INDEX "ix_claims_space_id" ON "claims" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_claims_subject_object_id" ON "claims" USING btree ("subject_object_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_created_by_agent_id" ON "evidence_links" USING btree ("created_by_agent_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_created_by_run_id" ON "evidence_links" USING btree ("created_by_run_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_created_by_user_id" ON "evidence_links" USING btree ("created_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_evidence_id" ON "evidence_links" USING btree ("evidence_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_evidence_target" ON "evidence_links" USING btree ("evidence_id","target_type","target_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_link_type" ON "evidence_links" USING btree ("link_type");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_space_id" ON "evidence_links" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_status" ON "evidence_links" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_target" ON "evidence_links" USING btree ("space_id","target_type","target_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_target_id" ON "evidence_links" USING btree ("target_id");--> statement-breakpoint
CREATE INDEX "ix_evidence_links_target_type" ON "evidence_links" USING btree ("target_type");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_evidence_links_active_dedupe" ON "evidence_links" USING btree ("space_id","evidence_id","target_type","target_id","link_type") WHERE ((status)::text = 'active'::text);--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_artifact_id" ON "extracted_evidence" USING btree ("artifact_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_content_hash" ON "extracted_evidence" USING btree ("content_hash");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_created_by_agent_id" ON "extracted_evidence" USING btree ("created_by_agent_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_created_by_run_id" ON "extracted_evidence" USING btree ("created_by_run_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_created_by_user_id" ON "extracted_evidence" USING btree ("created_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_deleted_at" ON "extracted_evidence" USING btree ("deleted_at");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_evidence_type" ON "extracted_evidence" USING btree ("evidence_type");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_extraction_job_id" ON "extracted_evidence" USING btree ("extraction_job_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_occurred_at" ON "extracted_evidence" USING btree ("occurred_at");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_source_item_id" ON "extracted_evidence" USING btree ("source_item_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_source_object" ON "extracted_evidence" USING btree ("space_id","source_object_type","source_object_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_source_object_id" ON "extracted_evidence" USING btree ("source_object_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_source_object_type" ON "extracted_evidence" USING btree ("source_object_type");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_source_snapshot_id" ON "extracted_evidence" USING btree ("source_snapshot_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_space_id" ON "extracted_evidence" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_space_status" ON "extracted_evidence" USING btree ("space_id","status");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_status" ON "extracted_evidence" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_extracted_evidence_trust_level" ON "extracted_evidence" USING btree ("trust_level");--> statement-breakpoint
CREATE INDEX "ix_knowledge_item_sources_knowledge_item_id" ON "knowledge_item_sources" USING btree ("knowledge_item_id");--> statement-breakpoint
CREATE INDEX "ix_knowledge_item_sources_relation_type" ON "knowledge_item_sources" USING btree ("relation_type");--> statement-breakpoint
CREATE INDEX "ix_knowledge_item_sources_source_id" ON "knowledge_item_sources" USING btree ("source_id");--> statement-breakpoint
CREATE INDEX "ix_knowledge_item_sources_space_id" ON "knowledge_item_sources" USING btree ("space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_knowledge_item_sources_unique" ON "knowledge_item_sources" USING btree ("knowledge_item_id","source_id","relation_type");--> statement-breakpoint
CREATE INDEX "ix_knowledge_items_created_from_proposal_id" ON "knowledge_items" USING btree ("created_from_proposal_id");--> statement-breakpoint
CREATE INDEX "ix_knowledge_items_knowledge_kind" ON "knowledge_items" USING btree ("knowledge_kind");--> statement-breakpoint
CREATE INDEX "ix_knowledge_items_redirect_to_item_id" ON "knowledge_items" USING btree ("redirect_to_item_id");--> statement-breakpoint
CREATE INDEX "ix_knowledge_items_root_item_id" ON "knowledge_items" USING btree ("root_item_id");--> statement-breakpoint
CREATE INDEX "ix_knowledge_items_slug" ON "knowledge_items" USING btree ("slug");--> statement-breakpoint
CREATE INDEX "ix_knowledge_items_space_id" ON "knowledge_items" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_knowledge_items_space_slug" ON "knowledge_items" USING btree ("space_id","slug");--> statement-breakpoint
CREATE INDEX "ix_knowledge_items_supersedes_item_id" ON "knowledge_items" USING btree ("supersedes_item_id");--> statement-breakpoint
CREATE INDEX "ix_note_collection_items_collection_id" ON "note_collection_items" USING btree ("space_id","collection_id");--> statement-breakpoint
CREATE INDEX "ix_note_collection_items_note_id" ON "note_collection_items" USING btree ("space_id","note_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_note_collections_one_archive_per_space" ON "note_collections" USING btree ("space_id") WHERE ((system_role)::text = 'archive'::text);--> statement-breakpoint
CREATE UNIQUE INDEX "ix_note_collections_one_inbox_per_space" ON "note_collections" USING btree ("space_id") WHERE ((system_role)::text = 'inbox'::text);--> statement-breakpoint
CREATE INDEX "ix_note_collections_parent_id" ON "note_collections" USING btree ("parent_id");--> statement-breakpoint
CREATE INDEX "ix_note_collections_parent_sort" ON "note_collections" USING btree ("space_id","parent_id","sort_order");--> statement-breakpoint
CREATE INDEX "ix_note_collections_space_id" ON "note_collections" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_note_collections_system_role" ON "note_collections" USING btree ("system_role");--> statement-breakpoint
CREATE INDEX "ix_note_links_from_object" ON "note_links" USING btree ("space_id","from_object_id");--> statement-breakpoint
CREATE INDEX "ix_note_links_link_type" ON "note_links" USING btree ("link_type");--> statement-breakpoint
CREATE INDEX "ix_note_links_space_id" ON "note_links" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_note_links_status" ON "note_links" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_note_links_to_object" ON "note_links" USING btree ("space_id","to_object_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_note_links_unique_active" ON "note_links" USING btree ("space_id","from_object_id","to_object_id","link_type") WHERE ((status)::text = 'active'::text);--> statement-breakpoint
CREATE INDEX "ix_notes_created_from_activity_id" ON "notes" USING btree ("created_from_activity_id");--> statement-breakpoint
CREATE INDEX "ix_notes_space_id" ON "notes" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_object_relations_from_object_id" ON "object_relations" USING btree ("from_object_id");--> statement-breakpoint
CREATE INDEX "ix_object_relations_relation_type" ON "object_relations" USING btree ("relation_type");--> statement-breakpoint
CREATE INDEX "ix_object_relations_source_claim_id" ON "object_relations" USING btree ("source_claim_id");--> statement-breakpoint
CREATE INDEX "ix_object_relations_source_object_id" ON "object_relations" USING btree ("source_object_id");--> statement-breakpoint
CREATE INDEX "ix_object_relations_space_id" ON "object_relations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_object_relations_status" ON "object_relations" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_object_relations_to_object_id" ON "object_relations" USING btree ("to_object_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_object_relations_unique_active" ON "object_relations" USING btree ("space_id","from_object_id","to_object_id","relation_type") WHERE ((status)::text = 'active'::text);--> statement-breakpoint
CREATE INDEX "ix_sources_source_activity_id" ON "sources" USING btree ("source_activity_id");--> statement-breakpoint
CREATE INDEX "ix_sources_source_type" ON "sources" USING btree ("source_type");--> statement-breakpoint
CREATE INDEX "ix_sources_space_id" ON "sources" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_space_object_kind_relation_hints_endpoint_kind" ON "space_object_kind_relation_hints" USING btree ("endpoint_object_kind_id");--> statement-breakpoint
CREATE INDEX "ix_space_object_kind_relation_hints_object_kind" ON "space_object_kind_relation_hints" USING btree ("object_kind_id");--> statement-breakpoint
CREATE INDEX "ix_space_object_kind_relation_hints_required" ON "space_object_kind_relation_hints" USING btree ("space_id","required");--> statement-breakpoint
CREATE INDEX "ix_space_object_kinds_base_object_type" ON "space_object_kinds" USING btree ("base_object_type");--> statement-breakpoint
CREATE INDEX "ix_space_object_kinds_created_by_user_id" ON "space_object_kinds" USING btree ("created_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_space_object_kinds_space_id" ON "space_object_kinds" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_space_object_kinds_status" ON "space_object_kinds" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_space_objects_created_by_user_id" ON "space_objects" USING btree ("created_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_space_objects_deleted_at" ON "space_objects" USING btree ("deleted_at");--> statement-breakpoint
CREATE INDEX "ix_space_objects_owner_user_id" ON "space_objects" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_space_objects_primary_project_id" ON "space_objects" USING btree ("primary_project_id");--> statement-breakpoint
CREATE INDEX "ix_space_objects_space_type" ON "space_objects" USING btree ("space_id","object_type");--> statement-breakpoint
CREATE INDEX "ix_space_objects_status" ON "space_objects" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_space_objects_visibility" ON "space_objects" USING btree ("visibility");--> statement-breakpoint
CREATE INDEX "ix_space_objects_workspace_id" ON "space_objects" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_memory_access_logs_accessed_at" ON "memory_access_logs" USING btree ("accessed_at");--> statement-breakpoint
CREATE INDEX "ix_memory_access_logs_agent_id" ON "memory_access_logs" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_memory_access_logs_memory_id" ON "memory_access_logs" USING btree ("memory_id");--> statement-breakpoint
CREATE INDEX "ix_memory_access_logs_run_id" ON "memory_access_logs" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_memory_access_logs_space_id" ON "memory_access_logs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_memory_access_logs_user_id" ON "memory_access_logs" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_agent_id" ON "memory_entries" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_created_from_proposal_id" ON "memory_entries" USING btree ("created_from_proposal_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_memory_layer" ON "memory_entries" USING btree ("memory_layer");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_memory_type" ON "memory_entries" USING btree ("memory_type");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_namespace" ON "memory_entries" USING btree ("namespace");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_owner_user_id" ON "memory_entries" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_project_id" ON "memory_entries" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_root_memory_id" ON "memory_entries" USING btree ("root_memory_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_scope_type" ON "memory_entries" USING btree ("scope_type");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_sensitivity_level" ON "memory_entries" USING btree ("sensitivity_level");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_space_id" ON "memory_entries" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_status" ON "memory_entries" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_subject_user_id" ON "memory_entries" USING btree ("subject_user_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_supersedes_memory_id" ON "memory_entries" USING btree ("supersedes_memory_id");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_visibility" ON "memory_entries" USING btree ("visibility");--> statement-breakpoint
CREATE INDEX "ix_memory_entries_workspace_id" ON "memory_entries" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_memory_maintenance_jobs_due" ON "memory_maintenance_jobs" USING btree ("status","run_after","updated_at");--> statement-breakpoint
CREATE INDEX "ix_memory_maintenance_jobs_owner" ON "memory_maintenance_jobs" USING btree ("space_id","owner_user_id","status","updated_at");--> statement-breakpoint
CREATE INDEX "ix_memory_relations_created_from_proposal_id" ON "memory_relations" USING btree ("created_from_proposal_id");--> statement-breakpoint
CREATE INDEX "ix_memory_relations_relation_type" ON "memory_relations" USING btree ("relation_type");--> statement-breakpoint
CREATE INDEX "ix_memory_relations_source" ON "memory_relations" USING btree ("space_id","source_type","source_id");--> statement-breakpoint
CREATE INDEX "ix_memory_relations_space_id" ON "memory_relations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_memory_relations_target" ON "memory_relations" USING btree ("space_id","target_type","target_id");--> statement-breakpoint
CREATE INDEX "ix_provenance_links_source" ON "provenance_links" USING btree ("space_id","source_type","source_id");--> statement-breakpoint
CREATE INDEX "ix_provenance_links_source_type" ON "provenance_links" USING btree ("source_type");--> statement-breakpoint
CREATE INDEX "ix_provenance_links_space_id" ON "provenance_links" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_provenance_links_target" ON "provenance_links" USING btree ("space_id","target_type","target_id");--> statement-breakpoint
CREATE INDEX "ix_participation_records_personal_space_id" ON "participation_records" USING btree ("personal_space_id");--> statement-breakpoint
CREATE INDEX "ix_participation_records_source" ON "participation_records" USING btree ("source_space_id","source_object_type","source_object_id");--> statement-breakpoint
CREATE INDEX "ix_participation_records_user_id" ON "participation_records" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grant_events_actor_user_id" ON "personal_memory_grant_events" USING btree ("actor_user_id");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grant_events_created_at" ON "personal_memory_grant_events" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grant_events_grant_id" ON "personal_memory_grant_events" USING btree ("grant_id");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grant_events_run_id" ON "personal_memory_grant_events" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grants_granting_user_id" ON "personal_memory_grants" USING btree ("granting_user_id");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grants_personal_space_id" ON "personal_memory_grants" USING btree ("personal_space_id");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grants_read_expires_at" ON "personal_memory_grants" USING btree ("read_expires_at");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grants_status" ON "personal_memory_grants" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grants_target_run_id" ON "personal_memory_grants" USING btree ("target_run_id");--> statement-breakpoint
CREATE INDEX "ix_personal_memory_grants_target_space_id" ON "personal_memory_grants" USING btree ("target_space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_personal_memory_grants_unique_active_consuming" ON "personal_memory_grants" USING btree ("granting_user_id","target_run_id") WHERE ((status)::text = ANY (ARRAY[('active'::character varying)::text, ('consuming'::character varying)::text]));--> statement-breakpoint
CREATE INDEX "ix_code_patch_snapshots_expires_at" ON "code_patch_snapshots" USING btree ("expires_at");--> statement-breakpoint
CREATE INDEX "ix_code_patch_snapshots_proposal_id" ON "code_patch_snapshots" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_code_patch_snapshots_workspace_id" ON "code_patch_snapshots" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "official_plugin_enablements_plugin_space_idx" ON "official_plugin_enablements" USING btree ("plugin_id","space_id") WHERE (space_id IS NOT NULL);--> statement-breakpoint
CREATE INDEX "official_plugin_enablements_space_idx" ON "official_plugin_enablements" USING btree ("space_id") WHERE (space_id IS NOT NULL);--> statement-breakpoint
CREATE UNIQUE INDEX "official_plugin_enablements_space_unique" ON "official_plugin_enablements" USING btree ("plugin_id","space_id") WHERE ((space_id IS NOT NULL) AND (user_id IS NULL));--> statement-breakpoint
CREATE UNIQUE INDEX "official_plugin_enablements_user_unique" ON "official_plugin_enablements" USING btree ("plugin_id","user_id") WHERE ((space_id IS NULL) AND (user_id IS NOT NULL));--> statement-breakpoint
CREATE INDEX "official_plugin_events_plugin_space_idx" ON "official_plugin_events" USING btree ("plugin_id","space_id","created_at" DESC NULLS FIRST) WHERE (space_id IS NOT NULL);--> statement-breakpoint
CREATE INDEX "official_plugin_events_space_idx" ON "official_plugin_events" USING btree ("space_id","created_at" DESC NULLS FIRST) WHERE (space_id IS NOT NULL);--> statement-breakpoint
CREATE INDEX "plugin_installs_status_idx" ON "plugin_installs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "plugin_migrations_plugin_id_idx" ON "plugin_migrations" USING btree ("plugin_id");--> statement-breakpoint
CREATE INDEX "ix_policies_created_from_proposal_id" ON "policies" USING btree ("created_from_proposal_id");--> statement-breakpoint
CREATE INDEX "ix_policies_domain" ON "policies" USING btree ("domain");--> statement-breakpoint
CREATE INDEX "ix_policies_policy_key" ON "policies" USING btree ("policy_key");--> statement-breakpoint
CREATE INDEX "ix_policies_space_id" ON "policies" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_policies_status" ON "policies" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_policies_supersedes_policy_id" ON "policies" USING btree ("supersedes_policy_id");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_action" ON "policy_decision_records" USING btree ("action");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_actor_id" ON "policy_decision_records" USING btree ("actor_id");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_audit_code" ON "policy_decision_records" USING btree ("audit_code");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_audit_created" ON "policy_decision_records" USING btree ("audit_code","created_at");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_created_at" ON "policy_decision_records" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_decision" ON "policy_decision_records" USING btree ("decision");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_proposal_created" ON "policy_decision_records" USING btree ("proposal_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_proposal_id" ON "policy_decision_records" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_resource_id" ON "policy_decision_records" USING btree ("resource_id");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_resource_type" ON "policy_decision_records" USING btree ("resource_type");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_risk_level" ON "policy_decision_records" USING btree ("risk_level");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_run_created" ON "policy_decision_records" USING btree ("run_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_run_id" ON "policy_decision_records" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_space_action_created" ON "policy_decision_records" USING btree ("space_id","action","created_at");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_space_created" ON "policy_decision_records" USING btree ("space_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_policy_decision_records_space_id" ON "policy_decision_records" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_prompt_deployment_refs_asset_label" ON "prompt_deployment_refs" USING btree ("asset_id","label");--> statement-breakpoint
CREATE INDEX "ix_prompt_deployment_refs_space_id" ON "prompt_deployment_refs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_prompt_deployment_refs_version_id" ON "prompt_deployment_refs" USING btree ("version_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_prompt_deployment_refs_active_scope_label" ON "prompt_deployment_refs" USING btree (COALESCE("space_id", ''),"asset_id","scope_type",COALESCE("scope_id", ''),"label") WHERE (status)::text = 'active'::text;--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_added_by_user_id" ON "project_corpus_items" USING btree ("added_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_evidence_id" ON "project_corpus_items" USING btree ("evidence_id");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_object_id" ON "project_corpus_items" USING btree ("object_id");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_project_id" ON "project_corpus_items" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_project_role" ON "project_corpus_items" USING btree ("space_id","project_id","role");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_project_triage" ON "project_corpus_items" USING btree ("space_id","project_id","triage_status");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_source_connection_id" ON "project_corpus_items" USING btree ("source_connection_id");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_source_decision_id" ON "project_corpus_items" USING btree ("source_decision_id");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_source_item_id" ON "project_corpus_items" USING btree ("source_item_id");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_space_id" ON "project_corpus_items" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_corpus_items_status" ON "project_corpus_items" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_project_corpus_items_project_evidence" ON "project_corpus_items" USING btree ("space_id","project_id","evidence_id") WHERE evidence_id IS NOT NULL AND object_id IS NULL;--> statement-breakpoint
CREATE UNIQUE INDEX "uq_project_corpus_items_project_object" ON "project_corpus_items" USING btree ("space_id","project_id","object_id") WHERE object_id IS NOT NULL;--> statement-breakpoint
CREATE UNIQUE INDEX "uq_project_corpus_items_project_source_item" ON "project_corpus_items" USING btree ("space_id","project_id","source_item_id") WHERE source_item_id IS NOT NULL AND object_id IS NULL AND evidence_id IS NULL;--> statement-breakpoint
CREATE INDEX "ix_project_experiment_campaigns_space_id" ON "project_experiment_campaigns" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_experiment_campaigns_project_id" ON "project_experiment_campaigns" USING btree ("space_id","project_id");--> statement-breakpoint
CREATE INDEX "ix_project_experiment_provenance_space_id" ON "project_experiment_provenance" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_experiment_provenance_project_id" ON "project_experiment_provenance" USING btree ("space_id","project_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_project_experiment_provenance_project_key" ON "project_experiment_provenance" USING btree ("space_id","project_id","experiment_key");--> statement-breakpoint
CREATE INDEX "ix_project_experiment_runs_space_id" ON "project_experiment_runs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_experiment_runs_campaign_id" ON "project_experiment_runs" USING btree ("space_id","campaign_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_artifact_links_space_id" ON "project_research_artifact_links" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_artifact_links_project_type" ON "project_research_artifact_links" USING btree ("space_id","project_id","artifact_type");--> statement-breakpoint
CREATE INDEX "ix_project_research_artifact_links_workflow_id" ON "project_research_artifact_links" USING btree ("workflow_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_artifact_links_artifact_id" ON "project_research_artifact_links" USING btree ("artifact_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_checkpoints_space_id" ON "project_research_checkpoints" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_checkpoints_project_id" ON "project_research_checkpoints" USING btree ("space_id","project_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_checkpoints_workflow_stage" ON "project_research_checkpoints" USING btree ("space_id","workflow_id","stage_key");--> statement-breakpoint
CREATE INDEX "ix_project_research_checkpoints_status" ON "project_research_checkpoints" USING btree ("space_id","status");--> statement-breakpoint
CREATE INDEX "ix_project_research_claim_links_space_id" ON "project_research_claim_links" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_claim_links_project_id" ON "project_research_claim_links" USING btree ("space_id","project_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_claim_links_workflow_id" ON "project_research_claim_links" USING btree ("workflow_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_project_research_claim_links_project_claim" ON "project_research_claim_links" USING btree ("space_id","project_id","claim_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_profiles_space_id" ON "project_research_profiles" USING btree ("space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_project_research_profiles_project" ON "project_research_profiles" USING btree ("space_id","project_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_screening_criteria_space_id" ON "project_research_screening_criteria" USING btree ("space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_project_research_screening_criteria_project" ON "project_research_screening_criteria" USING btree ("space_id","project_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_workflows_space_id" ON "project_research_workflows" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_research_workflows_project_status" ON "project_research_workflows" USING btree ("space_id","project_id","status");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_project_members_project_user_unique" ON "project_members" USING btree ("project_id","user_id");--> statement-breakpoint
CREATE INDEX "ix_project_members_space_id" ON "project_members" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_members_user_id" ON "project_members" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_project_public_summaries_project_unique" ON "project_public_summaries" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_project_public_summaries_review_status" ON "project_public_summaries" USING btree ("review_status");--> statement-breakpoint
CREATE INDEX "ix_project_public_summaries_space_id" ON "project_public_summaries" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_projects_owner_user_id" ON "projects" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_projects_space_id" ON "projects" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_projects_status" ON "projects" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_projects_space_name_active" ON "projects" USING btree ("space_id","name") WHERE ((status)::text = 'active'::text);--> statement-breakpoint
CREATE INDEX "ix_proposal_approvals_approval_type" ON "proposal_approvals" USING btree ("approval_type");--> statement-breakpoint
CREATE INDEX "ix_proposal_approvals_approver_user_id" ON "proposal_approvals" USING btree ("approver_user_id");--> statement-breakpoint
CREATE INDEX "ix_proposal_approvals_created_at" ON "proposal_approvals" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "ix_proposal_approvals_grant_id" ON "proposal_approvals" USING btree ("grant_id");--> statement-breakpoint
CREATE INDEX "ix_proposal_approvals_proposal_id" ON "proposal_approvals" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_proposal_approvals_target_space_id" ON "proposal_approvals" USING btree ("target_space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_proposal_approvals_unique_active" ON "proposal_approvals" USING btree ("proposal_id","approval_type","approver_user_id","grant_id") WHERE ((status)::text = 'approved'::text);--> statement-breakpoint
CREATE INDEX "ix_proposals_created_by_run_id" ON "proposals" USING btree ("created_by_run_id");--> statement-breakpoint
CREATE INDEX "ix_proposals_project_id" ON "proposals" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_proposals_proposal_type" ON "proposals" USING btree ("proposal_type");--> statement-breakpoint
CREATE INDEX "ix_proposals_risk_level" ON "proposals" USING btree ("risk_level");--> statement-breakpoint
CREATE INDEX "ix_proposals_space_id" ON "proposals" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_proposals_status" ON "proposals" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_proposals_urgency" ON "proposals" USING btree ("urgency");--> statement-breakpoint
CREATE INDEX "ix_proposals_workspace_id" ON "proposals" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_credentials_owner_user_id" ON "credentials" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_credentials_space_id" ON "credentials" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_model_provider_credentials_provider_id" ON "model_provider_credentials" USING btree ("provider_id");--> statement-breakpoint
CREATE INDEX "ix_model_provider_credentials_space_id" ON "model_provider_credentials" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_model_provider_space_grants_network_profile_id" ON "model_provider_space_grants" USING btree ("network_profile_id");--> statement-breakpoint
CREATE INDEX "ix_model_provider_space_grants_owner_user_id" ON "model_provider_space_grants" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_model_provider_space_grants_space_id" ON "model_provider_space_grants" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_model_providers_credential_id" ON "model_providers" USING btree ("credential_id");--> statement-breakpoint
CREATE INDEX "ix_model_providers_network_profile_id" ON "model_providers" USING btree ("network_profile_id");--> statement-breakpoint
CREATE INDEX "ix_model_providers_owner_user_id" ON "model_providers" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_model_providers_space_id" ON "model_providers" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_network_profiles_space_id" ON "network_profiles" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_provider_task_policies_space_id" ON "provider_task_policies" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_relation_affiliations_person" ON "relation_affiliations" USING btree ("person_object_id");--> statement-breakpoint
CREATE INDEX "ix_relation_affiliations_organization" ON "relation_affiliations" USING btree ("organization_object_id");--> statement-breakpoint
CREATE INDEX "ix_relation_affiliations_space_id" ON "relation_affiliations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_relation_affiliations_status" ON "relation_affiliations" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_relation_identities_object_id" ON "relation_identities" USING btree ("object_id");--> statement-breakpoint
CREATE INDEX "ix_relation_identities_space_id" ON "relation_identities" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_relation_identities_id_type" ON "relation_identities" USING btree ("id_type");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_relation_identities_object_type_value" ON "relation_identities" USING btree ("space_id","object_id","id_type","id_value");--> statement-breakpoint
CREATE INDEX "ix_relation_notes_object_id" ON "relation_notes" USING btree ("object_id");--> statement-breakpoint
CREATE INDEX "ix_relation_notes_space_id" ON "relation_notes" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_relation_organizations_space_id" ON "relation_organizations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_relation_organizations_parent" ON "relation_organizations" USING btree ("parent_organization_object_id");--> statement-breakpoint
CREATE INDEX "ix_relation_people_space_id" ON "relation_people" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_relation_source_links_object_id" ON "relation_source_links" USING btree ("object_id");--> statement-breakpoint
CREATE INDEX "ix_relation_source_links_space_id" ON "relation_source_links" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_relation_source_links_activity_id" ON "relation_source_links" USING btree ("activity_id");--> statement-breakpoint
CREATE INDEX "ix_relation_source_links_source_item_id" ON "relation_source_links" USING btree ("source_item_id");--> statement-breakpoint
CREATE INDEX "ix_relation_source_links_evidence_id" ON "relation_source_links" USING btree ("evidence_id");--> statement-breakpoint
CREATE INDEX "ix_retrieval_aliases_normalized_alias" ON "retrieval_aliases" USING btree ("normalized_alias");--> statement-breakpoint
CREATE INDEX "ix_retrieval_aliases_object" ON "retrieval_aliases" USING btree ("object_type","object_id");--> statement-breakpoint
CREATE INDEX "ix_retrieval_aliases_space_id" ON "retrieval_aliases" USING btree ("space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_retrieval_aliases_unique" ON "retrieval_aliases" USING btree ("space_id","object_type","object_id","normalized_alias","alias_kind");--> statement-breakpoint
CREATE INDEX "ix_retrieval_chunks_embedding_filter" ON "retrieval_chunks" USING btree ("space_id","object_type","embedding_dimensions") WHERE (embedding IS NOT NULL);--> statement-breakpoint
CREATE INDEX "ix_retrieval_chunks_embedding_hnsw_2560" ON "retrieval_chunks" USING hnsw ((embedding::halfvec(2560)) halfvec_cosine_ops) WHERE ((embedding IS NOT NULL) AND (embedding_dimensions = 2560));--> statement-breakpoint
CREATE INDEX "ix_retrieval_chunks_embedding_pending" ON "retrieval_chunks" USING btree ("space_id","embedding_claimed_at","created_at","id") WHERE (embedding IS NULL);--> statement-breakpoint
CREATE INDEX "ix_retrieval_chunks_object" ON "retrieval_chunks" USING btree ("object_type","object_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_retrieval_chunks_object_chunk_unique" ON "retrieval_chunks" USING btree ("retrieval_object_id","chunk_index");--> statement-breakpoint
CREATE INDEX "ix_retrieval_chunks_space_id" ON "retrieval_chunks" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_retrieval_chunks_tsv" ON "retrieval_chunks" USING gin ("tsv");--> statement-breakpoint
CREATE INDEX "ix_retrieval_edges_from" ON "retrieval_edges" USING btree ("from_object_type","from_object_id");--> statement-breakpoint
CREATE INDEX "ix_retrieval_edges_space_id" ON "retrieval_edges" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_retrieval_edges_to" ON "retrieval_edges" USING btree ("to_object_type","to_object_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_retrieval_edges_unique" ON "retrieval_edges" USING btree ("space_id","from_object_type","from_object_id","to_object_type","to_object_id","relation_type","edge_origin");--> statement-breakpoint
CREATE INDEX "ix_retrieval_feedback_events_lookup" ON "retrieval_feedback_events" USING btree ("space_id","actor_user_id","surface","query_hash","object_type","object_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_retrieval_feedback_events_object" ON "retrieval_feedback_events" USING btree ("space_id","object_type","object_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_retrieval_feedback_events_space_created" ON "retrieval_feedback_events" USING btree ("space_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_retrieval_objects_object" ON "retrieval_objects" USING btree ("object_type","object_id");--> statement-breakpoint
CREATE INDEX "ix_retrieval_objects_source_connections" ON "retrieval_objects" USING gin ("source_connection_ids_json");--> statement-breakpoint
CREATE INDEX "ix_retrieval_objects_space_id" ON "retrieval_objects" USING btree ("space_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_retrieval_objects_space_object_unique" ON "retrieval_objects" USING btree ("space_id","object_type","object_id");--> statement-breakpoint
CREATE INDEX "ix_retrieval_objects_status" ON "retrieval_objects" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_external_run_records_run_id" ON "external_run_records" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_external_run_records_runtime_adapter_type" ON "external_run_records" USING btree ("runtime_adapter_type");--> statement-breakpoint
CREATE INDEX "ix_external_run_records_space_id" ON "external_run_records" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_run_evaluations_evaluated_at" ON "run_evaluations" USING btree ("evaluated_at");--> statement-breakpoint
CREATE INDEX "ix_run_evaluations_evaluator_version" ON "run_evaluations" USING btree ("evaluator_version");--> statement-breakpoint
CREATE INDEX "ix_run_evaluations_run_id" ON "run_evaluations" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_run_evaluations_run_id_evaluated_at" ON "run_evaluations" USING btree ("run_id","evaluated_at");--> statement-breakpoint
CREATE INDEX "ix_run_evaluations_space_id" ON "run_evaluations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_run_events_actor_id" ON "run_events" USING btree ("actor_id");--> statement-breakpoint
CREATE INDEX "ix_run_events_artifact_id" ON "run_events" USING btree ("artifact_id");--> statement-breakpoint
CREATE INDEX "ix_run_events_created_at" ON "run_events" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "ix_run_events_error_code" ON "run_events" USING btree ("error_code");--> statement-breakpoint
CREATE INDEX "ix_run_events_event_type" ON "run_events" USING btree ("event_type");--> statement-breakpoint
CREATE INDEX "ix_run_events_proposal_id" ON "run_events" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_run_events_run_id" ON "run_events" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_run_events_space_id" ON "run_events" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_run_events_status" ON "run_events" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_run_events_step_id" ON "run_events" USING btree ("step_id");--> statement-breakpoint
CREATE INDEX "ix_run_events_workspace_id" ON "run_events" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_run_finalizations_finalized_at" ON "run_finalizations" USING btree ("finalized_at");--> statement-breakpoint
CREATE INDEX "ix_run_finalizations_run_evaluation_id" ON "run_finalizations" USING btree ("run_evaluation_id");--> statement-breakpoint
CREATE INDEX "ix_run_finalizations_run_id" ON "run_finalizations" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_run_finalizations_space_id" ON "run_finalizations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_run_finalizations_task_evaluation_id" ON "run_finalizations" USING btree ("task_evaluation_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_actor_id" ON "run_steps" USING btree ("actor_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_artifact_id" ON "run_steps" USING btree ("artifact_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_parent_step_id" ON "run_steps" USING btree ("parent_step_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_proposal_id" ON "run_steps" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_run_id" ON "run_steps" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_session_id" ON "run_steps" USING btree ("session_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_space_id" ON "run_steps" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_space_run_index" ON "run_steps" USING btree ("space_id","run_id","step_index");--> statement-breakpoint
CREATE INDEX "ix_run_steps_status" ON "run_steps" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_run_steps_step_type" ON "run_steps" USING btree ("step_type");--> statement-breakpoint
CREATE INDEX "ix_run_steps_task_id" ON "run_steps" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "ix_run_steps_workspace_id" ON "run_steps" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_runs_agent_id" ON "runs" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_runs_agent_version_id" ON "runs" USING btree ("agent_version_id");--> statement-breakpoint
CREATE INDEX "ix_runs_context_snapshot_id" ON "runs" USING btree ("context_snapshot_id");--> statement-breakpoint
CREATE INDEX "ix_runs_delegation_id" ON "runs" USING btree ("space_id","delegation_id");--> statement-breakpoint
CREATE INDEX "ix_runs_group_id" ON "runs" USING btree ("space_id","run_group_id");--> statement-breakpoint
CREATE INDEX "ix_runs_instructed_by_agent_id" ON "runs" USING btree ("space_id","instructed_by_agent_id");--> statement-breakpoint
CREATE INDEX "ix_runs_instructed_by_user_id" ON "runs" USING btree ("instructed_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_runs_mode" ON "runs" USING btree ("mode");--> statement-breakpoint
CREATE INDEX "ix_runs_model_provider_id" ON "runs" USING btree ("model_provider_id");--> statement-breakpoint
CREATE INDEX "ix_runs_parent_run_id" ON "runs" USING btree ("parent_run_id");--> statement-breakpoint
CREATE INDEX "ix_runs_parent_run_space" ON "runs" USING btree ("space_id","parent_run_id");--> statement-breakpoint
CREATE INDEX "ix_runs_project_id" ON "runs" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_runs_root_run_id" ON "runs" USING btree ("space_id","root_run_id");--> statement-breakpoint
CREATE INDEX "ix_runs_run_type" ON "runs" USING btree ("run_type");--> statement-breakpoint
CREATE INDEX "ix_runs_runtime_profile_id" ON "runs" USING btree ("runtime_profile_id");--> statement-breakpoint
CREATE INDEX "ix_runs_session_id" ON "runs" USING btree ("session_id");--> statement-breakpoint
CREATE INDEX "ix_runs_space_id" ON "runs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_runs_status" ON "runs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_runs_trigger_origin" ON "runs" USING btree ("trigger_origin");--> statement-breakpoint
CREATE INDEX "ix_runs_working_dir_id" ON "runs" USING btree ("working_dir_id");--> statement-breakpoint
CREATE INDEX "ix_runs_workspace_id" ON "runs" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_task_evaluations_run_evaluation_id" ON "task_evaluations" USING btree ("run_evaluation_id");--> statement-breakpoint
CREATE INDEX "ix_task_evaluations_run_id" ON "task_evaluations" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_task_evaluations_space_id" ON "task_evaluations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_task_evaluations_task_id" ON "task_evaluations" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "ix_task_runs_run_id" ON "task_runs" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_task_runs_space_id" ON "task_runs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_task_runs_task_id" ON "task_runs" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "ix_runtime_tool_bindings_agent_id" ON "runtime_tool_bindings" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_runtime_tool_bindings_capability_id" ON "runtime_tool_bindings" USING btree ("capability_id");--> statement-breakpoint
CREATE INDEX "ix_runtime_tool_bindings_enabled" ON "runtime_tool_bindings" USING btree ("enabled");--> statement-breakpoint
CREATE INDEX "ix_runtime_tool_bindings_runtime_adapter_type" ON "runtime_tool_bindings" USING btree ("runtime_adapter_type");--> statement-breakpoint
CREATE INDEX "ix_runtime_tool_bindings_space_id" ON "runtime_tool_bindings" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_runtime_tool_bindings_workspace_id" ON "runtime_tool_bindings" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_space_runtime_tool_policies_runtime" ON "space_runtime_tool_policies" USING btree ("runtime");--> statement-breakpoint
CREATE INDEX "ix_space_runtime_tool_policies_space_id" ON "space_runtime_tool_policies" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_space_runtime_tool_policies_updated_by_user_id" ON "space_runtime_tool_policies" USING btree ("updated_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_scheduler_tasks_due" ON "scheduler_tasks" USING btree ("task_type","status","next_run_at");--> statement-breakpoint
CREATE INDEX "ix_scheduler_tasks_space_id" ON "scheduler_tasks" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_scheduler_tasks_user_id" ON "scheduler_tasks" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_messages_session_id" ON "messages" USING btree ("session_id");--> statement-breakpoint
CREATE INDEX "ix_messages_space_id" ON "messages" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_messages_user_id" ON "messages" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_session_summaries_one_active_per_session" ON "session_summaries" USING btree ("session_id") WHERE ((status)::text = 'active'::text);--> statement-breakpoint
CREATE INDEX "ix_session_summaries_session_id" ON "session_summaries" USING btree ("session_id");--> statement-breakpoint
CREATE INDEX "ix_session_summaries_session_status" ON "session_summaries" USING btree ("session_id","status");--> statement-breakpoint
CREATE INDEX "ix_session_summaries_space_id" ON "session_summaries" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_session_summaries_space_session_status" ON "session_summaries" USING btree ("space_id","session_id","status");--> statement-breakpoint
CREATE INDEX "ix_session_summaries_status" ON "session_summaries" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_session_summaries_user_id" ON "session_summaries" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_sessions_agent_id" ON "sessions" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_sessions_space_id" ON "sessions" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_sessions_status" ON "sessions" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_sessions_user_id" ON "sessions" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_sessions_workspace_id" ON "sessions" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_settings_key" ON "settings" USING btree ("settings_key");--> statement-breakpoint
CREATE INDEX "ix_settings_scope" ON "settings" USING btree ("scope_type","scope_id");--> statement-breakpoint
CREATE INDEX "ix_source_pointers_expires_at" ON "source_pointers" USING btree ("expires_at");--> statement-breakpoint
CREATE INDEX "ix_source_pointers_granted_by_user_id" ON "source_pointers" USING btree ("granted_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_source_pointers_owner_space_id" ON "source_pointers" USING btree ("owner_space_id");--> statement-breakpoint
CREATE INDEX "ix_source_pointers_source" ON "source_pointers" USING btree ("source_space_id","source_object_type","source_object_id");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_connection_id" ON "extraction_jobs" USING btree ("connection_id");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_source_item_id" ON "extraction_jobs" USING btree ("source_item_id");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_source_object" ON "extraction_jobs" USING btree ("space_id","source_object_type","source_object_id");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_source_object_id" ON "extraction_jobs" USING btree ("source_object_id");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_source_object_type" ON "extraction_jobs" USING btree ("source_object_type");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_source_snapshot_id" ON "extraction_jobs" USING btree ("source_snapshot_id");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_space_created" ON "extraction_jobs" USING btree ("space_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_space_id" ON "extraction_jobs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_space_status" ON "extraction_jobs" USING btree ("space_id","status");--> statement-breakpoint
CREATE INDEX "ix_extraction_jobs_status" ON "extraction_jobs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_reader_annotations_space_artifact" ON "reader_annotations" USING btree ("space_id","artifact_id","status");--> statement-breakpoint
CREATE INDEX "ix_reader_annotations_space_snapshot" ON "reader_annotations" USING btree ("space_id","source_snapshot_id","status");--> statement-breakpoint
CREATE INDEX "ix_reader_annotations_space_source_item" ON "reader_annotations" USING btree ("space_id","source_item_id","status");--> statement-breakpoint
CREATE INDEX "ix_reader_annotations_space_user" ON "reader_annotations" USING btree ("space_id","created_by_user_id","status");--> statement-breakpoint
CREATE INDEX "ix_reader_annotations_space_visibility" ON "reader_annotations" USING btree ("space_id","visibility","status");--> statement-breakpoint
CREATE INDEX "ix_reader_comment_threads_space_annotation" ON "reader_comment_threads" USING btree ("space_id","annotation_id","status");--> statement-breakpoint
CREATE INDEX "ix_reader_comment_threads_space_user" ON "reader_comment_threads" USING btree ("space_id","created_by_user_id","status");--> statement-breakpoint
CREATE INDEX "ix_reader_comments_space_thread" ON "reader_comments" USING btree ("space_id","thread_id","status");--> statement-breakpoint
CREATE INDEX "ix_reader_comments_space_user" ON "reader_comments" USING btree ("space_id","created_by_user_id","status");--> statement-breakpoint
CREATE INDEX "ix_source_connection_user_subscriptions_connection_status" ON "source_connection_user_subscriptions" USING btree ("space_id","source_connection_id","status");--> statement-breakpoint
CREATE INDEX "ix_source_connection_user_subscriptions_user_status" ON "source_connection_user_subscriptions" USING btree ("space_id","user_id","status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_source_connection_user_subscriptions_space_connection_user" ON "source_connection_user_subscriptions" USING btree ("space_id","source_connection_id","user_id");--> statement-breakpoint
CREATE INDEX "ix_source_connections_active_handler_version_id" ON "source_connections" USING btree ("active_handler_version_id");--> statement-breakpoint
CREATE INDEX "ix_source_connections_active_recipe_version_id" ON "source_connections" USING btree ("active_recipe_version_id");--> statement-breakpoint
CREATE INDEX "ix_source_connections_connector_id" ON "source_connections" USING btree ("connector_id");--> statement-breakpoint
CREATE INDEX "ix_source_connections_credential_id" ON "source_connections" USING btree ("credential_id");--> statement-breakpoint
CREATE INDEX "ix_source_connections_deleted_at" ON "source_connections" USING btree ("deleted_at");--> statement-breakpoint
CREATE INDEX "ix_source_connections_owner_user_id" ON "source_connections" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "ix_source_connections_space_id" ON "source_connections" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_source_connections_space_status" ON "source_connections" USING btree ("space_id","status");--> statement-breakpoint
CREATE INDEX "ix_source_connections_status" ON "source_connections" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_source_connections_visibility" ON "source_connections" USING btree ("visibility");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_source_connections_active_endpoint" ON "source_connections" USING btree ("space_id","connector_id","endpoint_url") WHERE ((endpoint_url IS NOT NULL) AND (deleted_at IS NULL) AND ((status)::text <> 'archived'::text));--> statement-breakpoint
CREATE UNIQUE INDEX "ix_source_connectors_connector_key" ON "source_connectors" USING btree ("connector_key");--> statement-breakpoint
CREATE INDEX "ix_source_connectors_connector_type" ON "source_connectors" USING btree ("connector_type");--> statement-breakpoint
CREATE INDEX "ix_source_connectors_status" ON "source_connectors" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_source_handler_runs_handler_version_id" ON "source_handler_runs" USING btree ("handler_version_id");--> statement-breakpoint
CREATE INDEX "ix_source_handler_runs_source_connection_id" ON "source_handler_runs" USING btree ("source_connection_id");--> statement-breakpoint
CREATE INDEX "ix_source_handler_runs_space_id" ON "source_handler_runs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_source_handler_runs_status" ON "source_handler_runs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_source_handler_versions_source_connection_id" ON "source_handler_versions" USING btree ("source_connection_id");--> statement-breakpoint
CREATE INDEX "ix_source_handler_versions_space_id" ON "source_handler_versions" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_source_handler_versions_status" ON "source_handler_versions" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_source_item_user_states_item_user" ON "source_item_user_states" USING btree ("source_item_id","user_id");--> statement-breakpoint
CREATE INDEX "ix_source_item_user_states_user_status" ON "source_item_user_states" USING btree ("space_id","user_id","library_status","read_status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_source_item_user_states_space_item_user" ON "source_item_user_states" USING btree ("space_id","source_item_id","user_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_canonical_uri" ON "source_items" USING btree ("space_id","canonical_uri");--> statement-breakpoint
CREATE INDEX "ix_source_items_connection_id" ON "source_items" USING btree ("connection_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_content_hash" ON "source_items" USING btree ("content_hash");--> statement-breakpoint
CREATE INDEX "ix_source_items_created_by_user_id" ON "source_items" USING btree ("created_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_deleted_at" ON "source_items" USING btree ("deleted_at");--> statement-breakpoint
CREATE INDEX "ix_source_items_extracted_artifact_id" ON "source_items" USING btree ("extracted_artifact_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_item_type" ON "source_items" USING btree ("item_type");--> statement-breakpoint
CREATE INDEX "ix_source_items_occurred_at" ON "source_items" USING btree ("occurred_at");--> statement-breakpoint
CREATE INDEX "ix_source_items_raw_artifact_id" ON "source_items" USING btree ("raw_artifact_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_source_domain" ON "source_items" USING btree ("source_domain");--> statement-breakpoint
CREATE INDEX "ix_source_items_source_external_id" ON "source_items" USING btree ("source_external_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_source_object" ON "source_items" USING btree ("space_id","source_object_type","source_object_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_source_object_id" ON "source_items" USING btree ("source_object_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_source_object_type" ON "source_items" USING btree ("source_object_type");--> statement-breakpoint
CREATE INDEX "ix_source_items_space_connection" ON "source_items" USING btree ("space_id","connection_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_space_created_by_user_id" ON "source_items" USING btree ("space_id","created_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_space_domain" ON "source_items" USING btree ("space_id","source_domain");--> statement-breakpoint
CREATE INDEX "ix_source_items_space_id" ON "source_items" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_source_items_summary_artifact_id" ON "source_items" USING btree ("summary_artifact_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_source_items_active_canonical_uri" ON "source_items" USING btree ("space_id","canonical_uri") WHERE ((canonical_uri IS NOT NULL) AND (deleted_at IS NULL));--> statement-breakpoint
CREATE UNIQUE INDEX "uq_source_items_active_source_uri" ON "source_items" USING btree ("space_id","source_uri") WHERE ((source_uri IS NOT NULL) AND (deleted_at IS NULL));--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_item_decisions_connection_review" ON "source_post_processing_item_decisions" USING btree ("space_id","source_connection_id","review_status","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_item_decisions_item" ON "source_post_processing_item_decisions" USING btree ("space_id","source_item_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_item_decisions_project_review" ON "source_post_processing_item_decisions" USING btree ("space_id","project_id","review_status","relevance","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_item_decisions_rule_run" ON "source_post_processing_item_decisions" USING btree ("space_id","rule_id","run_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_source_post_processing_item_decisions_run_item" ON "source_post_processing_item_decisions" USING btree ("space_id","run_id","source_item_id");--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_rules_agent_id" ON "source_post_processing_rules" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_rules_project_id" ON "source_post_processing_rules" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_rules_source_status" ON "source_post_processing_rules" USING btree ("space_id","source_connection_id","status");--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_rules_trigger_status" ON "source_post_processing_rules" USING btree ("space_id","trigger_type","status");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_source_post_processing_rules_active_name" ON "source_post_processing_rules" USING btree ("space_id","source_connection_id","project_id","name") WHERE ((status)::text <> 'archived'::text);--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_runs_agent_run_id" ON "source_post_processing_runs" USING btree ("agent_run_id");--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_runs_rule_created" ON "source_post_processing_runs" USING btree ("space_id","rule_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_runs_source_created" ON "source_post_processing_runs" USING btree ("space_id","source_connection_id","created_at" DESC NULLS FIRST);--> statement-breakpoint
CREATE INDEX "ix_source_post_processing_runs_status" ON "source_post_processing_runs" USING btree ("space_id","status");--> statement-breakpoint
CREATE INDEX "ix_source_recipe_versions_connection" ON "source_recipe_versions" USING btree ("source_connection_id");--> statement-breakpoint
CREATE INDEX "ix_source_recipe_versions_space_id" ON "source_recipe_versions" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_source_snapshots_artifact_id" ON "source_snapshots" USING btree ("artifact_id");--> statement-breakpoint
CREATE INDEX "ix_source_snapshots_connection_id" ON "source_snapshots" USING btree ("connection_id");--> statement-breakpoint
CREATE INDEX "ix_source_snapshots_content_hash" ON "source_snapshots" USING btree ("content_hash");--> statement-breakpoint
CREATE INDEX "ix_source_snapshots_snapshot_type" ON "source_snapshots" USING btree ("snapshot_type");--> statement-breakpoint
CREATE INDEX "ix_source_snapshots_source_item_id" ON "source_snapshots" USING btree ("source_item_id");--> statement-breakpoint
CREATE INDEX "ix_source_snapshots_space_id" ON "source_snapshots" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_source_snapshots_space_item" ON "source_snapshots" USING btree ("space_id","source_item_id");--> statement-breakpoint
CREATE INDEX "ix_space_invitations_space_id" ON "space_invitations" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_space_invitations_status" ON "space_invitations" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_space_memberships_space_id" ON "space_memberships" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_space_memberships_user_id" ON "space_memberships" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_board_columns_board_id" ON "board_columns" USING btree ("board_id");--> statement-breakpoint
CREATE INDEX "ix_board_columns_space_id" ON "board_columns" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_boards_project_id" ON "boards" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_boards_space_id" ON "boards" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_boards_workspace_id" ON "boards" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_task_artifacts_artifact_id" ON "task_artifacts" USING btree ("artifact_id");--> statement-breakpoint
CREATE INDEX "ix_task_artifacts_run_id" ON "task_artifacts" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "ix_task_artifacts_space_id" ON "task_artifacts" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_task_artifacts_task_id" ON "task_artifacts" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "ix_task_dependencies_depends_on_task_id" ON "task_dependencies" USING btree ("depends_on_task_id");--> statement-breakpoint
CREATE INDEX "ix_task_dependencies_space_id" ON "task_dependencies" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_task_dependencies_task_id" ON "task_dependencies" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "ix_task_proposals_proposal_id" ON "task_proposals" USING btree ("proposal_id");--> statement-breakpoint
CREATE INDEX "ix_task_proposals_space_id" ON "task_proposals" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_task_proposals_task_id" ON "task_proposals" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "ix_tasks_board_id" ON "tasks" USING btree ("board_id");--> statement-breakpoint
CREATE INDEX "ix_tasks_column_id" ON "tasks" USING btree ("column_id");--> statement-breakpoint
CREATE INDEX "ix_tasks_parent_task_id" ON "tasks" USING btree ("parent_task_id");--> statement-breakpoint
CREATE INDEX "ix_tasks_project_id" ON "tasks" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_tasks_space_id" ON "tasks" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_tasks_workspace_id" ON "tasks" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_validation_recipes_enabled" ON "validation_recipes" USING btree ("enabled");--> statement-breakpoint
CREATE INDEX "ix_validation_recipes_space_id" ON "validation_recipes" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_validation_recipes_task_type" ON "validation_recipes" USING btree ("task_type");--> statement-breakpoint
CREATE INDEX "ix_validation_recipes_workspace_id" ON "validation_recipes" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_bindings_created_by_user_id" ON "project_source_bindings" USING btree ("created_by_user_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_bindings_project_id" ON "project_source_bindings" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_bindings_source_connection_id" ON "project_source_bindings" USING btree ("source_connection_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_bindings_space_id" ON "project_source_bindings" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_bindings_status" ON "project_source_bindings" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_project_source_item_links_binding_id" ON "project_source_item_links" USING btree ("project_source_binding_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_item_links_matched_at" ON "project_source_item_links" USING btree ("matched_at");--> statement-breakpoint
CREATE INDEX "ix_project_source_item_links_project_id" ON "project_source_item_links" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_item_links_source_connection_id" ON "project_source_item_links" USING btree ("source_connection_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_item_links_source_item_id" ON "project_source_item_links" USING btree ("source_item_id");--> statement-breakpoint
CREATE INDEX "ix_project_source_item_links_status" ON "project_source_item_links" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_project_workspaces_project_id" ON "project_workspaces" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "ix_project_workspaces_workspace_id" ON "project_workspaces" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_working_dirs_project_id" ON "working_dirs" USING btree ("project_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_working_dirs_project_uniq" ON "working_dirs" USING btree ("project_id") WHERE (project_id IS NOT NULL);--> statement-breakpoint
CREATE INDEX "ix_working_dirs_session_id" ON "working_dirs" USING btree ("session_id");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_working_dirs_session_uniq" ON "working_dirs" USING btree ("session_id") WHERE (session_id IS NOT NULL);--> statement-breakpoint
CREATE INDEX "ix_working_dirs_space_id" ON "working_dirs" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_working_dirs_status" ON "working_dirs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_workspace_profiles_space_id" ON "workspace_profiles" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_workspace_profiles_workspace_id" ON "workspace_profiles" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "ix_workspaces_slug" ON "workspaces" USING btree ("slug");--> statement-breakpoint
CREATE INDEX "ix_workspaces_space_id" ON "workspaces" USING btree ("space_id");--> statement-breakpoint
CREATE INDEX "ix_workspaces_status" ON "workspaces" USING btree ("status");