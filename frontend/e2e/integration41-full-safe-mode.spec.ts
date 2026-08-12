import { expect, test } from '@playwright/test'

const oidcPassword = process.env.P4_OIDC_PASSWORD
const acceptanceOrigin = new URL(
  process.env.PLAYWRIGHT_BASE_URL ?? 'https://p5b.localhost:8446',
).origin

test.use({ viewport: { width: 1600, height: 960 } })
test.skip(!oidcPassword, 'Full Integration runtime-only OIDC password was not provided')
test.setTimeout(600_000)

async function login(page: import('@playwright/test').Page) {
  await page.goto('/')
  await expect(page.getByTestId('oidc-login')).toBeEnabled()
  await Promise.all([
    page.waitForURL(/\/protocol\/openid-connect\/auth/),
    page.getByTestId('oidc-login').click(),
  ])
  await page.locator('#username').fill('p4.analyst')
  await page.locator('#password').fill(oidcPassword!)
  const callback = page.waitForResponse(
    response => response.url().includes('/api/v1/auth/oidc/callback'),
  )
  await page.locator('#kc-login').click()
  expect((await callback).ok()).toBeTruthy()
  await page.waitForURL(url => url.origin === acceptanceOrigin && url.pathname === '/')
}

test('Full Integration safe mode preserves primary user journeys', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  await login(page)

  await expect(page.getByRole('heading', { name: '功能总览' })).toBeVisible({ timeout: 120_000 })
  const dataStatus = page.locator('.global-data-status')
  await expect(dataStatus).toContainText('经营数据状态已核验')
  await expect(dataStatus).toContainText(/公开数据样本|模拟数据/)
  await expect(dataStatus).toContainText('来源：')
  await expect(dataStatus).toContainText('统计期间：')
  await expect(dataStatus).toContainText('分析 run_id：')
  const ordinaryBusinessText = await page.locator('.product-main').innerText()
  expect(ordinaryBusinessText).not.toMatch(/数据性质：|data_classification|source_type|fixture|fixed[- ]?seed/i)

  await page.getByRole('button', { name: '经营工作台' }).click()
  await expect(page.getByRole('heading', { name: '经营工作台' })).toBeVisible()
  await expect(page.locator('.notice.error')).toHaveCount(0)

  await page.getByRole('button', { name: 'AI经营分析' }).click()
  await expect(page.getByRole('heading', { name: 'AI经营分析' })).toBeVisible()
  const scenario = page.getByLabel('当前业务场景')
  await expect(scenario).toBeVisible()
  const salesInitialResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/assistant/query')
      && response.request().postDataJSON()?.scenario_id === 'sales_ops',
  )
  await scenario.selectOption('sales_ops')
  const salesInitialHttpResponse = await salesInitialResponse
  const salesInitial = await salesInitialHttpResponse.json()
  expect(salesInitialHttpResponse.status(), JSON.stringify(salesInitial)).toBe(200)
  const question = page.getByLabel('经营分析问题')
  await expect(page.getByLabel('发送分析问题')).toBeEnabled({ timeout: 120_000 })
  await expect(question).toHaveValue(/销售收入/)
  const salesStart = String(salesInitial.data_query_evidence.evidence.data_time_range.start)
  const salesEndExclusive = String(salesInitial.data_query_evidence.evidence.data_time_range.end_exclusive)
  const salesEnd = new Date(`${salesEndExclusive}T00:00:00Z`)
  salesEnd.setUTCDate(salesEnd.getUTCDate() - 1)
  const salesQuestion = `${salesStart}至${salesEnd.toISOString().slice(0, 10)}销售收入、订单数和销售毛利率是多少？`
  await question.fill(salesQuestion)
  const assistantResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/assistant/query')
      && response.request().postDataJSON()?.question === salesQuestion,
  )
  await page.getByLabel('发送分析问题').click()
  const assistantHttpResponse = await assistantResponse
  const answer = await assistantHttpResponse.json()
  expect(assistantHttpResponse.status(), JSON.stringify(answer)).toBe(200)
  expect(answer.data_query_evidence.engine).toBe('deterministic')
  expect(answer.data_query_evidence.engine_routing.mode).toBe('DETERMINISTIC_ONLY')
  expect(answer.data_query_evidence.engine_routing.route_decision).toBe('DETERMINISTIC_ONLY')
  expect(answer.data_query_evidence.evidence.query_guard).toBe('passed')
  expect(answer.data_query_evidence.evidence.answer_guard.status).toBe('passed')
  await expect(page.locator('.chat-runtime-strip')).toContainText('deterministic')
  await expect(page.locator('.chat-runtime-strip')).toContainText('DETERMINISTIC_ONLY')

  await question.fill('销售收入如何定义？')
  const knowledgeResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/assistant/query')
      && response.ok()
      && response.request().postDataJSON()?.question === '销售收入如何定义？',
  )
  await page.getByLabel('发送分析问题').click()
  const knowledge = await (await knowledgeResponse).json()
  expect(knowledge.knowledge_retrieval_evidence.answer_guard_status).toBe('PASSED')
  expect(knowledge.knowledge_retrieval_evidence.citation_count).toBeGreaterThan(0)

  await page.getByRole('button', { name: '企业知识库' }).click()
  await expect(page.getByRole('heading', { name: '企业知识库' })).toBeVisible()
  await expect(page.getByText('READY', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('REGISTERED_NOT_ELIGIBLE', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '记忆与偏好' }).click()
  await expect(page.getByRole('heading', { name: '记忆与偏好' })).toBeVisible()
  await expect(page.getByText('记忆状态已核验')).toBeVisible()

  await page.getByRole('button', { name: '经营预警' }).click()
  await expect(page.getByTestId('p6-alert-center')).toBeVisible()
  await page.getByRole('button', { name: '经营报告' }).click()
  await expect(page.getByTestId('p6-report-center')).toBeVisible()
  await page.getByRole('button', { name: '指标与场景管理' }).click()
  await expect(page.getByTestId('p6-metric-center')).toBeVisible()

  expect(consoleErrors).toEqual([])
})
