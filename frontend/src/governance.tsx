import { useEffect, useMemo, useState } from 'react'
import { PreproductionPage } from './preproduction'
import { ProductionAcceptancePage } from './production-acceptance'
import './governance.css'

type Snapshot = {
  identity: { principal_id: string; subject_id: string; tenant_id: string; workspace_id: string; roles: string[]; provider: string; auth_strength: string }
  principals: Array<{ principal_id: string; display_name: string; provider: string; type: string; status: string }>
  roles: Array<{ role_id: string; role_code: string; status: string }>
  policies: Array<{ policy_id: string; policy_code: string; version: number; status: string; effect: string; actions: string[]; approved_by: string | null }>
  credentials: Array<{ credential_ref_id: string; reference_name: string; provider: string; purpose: string; environment: string; status: string; version: number; allowed_actions: string[]; secret_value_exposed: false }>
  legal_holds: Array<{ legal_hold_id: string; resource_type: string; resource_id: string | null; status: string; reason_code: string }>
  retention_policies: Array<{ retention_policy_id: string; policy_code: string; resource_type: string; retention_days: number; archive_after_days: number | null; status: string }>
  alerts: Array<{ alert_id: string; rule_code: string; severity: string; status: string; event_count: number; summary: string; trace_id: string }>
  releases: Array<{ release_id: string; object_type: string; object_id: string; version: string; environment: string; status: string; approved_by: string | null; supersedes_release_id: string | null; rollback_of_release_id: string | null }>
  audit_events: Array<{ event_id: string; actor: string; action: string; resource_type: string; resource_id: string | null; result: string; trace_id: string }>
  runtime: { readiness_http_status: number; readiness: Record<string, unknown>; query_engine_mode: string; sqlbot_engine_enabled: boolean; sqlbot_canary_eligible: boolean; production_release_enabled: boolean }
}

type Tab = 'overview' | 'identity' | 'credentials' | 'retention' | 'audit' | 'release' | 'preproduction' | 'production'
const tabs: Array<[Tab, string]> = [['overview', '治理总览'], ['identity', '身份与授权'], ['credentials', '凭据引用'], ['retention', 'Legal Hold 与保留'], ['audit', '审计与告警'], ['release', '发布与运行'], ['preproduction', 'P4 预生产与 RC'], ['production', 'P5 生产验收']]

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers || {}) } })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const state = response.status === 401 ? 'Unauthorized' : response.status === 403 ? 'Forbidden' : '请求失败'
    throw new Error(`${state}：${body?.detail?.message || body?.detail?.code || response.status}`)
  }
  return body as T
}

function Status({ value }: { value: string }) {
  const tone = ['ACTIVE', 'APPROVED', 'SUCCESS', 'OPEN'].includes(value) ? 'ok' : ['DENIED', 'FAILED', 'BLOCKED', 'REVOKED'].includes(value) ? 'risk' : 'muted'
  return <span className={`gov-status ${tone}`}>{value}</span>
}
function Empty({ children }: { children: string }) { return <div className="gov-empty">{children}</div> }

export function GovernancePage({ token }: { token: string }) {
  const [tab, setTab] = useState<Tab>('overview')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [feedback, setFeedback] = useState('')
  const load = async () => {
    setLoading(true); setError('')
    try { setSnapshot(await request<Snapshot>('/api/v1/governance/snapshot', token)) }
    catch (reason) { setSnapshot(null); setError(reason instanceof Error ? reason.message : '治理数据加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [token])
  const action = async (path: string) => {
    setFeedback('')
    try { await request(path, token, { method: 'POST' }); setFeedback('操作已由服务端执行并写入治理审计。'); await load() }
    catch (reason) { setFeedback(reason instanceof Error ? reason.message : '操作失败') }
  }
  const openAlerts = useMemo(() => snapshot?.alerts.filter(item => item.status === 'OPEN').length || 0, [snapshot])
  if (loading && !snapshot) return <div className="gov-state">正在从治理 API 读取已落库状态…</div>
  if (error) return <div className="gov-state denied"><b>治理中心不可用</b><span>{error}</span><button onClick={() => void load()}>重新加载</button></div>
  if (!snapshot) return null

  return <div className="governance-page" data-testid="governance-page">
    <section className="gov-banner"><div><span>ENTERPRISE GOVERNANCE · P5</span><h2>企业治理与生产就绪控制台</h2><p>所有状态来自正式后端 API；权限判断、审批与审计均在服务端完成。</p></div><div className="gov-scope"><b>{snapshot.identity.tenant_id}</b><span>{snapshot.identity.workspace_id}</span><small>{snapshot.identity.provider} · {snapshot.identity.auth_strength}</small></div></section>
    <nav className="gov-tabs" aria-label="企业治理模块">{tabs.map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</nav>
    {feedback && <div className="gov-feedback">{feedback}</div>}

    {tab === 'overview' && <><section className="gov-kpis"><article><span>可信 Principal</span><b>{snapshot.principals.length}</b><small>服务端映射</small></article><article><span>ACTIVE Policy</span><b>{snapshot.policies.filter(item => item.status === 'ACTIVE').length}</b><small>未匹配默认拒绝</small></article><article><span>CredentialReference</span><b>{snapshot.credentials.length}</b><small>Secret 值暴露 0</small></article><article><span>OPEN 告警</span><b>{openAlerts}</b><small>仅站内告警</small></article><article><span>发布记录</span><b>{snapshot.releases.length}</b><small>保留历史版本</small></article></section><section className="gov-grid two"><article className="gov-panel"><header><h3>安全边界</h3><Status value="ACTIVE" /></header><dl><div><dt>Query Engine</dt><dd>{snapshot.runtime.query_engine_mode}</dd></div><div><dt>SQLBot 正式引擎</dt><dd>{String(snapshot.runtime.sqlbot_engine_enabled)}</dd></div><div><dt>Canary 资格</dt><dd>{String(snapshot.runtime.sqlbot_canary_eligible)}</dd></div><div><dt>生产发布</dt><dd>{String(snapshot.runtime.production_release_enabled)}</dd></div></dl></article><article className="gov-panel"><header><h3>当前可信身份</h3><Status value="ACTIVE" /></header><dl><div><dt>Principal</dt><dd>{snapshot.identity.principal_id}</dd></div><div><dt>Subject</dt><dd>{snapshot.identity.subject_id}</dd></div><div><dt>角色</dt><dd>{snapshot.identity.roles.join(', ')}</dd></div><div><dt>数据性质</dt><dd>模拟数据</dd></div></dl></article></section></>}

    {tab === 'identity' && <section className="gov-grid two"><article className="gov-panel"><header><h3>Principal / SSO 映射</h3><span>{snapshot.principals.length} 项</span></header>{snapshot.principals.map(item => <div className="gov-row" key={item.principal_id}><span><b>{item.display_name}</b><small>{item.principal_id} · {item.provider} · {item.type}</small></span><Status value={item.status} /></div>)}</article><article className="gov-panel"><header><h3>角色与权限基线</h3><span>{snapshot.roles.length} 个角色</span></header>{snapshot.roles.map(role => <div className="gov-row" key={role.role_id}><span><b>{role.role_code}</b><small>{role.role_id}</small></span><Status value={role.status} /></div>)}<p className="gov-note">模型输出与请求 Header 不参与最终授权；未匹配 Policy 时服务端默认拒绝。</p></article><article className="gov-panel wide"><header><h3>Policy Bundle</h3><span>{snapshot.policies.length} 个版本</span></header><table><thead><tr><th>Policy</th><th>版本</th><th>效果</th><th>权限</th><th>状态</th><th>审批人</th></tr></thead><tbody>{snapshot.policies.map(item => <tr key={item.policy_id}><td><b>{item.policy_code}</b><small>{item.policy_id}</small></td><td>v{item.version}</td><td>{item.effect}</td><td>{item.actions.join(', ')}</td><td><Status value={item.status} /></td><td>{item.approved_by || '未审批'}</td></tr>)}</tbody></table></article></section>}

    {tab === 'credentials' && <section className="gov-panel"><header><div><h3>CredentialReference</h3><p>只显示引用元数据、用途、作用域和状态；不会显示 Secret 值。</p></div><button disabled title="请通过受控管理 API 创建凭据引用">创建由管理 API 控制</button></header>{snapshot.credentials.length ? <table><thead><tr><th>引用</th><th>Provider / 环境</th><th>用途</th><th>允许动作</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>{snapshot.credentials.map(item => <tr key={item.credential_ref_id}><td><b>{item.reference_name}</b><small>{item.credential_ref_id}</small></td><td>{item.provider} / {item.environment}</td><td>{item.purpose}</td><td>{item.allowed_actions.join(', ')}</td><td>v{item.version}</td><td><Status value={item.status} /></td><td><button disabled={item.status !== 'ACTIVE'} onClick={() => void action(`/api/v1/governance/credentials/${item.credential_ref_id}/disable`)}>禁用</button></td></tr>)}</tbody></table> : <Empty>尚未创建 CredentialReference；SQLBot 外部复评保持 CONDITIONAL，并在外部请求前 fail-closed。</Empty>}<footer className="gov-boundary">Secret value exposed: <b>0</b> · 自动扫描 .env*: <b>禁止</b> · 缺失 Provider: <b>fail-closed</b></footer></section>}

    {tab === 'retention' && <section className="gov-grid two"><article className="gov-panel"><header><h3>Legal Hold</h3><span>{snapshot.legal_holds.length} 项</span></header>{snapshot.legal_holds.length ? snapshot.legal_holds.map(item => <div className="gov-row" key={item.legal_hold_id}><span><b>{item.reason_code}</b><small>{item.resource_type} · {item.resource_id || 'scope-wide'}</small></span><Status value={item.status} /></div>) : <Empty>当前无 Legal Hold</Empty>}<p className="gov-note">ACTIVE Hold 优先于删除、归档和自动过期；普通业务用户无权创建、解除或绕过。</p></article><article className="gov-panel"><header><h3>Retention Policy</h3><span>{snapshot.retention_policies.length} 个版本</span></header>{snapshot.retention_policies.map(item => <div className="gov-row" key={item.retention_policy_id}><span><b>{item.policy_code}</b><small>{item.resource_type} · 保留 {item.retention_days} 天 · 归档 {item.archive_after_days ?? '未设定'} 天</small></span><Status value={item.status} /></div>)}</article></section>}

    {tab === 'audit' && <section className="gov-grid two"><article className="gov-panel"><header><h3>站内安全告警</h3><span>{openAlerts} OPEN</span></header>{snapshot.alerts.length ? snapshot.alerts.map(item => <div className="gov-alert" key={item.alert_id}><span className={item.severity}><b>{item.rule_code}</b><small>{item.summary} · {item.event_count} 次 · trace_id={item.trace_id}</small></span><div><Status value={item.status} />{item.status === 'OPEN' && <button onClick={() => void action(`/api/v1/governance/alerts/${item.alert_id}/acknowledge`)}>确认</button>}</div></div>) : <Empty>当前无站内安全告警</Empty>}<button disabled title="P3 不自动发送外部消息">外部通知未开放</button></article><article className="gov-panel"><header><h3>Governance Audit</h3><span>追加写入</span></header>{snapshot.audit_events.slice(0, 12).map(item => <div className="gov-audit" key={item.event_id}><span><b>{item.action}</b><small>{item.actor} · {item.resource_type}/{item.resource_id || '-'}</small></span><span><Status value={item.result} /><small>{item.trace_id}</small></span></div>)}<p className="gov-note">审计事件为追加写入，普通业务用户无修改或删除接口；服务端支持过滤、分页和 CSV 导出。</p></article></section>}

    {tab === 'release' && <section className="gov-grid two"><article className="gov-panel wide"><header><div><h3>Release Registry</h3><p>DRAFT → REVIEW → APPROVED → ACTIVE；回滚创建新记录并保留历史。</p></div><button disabled title="P5 未关闭全部阻断门禁，真实生产发布明确禁用">生产发布已禁用</button></header>{snapshot.releases.length ? <table><thead><tr><th>对象</th><th>版本 / 环境</th><th>状态</th><th>审批</th><th>回滚链</th></tr></thead><tbody>{snapshot.releases.map(item => <tr key={item.release_id}><td><b>{item.object_type}</b><small>{item.object_id}</small></td><td>{item.version} / {item.environment}</td><td><Status value={item.status} /></td><td>{item.approved_by || '未审批'}</td><td>{item.rollback_of_release_id || item.supersedes_release_id || '-'}</td></tr>)}</tbody></table> : <Empty>尚无平台发布记录</Empty>}</article><article className="gov-panel"><header><h3>运行健康</h3><Status value={snapshot.runtime.readiness_http_status === 200 ? 'ACTIVE' : 'FAILED'} /></header><pre>{JSON.stringify(snapshot.runtime.readiness, null, 2)}</pre></article><article className="gov-panel"><header><h3>容量验收边界</h3><span>隔离环境</span></header><p className="gov-note">P50、P95、错误率和并发数由可重复的本地验收脚本生成，不作为生产 SLA。真实企业 SSO、生产发布和真实企业数据仍受外部门禁限制。</p><button onClick={() => void load()}>刷新运行状态</button></article></section>}
    {tab === 'preproduction' && <PreproductionPage token={token} />}
    {tab === 'production' && <ProductionAcceptancePage token={token} />}
  </div>
}
