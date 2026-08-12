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
  const startDate = page.getByRole('textbox', { name: '开始日期' })
  const endDate = page.getByRole('textbox', { name: '结束日期' })
  await startDate.fill('2020-06-02')
  await endDate.fill('2020-06-09')
  await expect(startDate).toHaveValue('2020-06-02')
  await expect(endDate).toHaveValue('2020-06-09')
  if (await page.getByRole('button', { name: '运行受控预警规则' }).isEnabled()) {
    await page.getByRole('button', { name: '运行受控预警规则' }).click()
  }
  const detail = page.locator('.p6-panel.detail')
  const status = detail.locator('header .p6-status')
  const transitions: Record<string, { label: string; next: string }> = {
    OPEN: { label: '分派', next: 'ASSIGNED' },
    REOPENED: { label: '重新分派', next: 'ASSIGNED' },
    ASSIGNED: { label: '确认', next: 'ACKNOWLEDGED' },
    ACKNOWLEDGED: { label: '开始处理', next: 'IN_PROGRESS' },
    IN_PROGRESS: { label: '解决', next: 'RESOLVED' },
    RESOLVED: { label: '验证', next: 'VERIFIED' },
    VERIFIED: { label: '关闭', next: 'CLOSED' },
    CLOSED: { label: '重开', next: 'REOPENED' },
  }
  let exercisedReopen = false
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const current = (await status.innerText()).trim()
    if (current === 'CLOSED' && exercisedReopen) break
    const transition = transitions[current]
    if (!transition) throw new Error(`unsupported alert state: ${current}`)
    if (current === 'CLOSED') exercisedReopen = true
    const button = detail.getByRole('button', { name: transition.label, exact: true })
    await expect(button).toBeVisible({ timeout: 120_000 })
    await button.click()
    await expect(status).toHaveText(transition.next, { timeout: 120_000 })
  }
  await expect(status).toHaveText('CLOSED')
  expect(exercisedReopen).toBeTruthy()

  await page.getByRole('button', { name: '经营报告' }).click()
  await expect(page.getByTestId('p6-report-center')).toBeVisible()
  await page.getByRole('button', { name: '创建月报草稿' }).click()
  await page.getByRole('button', { name: '新版本', exact: true }).click()
  await page.getByRole('button', { name: '提交审核', exact: true }).click()
  await page.getByRole('button', { name: '批准', exact: true }).click()
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.getByText('Evidence Snapshot 已冻结')).toBeVisible({ timeout: 120_000 })
  await page.getByRole('button', { name: '归档', exact: true }).click()
  await expect(page.getByText('ARCHIVED', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: '指标与场景管理' }).click()
  await expect(page.getByTestId('p6-metric-center')).toBeVisible()
  const draftChargingRevenue = page.locator('tr').filter({ hasText: 'charging_revenue' }).filter({ hasText: 'DRAFT' }).first()
  if (await draftChargingRevenue.count()) {
    await draftChargingRevenue.click()
  } else {
    const publishedChargingRevenue = page.locator('tr').filter({ hasText: 'charging_revenue' }).filter({ hasText: 'PUBLISHED' }).first()
    await publishedChargingRevenue.click()
    await page.getByRole('button', { name: '新建版本', exact: true }).click()
  }
  await page.getByRole('button', { name: '影响分析', exact: true }).click()
  await expect(page.locator('.p6-impact')).toContainText('dashboard')
  await page.getByRole('button', { name: '提交审核', exact: true }).click()
  await page.getByRole('button', { name: '批准', exact: true }).click()
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.locator('tr').filter({ hasText: 'charging_revenue' }).filter({ hasText: 'DEPRECATED' }).first()).toBeVisible()
  expect(consoleErrors).toEqual([])
})
