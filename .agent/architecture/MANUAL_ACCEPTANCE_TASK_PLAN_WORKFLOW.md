# Manual acceptance: Task, Agent Plan, Workflow Automation

Use a real authenticated user in one operational Space and an active Agent.
The shared PostgreSQL test fixture is the only database test infrastructure;
the manual steps below use the product UI and server APIs behind it.

## Task → Agent Plan

1. Open `/spaces/<spaceId>/tasks` and create a source Task using the compact
   natural-language form. Confirm it does not ask for a parent Task ID or raw
   JSON; execution limits use the displayed defaults unless changed later in
   Task Detail advanced settings.
2. Open the Task Detail page. Confirm there is no Plan immediately after Task
   creation. Click **Ask Agent to plan**.
3. In the Task Detail Runs tab, confirm a `planning` Run is queued and linked
   with the `planning` role. Open the Run and confirm its contract contains the
   source Task context and `task.plan.propose` capability.
4. After the Agent completes the planning Run, refresh Task Detail. The Agent
   Plan panel should show the Plan and current Version. A non-low-risk plan
   shows a **Review proposal** link.
5. Open the proposal from Task Detail or `/evolution/inbox`, approve it, then
   return to Plan Detail. The Version should be `approved`, nodes should be
   unlocked, and **Execute** should be available.
6. Execute the Plan. Confirm Plan Detail shows a root Run, Plan Nodes, and
   child node Run links. A node cannot become done solely from an adapter exit;
   it requires a passed evaluation.
7. Use **Reconcile** only as an owner/admin recovery action. Confirm the root
   Run and Plan finish after all node evaluations/checkpoints pass.
8. Click **Ask Agent to revise** on Task Detail. This queues another planning
   Run; it does not expose a raw Plan definition editor or direct Version
   mutation. The resulting Agent proposal creates the next Version.

## Fixed Workflow Automation

1. Open `/spaces/<spaceId>/automations` and choose **New automation** →
   **Workflow**.
2. Select a Workflow asset and an approved Version. Choose `pin` for a
   reproducible execution; scheduled Workflow Automations reject `follow`.
   Provide the input JSON object and save.
3. Click **Run now**. Confirm the result reports a `workflow_execution_id` and
   root Run. The `/plans` page must not gain a Plan and no `plan_review` is
   created.
4. On the Automation card, inspect **Workflow executions**. It should show
   the resolved Version, node progress, checkpoint/waiting state, and root Run
   link. Open the root or child Run for execution evidence.
5. For a Workflow with an approval checkpoint, approve the
   `workflow_execution_checkpoint` Proposal from the normal proposal or
   Evolution Inbox surface. Refresh the Automation card and confirm the
   Workflow Execution advances independently of Agent Plans.

## Negative checks

- There is no **New plan**, raw Definition, LLM planner, or **Revise** control
  on `/plans` or Plan Detail.
- A normal Task does not create a Plan unless **Ask Agent to plan** is clicked.
- A Workflow Automation fire never creates `plans`, `plan_versions`, or a
  `plan_review` Proposal.
- Plan Nodes do not appear as Task rows and are visible only inside Plan Detail.
- Cross-Space Task, Plan, and Workflow Execution links return the normal
  not-found/access-denied surface.
