import React, { useEffect, useMemo, useRef, useState } from 'react'
import { formatMetric, metricNames } from './format'
import './overview.css'

type Metadata = {
  data_classification: string
  data_time_range: { start: string; end_exclusive: string }
  source: string
  batch_id: string | null
  analysis_run_id: string
  generated_at?: string
}
type Summary = { metrics: Record<string, number | null>; metadata: Metadata }
type TrendPoint = { period: string; value: number | null }
type StationRow = {
  station_id: string
  station_name: string
  region_id: string
  city_id: string
  station_type: string
  metrics: Record<string, number | null>
}
type ViewId = 'overview' | 'dashboard' | 'revenue' | 'margin' | 'stations' | 'devices' | 'alerts' | 'chat' | 'reports' | 'mapping' | 'metrics'

const groups: Array<{ title: string; items: Array<{ id: ViewId; label: string; icon: string }> }> = [
  { title: '基础入口', items: [{ id: 'overview', label: '功能总览', icon: '⌂' }, { id: 'dashboard', label: '经营工作台', icon: '◫' }] },
  { title: '经营分析', items: [{ id: 'revenue', label: '收入与订单', icon: '▤' }, { id: 'margin', label: '毛利与成本', icon: '◴' }, { id: 'stations', label: '场站经营', icon: '♙' }, { id: 'devices', label: '设备健康', icon: '◇' }, { id: 'alerts', label: '经营预警', icon: '♧' }] },
  { title: '智能分析', items: [{ id: 'chat', label: 'AI经营分析', icon: 'AI' }] },
  { title: '内容管理', items: [{ id: 'reports', label: '经营报告', icon: '▱' }] },
  { title: '数据管理', items: [{ id: 'mapping', label: '数据接入与字段映射', icon: '◎' }, { id: 'metrics', label: '指标与场景管理', icon: '▧' }] },
]

const titles: Record<ViewId, string> = {
  overview: '功能总览', dashboard: '经营工作台', revenue: '收入与订单', margin: '毛利与成本',
  stations: '场站经营', devices: '设备健康', alerts: '经营预警', chat: 'AI经营分析',
  reports: '经营报告', mapping: '数据接入与字段映射', metrics: '指标与场景管理',
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
  const result = new Date(`${end}T00:00:00Z`)
  result.setUTCDate(result.getUTCDate() - 1)
  return result.toISOString().slice(0, 10)
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

function Overview({ summary, trend, loading, error, navigate }: { summary: Summary | null; trend: TrendPoint[]; loading: boolean; error: string; navigate: (id: ViewId) => void }) {
  const m = summary?.metrics ?? {}
  const questions = ['本期各区域充电收入排名如何？', '毛利率环比下降的主要原因？', '充电利用率偏低的场站有哪些？', '设备故障率最高的站点是哪些？', '夜间电量下降的主要原因？', '大功率订单占比趋势如何？']
  return <div className="overview-page">
    {error && <div className="notice error">{error}</div>}
    <section className={`overview-hero ${loading ? 'loading' : ''}`}>
      <div className="hero-copy">
        <h2>面向新能源充电运营企业的<br />AI 经营分析平台</h2>
        <p>整合多源数据，洞察经营全貌，驱动精细化运营与科学决策</p>
        <div className="truth-row"><b>模拟数据</b><span>来源：平台数据库</span><span>run：{summary?.metadata.analysis_run_id || '加载中'}</span></div>
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
      <article className="module-card"><ModuleTitle icon="站" color="violet" title="场站经营" subtitle="场站收入、利用率与排名分析" /><div className="util-bars">{[1, .83, .65, .47, .31].map((v, i) => <i key={i}><span style={{ width: `${Math.max((m.station_utilization_rate ?? 0) * v * 900, 15)}%` }} /></i>)}</div><div className="stack-metrics"><span>场站利用率<b>{formatMetric('station_utilization_rate', m.station_utilization_rate)}</b></span><span>充电量（kWh）<b>{formatMetric('charging_volume_kwh', m.charging_volume_kwh)}</b></span></div></article>
      <article className="module-card"><ModuleTitle icon="设" color="violet" title="设备健康" subtitle="设备在线率、故障率与健康评估" /><div className="ring-content"><Donut value={m.device_online_rate ?? 0} device /><div><span>设备在线率</span><b>{formatMetric('device_online_rate', m.device_online_rate)}</b><span>设备故障率</span><b>{formatMetric('device_fault_rate', m.device_fault_rate)}</b></div></div></article>
    </section>

    <section className="module-grid">
      <article className="module-card action"><ModuleTitle icon="警" color="red" title="经营预警" subtitle="风险预警、异常监控与告警管理" /><ul className="status-list warning"><li>毛利率异常<span>规则检测</span></li><li>高功率利用率异常<span>规则检测</span></li><li>设备离线告警<span>进入查看</span></li></ul><CardLink label="查看预警中心" onClick={() => navigate('alerts')} /></article>
      <article className="module-card action"><ModuleTitle icon="AI" color="blue" title="AI经营分析" subtitle="自然语言分析、智能问答与归因" /><div className="ask-sample">区域A的充电收入环比下降原因？</div><button className="ask-button" onClick={() => navigate('chat')}>◉　向 AI 提问 <b>›</b></button><CardLink label="查看分析洞察" onClick={() => navigate('chat')} /></article>
      <article className="module-card action"><ModuleTitle icon="报" color="teal" title="经营报告" subtitle="经营日报、周报、月报与专题报告" /><ul className="status-list"><li>经营日报<span>按需生成</span></li><li>经营周报<span>草稿可审核</span></li><li>经营月报<span>结果可追溯</span></li></ul><CardLink label="查看全部报告" onClick={() => navigate('reports')} /></article>
      <article className="module-card action"><ModuleTitle icon="数" color="blue" title="数据接入与映射" subtitle="数据连接、同步管理与字段映射" /><ul className="status-list"><li>平台数据源<span>已连接</span></li><li>数据批次<span>{summary?.metadata.batch_id ? '可追溯' : '加载中'}</span></li><li>数据口径<span>已发布</span></li></ul><CardLink label="进入映射配置" onClick={() => navigate('mapping')} /></article>
      <article className="module-card action"><ModuleTitle icon="指" color="orange" title="指标与场景管理" subtitle="指标体系、业务场景与权限管理" /><ul className="status-list"><li>核心指标<span>15 项</span></li><li>当前场景<span>充电运营</span></li><li>权限模式<span>RBAC</span></li></ul><CardLink label="进入管理中心" onClick={() => navigate('metrics')} /></article>
    </section>

    <section className="bottom-grid">
      <article className="bottom-card questions"><header><h3>常用分析入口</h3><button>⟳ 换一批</button></header><div>{questions.map((question, index) => <button key={question} onClick={() => navigate('chat')}><i>{index % 2 ? '⌁' : '↗'}</i>{question}</button>)}</div></article>
      <article className="bottom-card system"><header><h3>近期动态 / 系统状态</h3></header><ul><li><i>◷</i><span>数据最后刷新</span><b>{summary?.metadata.generated_at ? new Date(summary.metadata.generated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '加载中'}</b></li><li><i>♧</i><span>预警告警</span><b className="attention">进入预警查看</b></li><li><i>▱</i><span>报告生成</span><b>草稿按需生成</b></li><li><i>◎</i><span>数据同步状态</span><b>平台数据库已连接</b></li><li><i>✓</i><span>系统运行状态</span><b className="healthy">正常</b></li></ul></article>
      <article className="bottom-card guide"><header><h3>视图说明</h3></header><div><i>业</i><span><b>业务视图</b><small>面向运营与分析人员，聚焦经营分析与监控</small></span></div><div><i>管</i><span><b>管理视图</b><small>面向管理员，负责配置与系统管理</small></span></div><button>了解更多视图差异　→</button></article>
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
      <div className="summary-actions"><small>数据截止：{endInclusive(end)}　来源：平台数据库</small><div><button onClick={() => navigate('alerts')}>◉　查看分析依据</button><button onClick={() => navigate('chat')}>◎　继续追问</button><button className="primary" onClick={() => navigate('reports')}>▱　生成报告</button></div></div>
    </section>

    <section className="workbench-kpis">
      {cards.map(card => {
        const display = workbenchValue(card.id, metrics[card.id])
        return <article key={card.id}><header><i className={card.color}>{card.icon}</i><h3>{card.label}</h3><span>ⓘ</span></header><div className="kpi-number"><strong>{display.value}</strong><small>{display.unit}</small></div><p><span>环比 <b className={rate(metrics[card.id], previousMetrics[card.id]) != null && rate(metrics[card.id], previousMetrics[card.id])! < 0 ? 'down' : 'up'}>{deltaText(card.id, metrics[card.id], previousMetrics[card.id])}</b></span><span>同比 <b className={rate(metrics[card.id], yearAgoMetrics[card.id]) != null && rate(metrics[card.id], yearAgoMetrics[card.id])! < 0 ? 'down' : 'up'}>{deltaText(card.id, metrics[card.id], yearAgoMetrics[card.id])}</b></span></p><MiniLine points={trends[card.id] ?? revenueTrend} stroke={card.stroke} /><footer><span>指标状态　已验证</span><i className={card.color} /></footer></article>
      })}
    </section>

    <section className="workbench-analysis">
      <article className="trend-panel"><header><h3>收入与毛利趋势（万元）</h3><div><button className="active">月</button></div></header><ComboTrend revenue={trends.charging_revenue ?? revenueTrend} profit={trends.gross_profit ?? []} /></article>
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
  if (!summary) return <div className="notice">正在从平台数据库计算指标…</div>
  const ids = pageMetrics[active] || pageMetrics.dashboard
  const primary = ids[0]
  const max = Math.max(...stations.map(row => row.metrics[primary] ?? 0), 1)
  return <div className="detail-page">
    <div className="evidence"><b>模拟数据</b><span>数据时间：{summary.metadata.data_time_range.start} 至 {endInclusive(summary.metadata.data_time_range.end_exclusive)}</span><span>来源：平台数据库</span><span>run：{summary.metadata.analysis_run_id}</span></div>
    <section className="detail-kpis">{ids.map(id => <article key={id}><span>{metricNames[id]}</span><strong>{formatMetric(id, summary.metrics[id])}</strong><small>指标语义层 v0.1.0</small></article>)}</section>
    <section className="detail-grid"><article><h2>{metricNames[primary]}月度趋势</h2><p>按 Asia/Shanghai 自然月聚合</p><MiniLine points={trend} large /></article><article><h2>场站贡献排名</h2><p>{metricNames[primary]} Top 10</p><div className="ranking">{stations.map((row, index) => <div key={row.station_id}><b>{index + 1}</b><span>{row.station_name}<small>{row.region_id} · {row.station_type}</small></span><i><em style={{ width: `${(row.metrics[primary] ?? 0) / max * 100}%` }} /></i><strong>{formatMetric(primary, row.metrics[primary])}</strong></div>)}</div></article></section>
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

  if (!summary) return <div className="notice">正在从平台数据库计算场站经营指标…</div>

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
      <div className="station-truth"><b>模拟数据</b><span>{summary.metadata.data_time_range.start} 至 {endInclusive(summary.metadata.data_time_range.end_exclusive)}</span><span>来源：{summary.metadata.source}</span><span title={summary.metadata.analysis_run_id}>run：{summary.metadata.analysis_run_id}</span></div>
    </section>

    <section className="station-kpis">
      {cards.map(card => <article key={card.id}>
        <i className={card.tone}>{card.icon}</i>
        <div><span>{card.label}</span><p><strong>{card.value}</strong>{card.unit && <em>{card.unit}</em>}</p><small>较上期 <b className={card.delta.includes('↓') ? 'down' : 'up'}>{card.delta}</b></small></div>
      </article>)}
    </section>

    <section className="station-top-grid">
      <article className="station-panel matrix-panel"><header><h2>场站矩阵分布 <small>（本页中位数分层；气泡大小：收入）</small></h2><select aria-label="矩阵区域" value={region} onChange={event => setRegion(event.target.value)}><option value="all">全部区域</option>{regionOptions.map(option => <option value={option} key={option}>{option}</option>)}</select></header><StationMatrix stations={visibleStations} thresholds={thresholds} selectedId={selected?.station_id} select={setSelectedId} /><footer>{(Object.keys(stationSegmentMeta) as StationSegment[]).map(segment => <span key={segment}><i style={{ background: stationSegmentMeta[segment].color }} />{stationSegmentMeta[segment].label}</span>)}</footer></article>
      <article className="station-panel region-panel"><header><h2>区域表现分布</h2><button type="button">查看地图　›</button></header><div>{regionStats.map((item, index) => <section key={item.id}><i>{index + 1}</i><strong>{item.id}</strong><em>场站数 {item.count}</em><p><span>利用率　<b>{formatMetric('station_utilization_rate', item.utilization)}</b></span><span>毛利率　<b>{formatMetric('gross_margin', item.margin)}</b></span><span>收入(万)　<b>{(item.revenue / 10000).toFixed(1)}</b></span></p></section>)}</div></article>
      <article className="station-panel segment-panel"><header><div><h2>场站等级分布</h2><p>本页场站 {stations.length} 个 · 相对分层</p></div></header><div className="segment-overview"><div className="segment-donut" style={{ background: donut }}><span><small>场站总数</small><b>{stations.length} 个</b></span></div><ul>{(Object.keys(stationSegmentMeta) as StationSegment[]).map(segment => <li key={segment}><i style={{ background: stationSegmentMeta[segment].color }} /><span>{stationSegmentMeta[segment].label}</span><b>{segmentCounts[segment]}（{(segmentCounts[segment] / total * 100).toFixed(1)}%）</b></li>)}</ul></div><div className="segment-cards">{(Object.keys(stationSegmentMeta) as StationSegment[]).map(segment => <button type="button" key={segment} className={segment} onClick={() => setStatus(status === segment ? 'all' : segment)}><span>{stationSegmentMeta[segment].label}<b>{segmentCounts[segment]} ↑</b></span><small>{stationSegmentMeta[segment].description}</small><em>收入占比 {stations.length ? (stations.filter(row => stationSegment(row, thresholds) === segment).reduce((sum, row) => sum + (row.metrics.charging_revenue ?? 0), 0) / Math.max(stations.reduce((sum, row) => sum + (row.metrics.charging_revenue ?? 0), 0), 1) * 100).toFixed(1) : '0.0'}%</em></button>)}</div></article>
    </section>

    <section className="station-bottom-grid">
      <article className="station-panel rank-panel"><header><h2>场站综合排名</h2><div>{(['all', 'core', 'growth', 'cost', 'priority'] as const).map(segment => <button type="button" className={status === segment ? 'active' : ''} key={segment} onClick={() => setStatus(segment)}>{segment === 'all' ? '全部场站' : stationSegmentMeta[segment].label}</button>)}</div></header><div className="station-table-wrap"><table><thead><tr><th>排名</th><th>场站名称</th><th>区域</th><th>城市</th><th>收入（元）</th><th>利用率</th><th>毛利率</th><th>在线率</th><th>综合得分</th><th>风险等级</th><th>操作</th></tr></thead><tbody>{rankedStations.slice(0, 5).map((row, index) => {
        const segment = stationSegment(row, thresholds)
        return <tr key={row.station_id} className={selected?.station_id === row.station_id ? 'selected' : ''} onClick={() => setSelectedId(row.station_id)}><td>{index + 1}</td><td title={row.station_name}>{row.station_name}</td><td>{row.region_id}</td><td>{row.city_id}</td><td>{money(row.metrics.charging_revenue)}</td><td className="up">{formatMetric('station_utilization_rate', row.metrics.station_utilization_rate)}</td><td>{formatMetric('gross_margin', row.metrics.gross_margin)}</td><td>{formatMetric('device_online_rate', row.metrics.device_online_rate)}</td><td><b>{stationScore(row).toFixed(1)}</b></td><td><em className={segment}>{stationSegmentMeta[segment].label}</em></td><td><button type="button" aria-label={`查看${row.station_name}`}>◎</button></td></tr>
      })}</tbody></table></div><footer><span>显示 {rankedStations.slice(0, 5).length} / {rankedStations.length} 条</span><div><button type="button">‹</button><b>1</b><button type="button">2</button><button type="button">3</button><button type="button">…</button><button type="button">›</button><select aria-label="每页条数"><option>10 条/页</option></select></div></footer></article>

      <article className="station-panel station-detail-panel"><header><h2>场站详情（{selected?.station_name ?? '暂无场站'}）</h2><button type="button">更多详情　›</button></header>{selected && <><div className="detail-summary"><div><span>利用率</span><b>{formatMetric('station_utilization_rate', selected.metrics.station_utilization_rate)}</b></div><div><span>毛利率</span><b>{formatMetric('gross_margin', selected.metrics.gross_margin)}</b></div><div><span>在线率</span><b>{formatMetric('device_online_rate', selected.metrics.device_online_rate)}</b></div><div><span>经营分层</span><b style={{ color: selectedMeta.color }}>{selectedMeta.label}</b></div></div><div className="station-detail-body"><section><header><h3>趋势（当前数据区间）</h3><div><b>收入</b><span>利用率</span><span>毛利率</span></div></header><StationTrend points={trend} /></section><section><h3>结构化点评</h3><p>• 该站利用率 {formatMetric('station_utilization_rate', selected.metrics.station_utilization_rate)}，毛利率 {formatMetric('gross_margin', selected.metrics.gross_margin)}，当前归入“{selectedMeta.label}”。</p><p>• 设备在线率 {formatMetric('device_online_rate', selected.metrics.device_online_rate)}；设备与经营变化仅作相关线索，不构成因果结论。</p><button type="button" onClick={() => navigate('chat')}>◇　查看策略建议</button></section></div></>}</article>
    </section>
  </div>
}

const CHAT_INITIAL_QUESTION = '2026年6月充电收入环比变化的原因？'
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

function ChatPage({ token }: { token: string }) {
  const [question, setQuestion] = useState(CHAT_INITIAL_QUESTION)
  const [result, setResult] = useState<any>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [previous, setPrevious] = useState<Summary | null>(null)
  const [yearAgo, setYearAgo] = useState<Summary | null>(null)
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [history, setHistory] = useState<Array<{ question: string; time: string }>>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const initialized = useRef(false)

  const runQuestion = async (nextQuestion: string, currentConversation = conversationId) => {
    const normalized = nextQuestion.trim()
    if (!normalized) return
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/v1/chat/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: normalized, conversation_id: currentConversation }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail?.message || '问数失败')
      setResult(body)
      setConversationId(body.conversation_id)
      setHistory(items => [{ question: normalized, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }, ...items.filter(item => item.question !== normalized)].slice(0, 5))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '问数失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    Promise.all([
      api<Summary>('/api/v1/dashboard/summary?start=2026-06-01&end_exclusive=2026-07-01', token),
      api<Summary>('/api/v1/dashboard/summary?start=2026-05-01&end_exclusive=2026-06-01', token),
      api<Summary>('/api/v1/dashboard/summary?start=2025-06-01&end_exclusive=2025-07-01', token),
      api<{ points: TrendPoint[] }>('/api/v1/dashboard/trend?metric=charging_revenue&start=2026-01-01&end_exclusive=2026-07-01', token),
    ]).then(([currentResult, previousResult, yearAgoResult, trendResult]) => {
      setSummary(currentResult)
      setPrevious(previousResult)
      setYearAgo(yearAgoResult)
      setTrend(trendResult.points)
    }).catch(reason => setError(reason instanceof Error ? reason.message : '经营上下文加载失败'))
    void runQuestion(CHAT_INITIAL_QUESTION, null)
  }, [token])

  const ask = (event: React.FormEvent) => {
    event.preventDefault()
    void runQuestion(question)
  }
  const newSession = () => {
    setConversationId(null)
    setResult(null)
    setHistory([])
    setQuestion('')
    setError('')
  }

  const diagnosis = result?.result?.diagnosis
  const metrics = summary?.metrics ?? diagnosis?.current ?? {}
  const previousMetrics = previous?.metrics ?? diagnosis?.previous ?? {}
  const yearAgoMetrics = yearAgo?.metrics ?? {}
  const revenueChange = rate(metrics.charging_revenue, previousMetrics.charging_revenue)
  const bridge = diagnosis?.bridge ?? []
  const stationImpacts = diagnosis?.station_contributions ?? []
  const maxBridge = Math.max(...bridge.map((item: any) => Math.abs(item.contribution ?? 0)), 1)
  const strongestDriver = [...bridge].sort((a: any, b: any) => Math.abs(b.contribution) - Math.abs(a.contribution))[0]
  const conclusion = diagnosis
    ? `结论：全部授权区域 2026年6月充电收入为 ${money(metrics.charging_revenue)} 元，环比${revenueChange != null && revenueChange < 0 ? '下降' : '上升'} ${revenueChange == null ? '数据不足' : `${(Math.abs(revenueChange) * 100).toFixed(2)}%`}。变化拆解中贡献最大项为${chatDriverNames[strongestDriver?.driver] ?? '其他因素'}；关联线索不构成因果结论。`
    : result?.answer
  const cards = [
    { id: 'charging_revenue', label: '充电收入', icon: '¥', color: 'teal' },
    { id: 'charging_volume_kwh', label: '充电量', icon: '↯', color: 'teal' },
    { id: 'revenue_per_kwh', label: '度电收入', icon: '价', color: 'orange' },
    { id: 'gross_margin', label: '毛利率', icon: '率', color: 'red' },
  ]
  const suggestions = ['毛利率低于行业均值的原因？', '场站利用率下降原因', '度电成本上升原因']

  return <div className="ai-analysis-page">
    <h2 className="chat-trust-title">可信 ChatBI</h2>
    <aside className="chat-history-panel">
      <header><h2>会话历史</h2><button onClick={newSession}>＋ 新会话</button></header>
      <div className="chat-history-list">{history.length ? history.map((item, index) => <button key={`${item.time}-${item.question}`} className={index === 0 ? 'active' : ''} onClick={() => setQuestion(item.question)}><span>{item.question}</span><small>{item.time}</small></button>) : <p>新会话尚未产生分析记录</p>}</div>
      <section><header><h3>本次会话</h3><span>{history.length} 条</span></header><dl><div><dt>会话状态</dt><dd>{result?.status ?? '准备中'}</dd></div><div><dt>状态版本</dt><dd>v{result?.state_version ?? 0}</dd></div><div><dt>隔离范围</dt><dd>当前用户</dd></div></dl></section>
      <section className="chat-example-list"><header><h3>分析示例</h3></header>{['全平台收入与毛利分析', '场站贡献下降定位', '设备指标关联排查'].map(item => <button key={item} onClick={() => setQuestion(item)}><span>▧</span>{item}<b>★</b></button>)}</section>
      <section className="chat-chain-card"><header><h3>可信分析链路</h3><span>已启用</span></header><ol><li>自然语言结构化解析</li><li>Query Plan 合同校验</li><li>确定性参数化编译</li><li>只读执行与权限过滤</li><li>Answer Guard 证据检查</li></ol></section>
    </aside>

    <main className="chat-analysis-center">
      <form className="chat-question-box" onSubmit={ask}><div><textarea aria-label="经营分析问题" maxLength={1000} value={question} onChange={event => setQuestion(event.target.value)} /><span>{question.length}/1000</span><button aria-label="发送分析问题" disabled={loading}>{loading ? '…' : '➤'}</button></div><footer><span>试试这样问：</span>{suggestions.map(item => <button type="button" key={item} onClick={() => setQuestion(item)}>{item}</button>)}</footer></form>
      <section className="chat-recommended"><h3>推荐追问</h3><div>{['夜间电量下降的主要原因？', '低功率时段占比为何上升？', '快充占比下降的原因？', '与周边区域对比表现如何？'].map(item => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}</div><span>⟳ 换一批</span></section>
      <section className="chat-conditions"><h3>当前条件</h3><div><span>时间范围　2026-06-01 ~ 2026-06-30</span><span>区域筛选　全部区域⌄</span><span>业务类型　充电⌄</span><span>站点类型　全部⌄</span><span>设备类型　全部⌄</span><button onClick={() => setQuestion(CHAT_INITIAL_QUESTION)}>重置条件</button></div></section>

      <article className="chat-answer-card">
        <header><div><i>✦</i><h2>AI结论</h2><small>{loading ? '正在执行受控分析…' : result ? '已完成可信分析' : '等待分析'}</small></div><nav><button>☆ 收藏</button><button>⇧ 导出</button><button>↗ 分享</button><button>•••</button></nav></header>
        {error && <div className="notice error">{error}</div>}
        <p className="chat-conclusion">{conclusion || '正在通过 Query Plan、确定性 SQL Compiler 与安全守卫计算结果…'}</p>
        <section className="chat-metric-grid">{cards.map(card => <article key={card.id}><header><i className={card.color}>{card.icon}</i><span>{card.label}<small>{card.id === 'charging_volume_kwh' ? '(kWh)' : card.id.includes('revenue') ? '(元)' : ''}</small></span></header><strong>{card.id === 'charging_revenue' ? money(metrics[card.id]) : card.id === 'charging_volume_kwh' ? Math.round(metrics[card.id] ?? 0).toLocaleString('zh-CN') : formatMetric(card.id, metrics[card.id])}</strong><footer><span>环比 <b className={rate(metrics[card.id], previousMetrics[card.id]) != null && rate(metrics[card.id], previousMetrics[card.id])! < 0 ? 'down' : 'up'}>{deltaText(card.id, metrics[card.id], previousMetrics[card.id])}</b></span><span>同比 <b className={rate(metrics[card.id], yearAgoMetrics[card.id]) != null && rate(metrics[card.id], yearAgoMetrics[card.id])! < 0 ? 'down' : 'up'}>{deltaText(card.id, metrics[card.id], yearAgoMetrics[card.id])}</b></span></footer></article>)}</section>
        <section className="chat-insight-grid">
          <article><header><h3>近期充电收入趋势（元）</h3><span>按月⌄</span></header><ChatTrend points={trend} /></article>
          <article><header><h3>主要影响对象</h3><span>变化贡献（元）</span></header><div className="chat-impact-list">{stationImpacts.slice(0, 5).map((item: any) => <div key={item.station_id}><span>{item.station_name}</span><em className={item.contribution < 0 ? 'down' : 'up'}>{item.contribution < 0 ? '下降' : '上升'}</em><b className={item.contribution < 0 ? 'down' : 'up'}>{money(item.contribution)}</b></div>)}</div></article>
        </section>
        <section className="chat-action-grid">
          <article><header><h3>原因拆解（贡献度）</h3><span>ⓘ</span></header><div className="chat-driver-list">{bridge.slice(0, 5).map((item: any) => <div key={item.driver}><span>{chatDriverNames[item.driver] ?? item.driver}</span><b>{money(item.contribution)}</b><i><em className={item.contribution < 0 ? 'negative' : ''} style={{ width: `${Math.max(Math.abs(item.contribution) / maxBridge * 100, 5)}%` }} /></i></div>)}</div><small>对账残差：{money(diagnosis?.reconciliation?.residual)}</small></article>
          <article><header><h3>建议行动</h3></header><ul><li>复核充电量变化对应的时段与场站结构<b>高影响</b></li><li>复核度电收入变化与价格策略<b>高影响</b></li><li>关注贡献下降场站的运营条件<b>中影响</b></li><li>结合设备指标作同期关联排查<b>中影响</b></li></ul></article>
        </section>
        <footer className="chat-followups"><b>推荐追问</b>{['夜间电量下降的主要原因？', '低功率时段占比为何上升？', '快充占比下降的原因？'].map(item => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}</footer>
      </article>
    </main>

    <aside className="chat-evidence-panel">
      <header><h2>证据与数据来源</h2><span>×</span></header>
      <section><h3><i>①</i>数据来源</h3><p><b>平台数据库</b><em>simulated</em></p><small>固定 seed 新能源经营分析业务库</small></section>
      <section><h3><i>②</i>指标口径</h3><p>充电收入：完成订单的电费与服务费实收净额</p><p>毛利率：经营毛利 / 充电收入</p></section>
      <section><h3><i>③</i>查询条件</h3><ul><li>时间范围：2026-06-01 ~ 2026-06-30</li><li>区域：全部授权区域</li><li>业务类型：充电</li><li>站点类型：全部</li><li>设备类型：全部</li></ul></section>
      <section><h3><i>④</i>Query Plan 摘要</h3><p>{result?.query_plan ? `${result.query_plan.intent}；指标 ${result.query_plan.metrics.join('、')}；${result.query_plan.comparison?.type ?? '无'}比较。` : '等待结构化解析'}</p><details><summary>查看详情　›</summary><pre>{JSON.stringify(result?.query_plan, null, 2)}</pre></details></section>
      <section><h3><i>⑤</i>SQL 证据入口</h3><details><summary>查看受控 SQL　‹/›</summary><pre>{result?.evidence?.sql || '当前结果未执行 SQL，或当前角色无权查看。'}</pre></details></section>
      <section><h3><i>⑥</i>analysis_run_id</h3><code>{result?.evidence?.analysis_run_id ?? '等待生成'}</code></section>
      <footer><span>♢</span><p><b>业务默认，证据按需查看</b><small>Query Guard：{result?.evidence?.query_guard ?? 'pending'} · Answer Guard：{result?.evidence?.answer_guard?.status ?? 'pending'}</small></p></footer>
    </aside>
  </div>
}

function DiagnosticsPage({ token, start, end }: { token: string; start: string; end: string }) {
  const [data, setData] = useState<any>(null)
  const [anomaly, setAnomaly] = useState<any>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const query = `start=${start}&end_exclusive=${end}`
    Promise.all([
      api<any>(`/api/v1/diagnostics/decomposition?metric=gross_profit&comparison=mom&limit=5&${query}`, token),
      api<any>(`/api/v1/diagnostics/anomalies?metric=charging_revenue&${query}`, token),
    ]).then(([decomposition, anomalyResult]) => {
      setData(decomposition)
      setAnomaly(anomalyResult)
      setError('')
    }).catch(reason => setError(reason instanceof Error ? reason.message : '诊断加载失败'))
  }, [token, start, end])
  if (error) return <div className="notice error">{error}</div>
  if (!data) return <div className="notice">正在计算异常与贡献拆解…</div>
  const max = Math.max(...data.bridge.map((item: any) => Math.abs(item.contribution)), 1)
  return <div className="diagnostics-page">
    <article><h2>毛利变化桥接</h2><p>收入 − 电费成本 − 可变运营成本；结果描述相关与疑似影响，不构成因果结论。</p><div className="bridge">{data.bridge.map((item: any) => <div key={item.driver}><span>{item.driver}</span><i className={item.contribution < 0 ? 'negative' : ''} style={{ width: `${Math.abs(item.contribution) / max * 100}%` }} /><b>{formatMetric('gross_profit', item.contribution)}</b></div>)}</div></article>
    <article><h2>规则异常</h2><dl><div><dt>指标</dt><dd>充电收入</dd></div><div><dt>环比变化</dt><dd>{anomaly?.change_rate == null ? '数据不足' : formatMetric('gross_margin', anomaly.change_rate)}</dd></div><div><dt>规则状态</dt><dd>{anomaly?.triggered ? '已触发' : '未触发'}</dd></div></dl></article>
    <article className="wide"><h2>场站贡献定位</h2><table><thead><tr><th>场站</th><th>区域</th><th>当前</th><th>基期</th><th>贡献</th></tr></thead><tbody>{data.station_contributions.map((row: any) => <tr key={row.station_id}><td>{row.station_name}</td><td>{row.region_id}</td><td>{formatMetric('gross_profit', row.current)}</td><td>{formatMetric('gross_profit', row.previous)}</td><td>{formatMetric('gross_profit', row.contribution)}</td></tr>)}</tbody></table><div className="evidence"><b>模拟数据</b><span>来源：{data.metadata.source}</span><span>run：{data.metadata.analysis_run_id}</span><span>{data.metadata.causality_boundary}</span></div></article>
  </div>
}

function ReportTrend({ points }: { points: TrendPoint[] }) {
  const values = points.map(point => point.value ?? 0)
  const max = Math.max(...values, 1)
  const coords = values.map((value, index) => `${index / Math.max(values.length - 1, 1) * 100},${92 - value / max * 70}`).join(' ')
  return <div className="report-trend" aria-label="充电收入趋势">
    <div className="report-bars">{values.map((value, index) => <i key={index} style={{ height: `${Math.max(value / max * 100, 10)}%` }} />)}</div>
    <svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={coords} /></svg>
    <div className="report-trend-axis">{points.map(point => <span key={point.period}>{point.period.slice(5)}</span>)}</div>
  </div>
}

function ReportPage({ token, start, end, summary, stations, trend }: { token: string; start: string; end: string; summary: Summary | null; stations: StationRow[]; trend: TrendPoint[] }) {
  const [report, setReport] = useState<any>(null)
  const [reportType, setReportType] = useState<'weekly' | 'monthly'>('weekly')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [enabled, setEnabled] = useState({ summary: true, metric: true, trend: true, station: true, device: true, action: true })
  const metrics = report?.metrics ?? summary?.metrics ?? {}
  const metadata = report?.metadata ?? summary?.metadata
  const isReady = Boolean(report)
  const generate = async () => {
    setLoading(true)
    setError('')
    try {
      setReport(await api<any>(`/api/v1/reports/draft?report_type=${reportType}&start=${start}&end_exclusive=${end}`, token))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '报告生成失败')
    } finally {
      setLoading(false)
    }
  }
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
    ['charging_revenue', '收入（元）'], ['gross_profit', '毛利（元）'], ['gross_margin', '毛利率'], ['charging_volume_kwh', '充电电量（kWh）'], ['device_online_rate', '设备在线率'],
  ] as const
  const reportRows = ['新能源经营分析周报', '新能源经营分析日报', '场站运营分析月报', '设备健康分析月报', '收入与毛利分析月报']
  const diagnosticRows = report?.diagnostic?.station_contributions ?? []
  const actionRows = [
    '优先核查低毛利场站的费率、利用率与设备可用性。',
    '复核异常站点的运营数据与已发布指标口径。',
    '报告草稿仅供审核；结论须基于已验证结构化结果。',
  ]
  return <div className="report-workspace">
    <aside className="report-list-panel">
      <button className="report-create" onClick={() => void generate()}>＋ 新建报告</button>
      <label className="report-search">⌕<input aria-label="搜索报告名称" placeholder="搜索报告名称" /></label>
      <div className="report-tabs"><b>全部</b><span>我创建的</span><span>我订阅的</span></div>
      <header><h2>报告列表 <small>({reportRows.length})</small></h2><button aria-label="筛选报告">⌄</button></header>
      <div className="report-list-items">{reportRows.map((name, index) => <button className={index === 0 ? 'active' : ''} key={name}><i>{index === 0 ? '●' : '○'}</i><span>{name}<small>{index === 0 && isReady ? '已完成' : '可生成'}　{endInclusive(end).slice(5)}</small></span><b>⋮</b></button>)}</div>
      <section className="report-subscriptions"><h3>我的订阅 <small>(2)</small></h3><p>新能源经营分析周报<br /><span>每周一 · 08:30</span></p><p>场站运营分析月报<br /><span>每月 1 日 · 09:00</span></p><button>查看全部订阅　›</button></section>
    </aside>

    <section className="report-canvas">
      <header className="report-titlebar"><div><h2>{reportName}</h2><span>{start} ～ {endInclusive(end)}（{reportType === 'weekly' ? '周报' : '月报'}）</span><em>{isReady ? '已完成' : '待生成'}</em><p>模拟数据 · 来源：平台数据库 · run_id：{metadata?.analysis_run_id || '待生成报告'}</p></div><div><button className="report-primary" onClick={() => void generate()}>{loading ? '生成中…' : '生成报告'}</button><button disabled={!isReady} onClick={() => void download('markdown')}>导出 MD</button><button disabled={!isReady} onClick={() => void download('csv')}>导出 CSV</button></div></header>
      {error && <div className="notice error">{error}</div>}
      <section className="report-executive">
        <header><h3>一、管理摘要</h3><span>模拟数据 · {metadata?.batch_id || '数据加载中'}</span></header>
        <p>本期经营数据已按发布的指标语义层汇总。报告只呈现可审核的结构化结果；设备与经营指标仅作同期相关线索，不构成因果结论。</p>
        <div className="report-kpis">{primaryMetrics.map(([id, label]) => <article key={id}><span>{label}</span><strong>{formatMetric(id, metrics[id])}</strong><small>{isReady ? '已验证报告结果' : '已发布指标口径'}</small></article>)}</div>
      </section>
      <section className="report-analysis-grid">
        <article className="report-table-card"><header><h3>二、核心指标</h3><span>{isReady ? '报告结果' : '实时汇总'}</span></header><table><thead><tr><th>指标</th><th>本期值</th><th>口径</th></tr></thead><tbody>{primaryMetrics.map(([id, label]) => <tr key={id}><td>{label}</td><td>{formatMetric(id, metrics[id])}</td><td>v0.1.0</td></tr>)}</tbody></table></article>
        <article className="report-chart-card"><header><h3>三、收入趋势</h3><span>充电收入（元）</span></header>{trend.length ? <ReportTrend points={trend} /> : <div className="report-chart-empty">正在加载趋势数据…</div>}</article>
      </section>
      <section className="report-detail-grid">
        <article><header><h3>四、重点场站 TOP5（按毛利）</h3><span>模拟数据</span></header><table><thead><tr><th>排名</th><th>场站名称</th><th>毛利（元）</th></tr></thead><tbody>{stations.slice(0, 5).map((station, index) => <tr key={station.station_id}><td>{index + 1}</td><td>{station.station_name}</td><td>{formatMetric('gross_profit', station.metrics.gross_profit)}</td></tr>)}</tbody></table></article>
        <article><header><h3>五、贡献归因</h3><span>仅在生成后显示</span></header>{diagnosticRows.length ? <ul className="report-attribution">{diagnosticRows.slice(0, 4).map((item: any) => <li key={item.station_id}><span>{item.station_name}</span><b>{formatMetric('gross_profit', item.contribution)}</b></li>)}</ul> : <p className="report-pending">生成报告后展示已验证的场站贡献拆解。</p>}</article>
        <article><header><h3>六、设备状态</h3><span>模拟数据</span></header><div className="report-device"><div className="device-ring"><b>{formatMetric('device_online_rate', metrics.device_online_rate)}</b><span>在线率</span></div><p>故障率 <b>{formatMetric('device_fault_rate', metrics.device_fault_rate)}</b><br />场站利用率 <b>{formatMetric('station_utilization_rate', metrics.station_utilization_rate)}</b></p></div></article>
      </section>
      <section className="report-actions-card"><div><h3>七、建议行动</h3>{actionRows.map(item => <p key={item}>✓　{item}</p>)}</div><aside><span>责任部门</span><b>运营部 / 运维部 / 技术部</b><span>数据时间</span><b>{start} ～ {endInclusive(end)}</b></aside></section>
    </section>

    <aside className="report-settings"><header><h2>报告设置</h2><button onClick={() => setEnabled({ summary: true, metric: true, trend: true, station: true, device: true, action: true })}>恢复默认</button></header><section><h3>报告类型</h3><div className="report-type-buttons"><button className={reportType === 'weekly' ? 'active' : ''} onClick={() => setReportType('weekly')}>周报</button><button className={reportType === 'monthly' ? 'active' : ''} onClick={() => setReportType('monthly')}>月报</button></div></section><section><h3>时间范围</h3><p>{start}　～　{endInclusive(end)}</p></section><section><h3>区域范围</h3><p>全部区域　⌄</p></section><section className="report-switches"><h3>模块开关</h3>{([['summary', '管理摘要'], ['metric', '核心指标'], ['trend', '收入趋势'], ['station', '重点场站 TOP5'], ['device', '设备状态'], ['action', '建议行动']] as Array<[keyof typeof enabled, string]>).map(([key, label]) => <label key={key}><span>{label}</span><input type="checkbox" checked={enabled[key]} onChange={() => setEnabled(value => ({ ...value, [key]: !value[key] }))} /></label>)}</section><section className="report-note"><h3>说明备注（选填）</h3><textarea maxLength={200} placeholder="输入报告备注信息…" /><small>报告只生成草稿，不会自动发送或发布。</small></section></aside>
  </div>
}

function BoundaryPage({ active, summary }: { active: ViewId; summary: Summary | null }) {
  const messages: Record<string, string> = {
    alerts: '当前入口使用已实现的规则异常、同比环比与贡献拆解能力；完整预警工作流不属于本界面复刻范围。',
    reports: '当前 Alpha 只生成可审核报告草稿，不自动发送或发布。',
    mapping: '当前 Alpha 使用已验证的平台数据库与固定种子模拟数据，不接入未经授权的真实企业数据。',
    metrics: '当前已发布 15 项核心指标与 charging_ops 场景，组织规则发布仍需管理员或指标负责人审批。',
  }
  return <div className="boundary-page"><article><i>{active === 'reports' ? '报' : active === 'metrics' ? '指' : active === 'mapping' ? '数' : '警'}</i><h2>{titles[active]}</h2><p>{messages[active]}</p><div className="evidence"><b>模拟数据</b><span>批次：{summary?.metadata.batch_id || '加载中'}</span><span>来源：平台数据库</span><span>能力边界：如实展示</span></div></article></div>
}

function Sidebar({ active, navigate }: { active: ViewId; navigate: (id: ViewId) => void }) {
  return <aside className="product-sidebar"><div className="brand"><img src="/figma-assets/brand-mark.svg" alt="" /><strong>新能源经营分析智能平台</strong></div><nav>{groups.map(group => <section key={group.title}><h2>{group.title}</h2>{group.items.map(item => <button key={item.id} className={active === item.id ? 'active' : ''} onClick={() => navigate(item.id)}><i>{item.icon}</i><span>{item.label}</span></button>)}</section>)}</nav><button className="collapse"><i>≡</i><span>收起菜单</span><b>«</b></button></aside>
}

function ProductHeader({ active, start, end, setStart, setEnd, logout }: { active: ViewId; start: string; end: string; setStart: (v: string) => void; setEnd: (v: string) => void; logout: () => void }) {
  const showSearchAndDate = active === 'overview' || active === 'margin' || active === 'stations' || active === 'reports'
  const searchPlaceholder = active === 'stations' ? '搜索场站名称、区域、城市…' : '搜索场站、指标、报告、问题…'
  return <header className={`product-header${active === 'chat' ? ' chat-header' : ''}`}><div className="page-title"><h1>{titles[active]}</h1>{(active === 'overview' || active === 'margin') && <span>当前场景：<b>charging_ops</b>｜充电运营</span>}{active === 'dashboard' && <small>数据范围：{start} 至 {endInclusive(end)}　｜　模拟数据　｜　来源：平台数据库</small>}</div>{showSearchAndDate && <><label className="search"><i>⌕</i><input aria-label="全局搜索" placeholder={searchPlaceholder} />{active === 'overview' && <kbd>⌘ K</kbd>}</label><div className="date-range"><input aria-label="开始日期" type="date" value={start} onChange={e => setStart(e.target.value)} /><span>～</span><input aria-label="结束日期" type="date" value={endInclusive(end)} onChange={e => { const next = new Date(`${e.target.value}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1); setEnd(next.toISOString().slice(0, 10)) }} /></div></>}{active === 'chat' && <><button className="chat-model">分析模式　确定性链路⌄</button><div className="chat-period">2026-06-01　~　2026-06-30　▣</div></>}<button className="organization">{active === 'chat' ? '国内新能源集团' : '国际新能源集团'}　⌄</button><button className="bell" aria-label="通知">♧<b>12</b></button><button className="profile" onClick={logout}><span>张</span><div><b>张伟</b><small>运营分析师</small></div><i>⌄</i></button></header>
}

function ProductShell({ token, logout }: { token: string; logout: () => void }) {
  const [active, setActive] = useState<ViewId>('overview')
  const [summary, setSummary] = useState<Summary | null>(null)
  const [stations, setStations] = useState<StationRow[]>([])
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [start, setStart] = useState('2026-01-01')
  const [end, setEnd] = useState('2026-07-01')
  const [refreshKey, setRefreshKey] = useState(0)
  const primary = useMemo(() => active === 'stations' ? 'charging_revenue' : pageMetrics[active]?.[0] || 'charging_revenue', [active])
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    const query = `start=${start}&end_exclusive=${end}`
    Promise.all([
      api<Summary>(`/api/v1/dashboard/summary?${query}`, token),
      api<{ rows: StationRow[] }>(`/api/v1/dashboard/stations?${query}&limit=10&metrics=charging_revenue,gross_profit,gross_margin,charging_volume_kwh,station_utilization_rate,device_online_rate,device_fault_rate`, token),
      api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=${primary}&${query}`, token),
    ]).then(([summaryResult, stationResult, trendResult]) => {
      if (!cancelled) { setSummary(summaryResult); setStations(stationResult.rows); setTrend(trendResult.points) }
    }).catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : '加载失败') }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token, start, end, primary, refreshKey])
  let content: React.ReactNode
  if (active === 'overview') content = <Overview summary={summary} trend={trend} loading={loading} error={error} navigate={setActive} />
  else if (active === 'dashboard') content = <WorkbenchPage token={token} summary={summary} stations={stations} revenueTrend={trend} start={start} end={end} setStart={setStart} setEnd={setEnd} navigate={setActive} refreshKey={refreshKey} refresh={() => setRefreshKey(value => value + 1)} />
  else if (active === 'stations') content = <>{error && <div className="notice error">{error}</div>}<StationPage token={token} summary={summary} stations={stations} trend={trend} start={start} end={end} setStart={setStart} setEnd={setEnd} refresh={() => setRefreshKey(value => value + 1)} navigate={setActive} /></>
  else if (active === 'chat') content = <ChatPage token={token} />
  else if (active === 'alerts') content = <DiagnosticsPage token={token} start={start} end={end} />
  else if (active === 'reports') content = <ReportPage token={token} start={start} end={end} summary={summary} stations={stations} trend={trend} />
  else if (active === 'mapping' || active === 'metrics') content = <BoundaryPage active={active} summary={summary} />
  else content = <>{error && <div className="notice error">{error}</div>}<DetailPage active={active} summary={summary} stations={stations} trend={trend} /></>
  return <div className={`product-shell${active === 'stations' ? ' station-mode' : ''}`}><Sidebar active={active} navigate={setActive} /><div className="workspace"><ProductHeader active={active} start={start} end={end} setStart={setStart} setEnd={setEnd} logout={logout} /><main className={`product-main${active === 'stations' ? ' station-main' : ''}`}>{content}</main></div></div>
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
  return <main className="product-login"><form onSubmit={login}><div className="login-brand"><img src="/figma-assets/brand-mark.svg" alt="" /><span><strong>新能源经营分析智能平台</strong><small>AI 增强 BI · 产品级 Alpha</small></span></div><h1>欢迎登录</h1><p>统一指标、可信问数与经营洞察</p><div className="login-truth">固定种子模拟数据环境 · 不代表真实企业数据</div><label>账号<input name="username" defaultValue="analyst" autoComplete="username" /></label><label>密码<input name="password" type="password" defaultValue="AlphaAnalyst!2026" autoComplete="current-password" /></label><button disabled={loading}>{loading ? '正在安全登录…' : '安全登录'}</button>{error && <div className="login-error">{error}</div>}</form></main>
}

export function ProductApp() {
  const [token, setToken] = useState(localStorage.getItem('alpha_token') || '')
  return token ? <ProductShell token={token} logout={() => { localStorage.removeItem('alpha_token'); setToken('') }} /> : <Login loggedIn={setToken} />
}
