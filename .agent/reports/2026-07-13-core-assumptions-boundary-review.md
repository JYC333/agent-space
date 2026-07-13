# 核心假设与系统边界评审（Hostile Principal Architect Review）

- 日期：2026-07-13（评审执行于 2026-07-12）
- 性质：`.agent/reports/` 临时评审报告，非架构真相源。落实后应将持久结论合并进
  `.agent/architecture/` 或 ADR，然后删除本文件。
- 范围：产品命题、核心假设、系统边界、最小核心、停建/保护清单。
  不覆盖执行链路细节（见同日另一份报告
  `2026-07-13-execution-control-path-audit.md`）。

## 0. 评审背景事实（全部确证）

- 全仓库 81 个 commit；约 160k 行 server TS + 70k 行 web TS；59 个后端模块；
  290 个测试文件；40+ 个前端模块。
- `server/migrations/` 只有 `0001_baseline.sql` ⇒ 无生产数据、无真实使用压力。
- ADR 0010（2026-07-11）定义 30 天 dogfooding 验证门槛；次日（2026-07-12）
  orchestration+self-evolution 计划 Phase 0–D4 全部标记完成。验证周期一天未跑。
- 文档与代码的三处分歧：
  1. `current-focus.md` 将"自进化在评估门与部署任务持久化之前"列为非目标，
     部署任务持久化仍是 501，但 D1–D4 进化层已全部落地。
  2. `NON_GOALS_AND_DISABLED_SURFACES.md` 称 Automation/Trigger engine
     "Not implemented"，实际 `server/src/modules/automations/` 已实现且 B3 完成。
  3. ADR 0010 称"平台扩张不能替代产品验证"，实际验证未开始、平台已扩张完一整个计划。

## 1. 重构的产品命题

- 文档定位：面向个人/家庭/小团队的服务器权威 Agent Workbench。
- 代码实态：自托管通用 agent 编排与治理平台（Planner/Plan 图/RunAttempt/
  Supervisor/Router/Verification/Conformance/进化层/插件宿主）+ 半个 PKM
  （Memory/Knowledge/Library/Cards/Relations/Graph）。
- 实际用户：仓库所有者 + 至多一位家庭成员（两用户成员制，无 SaaS，B44A 禁公网）。
- 核心价值主张：治理 —— proposal 门控持久写、出处快照、可替换运行时适配器。

## 2. 核心假设清单与红队裁决

| # | 假设 | 证据 | 裁决 | 裁决要点 |
|---|---|---|---|---|
| A1 | 复杂任务由主系统递归分解 | 计划 Part III、N1/N3/N7、`server/src/modules/plans/` | **修订** | 图基座与手写计划保留；LLM Planner 与 atomicity evaluator 冻结在提案态，直到 dogfooding 出现"手写计划不够用"的真实事件 |
| A2 | 运行时/CLI 只执行有界叶子任务 | 计划验证 7、C1/C3、B13 | **约束保留** | 定位为风险分级策略而非产品身份；C3 合规第二波不做（五项 MVP 已够）；承认在与 CLI 长程能力进化对赌 |
| A3 | 模型路由集中控制 | C2、`modules/routing/`、ROUTING.md | **约束保留** | 保留审计记录与凭据/风险硬过滤；冻结评分复杂度；禁止 ML 路由；Router 定位为内部设施非产品特性 |
| A4 | Prompt/Capability/Workflow 等六层一等概念 | ADR 0009、B52/B52A、evolvable_assets | **修订** | 对外收敛为两个概念（技能/提示词、工作流），其余降为内部实现细节；冻结 Open Skill 导入。B52A 需要立法禁混淆本身即分类法超载的证据 |
| A5 | Project/Source/Knowledge/Memory/Relation 同核 | 59 个 server 模块并列 | **拆分** | Memory/Source/Project 留核心；Relation/Cards/Graph/Library **延后**（`planned:true` 存根证明连作者都未使用；每个闲置域都在收 schema/权限/测试税） |
| A6 | 工作流个性化且系统托管 | B1/B4、workflow_definition.v1 | **修订** | 保留定义存储+手动执行；版本晋升与进化挂钩冻结。真实需求首先是"存下来、下周再跑"，不是版本治理官僚流程 |
| A7 | Agent 进化发生在平台内部 | D1–D4、EVOLUTION_SIGNAL_SYSTEM.md | **延后** | 燃料（使用数据）为零：信号发射器对空流发射、评估用例为空、inbox 无自然信号。D1 信号作为纯遥测保留；D2–D4 停止投入 |
| A8 | 外部工具是适配器而非主系统 | B38/B39/B40、ADR 0008 | **保留** | 全仓库证据最充分的假设；唯一警告是运行时数量到三个已达收益递减点 |
| A9 | 通用平台与引导型个人 OS 共享一核 | 40+ 前端模块混排导航 | **修订** | 不拆库；UI 层切"日常面/操作员面"两套壳，操作员面默认对非 owner 隐藏 |
| A10 | 可扩展性先于产品稳定 | ADR 0006/0009、PluginHost、B34/B35/B51 | **延后** | 全套插件机制服务于唯一自建 diary 插件；冻结即可，已建部分不拆；Level 3 远程分发不做 |

## 3. 系统边界裁决表

| 能力 | 归类 | 错放代价 / 备注 |
|---|---|---|
| Project | 核心域 | 失去工作容器锚点 |
| Source | 核心域（收窄） | capture→evidence→proposal 出处基座；防 connector 生态扩张 |
| Relation | 可选扩展 | 留核心持续拖累 schema 与权限矩阵；当前无使用 |
| Memory | 核心域 | 差异化本体；外置=放弃产品命题 |
| Knowledge | 核心域（约束） | 保留人读层；grant/oversight 仪式已超前于两用户现实 |
| Prompt | 内部平台设施 | 版本化是内部机制；prompts 前端模块暴露层级错误，应下沉 |
| Capability | 内部平台设施 | 作为用户一等概念持续制造 B52A 式立法负担 |
| Workflow | 核心域（存储+手动执行） | 错放为进化资产会把"再跑一次"埋进晋升流程 |
| Agent | 核心域 | 无争议 |
| Task | 核心域 | N3（task=计划节点）已正确处理 |
| Runtime | 内部平台设施 | 暴露为产品概念会吓退非技术用户（B23） |
| Model Router | 内部平台设施（最小化） | 防评分/ML 军备竞赛 |
| Plugin | 延后 | 继续投入=为零外部开发者维护 API 契约 |
| Reader（Library） | 可选扩展 | 与 agent 循环无已证联动 |
| 外部 CLI | 外部集成（现状正确） | 风险仅是数量膨胀 |
| 自动进化 | 延后（信号遥测除外；自动应用永久排除） | 在零数据上固化错误形状的反馈回路，安全面最大 |

## 4. 最小连贯核心（现状大部分已建成，问题是从未被使用）

- 目标用户：所有者 + 一位家庭成员；两个 space（个人+家庭）。
- 触发：手动捕获（Activity）、聊天会话、定时 automation —— 仅此三种。
- 核心工作流：捕获/定时 → context 组装 → 单个 agent run（managed API 或
  Claude Code）→ artifact + proposal → 人审 → 记忆/任务/知识沉淀 → 定期重跑。
- 最小实体：Space、User、Agent(+Version)、ActivityRecord、Session、
  Run(+Step/Attempt)、Artifact、Proposal、Memory、Task、Source、Automation、
  WorkflowDefinition（存储态）。
- 最小执行组件：orchestration service、model_api + claude_code 两个适配器、
  确定性 Verification Engine（A2 现状不扩）、scheduler、CredentialBroker、
  worktree 沙箱 + Docker fail-closed。
- 显式排除：LLM Planner、路由评分增强、conformance 第二波、D2–D4、插件、
  OpenCode 扩权、Cards/Time/Graph/Relations/Publications、Open Skill 导入。

## 5. 停止建设清单（附重启证据）

- [ ] **S1 进化层 D2–D4 后续**（评估 harness 执行器、bundle 扩展、inbox 打磨）
  - 重启证据：真实使用 30 天自然积累 ≥20 条非人造进化信号，且至少一次提示词
    回归是人工审批漏掉的。
- [ ] **S2 运行时扩张**（第四个 CLI、conformance 第二波、OpenCode 越过低风险白名单）
  - 重启证据：出现现有三运行时都无法承载的真实工作负载。
- [ ] **S3 概念分类法与 Open Skill 导入**
  - 重启证据：非作者用户提出导入外部 skill 的真实请求。
- [ ] **S4 插件框架 Level 3 及新插件边界条款**
  - 重启证据：第二个真实插件的需求方出现。
- [ ] **S5 前端模块广度**（Cards/Time/Knowledge 存根实现、graph/publications 深化）
  - 重启证据：dogfooding 摩擦记录中被点名 ≥3 次。

## 6. 保护清单（禁止简化/重设计）

1. Proposal-first 持久写 + Activity-first 捕获（B9/B10/B24）—— 产品命题本身。
2. 单一图执行基座（N1/N3）—— 任何"轻量第二执行通道"提案都应被拒绝。
3. 确定性验证为完成权威（A2：声明检查后 exit-0 ≠ 成功；fail-closed）。
4. 凭据通道隔离与全线 fail-closed 姿态（ADR 0008、B41–B49）。
5. 不可变运行出处（contract snapshot、route decision 审计、attempt 级 finalization）。

## 7. 最高风险错误转向（已在发生的信号）

**"基础设施进度替代产品验证"** —— dogfooding 门槛永远"即将开始"，平台以每天
一个 track 的速度自我完善。直接证据：ADR 0010 立门次日 D4 完工。

漂移监测信号（每月检查一次）：
- [ ] ADR 0010 六条标准是否有任何一条达标？
- [ ] `evolution_signals` 表是否出现非人造行？
- [ ] `server/migrations/` 是否仍只有 `0001_baseline.sql`？
- [ ] `.agent/plans/` 是否出现第三份大计划？
- [ ] friction-driven fix 记录是否为零？

## 8. 未来 8–12 周焦点（执行项）

- [ ] **主焦点（唯一）**：执行 ADR 0010 dogfooding 检查点本身 —— 真实研究/写作/
      自动化工作 30 天、两名成员、每周三个实质产出；只修使用中发现的具体摩擦。
- [ ] 次焦点一：hardening 计划 P0 项收尾核实（CI、备份、告警）。
- [ ] 次焦点二：日常面/操作员面导航切分（A9 修订），使家庭成员可用
      （dogfooding 第二条标准的前提）。
- [ ] 文档纠偏：修正 §0 列出的三处文档-代码分歧（NON_GOALS 的 automation 条目、
      current-focus 的自进化非目标表述）。
- 不建：D 轨扩展、路由评分增强、第四运行时、插件分发、Cards/Time/Graph。
- 需真实使用验证的决策：workflow-as-data 治理仪式（版本/晋升/pin）是否高于
  "重跑上次那个"的真实需求。
- 保持刻意临时态：LLM Planner 与 atomicity evaluator、路由评分权重、
  进化 schema 信号分类、conformance 检查清单。
- 允许扩张边界的唯一成功证据：一个完整 30 天检查点周期六条全部达标。
