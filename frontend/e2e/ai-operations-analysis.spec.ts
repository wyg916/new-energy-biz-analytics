import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('AI经营分析在100%缩放下完整一屏并展示可信ChatBI证据', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: 'AI经营分析' }).click()

  await expect(page.getByRole('heading', { name: 'AI经营分析', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'AI结论' })).toBeVisible()
  await expect(page.getByLabel('经营分析问题')).toHaveValue('2026年6月充电收入环比变化的原因？')
  await expect(page.locator('.chat-evidence-panel code')).toContainText('CHAT-', { timeout: 120_000 })
  await expect(page.getByText('simulated', { exact: true })).toBeVisible()
  await expect(page.getByText('Query Guard：passed')).toBeVisible()
  await expect(page.getByText('Answer Guard：passed')).toBeVisible()
  await expect(page.locator('.chat-conclusion')).toContainText('全部授权区域')
  await expect(page.locator('.chat-metric-grid>article')).toHaveCount(4)
  await expect(page.locator('.chat-trend circle')).toHaveCount(6)
  await expect(page.locator('.chat-driver-list>div')).toHaveCount(3)

  const fit = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
    pageBottom: document.querySelector('.ai-analysis-page')?.getBoundingClientRect().bottom ?? 0,
  }))
  expect(fit.scrollHeight).toBeLessThanOrEqual(fit.viewportHeight)
  expect(fit.pageBottom).toBeLessThanOrEqual(fit.viewportHeight)

  await page.screenshot({ fullPage: true })
  expect(consoleErrors).toEqual([])
})
