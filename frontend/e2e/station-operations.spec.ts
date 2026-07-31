import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('场站经营复刻页在100%缩放下一屏完整展示', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '场站经营' }).click()

  await expect(page.getByRole('heading', { name: '场站经营', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: /场站矩阵分布/ })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '区域表现分布' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '场站等级分布' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '场站综合排名' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /场站详情/ })).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible()
  await expect(page.locator('.global-data-status')).toContainText(/run_id：DASH-/)

  const fit = await page.evaluate(() => {
    const panels = [...document.querySelectorAll<HTMLElement>('.station-panel')]
    const pageNode = document.querySelector<HTMLElement>('.station-page')
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
