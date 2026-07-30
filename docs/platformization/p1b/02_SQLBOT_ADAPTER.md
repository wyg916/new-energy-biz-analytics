# SQLBot Adapter

更新时间：2026-07-30

## 实现结论

SQLBot Adapter 已在现有 `QueryEngine` 合同下实现，返回统一
`QueryResult`，不改变项目自有 React UI，也不向浏览器暴露 SQLBot
账号、密码、Token 或内部 chat_id。

实际上游运行仍为 `SQLBOT_RUNTIME_PENDING`。本轮 Adapter 验收使用
HTTP Mock Transport，只证明平台合同、隔离、错误映射和安全控制有效，
不代表 SQLBot 容器或模型真实可用。

## 目录

实现位于 `backend/app/query_engines/sqlbot/`：

- `client.py`：后端专用 HTTP 客户端和秘密环境引用；
- `contracts.py`：会话、健康和标准化响应合同；
- `session_manager.py`：受控会话缓存和重建；
- `request_mapper.py`：平台请求到固定 SQLBot MCP 请求的映射；
- `response_parser.py`：只提取 SQL、结构化行、图表配置和 Token 用量；
- `error_mapper.py`：统一错误码和可重试属性；
- `health.py`：有界熔断器；
- `feature_flags.py`：启用与真实运行验收双门禁；
- `engine.py`：`SQLBotEngine` 和统一 `QueryResult`。

## QueryEngine 合同

`QueryEngine.execute` 现在接收：

```text
QueryRequest + QueryContext -> QueryResult
```

`QueryContext` 强制绑定：

- conversation；
- ScenarioVersion；
- SemanticModelVersion；
- DatasetVersion；
- SQLBot datasource；
- 当前场景允许的关系和字段；
- 执行模式、行数上限和取消状态。

返回仍包含：

- engine / engine_version；
- scenario / scenario_version；
- semantic_version / dataset_version；
- sql / columns / rows / chart_spec；
- evidence / warnings；
- execution_time / trace_id / run_id / status。

## 会话隔离

SQLBot 会话键由以下七个维度组成：

1. tenant；
2. workspace；
3. subject/user；
4. scenario；
5. scenario_version；
6. semantic_version；
7. dataset_version。

任何一个维度变化都会创建新 SQLBot 会话。访问 Token 只保存在后端进程内存，
不写入数据库证据、不写入日志、不进入 `QueryResult`。认证失效只允许一次受控
重建，不存在无限重试。

## 超时、取消和熔断

- HTTP 请求使用固定超时；
- 调用前后检查平台取消状态；
- 失败达到阈值后打开熔断器；
- 熔断恢复窗口只允许一个半开探测；
- SQLBot 错误转换为平台统一错误码；
- SQLBot Adapter 本身不修改 DeterministicEngine。

## 生成与执行模式

- `generate_only`：上游返回 SQL，平台 Query Guard 通过后交给注入的项目只读执行器；
- `upstream_readonly`：上游在专用只读 semantic view 上执行，平台仍对实际 SQL 和返回规模做独立校验。

固定 SQLBot v1.8.0 的公开 MCP API 尚不能可靠声明为生成与执行分离，
因此真实运行验收前不会启用任何模式。

## 配置门禁

- `SQLBOT_ENGINE_ENABLED=false`：默认关闭；
- `SQLBOT_RUNTIME_VERIFIED=false`：真实运行未验收；
- 生产环境若启用 SQLBot，必须同时满足运行已验收和独立 ChatBI 只读执行边界；
- 服务账号只通过 `SQLBOT_SERVICE_USERNAME` 与
  `SQLBOT_SERVICE_PASSWORD` 环境引用加载。

## 测试

`backend/tests/test_sqlbot_adapter.py` 覆盖：

- QueryResult 标准化和 Token 不泄漏；
- 用户、工作区、场景和版本会话隔离；
- generate-only 必须经过平台执行器；
- 超时、熔断和无无限重试；
- INSERT、UPDATE、DELETE、DROP、ALTER、多语句、系统表、非白名单表、
  非白名单字段、通配字段、危险函数、缺少 LIMIT、超大结果和 CTE 绕过。

结果：`18/18 PASS`。

纯单元测试使用 `no_db` marker，明确禁止创建或修改测试数据库；数据库相关
测试仍执行原有隔离建表流程，没有删除或弱化任何断言。

## 限制与回滚

- SQLBot 容器、模型和模拟数据源真实集成尚未完成；
- 当前会话秘密缓存随进程重启清空，随后受控重建；
- 上游只读执行模式必须等待专用 semantic view 和只读角色运行验收。

回滚时关闭 `SQLBOT_ENGINE_ENABLED`，或回退本工作包提交；
DeterministicEngine 不受影响。
