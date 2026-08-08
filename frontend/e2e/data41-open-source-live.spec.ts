import { expect, test } from '@playwright/test'

const oidcPassword = process.env.P4_OIDC_PASSWORD
const acceptanceOrigin = new URL(process.env.PLAYWRIGHT_BASE_URL ?? 'https://p5b.localhost:8446').origin

test.use({ viewport: { width: 1600, height: 900 } })
test.skip(!oidcPassword, 'DATA-4.1 runtime-only OIDC password was not provided')

async function login(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByTestId('oidc-login').click()
  await page.locator('#username').fill('p4.analyst')
  await page.locator('#password').fill(oidcPassword!)
  const callback = page.waitForResponse(
    response => response.url().includes('/api/v1/auth/oidc/callback'),
  )
  await page.locator('#kc-login').click()
  expect((await callback).ok()).toBeTruthy()
  await page.waitForURL(url => url.origin === acceptanceOrigin && url.pathname === '/')
}

test('DATA-4.1 public source flows through authenticated API, UI and guarded ChatBI', async ({ page }) => {
  const contextResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/dashboard/context') && response.ok(),
  )
  await login(page)
  const context = await (await contextResponse).json()

  expect(context.metric_count).toBe(15)
  expect(context.metadata.data_classification).toBe('open_source_real_data')
  expect(context.metadata.source).toContain('ACN-Data')
  expect(context.available_time_range).toEqual({
    start: '2020-05-09',
    end_exclusive: '2020-06-10',
  })

  const status = page.locator('.global-data-status')
  await expect(status).toContainText('公开数据样本')
  await expect(status).toContainText('ACN-Data via ORNL')
  await expect(status).toContainText('2020-05-09 至 2020-06-09')

  const catalog = await page.evaluate(async () => {
    const token = localStorage.getItem('alpha_token')
    const response = await fetch('/api/v1/data/open-source/schema-catalog', {
      headers: { Authorization: `Bearer ${token}` },
    })
    return response.json()
  })
  expect(catalog.catalog_version).toBe('data41-schema-catalog-v2')
  expect(catalog.statistics).toEqual({ table_count: 13, field_count: 141, relation_count: 19 })
  expect(catalog.sqlbot_enabled).toBe(false)

  await page.getByRole('button', { name: '收入与订单' }).click()
  await expect(page.getByRole('heading', { name: '收入与订单', exact: true })).toBeVisible()
  await expect(status).toContainText('公开数据样本')

  await page.getByRole('button', { name: '经营预警' }).click()
  await expect(page.getByRole('heading', { name: '经营预警', exact: true })).toBeVisible()
  await expect(status).toContainText('公开数据样本')

  const initialAssistantResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/assistant/query') && response.ok(),
  )
  await page.getByRole('button', { name: 'AI经营分析' }).click()
  await expect(page.getByRole('heading', { name: 'AI经营分析', exact: true })).toBeVisible()
  await expect(page.getByLabel('当前业务场景')).toHaveValue('charging_ops')
  await initialAssistantResponse
  const question = page.getByLabel('经营分析问题')
  const explicitQuestion = '2020年5月9日至2020年6月9日充电收入是多少'
  await question.fill(explicitQuestion)
  const assistantResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/assistant/query')
      && response.ok()
      && response.request().postDataJSON()?.question === explicitQuestion,
  )
  await page.getByLabel('发送分析问题').click()
  const assistant = await (await assistantResponse).json()

  expect(assistant.data_classification).toBe('open_source_real_data')
  expect(assistant.data_query_evidence.status).toBe('completed')
  expect(assistant.data_query_evidence.evidence.query_guard).toBe('passed')
  expect(assistant.data_query_evidence.evidence.answer_guard.status).toBe('passed')
  expect(assistant.data_query_evidence.query_result.dataset_version).toBe('2')
  expect(assistant.data_query_evidence.query_result.rows[0].charging_revenue).toBe(46.12)
  await expect(page.locator('.chat-conclusion')).toContainText('46.12')
  await expect(page.locator('.chat-evidence-panel')).toContainText('Query Guard：passed')
  await expect(page.locator('.chat-evidence-panel')).toContainText('Answer Guard：passed')
  await expect(status).toContainText('公开数据样本')
})
