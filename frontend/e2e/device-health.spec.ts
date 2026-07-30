import { expect, test } from '@playwright/test'

test.use({
  viewport: { width: 1600, height: 900 },
  launchOptions: {
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : {}),
  },
})

test('设备健康复刻页在100%缩放下一屏完整展示', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '设备健康' }).click()

  await expect(page.getByRole('heading', { name: '设备健康', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '故障类型 Pareto 排名' })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '设备在线 / 离线趋势' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '维修优先级清单' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /设备详情/ })).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible()
  await expect(page.getByText(/run_id：DASH-/)).toBeVisible()
  await expect(page.locator('.device-sparkline')).toHaveCount(0)
  await expect(page.locator('.device-truth')).toHaveCount(0)

  const fit = await page.evaluate(() => {
    const panels = [...document.querySelectorAll<HTMLElement>('.device-panel')]
    const pageNode = document.querySelector<HTMLElement>('.device-page')
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

  await page.screenshot({ fullPage: true })
  expect(consoleErrors).toEqual([])
})
