import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('企业治理控制台读取正式 API 并展示安全边界', async ({ page }) => {
  const snapshotResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/governance/snapshot') && response.ok(),
  )
  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '治理与生产就绪' }).click()
  const snapshot = await snapshotResponse
  const body = await snapshot.json()

  expect(body.runtime.query_engine_mode).toBe('SHADOW')
  expect(body.runtime.sqlbot_engine_enabled).toBe(false)
  expect(body.runtime.sqlbot_canary_eligible).toBe(false)
  expect(body.runtime.production_release_enabled).toBe(false)
  expect(body.credentials.every((item: { secret_value_exposed: boolean }) => item.secret_value_exposed === false)).toBe(true)

  await expect(page.getByRole('heading', { name: '企业治理与生产就绪', exact: true })).toBeVisible()
  await expect(page.getByTestId('governance-page')).toBeVisible()
  await expect(page.getByText('Secret 值暴露 0')).toBeVisible()
  await expect(page.getByText('SHADOW', { exact: true })).toBeVisible()
  await expect(page.getByText('false', { exact: true })).toHaveCount(3)

  for (const tab of ['身份与授权', '凭据引用', 'Legal Hold 与保留', '审计与告警', '发布与运行']) {
    await page.getByRole('button', { name: tab }).click()
  }
  await expect(page.getByRole('button', { name: '生产发布已禁用' })).toBeDisabled()
  await expect(page.getByText('隔离环境', { exact: true })).toBeVisible()
  await expect(page.locator('.global-data-status')).toContainText('模拟数据')
})

test('普通业务用户访问治理中心时明确显示 Forbidden 且无虚构 fallback', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('账号').fill('executive')
  await page.getByLabel('密码').fill('AlphaExec!2026')
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '治理与生产就绪' }).click()

  const state = page.locator('.gov-state.denied')
  await expect(state).toBeVisible()
  await expect(state).toContainText('Forbidden')
  await expect(page.getByTestId('governance-page')).toHaveCount(0)
})
