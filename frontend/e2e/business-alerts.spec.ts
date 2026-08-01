import { expect, test } from '@playwright/test'

test.use({
  viewport: { width: 1600, height: 900 },
  launchOptions: {
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : {}),
  },
})

test('经营预警复刻页在100%缩放下一屏完整展示', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '经营预警' }).click()

  await expect(page.getByRole('heading', { name: '经营预警', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '规则诊断列表（非预警工单）' })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '业务摘要' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '指标变化' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /贡献拆解/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: '影响对象' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '人工核查建议' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '本轮诊断证据' })).toBeVisible()
  await expect(page.getByText('无虚构处理记录')).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible()
  await expect(page.locator('.global-data-status')).toContainText(/run_id：DASH-/)

  const fit = await page.evaluate(() => {
    const panels = [...document.querySelectorAll<HTMLElement>('.alert-panel')]
    const pageNode = document.querySelector<HTMLElement>('.alert-page')
    return {
      documentScrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      pageBottom: pageNode?.getBoundingClientRect().bottom ?? 0,
      overflowingPanels: panels
        .filter(panel => panel.scrollHeight > panel.clientHeight + 1 || panel.scrollWidth > panel.clientWidth + 1)
        .map(panel => panel.className),
    }
  })
  expect(fit.documentScrollHeight).toBeLessThanOrEqual(fit.viewportHeight)
  expect(fit.pageBottom).toBeLessThanOrEqual(fit.viewportHeight)
  expect(fit.overflowingPanels).toEqual([])

  await page.getByLabel('贡献方向筛选').selectOption('high')
  await expect.poll(() => page.locator('.alert-rows > button').count()).toBeGreaterThan(0)
  await page.getByLabel('贡献方向筛选').selectOption('all')

  await page.screenshot({ fullPage: true })
  expect(consoleErrors).toEqual([])
})
