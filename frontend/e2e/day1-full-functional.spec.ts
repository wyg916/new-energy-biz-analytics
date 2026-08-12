import { expect, test, type Download, type Locator, type Page, type Request } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const oidcPassword = process.env.P4_OIDC_PASSWORD
const acceptanceOrigin = new URL(
  process.env.PLAYWRIGHT_BASE_URL ?? 'https://p5b.localhost:8446',
).origin
const repositoryRoot = fs.existsSync(path.join(process.cwd(), 'frontend'))
  ? process.cwd()
  : path.resolve(process.cwd(), '..')
const evidenceRoot = path.join(
  repositoryRoot,
  'docs',
  'platformization',
  'day1-functional-acceptance',
  'evidence',
)
const finalScreenshotRoot = path.join(evidenceRoot, 'screenshots', 'final')

type ApiObservation = {
  page: string
  method: string
  url: string
  status: number
  ok: boolean
  duration_ms: number
  resource_type: string
  content_type: string
}

type StepObservation = {
  id: string
  title: string
  status: 'PASS' | 'FAIL' | 'BOUNDARY_PASS'
  started_at: string
  finished_at: string
  duration_ms: number
  details?: Record<string, unknown>
  error?: string
}

type RawEvidence = {
  schema_version: string
  evidence_type: string
  run_key: string
  base_url: string
  started_at: string
  finished_at?: string
  status: 'RUNNING' | 'PASS' | 'FAIL'
  pages: string[]
  steps: StepObservation[]
  screenshots: string[]
  api_responses: ApiObservation[]
  console_errors: Array<{ page: string; text: string }>
  page_errors: Array<{ page: string; text: string }>
  request_failures: Array<{
    page: string
    method: string
    url: string
    resource_type: string
    error: string
  }>
  failure?: string
}

type ApiMatch = {
  method?: string
  path: string | RegExp
  timeout?: number
}

test.use({ viewport: { width: 1600, height: 960 }, acceptDownloads: true })
test.skip(!oidcPassword, 'DAY-1 full functional acceptance requires the runtime-only OIDC password')
test.setTimeout(900_000)

function isoNow() {
  return new Date().toISOString()
}

function dateOffset(value: string, days: number) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function chineseDate(value: string) {
  const [year, month, day] = value.split('-').map(Number)
  return `${year}年${month}月${day}日`
}

function safeUrl(raw: string, includeQuery = false) {
  try {
    const url = new URL(raw)
    return `${url.origin}${url.pathname}${includeQuery ? url.search : ''}`
  } catch {
    return raw.split('?')[0]
  }
}

function responseMatches(response: import('@playwright/test').Response, match: ApiMatch) {
  const url = new URL(response.url())
  const methodMatches = !match.method || response.request().method() === match.method
  const pathMatches = typeof match.path === 'string'
    ? url.pathname.includes(match.path)
    : match.path.test(url.pathname)
  return methodMatches && pathMatches
}

async function apiAction(
  page: Page,
  match: ApiMatch,
  action: () => Promise<unknown>,
) {
  const responsePromise = page.waitForResponse(
    response => responseMatches(response, match),
    { timeout: match.timeout ?? 120_000 },
  )
  await action()
  const response = await responsePromise
  const body = await response.json().catch(() => null)
  expect(
    response.ok(),
    `${response.request().method()} ${response.url()} returned ${response.status()} body=${JSON.stringify(body)}`,
  ).toBeTruthy()
  return { response, body }
}

async function expectOkWithBody(response: import('@playwright/test').Response) {
  const body = await response.json().catch(() => null)
  expect(
    response.ok(),
    `${response.request().method()} ${response.url()} returned ${response.status()} body=${JSON.stringify(body)}`,
  ).toBeTruthy()
  return body
}

async function expectDisabledBoundary(locator: Locator, title?: string | RegExp) {
  await expect(locator).toBeVisible()
  await expect(locator).toBeDisabled()
  await expect(locator).toHaveAttribute('title', title ?? /\S+/)
}

async function expectRenderedChart(locator: Locator) {
  await expect(locator).toBeVisible()
  const hasData = await locator.evaluate(node => {
    const primitives = Array.from(node.querySelectorAll('polyline,path,rect,circle,polygon,[style],button'))
    return primitives.some(item => {
      const points = item.getAttribute('points')
      const d = item.getAttribute('d')
      const height = item.getAttribute('height')
      const style = item.getAttribute('style')
      const box = (item as HTMLElement).getBoundingClientRect()
      return Boolean(
        (points && points.trim())
        || (d && d.trim())
        || (height && Number(height) > 0)
        || item.tagName === 'CIRCLE'
        || (style && box.width > 0 && box.height > 0),
      )
    })
  })
  expect(hasData).toBeTruthy()
}

async function readJsonDownload(download: Download) {
  const downloadedPath = await download.path()
  if (!downloadedPath) throw new Error('download path was not available')
  const text = fs.readFileSync(downloadedPath, 'utf8')
  expect(text.length).toBeGreaterThan(20)
  return JSON.parse(text) as Record<string, unknown>
}

function writeEvidence(value: RawEvidence) {
  fs.mkdirSync(evidenceRoot, { recursive: true })
  const target = path.join(evidenceRoot, 'day1-functional-playwright.json')
  const temporary = `${target}.${process.pid}.tmp`
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  fs.renameSync(temporary, target)
}

test('DAY-1 real OIDC and API full functional acceptance', async ({ page, context }) => {
  page.setDefaultTimeout(30_000)
  const runKey = `DAY1-${Date.now()}`
  const evidence: RawEvidence = {
    schema_version: '1.0',
    evidence_type: 'day1_full_functional_playwright_raw',
    run_key: runKey,
    base_url: acceptanceOrigin,
    started_at: isoNow(),
    status: 'RUNNING',
    pages: [],
    steps: [],
    screenshots: [],
    api_responses: [],
    console_errors: [],
    page_errors: [],
    request_failures: [],
  }
  const pageLabels = new WeakMap<Page, string>()
  const requestStartedAt = new WeakMap<Request, number>()
  let completed = false
  let restorePage: Page | null = null
  let conversationId = ''

  const setPage = (target: Page, label: string) => {
    pageLabels.set(target, label)
    if (!evidence.pages.includes(label)) evidence.pages.push(label)
  }

  const observe = (target: Page, initialLabel: string) => {
    setPage(target, initialLabel)
    target.on('request', request => requestStartedAt.set(request, Date.now()))
    target.on('console', message => {
      if (message.type() === 'error') {
        evidence.console_errors.push({ page: pageLabels.get(target) || 'UNKNOWN', text: message.text() })
      }
    })
    target.on('pageerror', error => {
      evidence.page_errors.push({ page: pageLabels.get(target) || 'UNKNOWN', text: error.message })
    })
    target.on('requestfailed', request => {
      evidence.request_failures.push({
        page: pageLabels.get(target) || 'UNKNOWN',
        method: request.method(),
        url: safeUrl(request.url()),
        resource_type: request.resourceType(),
        error: request.failure()?.errorText || 'unknown',
      })
    })
    target.on('response', response => {
      const url = new URL(response.url())
      if (!url.pathname.includes('/api/')) return
      const request = response.request()
      evidence.api_responses.push({
        page: pageLabels.get(target) || 'UNKNOWN',
        method: request.method(),
        url: safeUrl(response.url(), true),
        status: response.status(),
        ok: response.ok(),
        duration_ms: Math.max(0, Date.now() - (requestStartedAt.get(request) ?? Date.now())),
        resource_type: request.resourceType(),
        content_type: response.headers()['content-type'] || '',
      })
    })
  }

  const acceptanceStep = async <T,>(
    id: string,
    title: string,
    action: () => Promise<T>,
    summarize?: (value: T) => Record<string, unknown>,
    boundary = false,
  ): Promise<T> => test.step(`${id} ${title}`, async () => {
    const started = Date.now()
    const startedAt = isoNow()
    try {
      const value = await action()
      evidence.steps.push({
        id,
        title,
        status: boundary ? 'BOUNDARY_PASS' : 'PASS',
        started_at: startedAt,
        finished_at: isoNow(),
        duration_ms: Date.now() - started,
        ...(summarize ? { details: summarize(value) } : {}),
      })
      return value
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      evidence.steps.push({
        id,
        title,
        status: 'FAIL',
        started_at: startedAt,
        finished_at: isoNow(),
        duration_ms: Date.now() - started,
        error: message,
      })
      throw error
    }
  })

  const navigate = async (target: Page, label: string) => {
    setPage(target, label)
    await target.locator('.product-sidebar nav button').filter({ hasText: label }).click()
    await expect(target.locator('.product-header h1')).toContainText(label, { timeout: 120_000 })
    await expect(target.locator('.notice.error, .workbench-error, .revenue-error, .margin-error, .device-error, .gov-state.denied')).toHaveCount(0)
  }

  const capture = async (target: Page, id: string) => {
    fs.mkdirSync(finalScreenshotRoot, { recursive: true })
    const filename = `${id}.jpg`
    await target.screenshot({
      path: path.join(finalScreenshotRoot, filename),
      type: 'jpeg',
      quality: 72,
      fullPage: true,
    })
    const relative = `screenshots/final/${filename}`
    if (!evidence.screenshots.includes(relative)) evidence.screenshots.push(relative)
  }

  const selectSecondOptionWhenPresent = async (locator: Locator) => {
    const options = await locator.locator('option').count()
    await expect(locator).toBeEnabled()
    if (options > 1) {
      await locator.selectOption({ index: 1 })
      return await locator.inputValue()
    }
    await locator.selectOption({ index: 0 })
    return await locator.inputValue()
  }

  observe(page, 'LOGIN')

  try {
    await acceptanceStep('AUTH-001', '登录页和缺参 OIDC callback 边界', async () => {
      await page.goto('/')
      await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible({ timeout: 120_000 })
      const callbackPage = await context.newPage()
      observe(callbackPage, 'OIDC-CALLBACK-MISSING-PARAMS')
      await callbackPage.goto('/oidc/callback')
      await expect(callbackPage.getByTestId('oidc-callback')).toContainText('企业身份登录失败')
      await expect(callbackPage.getByTestId('oidc-callback')).toContainText('缺少 code 或 state')
      await callbackPage.close()
    })

    const dashboardContext = await acceptanceStep('AUTH-002', '真实 OIDC PKCE 登录与 callback', async () => {
      setPage(page, 'OIDC-LOGIN')
      const contextResponse = page.waitForResponse(
        response => response.url().includes('/api/v1/dashboard/context') && response.ok(),
        { timeout: 120_000 },
      )
      await expect(page.getByTestId('oidc-login')).toBeEnabled({ timeout: 120_000 })
      await Promise.all([
        page.waitForURL(/\/protocol\/openid-connect\/auth/),
        page.getByTestId('oidc-login').click(),
      ])
      await page.locator('#username').fill('p4.analyst')
      await page.locator('#password').fill(oidcPassword!)
      const callback = page.waitForResponse(
        response => response.url().includes('/api/v1/auth/oidc/callback'),
        { timeout: 120_000 },
      )
      await page.locator('#kc-login').click()
      await expectOkWithBody(await callback)
      await page.waitForURL(url => url.origin === acceptanceOrigin && url.pathname === '/')
      setPage(page, '功能总览')
      await expect(page.getByRole('heading', { name: '功能总览', exact: true })).toBeVisible({ timeout: 120_000 })
      const response = await contextResponse
      return await response.json() as any
    }, value => ({
      scenario_id: value.scenario?.scenario_id,
      metric_count: value.metric_count,
      default_time_range: value.default_time_range,
      available_time_range: value.available_time_range,
    }))

    restorePage = await acceptanceStep('AUTH-003', '同一浏览器上下文恢复 localStorage 会话', async () => {
      const restored = await context.newPage()
      observe(restored, 'SESSION-RESTORE')
      await restored.goto('/')
      await expect(restored.getByRole('heading', { name: '功能总览', exact: true })).toBeVisible({ timeout: 120_000 })
      const tokenPresent = await restored.evaluate(() => Boolean(localStorage.getItem('alpha_token')))
      expect(tokenPresent).toBeTruthy()
      return restored
    }, () => ({ storage: 'localStorage.alpha_token', restored: true }))

    const chargingStart = dashboardContext.available_time_range?.start
      ?? dashboardContext.default_time_range?.start
    const chargingEndExclusive = dashboardContext.available_time_range?.end_exclusive
      ?? dashboardContext.default_time_range?.end_exclusive
    expect(chargingStart).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(chargingEndExclusive).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    const periodEnd = dateOffset(chargingEndExclusive, -1)
    const chargingProposedStart = dateOffset(chargingEndExclusive, -8)
    const periodStart = chargingProposedStart < chargingStart ? chargingStart : chargingProposedStart
    let salesQuestionWindow = ''

    await acceptanceStep('GLOBAL-001', '全局开始和结束日期驱动真实 Dashboard API', async () => {
      setPage(page, '功能总览')
      const startInput = page.getByLabel('开始日期')
      const endInput = page.getByLabel('结束日期')
      const currentStart = await startInput.inputValue()
      if (currentStart === periodStart) {
        await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/summary' }, () => startInput.fill(dateOffset(periodStart, 1)))
      }
      await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/summary' }, () => startInput.fill(periodStart))
      const currentEnd = await endInput.inputValue()
      if (currentEnd === periodEnd) {
        await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/summary' }, () => endInput.fill(dateOffset(periodEnd, -1)))
      }
      await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/summary' }, () => endInput.fill(periodEnd))
      await expect(startInput).toHaveValue(periodStart)
      await expect(endInput).toHaveValue(periodEnd)
      await expect(page.locator('.global-data-status')).toContainText(`统计期间：${periodStart} 至 ${periodEnd}`)
    }, () => ({ start: periodStart, end_inclusive: periodEnd, end_exclusive: chargingEndExclusive }))

    await acceptanceStep('DASHBOARD-001', '工作台筛选、查询、图表、表格和钻取', async () => {
      const result = await apiAction(page, { method: 'GET', path: '/api/v1/diagnostics/decomposition' }, () => navigate(page, '经营工作台'))
      expect(result.response.ok()).toBeTruthy()
      const filters = page.locator('.workbench-filters')
      await expect(filters.locator('input[type="date"]').nth(0)).toHaveValue(periodStart)
      await expect(filters.locator('input[type="date"]').nth(1)).toHaveValue(periodEnd)
      const selects = filters.locator('select')
      await apiAction(page, { method: 'GET', path: '/api/v1/diagnostics/decomposition' }, () => selects.nth(0).selectOption('yoy'))
      await expect(selects.nth(0)).toHaveValue('yoy')
      for (const index of [1, 2, 3]) {
        await expect(selects.nth(index)).toBeDisabled()
        await expect(selects.nth(index)).toHaveAttribute('title', /尚未接入当前聚合接口/)
      }
      await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/summary' }, () => filters.getByRole('button', { name: /查询/ }).click())
      await expect(page.locator('.workbench-kpis article')).toHaveCount(6)
      await expect(page.locator('.workbench-analysis svg')).not.toHaveCount(0)
      await expect(page.locator('.workbench-tables article').nth(1).locator('tbody tr').first()).toBeVisible()
      await capture(page, '01-dashboard')
      await page.getByRole('button', { name: /查看更多场站/ }).click()
      await expect(page.locator('.product-header h1')).toHaveText('场站经营')
      await navigate(page, '经营工作台')
    }, () => ({ filters: ['date', 'comparison', 'region', 'city', 'station'], drilldown: '场站经营' }))

    await acceptanceStep('REVENUE-001', '收入页筛选、刷新、图表和表格', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/revenue/analysis' }, () => navigate(page, '收入与订单'))
      const bar = page.locator('.revenue-filter-bar')
      await expect(page.getByLabel('收入开始日期')).toHaveValue(periodStart)
      await expect(page.getByLabel('收入结束日期')).toHaveValue(periodEnd)
      await apiAction(page, { method: 'GET', path: '/api/v1/revenue/analysis' }, () => page.getByLabel('对比模式').selectOption('year'))
      await selectSecondOptionWhenPresent(bar.locator('select').nth(0))
      for (const index of [1, 2]) {
        await expectDisabledBoundary(bar.locator('select').nth(index), '收入分析接口当前仅支持区域维度')
      }
      await expectDisabledBoundary(bar.locator('select').nth(4), '收入趋势当前固定为按日粒度')
      await expectRenderedChart(page.getByRole('img', { name: '本期与对比期收入趋势' }))
      await expectRenderedChart(page.getByRole('img', { name: '收入变化驱动桥接图' }))
      await expect(page.locator('.revenue-heatmap i[title]').first()).toBeVisible()
      await expect(page.locator('.revenue-decline-panel tbody tr').first()).toBeVisible()
      await bar.getByRole('button', { name: '重置', exact: true }).click()
      await expect(page.getByLabel('对比模式')).toHaveValue('period')
      await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/summary' }, () => bar.getByRole('button', { name: '刷新', exact: true }).click())
      await capture(page, '02-revenue')
    }, () => ({ charts: 2, heatmap: true, table: '重点下滑场站' }))

    await acceptanceStep('MARGIN-001', '毛利页对比、重置、刷新、图表和表格', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/diagnostics/decomposition' }, () => navigate(page, '毛利与成本'))
      await apiAction(page, { method: 'GET', path: '/api/v1/diagnostics/decomposition' }, () => page.getByRole('button', { name: '同比', exact: true }).click())
      await expect(page.getByRole('heading', { name: /毛利桥接（同比）/ })).toBeVisible()
      await expectRenderedChart(page.getByRole('img', { name: '毛利桥接环比图' }))
      await expectRenderedChart(page.getByRole('img', { name: '度电成本月度趋势' }))
      await expect(page.locator('.margin-station-panel tbody tr').first()).toBeVisible()
      await page.getByRole('button', { name: '重置', exact: true }).click()
      await expect(page.getByRole('button', { name: '环比', exact: true })).toHaveClass(/active/)
      await apiAction(page, { method: 'GET', path: '/api/v1/diagnostics/decomposition' }, () => page.getByRole('button', { name: /刷新/ }).click())
      await expectDisabledBoundary(page.getByRole('button', { name: '日', exact: true }), '当前接口仅提供月粒度')
      await capture(page, '03-margin')
    }, () => ({ comparison: ['mom', 'yoy'], charts: 2, disabled_boundary: 'non-month grain' }))

    await acceptanceStep('STATIONS-001', '场站筛选、查询、矩阵、表格和详情钻取', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/stations' }, () => navigate(page, '场站经营'))
      const bar = page.locator('.station-filter-bar')
      const region = bar.locator('select').nth(0)
      const type = bar.locator('select').nth(3)
      await selectSecondOptionWhenPresent(region)
      await bar.getByRole('button', { name: '重置', exact: true }).click()
      await selectSecondOptionWhenPresent(type)
      await bar.getByRole('button', { name: '重置', exact: true }).click()
      await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/summary' }, () => bar.getByRole('button', { name: '查询', exact: true }).click())
      const bubble = page.locator('button.station-bubble').first()
      await expect(bubble).toBeVisible()
      await bubble.click()
      await expect(bubble).toHaveClass(/selected/)
      await expectRenderedChart(page.getByRole('img', { name: '场站利用率与毛利率矩阵' }))
      const row = page.locator('.rank-panel tbody tr').first()
      await row.click()
      await expect(page.locator('.station-detail-panel h2')).not.toContainText('暂无场站')
      await expectDisabledBoundary(page.getByRole('button', { name: /地图未开放/ }), '地图视图未实现')
      await expectDisabledBoundary(page.getByRole('button', { name: /详情页未开放/ }), '更多详情页面未实现')
      await capture(page, '04-stations')
      const chatResponse = page.waitForResponse(
        response => response.url().includes('/api/v1/assistant/query') && response.request().method() === 'POST',
        { timeout: 120_000 },
      )
      await page.getByRole('button', { name: /查看策略建议/ }).click()
      await expect(page.locator('.product-header h1')).toHaveText('AI经营分析')
      await expectOkWithBody(await chatResponse)
      await navigate(page, '场站经营')
    }, () => ({ filters: ['region', 'type'], matrix_selection: true, table_selection: true, drilldown: 'AI经营分析' }))

    await acceptanceStep('DEVICES-001', '设备筛选、刷新、图表、表格和详情', async () => {
      const devicePageResponse = await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/devices' }, () => navigate(page, '设备健康'))
      await selectSecondOptionWhenPresent(page.getByLabel('设备场站'))
      await page.getByRole('button', { name: '重置', exact: true }).click()
      await selectSecondOptionWhenPresent(page.getByLabel('设备型号'))
      await page.getByRole('button', { name: '风险优先', exact: true }).click()
      const row = page.locator('.device-table-panel tbody tr').first()
      await expect(row).toBeVisible()
      await row.click()
      await expect(page.locator('.device-detail-panel h2')).not.toContainText('暂无设备')
      const pareto = page.getByRole('img', { name: '故障类型帕累托排名' })
      if (await pareto.count()) {
        await expectRenderedChart(pareto)
      } else {
        expect(devicePageResponse.body.reason_summary).toEqual([])
        await expect(page.getByText('当前周期未发现离线或故障事件')).toBeVisible()
      }
      await expectRenderedChart(page.getByRole('img', { name: '设备在线、离线与故障率趋势' }))
      await page.getByRole('button', { name: '重置', exact: true }).click()
      await apiAction(page, { method: 'GET', path: '/api/v1/dashboard/devices' }, () => page.getByRole('button', { name: /刷新/ }).click())
      await expectDisabledBoundary(page.getByRole('button', { name: '详情未开放', exact: true }), '详情页未实现')
      await expectDisabledBoundary(page.getByRole('button', { name: '导出未开放', exact: true }), '导出未实现')
      await capture(page, '05-devices')
    }, () => ({ filters: ['station', 'model', 'status'], charts: 2, table_selection: true }))

    const chatResult = await acceptanceStep('CHATBI-001', '场景、回答风格、问题、多轮与反馈', async () => {
      const initial = page.waitForResponse(
        response => response.url().includes('/api/v1/assistant/query') && response.request().method() === 'POST',
        { timeout: 120_000 },
      )
      await navigate(page, 'AI经营分析')
      await expectOkWithBody(await initial)
      const scenario = page.getByLabel('当前业务场景')
      const salesInitial = await apiAction(page, { method: 'POST', path: '/api/v1/assistant/query' }, () => scenario.selectOption('sales_ops'))
      const salesRange = salesInitial.body.data_query_evidence?.evidence?.data_time_range
      expect(salesRange?.start).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(salesRange?.end_exclusive).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      const salesStart = dateOffset(salesRange.end_exclusive, -8)
      const salesEnd = dateOffset(salesRange.end_exclusive, -1)
      salesQuestionWindow = `${chineseDate(salesStart < salesRange.start ? salesRange.start : salesStart)}至${chineseDate(salesEnd)}`
      await page.getByLabel('回答风格').selectOption('analyst_detailed')
      const question = page.getByLabel('经营分析问题')
      const firstQuestion = `${salesQuestionWindow}销售收入、订单数和销售毛利率是多少？`
      await question.fill(firstQuestion)
      const first = await apiAction(page, { method: 'POST', path: '/api/v1/assistant/query' }, () => page.getByLabel('发送分析问题').click())
      expect(first.body.data_query_evidence.status).toBe('completed')
      expect(first.body.data_query_evidence.evidence.answer_guard.status).toBe('passed')
      const firstConversation = String(first.body.conversation_id)
      expect(firstConversation).toMatch(/^CONV-/)
      const secondQuestion = `${salesQuestionWindow}订单数是多少？`
      await question.fill(secondQuestion)
      const second = await apiAction(page, { method: 'POST', path: '/api/v1/assistant/query' }, () => page.getByLabel('发送分析问题').click())
      expect(second.body.conversation_id).toBe(firstConversation)
      expect(second.body.data_query_evidence.evidence.query_guard).toBe('passed')
      const feedback = await apiAction(page, { method: 'POST', path: '/api/v1/assistant/feedback' }, () => page.getByRole('button', { name: '有帮助', exact: true }).click())
      expect(feedback.body.status).toBe('recorded')
      await expect(page.getByText('反馈已记录到审计日志')).toBeVisible()
      await capture(page, '06-chatbi')
      return { conversationId: firstConversation, firstRunId: first.body.run_id, secondRunId: second.body.run_id }
    }, value => ({ conversation_id: value.conversationId, run_ids: [value.firstRunId, value.secondRunId], scenario: 'sales_ops' }))
    conversationId = chatResult.conversationId

    await acceptanceStep('MEMORY-001', '记忆保存、Working Memory 读取、JSON 导出与删除', async () => {
      if (!restorePage) throw new Error('session restore page is unavailable')
      await apiAction(restorePage, { method: 'GET', path: '/api/v1/memory/records' }, () => navigate(restorePage!, '记忆与偏好'))
      const workingInput = restorePage.getByLabel('Working Memory 会话 ID')
      await expectDisabledBoundary(
        restorePage.locator('.working-query button'),
        '需先输入真实 conversation_id',
      )
      await workingInput.fill(conversationId)
      const working = await apiAction(restorePage, { method: 'GET', path: /\/api\/v1\/memory\/working\// }, () => restorePage!.locator('.working-query button').click())
      expect(['AVAILABLE', 'MISS', 'DEGRADED']).toContain(working.body.status)
      await expect(restorePage.locator('.working-panel pre')).toBeVisible()

      const preferenceValue = `术语-${runKey}`
      await restorePage.locator('.preference-form select').selectOption('corrected_term')
      await restorePage.locator('.preference-form input').fill(preferenceValue)
      const saved = await apiAction(
        restorePage,
        { method: 'POST', path: /\/api\/v1\/memory\/candidates\/[^/]+\/confirm$/ },
        () => restorePage!.getByRole('button', { name: '确认保存 / 更正', exact: true }).click(),
      )
      const memoryId = String(saved.body.memory_id)
      expect(memoryId).toMatch(/^MEM-/)
      await expect(restorePage.getByText('偏好已确认并写入')).toBeVisible()

      const downloadPromise = restorePage.waitForEvent('download', { timeout: 120_000 })
      const exportResponse = await apiAction(
        restorePage,
        { method: 'GET', path: '/api/v1/memory/export' },
        () => restorePage!.getByRole('button', { name: '导出 JSON', exact: true }).click(),
      )
      expect(exportResponse.body.export_version).toBe('p2b-1.0')
      const download = await downloadPromise
      expect(download.suggestedFilename()).toBe('chatbi-memory-charging_ops.json')
      const exported = await readJsonDownload(download)
      expect(exported.export_version).toBe('p2b-1.0')

      const recordButtons = restorePage.locator('.memory-list button')
      let selected = false
      for (let index = 0; index < await recordButtons.count(); index += 1) {
        await recordButtons.nth(index).click()
        if ((await restorePage.locator('.detail-panel').innerText()).includes(memoryId)) {
          selected = true
          break
        }
      }
      expect(selected, `new memory ${memoryId} should be selectable in the UI`).toBeTruthy()
      restorePage.once('dialog', dialog => dialog.accept())
      await apiAction(
        restorePage,
        { method: 'DELETE', path: `/api/v1/memory/records/${memoryId}` },
        () => restorePage!.locator('.detail-panel header button.danger-link').click(),
      )
      await expect(restorePage.getByText('记忆已删除并从召回范围移除')).toBeVisible()
      const verification = await apiAction(
        restorePage,
        { method: 'GET', path: '/api/v1/memory/records' },
        () => restorePage!.evaluate(async () => {
          const response = await fetch('/api/v1/memory/records?scenario_id=charging_ops', {
            headers: { Authorization: `Bearer ${localStorage.getItem('alpha_token')}` },
          })
          if (!response.ok) throw new Error(`memory verification failed: ${response.status}`)
          return response.json()
        }),
      )
      expect(verification.body.records.some((record: any) => record.memory_id === memoryId)).toBeFalsy()
      await capture(restorePage, '07-memory')
      return { memoryId, workingStatus: working.body.status, exportFile: download.suggestedFilename() }
    }, value => ({ memory_id: value.memoryId, final_state: 'DELETED', working_status: value.workingStatus, export_file: value.exportFile }))

    await acceptanceStep('SKILLS-001', 'Skill 场景切换、Registry 刷新和行选择', async () => {
      if (!restorePage) throw new Error('session restore page is unavailable')
      await apiAction(restorePage, { method: 'GET', path: '/api/v1/skills' }, () => navigate(restorePage!, 'Skill 管理'))
      const scenario = restorePage.getByLabel('Skill 场景')
      await apiAction(restorePage, { method: 'GET', path: '/api/v1/skills' }, () => scenario.selectOption('sales_ops'))
      await apiAction(restorePage, { method: 'GET', path: '/api/v1/skills' }, () => scenario.selectOption('charging_ops'))
      await apiAction(restorePage, { method: 'GET', path: '/api/v1/skills' }, () => restorePage!.getByRole('button', { name: '刷新 Registry', exact: true }).click())
      const firstRow = restorePage.locator('.skill-catalog tbody tr').first()
      await expect(firstRow).toBeVisible()
      await firstRow.click()
      await expect(firstRow).toHaveClass(/selected/)
      await expect(restorePage.locator('.skill-detail')).toContainText('输入 Schema')
      const disabled = firstRow.locator('.skill-actions button:disabled')
      if (await disabled.count()) await expectDisabledBoundary(disabled.first())
      await capture(restorePage, '08-skills')
      return await restorePage.locator('.skill-catalog tbody tr').count()
    }, value => ({ registry_rows: value, scenarios: ['sales_ops', 'charging_ops'] }))

    await acceptanceStep('CHATBI-002', '服务端清除旧会话并由 UI 创建隔离新会话', async () => {
      setPage(page, 'AI经营分析')
      const cleared = await apiAction(
        page,
        { method: 'DELETE', path: `/api/v1/chat/sessions/${conversationId}` },
        () => page.getByRole('button', { name: /新会话/ }).click(),
      )
      expect(cleared.body.status).toBe('cleared')
      await expect(page.locator('.chat-history-list')).toContainText('新会话尚未产生分析记录')
      const question = page.getByLabel('经营分析问题')
      expect(salesQuestionWindow).not.toBe('')
      await question.fill(`${salesQuestionWindow}销售收入是多少？`)
      const next = await apiAction(page, { method: 'POST', path: '/api/v1/assistant/query' }, () => page.getByLabel('发送分析问题').click())
      expect(next.body.conversation_id).not.toBe(conversationId)
      expect(next.body.data_query_evidence.status).toBe('completed')
      conversationId = String(next.body.conversation_id)
      await capture(page, '09-chatbi-new-session')
      return conversationId
    }, value => ({ new_conversation_id: value, old_session_status: 'cleared' }))

    await acceptanceStep('KNOWLEDGE-001', '知识检索和唯一文档版本生命周期', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/knowledge/runtime' }, () => navigate(page, '企业知识库'))
      const retrievalCard = page.locator('.knowledge-card.retrieval')
      await retrievalCard.locator('textarea').fill('充电收入如何定义？')
      const retrieval = await apiAction(page, { method: 'POST', path: '/api/v1/knowledge/retrieval/test' }, () => retrievalCard.getByRole('button', { name: '执行受控检索' }).click())
      expect(retrieval.body.citations.length).toBeGreaterThan(0)
      await expect(retrievalCard.locator('.retrieval-result')).toBeVisible()

      const title = `DAY-1 验收知识 ${runKey}`
      const ingestCard = page.locator('.knowledge-card.ingest')
      await expect(ingestCard.locator('select').nth(2).locator('option').first()).toBeAttached()
      await ingestCard.getByRole('textbox').fill(title)
      const ingested = await apiAction(page, { method: 'POST', path: '/api/v1/knowledge/documents/ingest' }, () => ingestCard.getByRole('button', { name: '解析并创建版本' }).click())
      const versionId = String(ingested.body.document_version_id)
      expect(versionId).toMatch(/^kdv-/)
      let row = page.locator('.knowledge-card.versions tbody tr').filter({ hasText: title }).first()
      await expect(row).toContainText('READY', { timeout: 120_000 })
      await apiAction(page, { method: 'POST', path: `/api/v1/knowledge/versions/${versionId}/publish` }, () => row.getByRole('button', { name: '发布', exact: true }).click())
      row = page.locator('.knowledge-card.versions tbody tr').filter({ hasText: title }).first()
      await expect(row).toContainText('PUBLISHED')
      await apiAction(page, { method: 'POST', path: `/api/v1/knowledge/versions/${versionId}/retire` }, () => row.getByRole('button', { name: '撤回', exact: true }).click())
      row = page.locator('.knowledge-card.versions tbody tr').filter({ hasText: title }).first()
      await expect(row).toContainText('RETIRED')
      await apiAction(page, { method: 'GET', path: '/api/v1/knowledge/documents' }, () => page.locator('.knowledge-card.versions').getByRole('button', { name: '刷新', exact: true }).click())
      await expectDisabledBoundary(
        ingestCard.getByRole('button', { name: '本地文件上传未开放' }),
        /浏览器任意文件上传未开放/,
      )
      await capture(page, '10-knowledge')
      return { versionId, title, citations: retrieval.body.citations.length }
    }, value => ({ document_version_id: value.versionId, title: value.title, final_state: 'RETIRED', citations: value.citations }))

    await acceptanceStep('MAPPING-001', '数据接入试运行、质量、审批和发布闭环', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/data-integration/overview' }, () => navigate(page, '数据接入与字段映射'))
      await expectDisabledBoundary(page.locator('.mapping-flowbar').getByRole('button', { name: /自动推荐未开放/ }), '自动推荐尚未实现')
      const previewToggle = page.locator('.mapping-preview-panel input[type="checkbox"]')
      const originalPreview = await previewToggle.isChecked()
      await previewToggle.click()
      expect(await previewToggle.isChecked()).toBe(!originalPreview)
      await apiAction(page, { method: 'GET', path: '/api/v1/data-integration/overview' }, () => page.getByRole('button', { name: /重新预览/ }).click())

      const flow = page.locator('.mapping-flowbar')
      const connection = await apiAction(page, { method: 'POST', path: '/api/v1/data-integration/sources/platform-postgresql/test' }, () => flow.getByRole('button', { name: /测试连接/ }).click())
      expect(connection.body.latency_ms).toBeGreaterThanOrEqual(0)
      const run = await apiAction(page, { method: 'POST', path: /\/api\/v1\/data-integration\/datasets\/[^/]+\/run$/ }, () => flow.getByRole('button', { name: /试运行/ }).click())
      const ingestionRunId = String(run.body.run_id)
      expect(ingestionRunId.length).toBeGreaterThan(8)
      const advance = flow.locator('button.primary')
      await expect(advance).toContainText('执行质量校验', { timeout: 120_000 })
      await apiAction(page, { method: 'POST', path: `/runs/${ingestionRunId}/quality` }, () => advance.click())
      await expect(advance).toContainText('提交审批', { timeout: 120_000 })
      await apiAction(page, { method: 'POST', path: `/runs/${ingestionRunId}/submit` }, () => advance.click())
      await expect(advance).toContainText('审批通过', { timeout: 120_000 })
      page.once('dialog', dialog => dialog.accept())
      await apiAction(page, { method: 'POST', path: `/runs/${ingestionRunId}/review` }, () => advance.click())
      await expect(advance).toContainText('发布数据集', { timeout: 120_000 })
      const published = await apiAction(page, { method: 'POST', path: `/runs/${ingestionRunId}/publish` }, () => advance.click())
      await expect(advance).toContainText('已发布', { timeout: 120_000 })
      return { ingestionRunId, releaseVersion: published.body.release_version }
    }, value => ({ run_id: value.ingestionRunId, release_version: value.releaseVersion, final_state: 'published' }))

    await acceptanceStep('MAPPING-002', '平台 DatasetVersion 13 步真实闭环并回滚', async () => {
      const steps = page.locator('.platform-release-steps')
      await apiAction(page, { method: 'POST', path: '/api/v1/platform/foundation/sources' }, () => steps.getByRole('button', { name: /创建数据源/ }).click())
      await apiAction(page, { method: 'POST', path: '/api/v1/data-integration/sources/platform-postgresql/test' }, () => steps.getByRole('button', { name: /测试连接/ }).click())
      await apiAction(page, { method: 'GET', path: '/api/v1/platform/foundation/sources/platform-postgresql/discover' }, () => steps.getByRole('button', { name: /发现元数据/ }).click())
      await apiAction(page, { method: 'GET', path: '/api/v1/data-integration/overview' }, () => steps.getByRole('button', { name: /数据预览/ }).click())
      await steps.getByRole('button', { name: /字段映射/ }).click()
      await expect(page.locator('.mapping-feedback')).toContainText('字段映射已从数据库读取')
      await steps.getByRole('button', { name: /质量检查/ }).click()
      await expect(page.locator('.mapping-feedback')).toContainText('质量检查状态')
      const created = await apiAction(page, { method: 'POST', path: /\/api\/v1\/platform\/foundation\/datasets\/[^/]+\/versions$/ }, () => steps.getByRole('button', { name: /创建 DatasetVersion/ }).click())
      const versionId = String(created.body.dataset_version_id)
      expect(versionId.length).toBeGreaterThan(8)
      await apiAction(page, { method: 'POST', path: `/api/v1/platform/foundation/versions/${versionId}/submit` }, () => steps.getByRole('button', { name: /提交审核/ }).click())
      page.once('dialog', dialog => dialog.accept())
      await apiAction(page, { method: 'POST', path: `/api/v1/platform/foundation/versions/${versionId}/approve` }, () => steps.getByRole('button', { name: /批准/ }).click())
      await apiAction(page, { method: 'POST', path: `/api/v1/platform/foundation/versions/${versionId}/publish` }, () => steps.getByRole('button', { name: /发布/ }).click())
      await apiAction(page, { method: 'POST', path: `/api/v1/platform/foundation/versions/${versionId}/activate` }, () => steps.getByRole('button', { name: /激活/ }).click())
      await apiAction(page, { method: 'GET', path: '/api/v1/platform/foundation' }, () => steps.getByRole('button', { name: /当前 ACTIVE/ }).click())
      page.once('dialog', dialog => dialog.accept())
      const rollback = await apiAction(page, { method: 'POST', path: /\/api\/v1\/platform\/foundation\/datasets\/[^/]+\/rollback$/ }, () => steps.getByRole('button', { name: /回滚/ }).click())
      const verified = await apiAction(page, { method: 'GET', path: '/api/v1/platform/foundation' }, () => steps.getByRole('button', { name: /当前 ACTIVE/ }).click())
      expect(verified.body.activation.dataset_version_id).not.toBe(versionId)
      expect(verified.body.rollbacks.length).toBeGreaterThan(0)
      await capture(page, '11-mapping')
      return { versionId, rollbackId: rollback.body.rollback_record_id ?? verified.body.rollbacks.at(-1)?.rollback_record_id }
    }, value => ({ created_dataset_version_id: value.versionId, rollback_record_id: value.rollbackId, final_state: 'rolled_back' }))

    await acceptanceStep('GOVERNANCE-001', '治理八页签、运行/P4/P5 刷新与禁用边界', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/governance/snapshot' }, () => navigate(page, '治理与生产就绪'))
      const tabs = ['治理总览', '身份与授权', '凭据引用', 'Legal Hold 与保留', '审计与告警', '发布与运行', 'P4 预生产与 RC', 'P5 生产验收']
      for (const tab of tabs) {
        await page.getByRole('button', { name: tab, exact: true }).click()
        await expect(page.locator('.gov-tabs button.active')).toHaveText(tab)
        await expect(page.locator('.gov-state.denied, .p4-empty.denied, .p5-empty.blocked')).toHaveCount(0)
        if (tab === '凭据引用') {
          await expectDisabledBoundary(page.getByRole('button', { name: '创建由管理 API 控制' }), /受控管理 API/)
        }
        if (tab === '审计与告警') {
          await expectDisabledBoundary(page.getByRole('button', { name: '外部通知未开放' }), 'P3 不自动发送外部消息')
        }
        if (tab === '发布与运行') {
          await expectDisabledBoundary(page.getByRole('button', { name: '生产发布已禁用' }), /阻断门禁/)
          await apiAction(page, { method: 'GET', path: '/api/v1/governance/snapshot' }, () => page.getByRole('button', { name: '刷新运行状态' }).click())
        }
        if (tab === 'P4 预生产与 RC') {
          await expect(page.getByTestId('preproduction-page')).toBeVisible({ timeout: 120_000 })
          await apiAction(page, { method: 'GET', path: '/api/v1/preproduction/snapshot' }, () => page.locator('.p4-truth button').click())
        }
        if (tab === 'P5 生产验收') {
          await expect(page.getByTestId('production-acceptance-page')).toBeVisible({ timeout: 120_000 })
          await apiAction(page, { method: 'GET', path: '/api/v1/production-acceptance/snapshot' }, () => page.locator('.p5-truth button').click())
        }
      }
      await capture(page, '12-governance')
      return tabs.length
    }, value => ({ tab_count: value, refreshes: ['runtime', 'P4', 'P5'] }))

    await acceptanceStep('P6-ALERT-001', '预警规则和全状态生命周期最终闭环到 CLOSED', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/alerts' }, () => navigate(page, '经营预警'))
      const generated = await apiAction(page, { method: 'POST', path: '/api/v1/alerts/generate' }, () => page.getByRole('button', { name: '运行受控预警规则' }).click())
      expect(generated.body.created || generated.body.deduplicated).toBeTruthy()
      const detail = page.locator('.p6-panel.detail')
      await detail.getByLabel('处置理由').fill(`DAY-1 处置 ${runKey}`)
      await detail.getByLabel('处理人').fill(`analyst-${runKey.slice(-6)}`)
      const status = detail.locator('header .p6-status')
      const transitions: Record<string, { label: string; action: string; next: string }> = {
        OPEN: { label: '分派', action: 'assign', next: 'ASSIGNED' },
        REOPENED: { label: '重新分派', action: 'assign', next: 'ASSIGNED' },
        ASSIGNED: { label: '确认', action: 'acknowledge', next: 'ACKNOWLEDGED' },
        ACKNOWLEDGED: { label: '开始处理', action: 'in-progress', next: 'IN_PROGRESS' },
        IN_PROGRESS: { label: '解决', action: 'resolve', next: 'RESOLVED' },
        RESOLVED: { label: '验证', action: 'verify', next: 'VERIFIED' },
        VERIFIED: { label: '关闭', action: 'close', next: 'CLOSED' },
        CLOSED: { label: '重开', action: 'reopen', next: 'REOPENED' },
      }
      let exercisedReopen = false
      for (let attempt = 0; attempt < 20; attempt += 1) {
        const current = (await status.innerText()).trim()
        if (current === 'CLOSED' && exercisedReopen) break
        const transition = transitions[current]
        if (!transition) throw new Error(`unsupported alert state: ${current}`)
        if (current === 'CLOSED') exercisedReopen = true
        await apiAction(
          page,
          { method: 'POST', path: new RegExp(`/api/v1/alerts/[^/]+/${transition.action}$`) },
          () => detail.getByRole('button', { name: transition.label, exact: true }).click(),
        )
        await expect(status).toHaveText(transition.next, { timeout: 120_000 })
      }
      await expect(status).toHaveText('CLOSED')
      expect(exercisedReopen).toBeTruthy()
      await expect(detail.locator('.p6-timeline > div').first()).toBeVisible()
      await capture(page, '13-alerts')
      return { alertId: generated.body.alert?.alert_id, finalState: 'CLOSED' }
    }, value => ({ alert_id: value.alertId, final_state: value.finalState, reopen_exercised: true }))

    await acceptanceStep('P6-REPORT-001', '报告创建、版本、审核、发布、证据与归档', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/reports' }, () => navigate(page, '经营报告'))
      const created = await apiAction(page, { method: 'POST', path: /^\/api\/v1\/reports$/ }, () => page.getByRole('button', { name: '创建月报草稿' }).click())
      const reportId = String(created.body.report_id)
      expect(reportId.length).toBeGreaterThan(8)
      const actions = page.locator('.p6-panel.detail .p6-actions')
      await apiAction(page, { method: 'POST', path: `/api/v1/reports/${reportId}/versions` }, () => actions.getByRole('button', { name: '新版本', exact: true }).click())
      await apiAction(page, { method: 'POST', path: `/api/v1/reports/${reportId}/submit-review` }, () => actions.getByRole('button', { name: '提交审核', exact: true }).click())
      await apiAction(page, { method: 'POST', path: `/api/v1/reports/${reportId}/approve` }, () => actions.getByRole('button', { name: '批准', exact: true }).click())
      await apiAction(page, { method: 'POST', path: `/api/v1/reports/${reportId}/publish` }, () => actions.getByRole('button', { name: '发布', exact: true }).click())
      await expect(page.getByText('Evidence Snapshot 已冻结')).toBeVisible({ timeout: 120_000 })
      await apiAction(page, { method: 'POST', path: `/api/v1/reports/${reportId}/archive` }, () => actions.getByRole('button', { name: '归档', exact: true }).click())
      await expect(page.locator('.p6-panel.detail header .p6-status')).toHaveText('ARCHIVED')
      await capture(page, '14-reports')
      return reportId
    }, value => ({ report_id: value, final_state: 'ARCHIVED', evidence_snapshot: true }))

    await acceptanceStep('P6-METRIC-001', '指标新版本、保存、影响分析、审核和发布', async () => {
      await apiAction(page, { method: 'GET', path: '/api/v1/metrics/governance' }, () => navigate(page, '指标与场景管理'))
      const publishedRow = page.locator('.p6-panel.list tbody tr').filter({ hasText: 'PUBLISHED' }).first()
      await expect(publishedRow).toBeVisible()
      await publishedRow.click()
      const actions = page.locator('.p6-panel.detail .p6-actions')
      const drafted = await apiAction(page, { method: 'POST', path: '/api/v1/metrics/governance/drafts' }, () => actions.getByRole('button', { name: '新建版本', exact: true }).click())
      const versionId = String(drafted.body.metric_version_id)
      expect(versionId.length).toBeGreaterThan(8)
      const reason = page.locator('.p6-panel.detail').getByLabel('变更理由')
      await reason.fill(`DAY-1 指标验收 ${runKey}`)
      const formula = page.locator('.p6-panel.detail').getByLabel('公式')
      await expect(formula).toBeEnabled()
      await formula.fill(await formula.inputValue())
      await apiAction(page, { method: 'PATCH', path: `/api/v1/metrics/governance/versions/${versionId}` }, () => actions.getByRole('button', { name: '保存草稿', exact: true }).click())
      await apiAction(page, { method: 'POST', path: `/api/v1/metrics/governance/versions/${versionId}/impact-analysis` }, () => actions.getByRole('button', { name: '影响分析', exact: true }).click())
      await expect(page.locator('.p6-impact')).toBeVisible()
      await apiAction(page, { method: 'POST', path: `/api/v1/metrics/governance/versions/${versionId}/submit-review` }, () => actions.getByRole('button', { name: '提交审核', exact: true }).click())
      await apiAction(page, { method: 'POST', path: `/api/v1/metrics/governance/versions/${versionId}/approve` }, () => actions.getByRole('button', { name: '批准', exact: true }).click())
      await apiAction(page, { method: 'POST', path: `/api/v1/metrics/governance/versions/${versionId}/publish` }, () => actions.getByRole('button', { name: '发布', exact: true }).click())
      await expect(page.locator('.p6-panel.detail header .p6-status')).toHaveText('PUBLISHED')
      await capture(page, '15-metrics')
      return versionId
    }, value => ({ metric_version_id: value, final_state: 'PUBLISHED', unique_reason: runKey }))

    await acceptanceStep('AUTH-004', '真实 OIDC logout 清除当前页及恢复页会话', async () => {
      setPage(page, 'LOGOUT')
      await apiAction(page, { method: 'POST', path: '/api/v1/auth/oidc/logout' }, () => page.locator('button.profile').click())
      await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible({ timeout: 120_000 })
      expect(await page.evaluate(() => localStorage.getItem('alpha_token'))).toBeNull()
      if (!restorePage) throw new Error('session restore page is unavailable')
      setPage(restorePage, 'LOGOUT-RESTORE-CHECK')
      await restorePage.reload()
      await expect(restorePage.getByRole('heading', { name: '欢迎登录' })).toBeVisible({ timeout: 120_000 })
      expect(await restorePage.evaluate(() => localStorage.getItem('alpha_token'))).toBeNull()
      await capture(page, '16-logout')
    })

    await acceptanceStep('BOUNDARY-001', '登录后全局禁用边界未被破坏', async () => {
      await expect(page.getByTestId('oidc-login')).toBeEnabled()
      expect(evidence.steps.filter(item => item.status === 'FAIL')).toEqual([])
    }, undefined, true)

    expect(evidence.console_errors).toEqual([])
    expect(evidence.page_errors).toEqual([])
    expect(evidence.request_failures).toEqual([])
    expect(evidence.api_responses.filter(item => item.status >= 400)).toEqual([])
    completed = true
  } catch (error) {
    evidence.failure = error instanceof Error ? error.stack || error.message : String(error)
    throw error
  } finally {
    evidence.status = completed ? 'PASS' : 'FAIL'
    evidence.finished_at = isoNow()
    try {
      if (!page.isClosed()) await capture(page, completed ? '99-final-pass' : '99-final-failure')
    } catch (error) {
      evidence.failure = `${evidence.failure || ''}\nfinal screenshot: ${error instanceof Error ? error.message : String(error)}`.trim()
    }
    writeEvidence(evidence)
  }
})
