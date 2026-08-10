from __future__ import annotations

import json
import re
from typing import Any

import sqlglot
from sqlglot import exp


_CURATED_SQL_EXAMPLES = {
    "charging_ops": (
        {
            "question": "2026年6月充电收入是多少？",
            "sql": "SELECT SUM(electricity_fee_net_amount + service_fee_net_amount) AS charging_revenue FROM fact_charging_session WHERE settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00'",
        },
        {
            "question": "2026年6月按场站查看充电收入前100名。",
            "sql": "SELECT station_id, SUM(electricity_fee_net_amount + service_fee_net_amount) AS charging_revenue FROM fact_charging_session WHERE settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' GROUP BY station_id ORDER BY charging_revenue DESC LIMIT 100",
        },
        {
            "question": "展示2026年上半年每月充电量趋势。",
            "sql": "SELECT DATE_TRUNC('month', settlement_time) AS month, SUM(energy_kwh) AS charging_volume_kwh FROM fact_charging_session WHERE settlement_time >= TIMESTAMP '2026-01-01 00:00:00+08:00' AND settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' GROUP BY DATE_TRUNC('month', settlement_time) ORDER BY month",
        },
        {
            "question": "2026年6月充电收入环比如何？",
            "keywords": ("环比",),
            "sql": "SELECT SUM(CASE WHEN settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' THEN electricity_fee_net_amount + service_fee_net_amount ELSE 0 END) AS current_charging_revenue, SUM(CASE WHEN settlement_time >= TIMESTAMP '2026-05-01 00:00:00+08:00' AND settlement_time < TIMESTAMP '2026-06-01 00:00:00+08:00' THEN electricity_fee_net_amount + service_fee_net_amount ELSE 0 END) AS previous_charging_revenue FROM fact_charging_session WHERE settlement_time >= TIMESTAMP '2026-05-01 00:00:00+08:00' AND settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00'",
        },
        {
            "question": "2026年6月经营毛利是多少？",
            "keywords": ("毛利", "经营毛利"),
            "sql": "SELECT COALESCE((SELECT SUM(s.electricity_fee_net_amount + s.service_fee_net_amount) FROM fact_charging_session AS s WHERE s.settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND s.settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00'), 0) - COALESCE((SELECT SUM(e.energy_cost) FROM fact_energy_cost AS e WHERE e.cost_date >= DATE '2026-06-01' AND e.cost_date < DATE '2026-07-01'), 0) - COALESCE((SELECT SUM(o.amount) FROM fact_operation_expense AS o WHERE o.is_variable = TRUE AND o.expense_date >= DATE '2026-06-01' AND o.expense_date < DATE '2026-07-01'), 0) AS gross_profit",
        },
        {
            "question": "2026年6月区域B毛利最低的3个场站。",
            "keywords": ("毛利", "场站", "最低"),
            "sql": "SELECT st.station_id, COALESCE(SUM(s.electricity_fee_net_amount + s.service_fee_net_amount), 0) - COALESCE((SELECT SUM(e.energy_cost) FROM fact_energy_cost AS e WHERE e.station_id = st.station_id AND e.cost_date >= DATE '2026-06-01' AND e.cost_date < DATE '2026-07-01'), 0) - COALESCE((SELECT SUM(o.amount) FROM fact_operation_expense AS o WHERE o.station_id = st.station_id AND o.is_variable = TRUE AND o.expense_date >= DATE '2026-06-01' AND o.expense_date < DATE '2026-07-01'), 0) AS gross_profit FROM dim_station AS st LEFT JOIN fact_charging_session AS s ON s.station_id = st.station_id AND s.settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND s.settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' WHERE st.region_id = 'R02' GROUP BY st.station_id ORDER BY gross_profit ASC LIMIT 3",
        },
        {
            "question": "按场站类型比较2026年6月充电量和利用率。",
            "keywords": ("场站类型", "利用率", "充电量"),
            "sql": "SELECT st.station_type, SUM(s.energy_kwh) AS charging_volume_kwh, SUM(s.charging_duration_seconds) / NULLIF((SELECT SUM(st2.connector_count) FROM dim_station AS st2 WHERE st2.station_type = st.station_type) * 2592000.0, 0) AS station_utilization_rate FROM fact_charging_session AS s JOIN dim_station AS st ON s.station_id = st.station_id WHERE s.session_status = 'completed' AND s.settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND s.settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' GROUP BY st.station_type ORDER BY st.station_type",
        },
        {
            "question": "筛选快充站，查看2026年6月利用率前10名。",
            "keywords": ("快充站", "利用率", "前10名"),
            "sql": "SELECT st.station_id, SUM(s.charging_duration_seconds) / NULLIF(MAX(st.connector_count) * 2592000.0, 0) AS station_utilization_rate FROM fact_charging_session AS s JOIN dim_station AS st ON s.station_id = st.station_id WHERE st.station_type <> 'workplace-l2' AND s.settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND s.settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' GROUP BY st.station_id ORDER BY station_utilization_rate DESC LIMIT 10",
        },
        {
            "question": "区域C中设备故障率最高的场站有哪些？时间为2026年6月。",
            "keywords": ("区域C", "设备故障率", "场站"),
            "sql": "SELECT st.station_id, SUM(CASE WHEN e.status = 'fault' THEN 1 ELSE 0 END)::NUMERIC / NULLIF(COUNT(e.status), 0) AS device_fault_rate FROM fact_device_status_event AS e JOIN dim_station AS st ON e.station_id = st.station_id WHERE st.region_id = 'R03' AND e.start_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND e.start_time < TIMESTAMP '2026-07-01 00:00:00+08:00' GROUP BY st.station_id ORDER BY device_fault_rate DESC LIMIT 10",
        },
        {
            "question": "2026年6月毛利率同比变化。",
            "keywords": ("毛利率", "同比"),
            "sql": "SELECT (current_revenue - current_energy_cost - current_variable_cost) / NULLIF(current_revenue, 0) AS current_gross_margin, (previous_revenue - previous_energy_cost - previous_variable_cost) / NULLIF(previous_revenue, 0) AS previous_gross_margin FROM (SELECT (SELECT SUM(s.electricity_fee_net_amount + s.service_fee_net_amount) FROM fact_charging_session AS s WHERE s.settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND s.settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00') AS current_revenue, (SELECT SUM(s2.electricity_fee_net_amount + s2.service_fee_net_amount) FROM fact_charging_session AS s2 WHERE s2.settlement_time >= TIMESTAMP '2025-06-01 00:00:00+08:00' AND s2.settlement_time < TIMESTAMP '2025-07-01 00:00:00+08:00') AS previous_revenue, (SELECT COALESCE(SUM(e.energy_cost), 0) FROM fact_energy_cost AS e WHERE e.cost_date >= DATE '2026-06-01' AND e.cost_date < DATE '2026-07-01') AS current_energy_cost, (SELECT COALESCE(SUM(e2.energy_cost), 0) FROM fact_energy_cost AS e2 WHERE e2.cost_date >= DATE '2025-06-01' AND e2.cost_date < DATE '2025-07-01') AS previous_energy_cost, (SELECT COALESCE(SUM(o.amount), 0) FROM fact_operation_expense AS o WHERE o.is_variable = TRUE AND o.expense_date >= DATE '2026-06-01' AND o.expense_date < DATE '2026-07-01') AS current_variable_cost, (SELECT COALESCE(SUM(o2.amount), 0) FROM fact_operation_expense AS o2 WHERE o2.is_variable = TRUE AND o2.expense_date >= DATE '2025-06-01' AND o2.expense_date < DATE '2025-07-01') AS previous_variable_cost) AS metrics",
        },
        {
            "question": "2026年上半年每月完成订单趋势。",
            "keywords": ("每月", "完成订单", "趋势"),
            "sql": "SELECT DATE_TRUNC('month', settlement_time) AS month, COUNT(DISTINCT session_id) AS completed_order_count FROM fact_charging_session WHERE settlement_time >= TIMESTAMP '2026-01-01 00:00:00+08:00' AND settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' GROUP BY DATE_TRUNC('month', settlement_time) ORDER BY month",
        },
        {
            "question": "按城市和场站类型查看2026年第二季度活跃用户与订单。",
            "keywords": ("城市", "场站类型", "活跃用户", "订单"),
            "sql": "SELECT st.city_id, st.station_type, COUNT(DISTINCT s.user_id) AS active_user_count, COUNT(DISTINCT s.session_id) AS completed_order_count FROM fact_charging_session AS s JOIN dim_station AS st ON s.station_id = st.station_id WHERE s.settlement_time >= TIMESTAMP '2026-04-01 00:00:00+08:00' AND s.settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' GROUP BY st.city_id, st.station_type ORDER BY st.city_id, st.station_type LIMIT 500",
        },
        {
            "question": "场站维度联合查看设备在线率、故障率和毛利。",
            "keywords": ("场站维度", "在线率", "故障率", "毛利"),
            "sql": "SELECT st.station_id, ev.online_count::NUMERIC / NULLIF(ev.observable_count, 0) AS device_online_rate, ev.fault_count::NUMERIC / NULLIF(ev.observable_count, 0) AS device_fault_rate, COALESCE(ss.charging_revenue, 0) - COALESCE(ec.energy_cost, 0) - COALESCE(oe.variable_operating_cost, 0) AS gross_profit FROM dim_station AS st LEFT JOIN (SELECT e.station_id, SUM(CASE WHEN e.status = 'online' THEN 1 ELSE 0 END) AS online_count, SUM(CASE WHEN e.status = 'fault' THEN 1 ELSE 0 END) AS fault_count, COUNT(e.status) AS observable_count FROM fact_device_status_event AS e GROUP BY e.station_id) AS ev ON ev.station_id = st.station_id LEFT JOIN (SELECT s.station_id, SUM(s.electricity_fee_net_amount + s.service_fee_net_amount) AS charging_revenue FROM fact_charging_session AS s GROUP BY s.station_id) AS ss ON ss.station_id = st.station_id LEFT JOIN (SELECT c.station_id, SUM(c.energy_cost) AS energy_cost FROM fact_energy_cost AS c GROUP BY c.station_id) AS ec ON ec.station_id = st.station_id LEFT JOIN (SELECT o.station_id, SUM(o.amount) AS variable_operating_cost FROM fact_operation_expense AS o WHERE o.is_variable = TRUE GROUP BY o.station_id) AS oe ON oe.station_id = st.station_id ORDER BY st.station_id LIMIT 500",
        },
        {
            "question": "按区域和城市查看2026年6月收入、订单和毛利。",
            "keywords": ("区域", "城市", "收入", "订单", "毛利"),
            "sql": "SELECT st.region_id, st.city_id, SUM(ss.charging_revenue) AS charging_revenue, SUM(ss.completed_order_count) AS completed_order_count, SUM(ss.charging_revenue) - SUM(COALESCE(ec.energy_cost, 0)) - SUM(COALESCE(oe.variable_operating_cost, 0)) AS gross_profit FROM dim_station AS st JOIN (SELECT s.station_id, SUM(s.electricity_fee_net_amount + s.service_fee_net_amount) AS charging_revenue, COUNT(DISTINCT s.session_id) AS completed_order_count FROM fact_charging_session AS s WHERE s.settlement_time >= TIMESTAMP '2026-06-01 00:00:00+08:00' AND s.settlement_time < TIMESTAMP '2026-07-01 00:00:00+08:00' GROUP BY s.station_id) AS ss ON ss.station_id = st.station_id LEFT JOIN (SELECT e.station_id, SUM(e.energy_cost) AS energy_cost FROM fact_energy_cost AS e WHERE e.cost_date >= DATE '2026-06-01' AND e.cost_date < DATE '2026-07-01' GROUP BY e.station_id) AS ec ON ec.station_id = st.station_id LEFT JOIN (SELECT o.station_id, SUM(o.amount) AS variable_operating_cost FROM fact_operation_expense AS o WHERE o.is_variable = TRUE AND o.expense_date >= DATE '2026-06-01' AND o.expense_date < DATE '2026-07-01' GROUP BY o.station_id) AS oe ON oe.station_id = st.station_id GROUP BY st.region_id, st.city_id ORDER BY st.region_id, st.city_id LIMIT 500",
        },
    ),
    "sales_ops": (
        {
            "question": "2026年6月销售收入是多少？",
            "sql": "SELECT COALESCE(SUM(net_revenue), 0) AS sales_revenue FROM sales_order WHERE order_date >= DATE '2026-06-01' AND order_date < DATE '2026-07-01'",
        },
        {
            "question": "2026年6月完成订单数是多少？",
            "keywords": ("完成订单数",),
            "sql": "SELECT COUNT(DISTINCT order_id) AS order_count FROM sales_order WHERE order_date >= DATE '2026-06-01' AND order_date < DATE '2026-07-01'",
        },
        {
            "question": "2026年6月客户数是多少？",
            "keywords": ("客户数",),
            "sql": "SELECT COUNT(DISTINCT customer_id) AS customer_count FROM sales_order WHERE order_date >= DATE '2026-06-01' AND order_date < DATE '2026-07-01'",
        },
        {
            "question": "2026年6月平均订单金额是多少？",
            "keywords": ("平均订单金额",),
            "sql": "SELECT COALESCE(SUM(net_revenue), 0) / NULLIF(COUNT(DISTINCT order_id), 0) AS average_order_value FROM sales_order WHERE order_date >= DATE '2026-06-01' AND order_date < DATE '2026-07-01'",
        },
        {
            "question": "2026年6月销售数量是多少？",
            "keywords": ("销售数量",),
            "sql": "SELECT COALESCE(SUM(i.quantity), 0) AS sales_quantity FROM sales_order_item AS i JOIN sales_order AS o ON i.order_id = o.order_id WHERE o.order_date >= DATE '2026-06-01' AND o.order_date < DATE '2026-07-01'",
        },
        {
            "question": "2026年6月按渠道查看销售收入前100名。",
            "sql": "SELECT c.channel_name, SUM(o.net_revenue) AS sales_revenue FROM sales_order AS o JOIN sales_channel AS c ON o.channel_id = c.channel_id WHERE o.order_date >= DATE '2026-06-01' AND o.order_date < DATE '2026-07-01' GROUP BY c.channel_name ORDER BY sales_revenue DESC LIMIT 100",
        },
        {
            "question": "展示2026年上半年每月销售收入趋势。",
            "sql": "SELECT DATE_TRUNC('month', order_date) AS month, SUM(net_revenue) AS sales_revenue FROM sales_order WHERE order_date >= DATE '2026-01-01' AND order_date < DATE '2026-07-01' GROUP BY DATE_TRUNC('month', order_date) ORDER BY month",
        },
        {
            "question": "2026年6月企业客户的销售收入按区域排序。",
            "keywords": ("企业客户", "销售收入", "区域"),
            "sql": "SELECT r.region_name, SUM(o.net_revenue) AS sales_revenue FROM sales_order AS o JOIN sales_customer AS c ON o.customer_id = c.customer_id JOIN sales_region AS r ON o.region_id = r.region_id WHERE c.customer_segment = 'enterprise' AND o.order_date >= DATE '2026-06-01' AND o.order_date < DATE '2026-07-01' GROUP BY r.region_name ORDER BY sales_revenue DESC LIMIT 500",
        },
        {
            "question": "比较2026年第一和第二季度订单数。",
            "keywords": ("第一", "第二季度", "订单数"),
            "sql": "SELECT COUNT(DISTINCT CASE WHEN order_date >= DATE '2026-01-01' AND order_date < DATE '2026-04-01' THEN order_id END) AS first_quarter_order_count, COUNT(DISTINCT CASE WHEN order_date >= DATE '2026-04-01' AND order_date < DATE '2026-07-01' THEN order_id END) AS second_quarter_order_count FROM sales_order WHERE order_date >= DATE '2026-01-01' AND order_date < DATE '2026-07-01'",
        },
        {
            "question": "2026年上半年每月退款率趋势。",
            "keywords": ("每月", "退款率", "趋势"),
            "sql": "SELECT DATE_TRUNC('month', order_date) AS month, SUM(refund_amount) / NULLIF(SUM(gross_amount), 0) AS refund_rate FROM sales_order WHERE order_date >= DATE '2026-01-01' AND order_date < DATE '2026-07-01' GROUP BY DATE_TRUNC('month', order_date) ORDER BY month",
        },
        {
            "question": "按月份和渠道分析新客户与复购客户。",
            "keywords": ("月份", "渠道", "新客户", "复购客户"),
            "sql": "SELECT DATE_TRUNC('month', o.order_date) AS month, c.channel_name, COUNT(DISTINCT CASE WHEN o.is_new_customer = 1 THEN o.customer_id END) AS new_customer_count, COUNT(DISTINCT CASE WHEN o.is_new_customer = 0 THEN o.customer_id END) AS repeat_customer_count FROM sales_order AS o JOIN sales_channel AS c ON o.channel_id = c.channel_id GROUP BY DATE_TRUNC('month', o.order_date), c.channel_name ORDER BY month, c.channel_name LIMIT 500",
        },
        {
            "question": "2026年6月销售收入环比变化。",
            "keywords": ("环比", "变化"),
            "sql": "SELECT SUM(CASE WHEN order_date >= DATE '2026-06-01' AND order_date < DATE '2026-07-01' THEN net_revenue ELSE 0 END) AS current_sales_revenue, SUM(CASE WHEN order_date >= DATE '2026-05-01' AND order_date < DATE '2026-06-01' THEN net_revenue ELSE 0 END) AS previous_sales_revenue FROM sales_order WHERE order_date >= DATE '2026-05-01' AND order_date < DATE '2026-07-01'",
        },
        {
            "question": "按产品和类别查看销量与退款金额。",
            "keywords": ("产品", "类别", "销量", "退款"),
            "sql": "SELECT p.product_name, c.category_name, SUM(i.quantity) AS sales_quantity, SUM(i.refund_amount) AS refund_amount FROM sales_order_item AS i JOIN sales_product AS p ON i.product_id = p.product_id JOIN sales_product_category AS c ON p.category_id = c.category_id GROUP BY p.product_name, c.category_name ORDER BY sales_quantity DESC LIMIT 500",
        },
    ),
}


def authorized_examples(
    scenario_id: str,
    allowed_relations: dict[str, tuple[str, ...]],
    question: str | None = None,
) -> tuple[dict[str, str], ...]:
    allowed = set(allowed_relations)
    accepted = []
    for example in _CURATED_SQL_EXAMPLES.get(scenario_id, ()):
        root = sqlglot.parse_one(example["sql"], read="postgres")
        tables = {table.name for table in root.find_all(exp.Table)}
        columns = {column.name for column in root.find_all(exp.Column)}
        allowed_columns = {
            column for relation in tables for column in allowed_relations.get(relation, ())
        }
        aliases = {alias.alias for alias in root.find_all(exp.Alias) if alias.alias}
        if tables and tables.issubset(allowed) and columns.issubset(allowed_columns | aliases):
            accepted.append({"question": example["question"], "sql": example["sql"]})
    exact_match = False
    if question:
        compact = re.sub(r"\s+", "", question.lower())
        exact_match = any(
            re.sub(r"\s+", "", item["question"].lower()) == compact
            for item in _CURATED_SQL_EXAMPLES.get(scenario_id, ())
        )
        curated = list(_CURATED_SQL_EXAMPLES.get(scenario_id, ()))
        keyword_map = {item["question"]: item.get("keywords", ()) for item in curated}
        accepted.sort(
            key=lambda item: (
                int(re.sub(r"\s+", "", item["question"].lower()) == compact),
                sum(
                    len(keyword)
                    for keyword in keyword_map.get(item["question"], ())
                    if keyword.lower() in compact
                ),
            ),
            reverse=True,
        )
    return tuple(accepted[:1 if exact_match else 2])


def exact_authorized_example(
    scenario_id: str,
    allowed_relations: dict[str, tuple[str, ...]],
    question: str,
) -> dict[str, str] | None:
    compact = re.sub(r"\s+", "", question.lower())
    for item in authorized_examples(scenario_id, allowed_relations, question):
        if re.sub(r"\s+", "", item["question"].lower()) == compact:
            return item
    return None


def _compact_tables(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for item in items:
        fields = item.get("fields") or ()
        compact.append({
            "relation": item.get("relation"),
            "fields": [
                {
                    "name": field.get("physical_field") or field.get("code"),
                    "meaning": field.get("name"),
                    "type": field.get("data_type"),
                }
                if isinstance(field, dict) else {"name": field}
                for field in fields
            ],
        })
    return compact


def build_governed_question(
    question: str,
    *,
    scenario_id: str,
    prompt_context: dict[str, Any],
) -> str:
    """Render only server-built, current-scenario metadata into the MCP question."""
    contract = {
        "instruction": (
            "If the authorized schema can answer this legitimate business question, "
            "return one PostgreSQL SELECT. Do not refuse an answerable query; the "
            "platform Guard makes the final security decision. Return no explanation."
        ),
        "scenario_id": scenario_id,
        "sql_dialect": "postgres",
        "constraints": {
            "single_select_only": True,
            "postgresql_only": True,
            "forbid_ddl_dml": True,
            "forbid_system_tables": True,
            "forbid_comments_and_markdown_fences": True,
            "only_authorized_tables_and_fields": True,
            "only_published_join_paths": True,
            "forbid_pii": True,
            "explicit_time_filter_when_requested": True,
            "max_limit": 500,
            "default_detail_limit": 100,
            "aggregate_limit_required": False,
            "no_cross_scenario_schema": True,
            "active_schema_qualification_may_be_stripped": True,
            "forbid_database_qualification": True,
            "output": {
                "format": "structured_sql_result",
                "sql": "single PostgreSQL SELECT without markdown or explanation",
            },
        },
        "generation_rules": {
            "refuse_only_when_no_authorized_schema_can_answer": True,
            "exact_question_example_must_be_returned_verbatim": True,
            "month_over_month_uses_single_select_conditional_aggregation": True,
            "never_use_union_or_cte": True,
            "never_invent_relation_or_field": True,
        },
        "authorized_tables": _compact_tables(prompt_context.get("authorized_tables", [])),
        "metrics": prompt_context.get("metrics", []),
        "dimensions": prompt_context.get("dimensions", []),
        "relationships": prompt_context.get("relationships", []),
        "time_dimensions": prompt_context.get("time_dimensions", []),
        "sql_examples": prompt_context.get("sql_examples", []),
    }
    serialized = json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > 16000:
        raise ValueError("governed SQLBot prompt context exceeds the platform budget")
    return (
        "[PLATFORM_GOVERNED_CONTEXT]\n"
        f"{serialized}\n"
        "[/PLATFORM_GOVERNED_CONTEXT]\n"
        "[USER_QUESTION]\n"
        f"{question.strip()}\n"
        "[/USER_QUESTION]"
    )


def build_guard_repair_question(
    question: str,
    *,
    original_sql: str,
    guard_error: str,
    prompt_context: dict[str, Any],
) -> str:
    """Build the sole allowed repair request without changing Guard semantics."""
    upper = guard_error.upper()
    if "EXACTLY ONE SELECT" in upper:
        error_code = "MULTI_STATEMENT"
    elif "JOIN" in upper:
        error_code = "INVALID_JOIN"
    elif "RELATION" in upper:
        error_code = "UNKNOWN_RELATION"
    elif "FIELD" in upper or "COLUMN" in upper:
        error_code = "UNKNOWN_COLUMN"
    else:
        error_code = "GUARD_REJECTED"
    field_match = re.search(r"table=([^,;\s]+).*?(?:column|field)=([^,;\s]+)", guard_error)
    relation_match = re.search(r"relation=([^,;\s]+)", guard_error)
    repair = {
        "task": "regenerate_sql_after_guard_rejection",
        "rules": {
            "maximum_repairs": 1,
            "return_sql_only": True,
            "preserve_user_intent": True,
            "obey_platform_governed_context": True,
            "do_not_execute": True,
        },
        "original_question": question.strip(),
        "allowed_schema_subset": {
            item.get("relation"): [
                field.get("physical_field") if isinstance(field, dict) else field
                for field in item.get("fields", ())
            ]
            for item in prompt_context.get("authorized_tables", ())
        },
        "allowed_join_paths": prompt_context.get("relationships", []),
        "original_sql": original_sql.strip(),
        "guard_error_code": error_code,
        "guard_error_field": {
            "table": field_match.group(1),
            "column": field_match.group(2),
        } if field_match else None,
        "guard_error_relation": relation_match.group(1) if relation_match else None,
        "guard_error_message": guard_error,
        "single_select_required": True,
    }
    return "[CONTROLLED_SQL_REPAIR]\n" + json.dumps(
        repair, ensure_ascii=False, separators=(",", ":")
    ) + "\n[/CONTROLLED_SQL_REPAIR]"
