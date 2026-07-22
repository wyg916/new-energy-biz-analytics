# 数据合同 v0.1

> 状态：Phase 0.1 开发输入基线
> 数据类型：固定随机种子、业务规则驱动的模拟数据
> 时间范围：2025-01-01 00:00:00 至 2026-06-30 23:59:59，业务时区 `Asia/Shanghai`
> 非目标：本合同不创建数据库、迁移、数据生成器或真实数据接入。

## 1. 数据规模与来源标签

| 对象 | 目标规模 | 约束 |
|---|---:|---|
| 区域 | 3 | 固定编码，不与真实企业组织对应 |
| 城市 | 6 | 每个区域 2 个城市 |
| 场站 | 30 | 每个城市 5 个场站 |
| 设备 | 约 120 | 每站约 4 台，设备属于且只属于一个场站 |
| 模拟用户 | 约 10,000 | 使用不可逆模拟 ID，不生成真实姓名、手机号或支付信息 |
| 充电会话 | 约 300,000 | 仅完成会话进入核心指标；失败/取消会话用于质量和状态测试 |

所有数据批次必须包含：

- `source_type = simulated`；
- `generator_version`；
- `random_seed`；
- `generated_at`；
- `data_period_start` / `data_period_end`；
- 唯一 `batch_id` 和数据质量结果。

默认随机种子冻结为 `20260722`。修改种子或生成规则必须产生新批次和新版本，不得覆盖旧批次证据。

## 2. 通用字段规则

- 主键使用 UUID 或稳定字符串 ID；相同 seed 和生成器版本必须产生相同业务主键。
- 所有时间戳存储为带时区时间，业务展示统一为 `Asia/Shanghai`。
- 日期字段使用 ISO `YYYY-MM-DD`。
- 金额使用 `NUMERIC(18,2)`，单位人民币元；费率和中间计算建议保留至少 6 位小数。
- 电量使用 `NUMERIC(18,4)`，单位 kWh；时长使用整数秒。
- 布尔字段不得以空值代替未知；未知状态使用显式枚举。
- 事实表包含 `batch_id`、`source_type`、`created_at`。
- 软删除对象包含 `status` 或 `is_active`，不得物理覆盖历史事实。

## 3. 维度表

### 3.1 `dim_region`

粒度：一个模拟经营区域。主键：`region_id`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| region_id | VARCHAR(32) | 是 | 稳定区域编码 |
| region_name | VARCHAR(64) | 是 | 模拟名称，如区域 A |
| display_order | SMALLINT | 是 | 展示顺序 |
| status | VARCHAR(16) | 是 | `active` / `inactive` |
| source_type | VARCHAR(16) | 是 | 固定为 `simulated` |

### 3.2 `dim_city`

粒度：一个模拟城市。主键：`city_id`。外键：`region_id -> dim_region.region_id`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| city_id | VARCHAR(32) | 是 | 稳定城市编码 |
| city_name | VARCHAR(64) | 是 | 模拟名称 |
| region_id | VARCHAR(32) | 是 | 所属区域 |
| status | VARCHAR(16) | 是 | `active` / `inactive` |
| source_type | VARCHAR(16) | 是 | `simulated` |

### 3.3 `dim_station`

粒度：一个充电场站。主键：`station_id`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| station_id | VARCHAR(32) | 是 | 稳定场站编码 |
| station_name | VARCHAR(128) | 是 | 模拟名称 |
| city_id | VARCHAR(32) | 是 | 所属城市 |
| region_id | VARCHAR(32) | 是 | 冗余区域键，必须与城市一致 |
| operator_code | VARCHAR(32) | 是 | 模拟运营主体编码 |
| station_type | VARCHAR(32) | 是 | `urban` / `highway` / `community` / `destination` |
| open_date | DATE | 是 | 投运日期，不晚于数据期 |
| connector_count | INTEGER | 是 | 可用枪口设计数量，>0 |
| rated_power_kw | NUMERIC(12,2) | 是 | 额定功率，>0 |
| status | VARCHAR(16) | 是 | `active` / `maintenance` / `closed` |
| source_type | VARCHAR(16) | 是 | `simulated` |

### 3.4 `dim_device`

粒度：一台充电设备。主键：`device_id`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| device_id | VARCHAR(32) | 是 | 稳定设备编码 |
| station_id | VARCHAR(32) | 是 | 所属场站 |
| device_model | VARCHAR(64) | 是 | 模拟型号 |
| connector_count | SMALLINT | 是 | 枪口数，>0 |
| rated_power_kw | NUMERIC(10,2) | 是 | 额定功率，>0 |
| commission_date | DATE | 是 | 投运日期 |
| status | VARCHAR(16) | 是 | `active` / `retired` |
| source_type | VARCHAR(16) | 是 | `simulated` |

设备的 `connector_count` 按场站汇总后必须等于 `dim_station.connector_count`。

### 3.5 `dim_user`

粒度：一个模拟用户。主键：`user_id`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| user_id | VARCHAR(40) | 是 | 不可反推真实身份的模拟 ID |
| register_date | DATE | 是 | 注册日期 |
| acquisition_channel | VARCHAR(32) | 是 | 模拟渠道 |
| user_segment | VARCHAR(32) | 是 | `new` / `regular` / `high_value` / `dormant` |
| home_region_id | VARCHAR(32) | 否 | 模拟常用区域 |
| status | VARCHAR(16) | 是 | `active` / `inactive` |
| source_type | VARCHAR(16) | 是 | `simulated` |

不得生成姓名、手机号、身份证、车牌、支付账号或精确位置。

### 3.6 `dim_date`

粒度：一个自然日。主键：`date_key`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| date_key | DATE | 是 | 2025-01-01 至 2026-06-30 连续日期 |
| year | SMALLINT | 是 | 年 |
| quarter | SMALLINT | 是 | 1—4 |
| month | SMALLINT | 是 | 1—12 |
| iso_week | SMALLINT | 是 | ISO 周 |
| day_of_week | SMALLINT | 是 | 1—7 |
| is_weekend | BOOLEAN | 是 | 是否周末 |
| is_holiday | BOOLEAN | 是 | 模拟节假日标识 |
| holiday_name | VARCHAR(64) | 否 | 节假日名称 |

## 4. 事实表

### 4.1 `fact_charging_session`

粒度：一次充电会话。主键：`session_id`。核心指标只统计 `session_status = completed` 的会话。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| session_id | VARCHAR(48) | 是 | 会话唯一标识 |
| station_id | VARCHAR(32) | 是 | 场站 |
| device_id | VARCHAR(32) | 是 | 设备 |
| connector_no | SMALLINT | 是 | 设备内枪口序号，>=1 |
| user_id | VARCHAR(40) | 是 | 模拟用户 |
| start_time | TIMESTAMPTZ | 是 | 会话开始 |
| end_time | TIMESTAMPTZ | 是 | 会话结束，不早于开始 |
| settlement_time | TIMESTAMPTZ | 否 | 完成会话必填 |
| charging_duration_seconds | INTEGER | 是 | 实际充电时长，>=0 且不超过会话时长 |
| energy_kwh | NUMERIC(18,4) | 是 | 完成会话 >0；失败/取消可为 0 |
| electricity_fee_net_amount | NUMERIC(18,2) | 是 | 电费实收净额，已扣优惠/退款 |
| service_fee_net_amount | NUMERIC(18,2) | 是 | 服务费实收净额，已扣优惠/退款 |
| session_status | VARCHAR(16) | 是 | `completed` / `failed` / `cancelled` |
| batch_id | VARCHAR(48) | 是 | 生成批次 |
| source_type | VARCHAR(16) | 是 | `simulated` |
| created_at | TIMESTAMPTZ | 是 | 记录生成时间 |

关键不变量：

- 完成会话收入 = `electricity_fee_net_amount + service_fee_net_amount`；
- 完成会话 `energy_kwh > 0`、`settlement_time IS NOT NULL`；
- `device_id` 必须属于 `station_id`；
- 同一设备同一枪口的会话时间不得重叠；
- 设备离线/故障区间内不得生成完成会话，边界缓冲不超过 5 分钟；
- 单会话电量不得超过额定功率 × 充电时长的合理上限（允许 5% 浮动）。

### 4.2 `fact_energy_cost`

粒度：场站—日期—电价时段。主键：`station_id + cost_date + tariff_period`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| station_id | VARCHAR(32) | 是 | 场站 |
| cost_date | DATE | 是 | 成本日期 |
| tariff_period | VARCHAR(16) | 是 | `valley` / `flat` / `peak` / `super_peak` |
| purchase_price_per_kwh | NUMERIC(12,6) | 是 | 采购电价，>=0 |
| settled_energy_kwh | NUMERIC(18,4) | 是 | 对应时段结算电量，>=0 |
| energy_cost | NUMERIC(18,2) | 是 | `purchase_price_per_kwh * settled_energy_kwh` 四舍五入到分 |
| batch_id | VARCHAR(48) | 是 | 生成批次 |
| source_type | VARCHAR(16) | 是 | `simulated` |

场站日 `settled_energy_kwh` 与完成会话日充电量允许存在 0—3% 的线损/结算差异；差异率必须可配置并写入生成元数据。

### 4.3 `fact_operation_expense`

粒度：场站—日期—费用类型。主键：`station_id + expense_date + expense_type`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| station_id | VARCHAR(32) | 是 | 场站 |
| expense_date | DATE | 是 | 费用归属日 |
| expense_type | VARCHAR(32) | 是 | `payment_fee` / `maintenance_variable` / `platform_variable` / `marketing_variable` |
| amount | NUMERIC(18,2) | 是 | 可变运营成本，>=0 |
| is_variable | BOOLEAN | 是 | P0 记录固定为 `true` |
| allocation_rule | VARCHAR(32) | 是 | `direct` / `by_energy` / `by_orders` |
| batch_id | VARCHAR(48) | 是 | 生成批次 |
| source_type | VARCHAR(16) | 是 | `simulated` |

P0 的 `variable_operating_cost` 只汇总 `is_variable = true`；租赁、折旧等固定成本不进入 P0 经营毛利。

### 4.4 `fact_device_status_event`

粒度：一台设备的一段连续状态区间。主键：`status_event_id`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| status_event_id | VARCHAR(48) | 是 | 事件标识 |
| device_id | VARCHAR(32) | 是 | 设备 |
| station_id | VARCHAR(32) | 是 | 冗余场站键，必须与设备一致 |
| status | VARCHAR(16) | 是 | `online` / `offline` / `fault` / `unknown` |
| start_time | TIMESTAMPTZ | 是 | 区间开始 |
| end_time | TIMESTAMPTZ | 是 | 区间结束，晚于开始 |
| reason_code | VARCHAR(32) | 否 | 模拟故障/离线原因 |
| is_planned | BOOLEAN | 是 | 是否计划停机 |
| batch_id | VARCHAR(48) | 是 | 生成批次 |
| source_type | VARCHAR(16) | 是 | `simulated` |

同一设备状态区间不得重叠。`observable_duration` 为查询窗口内所有非 `unknown` 区间时长；`online_duration` 为 `online` 区间；`fault_duration` 为 `fault` 区间。

## 5. 治理与运行表

### 5.1 `data_generation_run`

粒度：一次模拟数据生成运行。主键：`batch_id`。

必需字段：`batch_id`、`generator_version`、`random_seed`、`period_start`、`period_end`、`target_counts_json`、`actual_counts_json`、`scenario_flags_json`、`status`、`quality_status`、`started_at`、`finished_at`、`error_summary`。

### 5.2 `metric_definition`

粒度：一个指标版本。主键：`metric_id + version`。

必需字段：`metric_id`、`version`、`name_zh`、`definition`、`formula`、`unit`、`time_field`、`source_tables_json`、`dimensions_json`、`synonyms_json`、`null_rule`、`status`、`valid_from`、`valid_to`、`approved_by`、`approved_at`。

### 5.3 `analysis_run`

粒度：一次用户分析请求。主键：`run_id`。

必需字段：`run_id`、`request_id`、`conversation_id`、`user_id`、`role_id`、`allowed_region_ids`、`question`、`query_plan_json`、`query_plan_version`、`sql_hash`、`params_redacted_json`、`metric_versions_json`、`batch_id`、`status`、`row_count`、`duration_ms`、`result_digest`、`answer_digest`、`error_code`、`created_at`、`finished_at`。

`status` 只能为 `pending`、`running`、`succeeded`、`partial`、`failed`、`cancelled`。失败运行不得覆盖最近成功结果。

### 5.4 `session_state`

字段和生命周期以 `docs/memory_contract_v0.1.md` 为准。P0 不创建长期用户偏好或历史案例召回表。

## 6. 允许的维度与连接关系

```text
dim_region 1 -> N dim_city 1 -> N dim_station 1 -> N dim_device
dim_user   1 -> N fact_charging_session
dim_station 1 -> N fact_charging_session
dim_device  1 -> N fact_charging_session
dim_station 1 -> N fact_energy_cost
dim_station 1 -> N fact_operation_expense
dim_device  1 -> N fact_device_status_event
dim_date joins to fact dates only through explicit date fields
```

禁止 LLM 自由猜测 Join。所有事实表跨表计算必须先聚合到共同粒度（通常为场站—日期）再连接，防止会话与成本/费用表之间的多对多行数膨胀。

## 7. 模拟数据生成规则

生成器必须覆盖并可单独开关：

1. 日内峰谷、工作日/周末、月度和季节性；
2. 节假日的出行与城市差异；
3. 区域、城市、场站类型、功率和运营策略差异；
4. 设备离线、故障、修复和计划维护；
5. 分时采购电价与阶段性电价上涨；
6. 服务费策略调整；
7. 用户获取、活跃、沉默和区域偏好变化；
8. 至少 3 个收入下降金标案例；
9. 至少 3 个毛利下降金标案例；
10. 数据延迟、缺失、重复、越界和关系断裂等质量异常批次。

正常批次必须满足所有阻断规则；质量异常批次必须带显式 `scenario_id`，只进入隔离测试，不得被驾驶舱当作成功批次。

## 8. 数据质量规则

| 规则 ID | 类别 | 规则 | 级别 | 失败处理 |
|---|---|---|---|---|
| DQ-001 | 唯一性 | 所有主键唯一 | 阻断 | 批次失败 |
| DQ-002 | 完整性 | 完成会话关键字段完整 | 阻断 | 隔离记录并失败 |
| DQ-003 | 关系 | 所有事实外键存在 | 阻断 | 批次失败 |
| DQ-004 | 层级 | 城市/场站/设备层级一致 | 阻断 | 批次失败 |
| DQ-005 | 时间 | 结束不早于开始，均在数据期内 | 阻断 | 隔离记录 |
| DQ-006 | 范围 | 电量、金额、时长、价格非负且在配置范围 | 阻断/预警 | 按字段处理 |
| DQ-007 | 功率 | 会话电量不超过功率时长上限 5% | 预警 | 标记异常 |
| DQ-008 | 会话重叠 | 同设备枪口完成会话不重叠 | 阻断 | 批次失败 |
| DQ-009 | 状态重叠 | 同设备状态区间不重叠 | 阻断 | 批次失败 |
| DQ-010 | 状态一致 | 离线/故障区间无完成会话 | 阻断 | 批次失败 |
| DQ-011 | 收入 | 会话收入等于两项净额之和 | 阻断 | 批次失败 |
| DQ-012 | 成本 | 电费成本等于电价×结算电量，容差 0.01 元 | 阻断 | 批次失败 |
| DQ-013 | 汇总 | 设备→场站→城市→区域汇总一致 | 阻断 | 批次失败 |
| DQ-014 | 能量 | 场站日成本电量与会话电量差异为 0—3% | 预警/阻断 | 超 3% 阻断 |
| DQ-015 | 日期连续 | `dim_date` 日期连续无缺口 | 阻断 | 批次失败 |
| DQ-016 | 规模 | 实际规模在目标值 ±5% 内 | 预警 | 记录偏差 |
| DQ-017 | 分布 | 季节性/节假日/区域差异符合场景参数 | 预警 | 生成报告 |
| DQ-018 | 来源 | 全部记录标记 `simulated` 与同一合法批次 | 阻断 | 批次失败 |
| DQ-019 | 隐私 | 不含姓名、手机号、证件、车牌、支付账号 | 阻断 | 停止发布 |
| DQ-020 | 发布 | 只有 `quality_status=passed` 批次可供应用查询 | 阻断 | 保留最近成功批次 |

## 9. 验收样例

- 相同生成器版本和 seed 连续运行两次，主键集合、记录数和核心汇总完全一致；
- 任取 3 个区域、6 个城市和 30 个场站，逐级汇总的订单、充电量和收入一致；
- 构造设备故障 8 小时的场站，故障区间无完成会话，在线率/故障率与区间时长一致；
- 构造服务费下调案例，充电量稳定时 `service_fee_revenue` 和 `revenue_per_kwh` 按规则下降；
- 构造采购电价上涨案例，收入稳定时 `energy_cost` 上升、`gross_profit` 和 `gross_margin` 下降；
- 构造分母为 0 的场站日，所有比率指标返回 `NULL` 并标记数据不足。

## 10. 变更控制

字段删除、粒度变化、金额/时间精度变化、主键或 Join 变化属于破坏性变更，必须升级合同主/次版本并重新评审指标、Query Plan、权限、评测集和迁移影响。
