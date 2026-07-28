import { expect, test } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const evidenceDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../docs/v2/evidence/alpha/screenshots',
)

const viewport = { width: 1440, height: 900 }
test.use({ viewport })

test('capture current Alpha product pages without changing business data', async ({ page }) => {
  await mkdir(evidenceDir, { recursive: true })
  const capturedAt = new Date().toISOString()
  const screenshots: Array<{ page: string; file: string }> = []

  async function capture(pageName: string, file: string) {
    await page.screenshot({ path: path.join(evidenceDir, file), fullPage: true })
    screenshots.push({ page: pageName, file })
  }

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '新能源经营分析平台' })).toBeVisible()
  await capture('登录页', '01-login.png')

  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '经营总览' })).toBeVisible()
  await expect(page.getByText('来源：平台数据库')).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('模拟数据', { exact: true })).toBeVisible()
  await capture('经营总览', '02-overview.png')

  for (const [pageName, file] of [
    ['收入分析', '03-revenue.png'],
    ['毛利分析', '04-gross-profit.png'],
    ['场站分析', '05-stations.png'],
    ['设备分析', '06-devices.png'],
  ] as const) {
    const response = page.waitForResponse(
      item => item.url().includes('/api/v1/dashboard/summary') && item.ok(),
    )
    await page.getByRole('button', { name: pageName }).click()
    await response
    await expect(page.getByRole('heading', { name: pageName })).toBeVisible()
    await expect(page.getByText('来源：平台数据库')).toBeVisible()
    await capture(pageName, file)
  }

  await page.getByRole('button', { name: '异常诊断' }).click()
  await expect(page.getByRole('heading', { name: '毛利变化桥接' })).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText(/不构成因果/)).toBeVisible()
  await capture('异常诊断', '07-diagnostics.png')

  await page.getByRole('button', { name: '可信问数' }).click()
  const chatResponse = page.waitForResponse(
    item => item.url().includes('/api/v1/chat/query') && item.ok(),
  )
  await page.getByRole('button', { name: '开始分析' }).click()
  await chatResponse
  await expect(page.getByText(/充电收入：/)).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('passed', { exact: true }).last()).toBeVisible()
  await capture('可信问数 / ChatBI', '08-chatbi.png')

  await page.getByRole('button', { name: '报告草稿' }).click()
  const reportResponse = page.waitForResponse(
    item => item.url().includes('/api/v1/reports/draft') && item.ok(),
  )
  await page.getByRole('button', { name: '生成月报草稿' }).click()
  await reportResponse
  await expect(page.getByText(/新能源经营分析月报草稿/)).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('状态：草稿')).toBeVisible()
  await capture('报告草稿', '09-report.png')

  const manifest = {
    captured_at: capturedAt,
    viewport,
    base_url: 'http://127.0.0.1:8080',
    data_classification: 'fixed_seed_simulated',
    data_source_label_verified: 'platform_database',
    screenshots,
    unavailable_pages: [
      {
        page: '系统或审计页面',
        reason: '当前 Alpha 前端没有系统或审计导航/路由；后端审计能力存在，但无对应页面。',
      },
    ],
  }
  await writeFile(
    path.join(evidenceDir, 'manifest.json'),
    JSON.stringify(manifest, null, 2) + '\n',
    'utf-8',
  )
})
