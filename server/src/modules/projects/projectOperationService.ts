import type { Queryable } from "../routeUtils/common";
import { ProjectOperationRepository } from "./projectOperationRepository";

/** Application boundary; the repository owns SQL and projection persistence. */
export class ProjectOperationService extends ProjectOperationRepository {
  constructor(db: Queryable) { super(db); }
}
