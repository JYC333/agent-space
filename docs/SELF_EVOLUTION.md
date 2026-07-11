# Self-Evolution Safety Boundary

## Current Status

Automatic self-evolution deployment is not implemented. `ENABLE_SYSTEM_EVOLUTION` can
register a manually provisioned `system_core` workspace and enable dry-run evolution
planning, but it does not grant deployment authority. If the configured workspace is not
already a Git repository, registration fails closed with an operator-facing warning.

The active code-change path is:

1. An agent works in a managed worktree/sandbox.
2. Changed files are collected into a `code_patch` proposal.
3. A human reviews and accepts the proposal.
4. The proposal applier writes the approved patch through `workspace.write_patch`, with a
   pre-apply snapshot for rollback.
5. Testing, commit, and deployment remain explicit operator actions.

There is no automatic merge or production-deploy loop.

## Privileged Deployer Boundary

The deployer sidecar mounts docker.sock and the canonical repository read-write. Together
these provide host-equivalent authority. Its Unix socket is
`/tmp/agent-space-deployer.sock` inside the deployer container and is not shared with the
server, agent runtimes, sandboxes, or the instance data root.

The deployer accepts exactly:

- `rebuild_agent_space`
- `restart_agent_space`
- `health_check`

Self-evolution helpers such as worktree creation, test deployment, patch merging, and
production deployment are not registered deployer jobs. Their script files are operator
tools only and must not be made reachable from product code.

The authenticated product deployment routes remain fail-closed (`POST` and detail routes
return 501). A future product deployment trigger must verify an authorized human-approved
proposal in the server authority, persist durable job/audit state, and only then submit a
core allowlisted job.

## Required Invariants

- Agent and server containers never mount docker.sock.
- Evolution, code-patch, capability, agent, automation, job, and scheduler paths cannot
  reach deployer input or invoke deployer scripts.
- The public workspace API cannot create `system_core` workspaces.
- `ENABLE_SYSTEM_EVOLUTION` remains disabled by default in every mode.
- High/critical execution never downgrades to an unimplemented sandbox level.
- The instance is not directly exposed to the public internet. TLS termination, rate
  limiting, and general CSRF-token hardening are prerequisites for reconsidering that rule.

## Operator Procedure

1. Keep `ENABLE_SYSTEM_EVOLUTION=false` for normal dogfooding.
2. If dry-run evolution work is intentionally enabled, manually provision the configured
   system-core Git workspace first.
3. Review generated diffs and proposals in the product.
4. Apply only an explicitly accepted proposal.
5. Run the repository test/CI gates.
6. Commit and deploy manually using the canonical ops commands.

## Stop Conditions

Stop immediately if any product or agent path can reach the deployer socket, if the deployer
accepts a non-core job type, if a code change bypasses proposal acceptance, or if deployment
occurs without a separate operator action.
