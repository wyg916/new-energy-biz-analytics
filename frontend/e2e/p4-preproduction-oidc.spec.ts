import { expect, test } from '@playwright/test'

const oidcPassword = process.env.P4_OIDC_PASSWORD

test.use({ viewport: { width: 1600, height: 900 } })
test.skip(!oidcPassword, 'P4 runtime-only OIDC password was not provided to this process')

test('真实 OIDC Code + PKCE 登录并读取 P4 正式 API', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('oidc-login')).toBeEnabled()
  await Promise.all([
    page.waitForURL(/\/protocol\/openid-connect\/auth/),
    page.getByTestId('oidc-login').click(),
  ])
  expect(page.url()).toContain('code_challenge_method=S256')
  expect(page.url()).toContain('code_challenge=')

  await page.locator('#username').fill('p4.analyst')
  await page.locator('#password').fill(oidcPassword!)
  const callbackResponse = page.waitForResponse(response => response.url().includes('/api/v1/auth/oidc/callback'))
  await page.locator('#kc-login').click()
  const callback = await callbackResponse
  const callbackBody = await callback.json()
  expect(callback.ok(), JSON.stringify(callbackBody?.detail || { code: 'OIDC_CALLBACK_FAILED' })).toBeTruthy()
  await page.waitForURL(url => url.origin === 'https://p4.localhost:8444' && url.pathname === '/')

  await page.getByRole('button', { name: '治理与生产就绪' }).click()
  const snapshotResponse = page.waitForResponse(response => response.url().includes('/api/v1/preproduction/snapshot') && response.ok())
  await page.getByRole('button', { name: 'P4 预生产与 RC' }).click()
  const snapshot = await (await snapshotResponse).json()

  expect(snapshot.oidc.status).toBe('READY')
  expect(snapshot.oidc.pkce_method).toBe('S256')
  expect(snapshot.secret_providers.VAULT_KV_V2.status).toBe('READY')
  expect(snapshot.credential_references.every((item: { value_returned: boolean }) => item.value_returned === false)).toBe(true)
  expect(snapshot.sqlbot_external_evaluation.actual_external_requests).toBe(0)
  expect(snapshot.runtime.query_engine_mode).toBe('SHADOW')
  expect(snapshot.runtime.production_release_authorized).toBe(false)

  await expect(page.getByTestId('preproduction-page')).toBeVisible()
  await expect(page.getByTestId('preproduction-page').getByText('模拟数据', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'SQLBot Canary 禁用' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '正式生产发布已禁用' })).toBeDisabled()

  await page.locator('.profile').click()
  await expect(page.getByTestId('oidc-login')).toBeVisible()
})

test('真实 OIDC 未映射用户在服务端 callback 阶段被拒绝', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('oidc-login').click()
  await page.locator('#username').fill('p4.unmapped')
  await page.locator('#password').fill(oidcPassword!)
  await page.locator('#kc-login').click()
  await page.waitForURL(url => url.origin === 'https://p4.localhost:8444' && url.pathname === '/oidc/callback')
  await expect(page.getByTestId('oidc-callback')).toContainText('企业身份登录失败')
  await expect(page.getByTestId('oidc-callback')).toContainText('预先审批')
  expect(await page.evaluate(() => localStorage.getItem('alpha_token'))).toBeNull()
})

test('真实 OIDC 禁用用户无法取得授权码', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('oidc-login').click()
  await page.locator('#username').fill('p4.disabled')
  await page.locator('#password').fill(oidcPassword!)
  await page.locator('#kc-login').click()
  await expect(page.getByText(/Account is disabled/i)).toBeVisible()
  expect(page.url()).toContain('/oidc/realms/chatbi/login-actions/')
  expect(page.url()).not.toContain('/oidc/callback')
  expect(await page.evaluate(() => localStorage.getItem('alpha_token'))).toBeNull()
})
