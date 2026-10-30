import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers } from './support'
let directory: string
const pattern = 'ZC:BC:DEMO:*'
const catalogue = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\n' +
  'BC,ZC:BC:DEMO:*,Investigation example,ZD:MATERIAL,CA - Master Data - Materials Display & Reporting,MIGO,Goods movement\n' +
  'BC,ZC:BC:DEMO:*,Investigation example,ZD:MATERIAL,CA - Master Data - Materials Display & Reporting,ME23N,Display purchase order\n' +
  'BC,ZC:BC:DEMO:*,Investigation example,ZD:BATCH,CA - Master Data - Batch Display,MIGO,Goods movement\n' +
  'BC,ZC:BC:DEMO:*,Investigation example,ZD:INFO,SD - Master Data - InfoRecord,VA03,Display sales order\n' +
  'BC,ZC:BC:DEMO:*,Investigation example,ZD:UNKNOWN,ZZZ - Source description,ZZ_DEMO,Custom transaction\n' +
  'BC,ZC:BC:DEMO:*,Investigation example,ZD:MISSING,,,\n' +
  'BC,ZC:BC:SECOND:*,Second example,ZD:MATERIAL,MM - Purchasing - Display,ME23N,Display purchase order\n' +
  'BC,ZC:BC:EXACT,,ZD:EMPTY,,,\n'
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-consolidated-'))
  const roles = path.join(directory, 'roles.csv'), users = path.join(directory, 'users.csv')
  writeFileSync(roles, catalogue)
  writeFileSync(users, 'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO,USER_LOCKED,USER_VALID_FROM,USER_VALID_TO\n' +
    ['ZC:BC:DEMO:ENP', 'ZC:BC:EXACT', 'ZC:BC:ABSENT', 'ZO:MM:M:PR_REL_ST_SH_N6:ALL', 'ZD:HIDDEN', 'ZZ:HIDDEN'].map(role => `DEMO_REVIEW,${role},DEMO_GROUP,20000101,99991231,X,20000101,99991231\n`).join('') +
    'DEMO_OPEN,ZC:BC:EXACT,DEMO_GROUP,20000101,99991231,0,20000101,99991231\nDEMO_UNKNOWN,ZC:BC:EXACT,DEMO_GROUP,20000101,99991231,,20000101,99991231\n')
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = roles; settings.user_csv_path = users
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }); rmSync(directory, { recursive: true, force: true }) })
async function openRole(page: Page, role = pattern) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Role Lookup',exact:true}).click()
  await page.getByRole('button', { name: `View details for ${role === pattern ? 'Investigation example' : role === 'ZC:BC:SECOND:*' ? 'Second example' : role}`, exact: true }).click()
  return page.getByRole('dialog')
}
async function openUser(page: Page) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'User Access', exact: true }).click()
  await page.getByRole('link', { name: 'DEMO_REVIEW', exact: true }).click()
  return page.getByRole('region', { name: 'User details', exact: true })
}
test('description area labels remain separate from canonical classification', async ({ page, request }) => {
  const dialog = await openRole(page)
  const entry = dialog.locator('.single-role-entry').filter({ has: page.getByRole('button', { name: 'Expand single role ZD:MATERIAL', exact: true }) })
  await expect(entry.locator('.role-entry-head .module-badge-label')).toHaveText('CA')
  await expect(entry.locator('.role-entry-title')).toHaveText('Master Data - Materials Display & Reporting')
  await expect(entry.locator('.single-role-description')).toHaveCount(0)
  const meta = (await entry.locator('.role-entry-head').boundingBox())!, text = (await entry.locator('.role-entry-title').boundingBox())!, code = (await entry.locator('.role-identifier').boundingBox())!
  expect(text.y).toBeGreaterThanOrEqual(meta.y - 1) // module identity and description share line 1
  expect(text.y + text.height).toBeLessThanOrEqual(meta.y + meta.height + 1)
  expect(code.y).toBeGreaterThanOrEqual(meta.y + meta.height - 1) // identifier on line 2
  const heading = (await entry.locator('.single-role-heading').boundingBox())!
  expect(code.x + code.width).toBeLessThanOrEqual(heading.x + heading.width)
  await expect(dialog.locator('.role-entry-title').filter({ hasText: 'ZZZ - Source description' })).toBeVisible()
  await expect(dialog.locator('.role-entry-title').filter({ hasText: 'Unclassified' })).toHaveCount(1)
  const response = await request.get(`/api/roles/${encodeURIComponent(pattern)}`, { headers })
  expect(response.ok()).toBeTruthy()
  const data=await response.json()
  expect(data.function_key).toBe('BC')
  await expect(dialog.locator('.role-detail-header .module-badge-label').filter({hasText:/^BC$/})).toHaveText('BC')
  expect(data.single_roles.find((s: { child_agr: string }) => s.child_agr === 'ZD:MATERIAL').function_key).toBe('UNCLASSIFIED')
  expect(data.single_roles.find((s: { child_agr: string }) => s.child_agr === 'ZD:MATERIAL').child_agr_text).toBe('CA - Master Data - Materials Display & Reporting')
})
test('sidebar searches collapsed mappings exactly, expands every match and restores expansion after clear', async ({ page }) => {
  const dialog = await openRole(page)
  const search = dialog.getByRole('form', { name: 'Sidebar transaction search' })
  await dialog.getByRole('button', { name: 'Expand single role ZD:INFO', exact: true }).click()
  await search.getByRole('textbox', { name: 'Find transaction code' }).fill(' migo ')
  await expect(search.getByRole('button', { name: 'Search', exact: true })).toHaveCount(0)
  await expect(search.getByRole('status')).toContainText('2 matching single roles for MIGO.')
  await expect(dialog.locator('.single-role-entry:visible')).toHaveCount(2)
  await expect(dialog.getByRole('button', { name: 'Expand single role ZD:MATERIAL', exact: true })).toHaveAttribute('aria-expanded', 'true')
  await expect(dialog.locator('tr[data-transaction-match=true]:visible')).toHaveCount(2)
  await expect(dialog.getByRole('button', { name: 'Investigate users with MIGO', exact: true })).toHaveCount(2)
  await search.getByRole('button', { name: 'Clear filter', exact: true }).click()
  await expect(dialog.locator('.single-role-entry:visible')).toHaveCount(5)
  await expect(dialog.getByRole('button', { name: 'Expand single role ZD:MATERIAL', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await expect(dialog.getByRole('button', { name: 'Expand single role ZD:INFO', exact: true })).toHaveAttribute('aria-expanded', 'true')
  await search.getByRole('textbox', { name: 'Find transaction code' }).fill('MIG')
  await search.getByRole('textbox', { name: 'Find transaction code' }).press('Enter')
  await expect(search.getByRole('status')).toContainText('No matching single roles for MIG')
  await expect(search.getByRole('status')).toContainText('source completeness cannot be established')
  await search.getByRole('textbox', { name: 'Find transaction code' }).fill('zz_demo')
  await expect(search.getByRole('button', { name: 'Search', exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Investigate users with ZZ_DEMO', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Investigate users with ZZ_DEMO', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Remove transaction ZZ_DEMO', exact: true })).toBeVisible()
})
test('role change resets sidebar search, provenance distinguishes missing descriptions and mappings', async ({ page }) => {
  let dialog = await openRole(page)
  await dialog.getByRole('textbox', { name: 'Find transaction code' }).fill('MIGO')
  await dialog.getByRole('textbox', { name: 'Find transaction code' }).press('Enter')
  await dialog.getByRole('button', { name: 'Close role details' }).click()
  await page.getByRole('button', { name: 'View details for Second example', exact: true }).click()
  await expect(dialog.getByRole('textbox', { name: 'Find transaction code' })).toHaveValue('')
  await expect(dialog.getByRole('button', { name: 'Expand single role ZD:MATERIAL', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await dialog.getByRole('button', { name: 'Close role details' }).click()
  await page.getByRole('button', { name: 'View details for ZC:BC:EXACT', exact: true }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByText('Relationships & analysis provenance', { exact: true }).click()
  await expect(dialog).toContainText('Role description missing from the imported catalogue.')
  await expect(dialog).toContainText('No transaction mappings supplied; this does not establish absence of SAP permissions.')
  await dialog.getByRole('textbox', { name: 'Find transaction code' }).fill('MIGO')
  await dialog.getByRole('textbox', { name: 'Find transaction code' }).press('Enter')
  await expect(dialog.getByRole('form', { name: 'Sidebar transaction search' }).getByRole('status')).toContainText('Transaction mappings unavailable')
})
test('All roles default, match codes only and one toolbar preserve search and CSV export', async ({ page }) => {
  const detail = await openUser(page)
  const sections = detail.getByRole('tablist', { name: 'User role sections' })
  await expect(sections.getByRole('tab')).toHaveText(['All roles', 'Business Roles — ZC:*', 'Release Roles — ZO:*'])
  await expect(sections.getByRole('tab', { name: 'All roles', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(detail).not.toContainText('ZD:HIDDEN'); await expect(detail).not.toContainText('ZZ:HIDDEN')
  const row = detail.getByRole('row').filter({ has: page.getByRole('button', { name: 'Copy role identifier ZC:BC:EXACT', exact: true }) })
  await expect(row.locator('.assigned-role-description')).toHaveText('Description unavailable')
  await expect(row.locator('.assigned-role-description .evidence-badge')).toHaveCount(0)
  await expect(row.getByRole('button', { name: 'View role details: ZC:BC:EXACT' }).locator('.lucide-arrow-right')).toBeVisible()
  await expect(detail.getByRole('columnheader',{name:'Catalogue match',exact:true})).toHaveCount(0)
  await expect(detail.getByRole('columnheader',{name:'Role description',exact:true})).toHaveCount(0);await expect(detail.locator('.assigned-role-description').first()).toBeVisible()
  await expect(detail.locator('.assignment-mapping-evidence')).toHaveCount(0)
  await expect(row.getByRole('button',{name:'View role details: ZC:BC:EXACT',exact:true})).toBeVisible()
  const toolbar = detail.getByRole('form', { name: 'User role toolbar' })
  await expect(toolbar.getByLabel('Assignment status', { exact: true })).toBeVisible()
  await toolbar.getByRole('textbox', { name: 'Find roles by transaction' }).fill('migo')
  const activeControls = toolbar.locator('.ui-search, select, button.ui-button, button.settings-secondary-button')
  await expect(activeControls).toHaveCount(6) // Includes the scoped date filter and assignment reset.
  const tops = await activeControls.evaluateAll(elements => elements.map(element => Math.round(element.getBoundingClientRect().y)))
  expect(new Set(tops).size).toBe(1)
  await toolbar.getByRole('textbox', { name: 'Find roles by transaction' }).press('Enter')
  await expect(detail.getByRole('row')).toHaveCount(2)
  const pending = page.waitForEvent('download')
  await toolbar.getByRole('button', { name: 'Export CSV', exact: true }).click()
  const csv = readFileSync((await (await pending).path())!, 'utf8')
  expect(csv).toContain('ZC:BC:DEMO:ENP'); expect(csv).not.toContain('ZC:BC:EXACT')
})
for (const theme of ['light', 'dark']) for (const width of [800, 1280]) test(`consolidated visual QA ${theme} ${width}`, async ({ page, request }, info) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.theme = theme; await request.post('/api/configuration', { headers, data: settings })
  await page.setViewportSize({ width, height: 900 })
  const detail = await openUser(page)
  const toolbar = detail.getByRole('form', { name: 'User role toolbar' })
  await expect(toolbar).toBeVisible()
  const controls = toolbar.locator('.ui-search, select, button.ui-button, button.settings-secondary-button')
  const boxes = await controls.evaluateAll(elements => elements.map(e => { const b = e.getBoundingClientRect(); return { x: b.x, y: b.y, right: b.right, height: b.height } }))
  expect(boxes.every(box => box.x >= 0 && box.right <= width)).toBe(true)
  if (width === 1280) { expect(new Set(boxes.map(box => Math.round(box.y))).size).toBe(1); expect(boxes.every(box => box.height >= 42)).toBe(true) }
  await expect(detail.locator('.lock-status').first()).toHaveText('Locked')
  await page.screenshot({ path: info.outputPath('user-details.png'), fullPage: true })
  await detail.getByRole('button', { name: `View role details: ${pattern}`, exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox', { name: 'Find transaction code' }).fill('MIGO')
  await dialog.getByRole('textbox', { name: 'Find transaction code' }).press('Enter')
  await expect(dialog.locator('tr[data-transaction-match=true]:visible')).toHaveCount(2)
  await page.screenshot({ path: info.outputPath('sidebar-search.png') })
})
