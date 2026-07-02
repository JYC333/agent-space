import { describe, expect, it } from "vitest";
import { PgAgentRepository } from "../src/modules/agents/repository";

function assistantRecord() {
  return {
    id: "assistant-1",
    space_id: "space-1",
    owner_user_id: null,
    name: "Space Assistant",
    description: null,
    visibility: "space_shared",
    role_instruction: null,
    status: "active",
    agent_kind: "system_assistant",
    current_version_id: "version-1",
    model_provider_id: null,
    model_name: null,
    provider_name: null,
    provider_type: null,
    system_prompt: "You are the space assistant.",
    runtime_adapter_type: "model_api",
    runtime_policy_json: { default_adapter_type: "model_api" },
    created_at: "2026-06-26T00:00:00.000Z",
    updated_at: "2026-06-26T00:00:00.000Z",
  };
}

function settingsRecord(id: string, settingsJson: Record<string, unknown>) {
  return {
    id,
    scope_type: "space",
    scope_id: "space-1",
    settings_key: "agent.default_assistant.settings",
    settings_json: settingsJson,
    updated_by_user_id: null,
    created_at: "2026-06-26T00:00:00.000Z",
    updated_at: "2026-06-26T00:01:00.000Z",
  };
}

class FakeAgentSettingsDb {
  calls: string[] = [];
  settingsJson: Record<string, unknown> | null = null;
  legacyTableName = ["space", "assistant", "settings"].join("_");

  async query<Row = Record<string, unknown>>(
    sql: string,
    params: readonly unknown[] = [],
  ): Promise<{ rows: Row[]; rowCount: number | null }> {
    const norm = sql.replace(/\s+/g, " ").trim();
    this.calls.push(norm);
    if (norm.includes(this.legacyTableName)) {
      throw new Error("assistant settings must use scoped settings");
    }
    if (norm.includes("FROM settings")) {
      return {
        rows: this.settingsJson ? [settingsRecord("settings-1", this.settingsJson) as Row] : [],
        rowCount: this.settingsJson ? 1 : 0,
      };
    }
    if (norm.includes("FROM agents a")) {
      return { rows: [assistantRecord() as Row], rowCount: 1 };
    }
    if (norm.startsWith("INSERT INTO settings")) {
      this.settingsJson = JSON.parse(String(params[4] ?? "{}")) as Record<string, unknown>;
      return norm.includes("RETURNING")
        ? { rows: [settingsRecord(String(params[0]), this.settingsJson) as Row], rowCount: 1 }
        : { rows: [] as Row[], rowCount: 0 };
    }
    return { rows: [], rowCount: 0 };
  }
}

describe("assistant settings repository", () => {
  it("stores assistant preferences in the scoped settings table", async () => {
    const db = new FakeAgentSettingsDb();
    const repo = new PgAgentRepository(db as never);

    const created = await repo.getAssistantSettings("space-1");
    expect(created.assistant_agent_id).toBe("assistant-1");
    expect(db.settingsJson).toMatchObject({
      assistant_agent_id: "assistant-1",
      default_context_toggles_json: {},
      model_preferences_json: {},
    });

    const updated = await repo.updateAssistantSettings("space-1", {
      response_style: "direct",
      verbosity: "concise",
      default_context_toggles_json: { memory: true },
      proposal_style: "balanced",
      model_preferences_json: { model: "system-default" },
    });

    expect(updated).toMatchObject({
      assistant_agent_id: "assistant-1",
      response_style: "direct",
      verbosity: "concise",
      proposal_style: "balanced",
    });
    expect(updated.default_context_toggles_json).toEqual({ memory: true });
    expect(updated.model_preferences_json).toEqual({ model: "system-default" });
    expect(db.calls.some((sql) => sql.includes(db.legacyTableName))).toBe(false);
  });

  it("keeps assistant preference enum validation after moving out of table constraints", async () => {
    const db = new FakeAgentSettingsDb();
    const repo = new PgAgentRepository(db as never);

    await repo.getAssistantSettings("space-1");
    await expect(repo.updateAssistantSettings("space-1", {
      response_style: "casual",
    })).rejects.toMatchObject({ statusCode: 422 });
  });
});
