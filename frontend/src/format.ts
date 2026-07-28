export function formatMetric(metricId: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return '数据不足'
  if (['gross_margin', 'station_utilization_rate', 'device_online_rate', 'device_fault_rate'].includes(metricId)) {
    return `${(value * 100).toFixed(1)}%`
  }
  if (['completed_order_count', 'active_user_count'].includes(metricId)) {
    return Math.round(value).toLocaleString('zh-CN')
  }
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

export const metricNames: Record<string, string> = {
  charging_revenue: '充电收入',
  service_fee_revenue: '服务费收入',
  completed_order_count: '完成订单数',
  charging_volume_kwh: '充电量',
  energy_cost: '电费成本',
  variable_operating_cost: '可变运营成本',
  gross_profit: '经营毛利',
  gross_margin: '毛利率',
  avg_order_energy_kwh: '单均充电量',
  revenue_per_kwh: '度电收入',
  cost_per_kwh: '度电成本',
  station_utilization_rate: '场站利用率',
  device_online_rate: '设备在线率',
  device_fault_rate: '设备故障率',
  active_user_count: '活跃用户数',
}
