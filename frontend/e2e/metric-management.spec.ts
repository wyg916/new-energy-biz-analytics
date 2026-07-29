import { expect, test } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdir } from 'node:fs/promises'

test.use({
  viewport: { width: 1600, height: 900 },
  launchOptions: {
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : {}),
  },
})

const screenshotPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../docs/v2/evidence/ui/metric-management.png',
)

test('指标与场景管理页在100%缩放下一屏完整展示', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '指标与场景管理' }).click()

  await expect(page.getByRole('heading', { name: '指标与场景管理', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '指标目录' })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByRole('heading', { name: /指标列表/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: '指标详情' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '场景应用预览' })).toBeVisible()
  await expect(page.getByText('15 项', { exact: true })).toBeVisible()
  await expect(page.getByText('充电收入', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible()
  await expect(page.getByText(/run_id：DASH-/)).toBeVisible()

  await page.getByPlaceholder('搜索指标名称/编码').fill('device_online_rate')
  await expect(page.getByText('设备在线率', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: '重置' }).click()
  await expect(page.getByText('共 15 条', { exact: true })).toBeVisible()

  const fit = await page.evaluate(() => {
    const pageNode = document.querySelector<HTMLElement>('.metrics-page')
    const workspace = document.querySelector<HTMLElement>('.metrics-workspace')
    const guardedPanels = [
      ...document.querySelectorAll<HTMLElement>('.metric-catalog-panel,.metric-table-panel,.metric-detail-card,.metric-preview-card'),
    ]
    return {
      documentScrollHeight: document.documentElement.scrollHeight,
      documentScrollWidth: document.documentElement.scrollWidth,
      viewportHeight: window.innerHeight,
      viewportWidth: window.innerWidth,
      pageBottom: pageNode?.getBoundingClientRect().bottom ?? 0,
      workspaceBottom: workspace?.getBoundingClientRect().bottom ?? 0,
      overflowingPanels: guardedPanels
        .filter(panel => panel.scrollHeight > panel.clientHeight + 1 || panel.scrollWidth > panel.clientWidth + 1)
        .map(panel => panel.className),
    }
  })
  expect(fit.documentScrollHeight).toBeLessThanOrEqual(fit.viewportHeight)
  expect(fit.documentScrollWidth).toBeLessThanOrEqual(fit.viewportWidth)
  expect(fit.pageBottom).toBeLessThanOrEqual(fit.viewportHeight)
  expect(fit.workspaceBottom).toBeLessThanOrEqual(fit.viewportHeight)
  expect(fit.overflowingPanels).toEqual([])

  await mkdir(path.dirname(screenshotPath), { recursive: true })
  await page.screenshot({ path: screenshotPath, fullPage: true })
  expect(consoleErrors).toEqual([])
})
