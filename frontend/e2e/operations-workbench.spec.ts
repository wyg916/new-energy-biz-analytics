import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('经营工作台在100%缩放下完整一屏并使用后端经营数据', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '经营工作台' }).click()

  await expect(page.getByRole('heading', { name: '经营工作台', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'AI经营摘要' })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText('342.41', { exact: true })).toBeVisible()
  await expect(page.getByText('120.33', { exact: true })).toBeVisible()
  await expect(page.getByText('35.1%', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '收入与毛利趋势（万元）' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '收入变化贡献（万元）' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '毛利变化贡献（万元）' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '重点问题' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '重点场站' })).toBeVisible()
  await expect(page.locator('.combo-bars i')).toHaveCount(6)
  const trendBarsVisible = await page.locator('.combo-bars i').evaluateAll(
    bars => bars.every(bar => bar.getBoundingClientRect().height >= 12),
  )
  expect(trendBarsVisible).toBe(true)

  const fit = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  }))
  expect(fit.scrollHeight).toBeLessThanOrEqual(fit.viewportHeight)

  await page.screenshot({ fullPage: true })
  expect(consoleErrors).toEqual([])
})
