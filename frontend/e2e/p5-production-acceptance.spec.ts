import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('P5 Production Gate Registry 来自正式 API 且保持 No-Go', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '治理与生产就绪' }).click()
  const snapshotResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/production-acceptance/snapshot') && response.ok(),
  )
  await page.getByRole('button', { name: 'P5 生产验收' }).click()
  const body = await (await snapshotResponse).json()

  expect(body.gates).toHaveLength(15)
  expect(body.summary.production_acceptance_ready).toBe(false)
  expect(body.summary.production_release_authorized).toBe(false)
  expect(body.summary.production_traffic_switched).toBe(false)
  expect(body.runtime_contract.sqlbot_canary_eligible).toBe(false)
  expect(body.gates.filter((gate: { status: string }) => gate.status === 'WAIVED').every((gate: { waiver: unknown }) => Boolean(gate.waiver))).toBe(true)

  const pageRoot = page.getByTestId('production-acceptance-page')
  await expect(pageRoot).toBeVisible()
  await expect(pageRoot.getByRole('heading', { name: '生产验收门禁与 Go/No-Go' })).toBeVisible()
  await expect(pageRoot.getByText('NO_GO', { exact: true }).first()).toBeVisible()
  await expect(pageRoot.locator('tbody tr')).toHaveCount(body.gates.length)
  await expect(pageRoot.getByRole('button', { name: 'SQLBot Canary 禁用' })).toBeDisabled()
  await expect(pageRoot.getByRole('button', { name: '正式生产发布已禁用' })).toBeDisabled()
  await expect(pageRoot.getByRole('button', { name: '生产切流已禁用' })).toBeDisabled()
  await expect(pageRoot.getByText('模拟数据', { exact: true })).toBeVisible()
})
