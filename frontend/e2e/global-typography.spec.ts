import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1920, height: 1080 } })

test('all primary product views use the unified readable typography scale', async ({ page }) => {
  await page.goto('/')
  await page.locator('.product-login form > button').click()

  const routeIndexes = [0, 1, 2, 3, 4, 5, 6, 7, 8]
  for (const index of routeIndexes) {
    await page.locator('.product-sidebar nav button').nth(index).click()

    const typography = await page.evaluate(() => {
      const selector = 'p,li,button,td,th,small,label,select,input,textarea,span,em,time,code,summary'
      const visibleNodes = [...document.querySelectorAll(selector)].filter(node => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return rect.width > 0
          && rect.height > 0
          && style.visibility !== 'hidden'
          && style.display !== 'none'
          && Boolean((node.textContent || '').trim())
      })
      const sizes = visibleNodes
        .map(node => Number.parseFloat(getComputedStyle(node).fontSize))
        .filter(Number.isFinite)
      return {
        minimumFontSize: sizes.length ? Math.min(...sizes) : 0,
        pageHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
        fontFamily: getComputedStyle(document.body).fontFamily,
      }
    })

    expect(typography.minimumFontSize).toBeGreaterThanOrEqual(10)
    expect(typography.pageHeight).toBeLessThanOrEqual(typography.viewportHeight)
    expect(typography.fontFamily).toContain('Noto Sans SC')
  }
})
