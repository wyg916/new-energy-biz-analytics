import React, { useEffect, useMemo, useState } from 'react'
import './metrics.css'

type Metadata = {
  data_classification: string
  data_time_range: { start: string; end_exclusive: string }
  source: string
  batch_id: string | null
  analysis_run_id: string
}

type MetricRow = {
  metric_id: string
  display_name: string
  unit: string
  version: string
  status: string
  formula: string
  allowed_dimensions: string[]
  business_domain: string
  definition: string
  source_tables: string[]
  supported_grains: string[]
  metric_type: string
}

type Catalog = {
  rows: MetricRow[]
  dimension_labels: Record<string, string>
  scenario: { scenario_id: string; display_name: string; status: string }
  metadata: Metadata
}

type SummaryLike = { metadata: Metadata } | null

const accentOrder = ['blue', 'teal', 'purple', 'orange']

function statusLabel(status: string) {
  return status === 'approved_for_implementation' ? '已发布' : status
}

function metricTypeLabel(metricType: string) {
  if (metricType === 'calculated') return '计算'
  if (metricType === 'ratio') return '比例'
  if (metricType === 'distinct_count') return '去重计数'
  return '聚合'
}

export function MetricsPage({
  token,
  summary,
  start,
  end,
}: {
  token: string
  summary: SummaryLike
  start: string
  end: string
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('全部指标')
  const [selectedId, setSelectedId] = useState('charging_revenue')
  const [feedback, setFeedback] = useState('')

  useEffect(() => {
    let cancelled = false
    const query = `start=${start}&end_exclusive=${end}`
    fetch(`/api/v1/dashboard/metric-catalog?${query}`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(async response => {
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail?.message || '指标目录加载失败')
      }
      return response.json() as Promise<Catalog>
    }).then(result => {
      if (!cancelled) {
        setCatalog(result)
        setError('')
        if (!result.rows.some(row => row.metric_id === selectedId)) {
          setSelectedId(result.rows[0]?.metric_id || '')
        }
      }
    }).catch(reason => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : '指标目录加载失败')
    })
    return () => { cancelled = true }
  }, [token, start, end])

  const rows = catalog?.rows || []
  const categoryOrder = useMemo(
    () => ['全部指标', ...Array.from(new Set(rows.map(row => row.business_domain)))],
    [rows],
  )
  const categoryCounts = useMemo(() => Object.fromEntries(categoryOrder.map(name => [
    name,
    name === '全部指标' ? rows.length : rows.filter(row => row.business_domain === name).length,
  ])), [rows])
  const visibleRows = useMemo(() => rows.filter(row => {
    const matchesCategory = category === '全部指标' || row.business_domain === category
    const term = search.trim().toLowerCase()
    const matchesSearch = !term || row.display_name.toLowerCase().includes(term) || row.metric_id.toLowerCase().includes(term)
    return matchesCategory && matchesSearch
  }), [rows, category, search])
  const pageRows = visibleRows.slice(0, 8)
  const selected = rows.find(row => row.metric_id === selectedId) || visibleRows[0] || rows[0]
  const selectedDomain = selected?.business_domain || '经营分析'
  const derivedCount = rows.filter(row => row.metric_type === 'calculated').length
  const ratioCount = rows.filter(row => row.unit === '%').length

  const act = (message: string) => {
    setFeedback(message)
    window.setTimeout(() => setFeedback(''), 2400)
  }

  return <div className="metrics-page">
    {error && <div className="metrics-alert">{error}</div>}
    {feedback && <div className="metrics-toast">{feedback}</div>}

    <section className="metrics-summary" aria-label="指标目录概览">
      {[
        { label: '指标总数', value: rows.length, suffix: '项', note: 'P0 冻结核心指标', icon: '◇' },
        { label: '业务场景', value: catalog ? 1 : 0, suffix: '个', note: catalog?.scenario.display_name || '加载中', icon: '▦' },
        { label: '允许维度', value: selected?.allowed_dimensions.length || 0, suffix: '个', note: '当前选中指标', icon: '▤' },
        { label: '目录版本', value: selected?.version || '--', suffix: '', note: '当前已发布版本', icon: '↻' },
      ].map((card, index) => <article key={card.label} className={`metric-summary-card ${accentOrder[index]}`}>
        <i>{card.icon}</i>
        <div><span>{card.label}</span><strong>{typeof card.value === 'number' ? card.value.toLocaleString('zh-CN') : card.value} <small>{card.suffix}</small></strong><p>{card.note}</p></div>
      </article>)}
    </section>

    <nav className="metrics-tabs" aria-label="管理模块">
      {['指标管理', '业务场景', '数据视图', '权限规则'].map((tab, index) =>
        <button key={tab} className={index === 0 ? 'active' : ''} onClick={() => index === 0 ? undefined : act(`${tab}沿用已批准产品边界，本次仅复刻指标管理主页`)}>{tab}</button>
      )}
    </nav>

    <section className="metrics-workspace">
      <aside className="metric-catalog-panel">
        <div className="metric-catalog-main">
          <h2>指标目录</h2>
          <label className="metric-catalog-search"><span>⌕</span><input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索指标名称/编码" /></label>
          <div className="metric-category-list">
            {categoryOrder.map((name, index) => <button key={name} className={category === name ? 'active' : ''} onClick={() => setCategory(name)}>
              <span><i>{category === name ? '▣' : '□'}</i>{name}</span><b>{categoryCounts[name]}</b><em>{index === 0 ? '' : '›'}</em>
            </button>)}
          </div>
        </div>
        <div className="metric-tag-panel">
          <h3>指标标签</h3>
          <span className="blue">◉ 核心指标 <b>{rows.length}</b></span>
          <span className="teal">◉ 衍生指标 <b>{derivedCount}</b></span>
          <span className="orange">♧ 比例指标 <b>{ratioCount}</b></span>
          <span className="purple">◇ 场景可用 <b>{rows.length}</b></span>
        </div>
      </aside>

      <main className="metric-table-panel">
        <div className="metric-actions">
          <button className="primary" onClick={() => act('指标新增需管理员或指标负责人审批，当前页面保持只读')}>＋ 新建指标</button>
          <button onClick={() => act('批量导入未在 P0 开放')}>⇧ 批量导入</button>
          <button onClick={() => act('当前目录版本为 v0.1.0')}>↶ 版本记录</button>
          <button onClick={() => act('更多操作遵循已批准的指标管理合同')}>☷ 更多操作⌄</button>
        </div>
        <div className="metric-filters">
          <label>指标类型<select value={category} onChange={event => setCategory(event.target.value)}>{categoryOrder.map(item => <option key={item}>{item}</option>)}</select></label>
          <label>状态<select defaultValue="已发布"><option>已发布</option></select></label>
          <label>版本<select defaultValue="v0.1.0"><option>v0.1.0</option></select></label>
          <button onClick={() => { setCategory('全部指标'); setSearch('') }}>↻ 重置</button>
        </div>
        <div className="metric-list-title"><h2>指标列表 <small>（{visibleRows.length}）</small></h2><span>已发布语义层 · 只读</span></div>
        <div className="metric-table-wrap">
          <table>
            <thead><tr><th></th><th>指标名称</th><th>指标编码</th><th>所属业务域</th><th>统计粒度</th><th>口径类型</th><th>状态</th><th>版本</th><th>操作</th></tr></thead>
            <tbody>{pageRows.map(row => <tr key={row.metric_id} className={selected?.metric_id === row.metric_id ? 'selected' : ''} onClick={() => setSelectedId(row.metric_id)}>
              <td><span className="metric-radio">{selected?.metric_id === row.metric_id ? '●' : ''}</span></td>
              <td><b>{row.display_name}</b></td>
              <td><code>{row.metric_id}</code></td>
              <td>{row.business_domain}</td>
              <td>{row.supported_grains.join('/')}</td>
              <td>{metricTypeLabel(row.metric_type)}</td>
              <td><em className="published">{statusLabel(row.status)}</em></td>
              <td>{row.version}</td>
              <td><button aria-label={`查看${row.display_name}`} onClick={event => { event.stopPropagation(); setSelectedId(row.metric_id) }}>◎</button><button aria-label={`编辑${row.display_name}`} onClick={event => { event.stopPropagation(); act('指标变更需审批，当前目录保持只读') }}>⌁</button></td>
            </tr>)}</tbody>
          </table>
          {!visibleRows.length && <div className="metric-empty">未找到匹配指标，请调整搜索条件。</div>}
        </div>
        <div className="metric-pagination"><span>共 {visibleRows.length} 条</span><button disabled>当前结果</button><div><button disabled>‹</button><button disabled className="active">1</button><button disabled>›</button></div></div>
      </main>

      <aside className="metric-detail-column">
        <article className="metric-detail-card">
          <header><h2>指标详情</h2><span>只读</span></header>
          {selected && <>
            <div className="metric-detail-title"><div><strong>{selected.display_name}</strong><code>{selected.metric_id}</code></div><em>{statusLabel(selected.status)}</em></div>
            <section className="metric-basic-grid">
              <span>业务域<b>{selectedDomain}</b></span><span>单位<b>{selected.unit}</b></span>
              <span>统计粒度<b>{selected.supported_grains.join('/')}</b></span><span>版本<b>v{selected.version}</b></span>
            </section>
            <section><h3>指标口径</h3><p>{selected.definition}</p></section>
            <section><h3>计算公式</h3><code className="metric-formula">{selected.formula}</code></section>
            <section><h3>关联维度</h3><div className="metric-dimensions">{selected.allowed_dimensions.map(item => <span key={item}>{catalog?.dimension_labels[item] || item}</span>)}</div></section>
            <section><h3>关联业务场景</h3><div className="metric-scenes"><span>● 经营工作台</span><span>● {selectedDomain}</span><span>● AI经营分析</span></div></section>
          </>}
        </article>
        <article className="metric-preview-card">
          <header><h2>场景应用预览</h2><button onClick={() => act('当前预览来自 charging_ops 已批准场景')}>查看全部 ›</button></header>
          <div>
            <section><b>经营工作台</b><small>核心指标卡片</small><strong>{selected?.display_name || '指标'}</strong><span>已发布口径</span></section>
            <section><b>{selectedDomain}</b><small>趋势与拆解</small><div className="preview-bars"><i /><i /><i /><i /></div><span>确定性查询</span></section>
            <section><b>经营报告</b><small>报告草稿引用</small><strong>v{selected?.version || '0.1.0'}</strong><span>可审核草稿</span></section>
          </div>
        </article>
      </aside>
    </section>
  </div>
}
