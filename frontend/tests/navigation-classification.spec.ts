import { test, expect } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const headers = { 'X-SAP-Lens': 'browser-test-session' }
const sections = ['System & Organization', 'Data Source & Import', 'SAP Modules', 'Domains & Classification', 'Appearance & Branding', 'Application & Diagnostics']
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
    await expect(page.getByRole('tab', { name: 'Data Source & Import', exact: true })).toHaveAttribute('aria-selected', 'true')
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
    await page.getByRole('tab', { name: 'Domains & Classification', exact: true }).press('ArrowUp')
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
    const sourceColor = (await (await request.get('/api/modules', { headers })).json()).find((item: { function_key: string }) => item.function_key === 'LOCAL_FIN').color
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
    expect((await (await request.get('/api/modules', { headers })).json()).find((item: { function_key: string }) => item.function_key === 'LOCAL_FIN').color).toBe(sourceColor)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

test('classification example explains CSV evidence, rules and fallback without changing stored settings', async ({ page, request }) => {
  const before = (await (await request.get('/api/configuration', { headers })).json()).settings
  expect(before.active_classification).toBe('legacy')
  await page.goto('/#session=browser-test-session')
  await page.getByRole('tab', { name: 'Domains & Classification', exact: true }).click()
  await expect(page.getByText('Saved method:', { exact: false })).toContainText('Current / Legacy')
  await expect(page.getByRole('button', { name: 'Add Custom profile', exact: true })).toBeHidden()
  await page.getByRole('combobox', { name: 'Classification profile', exact: true }).selectOption('generic')
  await page.getByLabel('Test an individual role name', { exact: true }).fill('Z_DEMO_PAYABLES')
  await page.getByLabel('CSV SAP area for this example (optional)', { exact: true }).fill('FI')
  await page.getByRole('button', { name: 'Preview classification', exact: true }).click()
  const result = page.getByRole('region', { name: 'Individual classification result', exact: true })
  await expect(result).toContainText('FI — Financial Accounting')
  await expect(result).toContainText('Recognized SAP area from CSV')
  await expect(result).toContainText('Generic SAP')
  await expect(result).toContainText('No business domain')
  await expect(result).toContainText('Unchanged — only Apply settings')
  await page.getByLabel('CSV SAP area for this example (optional)', { exact: true }).fill('')
  await expect(result).toBeHidden()
  await page.getByRole('button', { name: 'Preview classification', exact: true }).click()
  await expect(result).toContainText('No matching rule or recognized CSV area')
  await expect(result).toContainText('Yes — Unclassified because no evidence matched')
  expect((await (await request.get('/api/configuration', { headers })).json()).settings).toEqual(before)
})

test('custom individual preview names matched rules and explicitly warns when fallback replaces CSV evidence', async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  const profile = settings.classification_profiles.find((item: { id: string }) => item.id === 'custom')
  profile.domains = [{ id: 'finance', label: 'Synthetic finance', module_id: 'FI' }, { id: 'buying', label: 'Synthetic procurement', module_id: 'MM' }]
  profile.rules = [{ id: 'pay-rule', kind: 'prefix', pattern: 'Z_DEMO_PAY', domain_id: 'finance', priority: 100, case_sensitive: false }]
  profile.fallback_domain = 'buying'
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
  const saved = (await (await request.get('/api/configuration', { headers })).json()).settings
  await page.goto('/#session=browser-test-session')
  await page.getByRole('tab', { name: 'Domains & Classification', exact: true }).click()
  await page.getByRole('combobox', { name: 'Classification profile', exact: true }).selectOption('custom')
  await page.getByLabel('Test an individual role name', { exact: true }).fill('Z_DEMO_PAYABLES')
  await page.getByLabel('CSV SAP area for this example (optional)', { exact: true }).fill('FI')
  await page.getByRole('button', { name: 'Preview classification', exact: true }).click()
  const result = page.getByRole('region', { name: 'Individual classification result', exact: true })
  await expect(result).toContainText('prefix: Z_DEMO_PAY (pay-rule)')
  await expect(result).toContainText('Synthetic finance')
  await page.getByLabel('Test an individual role name', { exact: true }).fill('Z_DEMO_OTHER')
  await page.getByRole('button', { name: 'Preview classification', exact: true }).click()
  await expect(result).toContainText('MM — Materials Management')
  await expect(result).toContainText('Yes — configured fallback domain')
  await expect(result).toContainText('Proposed area MM replaces CSV area FI')
  await expect(result).toContainText('Synthetic procurement')
  expect((await (await request.get('/api/configuration', { headers })).json()).settings).toEqual(saved)
})
