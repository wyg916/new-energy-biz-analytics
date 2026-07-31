# P2A 100 条运行型 Golden Set

## 结论

- 离线合同：`PASS`，100/100
- 真实运行评测：`NOT_EXECUTED`，0/100
- 阻断码：`HUMAN_MODEL_CONFIG_REQUIRED`
- `SQLBOT_GOLDEN_RUNTIME`：`NOT_PASS`
- Canary：`NOT_ELIGIBLE`

离线 100/100 只验证 Golden Set 的结构、语义引用、拒答标签和 Query
Guard 负向候选，不是 SQLBot 执行准确率。

## 离线合同复核

执行 `python scripts/run_dual_engine_eval.py`：

| 项目 | 结果 |
| --- | ---: |
| 总数 | 100 |
| 通过 | 100 |
| 失败 | 0 |
| charging_ops | 48 |
| sales_ops | 52 |
| 每类用例 | 20 |
| 安全候选 | 10 |
| 危险 SQL 成功 | 0 |
| 越权攻击成功 | 0 |

该命令自身明确输出 `SQLBOT_RUNTIME_PENDING`，并将所有运行指标保留为
`null`。

## 真实运行分层结果

100 条用例均记录为：

| 字段 | 值 |
| --- | --- |
| `contract_status` | `NOT_REEVALUATED` |
| `model_called` | `false` |
| `sql_generated` | `false` |
| `sql_guard_pass` | `null` |
| `execution_attempted` | `false` |
| `execution_pass` | `null` |
| `result_match` | `null` |
| `permission_pass` | `null` |
| `final_status` | `NOT_EXECUTED` |
| `error` | `HUMAN_MODEL_CONFIG_REQUIRED` |

没有跳过失败后只统计成功项，也没有人工修 SQL 后重新归入模型成功。

## 运行指标

由于没有真实模型调用、SQL 生成和只读执行，以下指标均为
`NOT_AVAILABLE`，底层 JSON 值为 `null`：

| 指标 | 结果 |
| --- | --- |
| Model Call Success Rate | NOT_AVAILABLE |
| SQL Generation Rate | NOT_AVAILABLE |
| SQL Guard Pass Rate | NOT_AVAILABLE |
| SQL Execution Rate | NOT_AVAILABLE |
| Execution Accuracy | NOT_AVAILABLE |
| Metric Value Accuracy | NOT_AVAILABLE |
| Time Range Accuracy | NOT_AVAILABLE |
| Dimension Accuracy | NOT_AVAILABLE |
| Sort Accuracy | NOT_AVAILABLE |
| Permission Violation Rate | NOT_AVAILABLE |
| Cross-scenario Violation Rate | NOT_AVAILABLE |
| Hallucinated Table Rate | NOT_AVAILABLE |
| Hallucinated Field Rate | NOT_AVAILABLE |
| Rejection Accuracy | NOT_AVAILABLE |
| P50/P95 Latency | NOT_AVAILABLE |
| Token Usage | NOT_AVAILABLE |
| 单次估算成本 | NOT_AVAILABLE |
| charging_ops 运行结果 | NOT_AVAILABLE |
| sales_ops 运行结果 | NOT_AVAILABLE |

注意：Datasource 角色负向验证中危险、越权和跨场景成功数均为 0，是独立
数据库权限证据，不能替代上述模型运行指标。

## 门禁与后续

10 条真实 Smoke 尚未全部完成，因此按门禁不启动 100 条真实运行。
`QUERY_ENGINE_MODE` 保持 `SHADOW`，`SQLBOT_CANARY_ELIGIBLE=false`。
配置完整模型合同后必须先执行 10 条 Smoke，再以最大并发 2、单题超时、
总预算和每题最多一次受控重试执行完整 100 条，并保留全部 Bad Case。
