import { useEffect, useMemo, useState } from 'react'
import './production-acceptance.css'

type Evidence = {
  evidence_type: string
  uri: string
  sha256?: string | null
  observed_at: string
  summary: string
}

type Gate = {
  gate_id: string
  gate_code: string
  title: string
  category: string
  status: string
  recorded_status: string
  display_status: string
  owner: string
  blocker_level: string
  external_condition: boolean
  evidence: Evidence[]
  evidence_hash: string | null
  expires_at: string
  last_verified_at: string | null
  review_requirement: string
  waiver: null | { approved_by: string; basis: string; evidence_hash: string }
  version: number
}

type AcceptanceSnapshot = {
  environment: string
  data: { classification: string; period: { start: string; end_inclusive: string }; source: string; run_id_location: string }
  gates: Gate[]
  summary: {
    counts: Record<string, number>
    unresolved_blockers: string[]
    waived_gates: string[]
    production_acceptance_ready: boolean
    go_no_go_recommendation: string
    production_release_authorized: false
    production_traffic_switched: false
    sqlbot_canary_eligible: false
  }
  runtime_contract: {
    query_engine_mode: string
    sqlbot_engine_enabled: false
    sqlbot_canary_eligible: false
    rag_runtime_mode: string
    rag_vector_released: false
    production_release_authorized: false
    production_traffic_switched: false
  }
  generated_at: string
}

async function loadSnapshot(token: string): Promise<AcceptanceSnapshot> {
  const response = await fetch('/api/v1/production-acceptance/snapshot', {
    headers: { Authorization: `Bearer ${token}` },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail?.message || body?.detail?.code || `HTTP ${response.status}`)
  return body as AcceptanceSnapshot
}

function GateStatus({ value }: { value: string }) {
  const tone = ['PASSED'].includes(value) ? 'pass' : ['BLOCKED', 'EXPIRED'].includes(value) ? 'blocked' : value === 'WAIVED' ? 'waived' : 'open'
  return <span className={`p5-gate-status ${tone}`}>{value}</span>
}

const highlighted: Array<[string, string]> = [
  ['IMAGE_SECURITY', '镜像 CVE'],
  ['ENTERPRISE_IDP', '企业 IdP'],
  ['SECRET_MANAGER', 'Secret Manager'],
  ['SQLBOT_EXTERNAL_REVIEW', 'SQLBot 复评'],
  ['RAG_MODE', 'RAG 模式'],
  ['PRODUCTION_CAPACITY', '容量 / SLA'],
  ['MONITORING_ALERTING', '企业告警'],
  ['RISK_ACCEPTANCE', '风险接受'],
]

export function ProductionAcceptancePage({ token }: { token: string }) {
  const [snapshot, setSnapshot] = useState<AcceptanceSnapshot | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true); setError('')
    try { setSnapshot(await loadSnapshot(token)) }
    catch (reason) { setSnapshot(null); setError(reason instanceof Error ? reason.message : 'P5 验收状态读取失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [token])
  const byCode = useMemo(() => new Map(snapshot?.gates.map(gate => [gate.gate_code, gate]) || []), [snapshot])
  if (loading && !snapshot) return <div className="p5-empty">正在从 Production Gate Registry 读取落库状态…</div>
  if (error) return <div className="p5-empty blocked"><b>P5 生产验收 API 不可用</b><span>{error}</span><button onClick={() => void load()}>重新加载</button></div>
  if (!snapshot) return null

  return <div className="p5-page" data-testid="production-acceptance-page">
    <section className="p5-hero">
      <div><span>P5 · PRODUCTION ACCEPTANCE · GATED</span><h2>生产验收门禁与 Go/No-Go</h2><p>仅展示数据库中可审计的真实证据；没有证据的外部门禁保持 CONDITIONAL，不能由前端生成通过或豁免。</p></div>
      <div><GateStatus value={snapshot.summary.go_no_go_recommendation} /><b>{snapshot.summary.unresolved_blockers.length}</b><small>未关闭阻断门禁</small></div>
    </section>

    <section className="p5-highlight-grid">
      {highlighted.map(([code, label]) => { const gate = byCode.get(code); return <article key={code}><span>{label}</span><b>{gate?.title || code}</b><GateStatus value={gate?.display_status || 'OPEN'} /><small>{gate?.evidence.length || 0} 条证据 · {gate?.owner || '未分配'}</small></article> })}
    </section>

    <section className="p5-grid">
      <article className="p5-panel wide">
        <header><div><h3>Production Gate Registry</h3><p>状态集合固定为 OPEN / IN_PROGRESS / PASSED / WAIVED / BLOCKED / EXPIRED；所有结论由正式后端权限和审计控制。</p></div><span>{snapshot.gates.length} 个门禁</span></header>
        <div className="p5-table-wrap"><table><thead><tr><th>门禁</th><th>状态</th><th>Owner</th><th>阻断级别</th><th>证据</th><th>最后验证</th><th>过期 / 复核</th></tr></thead><tbody>{snapshot.gates.map(gate => <tr key={gate.gate_id}><td><b>{gate.title}</b><small>{gate.gate_code} · v{gate.version}</small></td><td><GateStatus value={gate.display_status} /></td><td>{gate.owner}</td><td>{gate.blocker_level}</td><td>{gate.evidence.length ? <details><summary>{gate.evidence.length} 条 · {gate.evidence_hash?.slice(0, 10)}…</summary>{gate.evidence.map(item => <small key={`${item.uri}-${item.observed_at}`}>{item.evidence_type} · {item.summary}</small>)}</details> : <span>尚无已验证证据</span>}</td><td>{gate.last_verified_at ? new Date(gate.last_verified_at).toLocaleString('zh-CN') : '未验证'}</td><td><small>{new Date(gate.expires_at).toLocaleString('zh-CN')}</small><span>{gate.review_requirement}</span></td></tr>)}</tbody></table></div>
      </article>

      <article className="p5-panel"><header><div><h3>运行合同</h3><p>候选资格与生产授权分离。</p></div><GateStatus value="BLOCKED" /></header><dl><div><dt>Query Engine</dt><dd>{snapshot.runtime_contract.query_engine_mode}</dd></div><div><dt>SQLBot Enabled</dt><dd>{String(snapshot.runtime_contract.sqlbot_engine_enabled)}</dd></div><div><dt>RAG</dt><dd>{snapshot.runtime_contract.rag_runtime_mode}</dd></div><div><dt>Vector Released</dt><dd>{String(snapshot.runtime_contract.rag_vector_released)}</dd></div></dl><footer><button disabled>SQLBot Canary 禁用</button></footer></article>
      <article className="p5-panel"><header><div><h3>最终 Go/No-Go</h3><p>阻断门禁全部 PASSED/WAIVED 后仍需另行授权。</p></div><GateStatus value={snapshot.summary.go_no_go_recommendation} /></header><dl><div><dt>Acceptance Ready</dt><dd>{String(snapshot.summary.production_acceptance_ready)}</dd></div><div><dt>Release Authorized</dt><dd>{String(snapshot.summary.production_release_authorized)}</dd></div><div><dt>Traffic Switched</dt><dd>{String(snapshot.summary.production_traffic_switched)}</dd></div><div><dt>WAIVED</dt><dd>{snapshot.summary.waived_gates.length}</dd></div></dl><footer><button disabled>正式生产发布已禁用</button><button disabled>生产切流已禁用</button></footer></article>

      <article className="p5-panel wide"><header><div><h3>未关闭阻断项</h3><p>不会使用历史缓存、Mock 或缺失的外部证据填充。</p></div><span>{snapshot.summary.unresolved_blockers.length}</span></header><div className="p5-blockers">{snapshot.summary.unresolved_blockers.map(code => { const gate = byCode.get(code); return <div key={code}><span><b>{gate?.title || code}</b><small>{gate?.review_requirement}</small></span><GateStatus value={gate?.display_status || 'OPEN'} /></div> })}</div></article>

      <article className="p5-panel wide"><header><div><h3>风险接受审计</h3><p>WAIVED 必须同时显示正式批准人、风险依据和证据哈希；当前不会自动生成签署记录。</p></div><span>{snapshot.summary.waived_gates.length} 项</span></header>{snapshot.summary.waived_gates.length ? snapshot.summary.waived_gates.map(code => { const gate = byCode.get(code); return <div className="p5-waiver" key={code}><b>{gate?.title}</b><span>{gate?.waiver?.approved_by}</span><small>{gate?.waiver?.basis} · {gate?.waiver?.evidence_hash}</small></div> }) : <div className="p5-empty">没有已获正式证据的风险接受项。</div>}</article>
    </section>

    <footer className="p5-truth"><b>模拟数据</b><span>{snapshot.data.period.start} 至 {snapshot.data.period.end_inclusive}</span><span>{snapshot.data.source}</span><span>run_id：{snapshot.data.run_id_location}</span><button onClick={() => void load()}>刷新正式 API 状态</button></footer>
  </div>
}
