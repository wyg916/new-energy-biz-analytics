import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { formatMetric, metricNames } from './format'
import './styles.css'
import { ProductApp } from './overview'
import './typography.css'

type Metadata = {data_classification:string;data_time_range:{start:string;end_exclusive:string};source:string;batch_id:string|null;analysis_run_id:string}
type Summary = {metrics:Record<string,number|null>;metadata:Metadata}
type StationRow = {station_id:string;station_name:string;region_id:string;city_id:string;station_type:string;metrics:Record<string,number|null>}
type TrendPoint = {period:string;value:number|null}

const nav = ['经营总览','收入分析','毛利分析','场站分析','设备分析','异常诊断','可信问数','报告草稿']
const navMetrics: Record<string,string[]> = {
  '经营总览':['charging_revenue','gross_profit','gross_margin','charging_volume_kwh','completed_order_count','active_user_count'],
  '收入分析':['charging_revenue','service_fee_revenue','revenue_per_kwh','completed_order_count'],
  '毛利分析':['gross_profit','gross_margin','energy_cost','variable_operating_cost','cost_per_kwh'],
  '场站分析':['station_utilization_rate','charging_volume_kwh','charging_revenue','gross_profit'],
  '设备分析':['device_online_rate','device_fault_rate','station_utilization_rate'],
}

async function api<T>(path:string, token:string):Promise<T>{
  const response=await fetch(path,{headers:{Authorization:`Bearer ${token}`}})
  if(response.status===401){localStorage.removeItem('alpha_token');location.reload()}
  if(!response.ok) throw new Error((await response.json()).detail?.message || '请求失败')
  return response.json()
}

function Sparkline({points}:{points:TrendPoint[]}){
  const values=points.map(p=>p.value ?? 0); const max=Math.max(...values,1); const min=Math.min(...values,0)
  const coords=values.map((v,i)=>`${(i/Math.max(values.length-1,1))*760},${160-((v-min)/(max-min||1))*130}`).join(' ')
  return <div className="chart"><svg viewBox="0 0 760 180" role="img" aria-label="指标月度趋势"><polyline points={coords}/></svg><div className="axis">{points.filter((_,i)=>i%3===0).map(p=><span key={p.period}>{p.period}</span>)}</div></div>
}

function ChatPanel({token}:{token:string}){
  const[question,setQuestion]=useState('区域A在2026年6月充电收入和毛利率是多少？');const[response,setResponse]=useState<any>(null);const[conversationId,setConversationId]=useState<string|null>(null);const[loading,setLoading]=useState(false);const[error,setError]=useState('')
  async function ask(event:React.FormEvent){event.preventDefault();setLoading(true);setError('');try{const r=await fetch('/api/v1/chat/query',{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify({question,conversation_id:conversationId})});const body=await r.json();if(!r.ok)throw new Error(body.detail?.message||'问数失败');setResponse(body);setConversationId(body.conversation_id)}catch(e){setError(e instanceof Error?e.message:'问数失败')}finally{setLoading(false)}}
  return <section className="chat-layout"><article className="panel chat-main"><div className="panel-title"><div><h2>可信 ChatBI</h2><p>自然语言 → Query Plan → 安全编译 → 只读执行 → Answer Guard</p></div><div><span className="safe-chip">受控查询</span> <button className="new-session" onClick={()=>{setConversationId(null);setResponse(null);setQuestion('')}}>新会话</button></div></div><form className="question-box" onSubmit={ask}><textarea value={question} onChange={e=>setQuestion(e.target.value)} maxLength={500}/><button disabled={loading}>{loading?'正在验证并计算…':'开始分析'}</button></form>{error&&<div className="notice error">{error}</div>}{response&&<div className="answer"><span className={`status ${response.status}`}>{response.status}</span><h3>回答</h3><p>{response.answer}</p><small>会话 {response.conversation_id} · 状态版本 {response.state_version}</small>{response.chart&&<div className="chart-data">图表：{response.chart.type} · {response.chart.metric_id} · {response.chart.data.length} 个数据点</div>}<details><summary>查看 Query Plan</summary><pre>{JSON.stringify(response.query_plan,null,2)}</pre></details></div>}</article>{response&&<aside className="panel evidence-panel"><h2>证据面板</h2><dl><div><dt>数据分类</dt><dd>{response.evidence.data_classification}</dd></div><div><dt>来源</dt><dd>{response.evidence.source}</dd></div><div><dt>批次</dt><dd>{response.evidence.batch_id||'未执行'}</dd></div><div><dt>分析运行</dt><dd>{response.evidence.analysis_run_id}</dd></div><div><dt>会话版本</dt><dd>{response.evidence.state_version}</dd></div><div><dt>Query Guard</dt><dd>{response.evidence.query_guard}</dd></div><div><dt>Answer Guard</dt><dd>{response.evidence.answer_guard?.status||'未执行'}</dd></div><div><dt>SQL hash</dt><dd>{response.evidence.sql_hash?.slice(0,16)||'未生成'}</dd></div><div><dt>解释方式</dt><dd>{response.evidence.explanation_mode}</dd></div></dl><details><summary>分析师 SQL 证据</summary><pre>{response.evidence.sql||'当前角色不显示 SQL 或本次未执行'}</pre></details></aside>}</section>
}

function DiagnosticsPanel({token,start,end}:{token:string;start:string;end:string}){
  const[data,setData]=useState<any>(null);const[anomaly,setAnomaly]=useState<any>(null);const[error,setError]=useState('')
  useEffect(()=>{const q=`start=${start}&end_exclusive=${end}`;Promise.all([api<any>(`/api/v1/diagnostics/decomposition?metric=gross_profit&comparison=mom&limit=5&${q}`,token),api<any>(`/api/v1/diagnostics/anomalies?metric=charging_revenue&${q}`,token)]).then(([d,a])=>{setData(d);setAnomaly(a);setError('')}).catch(e=>setError(e.message))},[start,end])
  if(error)return <div className="notice error">{error}</div>;if(!data)return <div className="notice">正在计算异常与贡献拆解…</div>
  const max=Math.max(...data.bridge.map((x:any)=>Math.abs(x.contribution)),1)
  return <section className="diagnostics-grid"><article className="panel"><div className="panel-title"><div><h2>毛利变化桥接</h2><p>收入 − 电费成本 − 可变运营成本</p></div><span className="safe-chip">残差 {data.reconciliation.residual}</span></div><div className="bridge">{data.bridge.map((item:any)=><div key={item.driver}><span>{item.driver}</span><i className={item.contribution<0?'negative':''} style={{width:`${Math.abs(item.contribution)/max*100}%`}}/><b>{formatMetric('gross_profit',item.contribution)}</b></div>)}</div></article><article className="panel"><h2>规则异常</h2><dl><div><dt>指标</dt><dd>充电收入</dd></div><div><dt>环比变化</dt><dd>{anomaly?.change_rate==null?'数据不足':formatMetric('gross_margin',anomaly.change_rate)}</dd></div><div><dt>阈值</dt><dd>{formatMetric('gross_margin',anomaly?.rule.threshold)}</dd></div><div><dt>状态</dt><dd>{anomaly?.triggered?'已触发':'未触发'}</dd></div></dl></article><article className="panel wide"><div className="panel-title"><div><h2>场站贡献定位</h2><p>按绝对贡献排序，不把同期关系解释为因果</p></div></div><table><thead><tr><th>场站</th><th>区域</th><th>当前</th><th>基期</th><th>贡献</th></tr></thead><tbody>{data.station_contributions.map((row:any)=><tr key={row.station_id}><td>{row.station_name}</td><td>{row.region_id}</td><td>{formatMetric('gross_profit',row.current)}</td><td>{formatMetric('gross_profit',row.previous)}</td><td className={row.contribution<0?'down':'up'}>{formatMetric('gross_profit',row.contribution)}</td></tr>)}</tbody></table><section className="evidence"><b>模拟数据</b><span>来源：{data.metadata.source}</span><span>run：{data.metadata.analysis_run_id}</span><span>{data.metadata.causality_boundary}</span></section></article></section>
}

function ReportPanel({token,start,end}:{token:string;start:string;end:string}){
  const[report,setReport]=useState<any>(null);const[error,setError]=useState('');const[loading,setLoading]=useState(false)
  async function generate(){setLoading(true);try{setReport(await api<any>(`/api/v1/reports/draft?report_type=monthly&start=${start}&end_exclusive=${end}`,token));setError('')}catch(e){setError(e instanceof Error?e.message:'生成失败')}finally{setLoading(false)}}
  async function download(format:'markdown'|'csv'){const r=await fetch(`/api/v1/reports/export?report_type=monthly&format=${format}&start=${start}&end_exclusive=${end}`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok){setError('导出失败');return}const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`新能源经营分析月报草稿.${format==='csv'?'csv':'md'}`;a.click();URL.revokeObjectURL(url)}
  return <section className="report-layout"><article className="panel"><div className="panel-title"><div><h2>周报 / 月报草稿</h2><p>仅引用验证后的结构化结果，导出时重新鉴权</p></div><div><button className="new-session" onClick={()=>void generate()}>{loading?'生成中…':'生成月报草稿'}</button></div></div>{error&&<div className="notice error">{error}</div>}{!report&&!loading&&<div className="empty-report">选择数据期后生成可审核草稿；不会自动发送或发布。</div>}{report&&<><section className="evidence"><b>模拟数据</b><span>来源：{report.metadata.source}</span><span>批次：{report.metadata.batch_id}</span><span>run：{report.metadata.analysis_run_id}</span><span>状态：草稿</span></section><div className="report-actions"><button onClick={()=>void download('markdown')}>导出 Markdown</button><button onClick={()=>void download('csv')}>导出 CSV</button></div><pre className="report-preview">{report.markdown}</pre></>}</article></section>
}

function Dashboard({token,onLogout}:{token:string;onLogout:()=>void}){
  const [active,setActive]=useState(nav[0]); const [summary,setSummary]=useState<Summary|null>(null)
  const [stations,setStations]=useState<StationRow[]>([]); const [trend,setTrend]=useState<TrendPoint[]>([])
  const [loading,setLoading]=useState(true); const [error,setError]=useState('')
  const [start,setStart]=useState('2026-01-01'); const [end,setEnd]=useState('2026-07-01')
  const isSpecial=['可信问数','异常诊断','报告草稿'].includes(active);const primary=isSpecial?'charging_revenue':navMetrics[active][0]
  async function load(){setLoading(true);setError('');try{
    const q=`start=${start}&end_exclusive=${end}`
    const [s,st,t]=await Promise.all([
      api<Summary>(`/api/v1/dashboard/summary?${q}`,token),
      api<{rows:StationRow[]}>(`/api/v1/dashboard/stations?${q}&limit=10`,token),
      api<{points:TrendPoint[]}>(`/api/v1/dashboard/trend?metric=${primary}&${q}`,token),
    ]);setSummary(s);setStations(st.rows);setTrend(t.points)
  }catch(e){setError(e instanceof Error?e.message:'加载失败')}finally{setLoading(false)}}
  useEffect(()=>{if(!isSpecial)void load()},[active])
  const maxStation=useMemo(()=>Math.max(...stations.map(s=>s.metrics[primary]??0),1),[stations,primary])
  return <div className="app-shell">
    <aside><div className="brand"><span>新能源</span><strong>经营分析平台</strong><small>AI 增强 BI · Alpha</small></div><nav>{nav.map(item=><button className={item===active?'active':''} onClick={()=>setActive(item)} key={item}>{item}</button>)}</nav><div className="truth-badge">仅限模拟数据<br/>不可用于生产决策</div></aside>
    <main><header><div><h1>{active}</h1><p>统一口径 · 权限过滤 · 可审计证据</p></div><div className="toolbar"><input type="date" value={start} onChange={e=>setStart(e.target.value)}/><span>至</span><input type="date" value={end} onChange={e=>setEnd(e.target.value)}/><button onClick={()=>void load()}>刷新</button><button className="ghost" onClick={onLogout}>退出</button></div></header>
      {active==='可信问数'?<ChatPanel token={token}/>:active==='异常诊断'?<DiagnosticsPanel token={token} start={start} end={end}/>:active==='报告草稿'?<ReportPanel token={token} start={start} end={end}/>:<>{error&&<div className="notice error">{error}</div>}{loading&&<div className="notice">正在从平台数据库计算指标…</div>}
      {summary&&<><section className="evidence"><b>模拟数据</b><span>数据时间：{summary.metadata.data_time_range.start} — {summary.metadata.data_time_range.end_exclusive}（右开）</span><span>来源：平台数据库</span><span>批次：{summary.metadata.batch_id}</span><span>analysis_run_id：{summary.metadata.analysis_run_id}</span></section>
      <section className="kpi-grid">{navMetrics[active].map((id,index)=><article className="kpi" key={id}><div><span>{metricNames[id]}</span><em>{index===0?'核心':'已验证口径'}</em></div><strong>{formatMetric(id,summary.metrics[id])}</strong><small>来自指标语义层 v0.1.0</small></article>)}</section>
      <section className="content-grid"><article className="panel wide"><div className="panel-title"><div><h2>{metricNames[primary]}月度趋势</h2><p>按 Asia/Shanghai 自然月聚合</p></div></div><Sparkline points={trend}/></article>
      <article className="panel"><div className="panel-title"><div><h2>场站贡献排行</h2><p>{metricNames[primary]} Top 10</p></div></div><div className="ranking">{stations.map((row,i)=><div className="rank" key={row.station_id}><b>{i+1}</b><span>{row.station_name}<small>{row.region_id} · {row.station_type}</small></span><div><i style={{width:`${((row.metrics[primary]??0)/maxStation)*100}%`}}/><em>{formatMetric(primary,row.metrics[primary])}</em></div></div>)}</div></article>
      <article className="panel"><div className="panel-title"><div><h2>设备与经营状态</h2><p>相关性提示，不作无证据因果判断</p></div></div><dl><div><dt>设备在线率</dt><dd>{formatMetric('device_online_rate',summary.metrics.device_online_rate)}</dd></div><div><dt>设备故障率</dt><dd>{formatMetric('device_fault_rate',summary.metrics.device_fault_rate)}</dd></div><div><dt>场站利用率</dt><dd>{formatMetric('station_utilization_rate',summary.metrics.station_utilization_rate)}</dd></div></dl></article></section></>}</>}
    </main>
  </div>
}

function App(){const[token,setToken]=useState(localStorage.getItem('alpha_token')||'');const[error,setError]=useState('')
  async function login(event:React.FormEvent<HTMLFormElement>){event.preventDefault();const form=new FormData(event.currentTarget);const response=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.get('username'),password:form.get('password')})});if(!response.ok){setError('登录失败，请检查账号和密码');return}const data=await response.json();localStorage.setItem('alpha_token',data.access_token);setToken(data.access_token)}
  if(token)return <Dashboard token={token} onLogout={()=>{localStorage.removeItem('alpha_token');setToken('')}}/>
  return <main className="login"><form className="login-card" onSubmit={login}><div className="logo">⚡</div><h1>新能源经营分析平台</h1><p>统一指标、可信问数与经营洞察</p><div className="demo-note">产品级 Alpha · 固定种子模拟数据环境</div><label>账号<input name="username" defaultValue="analyst" autoComplete="username"/></label><label>密码<input name="password" type="password" defaultValue="AlphaAnalyst!2026" autoComplete="current-password"/></label><button>安全登录</button>{error&&<p className="login-error">{error}</p>}<small>演示账号仅用于本地 Alpha，不代表真实企业身份</small></form></main>}

createRoot(document.getElementById('root')!).render(<React.StrictMode><ProductApp/></React.StrictMode>)
