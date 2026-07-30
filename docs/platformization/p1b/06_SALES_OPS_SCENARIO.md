# sales_ops 第二业务场景

更新时间：2026-07-30

## 目标与边界

`sales_ops` 是 P1B 新增的第二个业务场景，用于验证平台合同能够在不复制
Connector、DatasetVersion、SemanticRegistry、ScenarioPackageLoader 和
QueryEngine 的情况下承载新业务域。

所有销售数据均由固定随机种子生成，`data_classification=simulated`。本工作包
没有连接真实企业数据、外部数据库或附件中出现过的系统。

## 场景包

`scenarios/sales_ops/` 按现有 Scenario Package Contract 提供 12 个文件：

- `manifest.yaml`
- `data_models.yaml`
- `metrics.yaml`
- `dimensions.yaml`
- `relationships.yaml`
- `terminology.yaml`
- `sql_examples.yaml`
- `diagnostics.yaml`
- `report_templates.yaml`
- `permissions.yaml`
- `response_profiles.yaml`
- `knowledge_manifest.yaml`

场景通过现有 Loader、Validator、DatasetVersion、SemanticRegistry 和激活机制
发布为 `ScenarioVersion=1.0.0`、`SemanticModelVersion=1.0.0`。平台查询上下文
只从 ACTIVE 版本解析实际 relation 绑定。

## 模拟数据

固定参数：

- seed：`20260730`
- seed_run_id：`SALES-SIM-v1-20260730`
- 时间范围：`2025-01-01` 至 `2026-06-30`
- 销售订单：50,000
- 订单行：82,514
- 客户：8,000
- 产品：120
- 区域：8
- 渠道：5
- 销售人员：80

生成器可重复执行；已存在数据与期望订单数一致时只核验并返回持久化摘要，
不重复插入。订单数冲突时明确拒绝，避免静默覆盖。当前 PostgreSQL 中原有
充电会话仍为 300,000，未因 sales_ops 安装发生变化。

## 数据模型

迁移 `0011` 新增并隔离以下表：

- `sales_business_date`
- `sales_region`
- `sales_channel`
- `salesperson`
- `sales_customer`
- `sales_product_category`
- `sales_product`
- `sales_order`
- `sales_order_item`

迁移已完成隔离 SQLite 循环：

```text
base → 0011 → 0010 → 0011
```

sales_ops Schema 在迁移 `0011` 引入；当前 PostgreSQL 已随双场景会话隔离
工作包升级为 `0012 (head)`。降级到 `0010` 会删除上述 sales_ops 表，不修改
charging_ops 事实表和 P1A 平台表。

## 指标与维度

已实现并在当前 PostgreSQL 对账的 12 项指标：

- `sales_revenue`
- `order_count`
- `customer_count`
- `average_order_value`
- `sales_quantity`
- `gross_profit`
- `gross_margin`
- `refund_amount`
- `refund_rate`
- `new_customer_count`
- `repeat_customer_count`
- `channel_contribution`

支持的八类维度为 date、region、channel、product、category、
customer_segment、salesperson 和 organization。受限字段
`sales_customer.customer_name` 不进入查询上下文白名单。

基线由 `tests/evaluation/sales_ops_metric_baseline_v1.json` 固化。对账脚本
`scripts/verify_sales_ops_metric_reconciliation.py` 解析 ACTIVE 场景、数据集和
语义版本后逐项比较，结果为：

```text
metrics_checked=12
differences={}
status=passed
```

## 查询与隔离

`SalesOpsDeterministicEngine` 实现现有 `QueryEngine` 合同，输出统一
`QueryResult`，并携带 scenario、dataset、semantic、run_id、trace_id 和模拟
数据证据。查询入口拒绝以下情况：

- 请求场景不是 `sales_ops`；
- QueryContext 场景或版本不匹配；
- sales_ops 没有 ACTIVE Scenario/Dataset/Semantic 版本；
- 指标、时间或维度无法受控解析；
- 请求字段不在当前权限白名单。

集成测试验证：

- 相同 seed 重复生成得到相同订单数、订单行数和 checksum；
- charging_ops 与 sales_ops 可同时 ACTIVE；
- 跨场景调用返回 `SCENARIO_MISMATCH`；
- 禁用 sales_ops 后其 ACTIVE 解析失败；
- 禁用 sales_ops 后 charging_ops 仍可解析且事实数量不变。

## 当前证据

- 场景包合同：12 个文件，校验 PASS；
- sales_ops 单元与集成测试：`2/2 PASS`；
- 固定种子真实 PostgreSQL 生成：PASS；
- 12 项指标真实 PostgreSQL 对账：`12/12 PASS`；
- 跨场景成功数：`0`；
- SQLite Alembic 完整升降级：PASS；
- PostgreSQL Alembic：`0012 (head)`。

同一套 ChatBI API/UI 的 sales_ops 场景切换已在 P1B 前端工作包完成，证据见
`09_FRONTEND_INTEGRATION.md`。

## 回滚

应用层可先禁用 `sales_ops` ScenarioVersion，使场景不再可解析；平台和
charging_ops 继续运行。需要回退 Schema 时执行 `alembic downgrade 0010`。
该操作会删除 sales_ops 模拟数据，执行前应确认是否需要保留测试证据；不得
删除 PostgreSQL 数据卷。
