import {inspectTechnicalSources} from './source-details-fixture'
import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { formatDate, formatTimestamp } from '../src/lib/dateFormat'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
let directory: string
const catalogue = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nMM,ZC:MM:BUY:*,Purchasing,ZS:BUY,MM - Purchasing - Display,MIGO,Goods movement\nMM,ZC:MM:BUY:*,Purchasing,ZS:BUY,MM - Purchasing - Display,ME21N,Create purchase order\nSD,ZC:SD:VIEW:*,Sales,ZS:VIEW,SD - Sales - Display,VA03,Display sales order\nSD,ZC:SD:VIEW:*,Sales,ZS:VIEW,SD - Sales - Display,ME21N,Create purchase order\nFI,ZC:FI:EMPTY,No mappings,ZS:EMPTY,Missing exported mappings,,\n'
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-polish-'))
  const roles = path.join(directory, 'roles.csv'), users = path.join(directory, 'users.csv')
  writeFileSync(roles, catalogue)
  writeFileSync(users, 'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO,USER_LOCKED\n' +
    'DEMO_ALPHA,ZC:MM:BUY:ENP,G1,Demo,Alpha,20200101,99991231,20200101,99991231,0\n' +
    'DEMO_ALPHA,ZC:SD:VIEW:ENP,G1,Demo,Alpha,20200101,99991231,20200101,99991231,0\n' +
    'DEMO_ALPHA,ZC:MM:BUY:ENP,G1,Demo,Alpha,20200101,99991231,19900101,19991231,0\n' +
    'DEMO_ALPHA,ZO:MM:M:PR_REL_ST_SH_N6:ALL,G1,Demo,Alpha,20200101,99991231,20200101,99991231,0\n' +
    'DEMO_BETA,ZC:SD:VIEW:ENS,G1,Demo,Beta,20200101,99991231,20200101,99991231,X\n' +
    'DEMO_OTHER,ZC:SD:VIEW:ENO,G2,Demo,Other,20200101,99991231,20200101,99991231,\n')
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = roles; settings.user_csv_path = users
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }); rmSync(directory, { recursive: true, force: true }) })
async function user(page: Page) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'User Access', exact: true }).click()
  await page.getByRole('link', { name: 'DEMO_ALPHA', exact: true }).click()
  return page.getByRole('region', { name: 'User details', exact: true })
}
test('live multi-code user filtering, chips, duplicate prevention, Backspace and CSV respect OR and other filters', async ({ page }) => {
  const detail = await user(page), filter = detail.getByRole('group', { name: 'Find roles by transaction', exact: true })
  const input = filter.getByRole('textbox')
  await input.fill(' migo ')
  await expect(detail.getByRole('row')).toHaveCount(2)
  await input.press('Enter'); await expect(input).toHaveValue(''); await expect(input).toBeFocused()
  await expect(filter.getByRole('button', { name: 'Remove transaction MIGO' })).toHaveCount(1)
  await input.fill('MIGO'); await input.press('Enter')
  await expect(filter.getByRole('button', { name: 'Remove transaction MIGO' })).toHaveCount(1)
  await input.fill('va03')
  await filter.getByRole('button',{name:'OR',exact:true}).click()
  await expect(detail.getByRole('row')).toHaveCount(3)
  const pending = page.waitForEvent('download')
  await detail.getByRole('button', { name: 'Export CSV', exact: true }).click()
  const csv = readFileSync((await (await pending).path())!, 'utf8')
  expect(csv).toContain('ZC:MM:BUY:ENP'); expect(csv).toContain('ZC:SD:VIEW:ENP'); expect(csv).not.toContain('ZO:')
  expect(csv).toContain('2020-01-01'); expect(csv).toContain('9999-12-31')
  await input.press('Enter'); await input.press('Backspace')
  await expect(filter.getByRole('button', { name: 'Remove transaction VA03' })).toHaveCount(0)
  await expect(detail.getByRole('row')).toHaveCount(2)
  await detail.getByLabel('Assignment status', { exact: true }).selectOption('expired')
  await expect(detail.getByRole('row')).toHaveCount(2)
  await detail.getByRole('tab', { name: 'Release Roles — ZO:*', exact: true }).click()
  await expect(detail).toContainText('No matching roles')
  await filter.getByRole('button', { name: 'Clear filter', exact: true }).click()
  await expect(filter.getByRole('button', { name: 'Clear filter', exact: true })).toHaveCount(0)
  await expect(detail.getByLabel('Assignment status', { exact: true })).toHaveValue('expired')
})
test('sidebar multi-code chips search collapsed mappings and reset on role changes', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Role Lookup',exact:true}).click()
  await page.getByRole('button', { name: 'View details for Purchasing', exact: true }).click()
  const dialog = page.getByRole('dialog'), filter = dialog.getByRole('group', { name: 'Find transaction code', exact: true }), input = filter.getByRole('textbox')
  await input.fill('MIGO'); await input.press('Enter'); await input.fill('ME21N')
  await expect(dialog.locator('tr[data-transaction-match=true]:visible')).toHaveCount(2)
  await expect(dialog.getByRole('button', { name: 'Expand single role ZS:BUY', exact: true })).toHaveAttribute('aria-expanded', 'true')
  await filter.getByRole('button', { name: 'Remove transaction MIGO' }).click()
  await expect(dialog.locator('tr[data-transaction-match=true]:visible')).toHaveCount(1)
  await filter.getByRole('button', { name: 'Clear filter', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Expand single role ZS:BUY', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await dialog.getByRole('button', { name: 'Close role details' }).click()
  await page.getByRole('button', { name: 'View details for Sales', exact: true }).click()
  await expect(dialog.getByRole('textbox', { name: 'Find transaction code' })).toHaveValue('')
})
test('catalogue exact OR filtering combines with text/modules, preserves selections and action isolation', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Role Lookup',exact:true}).click()
  await page.getByRole('button', { name: 'Add to comparison', exact: true }).first().click()
  await page.getByRole('button', { name: 'Add to comparison', exact: true }).first().click()
  const filter = page.getByRole('group', { name: 'Filter catalogue by transaction', exact: true }), input = filter.getByRole('textbox')
  await input.fill('MIG')
  await expect(page.getByRole('article')).toHaveCount(0)
  await input.fill('MIGO'); await input.press('Enter'); await input.fill('VA03')
  await filter.getByRole('button', { name: 'OR', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(page.getByText('roles selected', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'MM – Materials Mgmt', exact: false }).click()
  await expect(page.getByRole('article')).toHaveCount(1)
  await filter.getByRole('button', { name: 'Remove transaction MIGO', exact: true }).click(); await input.fill('')
  await expect(page.getByRole('article')).toHaveCount(1)
  const card = page.getByRole('article')
  await card.getByRole('button', { name: 'View details for Purchasing', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: 'Close role details' }).click()
  await page.getByRole('button', { name: 'Clear selection', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Compare now', exact: true })).toHaveCount(0)
})
test('evidence summary clear preserves directory search, group, sorting and expired toggle', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Role Lookup',exact:true}).click()
  await page.getByRole('button', { name: 'View details for Purchasing', exact: true }).click()
  await page.getByRole('button', { name: 'Expand single role ZS:BUY', exact: true }).click()
  await page.getByRole('button', { name: 'Investigate users with MIGO', exact: true }).click()
  const directory = page.getByRole('region', { name: 'User Access', exact: true }), summary = directory.getByRole('region', { name: 'User transaction filter' })
  await expect(summary).toContainText('Transaction: MIGO')
  await expect(summary.getByRole('button',{name:'Remove transaction MIGO',exact:true})).toBeVisible()
  await directory.getByLabel('Search users', { exact: true }).fill('DEMO_')
  const group = directory.getByRole('combobox', { name: 'SAP User Group', exact: true })
  await group.fill('G1'); await group.press('Enter')
  await directory.getByLabel('Sort users', { exact: true }).selectOption('last_name')
  await directory.getByLabel('Descending', { exact: true }).check()
  await directory.getByLabel('Show expired assignments', { exact: true }).check()
  const clear = summary.getByRole('button', { name: 'Remove transaction MIGO', exact: true })
  await expect(clear.locator('.lucide-x')).toBeVisible()
  const resting = await clear.evaluate(e => getComputedStyle(e).backgroundColor)
  await clear.hover(); expect(await clear.evaluate(e => getComputedStyle(e).backgroundColor)).not.toBe(resting)
  await page.keyboard.press('Tab'); await clear.focus(); await expect(clear).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(summary.locator('.transaction-chip')).toHaveCount(0)
  await expect(directory.getByLabel('Search users', { exact: true })).toHaveValue('DEMO_')
  await expect(group).toHaveValue('G1')
  await expect(directory.getByLabel('Sort users', { exact: true })).toHaveValue('last_name')
  await expect(directory.getByLabel('Descending', { exact: true })).toBeChecked()
  await expect(directory.getByLabel('Show expired assignments', { exact: true })).toBeChecked()
  await expect(directory.getByRole('link', { name: 'DEMO_BETA', exact: true })).toBeVisible()
})
test('Norwegian date utilities preserve SAP dates and local/offset time semantics', () => {
  const previous = process.env.TZ
  process.env.TZ = 'America/Los_Angeles'
  try {
    expect(formatDate('2026-10-23')).toBe('23.10.2026')
    expect(formatDate('0001-01-01')).toBe('01.01.0001')
    expect(formatDate('9999-12-31')).toBe('31.12.9999')
    expect(formatDate('2026-02-30')).toBe('Unknown')
    expect(formatDate('0000-01-01')).toBe('Unknown')
    expect(formatDate(null)).toBe('Unknown')
    expect(formatTimestamp('2026-10-23T14:50:34')).toBe('23.10.2026 14:50')
    expect(formatTimestamp('2026-10-23T21:50:34Z')).toBe('23.10.2026 14:50')
    expect(formatTimestamp('2026-10-23T14:50:34', 'Unknown', true)).toBe('23.10.2026 14:50:34')
    expect(formatTimestamp('invalid')).toBe('Not available')
    expect(formatTimestamp('2026-02-30T12:00:00Z')).toBe('Not available')
  } finally { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous }
})
test('data status badges retain availability distinction and format timestamps in Norwegian', async ({ page, request }) => {
  const snapshot = await (await request.get('/api/diagnostics', { headers })).json()
  snapshot.last_successful_load = '2026-10-23T14:50:34Z'
  snapshot.sources[0].last_successful_load = snapshot.last_successful_load
  await page.route('**/api/diagnostics', route => route.fulfill({ json: snapshot }))
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings' }).click()
  await page.getByRole('tab', { name: 'Health & Diagnostics', exact: true }).click()
  await page.getByText('Source locations and storage details',{exact:true}).click()
  await inspectTechnicalSources(page)
  const source = page.getByRole('region', { name: snapshot.sources[0].name, exact: true })
  await expect(source.locator('.source-badge-success')).toHaveText('Loaded')
  await expect(source).toContainText('current access not checked')
  await expect(source).toContainText('23.10.2026')
  for (const state of ['loading', 'error', 'missing']) {
    snapshot.sources[0].loading = state === 'loading'; snapshot.sources[0].error = state === 'error' ? 'file_missing' : null
    snapshot.sources[0].loaded = state !== 'missing'; snapshot.sources[0].availability = state === 'error' ? 'missing' : 'not_checked'
    await page.getByRole('button', { name: 'Check again', exact: true }).click()
    await expect(source.locator('.source-badge')).toHaveText(state === 'loading' ? 'Loading' : state === 'error' ? 'Loaded' : 'Not loaded')
    if (state === 'error') { await expect(source).toContainText('Previously validated data is retained'); await expect(source).toContainText('File missing on last attempt') }
  }
})
for (const theme of ['light', 'dark']) for (const width of [800, 1280]) test(`live filter visual QA ${theme} ${width}`, async ({ page, request }, info) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.theme = theme; await request.post('/api/configuration', { headers, data: settings })
  await page.setViewportSize({ width, height: 900 })
  const detail = await user(page), filter = detail.getByRole('group', { name: 'Find roles by transaction', exact: true })
  const select = detail.getByLabel('Assignment status', { exact: true })
  const padding = await select.evaluate(element => parseFloat(getComputedStyle(element).paddingRight))
  expect(padding).toBeGreaterThanOrEqual(40)
  await filter.getByRole('textbox').fill('MIGO'); await filter.getByRole('textbox').press('Enter'); await filter.getByRole('textbox').fill('VA03')
  await filter.getByRole('button',{name:'OR',exact:true}).click()
  await expect(detail.getByRole('row')).toHaveCount(3)
  await expect(detail).toContainText('01.01.2020'); await expect(detail).toContainText('31.12.9999')
  await page.screenshot({ path: info.outputPath('user-live-filters.png'), fullPage: true })
  await detail.getByRole('button', { name: 'View role details: ZC:MM:BUY:*' }).click()
  await page.getByRole('button', { name: 'Expand single role ZS:BUY', exact: true }).click()
  await page.getByRole('button', { name: 'Investigate users with MIGO', exact: true }).click()
  const summary = page.getByRole('region', { name: 'User transaction filter' })
  const box = (await summary.boundingBox())!; expect(box.x + box.width).toBeLessThanOrEqual(width)
  await page.screenshot({ path: info.outputPath('active-evidence.png'), fullPage: true })
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Role Lookup', exact: true }).click()
  await page.getByRole('button', { name: 'Add to comparison', exact: true }).first().click()
  await page.getByRole('button', { name: 'Add to comparison', exact: true }).first().click()
  const catalogueFilter = page.getByRole('group', { name: 'Filter catalogue by transaction', exact: true })
  await catalogueFilter.getByRole('textbox').fill('MIGO'); await catalogueFilter.getByRole('textbox').press('Enter'); await catalogueFilter.getByRole('textbox').fill('VA03')
  await catalogueFilter.getByRole('button', { name: 'OR', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  // The compact grid uses display:contents for the semantic group. Measure the
  // actual input-to-chips extent rather than an intentionally boxless wrapper.
  const inputBox = (await catalogueFilter.getByRole('textbox').boundingBox())!
  const chipsBox = (await catalogueFilter.locator('.transaction-chips').boundingBox())!
  expect(chipsBox.y).toBeGreaterThanOrEqual(inputBox.y + inputBox.height)
  expect(chipsBox.y + chipsBox.height - inputBox.y).toBeLessThan(150)
  await page.screenshot({ path: info.outputPath('role-lookup-buttons.png'), fullPage: true })
  await page.getByRole('button', { name: 'View details for Purchasing', exact: true }).click()
  const panel = page.getByRole('dialog'), codes = panel.getByRole('group', { name: 'Find transaction code', exact: true })
  await codes.getByRole('textbox').fill('MIGO'); await codes.getByRole('textbox').press('Enter'); await codes.getByRole('textbox').fill('ME21N')
  await expect(panel.locator('tr[data-transaction-match=true]:visible')).toHaveCount(2)
  await page.screenshot({ path: info.outputPath('sidebar-chips.png') })
  await panel.getByRole('button', { name: 'Close role details' }).click()
  await page.getByRole('button', { name: 'Open settings' }).click()
  await page.getByRole('tab', { name: 'Health & Diagnostics', exact: true }).click()
  await page.getByText('Source locations and storage details',{exact:true}).click()
  await inspectTechnicalSources(page)
  const storage = page.getByRole('region', { name: 'Role Catalogue CSV', exact: true })
  await storage.scrollIntoViewIfNeeded()
  await expect(storage.locator('.source-badge-success')).toHaveText('Loaded')
  await page.screenshot({ path: info.outputPath('source-status.png') })

})
