# 双引擎路由

更新时间：2026-07-30

## 模式

`EngineRouter` 已实现五种显式模式：

- `DETERMINISTIC_ONLY`
- `SHADOW`
- `CANARY`
- `SQLBOT_ENABLED`
- `DISABLED`

未指定配置时，开发和测试环境为 `SHADOW`，生产环境为
`DETERMINISTIC_ONLY`。生产配置校验拒绝其他模式。

## 路由规则

现有 charging_ops 核心问题继续标记为
`deterministic_supported=true`，即使配置为 `CANARY` 或
`SQLBOT_ENABLED` 也固定进入 DeterministicEngine。

长尾查询只有在以下条件满足时才可能进入 SQLBot：

1. 当前模式允许；
2. 场景、时间、指标和权限已明确；
3. ACTIVE 场景、数据集和语义版本齐全；
4. SQLBot datasource 已绑定；
5. SQLBot 真实运行已验收；
6. Canary 范围和确定性百分比分桶命中。

Canary 支持 tenant、workspace、user、scenario 和 percentage。分桶输入
包含身份、场景和 trace id，使用 SHA-256 产生可审计确定性结果。

## Fail-closed

- `DISABLED`：拒绝；
- 未命中 Canary 的不受支持长尾查询：返回明确错误，不静默退回；
- SQLBot 在 Canary 或 Enabled 模式失败：返回统一路由错误，不静默 fallback；
- SHADOW 中 SQLBot 失败：用户仍得到确定性结果，同时记录明确错误码；
- 发生重大结果冲突：不得把 SQLBot 结果直接返回用户。

## 路由证据

`query_route_decision` 记录：

- route_decision / route_reason / mode / engine；
- scenario_version / semantic_version / dataset_version；
- feature_flag_version；
- run_id / trace_id；
- tenant / workspace / subject。

记录中不包含 SQLBot Token 或账号密码。

## 回退

将 `QUERY_ENGINE_MODE=DETERMINISTIC_ONLY` 即可一键切回稳定路径。生产默认
已经是该模式。

## 测试

路由单元测试覆盖：

- Deterministic-only 不调用 SQLBot；
- Shadow 返回确定性主结果并比较 SQLBot；
- SQLBot 故障不影响 Shadow 用户结果；
- 100% 和 0% Canary；
- 核心问题在 SQLBOT_ENABLED 下仍固定确定性；
- DISABLED fail-closed。

结果：`6/6 PASS`。
