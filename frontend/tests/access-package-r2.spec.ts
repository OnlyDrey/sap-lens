import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { goTo, seedSources, type SeededSources } from './support'

const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
FI,ZC:FI:VIEW:ENP,Finance view,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
FI,ZC:FI:VIEW:ENK,Finance view ENK,ZS:EX3,FI - Exclusive three,FB03,Display document
HR,ZC:HR:MISC:XYZ,Human resources exact,ZS:EX5,HR - Exclusive five,PA20,Display HR master data
SD,ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP,Long sales role,ZS:EX6,SD - Exclusive six,VA03,Display sales
`
let seeded: SeededSources
test.beforeEach(async ({ request }) => { seeded = await seedSources(request, { roles }) })
test.afterEach(async () => { await seeded.cleanup() })

const open = async (page: Page, titles: string[]) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
  for (const title of titles) await page.getByRole('article', { name: new RegExp(title) }).getByRole('button', { name: 'Add to access package' }).click()
  await page.getByRole('button', { name: new RegExp(`Access package \\(${titles.length}\\)`) }).click()
  return page.getByRole('dialog', { name: 'Proposed access package' })
}
const row = (panel: ReturnType<Page['getByRole']>, page: Page, role: string) => panel.getByRole('listitem').filter({ has: page.getByRole('button', { name: `Remove ${role} from access package` }) })

test('package rows show one codeblock, the suffix field right of it and a compact status; no separate generated-name block', async ({ page }) => {
  const panel = await open(page, ['Buyer plant'])
  const item = row(panel, page, 'ZC:MM:BUY:ENP')
  await expect(item.locator('.role-identifier')).toHaveCount(1)
  await expect(panel.getByText('Generated SAP role name', { exact: true })).toHaveCount(0)
  await expect(panel.getByText('Found in your roles')).toHaveCount(0)
  await expect(item).toContainText('Needs suffix')
  await panel.getByRole('combobox', { name: 'Package default suffix' }).fill('ens')
  const code = item.locator('code'); await expect(code).toHaveText('ZC:MM:BUY:ENS') // the codeblock shows the generated name once a suffix applies
  const field = item.getByRole('textbox', { name: 'Suffix for ZC:MM:BUY:ENP' })
  const [a, b] = [await code.boundingBox(), await field.boundingBox()]
  expect(b!.x).toBeGreaterThan(a!.x + a!.width - 1) // right of the codeblock
  expect(Math.abs((b!.y + b!.height / 2) - (a!.y + a!.height / 2))).toBeLessThan(a!.height) // on the same line
  await expect(code).toHaveCSS('white-space', 'nowrap')
})

test('exact roles without suffix variants keep their name and disable suffix editing with an explanation', async ({ page }) => {
  const panel = await open(page, ['Human resources exact', 'Buyer plant'])
  await panel.getByRole('combobox', { name: 'Package default suffix' }).fill('ens')
  const exact = row(panel, page, 'ZC:HR:MISC:XYZ')
  await expect(exact.locator('code')).toHaveText('ZC:HR:MISC:XYZ')
  const field = exact.getByRole('textbox', { name: 'Suffix for ZC:HR:MISC:XYZ' })
  await expect(field).toBeDisabled()
  await expect(exact).toContainText('Exact role name')
  await expect(exact).toContainText('Confirmed')
  const eligible = row(panel, page, 'ZC:MM:BUY:ENP')
  await expect(eligible.getByRole('textbox', { name: 'Suffix for ZC:MM:BUY:ENP' })).toBeEnabled()
  await expect(eligible.locator('code')).toHaveText('ZC:MM:BUY:ENS')
})

test('unconfirmed names can be copied and exported with a warning, invalid names never are', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const panel = await open(page, ['Finance view$', 'Long sales role', 'Human resources exact'])
  await panel.getByRole('combobox', { name: 'Package default suffix' }).fill('enq') // ZC:FI:VIEW:ENQ is valid but not in the catalogue
  const finance = row(panel, page, 'ZC:FI:VIEW:ENP')
  await expect(finance).toContainText('Unconfirmed')
  await expect(finance).toContainText('not confirmed by the imported catalogue')
  const long = row(panel, page, 'ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP')
  await expect(long).toContainText('Invalid')
  await expect(long).toContainText('not a valid SAP role name')
  await expect(panel.locator('.package-summary')).toContainText(/2 valid names.*1 unconfirmed.*1 need attention/)
  await panel.getByRole('button', { name: 'Copy all names' }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('ZC:FI:VIEW:ENQ\nZC:HR:MISC:XYZ')
  await expect(page.getByText(/1 name is not confirmed by the imported catalogue/).first()).toBeVisible()
  const download = page.waitForEvent('download')
  await panel.getByRole('button', { name: /Export CSV/ }).click()
  const text = readFileSync((await (await download).path())!, 'utf8')
  expect(text.split('\r\n').filter(Boolean)).toEqual([
    '﻿"Generated SAP Role Name";"Role Description";"Suffix";"Validation"',
    '"ZC:FI:VIEW:ENQ";"Finance view";"ENQ";"Unconfirmed"', '"ZC:HR:MISC:XYZ";"Human resources exact";"";"Confirmed"',
  ])
})

test('the sticky action bar holds Clear package, Copy all names and Export CSV with icons', async ({ page }) => {
  const panel = await open(page, ['Buyer plant'])
  const footer = panel.locator('.package-footer')
  for (const name of ['Clear package', 'Copy all names', /Export CSV/]) await expect(footer.getByRole('button', { name }).locator('svg').first()).toBeVisible()
  await expect(panel.locator('header, .ui-side-panel-header').getByRole('button', { name: 'Clear package' })).toHaveCount(0)
  const clear = await footer.getByRole('button', { name: 'Clear package' }).boundingBox(), copy = await footer.getByRole('button', { name: 'Copy all names' }).boundingBox()
  expect(clear!.x).toBeLessThan(copy!.x) // Clear on the left, copy and export grouped on the right
})
