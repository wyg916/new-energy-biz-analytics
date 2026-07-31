# P2A Shadow 运行验收

## 结论

- 真实 SQLBot 双跑：`NOT_EXECUTED`，0/20
- 隔离平台故障降级：`PASS`，20/20
- `SQLBOT_SHADOW`：`NOT_PASS`

20 条请求证明了 SQLBot `RUNTIME_PENDING` 时主回答不受影响、错误不静默
丢失、证据可关联。它们没有调用真实模型、没有生成 SQL、没有执行
SQLBot 查询，因此不能计为用户要求的 20 条真实 Shadow。

## 隔离运行环境

| 项目 | 值 |
| --- | --- |
| API | `127.0.0.1:18002` |
| 数据库 | 独立 Compose 项目 `renewable-p2a-runtime` |
| 数据性质 | 模拟数据 |
| Alembic | 0014 |
| `QUERY_ENGINE_MODE` | SHADOW |
| `SQLBOT_ENGINE_ENABLED` | true，仅隔离故障验证 |
| `SQLBOT_RUNTIME_VERIFIED` | false |
| 生产/默认开关修改 | 无 |

临时运行参数只用于隔离验收容器，未写入仓库配置，也没有将
`SQLBOT_RUNTIME_VERIFIED` 伪造为 true。

## 20 条平台请求

使用 `analyst_admin` 模拟用户通过正式 `/api/v1/chat/query` API 发送：

| 项目 | 结果 |
| --- | ---: |
| 总请求 | 20 |
| charging_ops | 10 |
| sales_ops | 10 |
| HTTP 200 | 20 |
| 主回答 completed | 20 |
| 主引擎 deterministic | 20 |
| `DETERMINISTIC_WITH_SHADOW` | 20 |
| `SQLBOT_RUNTIME_PENDING` 路由原因 | 20 |
| 响应中运行待定 warning | 20 |
| SQLBot 故障导致主回答失败 | 0 |

charging 使用 2026 年 6 月的 10 个已冻结核心指标，sales 使用 2026
年 6 月的 10 个已发布销售指标。业务值未写入本报告；每个响应均来自
隔离 PostgreSQL 正式 API 链路。

## 数据库证据

最近一批 `shadow_evaluation`：

| 字段 | 结果 |
| --- | ---: |
| 记录总数 | 20 |
| charging_ops | 10 |
| sales_ops | 10 |
| `error_code=SQLBOT_RUNTIME_PENDING` | 20 |
| `permission_result=NOT_EXECUTED` | 20 |
| SQLBot SQL 非空 | 0 |
| SQLBot 结果哈希非空 | 0 |
| Execution Accuracy 非空 | 0 |
| run_id 非空 | 20 |
| trace_id 非空 | 20 |
| 可关联路由决策 | 20 |
| SQLBot session binding | 0 |

这组空值是关键真实性证据：系统没有把未发生的模型调用、SQL 生成或
SQLBot 查询伪装成 Shadow 成功。20 条 `error_code` 说明错误已进入证据
表，不是静默丢失。

## 自动化回归

新增测试
`test_shadow_runtime_pending_preserves_main_result_and_error_evidence` 验证：

1. 返回确定性结果；
2. 响应带 `SQLBOT_RUNTIME_PENDING`；
3. Shadow 记录保存同一 run_id 和 trace_id；
4. SQLBot SQL、结果哈希和执行准确率保持空值；
5. 路由记录和 Shadow 错误可关联。

## 真实 Shadow 尚缺证据

以下要求均为 0/20：

- 真实模型调用；
- 真实 SQL 生成；
- Query Guard 后的 SQLBot 只读执行；
- 指标值、时间、维度、排序和权限比较；
- SQLBot 结果哈希、时延和 Token；
- 真实 SQLBot session binding。

只有至少一家 Provider 通过真实认证和三类 Smoke、10 条 SQLBot Smoke 全部
执行完成并继续跑满 20 条双跑后，才可重新判定 `SQLBOT_SHADOW`。本轮三家
`/models` 均为 HTTP 401，因此没有资格把既有降级证据改写为真实 Shadow。
