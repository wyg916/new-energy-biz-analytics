import { expect, test } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdir } from 'node:fs/promises'

test.use({
  viewport: { width: 1600, height: 900 },
  channel: process.env.PLAYWRIGHT_USE_SYSTEM_CHROME === '1' ? 'chrome' : undefined,
})

const screenshotPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../docs/v2/evidence/ui/revenue-orders.png',
)

test('收入与订单复刻页在100%缩放下一屏完整展示', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '收入与订单' }).click()

  await expect(page.getByRole('heading', { name: '收入与订单', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '收入趋势' })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '收入驱动拆解' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '区域收入贡献' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '城市收入排名 Top 10' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '时段分析（收入热力图）' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '重点下滑场站' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'AI经营洞察' })).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible()
  await expect(page.getByText(/run：REV-/)).toBeVisible()

  const fit = await page.evaluate(() => {
    const panels = [...document.querySelectorAll<HTMLElement>('.revenue-panel')]
    const pageNode = document.querySelector<HTMLElement>('.revenue-page')
    const declinePanel = document.querySelector<HTMLElement>('.revenue-decline-panel')
    const clippedDeclineRows = [...document.querySelectorAll<HTMLElement>('.revenue-decline-panel tbody tr')]
      .filter(row => row.getBoundingClientRect().bottom > (declinePanel?.getBoundingClientRect().bottom ?? 0) + 1)
      .map(row => ({
        text: row.textContent,
        overflow: row.getBoundingClientRect().bottom - (declinePanel?.getBoundingClientRect().bottom ?? 0),
      }))
    const textNodes = [...document.querySelectorAll<HTMLElement>('.revenue-page :is(p,span,small,td,th,label,button,input,select)')]
      .filter(node => node.offsetParent !== null && node.textContent?.trim())
    const sizes = textNodes.map(node => Number.parseFloat(getComputedStyle(node).fontSize))
    return {
      documentScrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      pageBottom: pageNode?.getBoundingClientRect().bottom ?? 0,
      overflowingPanels: panels
        .filter(panel => panel.scrollHeight > panel.clientHeight + 1 || panel.scrollWidth > panel.clientWidth + 1)
        .map(panel => panel.className),
      clippedDeclineRows,
      minFontSize: Math.min(...sizes),
      medianFontSize: sizes.sort((a, b) => a - b)[Math.floor(sizes.length / 2)],
    }
  })
  expect(fit.documentScrollHeight).toBeLessThanOrEqual(fit.viewportHeight)
  expect(fit.pageBottom).toBeLessThanOrEqual(fit.viewportHeight)
  expect(fit.overflowingPanels).toEqual([])
  expect(fit.clippedDeclineRows).toEqual([])
  expect(fit.minFontSize).toBeGreaterThanOrEqual(10)
  expect(fit.medianFontSize).toBeGreaterThanOrEqual(11)

  await mkdir(path.dirname(screenshotPath), { recursive: true })
  await page.screenshot({ path: screenshotPath, fullPage: true })
  expect(consoleErrors).toEqual([])
})
