import hashlib
import json

SCENARIO_ID = "charging_ops"
VERSION = "0.1.0"
DISPLAY_NAME = "充电运营"

METRICS = {
    "charging_revenue": ("充电收入", "元", "electricity_fee_net_amount + service_fee_net_amount"),
    "service_fee_revenue": ("服务费收入", "元", "SUM(service_fee_net_amount)"),
    "completed_order_count": ("完成订单数", "单", "COUNT(DISTINCT session_id)"),
    "charging_volume_kwh": ("充电量", "kWh", "SUM(energy_kwh)"),
    "energy_cost": ("电费成本", "元", "SUM(energy_cost)"),
    "variable_operating_cost": ("可变运营成本", "元", "SUM(amount WHERE is_variable)"),
    "gross_profit": ("经营毛利", "元", "charging_revenue - energy_cost - variable_operating_cost"),
    "gross_margin": ("毛利率", "%", "gross_profit / charging_revenue"),
    "avg_order_energy_kwh": ("单均充电量", "kWh/单", "charging_volume_kwh / completed_order_count"),
    "revenue_per_kwh": ("度电收入", "元/kWh", "charging_revenue / charging_volume_kwh"),
    "cost_per_kwh": ("度电成本", "元/kWh", "(energy_cost + variable_operating_cost) / charging_volume_kwh"),
    "station_utilization_rate": ("场站利用率", "%", "charging_duration / available_connector_duration"),
    "device_online_rate": ("设备在线率", "%", "online_duration / observable_duration"),
    "device_fault_rate": ("设备故障率", "%", "fault_duration / observable_duration"),
    "active_user_count": ("活跃用户数", "人", "COUNT(DISTINCT user_id)"),
}
ALLOWED_DIMENSIONS = ["date", "week", "month", "quarter", "region", "city", "station", "station_type", "operator", "device", "user_segment", "expense_type"]
MAPPING_FIELDS = [
    {"source": "station_id", "source_type": "varchar(50)", "label": "场站编码", "standard": "station_id", "target_type": "varchar(50)", "transform": "—", "unit": "—"},
    {"source": "station_name", "source_type": "varchar(200)", "label": "场站名称", "standard": "station_name", "target_type": "varchar(200)", "transform": "—", "unit": "—"},
    {"source": "region_id", "source_type": "varchar(50)", "label": "运营区域", "standard": "region_id", "target_type": "varchar(50)", "transform": "—", "unit": "—"},
    {"source": "city_id", "source_type": "varchar(50)", "label": "所属城市", "standard": "city_id", "target_type": "varchar(50)", "transform": "—", "unit": "—"},
    {"source": "charging_revenue", "source_type": "decimal(18,2)", "label": "充电收入", "standard": "charging_revenue", "target_type": "decimal(18,2)", "transform": "类型：decimal", "unit": "元"},
    {"source": "charging_volume_kwh", "source_type": "decimal(18,3)", "label": "充电电量", "standard": "charging_volume_kwh", "target_type": "decimal(18,3)", "transform": "精度：3 位", "unit": "kWh"},
    {"source": "gross_profit", "source_type": "decimal(18,2)", "label": "经营毛利", "standard": "gross_profit", "target_type": "decimal(18,2)", "transform": "类型：decimal", "unit": "元"},
    {"source": "gross_margin", "source_type": "decimal(8,4)", "label": "毛利率", "standard": "gross_margin", "target_type": "decimal(8,4)", "transform": "比例：×100", "unit": "%"},
]
MANIFEST = {
    "scenario_id": SCENARIO_ID,
    "version": VERSION,
    "display_name": DISPLAY_NAME,
    "metric_ids": sorted(METRICS),
    "dimensions": ALLOWED_DIMENSIONS,
    "source_tables": ["fact_charging_session", "fact_energy_cost", "fact_operation_expense", "fact_device_status_event"],
    "datasets": ["station-operations"],
    "data_classification": "simulated",
}
MANIFEST_JSON = json.dumps(MANIFEST, ensure_ascii=False, sort_keys=True)
MANIFEST_CHECKSUM = hashlib.sha256(MANIFEST_JSON.encode()).hexdigest()
