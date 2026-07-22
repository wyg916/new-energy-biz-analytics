# Query Plan 合同 v0.1

> 状态：Phase 0.1 开发输入基线
> 合同版本：`0.1.0`
> 原则：LLM 只能生成结构化计划或澄清请求，不能在 P0 输出可执行 SQL。

## 1. 处理路径

```text
问题 + 已授权会话状态 + 已发布语义元数据
-> 计划候选
-> JSON Schema 校验
-> 指标/维度/Join/过滤白名单校验
-> 权限校验
-> 澄清或 validated Query Plan
-> 确定性 SQL Compiler
-> Query Guard
```

任何校验失败都不得进入 SQL 编译。`confidence` 仅用于是否澄清，不能绕过规则。

## 2. JSON Schema

采用 JSON Schema Draft 2020-12。运行时应从本合同提取为独立版本化 Schema；本轮不创建运行时代码。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:energy-bi:query-plan:0.1.0",
  "title": "Energy Business Intelligence Query Plan",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "status", "intent", "metrics", "time_range", "filters", "dimensions", "analysis", "sort", "limit"],
  "properties": {
    "version": {"const": "0.1.0"},
    "status": {"enum": ["ready", "needs_clarification", "rejected"]},
    "intent": {
      "enum": [
        "metric_lookup", "trend", "comparison", "ranking",
        "diagnose_revenue_change", "diagnose_gross_profit_change",
        "anomaly_lookup", "metric_definition"
      ]
    },
    "metrics": {
      "type": "array",
      "minItems": 1,
      "maxItems": 5,
      "uniqueItems": true,
      "items": {
        "enum": [
          "charging_revenue", "service_fee_revenue", "completed_order_count",
          "charging_volume_kwh", "energy_cost", "variable_operating_cost",
          "gross_profit", "gross_margin", "avg_order_energy_kwh",
          "revenue_per_kwh", "cost_per_kwh", "station_utilization_rate",
          "device_online_rate", "device_fault_rate", "active_user_count"
        ]
      }
    },
    "dimensions": {
      "type": "array",
      "maxItems": 3,
      "uniqueItems": true,
      "items": {
        "enum": [
          "date", "week", "month", "quarter", "region", "city", "station",
          "station_type", "operator", "device", "user_segment", "expense_type"
        ]
      }
    },
    "time_range": {
      "oneOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["type", "start", "end_exclusive", "timezone", "grain"],
          "properties": {
            "type": {"const": "absolute"},
            "start": {"type": "string", "format": "date-time"},
            "end_exclusive": {"type": "string", "format": "date-time"},
            "timezone": {"const": "Asia/Shanghai"},
            "grain": {"enum": ["day", "week", "month", "quarter"]}
          }
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["type", "value", "timezone", "grain", "resolved_start", "resolved_end_exclusive"],
          "properties": {
            "type": {"const": "relative"},
            "value": {"enum": ["last_7_days", "last_30_days", "current_month", "previous_month", "current_quarter"]},
            "timezone": {"const": "Asia/Shanghai"},
            "grain": {"enum": ["day", "week", "month"]},
            "resolved_start": {"type": "string", "format": "date-time"},
            "resolved_end_exclusive": {"type": "string", "format": "date-time"}
          }
        }
      ]
    },
    "filters": {
      "type": "array",
      "maxItems": 10,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["field", "operator", "value"],
        "properties": {
          "field": {"enum": ["region", "city", "station", "station_type", "operator", "device", "user_segment", "expense_type"]},
          "operator": {"enum": ["eq", "in", "not_in"]},
          "value": {
            "oneOf": [
              {"type": "string", "minLength": 1, "maxLength": 128},
              {"type": "array", "minItems": 1, "maxItems": 50, "uniqueItems": true, "items": {"type": "string", "minLength": 1, "maxLength": 128}}
            ]
          }
        }
      }
    },
    "comparison": {
      "oneOf": [
        {"type": "null"},
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["type"],
          "properties": {
            "type": {"enum": ["previous_period", "mom", "yoy", "custom"]},
            "start": {"type": "string", "format": "date-time"},
            "end_exclusive": {"type": "string", "format": "date-time"}
          }
        }
      ]
    },
    "analysis": {
      "type": "array",
      "maxItems": 4,
      "uniqueItems": true,
      "items": {"enum": ["value", "trend", "comparison", "top_n", "bottom_n", "revenue_decomposition", "gross_profit_decomposition", "anomaly_context"]}
    },
    "sort": {
      "type": "array",
      "maxItems": 2,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["field", "direction"],
        "properties": {
          "field": {"type": "string", "minLength": 1, "maxLength": 64},
          "direction": {"enum": ["asc", "desc"]}
        }
      }
    },
    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    "clarification": {
      "oneOf": [
        {"type": "null"},
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["reason_code", "question", "options"],
          "properties": {
            "reason_code": {"enum": ["missing_metric", "ambiguous_metric", "missing_time", "ambiguous_scope", "unsupported_request", "out_of_data_range"]},
            "question": {"type": "string", "minLength": 1, "maxLength": 300},
            "options": {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 1, "maxLength": 128}}
          }
        }
      ]
    },
    "context_resolution": {
      "type": "object",
      "additionalProperties": false,
      "required": ["inherited_fields", "overridden_fields", "session_state_version"],
      "properties": {
        "inherited_fields": {"type": "array", "uniqueItems": true, "items": {"enum": ["metrics", "time_range", "region", "city", "station", "comparison", "dimensions", "analysis_object"]}},
        "overridden_fields": {"type": "array", "uniqueItems": true, "items": {"enum": ["metrics", "time_range", "region", "city", "station", "comparison", "dimensions", "analysis_object"]}},
        "session_state_version": {"type": "integer", "minimum": 0}
      }
    },
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  }
}
```

## 3. 语义校验规则

JSON Schema 通过后必须继续执行以下确定性校验：

1. `status=ready` 时 `clarification` 必须为 `null`；`status=needs_clarification` 时不得执行 SQL。
2. `end_exclusive` 必须晚于 `start`，并且解析后的窗口不得超出 2025-01-01 至 2026-07-01 的左闭右开数据范围。
3. `comparison.type=custom` 必须同时提供 `start` 和 `end_exclusive`；其他比较类型由系统解析，LLM 不得自造日期。
4. `ranking` 必须至少有一个业务维度、一个排序字段和 `top_n`/`bottom_n`；默认 `limit=10`。
5. 排序字段只能引用请求中的指标或系统生成的 `absolute_change`、`change_rate`、`contribution`。
6. `diagnose_revenue_change` 必须包含 `charging_revenue`，允许分析 `revenue_decomposition`，因子限定为订单量、单均电量、度电收入和残差。
7. `diagnose_gross_profit_change` 必须包含 `gross_profit`，因子限定为收入、电费成本、可变运营成本和残差。
8. `active_user_count` 跨日期/场站分组后不得通过客户端加总获得总活跃用户数。
9. 指标与维度兼容性以指标字典为准；不兼容时返回 `PLAN_422` 和可用维度。
10. 过滤值必须先解析为授权维度 ID；自然语言名称不能直接拼入 SQL。
11. 权限强制过滤不由 LLM 表达，也不能被用户过滤覆盖；最终有效范围为用户请求与授权范围的交集。
12. 原始 SQL、表名、字段名、函数名和数据库关键字不得出现在 Query Plan 可执行字段中。

## 4. 意图与结果类型

| intent | 必需内容 | 默认结果 | 不支持时行为 |
|---|---|---|---|
| metric_lookup | 指标、时间 | KPI/小表 | 缺指标或时间时澄清 |
| trend | 指标、时间、日期粒度 | 趋势序列 | 窗口过短时改用 KPI/比较 |
| comparison | 指标、时间、comparison | 当前/比较/差额 | 比较期不可用时数据不足 |
| ranking | 指标、实体维度、排序、limit | Top/Bottom 表 | 无实体维度时澄清 |
| diagnose_revenue_change | 收入、比较、拆解 | 贡献、对象、残差 | 数据不完整时降级为比较 |
| diagnose_gross_profit_change | 毛利、比较、拆解 | 收入/成本贡献 | 成本数据缺失时拒绝诊断 |
| anomaly_lookup | 指标/异常类型、时间 | 异常清单 | 无规则版本时拒绝 |
| metric_definition | 指标 | 口径说明 | 不执行经营 SQL |

## 5. 多轮继承与覆盖

P0 只使用同一会话内的结构化状态。

优先级：

```text
本轮明确指令
> 本轮已解析实体/时间
> 当前会话状态
> 系统默认值
```

规则：

- 可继承：指标、时间、区域、城市、站点、比较方式、维度和分析对象；
- 本轮明确出现的新值覆盖旧值，并记录在 `overridden_fields`；
- “其中”“这些站点”“继续下钻”等指代只有唯一可解析对象时才能继承，否则澄清；
- 增加维度不会自动删除已有过滤，例如从区域下钻场站仍保留区域范围；
- 新会话的 `session_state_version=0`，不得继承上一会话临时状态；
- 用户不能通过上下文继承扩大授权范围；
- 会话状态过期、版本冲突或来源运行不可用时，不继承并提示用户重新确认；
- P0 不读取长期偏好、历史案例或纠错记忆。

## 6. 澄清规则

必须澄清而不是猜测：

- “收入”在问题上下文中无法确定是充电收入还是服务费收入；
- “最近”“经营怎么样”缺少可安全解析的时间或指标；
- 同名场站/城市存在多个授权候选；
- 请求时间超出模拟数据范围；
- 诊断请求缺少比较基准；
- 请求指标或维度不在 P0 白名单；
- 用户同时给出互相冲突的时间、区域或排序条件。

澄清响应不得包含 SQL，也不得创建 `analysis_run` 的执行阶段；可记录 `clarification_requested` 审计事件。

## 7. 示例

问题：“2026 年 6 月区域 A 毛利率环比如何？”

```json
{
  "version": "0.1.0",
  "status": "ready",
  "intent": "comparison",
  "metrics": ["gross_margin"],
  "dimensions": [],
  "time_range": {
    "type": "absolute",
    "start": "2026-06-01T00:00:00+08:00",
    "end_exclusive": "2026-07-01T00:00:00+08:00",
    "timezone": "Asia/Shanghai",
    "grain": "month"
  },
  "filters": [{"field": "region", "operator": "eq", "value": "区域A"}],
  "comparison": {"type": "mom"},
  "analysis": ["value", "comparison"],
  "sort": [],
  "limit": 10,
  "clarification": null,
  "context_resolution": {"inherited_fields": [], "overridden_fields": [], "session_state_version": 0},
  "confidence": 0.98
}
```

## 8. 版本与兼容

- Patch：仅说明或非结构性约束修正；
- Minor：新增可选字段、意图、指标或维度；
- Major：删除/重命名字段、改变语义或默认行为。

Compiler、Guard、评测集和审计必须记录 Query Plan 版本。未知主/次版本一律 fail-closed。
