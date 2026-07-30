import { expect, test } from '@playwright/test'

const viewport = { width: 1440, height: 900 }
test.use({ viewport })

test('capture current Alpha product pages without changing business data', async ({ page }) => {
  const capturedAt = new Date().toISOString()
  const screenshots: Array<{ page: string; file: string }> = []

  async function capture(pageName: string, file: string) {
    await page.screenshot({ fullPage: true })
    screenshots.push({ page: pageName, file })
  }

  await page.goto('/')
  await expect(page.getByText('新能源经营分析智能平台', { exact: true })).toBeVisible()
  await capture('登录页', '01-login.png')

  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '功能总览', exact: true })).toBeVisible()
  await expect(page.getByText('来源：平台数据库')).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible()
  await capture('功能总览', '02-overview.png')

  for (const [pageName, file] of [
    ['收入与订单', '03-revenue.png'],
    ['毛利与成本', '04-gross-profit.png'],
    ['场站经营', '05-stations.png'],
    ['设备健康', '06-devices.png'],
  ] as const) {
    await page.getByRole('button', { name: pageName }).click()
    await expect(page.getByRole('heading', { name: pageName, exact: true })).toBeVisible()
    await expect(page.getByText('模拟数据', { exact: true }).first()).toBeVisible()
    await capture(pageName, file)
  }

  await page.getByRole('button', { name: '经营预警' }).click()
  await expect(page.getByRole('heading', { name: '经营预警', exact: true })).toBeVisible()
  await expect(page.getByText(/run_id：DIAG-/)).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('关联因素说明，不构成因果结论')).toBeVisible()
  await capture('经营预警', '07-diagnostics.png')

  await page.getByRole('button', { name: 'AI经营分析' }).click()
  await expect(page.getByRole('heading', { name: 'AI经营分析', exact: true })).toBeVisible()
  await expect(page.locator('.chat-evidence-panel code')).toContainText('CHAT-', { timeout: 90_000 })
  await expect(page.getByText('Query Guard：passed')).toBeVisible()
  await expect(page.getByText('Answer Guard：passed')).toBeVisible()
  await capture('AI经营分析 / ChatBI', '08-chatbi.png')

  const reportResponse = page.waitForResponse(
    item => item.url().includes('/api/v1/reports/draft') && item.ok(),
  )
  await page.getByRole('button', { name: '经营报告' }).click()
  await reportResponse
  await expect(page.locator('.report-truth')).toContainText('run_id：', { timeout: 90_000 })
  await expect(page.getByText(/报告只生成可审核草稿/)).toBeVisible()
  await capture('经营报告草稿', '09-report.png')

  const manifest = {
    captured_at: capturedAt,
    viewport,
    base_url: 'http://127.0.0.1:8080',
    data_classification: 'fixed_seed_simulated',
    data_source_label_verified: 'platform_database',
    screenshots,
    unavailable_pages: [
      {
        page: '系统或审计页面',
        reason: '当前 Alpha 前端没有系统或审计导航/路由；后端审计能力存在，但无对应页面。',
      },
    ],
  }
  expect(manifest.screenshots).toHaveLength(9)
  expect(manifest.data_classification).toBe('fixed_seed_simulated')
})
