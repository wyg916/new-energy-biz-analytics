import React, { useEffect, useMemo, useState } from 'react'
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

function MiniLine({ points, large = false }: { points: TrendPoint[]; large?: boolean }) {
  const values = points.map(item => item.value ?? 0)
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const width = large ? 760 : 190
  const height = large ? 170 : 56
  const coords = values.map((value, index) => `${index / Math.max(values.length - 1, 1) * width},${height - 7 - (value - min) / (max - min || 1) * (height - 18)}`).join(' ')
  return <svg className={large ? 'detail-line' : 'mini-line'} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="指标月度趋势"><polyline points={coords} /></svg>
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

function ChatPage({ token }: { token: string }) {
  const [question, setQuestion] = useState('区域A在所选周期的充电收入和毛利率是多少？')
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const ask = async (event: React.FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/v1/chat/query', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ question }) })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail?.message || '问数失败')
      setResult(body)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '问数失败')
    } finally {
      setLoading(false)
    }
  }
  return <div className="chat-page"><article><h2>可信 ChatBI</h2><p>自然语言 → Query Plan → 安全编译 → 只读执行 → Answer Guard</p><form onSubmit={ask}><textarea value={question} onChange={e => setQuestion(e.target.value)} /><button disabled={loading}>{loading ? '正在验证并计算…' : '开始分析'}</button></form>{error && <div className="notice error">{error}</div>}{result && <section><span>{result.status}</span><h3>回答</h3><p>{result.answer}</p><small>会话 {result.conversation_id} · 状态版本 {result.state_version}</small><details><summary>查看 Query Plan</summary><pre>{JSON.stringify(result.query_plan, null, 2)}</pre></details></section>}</article>{result && <aside><h2>证据面板</h2><dl><div><dt>数据分类</dt><dd>{result.evidence.data_classification}</dd></div><div><dt>来源</dt><dd>{result.evidence.source}</dd></div><div><dt>分析运行</dt><dd>{result.evidence.analysis_run_id}</dd></div><div><dt>Query Guard</dt><dd>{result.evidence.query_guard}</dd></div><div><dt>Answer Guard</dt><dd>{result.evidence.answer_guard?.status}</dd></div></dl></aside>}</div>
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
  return <header className="product-header"><div className="page-title"><h1>{titles[active]}</h1>{active === 'overview' && <span>当前场景：<b>charging_ops</b>｜充电运营</span>}</div><label className="search"><i>⌕</i><input aria-label="全局搜索" placeholder="搜索场站、指标、报告、问题…" /><kbd>⌘ K</kbd></label><button className="organization">国际新能源集团　⌄</button><div className="date-range"><input aria-label="开始日期" type="date" value={start} onChange={e => setStart(e.target.value)} /><span>→</span><input aria-label="结束日期" type="date" value={endInclusive(end)} onChange={e => { const next = new Date(`${e.target.value}T00:00:00Z`); next.setUTCDate(next.getUTCDate() + 1); setEnd(next.toISOString().slice(0, 10)) }} /></div><button className="bell" aria-label="通知">♧<b>!</b></button><button className="profile" onClick={logout}><span>张</span><div><b>张伟</b><small>运营分析师</small></div><i>⌄</i></button></header>
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
  const primary = useMemo(() => pageMetrics[active]?.[0] || 'charging_revenue', [active])
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    const query = `start=${start}&end_exclusive=${end}`
    Promise.all([
      api<Summary>(`/api/v1/dashboard/summary?${query}`, token),
      api<{ rows: StationRow[] }>(`/api/v1/dashboard/stations?${query}&limit=10`, token),
      api<{ points: TrendPoint[] }>(`/api/v1/dashboard/trend?metric=${primary}&${query}`, token),
    ]).then(([summaryResult, stationResult, trendResult]) => {
      if (!cancelled) { setSummary(summaryResult); setStations(stationResult.rows); setTrend(trendResult.points) }
    }).catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : '加载失败') }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token, start, end, primary])
  let content: React.ReactNode
  if (active === 'overview') content = <Overview summary={summary} trend={trend} loading={loading} error={error} navigate={setActive} />
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
