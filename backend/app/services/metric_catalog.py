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
