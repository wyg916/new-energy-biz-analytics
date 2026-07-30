import React, { useEffect, useMemo, useState } from 'react'
import './revenue.css'

type Metadata = {
  data_time_range: { start: string; end_exclusive: string }
  source: string
  analysis_run_id: string
}
type Summary = { metrics: Record<string, number | null>; metadata: Metadata }
type TrendPoint = { period: string; value: number | null }
type StationRow = {
  station_id: string
  station_name: string
  region_id: string
  city_id: string
  metrics: Record<string, number | null>
}
type RevenueAnalysis = {
  daily_trend: TrendPoint[]
  heatmap: Array<{ weekday: number; hour: number; value: number }>
  regions: Array<{ region_id: string; region_name: string; value: number }>
  cities: Array<{ city_id: string; city_name: string; region_id: string; value: number }>
  metadata: Metadata
}

type RevenuePageProps = {
  token: string
  summary: Summary | null
  stations: StationRow[]
  start: string
  end: string
  setStart: (value: string) => void
  setEnd: (value: string) => void
  refresh: () => void
}

async function request<T>(path: string, token: string): Promise<T> {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` } })
  if (!response.ok) throw new Error(`收入分析加载失败（${response.status}）`)
  return response.json()
}

function endInclusive(value: string) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - 1)
  return date.toISOString().slice(0, 10)
}

function previousRange(start: string, end: string) {
  const startDate = new Date(`${start}T00:00:00Z`)
  const endDate = new Date(`${end}T00:00:00Z`)
  const duration = endDate.getTime() - startDate.getTime()
  const previousEnd = new Date(startDate.getTime())
  const previousStart = new Date(startDate.getTime() - duration)
  return { start: previousStart.toISOString().slice(0, 10), end: previousEnd.toISOString().slice(0, 10) }
}

function value(value: number | null | undefined) {
  return value ?? 0
}

function compactNumber(input: number, digits = 2) {
  if (Math.abs(input) >= 100000000) return `${(input / 100000000).toFixed(digits)}亿`
  if (Math.abs(input) >= 10000) return `${(input / 10000).toFixed(digits)}万`
  return input.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

function fullNumber(input: number, digits = 2) {
  return input.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function changeRate(current: number, previous: number) {
  return previous === 0 ? null : (current - previous) / Math.abs(previous)
}

function Change({ current, previous, suffix = '%' }: { current: number; previous: number; suffix?: string }) {
  const rate = changeRate(current, previous)
  if (rate == null) return <span className="neutral">对比期无基数</span>
  const positive = rate >= 0
  return <span className={positive ? 'up' : 'down'}>较对比期 {positive ? '▲' : '▼'} {(Math.abs(rate) * 100).toFixed(2)}{suffix}</span>
}

function TrendChart({ current, previous }: { current: TrendPoint[]; previous: TrendPoint[] }) {
  const currentValues = current.map(point => value(point.value))
  const previousValues = previous.map(point => value(point.value))
  const allValues = [...currentValues, ...previousValues]
  if (!allValues.length) return <div className="revenue-empty">正在计算收入趋势…</div>
  const max = Math.max(...allValues, 1)
  const min = Math.min(...allValues)
  const spread = max - min || 1
  const coordinates = (values: number[]) => values.map((item, index) => {
    const x = 18 + index / Math.max(values.length - 1, 1) * 564
    const y = 156 - (item - min) / spread * 120
    return `${x},${y}`
  }).join(' ')
  const currentCoordinates = coordinates(currentValues)
  const previousCoordinates = coordinates(previousValues)
  const labels = current.length > 8
    ? current.filter((_, index) => index % Math.max(Math.floor(current.length / 6), 1) === 0)
    : current
  const average = currentValues.reduce((sum, item) => sum + item, 0) / Math.max(currentValues.length, 1)
  const averageY = 156 - (average - min) / spread * 120
  return <div className="revenue-trend-chart" role="img" aria-label="本期与对比期收入趋势">
    <svg viewBox="0 0 600 180" preserveAspectRatio="none">
      <defs><linearGradient id="revenueArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#10a780" stopOpacity=".22" /><stop offset="1" stopColor="#10a780" stopOpacity=".02" /></linearGradient></defs>
      <polygon points={`18,164 ${currentCoordinates} 582,164`} />
      <line className="average" x1="18" y1={averageY} x2="582" y2={averageY} />
      {previousCoordinates && <polyline className="previous" points={previousCoordinates} />}
      <polyline className="current" points={currentCoordinates} />
      {currentValues.map((item, index) => <circle key={current[index]?.period || index} cx={18 + index / Math.max(currentValues.length - 1, 1) * 564} cy={156 - (item - min) / spread * 120} r="2.3" />)}
    </svg>
    <div className="revenue-trend-axis">{labels.map(point => <span key={point.period}>{point.period.slice(5)}</span>)}</div>
  </div>
}

function DriverWaterfall({ previous, drivers, current }: {
  previous: number
  drivers: Array<{ label: string; value: number }>
  current: number
}) {
  const items = [{ label: '对比期收入', value: previous, total: true }, ...drivers.map(item => ({ ...item, total: false })), { label: '本期收入', value: current, total: true }]
  const max = Math.max(...items.map(item => Math.abs(item.value)), 1)
  return <div className="revenue-waterfall" role="img" aria-label="收入变化驱动桥接图">
    {items.map((item, index) => {
      const height = item.total ? 38 + Math.abs(item.value) / max * 35 : 10 + Math.abs(item.value) / max * 48
      return <div key={item.label}>
        <b className={item.total || item.value >= 0 ? 'up' : 'down'}>{item.total ? compactNumber(item.value) : `${item.value >= 0 ? '+' : ''}${compactNumber(item.value)}`}</b>
        <i className={`${item.total ? 'total ' : ''}${item.value >= 0 ? 'positive' : 'negative'}`} style={{ height: `${height}%` }} />
        <span>{item.label}</span>
        {index < items.length - 1 && <em />}
      </div>
    })}
  </div>
}

const weekdayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const palette = ['#eff9f6', '#ccefe6', '#89dac7', '#42bea3', '#099878']

export function RevenuePage({ token, summary, stations, start, end, setStart, setEnd, refresh }: RevenuePageProps) {
  const [analysis, setAnalysis] = useState<RevenueAnalysis | null>(null)
  const [previousAnalysis, setPreviousAnalysis] = useState<RevenueAnalysis | null>(null)
  const [previousSummary, setPreviousSummary] = useState<Summary | null>(null)
  const [stationRows, setStationRows] = useState<StationRow[]>(stations)
  const [previousStations, setPreviousStations] = useState<StationRow[]>([])
  const [error, setError] = useState('')
  const [comparisonMode, setComparisonMode] = useState<'period' | 'year'>('period')
  const [region, setRegion] = useState('全部区域')
  const comparison = useMemo(() => {
    if (comparisonMode === 'year') return { start: `${Number(start.slice(0, 4)) - 1}${start.slice(4)}`, end: `${Number(end.slice(0, 4)) - 1}${end.slice(4)}` }
    return previousRange(start, end)
  }, [start, end, comparisonMode])

  useEffect(() => setStationRows(stations), [stations])
  useEffect(() => {
    let cancelled = false
    setError('')
    const metrics = 'charging_revenue,service_fee_revenue,completed_order_count,charging_volume_kwh,revenue_per_kwh,station_utilization_rate'
    const currentQuery = `start=${start}&end_exclusive=${end}`
    const previousQuery = `start=${comparison.start}&end_exclusive=${comparison.end}`
    Promise.all([
      request<RevenueAnalysis>(`/api/v1/revenue/analysis?${currentQuery}`, token),
      request<RevenueAnalysis>(`/api/v1/revenue/analysis?${previousQuery}`, token),
      request<Summary>(`/api/v1/dashboard/summary?${previousQuery}`, token),
      request<{ rows: StationRow[] }>(`/api/v1/dashboard/stations?${currentQuery}&limit=30&metrics=${metrics}`, token),
      request<{ rows: StationRow[] }>(`/api/v1/dashboard/stations?${previousQuery}&limit=30&metrics=${metrics}`, token),
    ]).then(([currentResult, previousResult, summaryResult, stationsResult, previousStationsResult]) => {
      if (cancelled) return
      setAnalysis(currentResult)
      setPreviousAnalysis(previousResult)
      setPreviousSummary(summaryResult)
      setStationRows(stationsResult.rows)
      setPreviousStations(previousStationsResult.rows)
    }).catch(reason => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : '收入分析加载失败')
    })
    return () => { cancelled = true }
  }, [token, start, end, comparison.start, comparison.end])

  const currentMetrics = summary?.metrics ?? {}
  const previousMetrics = previousSummary?.metrics ?? {}
  const revenue = value(currentMetrics.charging_revenue)
  const previousRevenue = value(previousMetrics.charging_revenue)
  const orders = value(currentMetrics.completed_order_count)
  const previousOrders = value(previousMetrics.completed_order_count)
  const volume = value(currentMetrics.charging_volume_kwh)
  const previousVolume = value(previousMetrics.charging_volume_kwh)
  const averageVolume = orders ? volume / orders : 0
  const previousAverageVolume = previousOrders ? previousVolume / previousOrders : 0
  const revenuePerKwh = value(currentMetrics.revenue_per_kwh)
  const previousRevenuePerKwh = value(previousMetrics.revenue_per_kwh)
  const previousStationMap = useMemo(() => new Map(previousStations.map(row => [row.station_id, row])), [previousStations])
  const visibleStations = stationRows.filter(row => region === '全部区域' || row.region_id === region)
  const downStations = visibleStations.map(row => {
    const previous = previousStationMap.get(row.station_id)
    const currentValue = value(row.metrics.charging_revenue)
    const previousValue = value(previous?.metrics.charging_revenue)
    const delta = currentValue - previousValue
    const orderDelta = value(row.metrics.completed_order_count) - value(previous?.metrics.completed_order_count)
    return { row, currentValue, previousValue, delta, orderDelta, rate: changeRate(currentValue, previousValue) }
  }).sort((a, b) => a.delta - b.delta).slice(0, 5)
  const topRegions = analysis?.regions.slice(0, 4) ?? []
  const regionTotal = topRegions.reduce((sum, item) => sum + item.value, 0) || 1
  const regionColors = ['#0aa37c', '#1f84ef', '#f5a000', '#f05058']
  let regionCursor = 0
  const regionGradient = topRegions.length
    ? `conic-gradient(${topRegions.map((item, index) => {
      const startShare = regionCursor
      regionCursor += item.value / regionTotal * 100
      return `${regionColors[index]} ${startShare}% ${regionCursor}%`
    }).join(',')})`
    : '#eef2f6'
  const heatmapBuckets = useMemo(() => {
    const cells = Array.from({ length: 7 }, () => Array(12).fill(0) as number[])
    analysis?.heatmap.forEach(item => { cells[item.weekday - 1][Math.floor(item.hour / 2)] += item.value })
    return cells
  }, [analysis])
  const maxHeat = Math.max(...heatmapBuckets.flat(), 1)
  const revenueDelta = revenue - previousRevenue
  const orderImpact = previousAverageVolume * previousRevenuePerKwh * (orders - previousOrders)
  const volumeImpact = previousRevenuePerKwh * orders * (averageVolume - previousAverageVolume)
  const unitImpact = revenueDelta - orderImpact - volumeImpact
  const kpis = [
    { label: '充电收入', unit: '元', value: fullNumber(revenue), current: revenue, previous: previousRevenue, icon: '¥', tone: 'teal' },
    { label: '服务费收入', unit: '元', value: fullNumber(value(currentMetrics.service_fee_revenue)), current: value(currentMetrics.service_fee_revenue), previous: value(previousMetrics.service_fee_revenue), icon: '服', tone: 'blue' },
    { label: '完成订单', unit: '单', value: Math.round(orders).toLocaleString('zh-CN'), current: orders, previous: previousOrders, icon: '单', tone: 'orange' },
    { label: '充电量', unit: 'kWh', value: fullNumber(volume), current: volume, previous: previousVolume, icon: '电', tone: 'green' },
    { label: '度电收入', unit: '元/kWh', value: revenuePerKwh.toFixed(2), current: revenuePerKwh, previous: previousRevenuePerKwh, icon: '度', tone: 'violet' },
    { label: '单均充电量', unit: 'kWh/单', value: averageVolume.toFixed(2), current: averageVolume, previous: previousAverageVolume, icon: '均', tone: 'red' },
  ]
  const insights = [
    `本期收入 ${compactNumber(revenue)}，较对比期${revenueDelta >= 0 ? '增加' : '减少'} ${compactNumber(Math.abs(revenueDelta))}；订单量与单均充电量变化共同关联本期收入波动。`,
    downStations[0]
      ? `${downStations[0].row.station_name} 收入变化 ${compactNumber(downStations[0].delta)}，订单变化 ${downStations[0].orderDelta.toLocaleString('zh-CN')} 单，建议优先核验订单与设备运营记录。`
      : '当前筛选范围内暂无可对比的下滑场站。',
    `度电收入较对比期${revenuePerKwh >= previousRevenuePerKwh ? '上升' : '下降'} ${Math.abs(revenuePerKwh - previousRevenuePerKwh).toFixed(2)} 元/kWh；以上为结构化指标关联，不构成因果结论。`,
  ]

  return <div className="revenue-page">
    {error && <div className="revenue-error">{error}</div>}
    <section className="revenue-filter-bar">
      <label>时间范围<div className="revenue-period"><input type="date" aria-label="收入开始日期" value={start} onChange={event => setStart(event.target.value)} /><span>～</span><input type="date" aria-label="收入结束日期" value={endInclusive(end)} onChange={event => {
        const next = new Date(`${event.target.value}T00:00:00Z`)
        next.setUTCDate(next.getUTCDate() + 1)
        setEnd(next.toISOString().slice(0, 10))
      }} /></div></label>
      <label>对比时间<div className="revenue-period muted"><span>{comparison.start}</span><i>～</i><span>{endInclusive(comparison.end)}</span></div></label>
      <label>区域<select value={region} onChange={event => setRegion(event.target.value)}><option>全部区域</option>{[...new Set(stationRows.map(row => row.region_id))].map(item => <option key={item}>{item}</option>)}</select></label>
      <label>城市<select><option>全部城市</option></select></label>
      <label>场站<select><option>全部场站</option></select></label>
      <label>对比模式<select value={comparisonMode} onChange={event => setComparisonMode(event.target.value as 'period' | 'year')}><option value="period">上期对比</option><option value="year">同比对比</option></select></label>
      <label>指标粒度<select><option>按日</option></select></label>
      <button onClick={() => { setRegion('全部区域'); setComparisonMode('period') }}>重置</button>
      <button className="primary" onClick={refresh}>刷新</button>
    </section>

    <section className="revenue-kpis">
      {kpis.map(card => <article key={card.label}><i className={card.tone}>{card.icon}</i><div><span>{card.label}（{card.unit}）</span><p><strong>{card.value}</strong></p><Change current={card.current} previous={card.previous} /></div></article>)}
    </section>

    <section className="revenue-top-grid">
      <article className="revenue-panel revenue-trend-panel"><header><div><h2>收入趋势</h2><p>按日展示本期与对比期已完成订单收入</p></div><nav><span className="current">本期收入</span><span className="previous">对比期收入</span><span className="average">本期均值</span></nav></header><TrendChart current={analysis?.daily_trend ?? []} previous={previousAnalysis?.daily_trend ?? []} /></article>
      <article className="revenue-panel revenue-driver-panel"><header><div><h2>收入驱动拆解</h2><p>基于订单量、单均充电量及度电收入的恒等式桥接</p></div><button disabled>环比桥接</button></header>
        <div className="driver-cards">
          <div><span>收入变化额</span><b className={revenueDelta >= 0 ? 'up' : 'down'}>{revenueDelta >= 0 ? '+' : ''}{compactNumber(revenueDelta)}</b><small>{changeRate(revenue, previousRevenue) == null ? '--' : `${(changeRate(revenue, previousRevenue)! * 100).toFixed(2)}%`}</small></div>
          <div><span>订单量变化</span><b className={orders >= previousOrders ? 'up' : 'down'}>{orders - previousOrders >= 0 ? '+' : ''}{Math.round(orders - previousOrders).toLocaleString('zh-CN')}单</b><small>{changeRate(orders, previousOrders) == null ? '--' : `${(changeRate(orders, previousOrders)! * 100).toFixed(2)}%`}</small></div>
          <div><span>单均充电量</span><b className={averageVolume >= previousAverageVolume ? 'up' : 'down'}>{averageVolume - previousAverageVolume >= 0 ? '+' : ''}{(averageVolume - previousAverageVolume).toFixed(2)}kWh</b><small>{changeRate(averageVolume, previousAverageVolume) == null ? '--' : `${(changeRate(averageVolume, previousAverageVolume)! * 100).toFixed(2)}%`}</small></div>
          <div><span>度电收入变化</span><b className={revenuePerKwh >= previousRevenuePerKwh ? 'up' : 'down'}>{revenuePerKwh - previousRevenuePerKwh >= 0 ? '+' : ''}{(revenuePerKwh - previousRevenuePerKwh).toFixed(2)}元</b><small>{changeRate(revenuePerKwh, previousRevenuePerKwh) == null ? '--' : `${(changeRate(revenuePerKwh, previousRevenuePerKwh)! * 100).toFixed(2)}%`}</small></div>
        </div>
        <DriverWaterfall previous={previousRevenue} current={revenue} drivers={[{ label: '订单量', value: orderImpact }, { label: '单均电量', value: volumeImpact }, { label: '度电收入', value: unitImpact }]} />
      </article>
    </section>

    <section className="revenue-middle-grid">
      <article className="revenue-panel revenue-region-panel"><header><h2>区域收入贡献</h2><span>本期收入占比</span></header><div className="region-body"><div className="region-donut" style={{ background: regionGradient }}><span><small>收入合计</small><b>{compactNumber(regionTotal)}</b></span></div><ul>{topRegions.map((item, index) => <li key={item.region_id}><i style={{ background: regionColors[index] }} /><span>{item.region_name}</span><b>{(item.value / regionTotal * 100).toFixed(1)}%</b><em>{compactNumber(item.value)}</em></li>)}</ul></div></article>
      <article className="revenue-panel revenue-city-panel"><header><h2>城市收入排名 Top 10</h2><span>单位：元</span></header><ol>{(analysis?.cities ?? []).slice(0, 5).map((item, index) => <li key={item.city_id}><b>{index + 1}</b><span>{item.city_name}<small>{item.region_id}</small></span><i><em style={{ width: `${item.value / Math.max(analysis?.cities[0]?.value ?? 1, 1) * 100}%` }} /></i><strong>{compactNumber(item.value)}</strong></li>)}</ol></article>
      <article className="revenue-panel revenue-heatmap-panel"><header><div><h2>时段分析（收入热力图）</h2><p>按结算时间聚合，横轴为两小时区间</p></div><span>收入（元）</span></header><div className="revenue-heatmap"><div className="heat-hours">{Array.from({ length: 12 }, (_, index) => <span key={index}>{String(index * 2).padStart(2, '0')}</span>)}</div>{heatmapBuckets.map((row, rowIndex) => <div className="heat-row" key={weekdayNames[rowIndex]}><b>{weekdayNames[rowIndex]}</b>{row.map((item, index) => {
        const level = Math.min(Math.floor(item / maxHeat * 4), 4)
        return <i key={index} title={`${weekdayNames[rowIndex]} ${String(index * 2).padStart(2, '0')}:00-${String(index * 2 + 2).padStart(2, '0')}:00：${fullNumber(item)} 元`} style={{ background: palette[level] }} />
      })}</div>)}</div><footer><span>低</span>{palette.map(color => <i key={color} style={{ background: color }} />)}<span>高</span></footer></article>
    </section>

    <section className="revenue-bottom-grid">
      <article className="revenue-panel revenue-decline-panel"><header><div><h2>重点下滑场站</h2><p>按收入变化额升序，优先展示可比场站</p></div><button disabled>当前结果全部展示</button></header><div><table><thead><tr><th>场站名称</th><th>本期收入</th><th>对比期收入</th><th>变化额</th><th>变化率</th><th>订单变化</th><th>主要关联项</th></tr></thead><tbody>{downStations.map(item => <tr key={item.row.station_id}><td>{item.row.station_name}</td><td>{compactNumber(item.currentValue)}</td><td>{compactNumber(item.previousValue)}</td><td className={item.delta >= 0 ? 'up' : 'down'}>{item.delta >= 0 ? '+' : ''}{compactNumber(item.delta)}</td><td className={(item.rate ?? 0) >= 0 ? 'up' : 'down'}>{item.rate == null ? '--' : `${item.rate >= 0 ? '+' : ''}${(item.rate * 100).toFixed(1)}%`}</td><td className={item.orderDelta >= 0 ? 'up' : 'down'}>{item.orderDelta >= 0 ? '+' : ''}{Math.round(item.orderDelta)}</td><td>{item.orderDelta < 0 ? '订单量下降' : '度电结构变化'}</td></tr>)}</tbody></table></div></article>
      <article className="revenue-panel revenue-insight-panel"><header><div><h2>AI经营洞察</h2><p>仅引用本页结构化结果</p></div><span>确定性规则生成</span></header><ol>{insights.map((item, index) => <li key={item}><i>{index + 1}</i><p>{item}</p></li>)}</ol><button disabled>依据为本页结构化结果</button></article>
    </section>

    <footer className="revenue-truth"><b>模拟数据</b><span>数据时间：{summary?.metadata.data_time_range.start ?? start} 至 {endInclusive(summary?.metadata.data_time_range.end_exclusive ?? end)}</span><span>来源：平台数据库</span><span>run：{analysis?.metadata.analysis_run_id ?? summary?.metadata.analysis_run_id ?? '加载中'}</span></footer>
  </div>
}
