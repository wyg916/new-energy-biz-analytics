import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

const emptyState = {
  installed: false,
  scenario: null,
  dataset: null,
  versions: [],
  activation: null,
  rollbacks: [],
  data_classification: 'simulated',
}

async function openMapping(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '数据接入与字段映射' }).click()
}

test('平台状态 Unauthorized 时清除会话，Forbidden 时显示 Blocked 且无 fallback', async ({ page }) => {
  await page.route('**/api/v1/platform/foundation', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'UNAUTHORIZED', message: '身份已失效' } }),
  }))
  await openMapping(page)
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()

  await page.unroute('**/api/v1/platform/foundation')
  await page.route('**/api/v1/platform/foundation', route => route.fulfill({
    status: 403,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'FORBIDDEN', message: '无平台治理权限' } }),
  }))
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '数据接入与字段映射' }).click()
  await expect(page.getByText(/Blocked \/ Error：无平台治理权限/)).toBeVisible()
  await expect(page.getByText('未使用 fallback 数据')).toBeVisible()
})

test('空 Schema、字段发现失败、连接失败和 DQ 失败均显式呈现', async ({ page }) => {
  await page.route('**/api/v1/platform/foundation', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(emptyState),
  }))
  await page.route('**/api/v1/platform/foundation/sources/platform-postgresql/discover', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      source_id: 'platform-postgresql',
      source_type: 'postgresql',
      schemas: [],
      table_count: 0,
      credential_exposed: false,
      data_classification: 'simulated',
    }),
  }), { times: 1 })
  await page.route('**/api/v1/data-integration/sources/platform-postgresql/test', route => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'SOURCE_UNAVAILABLE', message: '连接失败且无 fallback' } }),
  }))
  await page.route('**/api/v1/data-integration/overview?**', async route => {
    const response = await route.fetch()
    const body = await response.json()
    body.latest_ingestion = { run_id: 'ING-DQ-FAIL', status: 'completed', rows_written: 1 }
    body.workflow = null
    await route.fulfill({ response, json: body })
  })
  await page.route('**/api/v1/data-integration/datasets/*/runs/ING-DQ-FAIL/quality', route => route.fulfill({
    status: 422,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'QUALITY_FAILED', message: 'DQ 阻断：主键不唯一' } }),
  }))

  await openMapping(page)
  await page.getByRole('button', { name: /发现元数据/ }).click()
  await expect(page.getByRole('button', { name: /发现元数据 0 张受控表/ })).toBeVisible()

  await page.route('**/api/v1/platform/foundation/sources/platform-postgresql/discover', route => route.fulfill({
    status: 422,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'DISCOVERY_FAILED', message: '字段发现失败且无 fallback' } }),
  }))
  await page.getByRole('button', { name: /发现元数据/ }).click()
  await expect(page.locator('.mapping-platform-error')).toContainText('字段发现失败且无 fallback')

  await page.getByRole('button', { name: /测试连接/ }).first().click()
  await expect(page.getByText(/连接失败且无 fallback/)).toBeVisible()

  await page.getByRole('button', { name: /质量检查/ }).click()
  await expect(page.getByText(/DQ 阻断：主键不唯一/)).toBeVisible()
  await page.waitForTimeout(2_000)
  await page.unrouteAll({ behavior: 'wait' })
})

test('审批驳回、激活失败与回滚均以数据库响应为准', async ({ page }) => {
  const baseState = {
    installed: true,
    scenario: { scenario_id: 'charging_ops', version: '1.0.0', status: 'ACTIVE' },
    dataset: { dataset_id: 'DS-UI-TEST', code: 'charging_operations', name: '测试', source_id: 'platform-postgresql', status: 'ENABLED' },
    versions: [
      { dataset_version_id: 'DSV-ACTIVE-2', version: 2, status: 'ACTIVE', checksum: 'a', row_count: 1, review_status: 'APPROVED' },
      { dataset_version_id: 'DSV-OLD-1', version: 1, status: 'SUPERSEDED', checksum: 'b', row_count: 1, review_status: 'APPROVED' },
      { dataset_version_id: 'DSV-PUBLISHED-3', version: 3, status: 'PUBLISHED', checksum: 'c', row_count: 1, review_status: 'APPROVED' },
      { dataset_version_id: 'DSV-PENDING-4', version: 4, status: 'PENDING_APPROVAL', checksum: 'd', row_count: 1, review_status: 'PENDING' },
    ],
    activation: {
      activation_id: 'ACT-UI',
      dataset_version_id: 'DSV-ACTIVE-2',
      semantic_model_version_id: 'SMV-UI',
      semantic_version: '0.1.0',
      scenario_version: '1.0.0',
      lock_version: 2,
    },
    rollbacks: [],
    data_classification: 'simulated',
  }
  await page.route('**/api/v1/platform/foundation', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(baseState),
  }))
  await page.route('**/api/v1/platform/foundation/versions/DSV-PENDING-4/reject', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'REJECTED', state: {
      ...baseState,
      versions: baseState.versions.map(item => item.dataset_version_id === 'DSV-PENDING-4' ? { ...item, status: 'REJECTED', review_status: 'REJECTED' } : item),
    } }),
  }))
  await page.route('**/api/v1/platform/foundation/versions/DSV-PUBLISHED-3/activate', route => route.fulfill({
    status: 409,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'ACTIVATION_FAILED', message: '激活失败，旧 ACTIVE 保持不变' } }),
  }))
  await page.route('**/api/v1/platform/foundation/datasets/DS-UI-TEST/rollback', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ rollback_record_id: 'RB-UI', run_id: 'RUN-UI', state: {
      ...baseState,
      activation: { ...baseState.activation, dataset_version_id: 'DSV-OLD-1', lock_version: 3 },
      versions: baseState.versions.map(item => item.dataset_version_id === 'DSV-OLD-1' ? { ...item, status: 'ACTIVE' } : item.dataset_version_id === 'DSV-ACTIVE-2' ? { ...item, status: 'SUPERSEDED' } : item),
      rollbacks: [{ rollback_record_id: 'RB-UI', from_dataset_version_id: 'DSV-ACTIVE-2', to_dataset_version_id: 'DSV-OLD-1', reason: 'test', run_id: 'RUN-UI' }],
    } }),
  }))
  page.on('dialog', dialog => dialog.accept())

  await openMapping(page)
  await page.getByRole('button', { name: '驳回待审版本' }).click()
  await expect(page.getByText(/已驳回，不能发布或激活/)).toBeVisible()

  await page.getByRole('button', { name: /激活/ }).click()
  await expect(page.getByText(/激活失败，旧 ACTIVE 保持不变/)).toBeVisible()
  await expect(page.getByRole('button', { name: /当前 ACTIVE DSV-ACTIVE-2/ })).toBeVisible()

  await page.getByRole('button', { name: /回滚/ }).click()
  await expect(page.getByText(/已回滚到 v1/)).toBeVisible()
})
