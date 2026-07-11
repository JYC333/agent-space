import type { Queryable, SpaceUserIdentity } from "../routeUtils/common";
import { HttpError, optionalString, requiredString } from "../routeUtils/common";
import { ProjectSourceBindingRepository } from "./projectSourceBindingRepository";

/**
 * Project-owned application boundary for source consumption CRUD (binding
 * lifecycle, health). Proposal-first flows (propose-bind, source setup,
 * propose-backfill) live in `ProjectSourceProposalService`.
 */
export class ProjectSourceBindingService {
  private readonly repository: ProjectSourceBindingRepository;

  constructor(private readonly db: Queryable) {
    this.repository = new ProjectSourceBindingRepository(db);
  }

  listBindings(identity: SpaceUserIdentity, filters: { projectId: string; sourceConnectionId: string | null }) {
    return this.repository.listProjectSourceBindings(identity, filters);
  }

  createBinding(identity: SpaceUserIdentity, body: Record<string, unknown>) {
    requiredString(body.project_id, "project_id");
    requiredString(body.source_connection_id, "source_connection_id");
    validateDeliveryScope(body.delivery_scope);
    return this.repository.createProjectSourceBinding(identity, body);
  }

  async updateBinding(identity: SpaceUserIdentity, bindingId: string, body: Record<string, unknown>, expectedProjectId?: string) {
    requiredString(bindingId, "binding_id");
    validateBindingStatus(body.status);
    validateDeliveryScope(body.delivery_scope);
    await this.assertBindingProject(identity.spaceId, bindingId, expectedProjectId);
    return this.repository.updateProjectSourceBinding(identity, bindingId, body);
  }

  async deleteBinding(identity: SpaceUserIdentity, bindingId: string, expectedProjectId?: string) {
    await this.assertBindingProject(identity.spaceId, bindingId, expectedProjectId);
    return this.repository.deleteProjectSourceBinding(identity, bindingId);
  }

  async backfillBinding(identity: SpaceUserIdentity, bindingId: string, expectedProjectId?: string) {
    await this.assertBindingProject(identity.spaceId, bindingId, expectedProjectId);
    return this.repository.backfillProjectSourceBinding(identity, bindingId);
  }

  health(identity: SpaceUserIdentity, projectId: string) {
    return this.repository.projectSourceHealth(identity, projectId);
  }

  private async assertBindingProject(spaceId: string, bindingId: string, expectedProjectId?: string): Promise<void> {
    if (!expectedProjectId) return;
    const result = await this.db.query(`SELECT 1 FROM project_source_bindings WHERE space_id = $1 AND project_id = $2 AND id = $3`, [spaceId, expectedProjectId, bindingId]);
    if (!result.rows[0]) throw new HttpError(404, "Project source binding not found");
  }
}

function validateBindingStatus(value: unknown): void {
  const status = optionalString(value);
  if (status && !["active", "paused", "archived"].includes(status)) {
    throw new HttpError(422, "invalid project source binding status");
  }
}

function validateDeliveryScope(value: unknown): void {
  const scope = optionalString(value);
  if (scope && !["project_members", "source_subscribers"].includes(scope)) {
    throw new HttpError(422, "delivery_scope must be project_members or source_subscribers");
  }
}
