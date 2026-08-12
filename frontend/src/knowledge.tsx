import React, { useEffect, useMemo, useState } from 'react'
import './knowledge.css'

type KnowledgeRuntime = {
  knowledge_service: string
  retrieval_mode: string
  vector_status: string
  sqlbot_runtime: string
  model_gateway: {
    status: string
    providers: Array<{ provider_alias: string; configured: boolean; enabled: boolean; credential_ref: string }>
    secret_values_exposed: boolean
  }
  data_classification: string
}

type KnowledgeVersion = {
  document_id: string
  document_version_id: string
  version: number
  title: string
  scenario_id: string
  knowledge_domain: string
  source: string
  status: string
  content_sha256: string
  published_at: string | null
  chunk_count: number
}

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail?.message || '知识服务请求失败')
  return body
}

export function KnowledgePage({ token }: { token: string }) {
  const [runtime, setRuntime] = useState<KnowledgeRuntime | null>(null)
  const [sources, setSources] = useState<string[]>([])
  const [documents, setDocuments] = useState<KnowledgeVersion[]>([])
  const [source, setSource] = useState('docs/metric_dictionary_v0.1.md')
  const [title, setTitle] = useState('指标字典 v0.1')
  const [scenario, setScenario] = useState('charging_ops')
  const [domain, setDomain] = useState('metric_definition')
  const [query, setQuery] = useState('充电收入如何定义？')
  const [retrieval, setRetrieval] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const load = async () => {
    try {
      const [runtimeResult, sourceResult, documentResult] = await Promise.all([
        request<KnowledgeRuntime>('/api/v1/knowledge/runtime', token),
        request<{ sources: string[] }>('/api/v1/knowledge/source-catalog', token),
        request<{ documents: KnowledgeVersion[] }>(`/api/v1/knowledge/documents?scenario_id=${scenario}`, token),
      ])
      setRuntime(runtimeResult)
      setSources(sourceResult.sources)
      setDocuments(documentResult.documents)
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '知识库加载失败')
    }
  }

  useEffect(() => { void load() }, [token, scenario])

  const ingest = async () => {
    setLoading(true); setMessage(''); setError('')
    try {
      await request('/api/v1/knowledge/documents/ingest', token, {
        method: 'POST',
        body: JSON.stringify({
          source_path: source,
          title,
          scenario_id: scenario,
          knowledge_domain: domain,
          roles: ['analyst_admin'],
          data_scopes: ['workspace:all'],
        }),
      })
      setMessage('文档版本已完成解析、分块和校验，当前为 READY，发布前不会参与正式召回。')
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文档接入失败')
    } finally {
      setLoading(false)
    }
  }

  const transition = async (version: KnowledgeVersion, action: 'publish' | 'retire') => {
    setLoading(true); setError(''); setMessage('')
    try {
      await request(`/api/v1/knowledge/versions/${version.document_version_id}/${action}`, token, {
        method: 'POST',
        body: JSON.stringify({ reason: `知识库管理界面执行 ${action}` }),
      })
      setMessage(action === 'publish' ? '版本已发布；同文档旧版本会自动转为 SUPERSEDED。' : '版本已撤回，后续检索不可召回。')
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '状态变更失败')
    } finally {
      setLoading(false)
    }
  }

  const rollback = async (current: KnowledgeVersion, target: KnowledgeVersion) => {
    setLoading(true); setError(''); setMessage('')
    try {
      await request(`/api/v1/knowledge/versions/${current.document_version_id}/rollback`, token, {
        method: 'POST',
        body: JSON.stringify({
          target_version_id: target.document_version_id,
          reason: '知识库管理界面执行受控回滚',
        }),
      })
      setMessage(`已回滚到 v${target.version}。`)
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '版本回滚失败')
    } finally {
      setLoading(false)
    }
  }

  const testRetrieval = async () => {
    setLoading(true); setError('')
    try {
      setRetrieval(await request('/api/v1/knowledge/retrieval/test', token, {
        method: 'POST',
        body: JSON.stringify({
          query,
          scenario_id: scenario,
          limit: 5,
          trace_id: `ui-rag-${Date.now()}`,
        }),
      }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '检索测试失败')
    } finally {
      setLoading(false)
    }
  }

  const rollbackTargets = useMemo(() => {
    const result = new Map<string, KnowledgeVersion>()
    documents.filter(item => item.status === 'SUPERSEDED').forEach(item => {
      const current = result.get(item.document_id)
      if (!current || item.version > current.version) result.set(item.document_id, item)
    })
    return result
  }, [documents])

  return <div className="knowledge-page">
    <section className="knowledge-runtime">
      <article><span>Knowledge Service</span><b>{runtime?.knowledge_service || '检查中'}</b><small>独立生命周期与权限边界</small></article>
      <article><span>Model Gateway</span><b className={runtime?.model_gateway.status === 'READY' ? 'ok' : 'pending'}>{runtime?.model_gateway.status || '检查中'}</b><small>凭据仅显示引用，不返回值</small></article>
      <article><span>SQLBot Runtime</span><b className="pending">{runtime?.sqlbot_runtime || '检查中'}</b><small>Open NL2SQL 已关闭；重新评测由独立 Provider Qualification 工作包完成</small></article>
      <article><span>RAG 检索</span><b>{runtime?.retrieval_mode || '检查中'}</b><small>{runtime?.vector_status || '检查中'} · P5 keyword-only 正式合同</small></article>
    </section>

    {error && <div className="notice error">{error}</div>}
    {message && <div className="notice">{message}</div>}

    <section className="knowledge-grid">
      <article className="knowledge-card ingest">
        <header><div><h2>知识源接入</h2><p>仅允许审核清单中的已跟踪、无秘密正式文档。</p></div><span>受控接入</span></header>
        <label>业务场景<select value={scenario} onChange={event => setScenario(event.target.value)}><option value="charging_ops">charging_ops</option><option value="sales_ops">sales_ops</option></select></label>
        <label>知识域<select value={domain} onChange={event => setDomain(event.target.value)}><option value="metric_definition">metric_definition</option><option value="data_dictionary">data_dictionary</option><option value="business_rule">business_rule</option><option value="analysis_method">analysis_method</option><option value="scenario_guide">scenario_guide</option><option value="security_rule">security_rule</option><option value="system_help">system_help</option></select></label>
        <label>审核来源<select value={source} onChange={event => setSource(event.target.value)}>{sources.map(item => <option key={item}>{item}</option>)}</select></label>
        <label>文档标题<input value={title} onChange={event => setTitle(event.target.value)} maxLength={256} /></label>
        <div className="knowledge-actions"><button onClick={() => void ingest()} disabled={loading || !source}>解析并创建版本</button><button className="disabled" disabled title="P2A 仅允许审核清单中的已跟踪文档；浏览器任意文件上传未开放">本地文件上传未开放</button></div>
        <small>4 份未跟踪用户源文档不会被扫描、读取或自动进入 RAG。</small>
      </article>

      <article className="knowledge-card retrieval">
        <header><div><h2>检索与引用测试</h2><p>权限、场景、状态和有效期在检索前过滤；Vector 已明确延后，不冒充混合检索。</p></div><span>{runtime?.vector_status || 'VECTOR_DEFERRED_POST_P5'}</span></header>
        <textarea value={query} onChange={event => setQuery(event.target.value)} maxLength={1000} />
        <button onClick={() => void testRetrieval()} disabled={loading}>执行受控检索</button>
        {retrieval && <div className="retrieval-result"><p><b>{retrieval.citations.length}</b> 个引用 · {retrieval.retrieval_mode}</p>{retrieval.warnings.map((item: string) => <small key={item}>{item}</small>)}{retrieval.citations.map((item: any) => <details key={item.chunk_id}><summary>{item.title} · {item.section || '未标注章节'} · {Number(item.retrieval_score).toFixed(3)}</summary><p>{item.citation_text}</p><code>{item.document_version_id} / {item.chunk_id}</code></details>)}</div>}
      </article>
    </section>

    <section className="knowledge-card versions">
      <header><div><h2>文档版本与发布</h2><p>READY → PUBLISHED → SUPERSEDED / RETIRED；支持受控回滚。</p></div><button onClick={() => void load()}>刷新</button></header>
      <table><thead><tr><th>文档</th><th>场景 / 知识域</th><th>版本</th><th>状态</th><th>分块</th><th>内容哈希</th><th>操作</th></tr></thead><tbody>{documents.map(item => {
        const target = rollbackTargets.get(item.document_id)
        return <tr key={item.document_version_id}><td><b>{item.title}</b><small>{item.source}</small></td><td>{item.scenario_id}<small>{item.knowledge_domain}</small></td><td>v{item.version}</td><td><em className={`knowledge-status ${item.status.toLowerCase()}`}>{item.status}</em></td><td>{item.chunk_count}</td><td><code>{item.content_sha256.slice(0, 12)}</code></td><td><div className="row-actions">{item.status === 'READY' && <button onClick={() => void transition(item, 'publish')}>发布</button>}{item.status === 'PUBLISHED' && <button onClick={() => void transition(item, 'retire')}>撤回</button>}{item.status === 'PUBLISHED' && target && <button onClick={() => void rollback(item, target)}>回滚至 v{target.version}</button>}</div></td></tr>
      })}</tbody></table>
      {!documents.length && <div className="knowledge-empty">当前场景尚无知识文档版本。</div>}
    </section>
  </div>
}
