import { expect, test } from '@playwright/test'

test('企业知识库展示受控生命周期与真实运行状态', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '功能总览' })).toBeVisible({ timeout: 120_000 })

  await page.getByRole('button', { name: '企业知识库' }).click()
  await expect(page.getByRole('heading', { name: '企业知识库', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '知识源接入' })).toBeVisible()
  await expect(page.getByText(/VECTOR_DEFERRED_POST_P5/).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '本地文件上传未开放' })).toBeDisabled()
  await expect(page.getByText('4 份未跟踪用户源文档不会被扫描、读取或自动进入 RAG。')).toBeVisible()
})

test('统一回答界面展示 Profile 与运行边界', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '功能总览' })).toBeVisible({ timeout: 120_000 })

  await page.getByRole('button', { name: 'AI经营分析' }).click()
  await expect(page.getByLabel('回答风格')).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText('MODEL_RUNTIME_PENDING', { exact: true })).toBeVisible()
  await expect(page.getByText('RUNTIME_PENDING', { exact: true })).toBeVisible()
})
