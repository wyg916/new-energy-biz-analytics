# Shadow 双跑与评测证据

更新时间：2026-07-30

## 数据模型

迁移 `0010` 新增：

- `sqlbot_session_binding`
- `shadow_evaluation`
- `query_route_decision`

迁移已在隔离 SQLite 数据库完成：

```text
base → 0010 → 0009 → 0010
```

## Shadow 行为

`SHADOW` 模式执行顺序：

1. DeterministicEngine 生成用户主结果；
2. 尝试调用 SQLBotEngine；
3. SQLBot 结果不替换当前用户答案；
4. 按结果、指标值、时间、维度、权限和版本进行比较；
5. 写入 ShadowEvaluation；
6. SQLBot 不可用时记录错误码，主结果保持有效。

## 记录字段

`shadow_evaluation` 记录：

- question / normalized_question；
- tenant / workspace / subject / conversation；
- scenario / scenario_version；
- semantic_version / dataset_version；
- deterministic_sql / sqlbot_sql；
- deterministic_result_hash / sqlbot_result_hash；
- execution_accuracy / metric_value_match；
- time_range_match / dimension_match；
- permission_result / row_count / latency_ms / token_usage；
- error_code / error；
- run_id / trace_id。

结果哈希使用结构化 columns、rows、状态和版本，不比较 SQL 字符串来代替
执行结果。

## 重大冲突

任一条件成立即视为重大冲突：

- 结构化结果哈希不同；
- 指标值不一致；
- 时间范围不一致；
- 维度不一致；
- 权限结果不是 PASS。

重大冲突不能进入用户可见 SQLBot Canary 结果。

## 秘密边界

`sqlbot_session_binding` 记录八维绑定、external chat_id 和受控重建代次，
不包含 access token、账号或密码。持久化测试显式验证模型没有
`access_token` 字段。

## 当前证据

- Router + Adapter 纯单元测试：`24/24 PASS`；
- Shadow、route、session 持久化测试：`1/1 PASS`；
- ChatBI SHADOW 集成：PASS；
- ACTIVE 版本路由回归：PASS；
- 真实 SQLBot 双跑：`PENDING`。

由于真实 SQLBot Runtime 尚未可用，当前没有伪造 execution accuracy、
Token 使用或 Shadow 一致率。真实指标只能在容器、模型和模拟 datasource
完成验收后生成。

## 回滚

关闭 SQLBot 或切换 `DETERMINISTIC_ONLY` 后不再产生新 Shadow 调用。迁移
`0010` 可 downgrade 到 `0009`，会删除 P1B 路由证据表；正式回滚前应先导出
所需审计证据。
