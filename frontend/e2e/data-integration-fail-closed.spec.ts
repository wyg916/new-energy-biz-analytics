import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('数据接入接口失败时显示 Blocked 且不展示跨域 fallback', async ({ page }) => {
  await page.route('**/api/v1/data-integration/overview?**', route => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'SOURCE_UNAVAILABLE', message: '数据接入事实暂不可用' } }),
  }))

  await page.goto('/')
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '数据接入与字段映射' }).click()

  await expect(page.getByRole('heading', { name: '数据接入已阻塞' })).toBeVisible()
  await expect(page.getByText('未显示任何替代业务数据，请恢复接口后重试。')).toBeVisible()
  await expect(page.getByText('数据接入状态：Blocked')).toBeVisible()
  await expect(page.locator('.mapping-workspace')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: /数据预览/ })).toHaveCount(0)
})
