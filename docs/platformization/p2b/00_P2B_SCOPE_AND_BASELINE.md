# P2B 范围与基线

## 状态声明

- 工作包：`P2B-AGENT-MEMORY-AND-PROCEDURAL-SKILLS`
- 辅助工作包：`P2A-Q1-SQLBOT-QUALITY-PATCH`
- 开发基线：`044a0b39920b64a81e8a2771569d69770929a1c6`
- 数据性质：固定随机种子与业务规则生成的模拟数据，不是企业生产数据
- 模拟数据时间：`2025-01-01` 至 `2026-06-30`
- 当前查询主答案：确定性引擎
- SQLBot：`SHADOW`，`SQLBOT_CANARY_ELIGIBLE=false`

本文冻结范围，不代表后续条目已经实现或验证。实现状态与运行证据以
`12_TEST_AND_ACCEPTANCE_MATRIX.md` 和 `14_P2B_IMPLEMENTATION_REPORT.md` 为准。

## 目标

1. 建立 Working、Semantic、Episodic、Procedural 和 Governance Meta 五类
   Memory 的最小生产闭环。
2. 所有长期记忆以 PostgreSQL 为权威事实源；Redis 仅承载短期 Working
   Memory，并在不可用时显式降级。
3. 建立受审核、版本化、可回滚的 Procedure Registry 与 Skill Registry。
4. 通过现有指标、维度、场景包和确定性查询链执行五个经营分析 Skill。
5. 将 Memory 和 Skill 接入现有 ChatBI 编排，保持单一 `run_id` 与逐步审计。
6. 提供用户可查看、确认、更正、拒绝、删除、导出和禁止记忆的受控 API/UI。
7. 以限时方式修复 SQLBot 的结构化输出、LIMIT、Source Binding、场景上下文和
   Golden Oracle，不改变 SQLBot 的 Shadow 状态。

## 范围

- 作用域：`GLOBAL`、`TENANT`、`WORKSPACE`、`USER`、`AGENT`、`SESSION`、`RUN`。
- 场景：`charging_ops` 和 `sales_ops`；不新增第三场景。
- Skill：`revenue_decline_diagnosis`、`order_anomaly_analysis`、
  `gross_profit_change_decomposition`、`station_efficiency_diagnosis`、
  `operating_report_generation`。
- 验收：至少 40 条 Memory 与 40 条 Skill 固定评测，以及现有全量回归。

## 非目标

- 多 Agent 或自治写库、审批、消息发送、跨系统执行。
- 自动激活模型生成的程序规则或让模型决定权限。
- 自由 SQL、生产 Canary、生产发布、Kubernetes、企业 SSO。
- 完整知识图谱、OCR、复杂多模态知识库、真实企业外部数据。
- 将 SQLBot Shadow 输出、模型猜测根因或实时业务值提升为长期事实记忆。

## 迁移并发事实

远端和指定基线的 Alembic 唯一 head 为 `0014`。扫描现有 worktree 时发现
`feat/p2a-sqlbot-runtime-rag-response` 的本地未推送提交包含
`0015_frontend_data_lineage`，其 `down_revision` 为 `0014`。本工作包不修改或
合并该并发 worktree；P2B 使用全局不重复的 revision 标识并显式指向本分支的
唯一 head `0014`。未来若两个分支汇合，必须显式解决 Alembic head，不得静默
merge。

## 基线证据

- 分支与远端：`feat/p2a-runtime-closeout` 与远端 ahead/behind 为 `0/0`。
- Alembic：运行库 `current=0014`，代码 `heads=0014`。
- 数据库：PostgreSQL 16，`public` schema 共有 62 张表；后续迁移前记录核心表
  精确行数并备份平台元数据。
- Feature Flags：开发环境 `QUERY_ENGINE_MODE=SHADOW`、
  `PLATFORM_VERSION_ROUTING_ENABLED=true`、`SQLBOT_CANARY_ELIGIBLE=false`。
- 已提交事实基线：charging_ops 15/15、sales_ops 12/12、Deterministic 40/40、
  DQ 20/20、后端 183/183、Playwright 20/20；本工作包将重新运行并以新证据
  覆盖这些声明。

## 数据库与安全影响

- 允许新增可 downgrade 的 Memory、Procedure、Skill、Source Binding 表。
- 不修改既有业务事实数据，不改变 15+12 项已发布指标。
- 正式迁移前备份平台元数据；完整迁移循环只在隔离数据库或临时 schema 执行。
- IdentityContext 在服务端注入 tenant、organization、workspace、user 与权限；
  前端和模型都不能决定最终作用域。
- 所有检索在查询前进行租户、用户、场景、状态与有效期硬过滤。
- 禁止写入密码、Token、API Key、数据库凭据和真实连接串。

## 验收与回滚

验收要求包括五类 Memory、五个 Skill、`run_id` 回放、删除后不可召回、跨租户/
跨用户/跨场景访问成功数为 0、未审核程序规则生效数为 0、现有回归保持通过，
以及 SQLBot 故障不影响确定性主答案。

代码回滚按独立提交逆序执行 `git revert <commit>`。数据库回滚使用对应 Alembic
`downgrade`，不得删除数据库卷；用户记忆删除遵守最小删除审计和 Legal Hold
预留规则。
