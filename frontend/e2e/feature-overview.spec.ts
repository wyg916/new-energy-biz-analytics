import { expect, test } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdir } from 'node:fs/promises'

test.use({ viewport: { width: 1600, height: 900 } })
const screenshotPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../docs/v2/evidence/ui/feature-overview.png',
)

test('功能总览复刻页使用后端指标并支持核心入口', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '功能总览', exact: true })).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true }).first()).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('3,424,091.33', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('35.1%', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('95.5%', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('来源：平台数据库', { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/^run：DASH-/)).toBeVisible()
  const viewportFit = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  }))
  expect(viewportFit.scrollHeight).toBeLessThanOrEqual(viewportFit.viewportHeight)
  await mkdir(path.dirname(screenshotPath), { recursive: true })
  await page.screenshot({ path: screenshotPath, fullPage: true })
  await page.getByRole('button', { name: /向 AI 提问/ }).click()
  await expect(page.getByRole('heading', { name: 'AI经营分析', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '可信 ChatBI' })).toBeVisible()
  await page.getByRole('button', { name: '功能总览' }).click()
  await expect(page.getByRole('heading', { name: '功能总览', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '经营预警' }).click()
  await expect(page.getByRole('heading', { name: '预警列表' })).toBeVisible({ timeout: 90_000 })
  await page.getByRole('button', { name: '经营报告' }).click()
  await expect(page.getByRole('heading', { name: '周报 / 月报草稿' })).toBeVisible()
  await page.getByRole('button', { name: '生成月报草稿' }).click()
  await expect(page.getByText('状态：草稿')).toBeVisible({ timeout: 90_000 })
  expect(consoleErrors).toEqual([])
})
