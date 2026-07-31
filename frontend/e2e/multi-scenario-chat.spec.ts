import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('自有 ChatBI UI 切换双场景并展示版本引擎证据', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (
      message.type() === 'error'
      && !message.text().includes('422 (Unprocessable Entity)')
    ) consoleErrors.push(message.text())
  })

  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: 'AI经营分析' }).click()

  const scenario = page.getByLabel('当前业务场景')
  await expect(scenario).toBeVisible()
  await scenario.selectOption('sales_ops')
  await expect(page.getByLabel('经营分析问题')).toHaveValue(
    '2026年6月销售收入、订单数和销售毛利率是多少？',
  )
  await expect(page.locator('.chat-runtime-strip')).toContainText(
    'sales_ops',
    { timeout: 120_000 },
  )
  await expect(page.locator('.chat-runtime-strip')).toContainText(
    'deterministic',
  )
  await expect(page.locator('.chat-runtime-strip')).toContainText('SHADOW')
  await expect(page.locator('.chat-metric-grid.sales>article')).toHaveCount(3)
  await expect(page.locator('.chat-conclusion')).not.toContainText('模拟数据')
  await expect(page.locator('.chat-evidence-panel')).toContainText(
    'SQLBOT_DISABLED',
  )
  await expect(page.locator('.chat-evidence-panel code')).toContainText(
    'SALES-',
  )

  await page.getByRole('button', { name: '有帮助' }).click()
  await expect(page.getByText('反馈已记录到审计日志')).toBeVisible()

  await scenario.selectOption('charging_ops')
  await expect(page.getByLabel('经营分析问题')).toHaveValue(
    '2026年6月充电收入环比变化的原因？',
  )
  await expect(page.locator('.chat-runtime-strip')).toContainText(
    'charging_ops',
    { timeout: 120_000 },
  )

  await scenario.selectOption('sales_ops')
  const question = page.getByLabel('经营分析问题')
  await question.fill('2026年6月表现如何？')
  await page.getByLabel('发送分析问题').click()
  await expect(page.locator('.notice.error')).toContainText(
    'METRIC_AMBIGUOUS',
  )
  await expect(page.locator('iframe')).toHaveCount(0)
  expect(consoleErrors).toEqual([])
})
