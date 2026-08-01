import { useEffect, useState } from 'react'
import './preproduction.css'

type Acceptance = {
  run_id: string
  category: string
  status: string
  evidence_hash: string
  finished_at: string
  metrics: Record<string, unknown>
}

type Snapshot = {
  environment: string
  data: { classification: string; period: { start: string; end_inclusive: string }; source: string; run_id_location: string }
  runtime: { release_version: string; migration_head: string; query_engine_mode: string; local_auth_enabled: boolean; production_release_authorized: boolean }
  oidc: { configured: boolean; status: string; provider?: string; issuer?: string; client_id?: string; pkce_method?: string; latency_ms?: number }
  secret_providers: Record<string, { configured: boolean; status: string }>
  credential_references: Array<{ credential_ref_id: string; reference_name: string; provider: string; purpose: string; version: number; status: string; value_returned: false }>
  data_sources: Array<{ source_id: string; display_name: string; scenario_id: string; lifecycle_status: string; version: number; connection_test_status: string; schema_discovery_status: string; profile_status: string; credential_value_returned: false }>
  external_alert: { enabled: boolean; status: string; circuit_state: string; deliveries: Record<string, number> }
  sqlbot_external_evaluation: { status: string; actual_external_requests: number; reason: string; query_engine_mode: string; engine_enabled: boolean; canary_eligible: boolean }
  acceptance: Acceptance[]
  release_candidate: null | { release_id: string; version: string; status: string; artifact_hash: string; environment: string }
  production_gates: Record<string, boolean>
  production_actions_enabled: false
  audit_event_count: number
  generated_at: string
}

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers || {}) },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const state = response.status === 403 ? 'Forbidden' : response.status === 401 ? 'Unauthorized' : 'Blocked'
    throw new Error(`${state}：${body?.detail?.message || body?.detail?.code || response.status}`)
  }
  return body as T
}

function State({ value }: { value: string }) {
  const tone = ['READY', 'PASS', 'ACTIVE', 'APPROVED'].includes(value) ? 'pass' : ['FAILED', 'UNAVAILABLE', 'DENIED'].includes(value) ? 'fail' : 'conditional'
  return <span className={`p4-state ${tone}`}>{value}</span>
}

export function PreproductionPage({ token }: { token: string }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true); setError('')
    try { setSnapshot(await request<Snapshot>('/api/v1/preproduction/snapshot', token)) }
    catch (reason) { setSnapshot(null); setError(reason instanceof Error ? reason.message : '预生产状态读取失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [token])
  if (loading && !snapshot) return <div className="p4-empty">正在从预生产 API 核验运行状态…</div>
  if (error) return <div className="p4-empty denied"><b>预生产控制台不可用</b><span>{error}</span><button onClick={() => void load()}>重新加载</button></div>
  if (!snapshot) return null

  const secretProvider = Object.entries(snapshot.secret_providers).find(([code]) => code === 'VAULT_KV_V2')
  const accepted = new Map(snapshot.acceptance.map(item => [item.category, item]))
  const evidence = (category: string) => accepted.get(category)
  return <div className="p4-page" data-testid="preproduction-page">
    <section className="p4-hero"><div><span>P4 · PREPRODUCTION · RELEASE CANDIDATE</span><h2>预生产集成与发布候选验收</h2><p>代码完成、预生产验收、RC 与正式生产授权分别呈现；当前数据仅为固定种子模拟数据。</p></div><div><b>{snapshot.runtime.release_version}</b><small>migration {snapshot.runtime.migration_head}</small><State value={snapshot.environment.toUpperCase()} /></div></section>

    <section className="p4-kpis">
      <article><span>OIDC Provider</span><b>{snapshot.oidc.provider || '未配置'}</b><State value={snapshot.oidc.status} /></article>
      <article><span>Secret Provider</span><b>{secretProvider?.[0] || '未配置'}</b><State value={secretProvider?.[1].status || 'CONDITIONAL'} /></article>
      <article><span>受控数据源</span><b>{snapshot.data_sources.length}</b><small>跨租户访问由服务端拒绝</small></article>
      <article><span>SQLBot 外部请求</span><b>{snapshot.sqlbot_external_evaluation.actual_external_requests}</b><State value={snapshot.sqlbot_external_evaluation.status} /></article>
      <article><span>生产发布授权</span><b>{String(snapshot.runtime.production_release_authorized)}</b><State value={snapshot.runtime.production_release_authorized ? 'APPROVED' : 'DENIED'} /></article>
    </section>

    <section className="p4-grid">
      <article className="p4-panel"><header><div><h3>OIDC 身份与协议闭环</h3><p>Authorization Code + PKCE，服务端校验 state、nonce、issuer、audience 与 JWKS。</p></div><State value={snapshot.oidc.status} /></header><dl><div><dt>Issuer</dt><dd>{snapshot.oidc.issuer || '-'}</dd></div><div><dt>Client</dt><dd>{snapshot.oidc.client_id || '-'}</dd></div><div><dt>PKCE</dt><dd>{snapshot.oidc.pkce_method || '-'}</dd></div><div><dt>Discovery latency</dt><dd>{snapshot.oidc.latency_ms ?? '-'} ms</dd></div></dl></article>
      <article className="p4-panel"><header><div><h3>Vault 与 CredentialReference</h3><p>只展示引用元数据；Secret 值不入数据库、不返回前端。</p></div><State value={secretProvider?.[1].status || 'CONDITIONAL'} /></header><div className="p4-list">{snapshot.credential_references.map(item => <div key={item.credential_ref_id}><span><b>{item.reference_name}</b><small>{item.provider} · v{item.version} · {item.purpose}</small></span><State value={item.status} /></div>)}</div><footer>Secret values returned: <b>{String(snapshot.credential_references.some(item => item.value_returned))}</b></footer></article>

      <article className="p4-panel wide"><header><div><h3>数据源接入审批生命周期</h3><p>创建 → 凭据引用 → 连通性 → Schema → 画像 → 审核 → 发布 → 激活；仅允许只读正式 Source Binding。</p></div><span>{snapshot.data_sources.length} 个版本</span></header><table><thead><tr><th>数据源</th><th>场景</th><th>版本</th><th>连通</th><th>Schema</th><th>画像</th><th>生命周期</th><th>Secret 暴露</th></tr></thead><tbody>{snapshot.data_sources.map(item => <tr key={item.source_id}><td><b>{item.display_name}</b><small>{item.source_id}</small></td><td>{item.scenario_id}</td><td>v{item.version}</td><td><State value={item.connection_test_status} /></td><td><State value={item.schema_discovery_status} /></td><td><State value={item.profile_status} /></td><td><State value={item.lifecycle_status} /></td><td>{String(item.credential_value_returned)}</td></tr>)}</tbody></table></article>

      <article className="p4-panel"><header><div><h3>SQLBot 安全外部复评</h3><p>无经授权外部模型 CredentialReference 时，在网络请求前退出。</p></div><State value={snapshot.sqlbot_external_evaluation.status} /></header><dl><div><dt>实际外部请求</dt><dd>{snapshot.sqlbot_external_evaluation.actual_external_requests}</dd></div><div><dt>Query Engine</dt><dd>{snapshot.sqlbot_external_evaluation.query_engine_mode}</dd></div><div><dt>正式引擎</dt><dd>{String(snapshot.sqlbot_external_evaluation.engine_enabled)}</dd></div><div><dt>Canary 资格</dt><dd>{String(snapshot.sqlbot_external_evaluation.canary_eligible)}</dd></div></dl><p className="p4-note">{snapshot.sqlbot_external_evaluation.reason}</p><button disabled>SQLBot Canary 禁用</button></article>
      <article className="p4-panel"><header><div><h3>外部告警测试适配器</h3><p>仅本地签名 Webhook；默认禁用设计，预生产显式启用。</p></div><State value={snapshot.external_alert.status} /></header><dl><div><dt>启用</dt><dd>{String(snapshot.external_alert.enabled)}</dd></div><div><dt>熔断器</dt><dd>{snapshot.external_alert.circuit_state}</dd></div><div><dt>投递状态</dt><dd>{Object.entries(snapshot.external_alert.deliveries).map(([key, value]) => `${key}:${value}`).join(' · ') || '无投递'}</dd></div></dl></article>

      <article className="p4-panel wide"><header><div><h3>容量、灾备与安全验收证据</h3><p>每条记录来自落库的可复现验收输出，不把未执行项展示为 PASS。</p></div><span>{snapshot.acceptance.length} 类</span></header><div className="p4-acceptance">{['OIDC_INTEGRATION', 'SECRET_PROVIDER', 'DATASOURCE_GOVERNANCE', 'CAPACITY_SOAK', 'FAILURE_RECOVERY', 'BACKUP_RESTORE', 'SECURITY_NEGATIVE', 'FRONTEND_E2E'].map(category => { const item = evidence(category); return <div key={category}><span><b>{category}</b><small>{item ? `${item.run_id} · ${item.finished_at}` : '尚无已执行证据'}</small></span><State value={item?.status || 'CONDITIONAL'} /></div> })}</div></article>

      <article className="p4-panel"><header><div><h3>Release Candidate</h3><p>RC 不等于正式生产发布。</p></div><State value={snapshot.release_candidate?.status || 'CONDITIONAL'} /></header>{snapshot.release_candidate ? <dl><div><dt>版本</dt><dd>{snapshot.release_candidate.version}</dd></div><div><dt>环境</dt><dd>{snapshot.release_candidate.environment}</dd></div><div><dt>Artifact</dt><dd>{snapshot.release_candidate.artifact_hash.slice(0, 16)}…</dd></div></dl> : <p className="p4-note">尚未形成通过验收的唯一 RC。</p>}</article>
      <article className="p4-panel"><header><div><h3>生产发布门禁</h3><p>外部企业系统和变更授权未关闭前，生产动作保持禁用。</p></div><State value="DENIED" /></header><div className="p4-list">{Object.entries(snapshot.production_gates).map(([gate, passed]) => <div key={gate}><span><b>{gate}</b></span><State value={passed ? 'PASS' : 'CONDITIONAL'} /></div>)}</div><footer><button disabled>正式生产发布已禁用</button><button disabled>生产切流已禁用</button></footer></article>
    </section>
    <footer className="p4-truth"><b>模拟数据</b><span>{snapshot.data.period.start} 至 {snapshot.data.period.end_inclusive}</span><span>{snapshot.data.source}</span><span>run_id：{snapshot.data.run_id_location}</span><button onClick={() => void load()}>刷新正式 API 状态</button></footer>
  </div>
}
