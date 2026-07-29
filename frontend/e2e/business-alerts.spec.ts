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
  '../../docs/v2/evidence/ui/business-alerts.png',
)

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
  await expect(page.getByRole('heading', { name: '预警列表' })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '业务摘要' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '指标变化' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /贡献拆解/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: '影响对象' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '建议行动' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '处理记录' })).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible()
  await expect(page.getByText(/run_id：DIAG-/)).toBeVisible()

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

  await page.getByLabel('风险等级筛选').selectOption('high')
  await expect(page.locator('.alert-rows > button')).toHaveCount(2)
  await page.getByLabel('风险等级筛选').selectOption('all')

  await mkdir(path.dirname(screenshotPath), { recursive: true })
  await page.screenshot({ path: screenshotPath, fullPage: true })
  expect(consoleErrors).toEqual([])
})
