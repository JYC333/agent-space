import { describe, expect, it } from "vitest";
import type { Queryable, QueryResult } from "../src/modules/routeUtils/common";
import {
  PgRuntimeSkillProvider,
  renderRuntimeSkillCandidate,
} from "../src/modules/capabilities/runtimeSkillProvider";

class FakeQueryable implements Queryable {
  constructor(
    private readonly dbBindingRows: Record<string, unknown>[],
    private readonly enablementRows: Record<string, unknown>[],
  ) {}

  async query<Row = Record<string, unknown>>(sql: string): Promise<QueryResult<Row>> {
    const rows = sql.includes("JOIN capability_runtime_bindings")
      ? this.dbBindingRows
      : this.enablementRows;
    return { rows: rows as Row[], rowCount: rows.length };
  }
}

describe("PgRuntimeSkillProvider", () => {
  it("loads default runtime bindings for enabled built-in capabilities", async () => {
    const provider = new PgRuntimeSkillProvider(
      new FakeQueryable([], [
        {
          capability_enablement_id: "enable-1",
          capability_key: "research.source_collect",
          capability_version_id: null,
          enabled: true,
          config_json: { source_mode: "project_sources" },
        },
      ]),
    );

    const candidates = await provider.loadCandidatesForRun({
      space_id: "space-1",
      run_id: "run-1",
      adapter_type: "codex_cli",
      capability_id: "research.source_collect",
      agent_id: "agent-1",
      project_id: "project-1",
      instructed_by_user_id: "user-1",
    });

    expect(candidates).toHaveLength(1);
    expect(candidates[0]).toMatchObject({
      binding_id: "research.source_collect:codex_cli:render_skill",
      capability_id: "research.source_collect",
      capability_version_id: null,
      capability_enablement_id: "enable-1",
      capability: { source_kind: "builtin" },
      enablement_config_json: { source_mode: "project_sources" },
    });

    const rendered = renderRuntimeSkillCandidate(candidates[0]!);
    expect(rendered?.rendered.files.map((file) => file.path)).toContain(
      ".agent-space/generated-skills/codex/research-source-collect/SKILL.md",
    );
  });
});
