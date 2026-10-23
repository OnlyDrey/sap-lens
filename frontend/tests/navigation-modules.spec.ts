import { test, expect } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const headers = { 'X-SAP-Lens': 'browser-test-session' }
const sections = ['System & Organization', 'Data Sources', 'SAP Modules', 'Appearance & Branding', 'Application & Diagnostics']
test.beforeEach(async ({ request }) => {
  expect((await request.post('/api/configuration/reset', { headers })).ok()).toBeTruthy()
})

test('data-source actions override every previous section while normal opening keeps navigation history', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  for (const section of sections) {
    await page.getByRole('tab', { name: section, exact: true }).click()
    await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    await expect(page.getByRole('tab', { name: section, exact: true })).toHaveAttribute('aria-selected', 'true')
    await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
    await page.getByRole('button', { name: 'Review data source', exact: true }).click()
    await expect(page.getByRole('tab', { name: 'Data Sources', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByLabel('CSV file location', { exact: true })).toBeFocused()
    await expect(page.getByLabel('CSV file location', { exact: true })).toBeInViewport()
  }
  await page.reload()
  await page.getByRole('tab', { name: 'Application & Diagnostics', exact: true }).click()
  await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
  await page.getByRole('button', { name: 'Review data source', exact: true }).click()
  await expect(page.getByLabel('CSV file location', { exact: true })).toBeFocused()
})

test('data warning follows the content container at wide and narrow desktop widths', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
  for (const width of [1920, 1280, 768]) {
    await page.setViewportSize({ width, height: 900 })
    const main = await page.locator('#main-content').evaluate((element) => {
      const rect = element.getBoundingClientRect(), style = getComputedStyle(element)
      return { left: rect.left + parseFloat(style.paddingLeft), right: rect.right - parseFloat(style.paddingRight) }
    })
    const warning = await page.getByRole('alert').filter({ has: page.getByRole('button', { name: 'Review data source', exact: true }) }).boundingBox()
    expect(warning!.x).toBeCloseTo(main.left, 0)
    expect(warning!.x + warning!.width).toBeCloseTo(main.right, 0)
  }
})

for (const theme of ['light', 'dark'] as const) {
  test(`navigation has no vertical selection marker and module hues remain varied and readable in ${theme}`, async ({ page, request }, testInfo) => {
    expect((await request.post('/api/configuration/theme', { headers, data: { theme } })).ok()).toBeTruthy()
    await page.goto('/#session=browser-test-session')
    const tab = page.getByRole('tab', { name: 'SAP Modules', exact: true })
    await tab.click()
    await expect(tab).toHaveCSS('box-shadow', 'none')
    await expect(tab).toHaveCSS('border-left-width', '0px')
    await tab.press('ArrowDown')
    await page.getByRole('tab', { name: 'Appearance & Branding', exact: true }).press('ArrowUp')
    await expect(tab).toBeFocused()
    await expect(tab).toHaveCSS('outline-style', 'solid')
    const colors = await page.locator('.module-list-row').evaluateAll((rows) => {
      const luminance = (color: string) => {
        const channels = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map((value) => value / 255)
          .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
        return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
      }
      return rows.map((row) => {
        const icon = row.querySelector('[data-module-icon]')!, style = getComputedStyle(icon)
        const [high, low] = [luminance(style.color), luminance(style.backgroundColor)].sort((a, b) => b - a)
        return { id: row.getAttribute('aria-label')!.match(/^Edit (.*?) —/)![1], foreground: style.color, tint: style.backgroundColor, contrast: (high + 0.05) / (low + 0.05) }
      })
    })
    const representatives = colors.filter((item) => ['FI', 'CO', 'MM', 'SD', 'WM', 'EWM', 'PP', 'PM', 'QM', 'BW', 'BTP', 'ABAP'].includes(item.id))
    expect(representatives).toHaveLength(12)
    expect(new Set(representatives.map((item) => item.foreground)).size).toBeGreaterThanOrEqual(10)
    expect(new Set(representatives.map((item) => item.tint)).size).toBe(12)
    for (const item of colors) expect(item.contrast, item.id).toBeGreaterThanOrEqual(3)
    await page.screenshot({ path: testInfo.outputPath(`area-palette-${theme}.png`) })
    await page.reload()
    await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
    const stable = await page.locator('.module-list-row [data-module-icon]').evaluateAll((icons) => icons.map((icon) => getComputedStyle(icon).backgroundColor))
    expect(stable).toEqual(colors.map((item) => item.tint))
  })
}

test('filter availability is keyboard accessible, persists and preserves explicit color and role data', async ({ page, request }) => {
  const directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-ui-filter-'))
  const file = path.join(directory, 'synthetic.csv')
  writeFileSync(file, 'FUNCTION_KEY,AGR_NAME,TCODE\nFI,Z_UI_FINANCE,FB03\nMM,Z_UI_BUYER,ME23N\nLOCAL_FIN,Z_UI_LOCAL,FB03\n')
  try {
    const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
    settings.data_csv_path = file
    settings.module_overrides.FI = { color: '#123456', enabled: true }
    expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
    const before = await (await request.get('/api/roles', { headers })).json()
    expect(before).toHaveLength(3)
    const sourceColor = (await (await request.get('/api/modules', { headers })).json()).find((item: { function_key: string }) => item.function_key === 'UNCLASSIFIED').color
    await page.goto('/#session=browser-test-session')
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
    await page.getByRole('button', { name: 'Edit FI — Financial Accounting', exact: true }).click()
    const checkbox = page.getByLabel('Show FI in module filters', { exact: true })
    await checkbox.focus()
    await expect(checkbox.locator('..')).toHaveCSS('outline-style', 'solid')
    await checkbox.press('Space')
    await expect(checkbox).not.toBeChecked()
    await page.getByRole('button', { name: 'Apply settings', exact: true }).click()
    await expect(page.getByRole('region', { name: 'SAP Lens settings', exact: true })).toBeHidden()
    await expect(page.getByRole('button', { name: /^FI –/ })).toHaveCount(0)
    await page.reload()
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
    await page.getByRole('button', { name: 'Edit FI — Financial Accounting', exact: true }).click()
    await expect(checkbox).not.toBeChecked()
    await expect(page.getByLabel('FI hexadecimal color', { exact: true })).toHaveValue('#123456')
    await page.getByRole('button', { name: 'Reset FI hexadecimal color', exact: true }).click()
    await expect(page.getByLabel('FI hexadecimal color', { exact: true })).toHaveValue('#6f8fc5')
    page.once('dialog', (dialog) => void dialog.accept())
    await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    await expect(page.getByLabel('FI hexadecimal color', { exact: true })).toHaveValue('#123456')
    expect(await (await request.get('/api/roles', { headers })).json()).toEqual(before)
    expect((await (await request.get('/api/modules', { headers })).json()).find((item: { function_key: string }) => item.function_key === 'UNCLASSIFIED').color).toBe(sourceColor)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

for (const theme of ['light', 'dark'] as const) for (const width of [1280, 390]) {
  test(`import source controls and review action are accessible in ${theme} at ${width}px`, async ({ page, request }, info) => {
    expect((await request.post('/api/configuration/theme', { headers, data: { theme } })).ok()).toBeTruthy()
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#session=browser-test-session')
    await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
    const action = page.getByRole('button', { name: 'Review data source', exact: true })
    const banner = page.getByRole('alert').filter({ has: action })
    await expect(banner).toContainText('Choose a SAP role catalogue or user access CSV in Settings.')
    await expect(action).toHaveCSS('text-decoration-line', 'none')
    await expect(action).toHaveCSS('border-top-width', '1px')
    await expect(action.locator('svg.lucide-database')).toHaveAttribute('aria-hidden', 'true')
    const normal = await action.evaluate(element => getComputedStyle(element).backgroundColor)
    await action.hover()
    expect(await action.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(normal)
    await action.focus()
    await action.press('Tab')
    await page.keyboard.press('Shift+Tab')
    await expect(action).toBeFocused()
    await expect(action).toHaveCSS('outline-style', 'solid')
    const bounds = await banner.boundingBox(), button = await action.boundingBox()
    expect(button!.x).toBeGreaterThanOrEqual(bounds!.x)
    expect(button!.x + button!.width).toBeLessThanOrEqual(bounds!.x + bounds!.width)
    expect(await banner.evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy()
    await page.screenshot({ path: info.outputPath('review-button.png'), fullPage: true })
    await action.press('Enter')
    await expect(page.getByRole('tab', { name: 'Data Sources', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByLabel('CSV file location', { exact: true })).toBeFocused()
    const catalogue = page.getByRole('tab', { name: 'Role Catalogue', exact: true })
    const users = page.getByRole('tab', { name: 'User Access', exact: true })
    await expect(catalogue.locator('svg.lucide-library-big')).toHaveAttribute('aria-hidden', 'true')
    await expect(users.locator('svg.lucide-users-round')).toHaveAttribute('aria-hidden', 'true')
    for (const tab of [catalogue, users]) {
      await expect(tab).toHaveCSS('border-top-width', '0px')
      await expect(tab).toHaveCSS('border-left-width', '0px')
      await expect(tab).toHaveCSS('box-shadow', 'none')
      const alignment = await tab.evaluate(element => {
        const icon = element.querySelector('svg')!.getBoundingClientRect()
        const label = element.querySelector('span')!.getBoundingClientRect()
        return Math.abs(icon.y + icon.height / 2 - label.y - label.height / 2)
      })
      expect(alignment).toBeLessThanOrEqual(1)
    }
    const selected = await catalogue.evaluate(element => getComputedStyle(element).backgroundColor)
    expect(await users.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(selected)
    await catalogue.focus()
    await catalogue.press('ArrowRight')
    await expect(users).toBeFocused()
    await expect(users).toHaveAttribute('aria-selected', 'true')
    await expect(users).toHaveCSS('outline-style', 'solid')
    await expect(users).toHaveCSS('border-top-width', '0px')
    await expect(users).toHaveCSS('background-color', selected)
    await expect(page.getByRole('tabpanel', { name: 'User Access', exact: true })).toBeVisible()
    await users.press('Home')
    await expect(catalogue).toBeFocused()
    await expect(catalogue).toHaveAttribute('aria-selected', 'true')
    const selector = page.getByRole('tablist', { name: 'Import source', exact: true })
    expect(await selector.evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy()
    await page.screenshot({ path: info.outputPath('import-selector.png'), fullPage: true })
  })
}
