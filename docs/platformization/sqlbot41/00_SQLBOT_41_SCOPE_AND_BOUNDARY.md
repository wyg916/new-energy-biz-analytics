# SQLBot 4.1 实时路由与受控开放 NL2SQL

## 结论

本工作包实现了受控开放 NL2SQL 的平台侧完整链路，并保留 Deterministic
Engine 作为核心指标、高风险请求和全部失败场景的安全路径。代码与离线/数据库
验收通过；本轮没有完成真实模型 SQLBot Runtime 的实时推理验收，因此不得把
Shadow、Canary 或 Scoped Stable 的合同测试描述为生产流量验证。

## 范围

- Schema Catalog：只从当前 ACTIVE 语义版本和权限过滤后的表列构建；
- Schema Retrieval：按问题、指标和维度检索，并补齐已发布 Join 关系端点；
- Query Understanding：核心指标与高风险请求优先固定到确定性引擎；
- SQL generation：仅接受 SQLBot v1.8.0 的结构化候选 SQL；
- Parser/AST：PostgreSQL 单条 `SELECT`，拒绝 CTE、集合操作、通配符和控制语句；
- Schema/Join：表列必须注册，Join 必须使用已发布等值关系；
- Permission/PII：候选 SQL 只能看到权限过滤后的字段，敏感字段名二次拒绝；
- Cost/timeout/row：最多 4 个 Join、明细查询强制 `LIMIT`、最多 500 行、5 秒数据库超时；
- Query Guard：所有候选 SQL 进入统一策略网关；
- Read-only execution：平台执行器要求独立 PostgreSQL 只读连接并显式设置只读事务；
- Result/Answer Guard：校验列形状、行数、有限数值和结构化数字来源；
- Audit：路由、Shadow、Fallback、版本、run_id 与 trace_id 进入既有证据表；
- Rollout：支持 Shadow、Canary 5%、Canary 20%、Scoped Stable 和自动回退。

## 明确非目标

- 不提供自由 SQL 输入或管理员 SQL 实验入口；
- 不允许 DDL/DML、多语句、跨库、系统表、敏感列或无界查询；
- 不修改前端、公共 API schema、根启动脚本或 Compose；
- 不宣称真实客户、生产流量、人工审批或经营收益；
- 不把 Mock/合同路由测试冒充真实模型推理。

## 路由与回退

1. 核心指标与高风险问题固定进入 Deterministic Engine；
2. Shadow 总是返回确定性结果，SQLBot 结果仅比较和审计；
3. Canary 按 tenant/workspace/user/scenario 稳定哈希分桶，请求 ID 不改变分桶；
4. Canary 控制组、作用域外请求、SQLBot 超时、策略拒绝和未知失败均回退确定性引擎；
5. Scoped Stable 仍受作用域 allowlist 约束，不等于全量开放；
6. 默认配置保持 SQLBot 关闭，生产配置仍保持 Deterministic Only。

## 数据库与安全影响

无数据库迁移、无 Schema 变更、无写入当前 DATA-4.1 数据库。实时数据库验证使用
`BEGIN READ ONLY`、`statement_timeout=5s` 和 `ROLLBACK`。一次全表聚合被超时取消，
随后受控 `LIMIT 5` 查询成功，证明超时边界没有被放宽。

## 回滚

回滚本工作包提交即可。运行时可立即将 `QUERY_ENGINE_MODE` 设置为
`DETERMINISTIC_ONLY` 或关闭 `SQLBOT_ENGINE_ENABLED`；数据库无迁移，无需数据回滚。
