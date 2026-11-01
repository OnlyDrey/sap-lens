import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { goTo, seedSources, type SeededSources } from './support'
let seeded: SeededSources
const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:EX1,MM - Exclusive one,ME21N,Create purchase order
FI,ZC:FI:VIEW:ENP,Finance view,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
FI,ZC:FI:VIEW:ENP,Finance view,ZS:EX2,FI - Exclusive two,FB03,Display document
FI,ZC:FI:VIEW:ENK,Finance view ENK,ZS:EX3,FI - Exclusive three,FB03,Display document
SD,ZC:SD:ORD:ENK,Orders ENK,ZS:EX4,SD - Exclusive four,VA03,Display sales
MM,ZC:MM:BUY:*,Buyer wildcard,ZS:W,MM - Wildcard,ME23N,Display purchase order
`
const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
U1,ZC:MM:BUY:ENP,G1,20200101,99991231
U2,ZC:FI:VIEW:ENP,G1,20200101,99991231
U3,ZC:FI:VIEW:ENP,G2,20200101,99991231
U3,ZC:MM:BUY:ENP,G2,20200101,99991231
U4,ZC:SD:ORD:ENK,G2,20200101,99991231
`
test.beforeEach(async ({ request }) => { seeded = await seedSources(request, { roles, users }) })
test.afterEach(async () => { await seeded.cleanup() })

const tile = (page: Page, title: string) => page.getByRole('article', { name: new RegExp(title) })

test('Add to access package and Add to comparison are independent toggles on each Role Lookup tile', { tag: '@smoke' }, async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Role Lookup')
  await expect(page.getByRole('article')).toHaveCount(5)
  const buyer = tile(page, 'Buyer plant')
  await buyer.getByRole('button', { name: 'Add to access package' }).click()
  await expect(buyer.getByRole('button', { name: 'Remove from access package' })).toHaveAttribute('aria-pressed', 'true')
  await expect(buyer.getByRole('button', { name: 'Add to comparison' })).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('button', { name: 'Access package (1)' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Compare now/ })).toHaveCount(0)
  await buyer.getByRole('button', { name: 'Add to comparison' }).click()
  await tile(page, 'Finance view$').getByRole('button', { name: 'Add to comparison' }).click()
  await expect(page.getByRole('button', { name: /Compare now/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Access package (1)' })).toBeVisible()
  await buyer.getByRole('button', { name: 'Remove from access package' }).click()
  await expect(buyer.getByRole('button', { name: 'Remove from comparison' })).toHaveAttribute('aria-pressed', 'true')
})

test('package: default suffix, per-role override, validation, copy, CSV, persistence and clearing', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Role Lookup')
  for (const title of ['Buyer plant', 'Finance view$', 'Buyer wildcard', 'Orders ENK']) await tile(page, title).getByRole('button', { name: 'Add to access package' }).click()
  await page.getByRole('button', { name: 'Access package (4)' }).click()
  const panel = page.getByRole('dialog', { name: 'Proposed access package' })
  await expect(panel).toContainText(/nothing is assigned or changed in SAP/i)
  await expect(panel.getByText('Found in your roles')).toHaveCount(0)
  await expect(panel.getByRole('listitem').first()).toContainText('Needs attention')
  await expect(panel.getByRole('listitem').first()).toContainText('Needs suffix')
  await panel.getByRole('combobox', { name: 'Package default suffix' }).click()
  await expect(page.getByRole('option', { name: 'ENP', exact: true })).toBeVisible(); await expect(page.getByRole('option', { name: 'ENK', exact: true })).toBeVisible()
  const row = (role: string) => panel.getByRole('listitem').filter({ has: page.getByRole('button', { name: `Remove ${role} from access package` }) })
  await panel.getByRole('combobox', { name: 'Package default suffix' }).fill('enk')
  await expect(row('ZC:MM:BUY:ENP')).toContainText('ZC:MM:BUY:ENK')
  await expect(row('ZC:MM:BUY:*')).toContainText('Invalid'); await expect(row('ZC:MM:BUY:*')).toContainText('Same name as another role')
  await row('ZC:MM:BUY:*').getByRole('textbox', { name: 'Suffix for ZC:MM:BUY:*' }).fill('eno')
  await expect(row('ZC:MM:BUY:*')).toContainText('ZC:MM:BUY:ENO')
  await expect(row('ZC:MM:BUY:*')).toContainText('Pattern match')
  await panel.getByRole('combobox', { name: 'Package default suffix' }).fill('ens')
  await expect(row('ZC:MM:BUY:ENP')).toContainText('ZC:MM:BUY:ENS')
  await expect(row('ZC:MM:BUY:*')).toContainText('ZC:MM:BUY:ENO') // the explicit override survives a default change
  await expect(row('ZC:SD:ORD:ENK')).toContainText('ZC:SD:ORD:ENS')
  await expect(row('ZC:SD:ORD:ENK')).toContainText('Needs attention'); await expect(row('ZC:SD:ORD:ENK')).toContainText('Check it in SAP')
  await expect(row('ZC:MM:BUY:ENP')).toContainText('Pattern match')
  await expect(panel.locator('.package-summary')).toContainText(/4 roles.*4 valid names.*2 pattern matches.*2 to check/)
  await panel.getByRole('button', { name: 'Copy all names' }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('ZC:FI:VIEW:ENS\nZC:MM:BUY:ENO\nZC:MM:BUY:ENS\nZC:SD:ORD:ENS')
  await row('ZC:MM:BUY:ENP').getByRole('button', { name: 'Copy generated SAP role name ZC:MM:BUY:ENS' }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('ZC:MM:BUY:ENS')
  const download = page.waitForEvent('download')
  await panel.getByRole('button', { name: /Export CSV/ }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/^sap-lens-access-package-\d{4}-\d{2}-\d{2}\.csv$/)
  const text = readFileSync((await file.path())!, 'utf8')
  expect(text.split('\r\n').filter(Boolean)).toEqual([
    '﻿"Generated SAP Role Name";"Role Description";"Suffix";"Validation"',
    '"ZC:FI:VIEW:ENS";"Finance view";"ENS";"Needs attention"', '"ZC:MM:BUY:ENO";"Buyer wildcard";"ENO";"Pattern match"', '"ZC:MM:BUY:ENS";"Buyer plant";"ENS";"Pattern match"', '"ZC:SD:ORD:ENS";"Orders ENK";"ENS";"Needs attention"',
  ])
  await row('ZC:SD:ORD:ENK').getByRole('button', { name: 'Remove ZC:SD:ORD:ENK from access package' }).click()
  await expect(panel.locator('.package-summary')).toContainText(/3 roles.*3 valid names.*2 pattern matches.*1 to check/)
  await page.keyboard.press('Escape')
  await goTo(page, 'Dashboard'); await goTo(page, 'Role Lookup')
  await expect(page.getByRole('button', { name: 'Access package (3)' })).toBeVisible()
  await page.getByRole('button', { name: 'Access package (3)' }).click()
  await expect(panel.getByRole('combobox', { name: 'Package default suffix' })).toHaveValue('ENS')
  await panel.getByRole('button', { name: 'Clear package' }).click()
  await page.getByRole('dialog', { name: 'Clear the access package?' }).getByRole('button', { name: 'Clear package' }).click()
  await expect(panel).toContainText('The access package is empty')
  await expect(page.getByRole('button', { name: /Access package \(/ })).toHaveCount(0) // the floating action exists only while the package has roles
})

test('Users lacking roles: Missing ANY and Missing ALL with a clearly shown operator', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  const usernames = () => page.getByRole('table').first().getByRole('link', { name: /^U\d$/ }).allInnerTexts().then(list => list.sort())
  await expect.poll(usernames).toEqual(['U1', 'U2', 'U3', 'U4'])
  const lack = page.getByRole('combobox', { name: 'Roles the user must lack', exact: true })
  for (const name of ['ZC:MM:BUY:ENP', 'ZC:FI:VIEW:ENP']) { await lack.fill(name); await page.getByRole('option', { name, exact: true }).click() }
  await lack.press('Escape')
  const mode = page.getByRole('group', { name: 'Missing role operator' })
  await expect(mode.getByRole('button', { name: 'Missing ANY' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('Missing ANY: users lacking at least one selected role.')).toBeVisible()
  await expect.poll(usernames).toEqual(['U1', 'U2', 'U4'])
  await mode.getByRole('button', { name: 'Missing ALL' }).click()
  await expect(page.getByText('Missing ALL: users lacking every selected role.')).toBeVisible()
  await expect.poll(usernames).toEqual(['U4'])
  await page.getByRole('button', { name: 'Remove Roles the user must lack ZC:MM:BUY:ENP' }).click()
  await expect.poll(usernames).toEqual(['U1', 'U4'])
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(mode).toHaveCount(0)
  await expect.poll(usernames).toEqual(['U1', 'U2', 'U3', 'U4'])
})

test('comparison: shared single roles expand inside their tile and exclusive roles are compact rows', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Role Lookup')
  await tile(page, 'Buyer plant').getByRole('button', { name: 'Add to comparison' }).click()
  await tile(page, 'Finance view$').getByRole('button', { name: 'Add to comparison' }).click()
  await page.getByRole('button', { name: /Compare now/ }).click()
  const shared = page.getByRole('article', { name: 'Single role ZS:SH' })
  await expect(shared).toBeVisible()
  const before = await shared.boundingBox()
  await shared.getByRole('button', { name: 'Expand single role ZS:SH' }).click()
  await expect(shared.getByRole('region', { name: 'Transactions for ZS:SH' })).toContainText('MIGO')
  const after = await shared.boundingBox()
  expect(after!.width).toBeCloseTo(before!.width, 0)
  expect(after!.height).toBeGreaterThan(before!.height)
  await expect(shared.locator('.role-entry-head')).toContainText('MM')
  const order = await shared.locator('.role-entry').first().evaluate(node => [...node.children].map(child => child.className.split(' ')[0]))
  expect(order.slice(0, 2)).toEqual(['role-entry-head', 'role-identifier'])
  const column = page.locator('.comparison-column').first()
  await expect(column.locator('.single-role-tile')).toHaveCount(0)
  const exclusive = column.locator('.single-role-row').first()
  await expect(exclusive).toBeVisible()
  await exclusive.getByRole('button', { name: /Expand single role/ }).click()
  await expect(exclusive.getByRole('region', { name: /Transactions for/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('the access package drawer keeps a compact header and a sticky action footer at 375px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Role Lookup')
  for (const title of ['Buyer plant', 'Orders ENK']) await tile(page, title).getByRole('button', { name: 'Add to access package' }).click()
  await page.getByRole('button', { name: 'Access package (2)' }).click()
  const panel = page.getByRole('dialog', { name: 'Proposed access package' })
  await expect(panel).toContainText('2 roles selected')
  // Clear package, Copy all names and Export CSV live in the sticky footer; the header only carries the title and Close.
  const clear = panel.locator('.package-footer').getByRole('button', { name: 'Clear package' })
  await expect(clear).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  // The footer (summary, copy, export) stays inside the viewport while the role list scrolls.
  const footer = panel.locator('.package-footer')
  await expect(footer.getByRole('button', { name: 'Copy all names' })).toBeVisible()
  const box = await footer.boundingBox()
  expect(box!.y + box!.height).toBeLessThanOrEqual(700 + 1)
  await panel.locator('.package-list').evaluate(node => node.scrollIntoView({ block: 'end' }))
  expect((await footer.boundingBox())!.y).toBeCloseTo(box!.y, 0)
})
