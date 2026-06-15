/**
 * Policy enforcement module.
 *
 * TS port of the Python `policy` enforcement context: the canonical action
 * registry, hard-invariant guard, rule engine, decision orchestration, and the
 * durable audit writer. Exposes service-authenticated internal enforcement
 * ports when `policyAuthority === "ts"`; otherwise inert (Python `PolicyGateway`
 * stays the local authority).
 */

import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const policyModule: ControlPlaneModule = {
  name: "policy",
  registerRoutes,
};

export { enforce, enforceProposalApply } from "./service";
export { computeDecision, checkProposalApplyPolicy } from "./gateway";
export { loadActionRegistry } from "./actionRegistry";
