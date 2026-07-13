# 任务执行控制链路审计（Execution Control Path Audit）

- 日期：2026-07-13（审计执行于 2026-07-12）
- 性质：`.agent/reports/` 临时评审报告，非架构真相源。修复项落实后应更新
  `EXECUTION_MODEL.md` / `PLAN_GRAPH_EXECUTION.md` / `ROUTING.md`，然后删除本文件。
- 范围：仅任务执行控制链路（intake → 计划/分解 → 路由 → 执行 → 验证/重试 → 完成）。
- 证据标注：【确证】= 直接读到的代码行为；【推断】= 由结构推出、未逐行验证。

## 0. 总裁决

**mostly aligned with local issues（大体符合控制原则，存在局部问题）。**

"系统拥有规划/路由/验证/监督，运行时只执行有界任务"的原则是真实实现：
请求体拒收、路由持久化审计、验证 fail-closed、重试单一归属、运行时自主性逐项
声明并真实执行。结构性缺口有一个半：

1. **计划图缺节点间数据流**（调度 DAG 而非数据流 DAG）—— 最高优先修复项。
2. **codex 信任分级未为 "unknown 可控性" 付出代价** + 路由合规门按适配器名点名。

## 1. 控制流重建（确证）

五条入口，汇聚到同一执行内核：

| 入口 | 路径 | 产物 |
|---|---|---|
| 聊天回合 | agents 模块 → `createQueuedRun` → 同步 `POST /internal/runs/execute`（`runs/routes.ts:183-205`） | 单 Run |
| 手动执行 | `POST /api/v1/runs/:runId/execute` —— 请求体完全被忽略（`runs/routes.ts:165-174`） | 执行已有 Run |
| 任务 | `tasks/repository` 创建 task 关联 Run | 单 Run |
| 自动化 | agent 目标→`automations/service.ts:452` 直接建 Run；workflow 目标→`plans.createPlan`+`executePlan`（:509/:537） | Run 或整个 Plan |
| 计划 | `POST /api/v1/plans`（手写/资产/LLM planner）→ execute | Run 图 |

主链路：

```
Plan 创建: planner.ts(LLM 仅编译定义，永不直接执行)
  → graph.ts: 深度≤3 / 节点≤30 / 环检测 / 原子性评估
  → decidePlanApproval: 全 low-risk+预算声明 ⇒ auto_approved，否则 plan_review 提案
→ executePlan(plans/repository.ts:271): 根协调 Run（创建即停 waiting_for_dependency）
  → scheduleReadyNodes(:683): 依赖满足节点 → 子 Run + contract_snapshot → jobs 入队
→ jobs worker(workerRuntime.ts) 领取 agent_run
→ RunOrchestrationService.executeRun(orchestrationService.ts:300):
  执行锁 → routeRun(C2 过滤/打分/持久化 route_decisions/盖章 run 行)
  → checkRunDispatchContract → markRunning
  → enforceRuntimePolicy(策略门 + critical 风险强升 one_shot_docker)
  → prepareRuntimeContext(worktree/ephemeral 沙箱 + context 文件)
  → invokeAdapter(合同 timeout 取 min) → spec.executor_family 分发
     managed_api | local_cli(claude_code/codex/opencode)
  → 物化(artifact/patch/proposal) → VerificationEngine(fail-closed)
  → markRunTerminal → finalizeRun
→ PostRunFinalizationService.finalize(finalizationService.ts:108):
  RunEvaluation → RunFinalization(按 attempt 幂等) → 进化信号(best-effort)
  → Supervisor(supervisor.ts:57): 可重试码∧预算内∧attempt<cap ⇒ 重试/换路，否则 human_review
  → reconcilePlan(best-effort): 推进下批节点 / integration 验证后结束计划
```

## 2. 决策归属矩阵

| 决策 | 归属 | 状态 |
|---|---|---|
| 是否分解 | 仅用户（选 /plans 或普通 run） | ⚠️ 无系统归属（见 §8 D4） |
| 如何分解 | 用户手写或 PlanPlannerService（LLM 输出强制走审批） | 清晰 |
| 分解何时停止 | graph.ts 硬限制 + 原子性评估（不达标转人审而非拒绝） | 清晰 |
| 选模型 | routeRun 选 runtime profile，模型随 profile（`model_override_json.model`） | 清晰（见 §8 D5） |
| 选运行时 | routeRun 硬过滤+打分；显式 profile 硬 pin | 清晰 |
| 建子任务 | Plan 调度器 + AgentRunGroup `agent.delegate`（双通道） | ⚠️ 双归属（已冻结但共存） |
| 何时算完成 | VerificationEngine 权威；plan 节点 done 需 `outcome_status='passed'`（reconcile SQL :581） | 清晰 |
| 是否重试 | Supervisor 唯一归属；重试作业 `max_attempts:1` 防 job 层二次重试（supervisor.ts:168） | 清晰 |
| 失败后续 | 同路重试→回退链→human_review；无自动 replan；revise 手动且协调器活跃时 409 | 清晰（保守） |
| 谁可取消 | 用户 PATCH /stop → 两阶段 SIGTERM/SIGKILL + 退出确认 | 清晰 |
| 上下文组装 | contextPreparer 每 run 独立渲染 | ⚠️ 节点间无数据传递（见 §8 D1） |

## 3. 隐藏/重复编排发现

1. 【确证】**第二条子运行通道**：`managedAgentDelegationTools.ts`（846 行），
   managed-API 运行在 AgentRunGroup 内经 `agent.delegate` 生成子 run；
   编排服务挂 delegationProjector 钩子。与 Plan 图并行，计划已冻结但代码是活的。
2. 【确证】**路由合规门按名点名**：`routing/router.ts:96-101` 只对 `"opencode"`
   要求非低风险须合规通过；claude_code/codex 仅在 `conformance_status==="failed"`
   时才拦。合规门是点名规则而非通用规则。
3. 【确证】**超时双层执行**：编排层 `withTimeout` + 同值写入
   `adapter_config.timeout`（orchestrationService.ts:1247-1276）。取 min、方向
   一致，可接受，记录在案。
4. 【确证】**两个执行触发器**：聊天走同步 internal execute，其余走 job 队列；
   同一编排服务靠执行锁互斥。可接受。
5. 【推断】自动化模块硬编码维护 fire 是第三条不走 Plan 图的编排小径（计划文档
   承认并冻结）。

## 4. 运行时自主性分级

| 运行时 | 内部子代理 | 关键声明（specs.ts） | 分级 |
|---|---|---|---|
| model_api / ts_agent_host | 无 | trust high；delegation 仅 group 内 policy 门 | 受控执行器（组内为有界代理） |
| claude_code | 有，可禁（渲染 `.claude/settings.json` deny Task，:273-277） | trust medium；observability opaque | 部分不透明代理 |
| codex_cli | 有，**禁用机制 unknown**（:336）、可控性 unknown | **trust medium** | 部分不透明代理，趋近不透明 —— ⚠️ 违反 N6 |
| opencode | 可禁（锁定 agent 配置 task:deny / webfetch deny，:406-414） | trust low；结构化事件流；合规前禁非低风险 | 有界代理 |

共同点（确证）：都不能改目标、不能系统级建子任务、不能自主重试、
持久变更只经 worktree diff → proposal。

## 5. 状态模型发现

概念划分总体清晰（Plan/PlanVersion、Task=节点、Run 逻辑、RunAttempt 物理、
RunStep/RunEvent 证据、RunEvaluation/RunFinalization 按 attempt 幂等、
VerificationResult、RouteDecision、Job 纯传输）。三处问题：

1. 【确证】**期望态与观测态混写**：`routeRun` 覆写
   `runs.runtime_profile_id / adapter_type / model_provider_id`
   （routing/repository.ts:127-147）；用户原始意图只剩
   `runtime_profile_selection_source` + route_decisions 反推。
2. 【确证】**根协调 Run 是伪 Run**：executePlan 创建后立即置
   `waiting_for_dependency`（plans/repository.ts:353-356），永不执行适配器；
   Run 语义被 coordinator 语义污染，会进入 run 列表/统计。
3. 【确证】**attempt 行懒回填**：run_attempts 仅在 Supervisor 介入时
   `ensureAttempt` 补建（supervisor.ts:204）；成功 run 可能永远无 attempt 行。
4. 【确证】`task.status` 同时承载看板语义与计划执行语义（waiting_for_review/
   superseded/blocked），一张状态机两种读法。

## 6. 失败语义追踪表（确证，除注明外）

| 场景 | 行为 |
|---|---|
| 模型调用失败 | 失败信封 → terminal failed → Supervisor（provider_network_error/rate_limit 可重试）→ 同路/回退链重试（默认 2 attempt 封顶），预算超限 → budget_exceeded 挂人审 |
| 运行时进程崩溃 | exit≠0 → failed；无输出 → cli_stall_timeout（可重试码） |
| worker 崩溃/孤儿 | 启动 `recoverStaleRuns` + 孤儿 finalize（workerRuntime.ts:88-106）；orphaned 可重试 |
| 用户取消 | 两阶段：cancelling → SIGTERM → 等待 → SIGKILL → 仅确认退出后写 cancelled；未确认停留 cancelling（orchestrationService.ts:820-847）；迟到结果不覆盖取消（:602-637） |
| 超时 | 合同 max_duration_seconds 与请求 timeout 取 min，双层执行 |
| 子节点失败 | 重试用尽 → 整个 Plan failed（plans/repository.ts:607-611）；无部分继续、无节点级自动 replan；恢复=手动 revise 新 PlanVersion（done 节点按内容哈希 carry-over :451-455） |
| 输出不完整 | 声明检查但证据缺失 → 验证 fail-closed → failed |
| 上下文超限 | 【推断：缺失】未见显式处理路径 |
| Plan 推进失败 | reconcilePlanBestEffort 吞错（finalizationService.ts:227-240）⇒ 计划可能静默停摆，唯一恢复是手动 POST reconcile；【推断】无周期性叫醒守护 |

## 7. 最小目标边界（确认并守住，多为现状）

- Task：意图+验收合同+看板状态；不拥有执行细节/路由/attempt。
- Plan/PlanVersion：目标+不可变图+审批+预算聚合；不拥有运行时状态。
- 节点：即 Task（维持 N3）；**待补：声明输入来源（依赖哪些节点输出）**。
- Run/Attempt：Run=逻辑执行+合同快照；Attempt=物理进程；coordinator 应显式
  标记并从统计排除。
- Orchestrator：生命周期/锁/沙箱/策略/证据；不拥有路由与完成判定内容。
- Model Router：过滤/打分/回退链/审计；不覆写 run 行"请求"字段。
- Runtime 收到：渲染好的 prompt+context+锁定配置+沙箱 cwd+超时；
  必须交回：exit code、stdout/事件流、工作区 diff。
- 分解停止点：叶子=单一目标+独立可验证+声明范围+单运行时预算（graph.ts 已编码）。

## 8. 五个最高杠杆决策（执行清单，按优先级）

- [ ] **D1 节点间数据流合同（最高优先）**
  - 歧义：下游节点如何取得上游输出。当前【确证】`scheduleReadyNodes`
    （plans/repository.ts:784-787）给子 run 的指令只有
    task.title+description+workflowInputSuffix，上游输出不进入下游上下文；
    文件通道也不通（每子 run 独立 worktree，上游 patch 需人工批准后才落回
    workspace）。
  - 选项：a) 依赖节点 output/artifact 摘要注入子 run 指令或 context；
    b) plan 级共享工作区；c) 显式声明"节点必须自包含"。
  - 当前隐含选择：c（未声明）。**建议：a**。
  - 最小迁移：调度时把依赖 run 的 output_text 截断+标注来源拼进 instruction；
    workflow_definition 元数据允许节点声明 `inputs_from`。不建通用数据总线。
  - 拖延后果：第一个真实多节点计划即失败，且难以诊断。
- [ ] **D2 codex 信任降级 + 合规门通用化**
  - 歧义：unknown 子代理控制为何享受 medium 信任；合规硬过滤为何点名 opencode。
  - 路径：`runtimeAdapters/specs.ts:336,344`、`routing/router.ts:92-101`。
  - 建议：codex `trust_level: "low"` 直至合规证据存在；router 特例改为通用规则
    `subagent_disable_mechanism === "unknown" ⇒ 非低风险要求 conformance passed`。
  - 最小迁移：两个字面量 + 一个条件。
  - 拖延后果：medium 风险任务可路由到不可控子代理运行时，N6 名存实亡。
- [ ] **D3 计划停摆叫醒机制**
  - 歧义：best-effort reconcile 静默失败后谁推进计划。
  - 路径：`finalizationService.ts:227-240`、`jobs/workerRuntime.ts`（启动恢复段）。
  - 建议：worker 启动恢复中加入"active 且无活跃子 run 的 plan"扫描 → reconcile。
  - 拖延后果：无人值守 automation→plan 链路第一次静默失败即数据静止事故。
- [ ] **D4 分解触发归属声明（文档级）**
  - 歧义：系统是否应评估任务复杂度并建议分解。
  - 建议：明确声明"不自动分解，由用户显式发起"写入
    PLAN_GRAPH_EXECUTION.md；待真实使用出现"该拆没拆"失败样本再考虑评估器。
- [ ] **D5 请求态与路由态分离**
  - 歧义：routeRun 覆写 runs 行 profile/adapter/provider 字段。
  - 路径：`routing/repository.ts:127-147`。
  - 建议：加 `requested_runtime_profile_id`（或保留创建值、执行读
    route_decisions），成本一列+读路径调整。
  - 拖延后果：消费 runs 行的功能越多，"路由结果"被误当"用户意图"的位置越多。

## 9. 聚焦迁移序列（仅此链路，增量执行）

1. [ ] （一行级）router 合规硬过滤改为按 spec 声明驱动；codex trust 降 low。（=D2）
2. [ ] （小）worker 启动恢复加入 plan 停摆扫描 → reconcile。（=D3）
3. [ ] （中）节点间数据流最小版：依赖 run output_text 注入 + `inputs_from` 声明。（=D1）
4. [ ] （小）runs 行加 `requested_runtime_profile_id`，routeRun 停止覆写混合字段。（=D5）
5. [ ] （文档级）EXECUTION_MODEL / PLAN_GRAPH_EXECUTION 写明两条裁决：
   "系统不自动分解，由用户显式发起"；"AgentRunGroup 委托与 Plan 图是两条
   冻结共存的子运行通道，新功能只允许走 Plan 图"。（=D4 + §3.1）

明确不做：不合并两条子运行通道、不加 ML/复杂度评估器、不建通用节点数据总线、
不动 jobs 层、不重构 task 状态机。

## 10. 值得保护的实现（禁止回退）

1. HTTP execute 拒收一切执行参数（runs/routes.ts:165-174）。
2. 路由决策持久化审计 + 显式 profile 硬 pin。
3. VerificationEngine fail-closed 作为完成权威。
4. Supervisor 单一重试归属 + 重试 job `max_attempts:1`。
5. 两阶段取消与退出确认；迟到适配器结果不覆盖取消。
6. LLM Planner "只产定义、必过审批" 的笼子（plans/planner.ts 注释与实现一致）。
