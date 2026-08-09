from __future__ import annotations

import json
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
    ),
    "sales_ops": (
        {
            "question": "2026年6月销售收入是多少？",
            "sql": "SELECT SUM(net_revenue) AS sales_revenue FROM sales_order WHERE order_date >= DATE '2026-06-01' AND order_date < DATE '2026-07-01'",
        },
        {
            "question": "2026年6月按渠道查看销售收入前100名。",
            "sql": "SELECT c.channel_name, SUM(o.net_revenue) AS sales_revenue FROM sales_order AS o JOIN sales_channel AS c ON o.channel_id = c.channel_id WHERE o.order_date >= DATE '2026-06-01' AND o.order_date < DATE '2026-07-01' GROUP BY c.channel_name ORDER BY sales_revenue DESC LIMIT 100",
        },
        {
            "question": "展示2026年上半年每月销售收入趋势。",
            "sql": "SELECT DATE_TRUNC('month', order_date) AS month, SUM(net_revenue) AS sales_revenue FROM sales_order WHERE order_date >= DATE '2026-01-01' AND order_date < DATE '2026-07-01' GROUP BY DATE_TRUNC('month', order_date) ORDER BY month",
        },
    ),
}


def authorized_examples(
    scenario_id: str,
    allowed_relations: dict[str, tuple[str, ...]],
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
            accepted.append(example)
    return tuple(accepted[:10])


def build_governed_question(
    question: str,
    *,
    scenario_id: str,
    prompt_context: dict[str, Any],
) -> str:
    """Render only server-built, current-scenario metadata into the MCP question."""
    contract = {
        "scenario_id": scenario_id,
        "sql_dialect": "postgres",
        "constraints": {
            "single_select_only": True,
            "max_limit": 500,
            "default_detail_limit": 100,
            "aggregate_limit_required": False,
            "no_cross_scenario_schema": True,
            "active_schema_qualification_may_be_stripped": True,
            "forbid_database_qualification": True,
            "output": {"sql": "single PostgreSQL SELECT"},
        },
        "authorized_tables": prompt_context.get("authorized_tables", []),
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
