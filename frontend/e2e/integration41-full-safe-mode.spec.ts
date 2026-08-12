import { expect, test } from '@playwright/test'

const oidcPassword = process.env.P4_OIDC_PASSWORD
const acceptanceOrigin = new URL(
  process.env.PLAYWRIGHT_BASE_URL ?? 'https://p5b.localhost:8446',
).origin

test.use({ viewport: { width: 1600, height: 960 } })
test.skip(!oidcPassword, 'Full Integration runtime-only OIDC password was not provided')

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
  await expect(dataStatus).toContainText('分析 run_id：')
  await expect(dataStatus).not.toContainText(/模拟数据|虚拟数据|真实数据|派生数据|公开数据|数据来源|source_type|data_classification|fixture|seed/i)

  await page.getByRole('button', { name: '经营工作台' }).click()
  await expect(page.getByRole('heading', { name: '经营工作台' })).toBeVisible()
  await expect(page.locator('.notice.error')).toHaveCount(0)

  await page.getByRole('button', { name: 'AI经营分析' }).click()
  await expect(page.getByRole('heading', { name: 'AI经营分析' })).toBeVisible()
  const scenario = page.getByLabel('当前业务场景')
  await expect(scenario).toBeVisible()
  await scenario.selectOption('sales_ops')
  const question = page.getByLabel('经营分析问题')
  await question.fill('2011年11月销售收入、订单数和销售毛利率是多少？')
  const assistantResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/assistant/query')
      && response.ok()
      && response.request().postDataJSON()?.question.includes('2011年11月'),
  )
  await page.getByLabel('发送分析问题').click()
  const answer = await (await assistantResponse).json()
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
