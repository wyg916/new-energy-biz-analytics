import { expect, test } from '@playwright/test'

const oidcPassword = process.env.P4_OIDC_PASSWORD
const acceptanceOrigin = new URL(process.env.PLAYWRIGHT_BASE_URL ?? 'https://p5b.localhost:8446').origin

test.use({ viewport: { width: 1600, height: 960 } })

async function login(page: import('@playwright/test').Page) {
  if (!oidcPassword) throw new Error('P6 runtime-only OIDC password was not provided')
  await page.goto('/')
  await expect(page.getByTestId('oidc-login')).toBeEnabled()
  await Promise.all([
    page.waitForURL(/\/protocol\/openid-connect\/auth/),
    page.getByTestId('oidc-login').click(),
  ])
  await page.locator('#username').fill('p4.analyst')
  await page.locator('#password').fill(oidcPassword)
  const callback = page.waitForResponse(
    response => response.url().includes('/api/v1/auth/oidc/callback'),
  )
  await page.locator('#kc-login').click()
  expect((await callback).ok()).toBeTruthy()
  await page.waitForURL(url => url.origin === acceptanceOrigin && url.pathname === '/')
}

test('P6 三类经营管理业务闭环经真实 API 完成', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await login(page)

  await page.getByRole('button', { name: '经营预警' }).click()
  await expect(page.getByTestId('p6-alert-center')).toBeVisible({ timeout: 120_000 })
  if (await page.getByRole('button', { name: '运行受控预警规则' }).isEnabled()) {
    await page.getByRole('button', { name: '运行受控预警规则' }).click()
  }
  for (const action of ['分派', '确认', '开始处理', '解决', '验证', '关闭', '重开']) {
    const button = page.getByRole('button', { name: action, exact: true })
    await expect(button).toBeVisible({ timeout: 120_000 })
    await button.click()
  }
  await expect(page.getByText('REOPENED', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: '经营报告' }).click()
  await expect(page.getByTestId('p6-report-center')).toBeVisible()
  await page.getByRole('button', { name: '创建月报草稿' }).click()
  await page.getByRole('button', { name: '提交审核', exact: true }).click()
  await page.getByRole('button', { name: '批准', exact: true }).click()
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.getByText('Evidence Snapshot 已冻结')).toBeVisible({ timeout: 120_000 })
  await page.getByRole('button', { name: '归档', exact: true }).click()
  await expect(page.getByText('ARCHIVED', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: '指标与场景管理' }).click()
  await expect(page.getByTestId('p6-metric-center')).toBeVisible()
  const publishedChargingRevenue = page.locator('tr').filter({ hasText: 'charging_revenue' }).filter({ hasText: 'PUBLISHED' }).first()
  await publishedChargingRevenue.click()
  await page.getByRole('button', { name: '新建版本', exact: true }).click()
  await page.getByRole('button', { name: '影响分析', exact: true }).click()
  await expect(page.getByText('dashboard', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '提交审核', exact: true }).click()
  await page.getByRole('button', { name: '批准', exact: true }).click()
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.locator('tr').filter({ hasText: 'charging_revenue' }).filter({ hasText: 'DEPRECATED' }).first()).toBeVisible()
  expect(consoleErrors).toEqual([])
})
