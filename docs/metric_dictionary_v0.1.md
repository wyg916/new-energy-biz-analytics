# P0 指标字典 v0.1

> 状态：项目负责人已冻结 P0 指标清单
> 指标数量：15，不能再表述为“12—15 项”或“18 项”
> 版本：所有指标首版为 `0.1.0`，状态 `approved_for_implementation`
> 时间与时区：业务时区 `Asia/Shanghai`；查询使用左闭右开区间 `[start, end)`
> 数据来源：仅使用质量通过且标记为 `simulated` 的批次。

## 1. 通用规则

- 查询参数必须绑定：`:start_ts`、`:end_ts`、`:start_date`、`:end_date`、`:allowed_station_ids`。
- `:end_ts` 和 `:end_date` 为排他上界。
- 只有 `fact_charging_session.session_status = 'completed'` 进入订单、收入、电量和用户指标。
- 金额展示到 2 位小数，计算中保留数据库精度；比例存储为 0—1，小数展示为百分比。
- 完整覆盖期内无业务记录时，加总/计数指标返回 0；若数据批次缺失、延迟或质量失败，则返回 `NULL` 并标记数据不足。
- 所有除法使用 `NULLIF(denominator, 0)`；分母为 0 时返回 `NULL`，不得返回无穷、虚构值或静默替换为 0。
- 维度和来源表必须在白名单内，LLM 不得自由创建公式或 Join。
- 跨事实表计算必须先分别聚合为标量或共同的“场站—日期”粒度，再连接，禁止原始会话与成本/费用明细直接多对多 Join。

允许维度代码：`date`、`week`、`month`、`quarter`、`region`、`city`、`station`、`station_type`、`operator`、`device`、`user_segment`、`expense_type`。

## 2. 指标总表

| # | metric_id | 中文名称 | 业务定义 | 公式 | 单位 | 时间字段 | 来源表 | 允许维度 | 同义词 |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | charging_revenue | 充电收入 | 完成会话的电费实收净额与服务费实收净额之和 | electricity_fee_net_amount + service_fee_net_amount | 元 | settlement_time | fact_charging_session | 日期/区域/城市/场站/类型/运营商/设备 | 充电营收、营收、收入 |
| 2 | service_fee_revenue | 服务费收入 | 完成会话服务费实收净额合计 | SUM(service_fee_net_amount) | 元 | settlement_time | fact_charging_session | 日期/区域/城市/场站/类型/运营商/设备 | 服务费、服务费营收 |
| 3 | completed_order_count | 完成订单数 | 完成充电会话去重计数 | COUNT(DISTINCT session_id) | 单 | settlement_time | fact_charging_session | 日期/区域/城市/场站/类型/运营商/设备 | 订单数、完成单量、充电订单 |
| 4 | charging_volume_kwh | 充电量 | 完成会话结算充电量合计 | SUM(energy_kwh) | kWh | settlement_time | fact_charging_session | 日期/区域/城市/场站/类型/运营商/设备 | 电量、充电电量 |
| 5 | energy_cost | 电费成本 | 各电价时段结算电量乘采购电价后的成本合计 | SUM(energy_cost) | 元 | cost_date | fact_energy_cost | 日期/区域/城市/场站/类型/运营商 | 采购电费、电能成本 |
| 6 | variable_operating_cost | 可变运营成本 | P0 定义内、随业务量变化的运营费用合计 | SUM(amount WHERE is_variable) | 元 | expense_date | fact_operation_expense | 日期/区域/城市/场站/类型/运营商/费用类型 | 变动运营成本、可变成本 |
| 7 | gross_profit | 经营毛利 | 充电收入扣除电费成本和可变运营成本 | charging_revenue - energy_cost - variable_operating_cost | 元 | 结算日期 | 三张事实表 | 日期/区域/城市/场站/类型/运营商 | 毛利、经营贡献 |
| 8 | gross_margin | 毛利率 | 经营毛利占充电收入比例 | gross_profit / charging_revenue | % | 结算日期 | 三张事实表 | 日期/区域/城市/场站/类型/运营商 | 毛利率、经营毛利率 |
| 9 | avg_order_energy_kwh | 单均充电量 | 完成会话平均充电量 | charging_volume_kwh / completed_order_count | kWh/单 | settlement_time | fact_charging_session | 日期/区域/城市/场站/类型/运营商/设备 | 单均电量、每单电量 |
| 10 | revenue_per_kwh | 度电收入 | 每 kWh 充电量对应的充电收入 | charging_revenue / charging_volume_kwh | 元/kWh | settlement_time | fact_charging_session | 日期/区域/城市/场站/类型/运营商/设备 | 单位电量收入、每度收入 |
| 11 | cost_per_kwh | 度电成本 | 每 kWh 充电量对应的电费和可变运营成本 | (energy_cost + variable_operating_cost) / charging_volume_kwh | 元/kWh | 结算日期 | 三张事实表 | 日期/区域/城市/场站/类型/运营商 | 单位电量成本、每度成本 |
| 12 | station_utilization_rate | 场站利用率 | 实际充电枪口时长占可用枪口时长比例 | charging_duration / available_connector_duration | % | 会话/状态区间 | 会话、状态事件、设备维表 | 日期/区域/城市/场站/类型/运营商 | 利用率、枪口利用率 |
| 13 | device_online_rate | 设备在线率 | 在线可观测时长占全部可观测时长比例 | online_duration / observable_duration | % | 状态事件时间 | fact_device_status_event | 日期/区域/城市/场站/类型/运营商/设备 | 在线率、设备可用率 |
| 14 | device_fault_rate | 设备故障率 | 故障时长占全部可观测时长比例 | fault_duration / observable_duration | % | 状态事件时间 | fact_device_status_event | 日期/区域/城市/场站/类型/运营商/设备 | 故障率、故障时长占比 |
| 15 | active_user_count | 活跃用户数 | 周期内至少有 1 次完成会话的模拟用户去重数 | COUNT(DISTINCT user_id) | 人 | settlement_time | fact_charging_session | 日期/周/月/区域/城市/场站/类型/用户分群 | 活跃用户、充电用户数 |

`active_user_count` 为半可加指标，不得把多个场站、日期或分群的去重用户数直接相加得到整体活跃用户数。

## 3. 基准 SQL

以下 SQL 是口径基准，不是运行时代码。权限过滤必须在每个来源 CTE 中应用。

### M01 `charging_revenue`

```sql
SELECT COALESCE(SUM(electricity_fee_net_amount + service_fee_net_amount), 0) AS charging_revenue
FROM fact_charging_session
WHERE session_status = 'completed'
  AND settlement_time >= :start_ts AND settlement_time < :end_ts
  AND station_id = ANY(:allowed_station_ids);
```

### M02 `service_fee_revenue`

```sql
SELECT COALESCE(SUM(service_fee_net_amount), 0) AS service_fee_revenue
FROM fact_charging_session
WHERE session_status = 'completed'
  AND settlement_time >= :start_ts AND settlement_time < :end_ts
  AND station_id = ANY(:allowed_station_ids);
```

### M03 `completed_order_count`

```sql
SELECT COUNT(DISTINCT session_id) AS completed_order_count
FROM fact_charging_session
WHERE session_status = 'completed'
  AND settlement_time >= :start_ts AND settlement_time < :end_ts
  AND station_id = ANY(:allowed_station_ids);
```

### M04 `charging_volume_kwh`

```sql
SELECT COALESCE(SUM(energy_kwh), 0) AS charging_volume_kwh
FROM fact_charging_session
WHERE session_status = 'completed'
  AND settlement_time >= :start_ts AND settlement_time < :end_ts
  AND station_id = ANY(:allowed_station_ids);
```

### M05 `energy_cost`

```sql
SELECT COALESCE(SUM(energy_cost), 0) AS energy_cost
FROM fact_energy_cost
WHERE cost_date >= :start_date AND cost_date < :end_date
  AND station_id = ANY(:allowed_station_ids);
```

### M06 `variable_operating_cost`

```sql
SELECT COALESCE(SUM(amount), 0) AS variable_operating_cost
FROM fact_operation_expense
WHERE is_variable = TRUE
  AND expense_date >= :start_date AND expense_date < :end_date
  AND station_id = ANY(:allowed_station_ids);
```

### M07 `gross_profit`

```sql
WITH revenue AS (
  SELECT COALESCE(SUM(electricity_fee_net_amount + service_fee_net_amount), 0) AS value
  FROM fact_charging_session
  WHERE session_status = 'completed'
    AND settlement_time >= :start_ts AND settlement_time < :end_ts
    AND station_id = ANY(:allowed_station_ids)
), energy AS (
  SELECT COALESCE(SUM(energy_cost), 0) AS value
  FROM fact_energy_cost
  WHERE cost_date >= :start_date AND cost_date < :end_date
    AND station_id = ANY(:allowed_station_ids)
), variable_cost AS (
  SELECT COALESCE(SUM(amount), 0) AS value
  FROM fact_operation_expense
  WHERE is_variable = TRUE
    AND expense_date >= :start_date AND expense_date < :end_date
    AND station_id = ANY(:allowed_station_ids)
)
SELECT revenue.value - energy.value - variable_cost.value AS gross_profit
FROM revenue CROSS JOIN energy CROSS JOIN variable_cost;
```

### M08 `gross_margin`

```sql
WITH values AS (
  SELECT
    (SELECT COALESCE(SUM(electricity_fee_net_amount + service_fee_net_amount), 0)
     FROM fact_charging_session
     WHERE session_status = 'completed'
       AND settlement_time >= :start_ts AND settlement_time < :end_ts
       AND station_id = ANY(:allowed_station_ids)) AS revenue,
    (SELECT COALESCE(SUM(energy_cost), 0)
     FROM fact_energy_cost
     WHERE cost_date >= :start_date AND cost_date < :end_date
       AND station_id = ANY(:allowed_station_ids)) AS energy_cost,
    (SELECT COALESCE(SUM(amount), 0)
     FROM fact_operation_expense
     WHERE is_variable = TRUE
       AND expense_date >= :start_date AND expense_date < :end_date
       AND station_id = ANY(:allowed_station_ids)) AS variable_cost
)
SELECT (revenue - energy_cost - variable_cost) / NULLIF(revenue, 0) AS gross_margin
FROM values;
```

### M09 `avg_order_energy_kwh`

```sql
SELECT SUM(energy_kwh) / NULLIF(COUNT(DISTINCT session_id), 0) AS avg_order_energy_kwh
FROM fact_charging_session
WHERE session_status = 'completed'
  AND settlement_time >= :start_ts AND settlement_time < :end_ts
  AND station_id = ANY(:allowed_station_ids);
```

### M10 `revenue_per_kwh`

```sql
SELECT SUM(electricity_fee_net_amount + service_fee_net_amount)
       / NULLIF(SUM(energy_kwh), 0) AS revenue_per_kwh
FROM fact_charging_session
WHERE session_status = 'completed'
  AND settlement_time >= :start_ts AND settlement_time < :end_ts
  AND station_id = ANY(:allowed_station_ids);
```

### M11 `cost_per_kwh`

```sql
WITH volume AS (
  SELECT COALESCE(SUM(energy_kwh), 0) AS value
  FROM fact_charging_session
  WHERE session_status = 'completed'
    AND settlement_time >= :start_ts AND settlement_time < :end_ts
    AND station_id = ANY(:allowed_station_ids)
), costs AS (
  SELECT
    (SELECT COALESCE(SUM(energy_cost), 0)
     FROM fact_energy_cost
     WHERE cost_date >= :start_date AND cost_date < :end_date
       AND station_id = ANY(:allowed_station_ids))
    +
    (SELECT COALESCE(SUM(amount), 0)
     FROM fact_operation_expense
     WHERE is_variable = TRUE
       AND expense_date >= :start_date AND expense_date < :end_date
       AND station_id = ANY(:allowed_station_ids)) AS value
)
SELECT costs.value / NULLIF(volume.value, 0) AS cost_per_kwh
FROM costs CROSS JOIN volume;
```

### M12 `station_utilization_rate`

```sql
WITH charging AS (
  SELECT COALESCE(SUM(charging_duration_seconds), 0) AS seconds
  FROM fact_charging_session
  WHERE session_status = 'completed'
    AND settlement_time >= :start_ts AND settlement_time < :end_ts
    AND station_id = ANY(:allowed_station_ids)
), available AS (
  SELECT COALESCE(SUM(
    EXTRACT(EPOCH FROM LEAST(e.end_time, :end_ts) - GREATEST(e.start_time, :start_ts))
    * d.connector_count
  ), 0) AS seconds
  FROM fact_device_status_event e
  JOIN dim_device d ON d.device_id = e.device_id
  WHERE e.status = 'online'
    AND e.end_time > :start_ts AND e.start_time < :end_ts
    AND e.station_id = ANY(:allowed_station_ids)
)
SELECT charging.seconds / NULLIF(available.seconds, 0) AS station_utilization_rate
FROM charging CROSS JOIN available;
```

### M13 `device_online_rate`

```sql
WITH durations AS (
  SELECT status,
         SUM(EXTRACT(EPOCH FROM LEAST(end_time, :end_ts) - GREATEST(start_time, :start_ts))) AS seconds
  FROM fact_device_status_event
  WHERE status <> 'unknown'
    AND end_time > :start_ts AND start_time < :end_ts
    AND station_id = ANY(:allowed_station_ids)
  GROUP BY status
)
SELECT COALESCE(SUM(seconds) FILTER (WHERE status = 'online'), 0)
       / NULLIF(SUM(seconds), 0) AS device_online_rate
FROM durations;
```

### M14 `device_fault_rate`

```sql
WITH durations AS (
  SELECT status,
         SUM(EXTRACT(EPOCH FROM LEAST(end_time, :end_ts) - GREATEST(start_time, :start_ts))) AS seconds
  FROM fact_device_status_event
  WHERE status <> 'unknown'
    AND end_time > :start_ts AND start_time < :end_ts
    AND station_id = ANY(:allowed_station_ids)
  GROUP BY status
)
SELECT COALESCE(SUM(seconds) FILTER (WHERE status = 'fault'), 0)
       / NULLIF(SUM(seconds), 0) AS device_fault_rate
FROM durations;
```

### M15 `active_user_count`

```sql
SELECT COUNT(DISTINCT user_id) AS active_user_count
FROM fact_charging_session
WHERE session_status = 'completed'
  AND settlement_time >= :start_ts AND settlement_time < :end_ts
  AND station_id = ANY(:allowed_station_ids);
```

## 4. 单元测试基准

统一正常 fixture `METRIC_FIXTURE_A`：

- 完成会话 S1：电费净额 80、服务费净额 20、电量 50 kWh、充电 3,600 秒、用户 U1；
- 完成会话 S2：电费净额 45、服务费净额 5、电量 25 kWh、充电 1,800 秒、用户 U2；
- 取消会话 S3：任何值均不得进入指标；
- 电费成本合计 90 元；
- 可变运营成本合计 15 元；
- 可用枪口时长 10,800 秒；
- 设备可观测时长 14,400 秒，其中在线 10,800 秒、故障 3,600 秒。

| test_id | 指标 | 预期结果 | 边界测试 |
|---|---|---:|---|
| UT-M01 | charging_revenue | 150.00 | 无完成会话且覆盖完整时为 0；覆盖缺失为 NULL |
| UT-M02 | service_fee_revenue | 25.00 | 取消会话不计入 |
| UT-M03 | completed_order_count | 2 | 重复 session_id 触发数据质量失败 |
| UT-M04 | charging_volume_kwh | 75.0000 | 负电量被数据质量阻断 |
| UT-M05 | energy_cost | 90.00 | 电价×电量差异超过 0.01 元阻断 |
| UT-M06 | variable_operating_cost | 15.00 | `is_variable=false` 不计入 |
| UT-M07 | gross_profit | 45.00 | 成本可大于收入并返回负毛利 |
| UT-M08 | gross_margin | 0.300000 | 收入为 0 时返回 NULL |
| UT-M09 | avg_order_energy_kwh | 37.5000 | 完成订单为 0 时返回 NULL |
| UT-M10 | revenue_per_kwh | 2.000000 | 充电量为 0 时返回 NULL |
| UT-M11 | cost_per_kwh | 1.400000 | 充电量为 0 时返回 NULL |
| UT-M12 | station_utilization_rate | 0.500000 | 可用枪口时长为 0 时返回 NULL；不得超过 1，超过则质量失败 |
| UT-M13 | device_online_rate | 0.750000 | 可观测时长为 0 时返回 NULL |
| UT-M14 | device_fault_rate | 0.250000 | 可观测时长为 0 时返回 NULL |
| UT-M15 | active_user_count | 2 | 同一用户多笔订单仍计 1；跨分组不可直接相加 |

## 5. 比较规则

- 环比：当前完整窗口与紧邻的等长前一窗口；自然月按完整自然月比较。
- 同比：与上一年相同自然日期范围比较；闰日采用显式日期映射并记录。
- 数据期末为 2026-06-30；超出数据范围的问题不得外推。
- 当前期或比较期数据不完整时，不计算同比/环比，返回数据不足与可用范围。
- 百分比变化：`(current - comparison) / NULLIF(comparison, 0)`；比较期为 0 时变化率为 NULL，但可展示绝对差额。

## 6. 权限与版本

所有 15 项均为经营聚合指标，不允许返回个人敏感字段。区域运营经理只能计算授权区域；管理层和分析师的范围以 RBAC 合同为准。指标公式、来源表或粒度变化必须生成新版本并更新固定评测集。

用户复购率明确进入 P1，不是 P0 指标。
