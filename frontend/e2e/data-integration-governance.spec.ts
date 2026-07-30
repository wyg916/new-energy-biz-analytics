import { expect, test } from '@playwright/test'

test.use({
  viewport: { width: 1600, height: 900 },
  launchOptions: {
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : {}),
  },
})
test('数据接入治理页展示已发布不可变快照和 13 步平台闭环', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.getByRole('button', { name: '数据接入与字段映射' }).click()
  await expect(page.getByRole('heading', { name: '数据接入与字段映射', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /已发布 v\d+\.\d+/ })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '校验状态 8/8' })).toBeVisible()
  await expect(page.getByText('DQI-008 受控结构不含直接身份字段')).toBeVisible()
  await expect(page.getByText(/治理状态：已发布 v\d+\.\d+；语义激活：not_implemented/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'P1A 数据源 → ACTIVE DatasetVersion 真实闭环' })).toBeVisible()
  await expect(page.locator('.platform-release-steps button')).toHaveCount(13)
  await expect(page.getByRole('button', { name: /创建数据源/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /当前 ACTIVE/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /回滚/ })).toBeVisible()
  const fit = await page.evaluate(() => {
    const selectors = [
      '.mapping-workspace', '.mapping-source-panel', '.mapping-center',
      '.mapping-field-panel', '.mapping-preview-panel', '.mapping-right',
      '.mapping-config-panel', '.mapping-validation-panel',
    ]
    return {
      pageWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
      overflowing: selectors.filter(selector => {
        const node = document.querySelector<HTMLElement>(selector)
        return node && node.scrollWidth > node.clientWidth + 1
      }),
    }
  })
  expect(fit.pageWidth).toBeLessThanOrEqual(fit.viewportWidth)
  expect(fit.overflowing).toEqual([])
  await page.screenshot({ fullPage: true })
  expect(consoleErrors).toEqual([])
})
