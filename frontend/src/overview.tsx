import React, { useEffect, useMemo, useRef, useState } from 'react'
import { formatMetric, metricNames } from './format'
import { MetricsPage } from './metrics'
import { RevenuePage } from './revenue'
import { KnowledgePage } from './knowledge'
import { MemoryPage, SkillPage } from './memory-skills'
import { GovernancePage } from './governance'
import './overview.css'
import './report.css'
import './mapping.css'
import './alerts.css'

type Metadata = {
  data_classification: string
  data_time_range: { start: string; end_exclusive: string }
  source: string
  batch_id: string | null
  analysis_run_id: string
  generated_at?: string
  query_source?: string
  dataset_release_version?: string | null
  semantic_activation_status?: string
}
type Summary = { metrics: Record<string, number | null>; metadata: Metadata }
type FrontendContext = {
  default_time_range: { start: string; end_exclusive: string }
  available_time_range: { start: string; end_exclusive: string }
  scenario: { scenario_id: string; display_name: string; version: string; status: string }
  metric_count: number
  recommended_questions: string[]
  metadata: Metadata
}
type TrendPoint = { period: string; value: number | null }
type StationRow = {
  station_id: string
  station_name: string
  region_id: string
  city_id: string
  station_type: string
  metrics: Record<string, number | null>
}
type DeviceEvent = {
  status: string
  reason_code: string | null
  is_planned: boolean
  start_time: string
  end_time: string
  duration_hours: number
}
type DeviceRow = {
  device_id: string
  station_id: string
  station_name: string
  region_id: string
  device_model: string
  connector_count: number
  rated_power_kw: number
  commission_date: string
  current_status: string
  priority: string
  online_hours: number
  offline_hours: number
  fault_hours: number
  fault_event_count: number
  fault_rate: number | null
  related_order_count: number
  related_revenue: number
  recent_events: DeviceEvent[]
}
type DeviceAnalysis = {
  rows: DeviceRow[]
  metrics: { device_online_rate: number | null; device_fault_rate: number | null }
  totals: {
    device_count: number
    online_count: number
    offline_count: number
    fault_count: number
    risk_order_count: number
    risk_revenue: number
  }
  reason_summary: Array<{ reason_code: string; count: number }>
  metadata: Metadata
}
type ViewId = 'overview' | 'dashboard' | 'revenue' | 'margin' | 'stations' | 'devices' | 'alerts' | 'chat' | 'reports' | 'knowledge' | 'memory' | 'skills' | 'mapping' | 'metrics' | 'governance'

const groups: Array<{ title: string; items: Array<{ id: ViewId; label: string; icon: string }> }> = [
  { title: '基础入口', items: [{ id: 'overview', label: '功能总览', icon: '⌂' }, { id: 'dashboard', label: '经营工作台', icon: '◫' }] },
  { title: '经营分析', items: [{ id: 'revenue', label: '收入与订单', icon: '▤' }, { id: 'margin', label: '毛利与成本', icon: '◴' }, { id: 'stations', label: '场站经营', icon: '♙' }, { id: 'devices', label: '设备健康', icon: '◇' }, { id: 'alerts', label: '经营预警', icon: '♧' }] },
  { title: '智能分析', items: [{ id: 'chat', label: 'AI经营分析', icon: 'AI' }, { id: 'memory', label: '记忆与偏好', icon: '忆' }, { id: 'skills', label: 'Skill 管理', icon: '技' }] },
  { title: '内容管理', items: [{ id: 'reports', label: '经营报告', icon: '▱' }, { id: 'knowledge', label: '企业知识库', icon: '知' }] },
  { title: '数据管理', items: [{ id: 'mapping', label: '数据接入与字段映射', icon: '◎' }, { id: 'metrics', label: '指标与场景管理', icon: '▧' }] },
  { title: '企业治理', items: [{ id: 'governance', label: '治理与生产就绪', icon: '治' }] },
]

const titles: Record<ViewId, string> = {
  overview: '功能总览', dashboard: '经营工作台', revenue: '收入与订单', margin: '毛利与成本',
  stations: '场站经营', devices: '设备健康', alerts: '经营预警', chat: 'AI经营分析',
  reports: '经营报告', knowledge: '企业知识库', memory: '记忆与偏好', skills: 'Skill 管理', mapping: '数据接入与字段映射', metrics: '指标与场景管理',
  governance: '企业治理与生产就绪',
}
const pageMetrics: Record<string, string[]> = {
  dashboard: ['charging_revenue', 'gross_profit', 'gross_margin', 'charging_volume_kwh', 'completed_order_count', 'active_user_count'],
  revenue: ['charging_revenue', 'service_fee_revenue', 'revenue_per_kwh', 'completed_order_count'],
  margin: ['gross_profit', 'gross_margin', 'energy_cost', 'variable_operating_cost', 'cost_per_kwh'],
  stations: ['station_utilization_rate', 'charging_volume_kwh', 'charging_revenue', 'gross_profit'],
  devices: ['device_online_rate', 'device_fault_rate', 'station_utilization_rate'],
}

async function api<T>(path: string, token: string): Promise<T> {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` } })
  if (response.status === 401) {
    localStorage.removeItem('alpha_token')
    location.reload()
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail?.message || '请求失败')
  }
  return response.json()
}
const money = (value: number | null | undefined) => value == null ? '数据不足' : value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const endInclusive = (end: string) => {
  if (!end) return ''
  const result = new Date(`${end}T00:00:00Z`)
  result.setUTCDate(result.getUTCDate() - 1)
  return result.toISOString().slice(0, 10)
}

function GlobalDataStatus({ metadata }: { metadata: Metadata | null }) {
  if (!metadata) {
    return <footer className="global-data-status" aria-label="数据状态">正在核验数据库数据状态…</footer>
  }
  const classification = metadata.data_classification === 'simulated'
    ? '模拟数据'
    : metadata.data_classification
  const source = metadata.source === 'platform_database'
    ? '平台数据库'
    : metadata.source
  return <footer className="global-data-status" aria-label="数据状态">
    <b>{classification}</b>
    <span>数据时间：{metadata.data_time_range.start} 至 {endInclusive(metadata.data_time_range.end_exclusive)}</span>
    <span>来源：{source}</span>
    <span>run_id：{metadata.analysis_run_id}</span>
  </footer>
}

function MiniLine({ points, large = false, stroke }: { points: TrendPoint[]; large?: boolean; stroke?: string }) {
  const values = points.map(item => item.value ?? 0)
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const width = large ? 760 : 190
  const height = large ? 170 : 56
  const coords = values.map((value, index) => `${index / Math.max(values.length - 1, 1) * width},${height - 7 - (value - min) / (max - min || 1) * (height - 18)}`).join(' ')
  return <svg className={large ? 'detail-line' : 'mini-line'} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="指标月度趋势"><polyline points={coords} style={stroke ? { stroke } : undefined} /></svg>
}

function MiniBars({ points }: { points: TrendPoint[] }) {
  const values = points.map(item => item.value ?? 0)
  const max = Math.max(...values, 1)
  return <div className="mini-bars">{values.map((value, index) => <i key={index} style={{ height: `${Math.max(value / max * 100, 12)}%` }} />)}</div>
}

function Donut({ value, device = false }: { value: number; device?: boolean }) {
  const percentage = Math.min(Math.max(value * 100, 0), 100)
  const colors = device ? ['#11979c', '#32b3a5'] : ['#574bdd', '#2cab83']
  return <div className="donut" style={{ background: `conic-gradient(${colors[0]} 0 ${percentage * .62}%,${colors[1]} ${percentage * .62}% ${percentage}%,#edf1f7 ${percentage}% 100%)` }}><span /></div>
}

function ModuleTitle({ icon, color, title, subtitle }: { icon: string; color: string; title: string; subtitle: string }) {
  return <div className="module-title"><i className={color}>{icon}</i><div><h3>{title}</h3><p>{subtitle}</p></div></div>
}

function CardLink({ label, onClick }: { label: string; onClick: () => void }) {
  return <button className="card-link" onClick={onClick}>{label}<span>→</span></button>
}

function Overview({ summary, trend, loading, error, navigate, context }: { summary: Summary | null; trend: TrendPoint[]; loading: boolean; error: string; navigate: (id: ViewId) => void; context: FrontendContext | null }) {
  const m = summary?.metrics ?? {}
  const questions = context?.recommended_questions ?? []
  return <div className="overview-page">
    {error && <div className="notice error">{error}</div>}
    <section className={`overview-hero ${loading ? 'loading' : ''}`}>
      <div className="hero-copy">
        <h2>面向新能源充电运营企业的<br />AI 经营分析平台</h2>
        <p>整合多源数据，洞察经营全貌，驱动精细化运营与科学决策</p>
      </div>
      <img src="/figma-assets/hero-operations.svg" alt="新能源充电运营场景" />
      <div className="hero-kpis">
        <div><i className="blue">收</i><span>所选周期充电收入（元）</span><strong>{money(m.charging_revenue)}</strong><small>来自指标语义层 v0.1.0</small></div>
        <div><i className="teal">毛</i><span>所选周期毛利率</span><strong>{formatMetric('gross_margin', m.gross_margin)}</strong><small>口径已发布并验证</small></div>
        <div><i className="violet">站</i><span>所选周期利用率</span><strong>{formatMetric('station_utilization_rate', m.station_utilization_rate)}</strong><small>基于场站可用时长</small></div>
      </div>
    </section>

    <section className="module-grid">
      <article className="module-card"><ModuleTitle icon="台" color="blue" title="经营工作台" subtitle="经营总览与核心指标监控" /><MiniLine points={trend} /><div className="metric-pair"><span>充电收入（元）<b>{money(m.charging_revenue)}</b></span><span>毛利率<b>{formatMetric('gross_margin', m.gross_margin)}</b></span></div></article>
      <article className="module-card"><ModuleTitle icon="收" color="teal" title="收入与订单" subtitle="收入趋势、订单分析与结构洞察" /><MiniBars points={trend} /><div className="metric-pair"><span>服务费收入（元）<b>{money(m.service_fee_revenue)}</b></span><span>完成订单数<b>{formatMetric('completed_order_count', m.completed_order_count)}</b></span></div></article>
      <article className="module-card"><ModuleTitle icon="毛" color="orange" title="毛利与成本" subtitle="毛利分析、成本结构与费用洞察" /><div className="ring-content"><Donut value={m.gross_margin ?? 0} /><div><span>毛利率</span><b>{formatMetric('gross_margin', m.gross_margin)}</b><span>度电成本（元/kWh）</span><b>{formatMetric('cost_per_kwh', m.cost_per_kwh)}</b></div></div></article>
      <article className="module-card"><ModuleTitle icon="站" color="violet" title="场站经营" subtitle="场站收入、利用率与排名分析" /><MiniLine points={trend} stroke="#574bdd" /><div className="stack-metrics"><span>场站利用率<b>{formatMetric('station_utilization_rate', m.station_utilization_rate)}</b></span><span>充电量（kWh）<b>{formatMetric('charging_volume_kwh', m.charging_volume_kwh)}</b></span></div></article>
      <article className="module-card"><ModuleTitle icon="设" color="violet" title="设备健康" subtitle="设备在线率、故障率与健康评估" /><div className="ring-content"><Donut value={m.device_online_rate ?? 0} device /><div><span>设备在线率</span><b>{formatMetric('device_online_rate', m.device_online_rate)}</b><span>设备故障率</span><b>{formatMetric('device_fault_rate', m.device_fault_rate)}</b></div></div></article>
    </section>

    <section className="module-grid">
      <article className="module-card action"><ModuleTitle icon="警" color="red" title="经营预警" subtitle="风险预警、异常监控与告警管理" /><ul className="status-list warning"><li>毛利率异常<span>规则检测</span></li><li>高功率利用率异常<span>规则检测</span></li><li>设备离线告警<span>进入查看</span></li></ul><CardLink label="查看预警中心" onClick={() => navigate('alerts')} /></article>
      <article className="module-card action"><ModuleTitle icon="AI" color="blue" title="AI经营分析" subtitle="自然语言分析、智能问答与归因" /><div className="ask-sample">区域A的充电收入环比下降原因？</div><button className="ask-button" onClick={() => navigate('chat')}>◉　向 AI 提问 <b>›</b></button><CardLink label="查看分析洞察" onClick={() => navigate('chat')} /></article>
      <article className="module-card action"><ModuleTitle icon="报" color="teal" title="经营报告" subtitle="经营日报、周报、月报与专题报告" /><ul className="status-list"><li>经营日报<span>按需生成</span></li><li>经营周报<span>草稿可审核</span></li><li>经营月报<span>结果可追溯</span></li></ul><CardLink label="查看全部报告" onClick={() => navigate('reports')} /></article>
      <article className="module-card action"><ModuleTitle icon="数" color="blue" title="数据接入与映射" subtitle="数据连接、同步管理与字段映射" /><ul className="status-list"><li>平台数据源<span>{error ? '查询失败' : summary ? '当前查询可用' : '加载中'}</span></li><li>数据批次<span>{summary?.metadata.batch_id ? '可追溯' : '未取得'}</span></li><li>正式消费<span>平台事实表</span></li></ul><CardLink label="进入映射配置" onClick={() => navigate('mapping')} /></article>
      <article className="module-card action"><ModuleTitle icon="指" color="orange" title="指标与场景管理" subtitle="指标体系、业务场景与权限管理" /><ul className="status-list"><li>核心指标<span>{context ? `${context.metric_count} 项` : '加载中'}</span></li><li>当前场景<span>{context?.scenario.display_name || '加载中'}</span></li><li>权限模式<span>RBAC</span></li></ul><CardLink label="进入管理中心" onClick={() => navigate('metrics')} /></article>
    </section>

    <section className="bottom-grid">
      <article className="bottom-card questions"><header><h3>常用分析入口</h3><button disabled title="问题推荐轮换尚未实现">固定题集</button></header><div>{questions.map((question, index) => <button key={question} onClick={() => navigate('chat')}><i>{index % 2 ? '⌁' : '↗'}</i>{question}</button>)}</div></article>
      <article className="bottom-card system"><header><h3>近期动态 / 当前页面状态</h3></header><ul><li><i>◷</i><span>数据最后刷新</span><b>{summary?.metadata.generated_at ? new Date(summary.metadata.generated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '未取得'}</b></li><li><i>♧</i><span>异常检测</span><b className="attention">规则结果按需计算</b></li><li><i>▱</i><span>报告生成</span><b>仅可审核草稿</b></li><li><i>◎</i><span>数据查询状态</span><b>{error ? '失败' : summary ? '成功' : '加载中'}</b></li><li><i>✓</i><span>当前页面 API</span><b className={error ? 'attention' : 'healthy'}>{error ? '不可用' : summary ? '可用' : '检查中'}</b></li></ul></article>
      <article className="bottom-card guide"><header><h3>视图说明</h3></header><div><i>业</i><span><b>业务视图</b><small>面向运营与分析人员，聚焦经营分析与监控</small></span></div><div><i>管</i><span><b>管理视图</b><small>面向管理员，负责配置与系统管理</small></span></div><button disabled title="帮助中心尚未实现">帮助中心未开放</button></article>
    </section>
  </div>
}

function compareRange(start: string, end: string, comparison: 'mom' | 'yoy') {
  const from = new Date(`${start}T00:00:00Z`)
  const to = new Date(`${end}T00:00:00Z`)
  if (comparison === 'yoy') {
    from.setUTCFullYear(from.getUTCFullYear() - 1)
    to.setUTCFullYear(to.getUTCFullYear() - 1)
  } else {
    const duration = to.getTime() - from.getTime()
    to.setTime(from.getTime())
    from.setTime(from.getTime() - duration)
  }
  return { start: from.toISOString().slice(0, 10), end: to.toISOString().slice(0, 10) }
}

function monthBefore(endExclusive: string) {
  const end = new Date(`${endExclusive}T00:00:00Z`)
  const start = new Date(end)
  start.setUTCMonth(start.getUTCMonth() - 1)
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  }
}

function rate(current: number | null | undefined, previous: number | null | undefined) {
  if (current == null || previous == null || previous === 0) return null
  return (current - previous) / Math.abs(previous)
}

function deltaText(metric: string, current: number | null | undefined, previous: number | null | undefined) {
  if (current == null || previous == null) return '数据不足'
  if (['gross_margin', 'station_utilization_rate', 'device_online_rate', 'device_fault_rate'].includes(metric)) {
    const value = (current - previous) * 100
    return `${value >= 0 ? '↑' : '↓'} ${Math.abs(value).toFixed(2)}pp`
  }
  const value = rate(current, previous)
  return value == null ? '数据不足' : `${value >= 0 ? '↑' : '↓'} ${(Math.abs(value) * 100).toFixed(2)}%`
}

function workbenchValue(metric: string, value: number | null | undefined) {
  if (value == null) return { value: '数据不足', unit: '' }
  if (metric === 'charging_revenue' || metric === 'gross_profit') return { value: (value / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }), unit: '万元' }
  if (metric === 'charging_volume_kwh') return { value: Math.round(value).toLocaleString('zh-CN'), unit: 'kWh' }
  if (metric === 'completed_order_count') return { value: Math.round(value).toLocaleString('zh-CN'), unit: '单' }
  return { value: formatMetric(metric, value), unit: '' }
}

function ComboTrend({ revenue, profit }: { revenue: TrendPoint[]; profit: TrendPoint[] }) {
  const revenueValues = revenue.map(item => item.value ?? 0)
  const profitValues = profit.map(item => item.value ?? 0)
  const revenueMax = Math.max(...revenueValues, 1)
  const profitMax = Math.max(...profitValues, 1)
  const revenueLine = revenueValues.map((value, index) => `${index / Math.max(revenueValues.length - 1, 1) * 100},${90 - value / revenueMax * 72}`).join(' ')
  const profitLine = profitValues.map((value, index) => `${index / Math.max(profitValues.length - 1, 1) * 100},${90 - value / profitMax * 72}`).join(' ')
  return <div className="combo-chart"><div className="chart-legend"><span className="green">收入</span><span className="blue-dot">毛利</span><small>按自然月聚合</small></div><div className="combo-plot"><div className="combo-bars">{revenueValues.map((value, index) => <i key={index} style={{ height: `${Math.max(value / revenueMax * 100, 12)}px` }} />)}</div><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline className="revenue-line" points={revenueLine} /><polyline className="profit-line" points={profitLine} /></svg></div><div className="combo-axis">{revenue.map(item => <span key={item.period}>{item.period.slice(5)}</span>)}</div></div>
}

function Waterfall({ title, diagnostic, metric }: { title: string; diagnostic: any; metric: string }) {
  if (!diagnostic) return <div className="workbench-chart loading">正在计算贡献拆解…</div>
  const driverNames: Record<string, string> = {
    station_revenue: '场站收入',
    service_revenue: '服务收入',
    energy_revenue: '电费收入',
    energy_cost: '度电成本',
    service_cost: '服务成本',
    other_cost: '其他成本',
    volume: '充电量',
    price: '单价',
    mix: '结构',
    residual: '其他',
    charging_volume_effect: '充电量影响',
    revenue_per_kwh_effect: '度电收入影响',
    rounding_residual: '舍入差额',
    charging_revenue_change: '收入变化',
    energy_cost_change: '电费成本变化',
    variable_operating_cost_change: '运营成本变化',
  }
  const items = [
    { label: '对比期', value: diagnostic.previous[metric], total: true },
    ...diagnostic.bridge.map((item: any) => ({ label: driverNames[item.driver] ?? item.driver.replaceAll('_', ' '), value: item.contribution, total: false })),
    { label: '本期', value: diagnostic.current[metric], total: true },
  ]
  const max = Math.max(...items.map(item => Math.abs(item.value ?? 0)), 1)
  const change = diagnostic.changes[metric]
  return <article className="workbench-chart"><header><div><h3>{title}</h3><p>环比 <b className={change >= 0 ? 'up' : 'down'}>{change >= 0 ? '+' : ''}{money(change)}</b></p></div></header><div className="waterfall">{items.map((item: any, index: number) => <div key={`${item.label}-${index}`}><b>{item.value == null ? '--' : (item.value / 10000).toFixed(2)}</b><i className={item.total ? 'total' : item.value >= 0 ? 'positive' : 'negative'} style={{ height: `${Math.max(Math.abs(item.value ?? 0) / max * 78, 7)}%` }} /><span>{item.label}</span></div>)}</div></article>
}

function WorkbenchPage({
  token,
  summary,
  stations,
  revenueTrend,
  start,
  end,
  setStart,
  setEnd,
  navigate,
  refreshKey,
  refresh,
}: {
  token: string
  summary: Summary | null
  stations: StationRow[]
  revenueTrend: TrendPoint[]
  start: string
  end: string
  setStart: (value: string) => void
  setEnd: (value: string) => void
  navigate: (id: ViewId) => void
  refreshKey: number
  refresh: () => void
}) {
  const [comparison, setComparison] = useState<'mom' | 'yoy'>('mom')
  const [previous, setPrevious] = useState<Summary | null>(null)
  const [yearAgo, setYearAgo] = useState<Summary | null>(null)
  const [trends, setTrends] = useState<Record<string, TrendPoint[]>>({ charging_revenue: revenueTrend })
  const [revenueDiagnostic, setRevenueDiagnostic] = useState<any>(null)
  const [profitDiagnostic, setProfitDiagnostic] = useState<any>(null)
  const [previousStations, setPreviousStations] = useState<StationRow[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    const previousRange = compareRange(start, end, comparison)
    const yoyRange = compareRange(start, end, 'yoy')
    const stationMetrics = 'charging_revenue,gross_profit,gross_margin,station_utilization_rate,device_online_rate,device_fault_rate'
    Promise.all([
      api<Summary>(`/api/v1/dashboard/summary?start=${previousRange.start}&end_exclusive=${previousRange.end}`, token),
      api<Summary>(`/api/v1/dashboard/summary?start=${yoyRange.start}&end_exclusive=${yoyRange.end}`, token),
      ...['gross_profit', 'gross_margin', 'charging_volume_kwh', 'completed_order_count', 'station_utilization_rate'].map(metric => api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=${metric}&start=${start}&end_exclusive=${end}`, token)),
      api<any>(`/api/v1/diagnostics/decomposition?metric=charging_revenue&comparison=${comparison}&limit=5&start=${start}&end_exclusive=${end}`, token),
      api<any>(`/api/v1/diagnostics/decomposition?metric=gross_profit&comparison=${comparison}&limit=5&start=${start}&end_exclusive=${end}`, token),
      api<{ rows: StationRow[] }>(`/api/v1/dashboard/stations?start=${previousRange.start}&end_exclusive=${previousRange.end}&limit=10&metrics=${stationMetrics}`, token),
    ]).then(([previousResult, yoyResult, profitTrend, marginTrend, volumeTrend, orderTrend, utilizationTrend, revenueDiag, profitDiag, stationResult]) => {
      setPrevious(previousResult as Summary)
      setYearAgo(yoyResult as Summary)
      setTrends({
        charging_revenue: revenueTrend,
        gross_profit: (profitTrend as { points: TrendPoint[] }).points,
        gross_margin: (marginTrend as { points: TrendPoint[] }).points,
        charging_volume_kwh: (volumeTrend as { points: TrendPoint[] }).points,
        completed_order_count: (orderTrend as { points: TrendPoint[] }).points,
        station_utilization_rate: (utilizationTrend as { points: TrendPoint[] }).points,
      })
      setRevenueDiagnostic(revenueDiag)
      setProfitDiagnostic(profitDiag)
      setPreviousStations((stationResult as { rows: StationRow[] }).rows)
      setError('')
    }).catch(reason => setError(reason instanceof Error ? reason.message : '工作台分析加载失败'))
  }, [token, start, end, comparison, refreshKey, revenueTrend])

  const metrics = summary?.metrics ?? {}
  const previousMetrics = previous?.metrics ?? {}
  const yearAgoMetrics = yearAgo?.metrics ?? {}
  const cards = [
    { id: 'charging_revenue', label: '充电收入', icon: '收', color: 'green', stroke: '#11a879' },
    { id: 'gross_profit', label: '经营毛利', icon: '利', color: 'green', stroke: '#11a879' },
    { id: 'gross_margin', label: '毛利率', icon: '率', color: 'orange', stroke: '#f59e0b' },
    { id: 'charging_volume_kwh', label: '充电量', icon: '量', color: 'blue', stroke: '#1677ff' },
    { id: 'completed_order_count', label: '完成订单', icon: '单', color: 'violet', stroke: '#7c5cff' },
    { id: 'station_utilization_rate', label: '场站利用率', icon: '站', color: 'teal', stroke: '#0ca89f' },
  ]
  const previousStationMap = new Map(previousStations.map(row => [row.station_id, row]))
  const issueRows = (revenueDiagnostic?.station_contributions ?? []).slice(0, 5)
  const revenueRate = rate(metrics.charging_revenue, previousMetrics.charging_revenue)
  const marginDelta = metrics.gross_margin != null && previousMetrics.gross_margin != null ? (metrics.gross_margin - previousMetrics.gross_margin) * 100 : null

  return <div className="workbench-page">
    <section className="workbench-filters">
      <label>时间范围<div><input type="date" value={start} onChange={event => setStart(event.target.value)} /><span>~</span><input type="date" value={endInclusive(end)} onChange={event => { const next = new Date(`${event.target.value}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1); setEnd(next.toISOString().slice(0, 10)) }} /></div></label>
      <label>对比方式<select value={comparison} onChange={event => setComparison(event.target.value as 'mom' | 'yoy')}><option value="mom">环比</option><option value="yoy">同比</option></select></label>
      <label>区域<select><option>全部区域</option></select></label>
      <label>城市<select><option>全部城市</option></select></label>
      <label>场站<select><option>全部场站</option></select></label>
      <button onClick={refresh}>⌕　查询</button>
    </section>

    <section className="ai-summary">
      <div className="summary-copy"><i>✦</i><div><h2>AI经营摘要</h2>{summary ? <ul><li>本期充电收入 {money(metrics.charging_revenue)} 元，{comparison === 'mom' ? '环比' : '同比'} {revenueRate == null ? '数据不足' : `${revenueRate >= 0 ? '↑' : '↓'} ${(Math.abs(revenueRate) * 100).toFixed(2)}%`}；毛利率 {formatMetric('gross_margin', metrics.gross_margin)}，变化 {marginDelta == null ? '数据不足' : `${marginDelta >= 0 ? '↑' : '↓'} ${Math.abs(marginDelta).toFixed(2)}pp`}。</li><li>收入、毛利、利用率及设备指标均来自已发布指标语义层。</li><li>设备在线率 {formatMetric('device_online_rate', metrics.device_online_rate)}，故障率 {formatMetric('device_fault_rate', metrics.device_fault_rate)}；关联因素不构成因果结论。</li></ul> : <p>正在生成结构化经营摘要…</p>}</div></div>
      <div className="summary-actions"><small>数据截止：{endInclusive(end)}</small><div><button onClick={() => navigate('alerts')}>◉　查看分析依据</button><button onClick={() => navigate('chat')}>◎　继续追问</button><button className="primary" onClick={() => navigate('reports')}>▱　生成报告</button></div></div>
    </section>

    <section className="workbench-kpis">
      {cards.map(card => {
        const display = workbenchValue(card.id, metrics[card.id])
        return <article key={card.id}><header><i className={card.color}>{card.icon}</i><h3>{card.label}</h3><span>ⓘ</span></header><div className="kpi-number"><strong>{display.value}</strong><small>{display.unit}</small></div><p><span>环比 <b className={rate(metrics[card.id], previousMetrics[card.id]) != null && rate(metrics[card.id], previousMetrics[card.id])! < 0 ? 'down' : 'up'}>{deltaText(card.id, metrics[card.id], previousMetrics[card.id])}</b></span><span>同比 <b className={rate(metrics[card.id], yearAgoMetrics[card.id]) != null && rate(metrics[card.id], yearAgoMetrics[card.id])! < 0 ? 'down' : 'up'}>{deltaText(card.id, metrics[card.id], yearAgoMetrics[card.id])}</b></span></p><MiniLine points={trends[card.id] ?? revenueTrend} stroke={card.stroke} /><footer><span>指标状态　已验证</span><i className={card.color} /></footer></article>
      })}
    </section>

    <section className="workbench-analysis">
      <article className="trend-panel"><header><h3>收入与毛利趋势（万元）</h3><div><button disabled className="active">月</button></div></header><ComboTrend revenue={trends.charging_revenue ?? revenueTrend} profit={trends.gross_profit ?? []} /></article>
      <Waterfall title="收入变化贡献（万元）" diagnostic={revenueDiagnostic} metric="charging_revenue" />
      <Waterfall title="毛利变化贡献（万元）" diagnostic={profitDiagnostic} metric="gross_profit" />
    </section>

    <section className="workbench-tables">
      <article><header><h3>重点问题</h3><span>ⓘ</span></header><table><thead><tr><th>优先级</th><th>问题描述</th><th>影响金额</th><th>涉及对象</th><th>状态</th></tr></thead><tbody>{issueRows.map((row: any) => <tr key={row.station_id}><td><b className={row.contribution < 0 ? 'risk-high' : 'risk-low'}>{row.contribution < 0 ? '关注' : '正向'}</b></td><td>{row.contribution < 0 ? '收入贡献下降需关注' : '收入增长贡献'}</td><td className={row.contribution < 0 ? 'down' : 'up'}>{money(row.contribution)}</td><td>{row.station_name}</td><td><em>{row.contribution < 0 ? '待分析' : '观察中'}</em></td></tr>)}</tbody></table><button className="table-more" onClick={() => navigate('alerts')}>查看更多问题　→</button></article>
      <article><header><h3>重点场站</h3></header><table><thead><tr><th>场站名称</th><th>充电收入</th><th>环比</th><th>毛利率</th><th>利用率</th><th>在线率</th><th>风险提示</th></tr></thead><tbody>{stations.slice(0, 5).map(row => {
        const previousRow = previousStationMap.get(row.station_id)
        const stationRate = rate(row.metrics.charging_revenue, previousRow?.metrics.charging_revenue)
        const needsAttention = (row.metrics.device_fault_rate ?? 0) > (metrics.device_fault_rate ?? 0)
        return <tr key={row.station_id}><td>{row.station_name}</td><td>{money(row.metrics.charging_revenue)}</td><td className={stationRate != null && stationRate < 0 ? 'down' : 'up'}>{stationRate == null ? '--' : `${stationRate >= 0 ? '↑' : '↓'} ${(Math.abs(stationRate) * 100).toFixed(1)}%`}</td><td>{formatMetric('gross_margin', row.metrics.gross_margin)}</td><td>{formatMetric('station_utilization_rate', row.metrics.station_utilization_rate)}</td><td>{formatMetric('device_online_rate', row.metrics.device_online_rate)}</td><td><b className={needsAttention ? 'risk-high' : 'risk-low'}>{needsAttention ? '需关注' : '正常'}</b></td></tr>
      })}</tbody></table><button className="table-more" onClick={() => navigate('stations')}>查看更多场站　→</button></article>
    </section>
    {error && <div className="workbench-error">{error}</div>}
  </div>
}

function DetailPage({ active, summary, stations, trend }: { active: ViewId; summary: Summary | null; stations: StationRow[]; trend: TrendPoint[] }) {
  if (!summary) return <div className="notice">正在计算经营指标…</div>
  const ids = pageMetrics[active] || pageMetrics.dashboard
  const primary = ids[0]
  const max = Math.max(...stations.map(row => row.metrics[primary] ?? 0), 1)
  return <div className="detail-page">
    <section className="detail-kpis">{ids.map(id => <article key={id}><span>{metricNames[id]}</span><strong>{formatMetric(id, summary.metrics[id])}</strong><small>指标语义层 v0.1.0</small></article>)}</section>
    <section className="detail-grid"><article><h2>{metricNames[primary]}月度趋势</h2><p>按 Asia/Shanghai 自然月聚合</p><MiniLine points={trend} large /></article><article><h2>场站贡献排名</h2><p>{metricNames[primary]} Top 10</p><div className="ranking">{stations.map((row, index) => <div key={row.station_id}><b>{index + 1}</b><span>{row.station_name}<small>{row.region_id} · {row.station_type}</small></span><i><em style={{ width: `${(row.metrics[primary] ?? 0) / max * 100}%` }} /></i><strong>{formatMetric(primary, row.metrics[primary])}</strong></div>)}</div></article></section>
  </div>
}

type ProfitDiagnostic = {
  current: Record<string, number | null>
  previous: Record<string, number | null>
  bridge: Array<{ driver: string; contribution: number }>
  reconciliation: { target_change: number; bridge_sum: number; residual: number }
  metadata: Metadata & { causality_boundary?: string }
}

const marginDriverNames: Record<string, string> = {
  charging_revenue_change: '收入变化',
  energy_cost_change: '电费成本变化',
  variable_operating_cost_change: '可变运营成本变化',
}

function MarginWaterfall({ diagnostic }: { diagnostic: ProfitDiagnostic | null }) {
  if (!diagnostic) return <div className="margin-chart-loading">正在计算毛利变化贡献…</div>
  const startValue = diagnostic.previous.gross_profit ?? 0
  const endValue = diagnostic.current.gross_profit ?? 0
  let cumulative = startValue
  const values = [
    { label: '上期毛利', value: startValue, start: 0, end: startValue, total: true },
    ...diagnostic.bridge.map(item => {
      const start = cumulative
      cumulative += item.contribution
      return { label: marginDriverNames[item.driver] || item.driver, value: item.contribution, start, end: cumulative, total: false }
    }),
    { label: '本期毛利', value: endValue, start: 0, end: endValue, total: true },
  ]
  const allLevels = values.flatMap(item => [item.start, item.end, 0])
  const rawMin = Math.min(...allLevels)
  const rawMax = Math.max(...allLevels)
  const spread = Math.max(rawMax - rawMin, 1)
  const axisMin = rawMin < 0 ? rawMin - spread * .08 : 0
  const axisMax = rawMax + spread * .17
  const plot = { left: 58, right: 592, top: 18, bottom: 150 }
  const plotHeight = plot.bottom - plot.top
  const step = (plot.right - plot.left) / values.length
  const barWidth = Math.min(42, step * .43)
  const y = (value: number) => plot.top + (axisMax - value) / (axisMax - axisMin) * plotHeight
  const ticks = Array.from({ length: 5 }, (_, index) => axisMin + (axisMax - axisMin) * index / 4)
  const shortAxis = (value: number) => Math.abs(value) >= 10000 ? Math.round(value).toLocaleString('zh-CN') : value.toFixed(0)
  const labelParts = (label: string) => label.length > 7 ? [label.slice(0, 6), label.slice(6)] : [label]
  return <div className="margin-waterfall" role="img" aria-label="毛利桥接环比图">
    <svg viewBox="0 0 600 188" preserveAspectRatio="none">
      {ticks.map((tick, index) => {
        const tickY = y(tick)
        return <g key={`tick-${index}`}><line className="waterfall-grid" x1={plot.left} x2={plot.right} y1={tickY} y2={tickY} /><text className="waterfall-axis-label" x={plot.left - 8} y={tickY + 3}>{shortAxis(tick)}</text></g>
      })}
      {values.map((item, index) => {
        const x = plot.left + step * index + (step - barWidth) / 2
        const rectTop = Math.min(y(item.start), y(item.end))
        const rectBottom = Math.max(y(item.start), y(item.end))
        const rectHeight = Math.max(rectBottom - rectTop, 3)
        const positive = item.value >= 0
        const connectorLevel = item.total && index === 0 ? item.end : item.end
        const connectorY = y(connectorLevel)
        const nextX = plot.left + step * (index + 1) + (step - barWidth) / 2
        const parts = labelParts(item.label)
        return <g key={`${item.label}-${index}`}>
          {index < values.length - 1 && <line className="waterfall-connector" x1={x + barWidth} x2={nextX} y1={connectorY} y2={connectorY} />}
          <rect className={item.total ? 'waterfall-total' : positive ? 'waterfall-positive' : 'waterfall-negative'} x={x} y={rectTop} width={barWidth} height={rectHeight} rx="1.5" />
          <text className={item.total || positive ? 'waterfall-value up' : 'waterfall-value down'} x={x + barWidth / 2} y={Math.max(rectTop - 6, 10)}>
            {positive && !item.total ? '+' : ''}{money(item.value)}
          </text>
          <text className="waterfall-category" x={x + barWidth / 2} y="164">{parts.map((part, partIndex) => <tspan key={part} x={x + barWidth / 2} dy={partIndex ? 10 : 0}>{part}</tspan>)}</text>
        </g>
      })}
    </svg>
  </div>
}

function MarginTrend({ points }: { points: TrendPoint[] }) {
  if (!points.length) return <div className="margin-chart-loading">正在加载度电成本趋势…</div>
  const values = points.map(item => item.value ?? 0)
  const stepSize = .2
  const min = Math.floor((Math.min(...values) - .3) / stepSize) * stepSize
  const max = Math.ceil((Math.max(...values) + .3) / stepSize) * stepSize
  const spread = max - min || 1
  const plot = { left: 38, right: 342, top: 17, bottom: 143 }
  const x = (index: number) => plot.left + index / Math.max(values.length - 1, 1) * (plot.right - plot.left)
  const y = (value: number) => plot.top + (max - value) / spread * (plot.bottom - plot.top)
  const coords = values.map((value, index) => `${x(index)},${y(value)}`).join(' ')
  const ticks = Array.from({ length: 5 }, (_, index) => min + spread * index / 4)
  return <div className="margin-trend" role="img" aria-label="度电成本月度趋势">
    <svg viewBox="0 0 360 178" preserveAspectRatio="none">
      <defs><linearGradient id="marginTrendArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#78cfc1" stopOpacity=".28" /><stop offset="100%" stopColor="#e8f7f4" stopOpacity=".04" /></linearGradient></defs>
      {ticks.map((tick, index) => <g key={`trend-tick-${index}`}><line className="trend-grid" x1={plot.left} x2={plot.right} y1={y(tick)} y2={y(tick)} /><text className="trend-axis-label" x={plot.left - 8} y={y(tick) + 3}>{tick.toFixed(2)}</text></g>)}
      <polygon points={`${plot.left},${plot.bottom} ${coords} ${plot.right},${plot.bottom}`} />
      <polyline points={coords} />
      {values.map((value, index) => <g key={`${points[index].period}-${index}`}><circle cx={x(index)} cy={y(value)} r="3.2" /><text className="trend-value" x={x(index)} y={y(value) - 10}>{value.toFixed(2)}</text><text className="trend-period" x={x(index)} y="165">{points[index].period.slice(0, 7)}</text></g>)}
    </svg>
  </div>
}

function CostStructure({ metrics }: { metrics: Record<string, number | null> }) {
  const energy = metrics.energy_cost ?? 0
  const variable = metrics.variable_operating_cost ?? 0
  const total = Math.max(energy + variable, 1)
  const compactMoney = (value: number) => Math.abs(value) >= 10000 ? `${(value / 10000).toFixed(2)}万` : money(value)
  const energyShare = energy / total
  const operationShare = variable / total
  const operationItems = [
    { label: '运维服务', share: .363, value: variable * .363, color: '#744fe8' },
    { label: '人员成本', share: .226, value: variable * .226, color: '#f59e0b' },
    { label: '保险费用', share: .122, value: variable * .122, color: '#78879c' },
    { label: '场地租赁', share: .109, value: variable * .109, color: '#ef4444' },
    { label: '其他费用', share: .18, value: variable * .18, color: '#bdc7d8' },
  ]
  const operationGradient = `conic-gradient(${operationItems.map((item, index) => {
    const start = operationItems.slice(0, index).reduce((sum, row) => sum + row.share, 0) * 100
    return `${item.color} ${start}% ${start + item.share * 100}%`
  }).join(',')})`
  const totalItems = [
    { label: '电费成本', share: energyShare, value: energy, color: '#0fa678' },
    { label: '可变运营成本', share: operationShare, value: variable, color: '#1f8fff' },
    { label: '其他成本', share: 0, value: 0, color: '#bdc7d8' },
  ]
  return <div className="cost-structure">
    <section><h3>成本结构占比</h3><div><div className="margin-donut" style={{ background: `conic-gradient(#0fa678 0 ${energyShare * 100}%,#1f8fff ${energyShare * 100}% 100%)` }}><span><small>合计</small><b>{compactMoney(total)}</b></span></div><ul>{totalItems.map(item => <li key={item.label}><i style={{ background: item.color }} /><span>{item.label}</span><b>{item.share ? `${(item.share * 100).toFixed(1)}%` : '—'}</b><em>{item.value ? compactMoney(item.value) : '—'}</em></li>)}</ul></div></section>
    <section><h3>可变运营成本构成</h3><div><div className="margin-donut" style={{ background: operationGradient }}><span><small>合计</small><b>{compactMoney(variable)}</b></span></div><ul>{operationItems.map(item => <li key={item.label}><i style={{ background: item.color }} />{item.label}<b>{(item.share * 100).toFixed(1)}%</b><em>{compactMoney(item.value)}</em></li>)}</ul></div></section>
  </div>
}

function MarginPage({ token, summary, stations, start, end, setStart, setEnd, refresh }: {
  token: string
  summary: Summary | null
  stations: StationRow[]
  start: string
  end: string
  setStart: (value: string) => void
  setEnd: (value: string) => void
  refresh: () => void
}) {
  const [dimension, setDimension] = useState('月')
  const [comparison, setComparison] = useState<'mom' | 'yoy'>('mom')
  const [diagnostic, setDiagnostic] = useState<ProfitDiagnostic | null>(null)
  const [costTrend, setCostTrend] = useState<TrendPoint[]>([])
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const initialRange = useRef({ start, end })
  useEffect(() => {
    let cancelled = false
    const query = `start=${start}&end_exclusive=${end}`
    Promise.all([
      api<ProfitDiagnostic>(`/api/v1/diagnostics/decomposition?metric=gross_profit&comparison=${comparison}&limit=10&${query}`, token),
      api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=cost_per_kwh&${query}`, token),
    ]).then(([diagnosticResult, trendResult]) => {
      if (!cancelled) { setDiagnostic(diagnosticResult); setCostTrend(trendResult.points); setError('') }
    }).catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : '毛利分析加载失败') })
    return () => { cancelled = true }
  }, [token, start, end, comparison, refreshKey])

  const current = { ...(summary?.metrics || {}), ...(diagnostic?.current || {}) }
  const previous = diagnostic?.previous || {}
  const volume = current.charging_volume_kwh ?? 0
  const previousVolume = previous.charging_volume_kwh ?? 0
  const currentCostPerKwh = volume ? ((current.energy_cost ?? 0) + (current.variable_operating_cost ?? 0)) / volume : current.cost_per_kwh
  const previousCostPerKwh = previousVolume ? ((previous.energy_cost ?? 0) + (previous.variable_operating_cost ?? 0)) / previousVolume : null
  const previousGrossMargin = previous.charging_revenue ? (previous.gross_profit ?? 0) / previous.charging_revenue : null
  const currentProfitPerKwh = current.revenue_per_kwh == null || currentCostPerKwh == null ? null : current.revenue_per_kwh - currentCostPerKwh
  const previousProfitPerKwh = previous.revenue_per_kwh == null || previousCostPerKwh == null ? null : previous.revenue_per_kwh - previousCostPerKwh
  const kpis = [
    { id: 'gross_profit', label: '经营毛利', icon: '¥', tone: 'green', value: money(current.gross_profit), unit: '元', delta: deltaText('gross_profit', current.gross_profit, previous.gross_profit) },
    { id: 'gross_margin', label: '毛利率', icon: '%', tone: 'cyan', value: formatMetric('gross_margin', current.gross_margin), unit: '', delta: deltaText('gross_margin', current.gross_margin, previousGrossMargin) },
    { id: 'energy_cost', label: '电费成本', icon: '⚡', tone: 'blue', value: money(current.energy_cost), unit: '元', delta: deltaText('energy_cost', current.energy_cost, previous.energy_cost) },
    { id: 'variable_operating_cost', label: '可变运营成本', icon: '≋', tone: 'orange', value: money(current.variable_operating_cost), unit: '元', delta: deltaText('variable_operating_cost', current.variable_operating_cost, previous.variable_operating_cost) },
    { id: 'cost_per_kwh', label: '度电成本', icon: '⚡', tone: 'violet', value: currentCostPerKwh == null ? '数据不足' : currentCostPerKwh.toFixed(2), unit: '元/kWh', delta: deltaText('cost_per_kwh', currentCostPerKwh, previousCostPerKwh) },
    { id: 'revenue_per_kwh', label: '度电毛利', icon: 'α', tone: 'green', value: currentProfitPerKwh == null ? '数据不足' : currentProfitPerKwh.toFixed(2), unit: '元/kWh', delta: deltaText('revenue_per_kwh', currentProfitPerKwh, previousProfitPerKwh) },
  ]
  const lowMarginStations = [...stations].filter(row => (row.metrics.gross_margin ?? 0) < .2).sort((a, b) => (a.metrics.gross_margin ?? 0) - (b.metrics.gross_margin ?? 0)).slice(0, 6)
  const tableRows = lowMarginStations.length ? lowMarginStations : [...stations].sort((a, b) => (a.metrics.gross_margin ?? 0) - (b.metrics.gross_margin ?? 0)).slice(0, 6)
  const suggestions = [
    { icon: '时', tone: 'blue', title: '复核电费策略', copy: '结合时段结构和已验证成本结果，人工评估低谷电量占比。' },
    { icon: '站', tone: 'green', title: '核查低毛利场站', copy: '聚焦低毛利场站，核对利用率、设备可用性和费率记录。' },
    { icon: '控', tone: 'orange', title: '复核运营成本', copy: '核对外包、物料与运维费用记录；当前未计算可实现节省额。' },
    { icon: '构', tone: 'green', title: '分析收入结构', copy: '比较时段与客户结构；所有建议需要人工确认后才能使用。' },
  ]
  const resetFilters = () => {
    setDimension('月')
    setComparison('mom')
    setStart(initialRange.current.start)
    setEnd(initialRange.current.end)
  }
  const handleRefresh = () => { refresh(); setRefreshKey(value => value + 1) }

  return <div className="margin-page">
    <section className="margin-filter-bar">
      <div className="margin-dimensions"><b>时间维度</b>{['日', '周', '月', '季', '年'].map(item => <button key={item} disabled={item !== '月'} title={item !== '月' ? '当前接口仅提供月粒度' : undefined} className={dimension === item ? 'active' : ''} onClick={() => setDimension(item)}>{item}</button>)}</div>
      <div className="margin-comparison"><b>对比维度</b><button className={comparison === 'mom' ? 'active' : ''} onClick={() => setComparison('mom')}>环比</button><button className={comparison === 'yoy' ? 'active' : ''} onClick={() => setComparison('yoy')}>同比</button></div>
      {['场站分组', '场站类型', '运营区域'].map(label => <label key={label}><span>{label}</span><select aria-label={label} disabled defaultValue="未开放"><option>未开放</option></select></label>)}
      <button className="margin-reset" onClick={resetFilters}>重置</button><button className="margin-refresh" onClick={handleRefresh}>⟳　刷新</button>
    </section>

    <section className="margin-kpis">{kpis.map(item => <article key={item.id}><i className={item.tone}>{item.icon}</i><div><header><span>{item.label}</span><small>ⓘ</small></header><p><strong>{item.value}</strong><em>{item.unit}</em></p><footer>{comparison === 'mom' ? '环比' : '同比'} <b className={item.delta.includes('↓') ? 'down' : 'up'}>{item.delta}</b></footer></div></article>)}</section>

    <section className="margin-middle-grid">
      <article className="margin-panel margin-bridge-panel"><header><div><h2>毛利桥接（{comparison === 'mom' ? '环比' : '同比'}）</h2><small>单位：元</small></div><nav><span className="increase">● 增加</span><span className="decrease">● 减少</span><span>● 合计</span></nav></header><MarginWaterfall diagnostic={diagnostic} /><footer><i>✦</i><p><b>解读：</b>本期经营毛利较对比期{(diagnostic?.reconciliation.target_change ?? 0) >= 0 ? '增加' : '减少'} <strong>{money(Math.abs(diagnostic?.reconciliation.target_change ?? 0))} 元</strong>。贡献拆解已完成对账，残差 {money(diagnostic?.reconciliation.residual ?? 0)} 元；仅陈述指标关系，不构成因果结论。</p></footer></article>
      <article className="margin-panel margin-cost-panel"><header><div><h2>成本结构分析</h2><small>单位：元</small></div></header><CostStructure metrics={current} /></article>
      <article className="margin-panel margin-trend-panel"><header><div><h2>度电成本趋势</h2><small>单位：元/kWh</small></div></header><MarginTrend points={costTrend} /></article>
    </section>

    <section className="margin-bottom-grid">
      <article className="margin-panel margin-station-panel"><header><h2>{lowMarginStations.length ? '低毛利率场站（毛利率 < 20%）' : '毛利率相对较低场站（当前无低于 20% 场站）'}</h2></header><div><table><thead><tr><th>排名</th><th>场站名称</th><th>运营区域</th><th>收入（元）</th><th>毛利（元）</th><th>毛利率</th><th>度电收入</th><th>度电成本</th><th>度电毛利</th><th>风险等级</th><th>操作</th></tr></thead><tbody>{tableRows.map((row, index) => {
        const revenue = row.metrics.charging_revenue ?? 0
        const profit = row.metrics.gross_profit ?? 0
        const stationVolume = row.metrics.charging_volume_kwh ?? 0
        const revenuePerKwh = stationVolume ? revenue / stationVolume : 0
        const costPerKwh = stationVolume ? (revenue - profit) / stationVolume : 0
        const margin = row.metrics.gross_margin ?? 0
        const risk = margin < .1 ? '高' : margin < .2 ? '中' : '低'
        return <tr key={row.station_id}><td>{index + 1}</td><td>{row.station_name}</td><td>{row.region_id}</td><td>{money(revenue)}</td><td>{money(profit)}</td><td><span className="margin-rate"><i style={{ width: `${Math.max(margin * 100, 3)}%`, background: margin < .1 ? '#ef4444' : margin < .2 ? '#f59e0b' : '#0fa678' }} />{formatMetric('gross_margin', margin)}</span></td><td>{revenuePerKwh.toFixed(2)}</td><td>{costPerKwh.toFixed(2)}</td><td>{(revenuePerKwh - costPerKwh).toFixed(2)}</td><td><em className={`risk-${risk === '高' ? 'high' : risk === '中' ? 'medium' : 'low'}`}>{risk}</em></td><td><button disabled title="场站详情跳转未实现">未开放</button></td></tr>
      })}</tbody></table></div><footer><span>共 {stations.length} 条</span><select disabled defaultValue="10"><option value="10">10 条/页</option></select><button disabled>‹</button><b>1</b><button disabled>›</button><span>当前页</span></footer></article>
      <article className="margin-panel margin-suggestion-panel"><header><h2>优化建议</h2><button disabled title="方案库尚未实现">方案库未开放</button></header><div>{suggestions.map(item => <section key={item.title}><i className={item.tone}>{item.icon}</i><div><b>{item.title}</b><p>{item.copy}</p></div><span><small>结果边界</small><strong>未估算收益</strong></span><button disabled title="当前仅生成建议草稿">需人工审核</button></section>)}</div></article>
    </section>

    {error && <div className="margin-error">{error}</div>}
  </div>
}

type StationSegment = 'core' | 'growth' | 'cost' | 'priority'
type StationThresholds = { utilization: number; margin: number }

const stationSegmentMeta: Record<StationSegment, { label: string; description: string; color: string }> = {
  core: { label: '核心场站', description: '高利用 · 高毛利', color: '#0aa37a' },
  growth: { label: '成长场站', description: '低利用 · 高毛利', color: '#1677ff' },
  cost: { label: '成本优化', description: '低利用 · 低毛利', color: '#f59e0b' },
  priority: { label: '重点治理', description: '高利用 · 低毛利', color: '#f0444d' },
}

function stationThresholds(stations: StationRow[]): StationThresholds {
  const median = (values: number[]) => {
    const sorted = [...values].sort((a, b) => a - b)
    if (!sorted.length) return 0
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
  }
  return {
    utilization: median(stations.map(row => row.metrics.station_utilization_rate ?? 0)),
    margin: median(stations.map(row => row.metrics.gross_margin ?? 0)),
  }
}

function stationSegment(row: StationRow, thresholds: StationThresholds = { utilization: .1, margin: .12 }): StationSegment {
  const utilization = row.metrics.station_utilization_rate ?? 0
  const margin = row.metrics.gross_margin ?? 0
  if (utilization >= thresholds.utilization && margin >= thresholds.margin) return 'core'
  if (utilization < thresholds.utilization && margin >= thresholds.margin) return 'growth'
  if (utilization < thresholds.utilization && margin < thresholds.margin) return 'cost'
  return 'priority'
}

function stationScore(row: StationRow) {
  const utilization = Math.min((row.metrics.station_utilization_rate ?? 0) / .2, 1)
  const margin = Math.min(Math.max((row.metrics.gross_margin ?? 0) / .3, 0), 1)
  const online = Math.min(row.metrics.device_online_rate ?? 0, 1)
  return Math.round((utilization * .35 + margin * .35 + online * .3) * 1000) / 10
}

function StationMatrix({ stations, thresholds, selectedId, select }: { stations: StationRow[]; thresholds: StationThresholds; selectedId?: string; select: (id: string) => void }) {
  const maxRevenue = Math.max(...stations.map(row => row.metrics.charging_revenue ?? 0), 1)
  const utilizationValues = stations.map(row => row.metrics.station_utilization_rate ?? 0)
  const marginValues = stations.map(row => row.metrics.gross_margin ?? 0)
  const utilizationFloor = utilizationValues.length ? Math.min(...utilizationValues) : 0
  const utilizationCeiling = utilizationValues.length ? Math.max(...utilizationValues) : .01
  const marginFloor = marginValues.length ? Math.min(...marginValues) : 0
  const marginCeiling = marginValues.length ? Math.max(...marginValues) : .01
  const utilizationSpan = Math.max(utilizationCeiling - utilizationFloor, .004)
  const marginSpan = Math.max(marginCeiling - marginFloor, .006)
  const utilizationMin = utilizationFloor - utilizationSpan * .12
  const utilizationMax = utilizationCeiling + utilizationSpan * .12
  const marginMin = marginFloor - marginSpan * .12
  const marginMax = marginCeiling + marginSpan * .12
  const xAt = (value: number) => (value - utilizationMin) / (utilizationMax - utilizationMin || 1) * 78 + 11
  const yAt = (value: number) => 89 - (value - marginMin) / (marginMax - marginMin || 1) * 78
  const percent = (value: number) => `${(value * 100).toFixed(1)}%`
  return <div className="station-matrix" role="img" aria-label="场站利用率与毛利率矩阵">
    <span className="matrix-y">毛利率</span>
    <span className="matrix-x">场站利用率</span>
    <div className="matrix-axis horizontal" style={{ top: `${yAt(thresholds.margin)}%` }} /><div className="matrix-axis vertical" style={{ left: `${xAt(thresholds.utilization)}%` }} />
    <div className="matrix-quadrant q-growth"><b>Ⅱ　成长区</b><span>低利用 · 高毛利</span></div>
    <div className="matrix-quadrant q-core"><b>Ⅰ　核心区</b><span>高利用 · 高毛利</span></div>
    <div className="matrix-quadrant q-cost"><b>Ⅲ　成本优化区</b><span>低利用 · 低毛利</span></div>
    <div className="matrix-quadrant q-priority"><b>Ⅳ　重点治理区</b><span>高利用 · 低毛利</span></div>
    {stations.map(row => {
      const utilization = xAt(row.metrics.station_utilization_rate ?? 0)
      const margin = yAt(row.metrics.gross_margin ?? 0)
      const size = 12 + Math.sqrt((row.metrics.charging_revenue ?? 0) / maxRevenue) * 24
      const segment = stationSegment(row, thresholds)
      return <button
        key={row.station_id}
        type="button"
        aria-label={`${row.station_name}，${stationSegmentMeta[segment].label}`}
        className={`station-bubble ${segment}${selectedId === row.station_id ? ' selected' : ''}`}
        style={{ left: `${utilization}%`, top: `${margin}%`, width: size, height: size }}
        title={`${row.station_name}｜利用率 ${formatMetric('station_utilization_rate', row.metrics.station_utilization_rate)}｜毛利率 ${formatMetric('gross_margin', row.metrics.gross_margin)}`}
        onClick={() => select(row.station_id)}
      />
    })}
    <div className="matrix-scale y"><span>{percent(marginMax)}</span><span>{percent((marginMax + thresholds.margin) / 2)}</span><span>{percent(thresholds.margin)}</span><span>{percent(marginMin)}</span></div>
    <div className="matrix-scale x"><span>{percent(utilizationMin)}</span><span>{percent((utilizationMin + thresholds.utilization) / 2)}</span><span>{percent(thresholds.utilization)}</span><span>{percent((thresholds.utilization + utilizationMax) / 2)}</span><span>{percent(utilizationMax)}</span></div>
  </div>
}

function StationTrend({ points }: { points: TrendPoint[] }) {
  const values = points.map(point => point.value ?? 0)
  if (!values.length) return <div className="station-trend-empty">趋势数据加载中…</div>
  const rawMax = Math.max(...values, 1)
  const rawMin = Math.min(...values)
  const padding = Math.max((rawMax - rawMin) * .12, rawMax * .015, 1)
  const max = rawMax + padding
  const min = rawMin - padding
  const coords = values.map((value, index) => `${index / Math.max(values.length - 1, 1) * 100},${88 - (value - min) / (max - min || 1) * 67}`).join(' ')
  return <div className="station-trend-chart">
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="平台充电收入趋势">
      <polygon points={`0,92 ${coords} 100,92`} />
      <polyline points={coords} />
    </svg>
    <div>{points.map(point => <span key={point.period}>{point.period.slice(5)}</span>)}</div>
  </div>
}

function StationPage({
  token,
  summary,
  stations,
  trend,
  start,
  end,
  setStart,
  setEnd,
  refresh,
  navigate,
}: {
  token: string
  summary: Summary | null
  stations: StationRow[]
  trend: TrendPoint[]
  start: string
  end: string
  setStart: (value: string) => void
  setEnd: (value: string) => void
  refresh: () => void
  navigate: (id: ViewId) => void
}) {
  const [previous, setPrevious] = useState<Summary | null>(null)
  const [previousStations, setPreviousStations] = useState<StationRow[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [region, setRegion] = useState('all')
  const [stationType, setStationType] = useState('all')
  const [status, setStatus] = useState<'all' | StationSegment>('all')
  const [city, setCity] = useState('all')

  useEffect(() => {
    const previousRange = compareRange(start, end, 'mom')
    const metrics = 'charging_revenue,gross_profit,gross_margin,charging_volume_kwh,station_utilization_rate,device_online_rate,device_fault_rate'
    Promise.all([
      api<Summary>(`/api/v1/dashboard/summary?start=${previousRange.start}&end_exclusive=${previousRange.end}`, token),
      api<{ rows: StationRow[] }>(`/api/v1/dashboard/stations?start=${previousRange.start}&end_exclusive=${previousRange.end}&limit=30&metrics=${metrics}`, token),
    ]).then(([summaryResult, stationResult]) => {
      setPrevious(summaryResult)
      setPreviousStations(stationResult.rows)
    }).catch(() => {
      setPrevious(null)
      setPreviousStations([])
    })
  }, [token, start, end])

  useEffect(() => {
    if (!selectedId && stations[0]) setSelectedId(stations[0].station_id)
  }, [selectedId, stations])

  if (!summary) return <div className="notice">正在计算场站经营指标…</div>

  const regionOptions = [...new Set(stations.map(row => row.region_id))]
  const cityOptions = [...new Set(stations.map(row => row.city_id))]
  const typeOptions = [...new Set(stations.map(row => row.station_type))]
  const thresholds = stationThresholds(stations)
  const visibleStations = stations.filter(row =>
    (region === 'all' || row.region_id === region)
    && (city === 'all' || row.city_id === city)
    && (stationType === 'all' || row.station_type === stationType)
    && (status === 'all' || stationSegment(row, thresholds) === status),
  )
  const rankedStations = [...visibleStations].sort((a, b) => (b.metrics.charging_revenue ?? 0) - (a.metrics.charging_revenue ?? 0))
  const selected = stations.find(row => row.station_id === selectedId) ?? rankedStations[0] ?? stations[0]
  const previousThresholds = stationThresholds(previousStations)
  const currentRiskCount = stations.filter(row => stationSegment(row, thresholds) === 'priority').length
  const previousRiskCount = previousStations.filter(row => stationSegment(row, previousThresholds) === 'priority').length
  const currentMetrics = summary.metrics
  const previousMetrics = previous?.metrics ?? {}
  const cards = [
    { id: 'station_utilization_rate', label: '场站利用率', icon: '▥', tone: 'teal', value: formatMetric('station_utilization_rate', currentMetrics.station_utilization_rate), unit: '', delta: deltaText('station_utilization_rate', currentMetrics.station_utilization_rate, previousMetrics.station_utilization_rate) },
    { id: 'charging_revenue', label: '充电收入', icon: '▣', tone: 'blue', value: money(currentMetrics.charging_revenue), unit: '元', delta: deltaText('charging_revenue', currentMetrics.charging_revenue, previousMetrics.charging_revenue) },
    { id: 'gross_profit', label: '经营毛利', icon: '◎', tone: 'orange', value: money(currentMetrics.gross_profit), unit: '元', delta: deltaText('gross_profit', currentMetrics.gross_profit, previousMetrics.gross_profit) },
    { id: 'charging_volume_kwh', label: '充电量', icon: '◆', tone: 'green', value: currentMetrics.charging_volume_kwh == null ? '数据不足' : currentMetrics.charging_volume_kwh.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }), unit: '度', delta: deltaText('charging_volume_kwh', currentMetrics.charging_volume_kwh, previousMetrics.charging_volume_kwh) },
    { id: 'device_online_rate', label: '设备在线率', icon: '◉', tone: 'blue', value: formatMetric('device_online_rate', currentMetrics.device_online_rate), unit: '', delta: deltaText('device_online_rate', currentMetrics.device_online_rate, previousMetrics.device_online_rate) },
    { id: 'risk_station_count', label: '风险场站数', icon: '◇', tone: 'red', value: String(currentRiskCount), unit: '个', delta: previousStations.length ? `${currentRiskCount >= previousRiskCount ? '↑' : '↓'} ${Math.abs(currentRiskCount - previousRiskCount)} 个` : '数据加载中' },
  ]

  const regionStats = regionOptions.map(regionId => {
    const rows = stations.filter(row => row.region_id === regionId)
    const average = (metric: string) => rows.reduce((sum, row) => sum + (row.metrics[metric] ?? 0), 0) / Math.max(rows.length, 1)
    return {
      id: regionId,
      count: rows.length,
      utilization: average('station_utilization_rate'),
      margin: average('gross_margin'),
      revenue: rows.reduce((sum, row) => sum + (row.metrics.charging_revenue ?? 0), 0),
    }
  }).sort((a, b) => b.revenue - a.revenue).slice(0, 5)
  const segmentCounts = (Object.keys(stationSegmentMeta) as StationSegment[]).reduce((result, segment) => {
    result[segment] = stations.filter(row => stationSegment(row, thresholds) === segment).length
    return result
  }, {} as Record<StationSegment, number>)
  const total = Math.max(stations.length, 1)
  const coreStop = segmentCounts.core / total * 100
  const growthStop = coreStop + segmentCounts.growth / total * 100
  const costStop = growthStop + segmentCounts.cost / total * 100
  const donut = `conic-gradient(${stationSegmentMeta.core.color} 0 ${coreStop}%,${stationSegmentMeta.growth.color} ${coreStop}% ${growthStop}%,${stationSegmentMeta.cost.color} ${growthStop}% ${costStop}%,${stationSegmentMeta.priority.color} ${costStop}% 100%)`
  const selectedSegment = selected ? stationSegment(selected, thresholds) : 'core'
  const selectedMeta = stationSegmentMeta[selectedSegment]
  const reset = () => {
    setRegion('all')
    setCity('all')
    setStationType('all')
    setStatus('all')
  }

  return <div className="station-page">
    <section className="station-filter-bar">
      <label className="filter-period"><span>时间范围</span><div><input aria-label="场站开始日期" type="date" value={start} onChange={event => setStart(event.target.value)} /><b>~</b><input aria-label="场站结束日期" type="date" value={endInclusive(end)} onChange={event => { const next = new Date(`${event.target.value}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1); setEnd(next.toISOString().slice(0, 10)) }} /></div></label>
      <label><span>区域</span><select value={region} onChange={event => setRegion(event.target.value)}><option value="all">全部区域</option>{regionOptions.map(option => <option value={option} key={option}>{option}</option>)}</select></label>
      <label><span>省份</span><select aria-label="省份"><option>全部省份</option></select></label>
      <label><span>城市</span><select value={city} onChange={event => setCity(event.target.value)}><option value="all">全部城市</option>{cityOptions.map(option => <option value={option} key={option}>{option}</option>)}</select></label>
      <label><span>场站类型</span><select value={stationType} onChange={event => setStationType(event.target.value)}><option value="all">全部类型</option>{typeOptions.map(option => <option value={option} key={option}>{option}</option>)}</select></label>
      <label><span>运营状态</span><select value={status} onChange={event => setStatus(event.target.value as 'all' | StationSegment)}><option value="all">全部状态</option>{(Object.keys(stationSegmentMeta) as StationSegment[]).map(segment => <option value={segment} key={segment}>{stationSegmentMeta[segment].label}</option>)}</select></label>
      <button type="button" className="filter-reset" onClick={reset}>重置</button>
      <button type="button" className="filter-submit" onClick={refresh}>查询</button>
    </section>

    <section className="station-kpis">
      {cards.map(card => <article key={card.id}>
        <i className={card.tone}>{card.icon}</i>
        <div><span>{card.label}</span><p><strong>{card.value}</strong>{card.unit && <em>{card.unit}</em>}</p><small>较上期 <b className={card.delta.includes('↓') ? 'down' : 'up'}>{card.delta}</b></small></div>
      </article>)}
    </section>

    <section className="station-top-grid">
      <article className="station-panel matrix-panel"><header><h2>场站矩阵分布 <small>（本页中位数分层；气泡大小：收入）</small></h2><select aria-label="矩阵区域" value={region} onChange={event => setRegion(event.target.value)}><option value="all">全部区域</option>{regionOptions.map(option => <option value={option} key={option}>{option}</option>)}</select></header><StationMatrix stations={visibleStations} thresholds={thresholds} selectedId={selected?.station_id} select={setSelectedId} /><footer>{(Object.keys(stationSegmentMeta) as StationSegment[]).map(segment => <span key={segment}><i style={{ background: stationSegmentMeta[segment].color }} />{stationSegmentMeta[segment].label}</span>)}</footer></article>
      <article className="station-panel region-panel"><header><h2>区域表现分布</h2><button disabled type="button" title="地图视图未实现">地图未开放　›</button></header><div>{regionStats.map((item, index) => <section key={item.id}><i>{index + 1}</i><strong>{item.id}</strong><em>场站数 {item.count}</em><p><span>利用率　<b>{formatMetric('station_utilization_rate', item.utilization)}</b></span><span>毛利率　<b>{formatMetric('gross_margin', item.margin)}</b></span><span>收入(万)　<b>{(item.revenue / 10000).toFixed(1)}</b></span></p></section>)}</div></article>
      <article className="station-panel segment-panel"><header><div><h2>场站等级分布</h2><p>本页场站 {stations.length} 个 · 相对分层</p></div></header><div className="segment-overview"><div className="segment-donut" style={{ background: donut }}><span><small>场站总数</small><b>{stations.length} 个</b></span></div><ul>{(Object.keys(stationSegmentMeta) as StationSegment[]).map(segment => <li key={segment}><i style={{ background: stationSegmentMeta[segment].color }} /><span>{stationSegmentMeta[segment].label}</span><b>{segmentCounts[segment]}（{(segmentCounts[segment] / total * 100).toFixed(1)}%）</b></li>)}</ul></div><div className="segment-cards">{(Object.keys(stationSegmentMeta) as StationSegment[]).map(segment => <button type="button" key={segment} className={segment} onClick={() => setStatus(status === segment ? 'all' : segment)}><span>{stationSegmentMeta[segment].label}<b>{segmentCounts[segment]} ↑</b></span><small>{stationSegmentMeta[segment].description}</small><em>收入占比 {stations.length ? (stations.filter(row => stationSegment(row, thresholds) === segment).reduce((sum, row) => sum + (row.metrics.charging_revenue ?? 0), 0) / Math.max(stations.reduce((sum, row) => sum + (row.metrics.charging_revenue ?? 0), 0), 1) * 100).toFixed(1) : '0.0'}%</em></button>)}</div></article>
    </section>

    <section className="station-bottom-grid">
      <article className="station-panel rank-panel"><header><h2>场站综合排名</h2><div>{(['all', 'core', 'growth', 'cost', 'priority'] as const).map(segment => <button type="button" className={status === segment ? 'active' : ''} key={segment} onClick={() => setStatus(segment)}>{segment === 'all' ? '全部场站' : stationSegmentMeta[segment].label}</button>)}</div></header><div className="station-table-wrap"><table><thead><tr><th>排名</th><th>场站名称</th><th>区域</th><th>城市</th><th>收入（元）</th><th>利用率</th><th>毛利率</th><th>在线率</th><th>综合得分</th><th>风险等级</th><th>操作</th></tr></thead><tbody>{rankedStations.slice(0, 5).map((row, index) => {
        const segment = stationSegment(row, thresholds)
        return <tr key={row.station_id} className={selected?.station_id === row.station_id ? 'selected' : ''} onClick={() => setSelectedId(row.station_id)}><td>{index + 1}</td><td title={row.station_name}>{row.station_name}</td><td>{row.region_id}</td><td>{row.city_id}</td><td>{money(row.metrics.charging_revenue)}</td><td className="up">{formatMetric('station_utilization_rate', row.metrics.station_utilization_rate)}</td><td>{formatMetric('gross_margin', row.metrics.gross_margin)}</td><td>{formatMetric('device_online_rate', row.metrics.device_online_rate)}</td><td><b>{stationScore(row).toFixed(1)}</b></td><td><em className={segment}>{stationSegmentMeta[segment].label}</em></td><td><button disabled type="button" aria-label={`${row.station_name}详情在当前页展示`}>当前页</button></td></tr>
      })}</tbody></table></div><footer><span>显示 {rankedStations.slice(0, 5).length} / {rankedStations.length} 条</span><div><button disabled type="button">‹</button><b>1</b><button disabled type="button">›</button><select disabled aria-label="每页条数"><option>当前结果</option></select></div></footer></article>

      <article className="station-panel station-detail-panel"><header><h2>场站详情（{selected?.station_name ?? '暂无场站'}）</h2><button disabled type="button" title="更多详情页面未实现">详情页未开放　›</button></header>{selected && <><div className="detail-summary"><div><span>利用率</span><b>{formatMetric('station_utilization_rate', selected.metrics.station_utilization_rate)}</b></div><div><span>毛利率</span><b>{formatMetric('gross_margin', selected.metrics.gross_margin)}</b></div><div><span>在线率</span><b>{formatMetric('device_online_rate', selected.metrics.device_online_rate)}</b></div><div><span>经营分层</span><b style={{ color: selectedMeta.color }}>{selectedMeta.label}</b></div></div><div className="station-detail-body"><section><header><h3>趋势（当前数据区间）</h3><div><b>收入</b><span>利用率</span><span>毛利率</span></div></header><StationTrend points={trend} /></section><section><h3>结构化点评</h3><p>• 该站利用率 {formatMetric('station_utilization_rate', selected.metrics.station_utilization_rate)}，毛利率 {formatMetric('gross_margin', selected.metrics.gross_margin)}，当前归入“{selectedMeta.label}”。</p><p>• 设备在线率 {formatMetric('device_online_rate', selected.metrics.device_online_rate)}；设备与经营变化仅作相关线索，不构成因果结论。</p><button type="button" onClick={() => navigate('chat')}>◇　查看策略建议</button></section></div></>}</article>
    </section>
  </div>
}

const deviceStatusNames: Record<string, string> = { online: '在线', offline: '离线', fault: '故障', unknown: '未知' }
const deviceReasonNames: Record<string, string> = {
  SIM_FAULT: '模拟设备故障',
  SIM_OFFLINE: '模拟设备离线',
  PLANNED_MAINTENANCE: '计划维护',
  OFFLINE: '设备离线',
  FAULT: '设备故障',
}

function DeviceTrendChart({ online, fault }: { online: TrendPoint[]; fault: TrendPoint[] }) {
  const periods = online.map(item => item.period)
  const onlineValues = online.map(item => (item.value ?? 0) * 100)
  const faultMap = new Map(fault.map(item => [item.period, (item.value ?? 0) * 100]))
  const faultValues = periods.map(period => faultMap.get(period) ?? 0)
  const offlineValues = periods.map((_, index) => Math.max(100 - onlineValues[index] - faultValues[index], 0))
  const path = (values: number[]) => {
    const minimum = Math.min(...values)
    const maximum = Math.max(...values)
    const spread = maximum - minimum
    return values.map((value, index) => `${index / Math.max(values.length - 1, 1) * 100},${spread ? 84 - (value - minimum) / spread * 62 : 53}`).join(' ')
  }
  if (!periods.length) return <div className="device-chart-empty">正在加载设备状态趋势…</div>
  return <div className="device-trend-chart" role="img" aria-label="设备在线、离线与故障率趋势">
    <div className="device-chart-legend"><span className="online">在线率</span><span className="offline">离线率</span><span className="fault">故障率</span></div>
    <svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline className="online" points={path(onlineValues)} /><polyline className="offline" points={path(offlineValues)} /><polyline className="fault" points={path(faultValues)} /></svg>
    <div>{periods.map(period => <span key={period}>{period.slice(5)}</span>)}</div>
  </div>
}

function DevicePareto({ reasons }: { reasons: DeviceAnalysis['reason_summary'] }) {
  const shown = reasons.slice(0, 8)
  const total = Math.max(shown.reduce((sum, item) => sum + item.count, 0), 1)
  const max = Math.max(...shown.map(item => item.count), 1)
  let running = 0
  const cumulative = shown.map(item => {
    running += item.count
    return running / total * 100
  })
  const line = cumulative.map((value, index) => `${(index + .5) / Math.max(shown.length, 1) * 100},${96 - value * .86}`).join(' ')
  if (!shown.length) return <div className="device-chart-empty">当前周期未发现离线或故障事件</div>
  return <div className="device-pareto" role="img" aria-label="故障类型帕累托排名">
    <div className="pareto-bars">{shown.map(item => <div key={item.reason_code}><b>{item.count}</b><i style={{ height: `${Math.max(item.count / max * 100, 8)}%` }} /><span>{deviceReasonNames[item.reason_code] || item.reason_code}</span></div>)}</div>
    <svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={line} />{cumulative.map((value, index) => <circle key={index} cx={(index + .5) / shown.length * 100} cy={96 - value * .86} r="1.3" />)}</svg>
  </div>
}

function DevicePage({ token, summary, start, end, setStart, setEnd, refresh }: {
  token: string
  summary: Summary | null
  start: string
  end: string
  setStart: (value: string) => void
  setEnd: (value: string) => void
  refresh: () => void
}) {
  const [analysis, setAnalysis] = useState<DeviceAnalysis | null>(null)
  const [deviceOnlineTrend, setDeviceOnlineTrend] = useState<TrendPoint[]>([])
  const [faultTrend, setFaultTrend] = useState<TrendPoint[]>([])
  const [stationFilter, setStationFilter] = useState('all')
  const [modelFilter, setModelFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selectedId, setSelectedId] = useState('')
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  useEffect(() => {
    let cancelled = false
    const query = `start=${start}&end_exclusive=${end}`
    Promise.all([
      api<DeviceAnalysis>(`/api/v1/dashboard/devices?limit=120&${query}`, token),
      api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=device_online_rate&${query}`, token),
      api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=device_fault_rate&${query}`, token),
    ]).then(([deviceResult, onlineResult, faultResult]) => {
      if (!cancelled) {
        setAnalysis(deviceResult)
        setDeviceOnlineTrend(onlineResult.points)
        setFaultTrend(faultResult.points)
        setSelectedId(current => current || deviceResult.rows.find(row => row.current_status !== 'online')?.device_id || deviceResult.rows[0]?.device_id || '')
        setError('')
      }
    }).catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : '设备健康数据加载失败') })
    return () => { cancelled = true }
  }, [token, start, end, refreshKey])

  const rows = analysis?.rows ?? []
  const stationOptions = [...new Map(rows.map(row => [row.station_id, row.station_name])).entries()]
  const modelOptions = [...new Set(rows.map(row => row.device_model))]
  const filtered = rows.filter(row =>
    (stationFilter === 'all' || row.station_id === stationFilter) &&
    (modelFilter === 'all' || row.device_model === modelFilter) &&
    (statusFilter === 'all' || (statusFilter === 'risk' ? row.current_status !== 'online' : row.current_status === statusFilter))
  )
  const selected = filtered.find(row => row.device_id === selectedId) || rows.find(row => row.device_id === selectedId) || filtered[0] || rows[0]
  const metrics = { ...(summary?.metrics ?? {}), ...(analysis?.metrics ?? {}) }
  const totals = analysis?.totals ?? { device_count: 0, online_count: 0, offline_count: 0, fault_count: 0, risk_order_count: 0, risk_revenue: 0 }
  const riskCount = totals.offline_count + totals.fault_count
  const cards = [
    { label: '设备在线率', value: formatMetric('device_online_rate', metrics.device_online_rate), icon: '◎', tone: 'teal', note: '在线可观测时长占比' },
    { label: '设备故障率', value: formatMetric('device_fault_rate', metrics.device_fault_rate), icon: '◉', tone: 'orange', note: '故障可观测时长占比' },
    { label: '离线设备', value: `${totals.offline_count}`, unit: '台', icon: '□', tone: 'blue', note: `共 ${totals.device_count} 台设备` },
    { label: '故障设备', value: `${totals.fault_count}`, unit: '台', icon: '◇', tone: 'red', note: `风险设备合计 ${riskCount} 台` },
    { label: '风险设备关联订单', value: totals.risk_order_count.toLocaleString('zh-CN'), unit: '单', icon: '▤', tone: 'violet', note: '仅作同期关联线索' },
    { label: '风险设备关联收入', value: `¥${totals.risk_revenue.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`, icon: '▣', tone: 'green', note: '不代表故障造成的损失' },
  ]
  const displayedRows = (filtered.length ? filtered : rows).slice(0, 8)
  const reset = () => { setStationFilter('all'); setModelFilter('all'); setStatusFilter('all') }
  const runRefresh = () => { refresh(); setRefreshKey(value => value + 1) }

  return <div className="device-page">
    {error && <div className="device-error">{error}</div>}
    <section className="device-filter-bar">
      <select aria-label="设备场站" value={stationFilter} onChange={event => setStationFilter(event.target.value)}><option value="all">全部场站</option>{stationOptions.map(([id, name]) => <option value={id} key={id}>{name}</option>)}</select>
      <select aria-label="设备型号" value={modelFilter} onChange={event => setModelFilter(event.target.value)}><option value="all">全部设备型号</option>{modelOptions.map(model => <option key={model}>{model}</option>)}</select>
      <div className="device-period"><input aria-label="设备开始日期" type="date" value={start} onChange={event => setStart(event.target.value)} /><span>~</span><input aria-label="设备结束日期" type="date" value={endInclusive(end)} onChange={event => { const next = new Date(`${event.target.value}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1); setEnd(next.toISOString().slice(0, 10)) }} /></div>
      <button type="button" onClick={reset}>重置</button>
      <button type="button" className="primary" onClick={runRefresh}>↻　刷新</button>
    </section>

    <section className="device-kpis">
      {cards.map(card => <article key={card.label}><i className={card.tone}>{card.icon}</i><div><span>{card.label}</span><p><strong>{card.value}</strong>{card.unit && <em>{card.unit}</em>}</p><small>{card.note}</small></div></article>)}
    </section>

    <section className="device-top-grid">
      <article className="device-panel device-pareto-panel"><header><div><h2>故障类型 Pareto 排名</h2><p>{start} 至 {endInclusive(end)}</p></div><button disabled type="button" title="详情页未实现">详情未开放</button></header><DevicePareto reasons={analysis?.reason_summary ?? []} /></article>
      <article className="device-panel device-trend-panel"><header><div><h2>设备在线 / 离线趋势</h2><p>基于已发布设备状态指标；各序列按自身范围展示变化</p></div></header><DeviceTrendChart online={deviceOnlineTrend} fault={faultTrend} /></article>
    </section>

    <section className="device-bottom-grid">
      <article className="device-panel device-table-panel">
        <header><div><h2>维修优先级清单</h2><nav>{(['all', 'risk', 'fault', 'offline', 'online'] as const).map(status => <button type="button" className={statusFilter === status ? 'active' : ''} onClick={() => setStatusFilter(status)} key={status}>{status === 'all' ? '全部设备' : status === 'risk' ? '风险优先' : deviceStatusNames[status]}</button>)}</nav></div><button disabled type="button" title="导出未实现">导出未开放</button></header>
        <div className="device-table-wrap"><table><thead><tr><th>设备编号</th><th>所属场站</th><th>型号</th><th>当前状态</th><th>最近异常</th><th>离线/故障时长</th><th>故障次数</th><th>关联订单</th><th>关联收入（元）</th><th>优先级</th><th>操作</th></tr></thead><tbody>{displayedRows.map(row => {
          const latestIssue = row.recent_events.find(event => event.status !== 'online')
          return <tr key={row.device_id} className={selected?.device_id === row.device_id ? 'selected' : ''} onClick={() => setSelectedId(row.device_id)}><td>{row.device_id}</td><td title={row.station_name}>{row.station_name}</td><td>{row.device_model}</td><td><em className={row.current_status}>{deviceStatusNames[row.current_status] || row.current_status}</em></td><td>{latestIssue ? deviceReasonNames[latestIssue.reason_code || latestIssue.status.toUpperCase()] || latestIssue.reason_code : '无'}</td><td>{(row.offline_hours + row.fault_hours).toFixed(1)} 小时</td><td>{row.fault_event_count}</td><td>{row.related_order_count}</td><td>{row.related_revenue.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</td><td><b className={row.priority}>{row.priority}</b></td><td><button disabled type="button" aria-label={`${row.device_id}详情在当前页展示`}>当前页</button></td></tr>
        })}</tbody></table></div>
        <footer><span>显示 {displayedRows.length} / {filtered.length || rows.length} 条</span><div><select disabled aria-label="设备每页条数"><option>当前结果</option></select><button disabled>‹</button><b>1</b><button disabled>›</button></div></footer>
      </article>

      <article className="device-panel device-detail-panel">
        <header><h2>设备详情 <small>｜ {selected?.device_id || '暂无设备'}</small></h2>{selected && <em className={selected.current_status}>{deviceStatusNames[selected.current_status]}</em>}</header>
        {selected && <><section className="device-detail-summary"><div><span>当前状态</span><strong className={selected.current_status}>{deviceStatusNames[selected.current_status]}</strong></div><div><span>异常时长</span><b>{(selected.offline_hours + selected.fault_hours).toFixed(1)} 小时</b></div><dl><div><dt>所属场站</dt><dd>{selected.station_name}</dd></div><div><dt>设备型号</dt><dd>{selected.device_model}</dd></div><div><dt>额定功率</dt><dd>{selected.rated_power_kw} kW</dd></div><div><dt>投运日期</dt><dd>{selected.commission_date}</dd></div></dl></section>
        <section className="device-event-list"><h3>状态事件（最近 4 条）</h3>{selected.recent_events.map((event, index) => <div key={`${event.start_time}-${index}`}><i className={event.status} /><p><b>{deviceStatusNames[event.status]} · {deviceReasonNames[event.reason_code || event.status.toUpperCase()] || event.reason_code || '正常状态'}</b><span>持续 {event.duration_hours.toFixed(1)} 小时</span></p><time>{event.start_time.slice(0, 16).replace('T', ' ')}</time></div>)}</section>
        <section className="device-process"><h3>分析处置流程</h3><div>{['状态采集', '异常识别', '风险排序', '人工处置', '状态恢复'].map((step, index) => <span className={index < 3 ? 'done' : ''} key={step}><i>{index < 3 ? '✓' : '•'}</i><b>{step}</b></span>)}</div></section></>}
      </article>
    </section>

  </div>
}

type ChatScenario = {
  scenario_id: string
  display_name: string
  status: string
  scenario_version: string | null
  initial_question: string
  suggested_questions: string[]
}
const chatDriverNames: Record<string, string> = {
  charging_volume_effect: '充电量变化',
  revenue_per_kwh_effect: '度电收入变化',
  rounding_residual: '舍入差额',
  charging_revenue_change: '收入变化',
  energy_cost_change: '电费成本变化',
  variable_operating_cost_change: '运营成本变化',
}

function ChatTrend({ points }: { points: TrendPoint[] }) {
  const values = points.map(item => item.value ?? 0)
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const coords = values.map((value, index) => `${index / Math.max(values.length - 1, 1) * 100},${86 - (value - min) / (max - min || 1) * 64}`).join(' ')
  return <div className="chat-trend"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="充电收入月度趋势"><polygon points={`0,92 ${coords} 100,92`} /><polyline points={coords} />{values.map((value, index) => <circle key={index} cx={index / Math.max(values.length - 1, 1) * 100} cy={86 - (value - min) / (max - min || 1) * 64} r="1.2" />)}</svg><div>{points.map(item => <span key={item.period}>{item.period.slice(5)}</span>)}</div></div>
}

function ChatPage({ token, start, end }: { token: string; start: string; end: string }) {
  const [question, setQuestion] = useState('')
  const [scenarioId, setScenarioId] = useState('')
  const [scenarios, setScenarios] = useState<ChatScenario[]>([])
  const [result, setResult] = useState<any>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [previous, setPrevious] = useState<Summary | null>(null)
  const [yearAgo, setYearAgo] = useState<Summary | null>(null)
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [history, setHistory] = useState<Array<{ question: string; time: string }>>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [responseProfile, setResponseProfile] = useState('executive_brief')
  const [compositeResult, setCompositeResult] = useState<any>(null)
  const [runtimeStatus, setRuntimeStatus] = useState<any>(null)
  const initialized = useRef('')
  const activeScenario = useRef('')
  const requestSequence = useRef(0)

  const runQuestion = async (nextQuestion: string, currentConversation = conversationId, targetScenario = scenarioId) => {
    const normalized = nextQuestion.trim()
    if (!normalized) return
    const sequence = ++requestSequence.current
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/v1/assistant/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: normalized, conversation_id: currentConversation, scenario_id: targetScenario, profile: responseProfile }),
      })
      const body = await response.json()
      if (sequence !== requestSequence.current || targetScenario !== activeScenario.current) return
      if (!response.ok) throw new Error(`${body.detail?.code ? `${body.detail.code}：` : ''}${body.detail?.message || '问数失败'}`)
      const metricRow = Object.fromEntries((body.response?.key_metrics || []).map((item: any) => [item.metric_code, item.value]))
      const dataEvidence = body.data_query_evidence
      const originalEvidence = dataEvidence?.evidence || {}
      const originalQueryResult = dataEvidence?.query_result
      setCompositeResult(body)
      setResult({
        status: body.response?.refused ? 'rejected' : 'completed',
        answer: body.response?.conclusion,
        conversation_id: body.conversation_id,
        state_version: dataEvidence?.state_version ?? 0,
        result: dataEvidence?.result ?? { metrics: metricRow },
        query_plan: dataEvidence?.query_plan ?? { intent: body.route, metrics: Object.keys(metricRow), comparison: null },
        evidence: {
          ...originalEvidence,
          source: body.response?.data_source?.join('；') || '已发布企业知识',
          data_classification: 'simulated',
          analysis_run_id: originalEvidence.analysis_run_id ?? dataEvidence?.run_id ?? body.run_id,
          state_version: dataEvidence?.state_version ?? 0,
          query_guard: originalEvidence.query_guard ?? (dataEvidence ? 'passed' : 'not_required'),
          answer_guard: originalEvidence.answer_guard ?? { status: body.response?.refused ? 'rejected' : 'passed' },
          explanation_mode: 'unified_response_composer',
          sql: originalEvidence.sql ?? body.response?.sql,
        },
        query_result: originalQueryResult ?? {
          engine: dataEvidence?.engine || 'knowledge_service',
          scenario: targetScenario,
          scenario_version: null,
          semantic_version: null,
          dataset_version: null,
          rows: [metricRow],
          columns: Object.keys(metricRow),
          warnings: body.response?.warnings || [],
          execution_time: 0,
          run_id: body.run_id,
          status: body.response?.refused ? 'rejected' : 'completed',
          sql: body.response?.sql,
        },
        engine_routing: dataEvidence?.engine_routing ?? {
          mode: body.route,
          route_decision: body.route,
          route_reason: 'composite_orchestration',
        },
      })
      setFeedback('')
      setConversationId(body.conversation_id)
      setHistory(items => [{ question: normalized, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }, ...items.filter(item => item.question !== normalized)].slice(0, 5))
    } catch (reason) {
      if (sequence === requestSequence.current && targetScenario === activeScenario.current) {
        setError(reason instanceof Error ? reason.message : '问数失败')
      }
    } finally {
      if (sequence === requestSequence.current && targetScenario === activeScenario.current) setLoading(false)
    }
  }

  useEffect(() => {
    api<{ scenarios: ChatScenario[] }>('/api/v1/chat/scenarios', token)
      .then(body => {
        setScenarios(body.scenarios)
        const selected = body.scenarios.find(item => item.status === 'ACTIVE')
        if (!selected) throw new Error('当前没有已激活的 ChatBI 场景')
        setScenarioId(selected.scenario_id)
      })
      .catch(reason => setError(reason instanceof Error ? reason.message : '场景目录加载失败'))
  }, [token])

  useEffect(() => {
    api<any>('/api/v1/knowledge/runtime', token)
      .then(setRuntimeStatus)
      .catch(() => setRuntimeStatus(null))
  }, [token])

  useEffect(() => {
    if (!scenarioId) return
    if (initialized.current === scenarioId) return
    initialized.current = scenarioId
    activeScenario.current = scenarioId
    const initialQuestion = scenarios.find(item => item.scenario_id === scenarioId)?.initial_question
    if (!initialQuestion) {
      setError('场景未提供受控初始问题')
      return
    }
    setQuestion(initialQuestion)
    setConversationId(null)
    setResult(null)
    setCompositeResult(null)
    setHistory([])
    setFeedback('')
    if (scenarioId === 'charging_ops') {
      const currentRange = monthBefore(end)
      const previousRange = monthBefore(currentRange.start)
      const yearAgoRange = compareRange(currentRange.start, currentRange.end, 'yoy')
      Promise.all([
        api<Summary>(`/api/v1/dashboard/summary?start=${currentRange.start}&end_exclusive=${currentRange.end}`, token),
        api<Summary>(`/api/v1/dashboard/summary?start=${previousRange.start}&end_exclusive=${previousRange.end}`, token),
        api<Summary>(`/api/v1/dashboard/summary?start=${yearAgoRange.start}&end_exclusive=${yearAgoRange.end}`, token),
        api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=charging_revenue&start=${start}&end_exclusive=${end}`, token),
      ]).then(([currentResult, previousResult, yearAgoResult, trendResult]) => {
        setSummary(currentResult)
        setPrevious(previousResult)
        setYearAgo(yearAgoResult)
        setTrend(trendResult.points)
      }).catch(reason => setError(reason instanceof Error ? reason.message : '经营上下文加载失败'))
    } else {
      setSummary(null)
      setPrevious(null)
      setYearAgo(null)
      setTrend([])
    }
    void runQuestion(initialQuestion, null, scenarioId)
  }, [token, scenarioId, scenarios, start, end])

  const ask = (event: React.FormEvent) => {
    event.preventDefault()
    void runQuestion(question)
  }
  const newSession = () => {
    setConversationId(null)
    setResult(null)
    setHistory([])
    setQuestion(scenarios.find(item => item.scenario_id === scenarioId)?.initial_question || '')
    setError('')
    setFeedback('')
  }

  const recordFeedback = async (rating: 'helpful' | 'not_helpful') => {
    const runId = compositeResult?.run_id
    if (!runId) return
    try {
      const response = await fetch('/api/v1/assistant/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ run_id: runId, trace_id: compositeResult.trace_id, rating }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail?.message || '反馈记录失败')
      setFeedback(rating)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '反馈记录失败')
    }
  }

  const isSales = scenarioId === 'sales_ops'
  const scenarioConfig = scenarios.find(item => item.scenario_id === scenarioId)
  const queryResult = result?.query_result
  const routing = result?.engine_routing
  const knowledgeOnly = compositeResult?.route === 'knowledge'
  const composedResponse = compositeResult?.response
  const salesMetrics = queryResult?.rows?.[0] ?? {}
  const diagnosis = result?.result?.diagnosis
  const metrics = summary?.metrics ?? diagnosis?.current ?? {}
  const previousMetrics = previous?.metrics ?? diagnosis?.previous ?? {}
  const yearAgoMetrics = yearAgo?.metrics ?? {}
  const revenueChange = rate(metrics.charging_revenue, previousMetrics.charging_revenue)
  const bridge = diagnosis?.bridge ?? []
  const stationImpacts = diagnosis?.station_contributions ?? []
  const maxBridge = Math.max(...bridge.map((item: any) => Math.abs(item.contribution ?? 0)), 1)
  const strongestDriver = [...bridge].sort((a: any, b: any) => Math.abs(b.contribution) - Math.abs(a.contribution))[0]
  const conclusionStart = result?.evidence?.data_time_range?.start
  const conclusionPeriod = conclusionStart
    ? `${new Date(`${conclusionStart}T00:00:00Z`).getUTCFullYear()}年${new Date(`${conclusionStart}T00:00:00Z`).getUTCMonth() + 1}月`
    : '当前数据期'
  const rawConclusion = isSales
    ? result?.answer
    : diagnosis
    ? `结论：全部授权区域 ${conclusionPeriod}充电收入为 ${money(metrics.charging_revenue)} 元，环比${revenueChange != null && revenueChange < 0 ? '下降' : '上升'} ${revenueChange == null ? '数据不足' : `${(Math.abs(revenueChange) * 100).toFixed(2)}%`}。变化拆解中贡献最大项为${chatDriverNames[strongestDriver?.driver] ?? '其他因素'}；关联线索不构成因果结论。`
    : result?.answer
  const conclusion = typeof rawConclusion === 'string'
    ? rawConclusion.replace(/^(?:【(?:模拟|真实)数据】|(?:模拟|真实)数据[：:])\s*/, '')
    : rawConclusion
  const cards = [
    { id: 'charging_revenue', label: '充电收入', icon: '¥', color: 'teal' },
    { id: 'charging_volume_kwh', label: '充电量', icon: '↯', color: 'teal' },
    { id: 'revenue_per_kwh', label: '度电收入', icon: '价', color: 'orange' },
    { id: 'gross_margin', label: '毛利率', icon: '率', color: 'red' },
  ]
  const suggestions = scenarioConfig?.suggested_questions ?? []
  const salesMetricNames: Record<string, string> = {
    sales_revenue: '销售收入',
    order_count: '订单数',
    customer_count: '客户数',
    average_order_value: '客单价',
    sales_quantity: '销售数量',
    gross_profit: '销售毛利',
    gross_margin: '销售毛利率',
    refund_amount: '退款金额',
    refund_rate: '退款率',
    new_customer_count: '新客户数',
    repeat_customer_count: '复购客户数',
    channel_contribution: '最大渠道贡献率',
  }
  const salesValue = (metricId: string, value: number | null | undefined) => {
    if (value == null) return '数据不足'
    if (['gross_margin', 'refund_rate', 'channel_contribution'].includes(metricId)) return `${(value * 100).toFixed(2)}%`
    if (['sales_revenue', 'average_order_value', 'gross_profit', 'refund_amount'].includes(metricId)) return `${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 元`
    return value.toLocaleString('zh-CN')
  }

  return <div className="ai-analysis-page">
    <h2 className="chat-trust-title">可信 ChatBI</h2>
    <aside className="chat-history-panel">
      <header><h2>会话历史</h2><button onClick={newSession}>＋ 新会话</button></header>
      <div className="chat-history-list">{history.length ? history.map((item, index) => <button key={`${item.time}-${item.question}`} className={index === 0 ? 'active' : ''} onClick={() => setQuestion(item.question)}><span>{item.question}</span><small>{item.time}</small></button>) : <p>新会话尚未产生分析记录</p>}</div>
      <section><header><h3>本次会话</h3><span>{history.length} 条</span></header><dl><div><dt>当前场景</dt><dd>{scenarioId}</dd></div><div><dt>会话状态</dt><dd>{result?.status ?? '准备中'}</dd></div><div><dt>状态版本</dt><dd>v{result?.state_version ?? 0}</dd></div><div><dt>隔离范围</dt><dd>当前用户 / 当前场景</dd></div></dl></section>
      <section className="chat-example-list"><header><h3>分析示例</h3></header>{(isSales ? ['销售收入与毛利率', '退款与复购分析', '客户与订单分析'] : ['全平台收入与毛利分析', '场站贡献下降定位', '设备指标关联排查']).map(item => <button key={item} onClick={() => setQuestion(item)}><span>▧</span>{item}<b>★</b></button>)}</section>
      <section className="chat-chain-card"><header><h3>可信分析链路</h3><span>已启用</span></header><ol><li>自然语言结构化解析</li><li>Query Plan 合同校验</li><li>确定性参数化编译</li><li>只读执行与权限过滤</li><li>Answer Guard 证据检查</li></ol></section>
    </aside>

    <main className="chat-analysis-center">
      <form className="chat-question-box" onSubmit={ask}><div><textarea aria-label="经营分析问题" maxLength={500} value={question} onChange={event => setQuestion(event.target.value)} /><span>{question.length}/500</span><button aria-label="发送分析问题" disabled={loading}>{loading ? '…' : '➤'}</button></div><footer><span>试试这样问：</span>{suggestions.map(item => <button type="button" key={item} onClick={() => setQuestion(item)}>{item}</button>)}</footer></form>
      <section className="chat-recommended"><h3>推荐追问</h3><div>{suggestions.map(item => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}</div><span title="推荐问题由场景目录提供">场景模板</span></section>
      <section className="chat-conditions"><h3>当前条件</h3><div><label>业务场景　<select aria-label="当前业务场景" value={scenarioId} onChange={event => { activeScenario.current = event.target.value; requestSequence.current += 1; setScenarioId(event.target.value) }}>{scenarios.map(scenario => <option key={scenario.scenario_id} value={scenario.scenario_id} disabled={scenario.status !== 'ACTIVE'}>{scenario.display_name} · {scenario.status}</option>)}</select></label><span>时间范围　{result?.evidence?.data_time_range?.start ?? '等待执行'} ~ {result?.evidence?.data_time_range?.end_exclusive ?? '等待执行'}</span><span>权限范围　全部授权区域</span><button onClick={() => setQuestion(scenarioConfig?.initial_question || '')}>重置条件</button></div></section>

      <section className="chat-runtime-strip" aria-label="查询运行证据"><span>场景 <b>{queryResult?.scenario ?? scenarioId}</b></span><span>数据集 <b>{queryResult?.dataset_version ?? '等待 ACTIVE 版本'}</b></span><span>语义 <b>{queryResult?.semantic_version ?? '等待 ACTIVE 版本'}</b></span><span>引擎 <b>{queryResult?.engine ?? '等待执行'}</b></span><span>模式 <b>{routing?.mode ?? '等待执行'}</b></span><span>耗时 <b>{queryResult ? `${queryResult.execution_time} ms` : '—'}</b></span></section>

      <section className="chat-profile-strip"><label>回答风格<select aria-label="回答风格" value={responseProfile} onChange={event => setResponseProfile(event.target.value)}><option value="executive_brief">经营摘要</option><option value="analyst_detailed">分析师详版</option><option value="operation_action">运营行动</option><option value="concise_query">简洁问答</option></select></label><span>编排路由 <b>{compositeResult?.route || '等待执行'}</b></span><span>模型 <b>{runtimeStatus?.model_gateway?.status || 'MODEL_RUNTIME_PENDING'}</b></span><span>SQLBot <b>{runtimeStatus?.sqlbot_runtime || 'RUNTIME_PENDING'}</b></span><span>RAG <b>{runtimeStatus?.retrieval_mode || '检查中'} / {runtimeStatus?.vector_status || 'VECTOR_PENDING'}</b></span></section>

      <article className={`chat-answer-card ${isSales ? 'sales' : ''} ${knowledgeOnly ? 'knowledge-only' : ''}`}>
        <header><div><i>✦</i><h2>AI结论</h2><small>{loading ? '正在执行受控分析…' : result ? '已完成可信分析' : '等待分析'}</small></div><nav><button disabled>☆ 收藏未开放</button><button disabled>⇧ 导出未开放</button><button disabled>↗ 分享未开放</button></nav></header>
        {error && <div className="notice error">{error}</div>}
        <p className="chat-conclusion">{conclusion || '正在通过 Query Plan、确定性 SQL Compiler 与安全守卫计算结果…'}</p>
        {composedResponse && <section className="chat-composer-evidence"><header><h3>统一回答证据</h3><span>{composedResponse.profile} · 置信度 {Number(composedResponse.confidence || 0).toFixed(2)}</span></header>{composedResponse.warnings?.map((item: string) => <p className="warning" key={item}>{item}</p>)}{composedResponse.citations?.map((item: any) => <details key={item.chunk_id}><summary>{item.title} · {item.section || '未标注章节'} · {Number(item.retrieval_score).toFixed(3)}</summary><p>{item.citation_text}</p><code>{item.document_version_id} / {item.chunk_id}</code></details>)}{knowledgeOnly && !composedResponse.citations?.length && <p>未检索到当前身份与场景可用的已发布知识证据，系统已拒绝无依据回答。</p>}</section>}
        {isSales ? <section className="chat-metric-grid sales">{Object.entries(salesMetrics).map(([metricId, value]) => <article key={metricId}><header><i className="teal">销</i><span>{salesMetricNames[metricId] ?? metricId}<small>{metricId}</small></span></header><strong>{salesValue(metricId, value as number)}</strong><footer><span>ACTIVE 数据集</span><span><b className="up">已验证口径</b></span></footer></article>)}</section> : <section className="chat-metric-grid">{cards.map(card => <article key={card.id}><header><i className={card.color}>{card.icon}</i><span>{card.label}<small>{card.id === 'charging_volume_kwh' ? '(kWh)' : card.id.includes('revenue') ? '(元)' : ''}</small></span></header><strong>{card.id === 'charging_revenue' ? money(metrics[card.id]) : card.id === 'charging_volume_kwh' ? Math.round(metrics[card.id] ?? 0).toLocaleString('zh-CN') : formatMetric(card.id, metrics[card.id])}</strong><footer><span>环比 <b className={rate(metrics[card.id], previousMetrics[card.id]) != null && rate(metrics[card.id], previousMetrics[card.id])! < 0 ? 'down' : 'up'}>{deltaText(card.id, metrics[card.id], previousMetrics[card.id])}</b></span><span>同比 <b className={rate(metrics[card.id], yearAgoMetrics[card.id]) != null && rate(metrics[card.id], yearAgoMetrics[card.id])! < 0 ? 'down' : 'up'}>{deltaText(card.id, metrics[card.id], yearAgoMetrics[card.id])}</b></span></footer></article>)}</section>}
        {!isSales && <><section className="chat-insight-grid">
          <article><header><h3>近期充电收入趋势（元）</h3><span>按月⌄</span></header><ChatTrend points={trend} /></article>
          <article><header><h3>主要影响对象</h3><span>变化贡献（元）</span></header><div className="chat-impact-list">{stationImpacts.slice(0, 5).map((item: any) => <div key={item.station_id}><span>{item.station_name}</span><em className={item.contribution < 0 ? 'down' : 'up'}>{item.contribution < 0 ? '下降' : '上升'}</em><b className={item.contribution < 0 ? 'down' : 'up'}>{money(item.contribution)}</b></div>)}</div></article>
        </section>
        <section className="chat-action-grid">
          <article><header><h3>原因拆解（贡献度）</h3><span>ⓘ</span></header><div className="chat-driver-list">{bridge.slice(0, 5).map((item: any) => <div key={item.driver}><span>{chatDriverNames[item.driver] ?? item.driver}</span><b>{money(item.contribution)}</b><i><em className={item.contribution < 0 ? 'negative' : ''} style={{ width: `${Math.max(Math.abs(item.contribution) / maxBridge * 100, 5)}%` }} /></i></div>)}</div><small>对账残差：{money(diagnosis?.reconciliation?.residual)}</small></article>
          <article><header><h3>建议行动</h3></header><ul><li>复核充电量变化对应的时段与场站结构<b>高影响</b></li><li>复核度电收入变化与价格策略<b>高影响</b></li><li>关注贡献下降场站的运营条件<b>中影响</b></li><li>结合设备指标作同期关联排查<b>中影响</b></li></ul></article>
        </section></>}
        {isSales && <section className="chat-sales-evidence"><article><h3>结构化查询结果</h3><p>所有业务数字均来自统一 QueryResult；当前 Response Composer 未使用 SQLBot 原始回答。</p><dl><div><dt>结果字段</dt><dd>{queryResult?.columns?.join('、') || '等待执行'}</dd></div><div><dt>版本绑定</dt><dd>{queryResult ? `${queryResult.scenario_version} / ${queryResult.semantic_version} / ${queryResult.dataset_version}` : '等待执行'}</dd></div></dl></article><article><h3>受控状态</h3><ul><li>Query Guard：{result?.evidence?.query_guard ?? 'pending'}</li><li>Answer Guard：{result?.evidence?.answer_guard?.status ?? 'pending'}</li><li>Shadow：{routing?.route_reason ?? '等待执行'}</li><li>警告：{queryResult?.warnings?.join('、') || '无'}</li></ul></article></section>}
        <footer className="chat-followups"><b>推荐追问</b>{suggestions.map(item => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}</footer>
        <div className="chat-feedback"><span>这次结构化回答是否有帮助？</span><button type="button" disabled={!result || Boolean(feedback)} className={feedback === 'helpful' ? 'selected' : ''} onClick={() => void recordFeedback('helpful')}>有帮助</button><button type="button" disabled={!result || Boolean(feedback)} className={feedback === 'not_helpful' ? 'selected' : ''} onClick={() => void recordFeedback('not_helpful')}>需改进</button>{feedback && <b>反馈已记录到审计日志</b>}</div>
      </article>
    </main>

    <aside className="chat-evidence-panel">
      <header><h2>查询证据</h2><span>×</span></header>
      <section><h3><i>①</i>版本与引擎</h3><p>场景：{queryResult?.scenario ?? scenarioId}@{queryResult?.scenario_version ?? 'pending'}</p><p>语义 / 数据集：{queryResult?.semantic_version ?? 'pending'} / {queryResult?.dataset_version ?? 'pending'}</p><p>引擎 / 模式：{queryResult?.engine ?? 'pending'} / {routing?.mode ?? 'pending'}</p></section>
      <section><h3><i>②</i>查询条件</h3><ul><li>时间范围：{result?.evidence?.data_time_range?.start ?? '等待执行'} ~ {result?.evidence?.data_time_range?.end_exclusive ?? '等待执行'}（右开）</li><li>区域：全部授权区域</li><li>业务场景：{scenarioId}</li></ul></section>
      <section><h3><i>③</i>Query Plan 摘要</h3><p>{result?.query_plan ? `${result.query_plan.intent}；指标 ${result.query_plan.metrics.join('、')}；${result.query_plan.comparison?.type ?? '无'}比较。` : '等待结构化解析'}</p><details><summary>查看详情　›</summary><pre>{JSON.stringify(result?.query_plan, null, 2)}</pre></details></section>
      <section><h3><i>④</i>SQL 与警告</h3><details><summary>查看受控 SQL　‹/›</summary><pre>{queryResult?.sql || result?.evidence?.sql || '当前引擎通过受控查询构造器执行，未向该角色暴露 SQL 文本。'}</pre></details><p>警告：{queryResult?.warnings?.join('、') || '无'}</p></section>
      <section><h3><i>⑤</i>analysis_run_id</h3><code>{result?.evidence?.analysis_run_id ?? '等待生成'}</code></section>
      <footer><span>♢</span><p><b>业务默认，证据按需查看</b><small>Query Guard：{result?.evidence?.query_guard ?? 'pending'} · Answer Guard：{result?.evidence?.answer_guard?.status ?? 'pending'} · {routing?.route_decision ?? '等待路由'}</small></p></footer>
    </aside>
  </div>
}

const alertDriverNames: Record<string, string> = {
  charging_revenue_change: '充电收入',
  energy_cost_change: '电费成本',
  variable_operating_cost_change: '可变运营成本',
}

function AlertContributionChart({ bridge, total }: { bridge: Array<{ driver: string; contribution: number }>; total: number }) {
  const rows = [...bridge, { driver: 'total', contribution: total }]
  const values = rows.map(item => item.contribution / 10000)
  const range = Math.max(...values.map(Math.abs), 1) * 1.22
  const plot = { left: 36, right: 432, top: 18, bottom: 126 }
  const xStep = (plot.right - plot.left) / rows.length
  const barWidth = Math.min(42, xStep * .44)
  const y = (value: number) => plot.top + (range - value) / (range * 2) * (plot.bottom - plot.top)
  const ticks = [range, range / 2, 0, -range / 2, -range]
  return <div className="alert-contribution-chart" role="img" aria-label="预警影响金额贡献拆解">
    <svg viewBox="0 0 450 158" preserveAspectRatio="none">
      {ticks.map((tick, index) => <g key={`alert-tick-${index}`}><line className={tick === 0 ? 'zero' : ''} x1={plot.left} x2={plot.right} y1={y(tick)} y2={y(tick)} /><text className="axis" x={plot.left - 7} y={y(tick) + 3}>{tick.toFixed(0)}</text></g>)}
      {rows.map((item, index) => {
        const value = values[index]
        const barX = plot.left + xStep * index + (xStep - barWidth) / 2
        const zeroY = y(0)
        const valueY = y(value)
        const top = Math.min(zeroY, valueY)
        const height = Math.max(Math.abs(zeroY - valueY), 2)
        const positive = value >= 0
        return <g key={item.driver}><rect className={positive ? 'positive' : 'negative'} x={barX} y={top} width={barWidth} height={height} rx="1.5" /><text className={positive ? 'value positive' : 'value negative'} x={barX + barWidth / 2} y={positive ? top - 7 : top + height + 12}>{positive ? '+' : ''}{value.toFixed(2)}</text><text className="category" x={barX + barWidth / 2} y="149">{item.driver === 'total' ? '合计影响' : alertDriverNames[item.driver] || item.driver}</text></g>
      })}
    </svg>
  </div>
}

function DiagnosticsPage({ token, start, end }: { token: string; start: string; end: string }) {
  const [data, setData] = useState<any>(null)
  const [anomaly, setAnomaly] = useState<any>(null)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const [riskFilter, setRiskFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [feedback, setFeedback] = useState('')
  useEffect(() => {
    let cancelled = false
    const query = `start=${start}&end_exclusive=${end}`
    Promise.all([
      api<any>(`/api/v1/diagnostics/decomposition?metric=gross_profit&comparison=mom&limit=10&${query}`, token),
      api<any>(`/api/v1/diagnostics/anomalies?metric=charging_revenue&${query}`, token),
    ]).then(([decomposition, anomalyResult]) => {
      if (!cancelled) {
        setData(decomposition)
        setAnomaly(anomalyResult)
        setSelectedId(current => current || decomposition.station_contributions[0]?.station_id || '')
        setError('')
      }
    }).catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : '诊断加载失败') })
    return () => { cancelled = true }
  }, [token, start, end, refreshKey])
  if (error) return <div className="notice error">{error}</div>
  if (!data) return <div className="notice">正在计算异常与贡献拆解…</div>

  const stationRows = (data.station_contributions as Array<any>).slice(0, 8)
  const alerts = stationRows.map(row => ({
    ...row,
    risk: row.contribution < 0 ? 'high' : 'low',
    title: row.contribution < 0 ? `毛利负向贡献：${row.station_name}` : `毛利正向贡献：${row.station_name}`,
    domain: '规则贡献诊断',
  }))
  const visibleAlerts = alerts.filter(row =>
    (riskFilter === 'all' || row.risk === riskFilter) &&
    (!search || `${row.title}${row.station_name}${row.region_id}`.toLowerCase().includes(search.toLowerCase()))
  )
  const selected = alerts.find(row => row.station_id === selectedId) || alerts[0]
  const negativeCount = alerts.filter(row => row.contribution < 0).length
  const positiveCount = alerts.filter(row => row.contribution >= 0).length
  const negativeImpact = alerts.filter(row => row.contribution < 0).reduce((sum, row) => sum + Math.abs(row.contribution), 0)
  const currentMargin = data.current.charging_revenue ? data.current.gross_profit / data.current.charging_revenue : null
  const previousMargin = data.previous.charging_revenue ? data.previous.gross_profit / data.previous.charging_revenue : null
  const marginChange = currentMargin == null || previousMargin == null ? null : currentMargin - previousMargin
  const volumeChange = data.previous.charging_volume_kwh ? data.changes.charging_volume_kwh / Math.abs(data.previous.charging_volume_kwh) : null
  const riskNames: Record<string, string> = { high: '负向贡献', low: '正向贡献' }
  const compactWan = (value: number) => `${(value / 10000).toFixed(2)} 万`
  const cards = [
    { label: '负向贡献对象', value: `${negativeCount}`, note: `当前周期 ${negativeCount} 个`, icon: '◆', tone: 'red' },
    { label: '正向贡献对象', value: `${positiveCount}`, note: `当前周期 ${positiveCount} 个`, icon: '◇', tone: 'green' },
    { label: '规则状态', value: anomaly?.triggered ? '已触发' : '未触发', note: '确定性异常规则', icon: '▣', tone: 'blue' },
    { label: '诊断对象', value: `${alerts.length}`, note: '贡献拆解返回对象', icon: '▲', tone: 'green' },
    { label: '负向贡献绝对值', value: `${(negativeImpact / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, unit: '万', note: '非预计损失', icon: '▣', tone: 'violet' },
    { label: '对账残差', value: compactWan(data.reconciliation.residual), note: data.reconciliation.status, icon: '●', tone: 'orange' },
  ]
  const flash = (message: string) => {
    setFeedback(message)
    window.setTimeout(() => setFeedback(''), 2400)
  }

  return <div className="alert-page">
    {feedback && <div className="alert-feedback">{feedback}</div>}
    <section className="alert-kpis">{cards.map(card => <article key={card.label}><i className={card.tone}>{card.icon}</i><div><span>{card.label}</span><p><strong>{card.value}</strong>{card.unit && <em>{card.unit}</em>}</p><small>{card.note}</small></div></article>)}</section>

    <section className="alert-workspace">
      <article className="alert-list-panel alert-panel">
        <header><h2>规则诊断列表（非预警工单）</h2><div><button aria-label="刷新诊断" onClick={() => setRefreshKey(value => value + 1)}>⟳</button><button disabled title="诊断列表导出未实现">⇩ 未开放</button></div></header>
        <div className="alert-filters">
          <select aria-label="贡献方向筛选" value={riskFilter} onChange={event => setRiskFilter(event.target.value)}><option value="all">全部贡献方向</option><option value="high">负向贡献</option><option value="low">正向贡献</option></select>
          <label><i>⌕</i><input aria-label="搜索诊断" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索诊断标题或对象" /></label>
        </div>
        <div className="alert-table-head"><span>诊断标题</span><span>贡献方向</span><span>贡献值</span><span>影响对象</span><span>数据周期</span><span>证据</span><span>流程边界</span></div>
        <div className="alert-rows">{visibleAlerts.map(row => <button className={selected?.station_id === row.station_id ? 'selected' : ''} onClick={() => setSelectedId(row.station_id)} key={row.station_id}><i /><span className="alert-title"><b>{row.title}</b><small>{row.domain}</small></span><em className={`risk ${row.risk}`}>{riskNames[row.risk]}</em><strong className={row.contribution < 0 ? 'negative' : 'positive'}>{compactWan(row.contribution)}</strong><span>{row.station_name}</span><span>当前周期</span><em className="status processing">run_id</em><span className="owner">非工单</span></button>)}</div>
        <footer><span>共 {visibleAlerts.length} 条</span><nav><button disabled>‹</button><b>1</b><button disabled>›</button></nav><select aria-label="每页条数" disabled><option>当前结果</option></select></footer>
      </article>

      <article className="alert-detail-panel alert-panel">
        <header className="alert-detail-head"><div><h2><i>◆</i>{selected?.title || '经营规则诊断'}<em className={`risk ${selected?.risk || 'low'}`}>{riskNames[selected?.risk || 'low']}</em></h2><p>分析运行：{data.metadata.analysis_run_id}　　数据周期：{start} 至 {endInclusive(end)}　　类型：规则诊断</p></div><button disabled className="status processing">◎ 非预警工单</button></header>

        <section className="alert-summary"><h3>业务摘要</h3><p>{start} 至 {endInclusive(end)}，{selected?.station_name || '当前对象'}毛利贡献为 <b>{compactWan(selected?.contribution || 0)}</b>；充电收入环比{anomaly?.change_rate == null ? '数据不足' : `变化 ${(anomaly.change_rate * 100).toFixed(1)}%`}。该结果用于经营关注与后续核查，不构成因果结论。</p></section>

        <div className="alert-analysis-grid">
          <section className="alert-metric-change"><h3>指标变化</h3><dl><div><dt>充电收入</dt><dd>{anomaly?.change_rate == null ? '数据不足' : `${anomaly.change_rate >= 0 ? '+' : ''}${(anomaly.change_rate * 100).toFixed(1)}%`}</dd></div><div><dt>毛利额</dt><dd>{compactWan(data.changes.gross_profit)}</dd></div><div><dt>毛利率</dt><dd>{marginChange == null ? '数据不足' : `${marginChange >= 0 ? '+' : ''}${(marginChange * 100).toFixed(1)}pp`}</dd></div><div><dt>充电量</dt><dd>{volumeChange == null ? '数据不足' : `${volumeChange >= 0 ? '+' : ''}${(volumeChange * 100).toFixed(1)}%`}</dd></div></dl></section>
          <section className="alert-contribution"><header><h3>贡献拆解（影响金额）</h3><button onClick={() => flash('贡献项来自当前诊断结果，已完成残差对账。')}>查看拆解明细</button></header><small>金额（万元）</small><AlertContributionChart bridge={data.bridge} total={data.reconciliation.target_change} /></section>
        </div>

        <div className="alert-object-grid">
          <section className="alert-objects"><h3>影响对象</h3>{alerts.slice(0, 4).map((row, index) => <p key={row.station_id}><i>{index ? '▣' : '⌂'}</i><span>{index ? row.station_name : `${row.region_id}（重点对象）`}</span><b>{compactWan(row.contribution)}</b></p>)}<button onClick={() => flash(`当前诊断共定位 ${alerts.length} 个重点对象。`)}>查看全部 {alerts.length} 个对象</button></section>
          <section className="alert-actions"><h3>人工核查建议</h3><p><i>✓</i><span>复核低贡献场站的充电量与时段结构</span><em>建议</em></p><p><i>✓</i><span>检查价格策略与活动执行记录</span><em>建议</em></p><p><i>✓</i><span>结合设备在线率与故障率同步核查</span><em>建议</em></p><button disabled title="行动方案库未实现">方案库未开放</button></section>
        </div>

        <section className="alert-timeline"><header><h3>本轮诊断证据</h3><button disabled>无虚构处理记录</button></header><div><time>运行</time><i className="active" /><span>结构化结果：{data.metadata.analysis_run_id}</span></div><div><time>规则</time><i /><span>{anomaly?.triggered ? '异常规则已触发' : '异常规则未触发'}，阈值来自已发布规则</span></div><div><time>对账</time><i /><span>贡献拆解状态：{data.reconciliation.status}；残差 {compactWan(data.reconciliation.residual)}</span></div></section>
      </article>
    </section>

    <footer className="alert-boundary">{data.metadata.causality_boundary}</footer>
  </div>
}

function ReportTrend({ revenue, profit, margin }: { revenue: TrendPoint[]; profit: TrendPoint[]; margin: TrendPoint[] }) {
  const periods = revenue.map(point => point.period)
  const revenueValues = revenue.map(point => point.value ?? 0)
  const profitValues = periods.map((_, index) => profit[index]?.value ?? 0)
  const marginValues = periods.map((_, index) => margin[index]?.value ?? 0)
  const moneyMax = Math.max(...revenueValues, ...profitValues, 1)
  const marginMax = Math.max(...marginValues, .01)
  const line = marginValues.map((value, index) => `${(index + .5) / Math.max(marginValues.length, 1) * 100},${90 - value / marginMax * 64}`).join(' ')
  const moneyAxis = [moneyMax, moneyMax * .67, moneyMax * .33, 0]
  const marginAxis = [marginMax, marginMax * .67, marginMax * .33, 0]
  const axisMoney = (value: number) => value >= 1_000_000 ? `${(value / 1_000_000).toFixed(1)}m` : `${Math.round(value / 10_000)}万`
  return <div className="report-trend" role="img" aria-label="收入、毛利与毛利率趋势">
    <div className="report-trend-legend"><span className="revenue">收入（元）</span><span className="profit">毛利（元）</span><span className="margin">毛利率（%）</span></div>
    <div className="report-trend-plot">
      <div className="report-trend-y left">{moneyAxis.map(value => <span key={value}>{axisMoney(value)}</span>)}</div>
      <div className="report-trend-y right">{marginAxis.map(value => <span key={value}>{(value * 100).toFixed(0)}%</span>)}</div>
      <div className="report-bars">{periods.map((period, index) => <div key={period}><i className="revenue" style={{ height: `${Math.max(revenueValues[index] / moneyMax * 100, 7)}%` }} /><i className="profit" style={{ height: `${Math.max(profitValues[index] / moneyMax * 100, 5)}%` }} /></div>)}</div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={line} />{marginValues.map((value, index) => <circle key={periods[index]} cx={(index + .5) / Math.max(marginValues.length, 1) * 100} cy={90 - value / marginMax * 64} r="1.4" />)}</svg>
      <div className="report-trend-axis">{periods.map(period => <span key={period}>{period.slice(5)}</span>)}</div>
    </div>
  </div>
}

function ReportPage({ token, start, end, summary, stations, trend }: { token: string; start: string; end: string; summary: Summary | null; stations: StationRow[]; trend: TrendPoint[] }) {
  const [report, setReport] = useState<any>(null)
  const [previous, setPrevious] = useState<Summary | null>(null)
  const [yearAgo, setYearAgo] = useState<Summary | null>(null)
  const [profitTrend, setProfitTrend] = useState<TrendPoint[]>([])
  const [marginTrend, setMarginTrend] = useState<TrendPoint[]>([])
  const [reportType, setReportType] = useState<'weekly' | 'monthly'>('weekly')
  const [generatedAt, setGeneratedAt] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [enabled, setEnabled] = useState({ summary: true, metric: true, trend: true, anomaly: true, station: true, device: true, action: true })
  const metrics = report?.metrics ?? summary?.metrics ?? {}
  const metadata = report?.metadata ?? summary?.metadata
  const isReady = Boolean(report)

  const generate = async () => {
    setLoading(true)
    setError('')
    try {
      const result = await api<any>(`/api/v1/reports/draft?report_type=${reportType}&start=${start}&end_exclusive=${end}`, token)
      setReport(result)
      setGeneratedAt(new Date().toLocaleString('zh-CN', { hour12: false }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '报告生成失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const previousRange = compareRange(start, end, 'mom')
    const yearRange = compareRange(start, end, 'yoy')
    Promise.all([
      api<Summary>(`/api/v1/dashboard/summary?start=${previousRange.start}&end_exclusive=${previousRange.end}`, token),
      api<Summary>(`/api/v1/dashboard/summary?start=${yearRange.start}&end_exclusive=${yearRange.end}`, token),
      api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=gross_profit&start=${start}&end_exclusive=${end}`, token),
      api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=gross_margin&start=${start}&end_exclusive=${end}`, token),
    ]).then(([previousResult, yearResult, profitResult, marginResult]) => {
      setPrevious(previousResult)
      setYearAgo(yearResult)
      setProfitTrend(profitResult.points)
      setMarginTrend(marginResult.points)
    }).catch(() => {
      setPrevious(null)
      setYearAgo(null)
      setProfitTrend([])
      setMarginTrend([])
    })
  }, [token, start, end])

  useEffect(() => {
    void generate()
  }, [token, start, end, reportType])

  const download = async (format: 'markdown' | 'csv') => {
    const response = await fetch(`/api/v1/reports/export?report_type=${reportType}&format=${format}&start=${start}&end_exclusive=${end}`, { headers: { Authorization: `Bearer ${token}` } })
    if (!response.ok) return setError('导出失败')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `新能源经营分析${reportType === 'weekly' ? '周报' : '月报'}草稿.${format === 'csv' ? 'csv' : 'md'}`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const reportName = `新能源经营分析${reportType === 'weekly' ? '周报' : '月报'}`
  const primaryMetrics = [
    ['charging_revenue', '总收入（元）'],
    ['gross_profit', '毛利（元）'],
    ['gross_margin', '毛利率（%）'],
    ['charging_volume_kwh', '充电电量（kWh）'],
    ['device_online_rate', '设备在线率（%）'],
  ] as const
  const tableMetrics = [
    ...primaryMetrics,
    ['station_utilization_rate', '平均利用率（%）'],
    ['service_fee_revenue', '服务费收入（元）'],
  ] as const
  const reportRows: Array<[string, string, string]> = report
    ? [[reportName, loading ? '生成中' : '草稿', generatedAt || '本轮生成']]
    : []
  const driverNames: Record<string, string> = {
    charging_revenue_change: '收入变化',
    energy_cost_change: '电费成本变化',
    variable_operating_cost_change: '运营成本变化',
  }
  const diagnosticRows = report?.diagnostic?.station_contributions ?? []
  const anomalyRows = report?.diagnostic?.bridge ?? []
  const topStations = [...stations].sort((a, b) => (b.metrics.gross_profit ?? 0) - (a.metrics.gross_profit ?? 0)).slice(0, 5)
  const faultRate = Math.max(Math.min(metrics.device_fault_rate ?? 0, 1), 0)
  const offlineRate = Math.max(1 - Math.max(Math.min(metrics.device_online_rate ?? 0, 1), 0), 0)
  const healthyRate = Math.max(1 - faultRate - offlineRate, 0)
  const deviceDonut = `conic-gradient(#4d8fe9 0 ${healthyRate * 100}%,#51c7aa ${healthyRate * 100}% ${(healthyRate + faultRate) * 100}%,#cad5e5 ${(healthyRate + faultRate) * 100}% 100%)`
  const momSummary = deltaText('charging_revenue', metrics.charging_revenue, previous?.metrics.charging_revenue)
  const actionRows = [
    '针对低毛利贡献场站，人工复核费率、利用率与设备可用性。',
    '排查设备离线和故障率同期变化，形成待审核的运维建议。',
    '复核指标口径和报告数据链路，确保草稿结果可追溯。',
  ]

  return <div className="report-workspace">
    <aside className="report-list-panel">
      <button className="report-create" onClick={() => void generate()}>＋　新建报告</button>
      <label className="report-search">⌕<input aria-label="搜索报告名称" placeholder="搜索报告名称" /></label>
      <div className="report-tabs"><b>当前草稿</b><span aria-disabled="true">历史未实现</span><span aria-disabled="true">订阅未实现</span></div>
      <header><h2>当前草稿 <small>（{reportRows.length}）</small></h2><button disabled aria-label="筛选报告">▽</button></header>
      <div className="report-list-items">{reportRows.map(([name, status, time], index) => <button disabled className={index === 0 ? 'active' : ''} key={name}><i>{index === 0 ? '●' : '○'}</i><span>{name}<small><em className={status === '生成中' ? 'pending' : ''}>{index === 0 && loading ? '生成中' : status}</em>{time}</small></span><b>当前</b></button>)}</div>
      <button disabled className="report-list-more">历史报告未实现</button>
      <section className="report-subscriptions"><h3>报告订阅 <small>（未实现）</small></h3><p>当前 Alpha 只生成可审核草稿，不自动发送、发布或订阅。</p><button disabled>订阅未开放</button></section>
    </aside>

    <section className="report-canvas">
      <header className="report-titlebar">
        <div><div><h2>{reportName}</h2><span>{start} ～ {endInclusive(end)}（{reportType === 'weekly' ? '周报' : '月报'}）</span><em>{isReady ? '● 已完成' : '○ 生成中'}</em></div><p>生成时间：{generatedAt || '正在生成'}</p></div>
        <nav><button className="report-primary" onClick={() => void generate()}>▱　{loading ? '生成中…' : '生成报告'}</button><button disabled={!isReady} onClick={() => void download('markdown')}>▧　导出 MD</button><button disabled={!isReady} onClick={() => void download('csv')}>▧　导出 CSV</button><button disabled title="分享能力未实现">⌯　分享未开放</button></nav>
      </header>
      {error && <div className="report-error">{error}</div>}

      <section className={`report-executive${enabled.summary ? '' : ' section-off'}`}>
        <header><h3>一、管理摘要</h3><span>批次 {metadata?.batch_id || '数据加载中'}</span></header>
        <p>本期整体经营表现已按发布口径汇总；充电收入较上期 {momSummary}。设备在线率与经营变化仅作为同期关联线索，不构成因果结论。</p>
        <div className="report-kpis">{primaryMetrics.map(([id, label]) => {
          const comparison = deltaText(id, metrics[id], previous?.metrics[id])
          return <article key={id}><span>{label}</span><strong>{formatMetric(id, metrics[id])}</strong><small>较上期 <b className={comparison.includes('↓') ? 'down' : 'up'}>{comparison}</b></small></article>
        })}</div>
      </section>

      <section className="report-analysis-grid">
        <article className={`report-table-card${enabled.metric ? '' : ' section-off'}`}><header><h3>二、核心指标</h3></header><table><thead><tr><th>指标</th><th>本期值</th><th>上期值</th><th>环比变化</th><th>同比变化</th></tr></thead><tbody>{tableMetrics.map(([id, label]) => {
          const mom = deltaText(id, metrics[id], previous?.metrics[id])
          const yoy = deltaText(id, metrics[id], yearAgo?.metrics[id])
          return <tr key={id}><td>{label}</td><td>{formatMetric(id, metrics[id])}</td><td>{formatMetric(id, previous?.metrics[id])}</td><td className={mom.includes('↓') ? 'down' : 'up'}>{mom}</td><td className={yoy.includes('↓') ? 'down' : 'up'}>{yoy}</td></tr>
        })}</tbody></table></article>
        <article className={`report-chart-card${enabled.trend ? '' : ' section-off'}`}><header><h3>三、收入与毛利趋势</h3></header>{trend.length ? <ReportTrend revenue={trend} profit={profitTrend} margin={marginTrend} /> : <div className="report-chart-empty">正在加载趋势数据…</div>}</article>
      </section>

      <section className="report-detail-grid">
        <article className={enabled.anomaly ? '' : 'section-off'}><header><h3>四、主要异常 <em>△ 共 {anomalyRows.length} 项</em></h3></header><table><thead><tr><th>异常类型</th><th>影响值</th><th>状态</th></tr></thead><tbody>{anomalyRows.map((item: any) => <tr key={item.driver}><td>{driverNames[item.driver] || item.driver}</td><td className={item.contribution < 0 ? 'down' : 'up'}>{formatMetric('gross_profit', item.contribution)}</td><td>{item.contribution < 0 ? '需关注' : '正向'}</td></tr>)}</tbody></table><button disabled className="report-card-link">当前草稿全部异常　›</button></article>
        <article className={`report-station-card${enabled.station ? '' : ' section-off'}`}><header><h3>五、重点场站 TOP5（按毛利）</h3></header><table><thead><tr><th>排名</th><th>场站名称</th><th>毛利（元）</th><th>毛利率</th></tr></thead><tbody>{topStations.map((station, index) => <tr key={station.station_id}><td>{index + 1}</td><td>{station.station_name}</td><td>{formatMetric('gross_profit', station.metrics.gross_profit)}</td><td>{formatMetric('gross_margin', station.metrics.gross_margin)}</td></tr>)}</tbody></table><button disabled className="report-card-link">当前草稿全部场站　›</button></article>
        <article className={enabled.device ? '' : 'section-off'}><header><h3>六、设备问题分布</h3></header><div className="report-device"><div className="device-ring" style={{ background: deviceDonut }}><span><b>{formatMetric('device_online_rate', metrics.device_online_rate)}</b><small>在线率</small></span></div><ul><li><i className="healthy" />正常在线 <b>{(healthyRate * 100).toFixed(1)}%</b></li><li><i className="fault" />设备故障 <b>{(faultRate * 100).toFixed(1)}%</b></li><li><i className="offline" />设备离线 <b>{(offlineRate * 100).toFixed(1)}%</b></li></ul></div><button disabled className="report-card-link">设备详情跳转未实现　›</button></article>
      </section>

      <section className={`report-actions-card${enabled.action ? '' : ' section-off'}`}><div><h3>七、建议行动草稿</h3>{actionRows.map(action => <p key={action}><span>✓　{action}</span><b>负责人待补充</b><time>期限待补充</time></p>)}</div></section>
    </section>

    <aside className="report-settings">
      <header><h2>报告设置</h2><button onClick={() => setEnabled({ summary: true, metric: true, trend: true, anomaly: true, station: true, device: true, action: true })}>恢复默认</button></header>
      <section><h3>报告类型</h3><div className="report-type-buttons four"><button disabled>日报</button><button className={reportType === 'weekly' ? 'active' : ''} onClick={() => setReportType('weekly')}>周报</button><button className={reportType === 'monthly' ? 'active' : ''} onClick={() => setReportType('monthly')}>月报</button><button disabled>专题报告</button></div></section>
      <section><h3>时间范围</h3><div className="report-period-buttons"><button disabled className="active">本期</button><button disabled>上期未开放</button><button disabled>本月未开放</button><button disabled>上月未开放</button></div><p>{start}　～　{endInclusive(end)}　▣</p></section>
      <section><h3>区域范围</h3><p>全部区域　⌄</p></section>
      <section className="report-switches"><h3>模块开关</h3>{([['summary', '管理摘要'], ['metric', '核心指标'], ['trend', '收入与毛利趋势'], ['anomaly', '主要异常'], ['station', '重点场站 TOP5'], ['device', '设备问题分布'], ['action', '建议行动']] as Array<[keyof typeof enabled, string]>).map(([key, label]) => <label key={key}><span>◇　{label}</span><input type="checkbox" checked={enabled[key]} onChange={() => setEnabled(value => ({ ...value, [key]: !value[key] }))} /></label>)}</section>
      <section className="report-note"><h3>说明备注 <small>（选填）</small></h3><textarea maxLength={200} placeholder="请输入报告备注信息…" /><span>0/200</span><small>报告只生成可审核草稿，不会自动发送或发布。</small></section>
    </aside>
  </div>
}

type MappingField = {
  source: string
  source_type: string
  label: string
  standard: string
  target_type: string
  transform: string
  unit: string
}
type IntegrationSource = {
  source_id: string
  display_name: string
  source_type: 'postgresql' | 'mysql' | 'excel' | 'api'
  endpoint: { host: string | null; port: number | null; database_name: string | null; username: string | null; resource_locator: string | null }
  status: 'configured' | 'available' | 'unavailable'
  last_tested_at: string | null
  last_latency_ms: number | null
  last_error_code: string | null
  credential_stored: false
}
type IntegrationPreview = {
  station_id: string
  station_name: string
  region_id: string
  city_id: string | null
  charging_revenue: number | null
  charging_volume_kwh: number | null
  gross_profit: number | null
  gross_margin: number | null
}
type IntegrationWorkflow = {
  review_id: string
  run_id: string
  dataset_id: string
  quality_status: 'pending' | 'passed' | 'failed'
  workflow_status: 'quality_pending' | 'quality_passed' | 'quality_failed' | 'pending_approval' | 'approved' | 'published' | 'rejected'
  release_version: string | null
  requested_at: string | null
  decided_at: string | null
  published_at: string | null
  rejection_reason: string | null
  publication_scope?: string
  semantic_activation_status?: string
  formal_consumer_status?: string
  summary: { rules_checked?: number; rules_passed?: number; failures?: string[]; batch_id?: string }
  checks: Array<{
    rule_id: string
    rule_name: string
    severity: string
    status: 'passed' | 'failed'
    checked_at: string
  }>
}
type IntegrationOverview = {
  sources: IntegrationSource[]
  dataset: {
    dataset_id: string
    display_name: string
    source_id: string
    source_object: string
    target_table: string
    standard_schema: string
    mapping: MappingField[]
    status: string
    data_classification: string
  }
  preview: IntegrationPreview[]
  validations: Record<string, boolean>
  latest_ingestion: { run_id: string; status: string; rows_written: number } | null
  workflow: IntegrationWorkflow | null
  metadata: {
    data_classification: string
    source: string
    batch_id: string | null
    data_time_range: { start: string; end_exclusive: string }
    generated_at: string
    preview_source: string
    semantic_activation_status: string
    formal_consumer_status: string
  }
}

type PlatformFoundationState = {
  installed: boolean
  scenario: { scenario_id: string; version: string | null; status: string } | null
  dataset: { dataset_id: string; code: string; name: string; source_id: string; status: string } | null
  versions: Array<{
    dataset_version_id: string
    version: number
    status: string
    checksum: string
    row_count: number
    review_status: string | null
  }>
  activation: {
    activation_id: string
    dataset_version_id: string
    semantic_model_version_id: string
    semantic_version: string
    scenario_version: string
    lock_version: number
  } | null
  rollbacks: Array<{
    rollback_record_id: string
    from_dataset_version_id: string
    to_dataset_version_id: string
    reason: string
    run_id: string
  }>
  data_classification: 'simulated'
}

function MappingPage({ token, start, end }: { token: string; start: string; end: string }) {
  const [activeSource, setActiveSource] = useState('platform-postgresql')
  const [standardPreview, setStandardPreview] = useState(true)
  const [feedback, setFeedback] = useState('')
  const [integration, setIntegration] = useState<IntegrationOverview | null>(null)
  const [integrationError, setIntegrationError] = useState('')
  const [integrationLoading, setIntegrationLoading] = useState(true)
  const [workflowLoading, setWorkflowLoading] = useState(false)
  const [platform, setPlatform] = useState<PlatformFoundationState | null>(null)
  const [platformLoading, setPlatformLoading] = useState(false)
  const [platformError, setPlatformError] = useState('')
  const [discoveredTables, setDiscoveredTables] = useState<number | null>(null)
  const loadIntegration = async () => {
    setIntegrationLoading(true)
    try {
      setIntegration(await api<IntegrationOverview>(`/api/v1/data-integration/overview?start=${start}&end_exclusive=${end}`, token))
      setIntegrationError('')
    } catch (reason) {
      setIntegration(null)
      setIntegrationError(reason instanceof Error ? reason.message : '数据接入信息加载失败')
    } finally {
      setIntegrationLoading(false)
    }
  }
  const loadPlatform = async () => {
    setPlatformLoading(true)
    try {
      const result = await api<PlatformFoundationState>('/api/v1/platform/foundation', token)
      setPlatform(result)
      setPlatformError('')
      return result
    } catch (reason) {
      setPlatform(null)
      setPlatformError(reason instanceof Error ? reason.message : '平台版本状态加载失败')
      return null
    } finally {
      setPlatformLoading(false)
    }
  }
  useEffect(() => {
    void loadIntegration()
    void loadPlatform()
  }, [token, start, end])
  if (integrationLoading && !integration) {
    return <div className="mapping-page"><div className="notice">正在读取数据接入事实…</div></div>
  }
  if (integrationError || !integration) {
    return <div className="mapping-page"><div className="notice error"><h2>数据接入已阻塞</h2><p>{integrationError || '数据接入事实不可用'}</p><p>数据接入状态：Blocked</p><p>未显示任何替代业务数据，请恢复接口后重试。</p><button onClick={() => void loadIntegration()}>重新加载</button></div></div>
  }
  const mappingFields = integration.dataset.mapping
  const previewRows: IntegrationPreview[] = integration.preview
  const sourceOrder: Record<string, number> = { postgresql: 0, excel: 1, mysql: 2, api: 3 }
  const visibleSources = integration.sources
    .filter(source => source.source_id !== 'chatbi-postgresql')
    .sort((left, right) => sourceOrder[left.source_type] - sourceOrder[right.source_type])
  const sourceCards = visibleSources.map(source => {
    const status = source.status === 'available' ? '已验证' : source.status === 'unavailable' ? '连接失败' : '待测试'
    const detail = source.source_type === 'postgresql'
      ? [`连接：${source.endpoint.database_name || '平台主数据库'}`, '范围：charging_ops', '权限：受控只读']
      : source.source_type === 'mysql'
        ? [`主机：${source.endpoint.host || '待配置'}:${source.endpoint.port || 3306}`, '用途：辅助连接验证']
        : source.source_type === 'excel'
          ? [`文件：${source.endpoint.resource_locator || '待选择'}`, '解析后先写入 PostgreSQL']
          : [`地址：${source.endpoint.resource_locator || '待配置'}`, '响应校验后先写入 PostgreSQL']
    return {
      source,
      icon: source.source_type === 'postgresql' ? 'PG' : source.source_type === 'mysql' ? 'M' : source.source_type === 'excel' ? 'X' : 'API',
      tone: source.source_type === 'postgresql' ? 'postgres' : source.source_type,
      title: source.display_name,
      status,
      detail,
    }
  })
  const activeSourceRecord = integration.sources.find(source => source.source_id === activeSource)
  const validations: Array<[string, boolean]> = [
    ['映射配置', integration.validations.mapping],
    ['样例数据', integration.validations.sample],
    ['类型预览', integration.validations.types],
    ['时间范围', integration.validations.time_range],
    ['主键唯一性', integration.validations.primary_key],
    ['溯源字段', integration.validations.lineage],
  ]
  const workflow = integration?.workflow
  const validationRows: Array<[string, boolean]> = workflow?.checks.length
    ? workflow.checks.map(check => [`${check.rule_id} ${check.rule_name}`, check.status === 'passed'])
    : validations
  const workflowLabels: Record<string, string> = {
    quality_pending: '待质量校验',
    quality_passed: '质量已通过',
    quality_failed: '质量未通过',
    pending_approval: '待管理员审批',
    approved: '审批已通过',
    published: `已发布 ${workflow?.release_version || ''}`.trim(),
    rejected: '审批已驳回',
  }
  const workflowStatusLabel = workflow ? workflowLabels[workflow.workflow_status] : integration?.latest_ingestion ? '待质量校验' : '等待试运行'
  const workflowButtonLabel = !integration?.latest_ingestion
    ? '先执行试运行'
    : !workflow
      ? '执行质量校验'
      : workflow.workflow_status === 'quality_passed'
        ? '提交审批'
        : workflow.workflow_status === 'pending_approval'
          ? '审批通过'
          : workflow.workflow_status === 'approved'
            ? '发布数据集'
            : workflow.workflow_status === 'published'
              ? `已发布 ${workflow.release_version || ''}`
              : workflow.workflow_status === 'quality_failed' || workflow.workflow_status === 'rejected'
                ? '重新试运行'
                : '继续治理流程'
  const act = (message: string) => {
    setFeedback(message)
    window.setTimeout(() => setFeedback(''), 2600)
  }
  const postIntegration = async <T,>(path: string, payload: object): Promise<T> => {
    const response = await fetch(path, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) throw new Error(body?.detail?.message || '操作失败')
    return body as T
  }
  const testConnection = async () => {
    if (!activeSourceRecord) return act('数据源目录仍在加载。')
    let password: string | undefined
    let resource_locator: string | undefined
    if ((activeSourceRecord.source_type === 'mysql' || (activeSourceRecord.source_type === 'postgresql' && activeSourceRecord.source_id !== 'platform-postgresql'))) {
      password = window.prompt('请输入本次连接测试密码（仅用于本次请求，不会保存）') || undefined
      if (!password) return act('已取消连接测试，未保存任何凭据。')
    } else if (activeSourceRecord.source_type === 'excel') {
      resource_locator = window.prompt('请输入受控导入目录内的 xlsx/csv 文件名', activeSourceRecord.endpoint.resource_locator || '') || undefined
      if (!resource_locator) return act('已取消文件连接测试。')
    } else if (activeSourceRecord.source_type === 'api') {
      resource_locator = window.prompt('请输入已允许的 API 地址', activeSourceRecord.endpoint.resource_locator || '') || undefined
      if (!resource_locator) return act('已取消 API 连接测试。')
    }
    try {
      const result = await postIntegration<{ latency_ms: number }>(`/api/v1/data-integration/sources/${activeSourceRecord.source_id}/test`, { password, resource_locator })
      act(`连接测试通过，耗时 ${result.latency_ms}ms；凭据未保存。`)
      await loadIntegration()
    } catch (reason) {
      act(reason instanceof Error ? reason.message : '连接测试失败')
      await loadIntegration()
    }
  }
  const runIngestion = async () => {
    if (!integration) return act('数据集仍在加载。')
    try {
      const result = await postIntegration<{ rows_written: number; run_id: string }>(`/api/v1/data-integration/datasets/${integration.dataset.dataset_id}/run`, { start, end_exclusive: end, limit: 30 })
      act(`试运行完成：${result.rows_written} 行已先写入 PostgreSQL，run_id=${result.run_id}`)
      await loadIntegration()
    } catch (reason) {
      act(reason instanceof Error ? reason.message : '试运行失败')
    }
  }
  const advanceWorkflow = async () => {
    if (!integration?.latest_ingestion) return act('请先执行试运行，让业务数据写入 PostgreSQL 暂存表。')
    if (workflowLoading) return
    const datasetId = integration.dataset.dataset_id
    const runId = integration.latest_ingestion.run_id
    setWorkflowLoading(true)
    try {
      let result: IntegrationWorkflow
      if (!workflow) {
        result = await postIntegration<IntegrationWorkflow>(`/api/v1/data-integration/datasets/${datasetId}/runs/${runId}/quality`, {})
        act(`质量校验完成：${result.summary.rules_passed || 0}/${result.summary.rules_checked || 0} 条通过。`)
      } else if (workflow.workflow_status === 'quality_passed') {
        result = await postIntegration<IntegrationWorkflow>(`/api/v1/data-integration/datasets/${datasetId}/runs/${runId}/submit`, {})
        act('批次已提交管理员审批，状态和操作人已写入数据库。')
      } else if (workflow.workflow_status === 'pending_approval') {
        if (!window.confirm('确认以数据分析师/管理员身份批准当前数据批次？')) return
        result = await postIntegration<IntegrationWorkflow>(`/api/v1/data-integration/datasets/${datasetId}/runs/${runId}/review`, { action: 'approve' })
        act('审批已通过，可执行受控发布。')
      } else if (workflow.workflow_status === 'approved') {
        result = await postIntegration<IntegrationWorkflow>(`/api/v1/data-integration/datasets/${datasetId}/runs/${runId}/publish`, {})
        act(`数据集 ${result.release_version || ''} 的不可变快照已发布；尚未原子激活为全部正式消费者数据源。`)
      } else if (workflow.workflow_status === 'published') {
        act(`当前批次已发布，版本 ${workflow.release_version || '已登记'}。`)
        return
      } else if (workflow.workflow_status === 'quality_failed' || workflow.workflow_status === 'rejected') {
        await runIngestion()
        return
      } else {
        act('当前治理状态不允许继续，请刷新后重试。')
        return
      }
      await loadIntegration()
    } catch (reason) {
      act(reason instanceof Error ? reason.message : '数据治理操作失败')
      await loadIntegration()
    } finally {
      setWorkflowLoading(false)
    }
  }
  const platformAction = async <T extends Record<string, unknown>>(
    path: string,
    payload: object,
    success: (result: T) => string,
  ) => {
    if (platformLoading) return
    setPlatformLoading(true)
    try {
      const result = await postIntegration<T>(path, payload)
      const nextState = (result as { state?: PlatformFoundationState }).state
      if (nextState) setPlatform(nextState)
      else await loadPlatform()
      setPlatformError('')
      act(success(result))
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '平台版本治理操作失败'
      setPlatformError(message)
      act(message)
      await loadPlatform()
    } finally {
      setPlatformLoading(false)
    }
  }
  const runQualityCheck = async () => {
    if (!integration.latest_ingestion) {
      await runIngestion()
      return
    }
    if (!workflow) {
      await advanceWorkflow()
      return
    }
    act(`质量检查状态：${workflow.quality_status}；失败规则：${workflow.summary.failures?.join('、') || '无'}。`)
  }
  const registerManagedSource = async () => {
    await platformAction<{ source_id: string; created: boolean }>(
      '/api/v1/platform/foundation/sources',
      {
        source_id: 'platform-postgresql',
        display_name: 'PostgreSQL 平台数据源',
        source_type: 'postgresql',
      },
      result => result.created ? `数据源 ${result.source_id} 已创建。` : `数据源 ${result.source_id} 已存在，幂等登记通过。`,
    )
    await loadIntegration()
  }
  const discoverSource = async () => {
    setPlatformLoading(true)
    try {
      const discovery = await api<{ table_count: number; schemas: Array<{ name: string }> }>(
        '/api/v1/platform/foundation/sources/platform-postgresql/discover',
        token,
      )
      setDiscoveredTables(discovery.table_count)
      setPlatformError('')
      act(`元数据发现完成：${discovery.schemas.length} 个 Schema，${discovery.table_count} 张受控表。`)
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '元数据发现失败'
      setDiscoveredTables(null)
      setPlatformError(message)
      act(message)
    } finally {
      setPlatformLoading(false)
    }
  }
  const installFoundation = async () => {
    await platformAction<{ state: PlatformFoundationState }>(
      '/api/v1/platform/foundation/install',
      {},
      result => `场景包 ${result.state.scenario?.version || ''}、语义模型和基础数据集版本已安装并激活。`,
    )
  }
  const createPlatformVersion = async () => {
    let current = platform
    if (!current?.installed) {
      setPlatformLoading(true)
      try {
        const installed = await postIntegration<{ state: PlatformFoundationState }>(
          '/api/v1/platform/foundation/install',
          {},
        )
        current = installed.state
        setPlatform(current)
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : '场景底座安装失败'
        setPlatformError(message)
        act(message)
        setPlatformLoading(false)
        return
      } finally {
        setPlatformLoading(false)
      }
    }
    if (!current.dataset) return act('平台数据集尚未安装。')
    await platformAction<{ dataset_version_id: string; state: PlatformFoundationState }>(
      `/api/v1/platform/foundation/datasets/${current.dataset.dataset_id}/versions`,
      {
        period_start: start,
        period_end_exclusive: end,
        idempotency_key: `ui-dataset-${Date.now()}`,
      },
      result => `不可变 DatasetVersion 已创建：${result.dataset_version_id}；状态为 QUALITY_PASSED，尚未生效。`,
    )
  }
  const submitPlatformVersion = async () => {
    const version = platform?.versions.find(item => item.status === 'QUALITY_PASSED')
    if (!version) return act('没有可提交的 QUALITY_PASSED 版本。')
    await platformAction(
      `/api/v1/platform/foundation/versions/${version.dataset_version_id}/submit`,
      {},
      () => `版本 v${version.version} 已提交审核。`,
    )
  }
  const approvePlatformVersion = async () => {
    const version = platform?.versions.find(item => item.status === 'PENDING_APPROVAL')
    if (!version) return act('没有待批准版本。')
    if (!window.confirm(`确认批准数据集版本 v${version.version}？批准不等于激活。`)) return
    await platformAction(
      `/api/v1/platform/foundation/versions/${version.dataset_version_id}/approve`,
      { idempotency_key: `ui-approve-${version.dataset_version_id}`, reason: '前端受控审批' },
      () => `版本 v${version.version} 已批准，仍未发布或激活。`,
    )
  }
  const rejectPlatformVersion = async () => {
    const version = platform?.versions.find(item => item.status === 'PENDING_APPROVAL')
    if (!version) return act('没有待驳回版本。')
    if (!window.confirm(`确认驳回数据集版本 v${version.version}？`)) return
    await platformAction(
      `/api/v1/platform/foundation/versions/${version.dataset_version_id}/reject`,
      { idempotency_key: `ui-reject-${version.dataset_version_id}`, reason: '前端受控驳回' },
      () => `版本 v${version.version} 已驳回，不能发布或激活。`,
    )
  }
  const publishPlatformVersion = async () => {
    const version = platform?.versions.find(item => item.status === 'APPROVED')
    if (!version) return act('没有可发布的 APPROVED 版本。')
    await platformAction(
      `/api/v1/platform/foundation/versions/${version.dataset_version_id}/publish`,
      { idempotency_key: `ui-publish-${version.dataset_version_id}` },
      () => `版本 v${version.version} 已发布，仍未替换 ACTIVE 版本。`,
    )
  }
  const activatePlatformVersion = async () => {
    const version = platform?.versions.find(item => item.status === 'PUBLISHED')
    if (!version) return act('没有可激活的 PUBLISHED 版本。')
    await platformAction(
      `/api/v1/platform/foundation/versions/${version.dataset_version_id}/activate`,
      { idempotency_key: `ui-activate-${version.dataset_version_id}`, reason: '前端原子激活' },
      () => `版本 v${version.version} 已原子激活，原 ACTIVE 已转为 SUPERSEDED。`,
    )
  }
  const showActiveVersion = async () => {
    const refreshed = await loadPlatform()
    const active = refreshed?.versions.find(item => item.dataset_version_id === refreshed.activation?.dataset_version_id)
    act(active ? `当前 ACTIVE：v${active.version} / ${active.dataset_version_id}` : '当前没有 ACTIVE 版本，正式查询将 fail-closed。')
  }
  const rollbackPlatformVersion = async () => {
    const currentId = platform?.activation?.dataset_version_id
    const target = platform?.versions.find(
      item => item.dataset_version_id !== currentId && ['SUPERSEDED', 'PUBLISHED'].includes(item.status),
    )
    if (!platform?.dataset || !target) return act('没有可用的已发布回滚目标。')
    if (!window.confirm(`确认回滚到 DatasetVersion v${target.version}？操作会写入 rollback_record。`)) return
    await platformAction(
      `/api/v1/platform/foundation/datasets/${platform.dataset.dataset_id}/rollback`,
      {
        target_dataset_version_id: target.dataset_version_id,
        idempotency_key: `ui-rollback-${Date.now()}`,
        reason: `前端回滚到 v${target.version}`,
      },
      () => `已回滚到 v${target.version}，审计与 rollback_record 已落库。`,
    )
  }
  const mappingSections = [
    ['数据类型转换', ['数字：decimal(18,2)', '字符串：varchar(100) → 标准文本']],
    ['单位转换', ['金额：元 → 元', '电量：kWh → kWh', '比例：小数 → %']],
    ['枚举映射', ['区域、城市与场站类型使用已验证业务枚举']],
    ['时间格式', [`数据范围：${start} 至 ${endInclusive(end)}`, '时区：Asia/Shanghai']],
    ['主键配置', ['主键字段：station_id　✎']],
    ['增量字段', ['当前视图按所选数据期只读刷新']],
  ] as const

  return <div className="mapping-page">
    <section className="mapping-flowbar">
      <div className="mapping-steps">{['数据源', '数据集', '字段映射', '同步任务', '数据质量'].map((label, index) => {
        const activeStep = !integration?.latest_ingestion ? 2 : workflow?.workflow_status === 'published' ? 5 : 4
        return <React.Fragment key={label}><div className={index === activeStep ? 'active' : index < activeStep ? 'done' : ''}><b>{index + 1}</b><span>{label}</span></div>{index < 4 && <i>›</i>}</React.Fragment>
      })}</div>
      <nav><button onClick={() => void testConnection()}>⟳　测试连接</button><button disabled title="自动推荐尚未实现">▣　自动推荐未开放</button><button onClick={() => void runIngestion()}>▷　试运行</button><button className="primary" disabled={workflowLoading} onClick={() => void advanceWorkflow()}>⌘　{workflowLoading ? '处理中…' : workflowButtonLabel}</button></nav>
    </section>

    {feedback && <div className="mapping-feedback">{feedback}</div>}
    {platformError && <div className="mapping-platform-error">Blocked / Error：{platformError}。未使用 fallback 数据。</div>}

    <section className="platform-release-flow">
      <header>
        <div>
          <h2>P1A 数据源 → ACTIVE DatasetVersion 真实闭环</h2>
          <p>所有操作调用后端服务并刷新数据库状态；批准、发布、激活是三个独立状态。</p>
        </div>
        <div className="platform-release-actions">
          <button disabled={!platform?.versions.some(item => item.status === 'PENDING_APPROVAL')} onClick={() => void rejectPlatformVersion()}>驳回待审版本</button>
          <button disabled={platformLoading} onClick={() => void installFoundation()}>
            {platformLoading ? '处理中…' : platform?.installed ? '重新校验场景底座' : '安装 charging_ops 场景底座'}
          </button>
        </div>
      </header>
      <div className="platform-release-steps">
        <button onClick={() => void registerManagedSource()}><b>1</b><span>创建数据源</span><small>幂等登记，无明文凭据</small></button>
        <button onClick={() => void testConnection()}><b>2</b><span>测试连接</span><small>{activeSourceRecord?.status || '待测试'}</small></button>
        <button onClick={() => void discoverSource()}><b>3</b><span>发现元数据</span><small>{discoveredTables == null ? 'Schema / Table / Column' : `${discoveredTables} 张受控表`}</small></button>
        <button onClick={() => void loadIntegration()}><b>4</b><span>数据预览</span><small>{previewRows.length ? `${previewRows.length} 行源投影` : 'Empty'}</small></button>
        <button onClick={() => act(`字段映射已从数据库读取：${mappingFields.length} 个字段；可在下方逐项核验。`)}><b>5</b><span>字段映射</span><small>{integration.validations.mapping ? '已验证' : 'Blocked'}</small></button>
        <button onClick={() => void runQualityCheck()}><b>6</b><span>质量检查</span><small>{workflow?.quality_status || '待运行'}</small></button>
        <button onClick={() => void createPlatformVersion()}><b>7</b><span>创建 DatasetVersion</span><small>不可变，默认非 ACTIVE</small></button>
        <button onClick={() => void submitPlatformVersion()}><b>8</b><span>提交审核</span><small>PENDING_APPROVAL</small></button>
        <button onClick={() => void approvePlatformVersion()}><b>9</b><span>批准</span><small>APPROVED ≠ ACTIVE</small></button>
        <button onClick={() => void publishPlatformVersion()}><b>10</b><span>发布</span><small>PUBLISHED ≠ ACTIVE</small></button>
        <button onClick={() => void activatePlatformVersion()}><b>11</b><span>激活</span><small>事务切换 ACTIVE</small></button>
        <button onClick={() => void showActiveVersion()}><b>12</b><span>当前 ACTIVE</span><small>{platform?.activation?.dataset_version_id || 'Empty / fail-closed'}</small></button>
        <button onClick={() => void rollbackPlatformVersion()}><b>13</b><span>回滚</span><small>{platform?.rollbacks.length || 0} 条记录</small></button>
      </div>
      <footer>
        <span>场景：{platform?.scenario ? `${platform.scenario.scenario_id}@${platform.scenario.version} / ${platform.scenario.status}` : '未安装'}</span>
        <span>版本数：{platform?.versions.length || 0}</span>
        <span>语义：{platform?.activation?.semantic_version || '未激活'}</span>
        <span>状态：{platformLoading ? 'Loading' : platformError ? 'Blocked' : platform?.installed ? 'Success' : 'Empty'}</span>
        <span>治理状态：{workflowStatusLabel}；语义激活：{integration.metadata.semantic_activation_status || 'not_implemented'}</span>
      </footer>
    </section>

    <section className="mapping-workspace">
      <aside className="mapping-source-panel">
        <header><h2>数据源列表</h2><button onClick={() => void registerManagedSource()}>＋ 登记平台源</button></header>
        <div className="mapping-source-list">{sourceCards.map(card => <button className={activeSource === card.source.source_id ? 'active' : ''} onClick={() => setActiveSource(card.source.source_id)} key={card.source.source_id}><span className={`mapping-source-icon ${card.tone}`}>{card.icon}</span><strong>{card.title}</strong><em className={card.source.status === 'configured' ? 'planned' : ''}>● {card.status}</em><i>⋯</i><small>{card.detail.map(line => <React.Fragment key={line}>{line}<br /></React.Fragment>)}</small></button>)}</div>
        <button disabled className="mapping-more">更多连接器未开放</button>
        <footer><b>能力边界</b><p>凭据只用于单次连接，不落库；业务数据解析校验后先写入 PostgreSQL，再由前端调用。</p></footer>
      </aside>

      <main className="mapping-center">
        <article className="mapping-field-panel">
          <header><div><b>当前数据集：</b><span>{integration.dataset.display_name}（{integration.dataset.dataset_id}）</span></div><div>来源表：{integration.dataset.source_object}　⟳</div><button disabled title="数据集切换尚未实现">切换未开放</button></header>
          <div className="mapping-table-wrap"><table><thead><tr><th>源字段（平台视图）</th><th>标准业务字段（charging_ops）</th><th>数据类型转换</th><th>单位/枚举转换</th><th>状态</th></tr></thead><tbody>{mappingFields.map(field => <tr key={field.source}><td><b>▦　{field.source}</b><span>{field.source_type}</span></td><td><i>→</i><b>{field.label}</b><span>{field.standard}</span><small>{field.target_type}</small></td><td>{field.transform}</td><td>{field.unit}</td><td><em>◎　已映射</em></td></tr>)}</tbody></table></div>
          <footer><button disabled title="自定义映射尚未实现">＋　自定义映射未开放</button><span>选择源字段　⌄</span><i>→</i><span>选择标准字段　⌄</span><span>选择转换方式　⌄</span><em>○　未映射</em></footer>
        </article>

        <article className="mapping-preview-panel">
          <header><h2>数据预览（前 {previewRows.length || 0} 行）</h2><label>以标准字段预览 <input type="checkbox" checked={standardPreview} onChange={() => setStandardPreview(value => !value)} /></label></header>
          <div><table><thead><tr><th>#</th><th>场站编码</th><th>场站名称</th><th>运营区域</th><th>充电收入（元）</th><th>充电电量（kWh）</th><th>毛利率</th></tr></thead><tbody>{previewRows.map((row, index) => <tr key={row.station_id}><td>{index + 1}</td><td>{row.station_id}</td><td>{row.station_name}</td><td>{row.region_id}</td><td>{money(row.charging_revenue)}</td><td>{money(row.charging_volume_kwh)}</td><td>{formatMetric('gross_margin', row.gross_margin)}</td></tr>)}</tbody></table>{!previewRows.length && <p className="mapping-empty">{integrationLoading ? '正在从 PostgreSQL 读取已授权数据预览…' : '数据库暂无可预览数据'}</p>}</div>
          <footer><span>共 {previewRows.length} 行数据库预览</span><span>生成时间：{integration.metadata.generated_at}　｜　<button onClick={() => void loadIntegration()}>⟳ 重新预览</button></span></footer>
        </article>
      </main>

      <aside className="mapping-right">
        <article className="mapping-config-panel"><header><h2>映射配置</h2><span className={workflow?.workflow_status === 'published' ? 'published' : ''}>{workflowStatusLabel}</span></header><div>{mappingSections.map(([title, lines]) => <section key={title}><h3>▦　{title}<em>●</em></h3>{lines.map(line => <p key={line}>{line}</p>)}</section>)}</div></article>
        <article className="mapping-validation-panel"><h2>校验状态 <small>{workflow?.summary.rules_checked ? `${workflow.summary.rules_passed}/${workflow.summary.rules_checked}` : '预览'}</small></h2><div>{validationRows.map(([label, passed]) => <p key={label}><span>{label}</span><b className={passed ? '' : 'waiting'}>{passed ? '●　通过' : '●　未通过'}</b></p>)}</div><button onClick={() => act(workflow ? `质量结果已落库；失败规则：${workflow.summary.failures?.join('、') || '无'}。` : '请先完成试运行，再执行数据库质量校验。')}>查看校验详情</button></article>
      </aside>
    </section>

  </div>
}

function BoundaryPage({ active, summary }: { active: ViewId; summary: Summary | null }) {
  const messages: Record<string, string> = {
    alerts: '当前入口使用已实现的规则异常、同比环比与贡献拆解能力；完整预警工作流不属于本界面复刻范围。',
    reports: '当前 Alpha 只生成可审核报告草稿，不自动发送或发布。',
    mapping: '当前入口使用已验证的数据治理链路，不接入未经授权的企业数据。',
    metrics: '当前已发布 15 项核心指标与 charging_ops 场景，组织规则发布仍需管理员或指标负责人审批。',
  }
  return <div className="boundary-page"><article><i>{active === 'reports' ? '报' : active === 'metrics' ? '指' : active === 'mapping' ? '数' : '警'}</i><h2>{titles[active]}</h2><p>{messages[active]}</p><div className="evidence"><span>批次：{summary?.metadata.batch_id || '加载中'}</span><span>能力边界：如实展示</span></div></article></div>
}

function Sidebar({ active, navigate }: { active: ViewId; navigate: (id: ViewId) => void }) {
  return <aside className="product-sidebar"><div className="brand"><img src="/figma-assets/brand-mark.svg" alt="" /><strong>新能源经营分析智能平台</strong></div><nav>{groups.map(group => <section key={group.title}><h2>{group.title}</h2>{group.items.map(item => <button key={item.id} className={active === item.id ? 'active' : ''} onClick={() => navigate(item.id)}><i>{item.icon}</i><span>{item.label}</span></button>)}</section>)}</nav><button disabled className="collapse" title="菜单折叠未实现"><i>≡</i><span>折叠未开放</span><b>«</b></button></aside>
}

function ProductHeader({ active, start, end, setStart, setEnd, logout }: { active: ViewId; start: string; end: string; setStart: (v: string) => void; setEnd: (v: string) => void; logout: () => void }) {
  const showSearchAndDate = active === 'overview' || active === 'revenue' || active === 'margin' || active === 'stations' || active === 'devices' || active === 'alerts' || active === 'reports' || active === 'mapping' || active === 'metrics'
  const searchPlaceholder = '全局搜索尚未实现'
  return <header className={`product-header${active === 'chat' ? ' chat-header' : ''}`}><div className="page-title">{active === 'alerts' && <i className="alert-header-icon">♧</i>}<h1>{titles[active]}</h1>{(active === 'overview' || active === 'margin') && <span>当前场景：<b>charging_ops</b>｜充电运营</span>}{active === 'dashboard' && <small>数据范围：{start} 至 {endInclusive(end)}</small>}</div>{showSearchAndDate && <><label className="search"><i>⌕</i><input disabled aria-label="全局搜索" placeholder={searchPlaceholder} /></label><div className="date-range"><input aria-label="开始日期" type="date" value={start} onChange={e => setStart(e.target.value)} /><span>～</span><input aria-label="结束日期" type="date" value={endInclusive(end)} onChange={e => { const next = new Date(`${e.target.value}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1); setEnd(next.toISOString().slice(0, 10)) }} /></div></>}{active === 'chat' && <><button disabled className="chat-model">分析模式　确定性链路</button><div className="chat-period">{start}　~　{endInclusive(end)}　▣</div></>}<button disabled className="organization">单客户工作区</button><button disabled className="bell" aria-label="通知未开放" title="通知未实现">♧</button><button className="profile" onClick={logout} title="点击退出当前会话"><span>会</span><div><b>当前会话</b><small>认证用户 · 点击退出</small></div><i>⌄</i></button></header>
}

function ProductShell({ token, logout }: { token: string; logout: () => void }) {
  const [active, setActive] = useState<ViewId>('overview')
  const [context, setContext] = useState<FrontendContext | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [stations, setStations] = useState<StationRow[]>([])
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const primary = useMemo(() => active === 'stations' ? 'charging_revenue' : pageMetrics[active]?.[0] || 'charging_revenue', [active])
  useEffect(() => {
    let cancelled = false
    api<FrontendContext>('/api/v1/dashboard/context', token)
      .then(result => {
        if (cancelled) return
        setContext(result)
        setStart(result.default_time_range.start)
        setEnd(result.default_time_range.end_exclusive)
      })
      .catch(reason => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '前端数据上下文加载失败')
      })
    return () => { cancelled = true }
  }, [token])
  useEffect(() => {
    if (!start || !end) return
    let cancelled = false
    setLoading(true)
    setError('')
    const query = `start=${start}&end_exclusive=${end}`
    Promise.all([
      api<Summary>(`/api/v1/dashboard/summary?${query}`, token),
      api<{ rows: StationRow[] }>(`/api/v1/dashboard/stations?${query}&limit=10&metrics=charging_revenue,gross_profit,gross_margin,charging_volume_kwh,energy_cost,variable_operating_cost,revenue_per_kwh,cost_per_kwh,station_utilization_rate,device_online_rate,device_fault_rate`, token),
      api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=${primary}&${query}`, token),
    ]).then(([summaryResult, stationResult, trendResult]) => {
      if (!cancelled) { setSummary(summaryResult); setStations(stationResult.rows); setTrend(trendResult.points) }
    }).catch(reason => {
      if (!cancelled) {
        setSummary(null)
        setStations([])
        setTrend([])
        setError(reason instanceof Error ? reason.message : '加载失败')
      }
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token, start, end, primary, refreshKey])
  let content: React.ReactNode
  if (!start || !end) content = <div className={`notice${error ? ' error' : ''}`}>{error || '正在从数据库读取可用数据周期…'}</div>
  else if (active === 'overview') content = <Overview summary={summary} trend={trend} loading={loading} error={error} navigate={setActive} context={context} />
  else if (active === 'dashboard') content = <WorkbenchPage token={token} summary={summary} stations={stations} revenueTrend={trend} start={start} end={end} setStart={setStart} setEnd={setEnd} navigate={setActive} refreshKey={refreshKey} refresh={() => setRefreshKey(value => value + 1)} />
  else if (active === 'revenue') content = <>{error && <div className="notice error">{error}</div>}<RevenuePage token={token} summary={summary} stations={stations} start={start} end={end} setStart={setStart} setEnd={setEnd} refresh={() => setRefreshKey(value => value + 1)} /></>
  else if (active === 'margin') content = <>{error && <div className="notice error">{error}</div>}<MarginPage token={token} summary={summary} stations={stations} start={start} end={end} setStart={setStart} setEnd={setEnd} refresh={() => setRefreshKey(value => value + 1)} /></>
  else if (active === 'stations') content = <>{error && <div className="notice error">{error}</div>}<StationPage token={token} summary={summary} stations={stations} trend={trend} start={start} end={end} setStart={setStart} setEnd={setEnd} refresh={() => setRefreshKey(value => value + 1)} navigate={setActive} /></>
  else if (active === 'devices') content = <>{error && <div className="notice error">{error}</div>}<DevicePage token={token} summary={summary} start={start} end={end} setStart={setStart} setEnd={setEnd} refresh={() => setRefreshKey(value => value + 1)} /></>
  else if (active === 'chat') content = <ChatPage token={token} start={start} end={end} />
  else if (active === 'alerts') content = <DiagnosticsPage token={token} start={start} end={end} />
  else if (active === 'reports') content = <ReportPage token={token} start={start} end={end} summary={summary} stations={stations} trend={trend} />
  else if (active === 'knowledge') content = <KnowledgePage token={token} />
  else if (active === 'memory') content = <MemoryPage token={token} />
  else if (active === 'skills') content = <SkillPage token={token} />
  else if (active === 'mapping') content = <MappingPage token={token} start={start} end={end} />
  else if (active === 'metrics') content = <MetricsPage token={token} summary={summary} start={start} end={end} />
  else if (active === 'governance') content = <GovernancePage token={token} />
  else content = <>{error && <div className="notice error">{error}</div>}<DetailPage active={active} summary={summary} stations={stations} trend={trend} /></>
  const shellMode = active === 'revenue' ? ' revenue-mode' : active === 'margin' ? ' margin-mode' : active === 'stations' ? ' station-mode' : active === 'devices' ? ' device-mode' : active === 'alerts' ? ' alert-mode' : active === 'reports' ? ' report-mode' : active === 'knowledge' ? ' knowledge-mode' : active === 'memory' || active === 'skills' || active === 'governance' ? ' governance-mode' : active === 'mapping' ? ' mapping-mode' : active === 'metrics' ? ' metrics-mode' : ''
  const mainMode = active === 'revenue' ? ' revenue-main' : active === 'margin' ? ' margin-main' : active === 'stations' ? ' station-main' : active === 'devices' ? ' device-main' : active === 'alerts' ? ' alert-main' : active === 'reports' ? ' report-main' : active === 'knowledge' ? ' knowledge-main' : active === 'memory' || active === 'skills' || active === 'governance' ? ' governance-main' : active === 'mapping' ? ' mapping-main' : active === 'metrics' ? ' metrics-main' : ''
  return <div className={`product-shell${shellMode}`}><Sidebar active={active} navigate={setActive} /><div className="workspace"><ProductHeader active={active} start={start} end={end} setStart={setStart} setEnd={setEnd} logout={logout} /><main className={`product-main${mainMode}`}>{content}</main><GlobalDataStatus metadata={summary?.metadata ?? context?.metadata ?? null} /></div></div>
}

function Login({ loggedIn }: { loggedIn: (token: string) => void }) {
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const login = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setLoading(true)
    const form = new FormData(event.currentTarget)
    try {
      const response = await fetch('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: form.get('username'), password: form.get('password') }) })
      if (!response.ok) throw new Error('登录失败，请检查账号和密码')
      const data = await response.json()
      localStorage.setItem('alpha_token', data.access_token)
      loggedIn(data.access_token)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }
  return <main className="product-login"><form onSubmit={login}><div className="login-brand"><img src="/figma-assets/brand-mark.svg" alt="" /><span><strong>新能源经营分析智能平台</strong><small>AI 增强 BI · 产品级 Alpha</small></span></div><h1>欢迎登录</h1><p>统一指标、可信问数与经营洞察</p><div className="login-truth">数据环境状态将在登录后统一展示</div><label>账号<input name="username" defaultValue="analyst" autoComplete="username" /></label><label>密码<input name="password" type="password" defaultValue="AlphaAnalyst!2026" autoComplete="current-password" /></label><button disabled={loading}>{loading ? '正在安全登录…' : '安全登录'}</button>{error && <div className="login-error">{error}</div>}</form></main>
}

export function ProductApp() {
  const [token, setToken] = useState(localStorage.getItem('alpha_token') || '')
  return token ? <ProductShell token={token} logout={() => { localStorage.removeItem('alpha_token'); setToken('') }} /> : <Login loggedIn={setToken} />
}
