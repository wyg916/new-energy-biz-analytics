import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

function App() {
  const [token, setToken] = useState(localStorage.getItem('alpha_token') || '')
  const [error, setError] = useState('')
  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const response = await fetch('/api/v1/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:form.get('username'), password:form.get('password')})})
    if (!response.ok) { setError('登录失败，请检查账号和密码'); return }
    const data = await response.json(); localStorage.setItem('alpha_token', data.access_token); setToken(data.access_token); setError('')
  }
  if (token) return <main><header><strong>新能源企业经营分析智能平台</strong><button onClick={()=>{localStorage.removeItem('alpha_token');setToken('')}}>退出</button></header><section className="card"><h1>认证闭环已就绪</h1><p>后续经营数据切片将在本页面连续接入。</p><small>模拟数据 · 数据时间待生成 · 来源：平台数据库 · analysis_run_id：待执行</small></section></main>
  return <main className="login"><form className="card" onSubmit={login}><h1>经营分析平台</h1><p>产品级 Alpha · 模拟数据环境</p><label>账号<input name="username" defaultValue="analyst" /></label><label>密码<input name="password" type="password" defaultValue="AlphaAnalyst!2026" /></label><button>登录</button>{error && <p className="error">{error}</p>}</form></main>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
