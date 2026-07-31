# P2A SQLBot 运行 Smoke 结果

## 结论

- 状态：`NOT_EXECUTED`
- 阻断码：`HUMAN_MODEL_CONFIG_REQUIRED`
- 真实模型调用：0
- Mock Provider 调用：0
- 外部请求：0
- 10 条目标问题执行：0/10
- `SQLBOT_QUERY_RUNTIME`：`NOT_PASS`

缺少可验证的 `provider`、`base_url`、`model_name` 和运行时凭据，
因此没有调用未知端点，也没有用 Mock 冒充真实运行。此状态不是 Smoke
失败用例统计，而是 Smoke 前置门禁未满足。

## ACTIVE 数据范围

在隔离 PostgreSQL 的受控语义 View 中解析：

| 场景 | min_date | max_date | 行数 | 数据性质 |
| --- | --- | --- | ---: | --- |
| `charging_ops` | 2025-01-01 | 2026-06-30 | 300,000 | 模拟数据 |
| `sales_ops` | 2025-01-01 | 2026-06-30 | 50,000 | 模拟数据 |

charging 时间按 `Asia/Shanghai` 将 `start_time` 转成本地日期。两个场景
各有且仅有 1 条 ACTIVE 上下文。

## 10 条目标问题

以下问题已由 ACTIVE 数据范围生成，但均未发送给模型或 SQLBot：

| ID | 场景 | 目标问题 | 状态 |
| --- | --- | --- | --- |
| RSM-CH-001 | charging_ops | 有效期内最近 30 天充电收入趋势 | NOT_EXECUTED |
| RSM-CH-002 | charging_ops | 按区域统计充电收入和订单量 | NOT_EXECUTED |
| RSM-CH-003 | charging_ops | 充电收入最高的 10 个场站 | NOT_EXECUTED |
| RSM-CH-004 | charging_ops | 设备利用率最低的场站 | NOT_EXECUTED |
| RSM-CH-005 | charging_ops | 充电量和充电收入的关系 | NOT_EXECUTED |
| RSM-SA-001 | sales_ops | 有效期内最近 30 天销售收入 | NOT_EXECUTED |
| RSM-SA-002 | sales_ops | 按渠道统计销售收入 | NOT_EXECUTED |
| RSM-SA-003 | sales_ops | 销售收入最高的 10 个商品 | NOT_EXECUTED |
| RSM-SA-004 | sales_ops | 退款率最高的商品分类 | NOT_EXECUTED |
| RSM-SA-005 | sales_ops | 按区域统计客户数和订单量 | NOT_EXECUTED |

可复现脚本会为每条问题输出完整的未执行记录，包括
`question`、`normalized_question`、`scenario`、`model`、
`sqlbot_session`、`generated_sql`、`guard_result`、
`execution_status`、`row_count`、`result_hash`、`latency_ms`、
`token_usage`、版本、`run_id`、`trace_id` 和 `error`。所有只有在真实
运行后才可产生的字段均为 `null`，不会填入推测值。

## 可复现命令

```powershell
python scripts/record_blocked_runtime_evaluation.py `
  --credential-ref-present `
  --charging-min-date 2025-01-01 `
  --charging-max-date 2026-06-30 `
  --sales-min-date 2025-01-01 `
  --sales-max-date 2026-06-30 `
  --output .cache/p2a-runtime/runtime-blocked-evidence.json
```

预期退出码为 2，摘要为：

```text
runtime_status=HUMAN_MODEL_CONFIG_REQUIRED
smoke: total=10, executed=0, not_executed=10
model_called=false
external_request_count=0
```

`.cache` 中的运行产物不提交 Git；提交的是可审计脚本、测试和本结论。

## 最小人工输入

需要提供以下四项运行时引用后，才能执行真实 Smoke：

1. `provider`
2. `base_url`
3. `model_name`
4. `credential_ref`

不得在工单、日志、命令输出或 Git 中提供凭据明文。
