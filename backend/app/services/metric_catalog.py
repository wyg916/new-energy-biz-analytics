from app.scenarios.charging_ops.manifest import ALLOWED_DIMENSIONS, METRICS

DIMENSION_LABELS = {
    "date": "日期",
    "week": "周",
    "month": "月",
    "quarter": "季度",
    "region": "区域",
    "city": "城市",
    "station": "场站",
    "station_type": "场站类型",
    "operator": "运营商",
    "device": "设备",
    "user_segment": "用户分群",
    "expense_type": "费用类型",
}

METRIC_DETAILS = {
    "charging_revenue": {
        "business_domain": "收入分析",
        "definition": "已完成充电订单中，电费净额与服务费净额之和。",
        "source_tables": ["fact_charging_session"],
        "metric_type": "aggregation",
    },
    "service_fee_revenue": {
        "business_domain": "收入分析",
        "definition": "已完成充电订单的服务费净额汇总。",
        "source_tables": ["fact_charging_session"],
        "metric_type": "aggregation",
    },
    "completed_order_count": {
        "business_domain": "收入分析",
        "definition": "统计期内已完成充电会话的去重订单数。",
        "source_tables": ["fact_charging_session"],
        "metric_type": "distinct_count",
    },
    "charging_volume_kwh": {
        "business_domain": "收入分析",
        "definition": "已完成充电订单的充电电量汇总。",
        "source_tables": ["fact_charging_session"],
        "metric_type": "aggregation",
    },
    "avg_order_energy_kwh": {
        "business_domain": "收入分析",
        "definition": "充电量除以完成订单数，分母为零时返回空值。",
        "source_tables": ["fact_charging_session"],
        "metric_type": "calculated",
    },
    "revenue_per_kwh": {
        "business_domain": "收入分析",
        "definition": "充电收入除以充电量，分母为零时返回空值。",
        "source_tables": ["fact_charging_session"],
        "metric_type": "calculated",
    },
    "active_user_count": {
        "business_domain": "收入分析",
        "definition": "统计期内已完成订单对应的去重活跃用户数。",
        "source_tables": ["fact_charging_session"],
        "metric_type": "distinct_count",
    },
    "energy_cost": {
        "business_domain": "毛利成本",
        "definition": "已完成充电订单对应的电费成本汇总。",
        "source_tables": ["fact_energy_cost"],
        "metric_type": "aggregation",
    },
    "variable_operating_cost": {
        "business_domain": "毛利成本",
        "definition": "统计期内可变运营费用汇总。",
        "source_tables": ["fact_operation_expense"],
        "metric_type": "aggregation",
    },
    "gross_profit": {
        "business_domain": "毛利成本",
        "definition": "充电收入扣除电费成本和可变运营成本后的经营毛利。",
        "source_tables": [
            "fact_charging_session",
            "fact_energy_cost",
            "fact_operation_expense",
        ],
        "metric_type": "calculated",
    },
    "gross_margin": {
        "business_domain": "毛利成本",
        "definition": "经营毛利占充电收入的比例，分母为零时返回空值。",
        "source_tables": [
            "fact_charging_session",
            "fact_energy_cost",
            "fact_operation_expense",
        ],
        "metric_type": "ratio",
    },
    "cost_per_kwh": {
        "business_domain": "毛利成本",
        "definition": "电费成本与可变运营成本之和除以充电量。",
        "source_tables": [
            "fact_charging_session",
            "fact_energy_cost",
            "fact_operation_expense",
        ],
        "metric_type": "calculated",
    },
    "station_utilization_rate": {
        "business_domain": "场站经营",
        "definition": "实际充电时长占可用枪口时长的比例。",
        "source_tables": ["fact_charging_session", "dim_station"],
        "metric_type": "ratio",
    },
    "device_online_rate": {
        "business_domain": "设备健康",
        "definition": "设备在线时长占可观测时长的比例。",
        "source_tables": ["fact_device_status_event", "dim_device"],
        "metric_type": "ratio",
    },
    "device_fault_rate": {
        "business_domain": "设备健康",
        "definition": "设备故障时长占可观测时长的比例。",
        "source_tables": ["fact_device_status_event", "dim_device"],
        "metric_type": "ratio",
    },
}

SUPPORTED_GRAINS = ["day", "week", "month"]

__all__ = [
    "ALLOWED_DIMENSIONS",
    "DIMENSION_LABELS",
    "METRICS",
    "METRIC_DETAILS",
    "SUPPORTED_GRAINS",
]
