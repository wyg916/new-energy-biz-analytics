# 平台版本路由 Canary

更新时间：2026-07-30

## 默认值

平台版本路由现在按环境计算有效默认值：

| 环境 | PLATFORM_VERSION_ROUTING_ENABLED | QUERY_ENGINE_MODE |
|---|---|---|
| development | true | SHADOW |
| test | true | SHADOW |
| production | false | DETERMINISTIC_ONLY |

显式环境变量高于非生产默认值。生产配置校验会拒绝启用平台版本路由，也会
拒绝非 `DETERMINISTIC_ONLY` 的查询引擎模式。私有部署 Compose 对两个值
进行显式冻结，避免环境漂移。

测试总夹具为不依赖 P1A ACTIVE 版本的既有测试显式关闭平台版本路由；专门的
ACTIVE 路由和 Canary 测试会显式开启并验证完整路径。这是测试隔离，不改变
应用在 development/test 环境的默认值。

## Canary 范围

SQLBot 长尾查询 Canary 支持以下组合范围：

- tenant
- workspace
- user
- scenario
- percentage

非空范围必须全部命中。percentage 使用 tenant、workspace、subject、
scenario 和 request/trace id 的 SHA-256 确定性分桶。首轮场景 allowlist
仅包含 `charging_ops` 和 `sales_ops`，默认比例为 5%。SQLBot Runtime 未
验证期间保持 `SHADOW`，不把 5% 配置解释为已开放用户可见 SQLBot 结果。

核心指标和确定性支持问题即使在 `CANARY` 或 `SQLBOT_ENABLED` 模式下也固定
进入 DeterministicEngine。未命中 Canary 的长尾请求返回
`CANARY_NOT_SELECTED`，SQLBot 故障返回明确路由错误，不执行静默 fallback。

## 版本和审计证据

`query_route_decision` 已记录：

- `route_decision`
- `route_reason`
- `mode`
- `engine`
- `scenario_version`
- `semantic_version`
- `dataset_version`
- `feature_flag_version`
- `run_id`
- `trace_id`
- tenant / workspace / subject

所有正式消费者统一读取
`effective_platform_version_routing_enabled`。启用时从 ACTIVE
ScenarioVersion、DatasetVersion 和 SemanticModelVersion 解析绑定；版本不
完整时 fail-closed，不回退到未发布关系。

## SQLBot 代理网络

主平台 API 加入名为 `renewable-sqlbot-proxy` 的共享 Docker 网络。SQLBot
隔离 Compose 只通过该网络向 API 暴露内部服务名；浏览器仍只能访问项目二
API。SQLBot 本地管理端口继续只绑定 `127.0.0.1`。

网络定义只建立后端代理通道，不表示 SQLBot Runtime 已成功启动。当前镜像
运行仍为 `SQLBOT_RUNTIME_PENDING`。

## 立即回退

两级开关可以立即回到 P0/P1A 稳定链路：

```text
PLATFORM_VERSION_ROUTING_ENABLED=false
QUERY_ENGINE_MODE=DETERMINISTIC_ONLY
```

第一个开关停止 ACTIVE 平台版本关系路由，第二个开关保证 SQLBot 不被调用。
两者都不需要数据库降级或删除数据。生产默认和私有部署模板已经使用该组合。

## 测试证据

- 环境默认值、生产拒绝误开启、立即回退：PASS；
- tenant/workspace/user/scenario/percentage 范围：PASS；
- EngineRouter 五种模式回归：PASS；
- Canary 纯契约：`9/9 PASS`；
- ACTIVE Dataset/Semantic/Scenario 正式消费者：`2/2 PASS`；
- 禁用 ACTIVE 场景后 ChatBI fail-closed：PASS；
- SQLBot 默认禁用且 Runtime 未验证：PASS。

## 回滚

先应用上述两个配置即可逻辑回退。若需代码回滚，回滚本提交即可恢复平台版本
路由默认关闭；`0010` 路由证据表和 `0011` sales_ops 表无需降级。
