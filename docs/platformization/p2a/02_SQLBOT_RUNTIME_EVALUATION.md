# SQLBot 运行评测

更新时间：2026-07-31

## 当前实际边界

固定 SQLBot 容器已健康，但没有取得可验证的实际模型 base URL、模型合同和
运行时 CredentialReference 注入，也没有在 SQLBot 中创建已验收的模拟
datasource。因此本轮没有：

- 实际模型会话；
- 实际 NL2SQL；
- 实际 SQL Guard/执行；
- 实际 QueryResult 转换；
- 实际 Token、成本和时延；
- 实际双跑 Shadow。

## 100 条 Golden Set

离线合同复验：

- total=100
- passed=100
- charging_ops=48
- sales_ops=52
- 安全候选=10
- dangerous_sql_successes=0
- permission_attack_successes=0

这只证明 Golden Set 结构、指标/维度引用、拒答标签和安全候选合同，不是
SQLBot 运行准确率。运行指标继续为 null：

- SQL 生成和执行成功率；
- Execution Accuracy；
- 指标值、时间、维度、排序准确率；
- 幻觉表/字段率；
- 拒答准确率；
- P50/P95；
- Token/成本；
- 两场景一致率。

## Shadow 与 Canary

真实 Shadow 未开始，DeterministicEngine 仍是用户主答案。由于运行阈值没有
实际测量：

- `SQLBOT_SHADOW = NOT PASS`
- `SQLBOT_CANARY_ELIGIBLE = false`
- Canary 未开启
- `QUERY_ENGINE_MODE` 生产门禁仍固定为 `DETERMINISTIC_ONLY`

回退不依赖 SQLBot：

```text
SQLBOT_ENGINE_ENABLED=false
SQLBOT_RUNTIME_VERIFIED=false
QUERY_ENGINE_MODE=DETERMINISTIC_ONLY
```
