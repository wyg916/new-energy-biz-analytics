# P2A SQLBot 运行 Smoke 结果

> 当前有效结果：2026-08-01。下方 `NOT_EXECUTED` 为 Provider 修复前快照。

## 当前真实运行结果

- Provider/模型：DeepSeek / `deepseek-v4-flash`。
- ACTIVE 模拟数据范围：两个场景均为 2025-01-01 至 2026-06-30。
- charging_ops 5 条、sales_ops 5 条；真实外部请求 10/10，执行尝试 10/10。
- 全链路 PASS 1、FAIL 9；模型调用、SQL 生成、Guard 通过、上游只读完成率均为 10%。
- 通过用例：`RSM-SA-003`；记录了 SQL、SQL hash、结果 hash、行数、token 10938、版本、run_id 和 trace_id。
- P50 22135 ms，P95 40926 ms；权限违规和跨场景成功均为 0。

失败不是缓存或 Mock：9 条以结构化上游失败形式结束。只有 1 条成功暴露 usage，因此 token 覆盖为 1/10。10 条都已完成真实调用和有限重试边界，但没有达到“每条均生成 SQL 并执行”的 Smoke 验收门槛，状态为 `COMPLETED_WITH_FAILURES / NOT_PASS`。

证据：`.cache/p2a-runtime/sqlbot-smoke-live.json`，不进入 Git。

---

## 预运行快照（已取代）

## 结论

- 状态：`NOT_EXECUTED`
- 阻断码：`PROVIDER_AUTHENTICATION_FAILED`
- 真实模型调用：0
- Mock Provider 调用：0
- 外部请求：0
- 10 条目标问题执行：0/10
- `SQLBOT_QUERY_RUNTIME`：`NOT_PASS`

三家 `provider`、`base_url`、preferred `model_name` 和运行时凭据均已注入，
但真实 `/models` 全部 HTTP 401，无法发现可调用模型。已按指令继续验证其余
Provider，并对 MiMo 同时复核 Bearer 与 `api-key`；三家均失败后停止 SQLBot
主线。此状态不是 10 条问题失败统计，而是 Provider 认证前置门禁未满足。

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
  --provider-present `
  --base-url-present `
  --model-name-present `
  --credential-ref-present `
  --runtime-blocker PROVIDER_AUTHENTICATION_FAILED `
  --charging-min-date 2025-01-01 `
  --charging-max-date 2026-06-30 `
  --sales-min-date 2025-01-01 `
  --sales-max-date 2026-06-30 `
  --output .cache/p2a-runtime/runtime-blocked-evidence.json
```

预期退出码为 2，摘要为：

```text
runtime_status=PROVIDER_AUTHENTICATION_FAILED
smoke: total=10, executed=0, not_executed=10
model_called=false
external_request_count=0
```

`.cache` 中的运行产物不提交 Git；提交的是可审计脚本、测试和本结论。

## 解除条件

不再返回 `HUMAN_MODEL_CONFIG_REQUIRED`。当前需要在同一仓库外文件中更换或
修复至少一家可通过官方 `/models` 和三类 Smoke 的凭据/账户授权；不得在工单、
日志、命令输出或 Git 中提供凭据明文。认证成功后仍必须从 10 条 Smoke 开始，
不能直接复用本次未执行记录。
