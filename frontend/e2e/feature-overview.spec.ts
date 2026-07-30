import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1600, height: 900 } })

test('功能总览复刻页使用后端指标并支持核心入口', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '功能总览', exact: true })).toBeVisible()
  await expect(page.getByText('模拟数据', { exact: true }).first()).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('3,424,091.33', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('35.1%', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('95.5%', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('来源：平台数据库', { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/^run：DASH-/)).toBeVisible()
  const viewportFit = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  }))
  expect(viewportFit.scrollHeight).toBeLessThanOrEqual(viewportFit.viewportHeight)
  await page.screenshot({ fullPage: true })
  await page.getByRole('button', { name: /向 AI 提问/ }).click()
  await expect(page.getByRole('heading', { name: 'AI经营分析', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '可信 ChatBI' })).toBeVisible()
  await page.getByRole('button', { name: '功能总览' }).click()
  await expect(page.getByRole('heading', { name: '功能总览', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '经营预警' }).click()
  await expect(page.getByRole('heading', { name: '规则诊断列表（非预警工单）' })).toBeVisible({ timeout: 90_000 })
  await page.getByRole('button', { name: '经营报告' }).click()
  await expect(page.getByRole('heading', { name: '新能源经营分析周报' })).toBeVisible()
  await page.getByRole('button', { name: /生成报告/ }).click()
  await expect(page.getByText('● 已完成')).toBeVisible({ timeout: 90_000 })
  expect(consoleErrors).toEqual([])
})
