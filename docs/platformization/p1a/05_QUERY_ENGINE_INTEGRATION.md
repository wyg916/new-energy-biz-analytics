# Query Engine 与 ACTIVE 版本接入

## 链路

启用平台版本路由后的正式链路：

`IdentityContext → ScenarioResolver → ActiveSemanticResolver → DeterministicEngine → Query Guard → Readonly Executor → Answer Guard`

默认 `PLATFORM_VERSION_ROUTING_ENABLED=false`，因此不替换稳定 P0 路径。开启后缺少 ACTIVE 场景、语义或数据集会返回 409/fail-closed。

## QueryEngine

通用对象：

- `QueryRequest`
- `QueryResult`
- `QueryEngine`
- `DeterministicEngine`
- `SQLBotEngine`

QueryResult 包含 engine、engine_version、scenario、scenario_version、semantic_version、dataset_version、sql、columns、rows、chart_spec、evidence、warnings、execution_time、trace_id、run_id、status。

现有 Chat API 响应保持兼容，并追加 `query_result`。Dashboard、ChatBI、Diagnostics、Reports 在版本路由开启时解析同一个 ACTIVE DatasetVersion/SemanticModelVersion。

## SQLBot 边界

- 默认关闭；
- 健康状态 `NOT_CONFIGURED`；
- execute 明确抛出 `NOT_CONFIGURED`；
- 未连接真实业务数据库，未替换 DeterministicEngine。

## 安全结果

- 固定 Query Plan 评测：40/40；
- 危险 SQL：15/15 拒绝；
- 区域越权：403；
- Query Guard 和 Answer Guard smoke：PASS。
