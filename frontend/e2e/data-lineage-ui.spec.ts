import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('所有业务页面仅使用统一数据状态区并保持正式 API 链路', async ({ page }) => {
  const contextResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/dashboard/context') && response.ok(),
  )
  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  const context = await contextResponse
  const contextBody = await context.json()

  expect(contextBody.default_time_range).toEqual({
    start: '2026-01-01',
    end_exclusive: '2026-07-01',
  })
  expect(contextBody.metric_count).toBe(15)

  const status = page.locator('.global-data-status')
  await expect(status).toBeVisible({ timeout: 90_000 })
  await expect(status).toContainText('模拟数据')
  await expect(status).toContainText('来源：平台数据库')
  await expect(status).toContainText(/run_id：DASH-/)

  for (const pageName of [
    '经营工作台',
    '收入与订单',
    '毛利与成本',
    '场站经营',
    '设备健康',
    '经营预警',
    'AI经营分析',
    '经营报告',
    '企业知识库',
    '数据接入与字段映射',
    '指标与场景管理',
  ]) {
    await page.getByRole('button', { name: pageName }).click()
    await expect(page.getByRole('heading', { name: pageName, exact: true })).toBeVisible()
    await expect(status).toBeVisible()
    await expect(page.getByText('模拟数据', { exact: true })).toHaveCount(1)
  }

  await expect(page.locator(
    '.truth-row,.revenue-truth,.margin-truth,.station-truth,.device-data-note,.alert-truth,.report-truth,.knowledge-truth,.mapping-truth,.metrics-truth',
  )).toHaveCount(0)
})
