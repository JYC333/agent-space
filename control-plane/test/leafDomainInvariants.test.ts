import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { TS_OWNED_MODULES } from "../src/gateway/routeRegistry";

function source(path: string): string {
  return readFileSync(join(process.cwd(), path), "utf8");
}

const activityRepository = source("src/modules/activity/repository.ts");
const intakeRepository = source("src/modules/intake/repository.ts");
const knowledgeRepository = source("src/modules/knowledge/repository.ts");
const knowledgeApplier = source("src/modules/knowledge/proposalApplier.ts");
const tasksRepository = source("src/modules/tasks/repository.ts");
const tasksApplier = source("src/modules/tasks/proposalApplier.ts");
const routeRegistry = source("src/gateway/routeRegistry.ts");

const leafDomainSources = [
  activityRepository,
  intakeRepository,
  knowledgeRepository,
  knowledgeApplier,
  tasksRepository,
  tasksApplier,
].join("\n");

describe("Leaf domain ownership invariants", () => {
  it("registers activity, intake, knowledge, and tasks as TS-owned modules", () => {
    expect(TS_OWNED_MODULES.map((module) => module.name)).toEqual(
      expect.arrayContaining(["activity", "intake", "knowledge", "tasks"]),
    );
    expect(routeRegistry).toMatch(/activityModule/);
    expect(routeRegistry).toMatch(/intakeModule/);
    expect(routeRegistry).toMatch(/knowledgeModule/);
    expect(routeRegistry).toMatch(/tasksModule/);
  });

  it("keeps capture and intake as proposal-gated inputs, not direct memory writes", () => {
    expect(activityRepository).toMatch(/INSERT INTO activity_records/);
    expect(activityRepository).toMatch(/proposalType: "memory_create"/);
    expect(intakeRepository).toMatch(/"memory_create"/);
    expect(leafDomainSources).not.toMatch(/INSERT INTO memory_entries|UPDATE memory_entries|DELETE FROM memory_entries/);
  });

  it("keeps intake evidence candidate-only and carries provenance into proposals", () => {
    expect(intakeRepository).toMatch(/Intake evidence remains candidate-only/);
    expect(intakeRepository).toMatch(/source_type: "extracted_evidence"/);
    expect(intakeRepository).toMatch(/source_type: "intake_item"/);
    expect(intakeRepository).toMatch(/provenance_entries: sourceRefs/);
    expect(intakeRepository).toMatch(/source_refs: sourceRefs/);
  });

  it("applies knowledge proposals in TS without auto-promoting knowledge into memory", () => {
    expect(knowledgeApplier).toMatch(/registry\.register\("knowledge_create"/);
    expect(knowledgeApplier).toMatch(/registry\.register\("knowledge_update"/);
    expect(knowledgeApplier).toMatch(/registry\.register\("knowledge_relation_create"/);
    expect(knowledgeRepository).toMatch(/proposalType: "knowledge_create"/);
    expect(knowledgeRepository).toMatch(/proposalType: "knowledge_update"/);
    expect(`${knowledgeRepository}\n${knowledgeApplier}`).not.toMatch(/memory_create|INSERT INTO memory_entries/);
  });

  it("models task-board runs through task_runs and Run creation, not Jobs", () => {
    expect(tasksRepository).toMatch(/INSERT INTO task_runs/);
    expect(tasksRepository).toMatch(/createQueuedRun/);
    expect(tasksRepository).toMatch(/INSERT INTO task_evaluations/);
    expect(tasksRepository).not.toMatch(/INSERT INTO jobs|FROM jobs|claimNextAgentRun|RunJobRepository/);
  });

  it("registers follow_up_task applier in TS and creates a task row without direct memory writes", () => {
    expect(tasksApplier).toMatch(/registry\.register\("follow_up_task"/);
    expect(tasksApplier).toMatch(/INSERT INTO tasks/);
    expect(tasksApplier).not.toMatch(/INSERT INTO memory_entries|UPDATE memory_entries/);
  });

  it("marks reviewed activities as consolidation_status=skipped so the consolidation job ignores them", () => {
    expect(activityRepository).toMatch(/consolidation_status.*'skipped'/);
  });
});
