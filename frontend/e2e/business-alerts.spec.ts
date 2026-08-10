import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('经营预警中心展示后端持久化事件与 SLA', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '经营预警' }).click()
  await expect(page.getByTestId('p6-alert-center')).toBeVisible({ timeout: 120_000 })
  const response = page.waitForResponse(item => item.url().includes('/api/v1/alerts/generate') && item.ok())
  await page.getByRole('button', { name: '运行受控预警规则' }).click()
  const result = await (await response).json()
  expect(result.created || result.deduplicated).toBeTruthy()
  await expect(page.getByRole('heading', { name: '预警事件' })).toBeVisible()
  await expect(page.getByText('charging_revenue', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '处置工作台' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '状态时间线' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '等级' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '处理人' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'SLA' })).toBeVisible()
  await expect(page.locator('.global-data-status')).toContainText('run_id：')
  const fit = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    overflowingPanels: [...document.querySelectorAll<HTMLElement>('.p6-panel')]
      .filter(panel => panel.scrollWidth > panel.clientWidth + 1).map(panel => panel.className),
  }))
  expect(fit.documentWidth).toBeLessThanOrEqual(fit.viewportWidth)
  expect(fit.overflowingPanels).toEqual([])
  expect(consoleErrors).toEqual([])
})
