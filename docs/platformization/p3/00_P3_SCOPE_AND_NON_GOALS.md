# P3 范围与非目标

## 状态声明

- 工作包：`P3-ENTERPRISE-GOVERNANCE-AND-PRODUCTION-READINESS`
- 开发基线：`7ea31fcc7c81106c5a0c169c5b06efdbc791e1d0`
- 开发分支：`feat/p3-enterprise-governance-readiness`
- 数据性质：固定随机种子和业务规则生成的模拟数据，不是企业生产数据
- 数据时间：`2025-01-01` 至 `2026-06-30`
- 用户主答案：`DeterministicEngine`
- SQLBot：`SHADOW`，`SQLBOT_ENGINE_ENABLED=false`，`SQLBOT_CANARY_ELIGIBLE=false`

本文只冻结 P3 范围，不代表下列能力已经实现或验证。实际状态以本目录中的测试矩阵和
实施报告为准。

## 主线范围

1. 服务端可信 Principal / Identity 注入，以及本地认证和可测试 OIDC Provider 抽象。
2. RBAC 基础权限和 tenant、workspace、scenario、resource owner、数据分类、环境约束的
   ABAC 默认拒绝闭环。
3. 仅保存引用元数据的 CredentialReference，以及显式允许的 Secret Provider、轮换、
   禁用、撤回和使用审计。
4. Retention Policy、Legal Hold、删除/归档冲突处理和管理 API。
5. 统一 Governance Audit、站内安全告警、检索、分页和导出。
6. Scenario Package、Semantic Model、RAG 文档、Procedure、Skill、SQLBot Source Binding
   和 Policy Bundle 的 Release Registry、审批、激活与回滚。
7. 将统一授权服务接入 Orchestrator、Memory、Skill/Procedure、RAG、SQL Guard 和数据源访问。
8. 基于正式后端 API 的企业治理 React UI。
9. 本地隔离环境中的容量、并发、故障恢复、迁移循环和备份恢复验收。

## 独立 Conditional 轨道

SQLBot 真实外部 10 Smoke、30 代表性 Golden、20 Shadow 复评只在 CredentialReference
安全注入成功后运行。未注入时必须在外部请求前 fail-closed，并如实记录为
`CONDITIONAL`；该结果不阻塞 P3 治理主线完成。

无论复评结果如何，P3 都不会自动开启 Canary、替换确定性主链、把 Shadow 结果写入长期
事实，或让 SQLBot 故障影响用户主答案。

## 非目标

- 不建设多 Agent 或自治执行系统。
- 不开发第三个业务场景，不修改 charging_ops 15 项和 sales_ops 12 项指标结果。
- 不开放自由 SQL，不降低 Query Guard、Answer Guard、Memory Guard 或 RAG 权限过滤。
- 不接入真实企业数据、真实企业 IdP、真实生产 Secret 或真实生产发布。
- 不自动写库、审批、激活、发布、发邮件、建工单或发送外部消息。
- 不让模型、前端 Header 或请求参数决定最终身份、租户、用户或权限。
- 不删除 PostgreSQL/Redis 卷，不使用历史、离线或 Mock 结果冒充本轮真实外部调用。

## 回滚原则

代码按 P3 独立提交逆序执行 `git revert`。数据库只使用明确的 Alembic downgrade 路径，
回滚前保留审计和治理元数据；不得删除数据库卷或改写既有 revision。
