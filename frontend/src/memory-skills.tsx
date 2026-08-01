import React, { useEffect, useMemo, useState } from 'react'
import './memory-skills.css'

type MemoryRecord = {
  memory_id: string
  memory_type: string
  scope_type: string
  scenario_id: string | null
  content: string
  structured_value: Record<string, unknown>
  source_type: string
  source_id: string | null
  trust_level: string
  confidence: number
  importance: number
  status: string
  version: number
  expires_at: string | null
  created_at: string
  updated_at: string
}

type MemoryCandidate = {
  candidate_id: string
  memory_type: string
  scenario_id: string | null
  content: string
  source_type: string
  trust_level: string
  confidence: number
  status: string
  write_reason: string
  rejection_reason: string | null
  created_at: string
}

type Skill = {
  skill_id: string
  skill_code: string
  scenario_id: string
  version: string
  status: string
  owner: string
  enabled: boolean
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  adapter_code: string
  steps: Array<Record<string, unknown>>
  validations: Array<Record<string, unknown>>
  shadow_result: Record<string, unknown>
  rollback_skill_id: string | null
  approved_by: string | null
  approved_at: string | null
  controls: { can_enable: boolean; can_disable: boolean; can_rollback: boolean }
}

async function requestJson<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  })
  if (response.status === 401) {
    localStorage.removeItem('alpha_token')
    location.reload()
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail?.message || '请求失败')
  return body
}

function downloadJson(name: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

export function MemoryPage({ token }: { token: string }) {
  const [scenario, setScenario] = useState('charging_ops')
  const [records, setRecords] = useState<MemoryRecord[]>([])
  const [candidates, setCandidates] = useState<MemoryCandidate[]>([])
  const [selected, setSelected] = useState<MemoryRecord | null>(null)
  const [memoryEnabled, setMemoryEnabled] = useState(true)
  const [sessionId, setSessionId] = useState('')
  const [working, setWorking] = useState<Record<string, unknown> | null>(null)
  const [preferenceKey, setPreferenceKey] = useState('answer_style')
  const [preferenceValue, setPreferenceValue] = useState('简洁')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [memory, candidateResult] = await Promise.all([
        requestJson<{ records: MemoryRecord[]; memory_enabled: boolean }>(`/api/v1/memory/records?scenario_id=${scenario}`, token),
        requestJson<{ candidates: MemoryCandidate[] }>('/api/v1/memory/candidates', token),
      ])
      setRecords(memory.records)
      setMemoryEnabled(memory.memory_enabled)
      setCandidates(candidateResult.candidates)
      setSelected(current => memory.records.find(item => item.memory_id === current?.memory_id) || memory.records[0] || null)
    } catch (reason) {
      setRecords([])
      setCandidates([])
      setError(reason instanceof Error ? reason.message : '记忆数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [scenario, token])

  const semantic = useMemo(() => records.filter(item => item.memory_type === 'SEMANTIC'), [records])
  const episodic = useMemo(() => records.filter(item => item.memory_type === 'EPISODIC'), [records])

  const execute = async (key: string, action: () => Promise<void>) => {
    setBusy(key)
    setError('')
    setNotice('')
    try {
      await action()
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '操作失败')
    } finally {
      setBusy('')
    }
  }

  const savePreference = () => execute('preference', async () => {
    const proposed = await requestJson<{ candidate_id: string; status: string }>('/api/v1/memory/preferences', token, {
      method: 'POST',
      body: JSON.stringify({ key: preferenceKey, value: preferenceValue, scenario_id: null, confirmed: true, write_reason: '用户在记忆与偏好页面明确保存或更正' }),
    })
    await requestJson(`/api/v1/memory/candidates/${proposed.candidate_id}/confirm`, token, { method: 'POST' })
    setNotice('偏好已确认并写入；冲突旧版本会转为 SUPERSEDED。')
  })

  const toggleMemory = () => execute('toggle', async () => {
    const result = await requestJson<{ memory_enabled: boolean }>('/api/v1/memory/settings', token, {
      method: 'PUT',
      body: JSON.stringify({ enabled: !memoryEnabled }),
    })
    setNotice(result.memory_enabled ? '后续会话记忆已启用。' : '后续记忆召回与运行记忆已禁用；最小治理审计仍保留。')
  })

  const deleteMemory = (record: MemoryRecord) => execute(`delete:${record.memory_id}`, async () => {
    if (!window.confirm(`确认删除记忆 ${record.memory_id}？删除后不可继续召回。`)) return
    await requestJson(`/api/v1/memory/records/${record.memory_id}?reason=${encodeURIComponent('用户在管理页面删除')}`, token, { method: 'DELETE' })
    setSelected(null)
    setNotice('记忆已删除并从召回范围移除。')
  })

  const decideCandidate = (candidate: MemoryCandidate, decision: 'confirm' | 'reject') => execute(`${decision}:${candidate.candidate_id}`, async () => {
    await requestJson(`/api/v1/memory/candidates/${candidate.candidate_id}/${decision}`, token, {
      method: 'POST',
      ...(decision === 'reject' ? { body: JSON.stringify({ reason: '用户在管理页面拒绝' }) } : {}),
    })
    setNotice(decision === 'confirm' ? '候选记忆已确认。' : '候选记忆已拒绝。')
  })

  const loadWorking = () => execute('working', async () => {
    const result = await requestJson<Record<string, unknown>>(`/api/v1/memory/working/${encodeURIComponent(sessionId)}?scenario_id=${scenario}`, token)
    setWorking(result)
    setNotice('已从 Redis Working Memory 读取当前会话状态。')
  })

  const exportAll = () => execute('export', async () => {
    const result = await requestJson(`/api/v1/memory/export?scenario_id=${scenario}`, token)
    downloadJson(`chatbi-memory-${scenario}.json`, result)
    setNotice('导出文件已生成，包含模拟数据声明和 run_id 位置说明。')
  })

  return <div className="memory-admin-page">
    <section className="memory-toolbar">
      <div><h2>记忆与偏好</h2><p>用户可查看、确认、更正、拒绝、删除和限制记忆；权限由服务端 IdentityContext 注入。</p></div>
      <label>场景<select aria-label="记忆场景" value={scenario} onChange={event => setScenario(event.target.value)}><option value="charging_ops">charging_ops</option><option value="sales_ops">sales_ops</option></select></label>
      <button className={memoryEnabled ? 'danger' : 'primary'} disabled={busy === 'toggle'} onClick={() => void toggleMemory()}>{memoryEnabled ? '禁止后续记忆' : '启用后续记忆'}</button>
      <button disabled={busy === 'export'} onClick={() => void exportAll()}>导出 JSON</button>
    </section>
    <div className="memory-truth"><b>模拟数据</b><span>来源：受治理 PostgreSQL Memory；Working 状态来自 Redis</span><span>run_id：历史分析记录详情中展示</span><span>记忆状态：{memoryEnabled ? '已启用' : '已禁用'}</span></div>
    {error && <div className="notice error">{error}</div>}{notice && <div className="notice success">{notice}</div>}
    {loading ? <div className="notice">正在读取受权限过滤的记忆…</div> : <>
      <section className="memory-summary-grid">
        <article><span>当前偏好</span><b>{semantic.length}</b><small>ACTIVE Semantic</small></article>
        <article><span>历史分析</span><b>{episodic.length}</b><small>可按 run_id 回放</small></article>
        <article><span>待确认候选</span><b>{candidates.filter(item => ['CANDIDATE', 'PENDING_APPROVAL'].includes(item.status)).length}</b><small>不会自动生效</small></article>
        <article><span>跨场景共享</span><b>0</b><small>私有记忆硬隔离</small></article>
      </section>
      <section className="memory-grid">
        <article className="memory-panel preferences-panel"><header><div><h3>当前用户偏好</h3><small>更正会创建新版本，不静默覆盖</small></div></header><div className="preference-form"><label>偏好项<select value={preferenceKey} onChange={event => setPreferenceKey(event.target.value)}><option value="answer_style">回答风格</option><option value="default_region">默认区域</option><option value="default_time_range">默认时间范围</option><option value="corrected_term">术语更正</option></select></label><label>值<input value={preferenceValue} onChange={event => setPreferenceValue(event.target.value)} maxLength={200} /></label><button className="primary" disabled={!preferenceValue.trim() || busy === 'preference'} onClick={() => void savePreference()}>确认保存 / 更正</button></div><div className="memory-list">{semantic.length ? semantic.map(item => <button key={item.memory_id} className={selected?.memory_id === item.memory_id ? 'selected' : ''} onClick={() => setSelected(item)}><span>{String(item.structured_value.key || item.content)}</span><b>v{item.version}</b><small>{item.trust_level} · {item.scope_type}</small></button>) : <p>当前没有已确认偏好。</p>}</div></article>
        <article className="memory-panel working-panel"><header><div><h3>当前工作记忆</h3><small>仅 Redis 短 TTL，不保存完整大结果集</small></div></header><div className="working-query"><input aria-label="Working Memory 会话 ID" placeholder="输入 conversation_id" value={sessionId} onChange={event => setSessionId(event.target.value)} /><button disabled={!sessionId.trim() || busy === 'working'} title={!sessionId.trim() ? '需先输入真实 conversation_id' : ''} onClick={() => void loadWorking()}>读取会话状态</button></div>{working ? <pre>{JSON.stringify(working, null, 2)}</pre> : <div className="memory-empty">尚未选择会话；不会构造替代 Working Memory。</div>}</article>
        <article className="memory-panel history-panel"><header><div><h3>历史分析记录</h3><small>Episodic 摘要与不可逆结果 hash</small></div></header><div className="history-table"><table><thead><tr><th>问题 / Skill</th><th>场景</th><th>run_id</th><th>版本</th><th>操作</th></tr></thead><tbody>{episodic.map(item => <tr key={item.memory_id}><td>{item.content}</td><td>{item.scenario_id}</td><td title={String(item.structured_value.run_id || item.source_id)}>{String(item.structured_value.run_id || item.source_id || '-')}</td><td>v{item.version}</td><td><button onClick={() => setSelected(item)}>查看</button><button className="danger-link" disabled={busy === `delete:${item.memory_id}`} onClick={() => void deleteMemory(item)}>删除</button></td></tr>)}</tbody></table>{!episodic.length && <div className="memory-empty">当前场景没有可召回历史分析。</div>}</div></article>
        <article className="memory-panel candidate-panel"><header><div><h3>候选记忆 / 程序规则</h3><small>未审核候选不会 ACTIVE</small></div></header><div className="candidate-list">{candidates.map(item => <section key={item.candidate_id}><div><b>{item.memory_type}</b><span>{item.status}</span></div><p>{item.content}</p><small>{item.source_type} · {item.write_reason}</small><footer><button disabled={!['CANDIDATE', 'PENDING_APPROVAL'].includes(item.status) || busy === `confirm:${item.candidate_id}`} title={!['CANDIDATE', 'PENDING_APPROVAL'].includes(item.status) ? '候选当前状态不可确认' : ''} onClick={() => void decideCandidate(item, 'confirm')}>确认</button><button disabled={!['CANDIDATE', 'PENDING_APPROVAL'].includes(item.status) || busy === `reject:${item.candidate_id}`} onClick={() => void decideCandidate(item, 'reject')}>拒绝</button></footer></section>)}{!candidates.length && <div className="memory-empty">当前用户没有候选记忆。</div>}</div></article>
        <article className="memory-panel detail-panel"><header><div><h3>记忆详情</h3><small>来源、作用域、可信度、版本与过期时间</small></div>{selected && <button className="danger-link" onClick={() => void deleteMemory(selected)}>删除</button>}</header>{selected ? <><dl><div><dt>ID</dt><dd>{selected.memory_id}</dd></div><div><dt>类型 / 状态</dt><dd>{selected.memory_type} / {selected.status}</dd></div><div><dt>作用域 / 场景</dt><dd>{selected.scope_type} / {selected.scenario_id || '通用'}</dd></div><div><dt>来源</dt><dd>{selected.source_type} / {selected.source_id || '-'}</dd></div><div><dt>可信度</dt><dd>{selected.trust_level} · {(selected.confidence * 100).toFixed(0)}%</dd></div><div><dt>版本 / 过期</dt><dd>v{selected.version} / {selected.expires_at || '按策略保留'}</dd></div></dl><pre>{JSON.stringify(selected.structured_value, null, 2)}</pre></> : <div className="memory-empty">选择一条记录查看详情。</div>}</article>
      </section>
    </>}
  </div>
}

export function SkillPage({ token }: { token: string }) {
  const [scenario, setScenario] = useState('charging_ops')
  const [skills, setSkills] = useState<Skill[]>([])
  const [selected, setSelected] = useState<Skill | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const result = await requestJson<{ skills: Skill[] }>(`/api/v1/skills?scenario_id=${scenario}`, token)
      setSkills(result.skills)
      setSelected(current => result.skills.find(item => item.skill_id === current?.skill_id) || result.skills[0] || null)
    } catch (reason) {
      setSkills([])
      setError(reason instanceof Error ? reason.message : 'Skill 加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [scenario, token])

  const control = async (skill: Skill, action: 'enable' | 'disable' | 'rollback') => {
    setBusy(`${action}:${skill.skill_id}`)
    setError('')
    setNotice('')
    try {
      await requestJson(`/api/v1/skills/${skill.skill_id}/${action}`, token, { method: 'POST' })
      setNotice(`Skill ${action} 操作已由后端完成并写入审计。`)
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Skill 操作失败')
    } finally {
      setBusy('')
    }
  }

  return <div className="skill-admin-page">
    <section className="skill-toolbar"><div><h2>Skill 管理</h2><p>程序模板、场景适配、审核状态、灰度与回滚均来自后端 Registry。</p></div><label>场景<select aria-label="Skill 场景" value={scenario} onChange={event => setScenario(event.target.value)}><option value="charging_ops">charging_ops</option><option value="sales_ops">sales_ops</option></select></label><button onClick={() => void load()}>刷新 Registry</button></section>
    <div className="memory-truth"><b>模拟数据</b><span>来源：ProcedureRegistry / SkillRegistry</span><span>ACTIVE Skill：{skills.filter(item => item.status === 'ACTIVE' && item.enabled).length}</span><span>未审核生效数：0</span></div>
    {error && <div className="notice error">{error}</div>}{notice && <div className="notice success">{notice}</div>}
    {loading ? <div className="notice">正在读取 Skill Registry…</div> : <section className="skill-grid">
      <article className="skill-catalog"><header><h3>已发布与候选 Skill</h3><span>{skills.length} 个版本</span></header><table><thead><tr><th>Skill</th><th>场景</th><th>版本</th><th>状态</th><th>Owner</th><th>操作</th></tr></thead><tbody>{skills.map(skill => <tr key={skill.skill_id} className={selected?.skill_id === skill.skill_id ? 'selected' : ''} onClick={() => setSelected(skill)}><td><b>{skill.skill_code}</b><small>{skill.adapter_code}</small></td><td>{skill.scenario_id}</td><td>{skill.version}</td><td><em className={skill.status.toLowerCase()}>{skill.status}</em></td><td>{skill.owner}</td><td><div className="skill-actions"><button disabled={!skill.controls.can_enable || busy === `enable:${skill.skill_id}`} title={!skill.controls.can_enable ? '仅 APPROVED / SHADOW / CANARY 可启用' : ''} onClick={event => { event.stopPropagation(); void control(skill, 'enable') }}>启用</button><button disabled={!skill.controls.can_disable || busy === `disable:${skill.skill_id}`} title={!skill.controls.can_disable ? '仅已启用 ACTIVE Skill 可停用' : ''} onClick={event => { event.stopPropagation(); void control(skill, 'disable') }}>停用</button><button disabled={!skill.controls.can_rollback || busy === `rollback:${skill.skill_id}`} title={!skill.controls.can_rollback ? '未配置已批准回滚目标' : ''} onClick={event => { event.stopPropagation(); void control(skill, 'rollback') }}>回滚</button></div></td></tr>)}</tbody></table>{!skills.length && <div className="memory-empty">当前场景尚未发布 Skill。</div>}</article>
      <article className="skill-detail"><header><div><h3>Skill 定义与验证</h3><small>输入输出、步骤、校验、Shadow 与审核</small></div></header>{selected ? <><dl><div><dt>名称 / 版本</dt><dd>{selected.skill_code} / {selected.version}</dd></div><div><dt>状态 / Owner</dt><dd>{selected.status} / {selected.owner}</dd></div><div><dt>审核</dt><dd>{selected.approved_by || '未审核'} · {selected.approved_at || '-'}</dd></div><div><dt>场景适配</dt><dd>{selected.scenario_id} → {selected.adapter_code}</dd></div></dl><section><h4>输入 Schema</h4><pre>{JSON.stringify(selected.input_schema, null, 2)}</pre></section><section><h4>输出 Schema</h4><pre>{JSON.stringify(selected.output_schema, null, 2)}</pre></section><section><h4>程序步骤</h4><ol>{selected.steps.map((step, index) => <li key={index}><b>{String(step.code || index + 1)}</b><span>{String(step.tool || '')}</span></li>)}</ol></section><section><h4>校验规则</h4><ul>{selected.validations.map((rule, index) => <li key={index}>{String(rule.code || JSON.stringify(rule))}</li>)}</ul></section><section><h4>Shadow 结果</h4><pre>{Object.keys(selected.shadow_result).length ? JSON.stringify(selected.shadow_result, null, 2) : '尚无 Shadow 结果；不会显示虚构评测。'}</pre></section></> : <div className="memory-empty">选择一个 Skill 查看定义。</div>}</article>
    </section>}
  </div>
}
