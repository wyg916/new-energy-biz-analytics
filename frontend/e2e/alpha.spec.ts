import { expect, test } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const evidenceDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/evidence/screenshots')

test('product alpha core journey uses live backend data', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '新能源经营分析平台' })).toBeVisible()
  await page.screenshot({ path: path.join(evidenceDir, '01-login.png'), fullPage: true })
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '经营总览' })).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('来源：平台数据库')).toBeVisible()
  await page.screenshot({ path: path.join(evidenceDir, '02-dashboard.png'), fullPage: true })

  await page.getByRole('button', { name: '可信问数' }).click()
  await page.getByRole('button', { name: '开始分析' }).click()
  await expect(page.getByText(/充电收入：/)).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('passed', { exact: true }).last()).toBeVisible()
  await page.screenshot({ path: path.join(evidenceDir, '03-chatbi.png'), fullPage: true })

  await page.getByRole('button', { name: '异常诊断' }).click()
  await expect(page.getByRole('heading', { name: '毛利变化桥接' })).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText(/不构成因果/)).toBeVisible()
  await page.screenshot({ path: path.join(evidenceDir, '04-diagnostics.png'), fullPage: true })

  await page.getByRole('button', { name: '报告草稿' }).click()
  await page.getByRole('button', { name: '生成月报草稿' }).click()
  await expect(page.getByText(/新能源经营分析月报草稿/)).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('状态：草稿')).toBeVisible()
  await page.screenshot({ path: path.join(evidenceDir, '05-report.png'), fullPage: true })
  expect(consoleErrors).toEqual([])
})
