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

function ReportPage({ token, start, end }: { token: string; start: string; end: string }) {
  const [report, setReport] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const generate = async () => {
    setLoading(true)
    setError('')
    try {
      setReport(await api<any>(`/api/v1/reports/draft?report_type=monthly&start=${start}&end_exclusive=${end}`, token))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '报告生成失败')
    } finally {
      setLoading(false)
    }
  }
  const download = async (format: 'markdown' | 'csv') => {
    const response = await fetch(`/api/v1/reports/export?report_type=monthly&format=${format}&start=${start}&end_exclusive=${end}`, { headers: { Authorization: `Bearer ${token}` } })
    if (!response.ok) return setError('导出失败')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `新能源经营分析月报草稿.${format === 'csv' ? 'csv' : 'md'}`
    anchor.click()
    URL.revokeObjectURL(url)
  }
  return <div className="report-page"><article><header><div><h2>周报 / 月报草稿</h2><p>只引用验证后的结构化结果，导出时重新鉴权</p></div><button onClick={() => void generate()}>{loading ? '生成中…' : '生成月报草稿'}</button></header>{error && <div className="notice error">{error}</div>}{!report && !loading && <div className="report-empty">选择数据期后生成可审核草稿；不会自动发送或发布。</div>}{report && <><div className="evidence"><b>模拟数据</b><span>来源：{report.metadata.source}</span><span>批次：{report.metadata.batch_id}</span><span>run：{report.metadata.analysis_run_id}</span><span>状态：草稿</span></div><div className="report-actions"><button onClick={() => void download('markdown')}>导出 Markdown</button><button onClick={() => void download('csv')}>导出 CSV</button></div><pre>{report.markdown}</pre></>}</article></div>
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
  return <header className={`product-header${active === 'chat' ? ' chat-header' : ''}`}><div className="page-title"><h1>{titles[active]}</h1>{active === 'overview' && <span>当前场景：<b>charging_ops</b>｜充电运营</span>}{active === 'dashboard' && <small>数据范围：{start} 至 {endInclusive(end)}　｜　模拟数据　｜　来源：平台数据库</small>}</div>{active === 'overview' && <><label className="search"><i>⌕</i><input aria-label="全局搜索" placeholder="搜索场站、指标、报告、问题…" /><kbd>⌘ K</kbd></label><div className="date-range"><input aria-label="开始日期" type="date" value={start} onChange={e => setStart(e.target.value)} /><span>→</span><input aria-label="结束日期" type="date" value={endInclusive(end)} onChange={e => { const next = new Date(`${e.target.value}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1); setEnd(next.toISOString().slice(0, 10)) }} /></div></>}{active === 'chat' && <><button className="chat-model">分析模式　确定性链路⌄</button><div className="chat-period">2026-06-01　~　2026-06-30　▣</div></>}<button className="organization">{active === 'chat' ? '国内新能源集团' : '国际新能源集团'}　⌄</button><button className="bell" aria-label="通知">♧<b>!</b></button><button className="profile" onClick={logout}><span>张</span><div><b>张伟</b><small>运营分析师</small></div><i>⌄</i></button></header>
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
  const primary = useMemo(() => pageMetrics[active]?.[0] || 'charging_revenue', [active])
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
  else if (active === 'chat') content = <ChatPage token={token} />
  else if (active === 'alerts') content = <DiagnosticsPage token={token} start={start} end={end} />
  else if (active === 'reports') content = <ReportPage token={token} start={start} end={end} />
  else if (active === 'mapping' || active === 'metrics') content = <BoundaryPage active={active} summary={summary} />
  else content = <>{error && <div className="notice error">{error}</div>}<DetailPage active={active} summary={summary} stations={stations} trend={trend} /></>
  return <div className="product-shell"><Sidebar active={active} navigate={setActive} /><div className="workspace"><ProductHeader active={active} start={start} end={end} setStart={setStart} setEnd={setEnd} logout={logout} /><main className="product-main">{content}</main></div></div>
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
