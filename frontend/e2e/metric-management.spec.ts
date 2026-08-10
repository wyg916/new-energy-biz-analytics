import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('指标治理中心展示语义层的正式版本历史', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '指标与场景管理' }).click()
  await expect(page.getByTestId('p6-metric-center')).toBeVisible({ timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '指标版本' })).toBeVisible()
  await expect(page.getByText('15', { exact: true })).toBeVisible()
  await expect(page.getByText('充电收入', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '指标版本治理' })).toBeVisible()
  await expect(page.getByText('PUBLISHED', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Owner', { exact: true })).toBeVisible()
  await expect(page.getByText('公式', { exact: true })).toBeVisible()
  await expect(page.getByText('来源表', { exact: true })).toBeVisible()
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
