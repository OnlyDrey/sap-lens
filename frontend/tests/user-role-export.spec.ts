import { test, expect } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers } from './support'
let directory: string
const business = 'ZC:MM:BUY:ENP', release = 'ZO:MM:M:PR_REL_ST_SH_N6:ALL'
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-export-'))
  const catalogue = path.join(directory, 'catalogue.csv'), users = path.join(directory, 'users.csv')
  writeFileSync(catalogue, 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE\nMM,ZC:MM:BUY:EN*,Purchasing,ZD:BUY,Purchasing evidence,ME21N\nFI,ZC:FI:VIEW:*,Display,ZD:VIEW,Accounting evidence,ME21N\nMM,ZO:MM:M:PR_REL_ST_SH_N6:ALL,Release,ZD:REL,Release evidence,ME21N\n')
  const row = (username: string, role: string, group = 'GROUP_A', from = '20000101', to = '99991231', locked = '') => `${username},${role},${group},"Éva, ""Demo""",Example,${from},${to},${locked},20000101,99991231\n`
  writeFileSync(users, 'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,ROLE_VALID_FROM,ROLE_VALID_TO,USER_LOCKED,USER_VALID_FROM,USER_VALID_TO\n' +
    row('DEMO_EXPORT', business) + row('DEMO_EXPORT', 'ZC:FI:VIEW:ENO', '=1+1') + row('DEMO_EXPORT', release) + row('DEMO_EXPORT', business, 'GROUP_B', '20010101') +
    row('DEMO_EXPORT', 'ZC:EXPIRED', 'GROUP_A', '19900101', '19991231') + row('DEMO_EXPORT', 'ZC:FUTURE', 'GROUP_A', '29990101') +
    row('DEMO_EXPORT', 'ZD:HIDDEN') + row('DEMO_EXPORT', 'ZZ:HIDDEN') +
    Array.from({ length: 105 }, (_, i) => row('DEMO_EXPORT', `ZC:UNMAPPED:${i}`)).join('') +
    row('DEMO_LOCKED', business, 'G', '20000101', '99991231', 'X') + row('DEMO_UNLOCKED', business, 'G', '20000101', '99991231', '0') +
    row('DEMO_FUTURE', business).replace(',20000101,99991231\n', ',29990101,99991231\n') +
    row('DEMO_EXPIRED', business).replace(',20000101,99991231\n', ',19900101,19991231\n') +
    row('DEMO_UNKNOWN', business).replace(',20000101,99991231\n', ',,\n'))
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = catalogue; settings.user_csv_path = users
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }); rmSync(directory, { recursive: true, force: true }) })
async function openUser(page: import('@playwright/test').Page) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'User Access', exact: true }).click()
  await page.getByRole('link', { name: 'DEMO_EXPORT', exact: true }).click()
}
test('transaction search respects exact code, scope and status and opens catalogue evidence', async ({ page }) => {
  await openUser(page)
  await page.getByRole('tab', { name: 'All roles', exact: true }).click()
  await page.getByRole('textbox', { name: 'Find roles by transaction' }).fill(' me21n ')
  await expect(page.getByRole('button', { name: 'Search', exact: true })).toHaveCount(0)
  const details = page.getByRole('region', { name: 'User details', exact: true })
  await expect(details.getByRole('row')).toHaveCount(5) // header and four distinct assignments
  await details.getByText('Transaction mapping evidence',{exact:true}).first().click()
  await expect(details.getByRole('region',{name:'User role assignments',exact:true})).toContainText('ZD:BUY')
  await expect(details.getByRole('region', { name: 'User role assignments' })).toContainText('Purchasing')
  await expect(details).toContainText('may be incomplete')
  await expect(details).not.toContainText('associated transactions')
  await details.getByRole('button', { name: 'View role details: ZC:MM:BUY:EN*', exact: true }).first().click()
  await expect(page.getByRole('dialog')).toContainText('Purchasing evidence')
  await expect(page.getByRole('dialog')).not.toContainText('Unclassified')
  await expect(page.getByRole('dialog').locator('.single-role-heading .lucide-layers')).toHaveCount(1)
  await page.getByRole('button', { name: 'Expand single role ZD:BUY', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Investigate users with ME21N', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close role details' }).click()
  await page.getByRole('tab', { name: 'Release Roles — ZO:*', exact: true }).click()
  await expect(details.getByRole('row')).toHaveCount(2)
  await page.getByRole('textbox', { name: 'Find roles by transaction' }).fill('ME21')
  await expect(page.getByRole('button', { name: 'Search', exact: true })).toHaveCount(0)
  await expect(details).toContainText('No matching roles for this transaction')
  await page.getByRole('button', { name: 'Clear filter' }).click()
  await expect(details.getByRole('row')).toHaveCount(2)
})
test('CSV includes every filtered page, exact identifiers, dates, UTF-8 and safe spreadsheet fields', async ({ page }) => {
  await openUser(page)
  await page.getByRole('tab', { name: 'All roles', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Export CSV', exact: true })).toBeEnabled()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  const download = await downloadPromise
  const bytes = readFileSync((await download.path())!)
  expect(bytes.subarray(0, 3).toString('hex')).toBe('efbbbf')
  const csv = bytes.toString('utf8')
  expect(csv).toContain('"Éva, ""Demo"" Example"')
  expect(csv).toContain('"\'=1+1"')
  expect(csv).toContain('"9999-12-31"')
  expect(csv).toContain(`"${business}","Purchasing","Business"`)
  expect(csv).toContain(`"${release}"`)
  expect(csv).toContain('"ZC:UNMAPPED:104"')
  expect(csv).not.toContain('ZD:HIDDEN'); expect(csv).not.toContain('ZZ:HIDDEN'); expect(csv).not.toContain('ZC:EXPIRED')
  expect(csv.split('\r\n')).toHaveLength(112) // header + 110 rows + final empty line
  expect(download.suggestedFilename()).toMatch(/^sap-lens-DEMO_EXPORT-all-\d{4}-\d{2}-\d{2}\.csv$/)
  await page.getByLabel('Assignment status', { exact: true }).selectOption('expired')
  const expiredPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  const expired = readFileSync((await (await expiredPromise).path())!, 'utf8')
  expect(expired).toContain('ZC:EXPIRED'); expect(expired).not.toContain(business)
})
test('desktop CSV uses authenticated native save instead of a blocked browser download', async ({ page }) => {
  await openUser(page)
  await page.evaluate(() => {
    window.pywebview = { api: { choose_csv: async () => null, save_user_access_csv: async (token, filename, content) => { (window as unknown as { saved: unknown }).saved = { token, filename, content }; return true } } }
  })
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'CSV exported.' })).toBeVisible()
  const saved = await page.evaluate(() => (window as unknown as { saved: { token: string; content: string } }).saved)
  expect(saved.token).toBe('browser-test-session'); expect(saved.content).toContain(business)
})
for (const theme of ['light', 'dark']) for (const width of [800, 1280]) test(`separate validity and lock indicators ${theme} ${width}`, async ({ page, request }, info) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.theme = theme; await request.post('/api/configuration', { headers, data: settings })
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'User Access', exact: true }).click()
  await expect(page.getByRole('columnheader', { name: 'User status', exact: true })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Lock status', exact: true })).toBeVisible()
  const locked = page.getByRole('row').filter({ has: page.getByRole('link', { name: 'DEMO_LOCKED', exact: true }) })
  await expect(locked.locator('.lock-status')).toHaveText('Locked')
  await expect(locked.locator('.lock-status svg')).toHaveClass(/lucide-lock-keyhole/)
  const unlocked = page.getByRole('row').filter({ has: page.getByRole('link', { name: 'DEMO_UNLOCKED', exact: true }) })
  await expect(unlocked.locator('.lock-status')).toHaveText('Unlocked')
  await expect(unlocked.locator('.lock-status svg')).toHaveClass(/lucide-lock-open/)
  const unknown = page.getByRole('row').filter({ has: page.getByRole('link', { name: 'DEMO_EXPORT', exact: true }) })
  await expect(unknown.locator('.lock-status')).toHaveText('Unknown')
  await expect(unknown.locator('.evidence-success svg')).toHaveClass(/lucide-circle-check/)
  for (const [username, icon] of [['DEMO_FUTURE', 'circle-x'], ['DEMO_EXPIRED', 'circle-x'], ['DEMO_UNKNOWN', 'circle-help']]) {
    const row = page.getByRole('row').filter({ has: page.getByRole('link', { name: username, exact: true }) })
    await expect(row.locator(`td[aria-label="Account validity"] .evidence-badge svg.lucide-${icon}`)).toBeVisible()
  }
  const appearance = await locked.locator('.lock-status').evaluate(element => {
    const style = getComputedStyle(element), icon = element.querySelector('svg')!.getBoundingClientRect(), box = element.getBoundingClientRect()
    return { background: style.backgroundColor, border: style.borderWidth, centered: Math.abs(icon.y + icon.height / 2 - box.y - box.height / 2) < 1 }
  })
  expect(appearance.background).not.toBe('rgba(0, 0, 0, 0)')
  expect(appearance.border).toBe('0px'); expect(appearance.centered).toBe(true)
  await locked.locator('.lock-status').scrollIntoViewIfNeeded()
  await page.screenshot({ path: info.outputPath('directory.png'), fullPage: true })
  await page.getByRole('link', { name: 'DEMO_EXPORT', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Account Status', exact: true }).locator('.lock-status')).toHaveText('Unknown')
  await page.getByRole('tab', { name: 'All roles', exact: true }).click()
  await page.getByRole('textbox', { name: 'Find roles by transaction' }).fill('ME21N')
  await expect(page.getByRole('button', { name: 'Search', exact: true })).toHaveCount(0)
  await page.getByText('Transaction mapping evidence',{exact:true}).first().click(); await expect(page.getByRole('region',{name:'User role assignments',exact:true})).toContainText('ZD:BUY')
  await page.screenshot({ path: info.outputPath('details.png'), fullPage: true })
  await page.getByRole('button', { name: 'View role details: ZC:MM:BUY:EN*', exact: true }).first().click()
  await page.getByRole('button', { name: 'Expand single role ZD:BUY', exact: true }).click()
  await page.screenshot({ path: info.outputPath('sidebar.png'), fullPage: false })
})

test('changed source generation aborts export rather than downloading mixed pages', async ({ page }) => {
  await openUser(page)
  let downloaded = false
  page.on('download', () => { downloaded = true })
  await page.route('**/api/access/users/DEMO_EXPORT?**', async route => {
    if (new URL(route.request().url()).searchParams.get('offset') !== '100') return route.continue()
    const response = await route.fetch(), json = await response.json()
    await route.fulfill({ response, json: { ...json, data_revision: 'different-import' } })
  })
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Source data changed.' })).toBeVisible()
  expect(downloaded).toBe(false)
  await page.getByRole('textbox', { name: 'Find roles by transaction' }).fill('NO_SUCH_TRANSACTION')
  await expect(page.getByRole('button', { name: 'Search', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Export CSV', exact: true })).toBeDisabled()
})

test('desktop cancellation and unavailable bridge provide feedback without browser fallback', async ({ page }) => {
  await openUser(page)
  let downloaded = false
  page.on('download', () => { downloaded = true })
  await page.evaluate(() => { window.pywebview = { api: { choose_csv: async () => null, save_user_access_csv: async () => false } } })
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Export cancelled.' })).toBeVisible()
  await page.evaluate(() => { delete window.pywebview!.api.save_user_access_csv })
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Update the desktop application.' })).toBeVisible()
  expect(downloaded).toBe(false)
})
