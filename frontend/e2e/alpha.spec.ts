import { expect, test } from '@playwright/test'

test('product alpha core journey uses live backend data', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await page.goto('/')
  await expect(page.getByText('新能源经营分析智能平台', { exact: true })).toBeVisible()
  await page.screenshot({ fullPage: true })
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '功能总览', exact: true })).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('来源：平台数据库')).toBeVisible()
  await page.screenshot({ fullPage: true })

  await page.getByRole('button', { name: 'AI经营分析' }).click()
  await expect(page.getByRole('heading', { name: 'AI经营分析', exact: true })).toBeVisible()
  await expect(page.locator('.chat-evidence-panel code')).toContainText('CHAT-', { timeout: 90_000 })
  await expect(page.getByText('Query Guard：passed')).toBeVisible()
  await expect(page.getByText('Answer Guard：passed')).toBeVisible()
  await page.screenshot({ fullPage: true })

  await page.getByRole('button', { name: '经营预警' }).click()
  await expect(page.getByRole('heading', { name: '经营预警', exact: true })).toBeVisible()
  await expect(page.getByText(/run_id：DIAG-/)).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('关联因素说明，不构成因果结论')).toBeVisible()
  await page.screenshot({ fullPage: true })

  const reportResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/reports/draft') && response.ok(),
  )
  await page.getByRole('button', { name: '经营报告' }).click()
  await reportResponse
  await expect(page.getByRole('heading', { name: '经营报告', exact: true })).toBeVisible()
  await expect(page.locator('.report-truth')).toContainText('run_id：', { timeout: 90_000 })
  await expect(page.getByText(/报告只生成可审核草稿/)).toBeVisible()
  await page.screenshot({ fullPage: true })
  expect(consoleErrors).toEqual([])
})
