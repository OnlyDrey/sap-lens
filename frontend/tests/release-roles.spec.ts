import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { goTo, seedSources, type SeededSources } from './support'
let seeded: SeededSources
const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
MM,ZC:MM:BUY:ENK,Buyer plant ENK,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
FI,ZC:FI:VIEW:ENP,Finance view,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
FI,ZC:FI:VIEW:ENK,Finance view ENK,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
`
const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
U1,ZO:MM:M:PR_REL_ST_E2_N1:ALL,G1,20200101,99991231
U1,ZO:MM:M:PO_REL_ST_E3_N2:ALL,G1,20200101,99991231
U2,ZO:MM:M:PR_REL_ST_E2_N1:ALL,G2,20200101,99991231
U2,ZO:MM:M:PR_REL_ST_N1_N1:ALL,G2,20200101,99991231
U2,ZO:MM:M:PR_REL_ST_A2_S1:ALL,G2,20200101,20210101
U3,ZO:UNKNOWN,G2,20200101,99991231
U3,ZC:MM:BUY:ENP,G2,20200101,99991231
`
test.beforeEach(async ({ request }) => { seeded = await seedSources(request, { roles, users }) })
test.afterEach(async () => { await seeded.cleanup() })

const open = async (page: Page, view: 'Table' | 'Matrix' = 'Table') => {
  await page.goto('/#session=browser-test-session'); await goTo(page, 'Release Roles')
  await page.getByRole('button', { name: view, exact: true }).click()
}
const pick = async (page: Page, label: string, option: string) => {
  const box = page.getByRole('combobox', { name: label, exact: true })
  await box.click(); await box.fill(option)
  await page.getByRole('option', { name: option, exact: true }).click()
}
const tableRoles = (page: Page) => page.getByRole('region', { name: 'Release role results' }).getByRole('button', { name: 'Release role details' }).allInnerTexts().then(list => list.sort())
const E2 = 'ZO:MM:M:PR_REL_ST_E2_N1:ALL', E3 = 'ZO:MM:M:PO_REL_ST_E3_N2:ALL', N1 = 'ZO:MM:M:PR_REL_ST_N1_N1:ALL'

test('Release Area is derived from the Release Group and multi-selects combine OR within and AND between filters', async ({ page }) => {
  await open(page)
  const sidebar = page.getByRole('complementary', { name: 'Filters' })
  await expect(sidebar.locator('legend').first()).toHaveText('Saved Filters')
  await expect(sidebar.getByRole('combobox', { name: 'Release Area', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: 'Release Area', exact: true }).click()
  await expect(page.getByRole('listbox', { name: 'Release Area options' }).getByRole('option')).toHaveText(['E', 'N'])
  await page.keyboard.press('Escape')
  await pick(page, 'Release Area', 'E')
  await expect.poll(() => tableRoles(page)).toEqual([E3, E2].sort())
  await expect(page.getByRole('region', { name: 'Release role results' }).getByRole('row').nth(1)).toContainText('E')
  // Release Group options narrow to the selected areas and widen with another area (OR).
  await page.getByRole('combobox', { name: 'Release Group', exact: true }).click()
  await expect(page.getByRole('listbox', { name: 'Release Group options' }).getByRole('option')).toHaveText(['E2', 'E3'])
  await page.keyboard.press('Escape')
  await pick(page, 'Release Area', 'N')
  await expect.poll(() => tableRoles(page)).toEqual([E3, E2, N1].sort())
  await page.getByRole('combobox', { name: 'Release Group', exact: true }).click()
  await expect(page.getByRole('listbox', { name: 'Release Group options' }).getByRole('option')).toHaveText(['E2', 'E3', 'N1'])
  await page.keyboard.press('Escape')
  // AND with Release Group and PR/PO; groups outside a removed area are dropped.
  await pick(page, 'Release Group', 'E3')
  await expect.poll(() => tableRoles(page)).toEqual([E3])
  await pick(page, 'Release Group', 'N1')
  await expect.poll(() => tableRoles(page)).toEqual([E3, N1].sort())
  await pick(page, 'PR/PO', 'PR')
  await expect.poll(() => tableRoles(page)).toEqual([N1])
  await page.getByRole('button', { name: 'Remove Release Area N' }).click()
  await expect(page.getByRole('button', { name: 'Remove Release Group N1' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Remove Release Group E3' })).toBeVisible()
  await page.getByRole('complementary', { name: 'Filters' }).getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(page.getByRole('button', { name: /^Remove Release/ })).toHaveCount(0)
  await expect.poll(() => tableRoles(page)).toHaveLength(4)
})

test('Matrix and Table stay consistent for Release Area filters', async ({ page }) => {
  await open(page, 'Matrix')
  await pick(page, 'Release Area', 'E')
  await expect(page.getByRole('table', { name: 'PR release matrix' }).getByRole('rowheader')).toHaveText(['E2'])
  await expect(page.getByRole('table', { name: 'PO release matrix' }).getByRole('rowheader')).toHaveText(['E3'])
  await expect(page.getByRole('table', { name: 'PR release matrix' }).getByRole('button', { name: /Investigate PR E2 N1: 2 users/ })).toBeVisible()
  await page.getByRole('button', { name: 'Table', exact: true }).click()
  await expect.poll(() => tableRoles(page)).toEqual([E3, E2].sort())
  await page.getByRole('button', { name: 'Matrix', exact: true }).click()
  await expect(page.getByRole('table', { name: 'PR release matrix' }).getByRole('rowheader')).toHaveText(['E2'])
})

test('Saved Filters live in the sidebar and restore Release Area and Release Group selections', async ({ page }) => {
  await open(page)
  const toolbar = page.locator('div.saved-filter-toolbar[aria-label="release saved filters"]')
  await expect(page.getByRole('complementary', { name: 'Filters' }).locator(toolbar)).toHaveCount(1)
  await pick(page, 'Release Area', 'E'); await pick(page, 'Release Group', 'E3')
  await toolbar.getByRole('button', { name: /Saved filters/ }).click()
  const dialog = page.getByRole('dialog', { name: 'release saved filters', exact: true })
  await dialog.getByLabel('Saved filter name').fill('East')
  await dialog.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(toolbar).toContainText('East')
  await page.getByRole('complementary', { name: 'Filters' }).getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect.poll(() => tableRoles(page)).toHaveLength(4)
  await toolbar.getByRole('button', { name: /Saved filters/ }).click()
  await dialog.getByRole('button', { name: 'Load', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Remove Release Area E' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Remove Release Group E3' })).toBeVisible()
  await expect.poll(() => tableRoles(page)).toEqual([E3])
})

test('release roles join the shared access package with exact names next to catalogue roles', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await open(page)
  const add = (role: string) => page.getByRole('button', { name: `Add ${role} to access package`, exact: true })
  await add(E2).click()
  await expect(page.getByRole('button', { name: `Remove ${E2} from access package`, exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'Access package (1)' })).toBeVisible()
  await goTo(page, 'Role Lookup')
  await page.getByRole('article', { name: /Buyer plant$/ }).getByRole('button', { name: 'Add to access package' }).click()
  await expect(page.getByRole('button', { name: 'Access package (2)' })).toBeVisible()
  await goTo(page, 'Release Roles')
  await page.getByRole('button', { name: 'Table', exact: true }).click()
  await expect(page.getByRole('button', { name: `Remove ${E2} from access package`, exact: true })).toBeVisible() // state is shared and synchronized
  await page.getByRole('button', { name: 'Access package (2)' }).click()
  const panel = page.getByRole('dialog', { name: 'Proposed access package' })
  await panel.getByRole('combobox', { name: 'Package default suffix' }).fill('ens')
  const row = (role: string) => panel.getByRole('listitem').filter({ has: page.getByRole('button', { name: `Remove ${role} from access package` }) })
  await expect(row(E2)).toContainText(E2)
  await expect(row(E2)).toContainText('Release role')
  await expect(row(E2).getByRole('textbox')).toHaveCount(0) // a package suffix never rewrites a release role
  await expect(row('ZC:MM:BUY:ENP')).toContainText('ZC:MM:BUY:ENS')
  await panel.getByRole('button', { name: 'Copy all names' }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`ZC:MM:BUY:ENS\n${E2}`)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: `Remove ${E2} from access package`, exact: true }).click()
  await expect(page.getByRole('button', { name: 'Access package (1)' })).toBeVisible()
})

test('Matrix has no Add to Access Package controls and the Table keeps them', async ({ page }) => {
  await open(page, 'Matrix')
  await expect(page.getByRole('button', { name: /access package/i })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Investigate PR E2 N1: 2 users/ })).toBeVisible()
  await page.getByRole('button', { name: 'Table', exact: true }).click()
  await expect(page.getByRole('button', { name: `Add ${E2} to access package`, exact: true })).toBeVisible()
})

test('Table pagination offers 10, 20, 50 and 100 rows, resets to the first page and clamps', async ({ page, request }) => {
  await seeded.cleanup()
  const many = Array.from({ length: 25 }, (_, i) => `U1,ZO:MM:M:PR_REL_ST_E${i + 1}_N1:ALL,G1,20200101,99991231`).join('\n')
  seeded = await seedSources(request, { roles, users: `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n${many}\n` })
  await open(page)
  const pager = page.getByRole('navigation', { name: 'Release role pages' })
  const size = pager.getByRole('combobox', { name: 'Release role pages: rows per page' })
  await expect(size.locator('option')).toHaveText(['10', '20', '50', '100'])
  await expect(size).toHaveValue('20')
  await expect(pager.getByRole('status')).toHaveText('1–20 of 25')
  await pager.getByRole('button', { name: 'Next' }).click()
  await expect(pager.getByRole('status')).toHaveText('21–25 of 25')
  await size.selectOption('10')
  await expect(pager.getByRole('status')).toHaveText('1–10 of 25')
  await expect(page.getByRole('region', { name: 'Release role results' }).getByRole('button', { name: 'Release role details' })).toHaveCount(10)
  await size.selectOption('100')
  await expect(pager.getByRole('status')).toHaveText('1–25 of 25')
})

test('bulk actions add, copy and export distinct filtered roles without changing the assignment export', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await open(page)
  await pick(page, 'Release Area', 'E')
  const actions = page.getByRole('group', { name: 'Filtered release role actions' })
  await expect(actions.getByRole('button', { name: 'Add filtered roles' })).toBeEnabled()
  await actions.getByRole('button', { name: 'Copy role names' }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${E3}\n${E2}`.split('\n').sort((a, b) => a.localeCompare(b)).join('\n'))
  await actions.getByRole('button', { name: 'Add filtered roles' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Added 2 release roles to the access package; 0 already selected.' })).toBeVisible()
  await page.getByRole('button', { name: `Remove ${E3} from access package`, exact: true }).click()
  await actions.getByRole('button', { name: 'Add filtered roles' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Added 1 release role to the access package; 1 already selected.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Access package (2)' })).toBeVisible()
  const roleList = page.waitForEvent('download')
  await actions.getByRole('button', { name: 'Export role list' }).click()
  const file = await roleList
  expect(file.suggestedFilename()).toMatch(/^sap-lens-release-role-list-review-\d{4}-\d{2}-\d{2}\.csv$/)
  const lines = readFileSync((await file.path())!, 'utf8').split('\r\n').filter(Boolean)
  expect(lines).toEqual(['﻿"ROLE_NAME";"ROLE_DESCRIPTION";"RELEASE_AREA";"RELEASE_GROUP";"RELEASE_STRATEGY";"PR_PO"',
    `"${E3}";"";"E";"E3";"N2";"PO"`, `"${E2}";"";"E";"E2";"N1";"PR"`])
  const assignments = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  const assignmentFile = await assignments
  expect(assignmentFile.suggestedFilename()).toMatch(/^sap-lens-release-roles-review-/)
  expect(readFileSync((await assignmentFile.path())!, 'utf8').split('\r\n').filter(Boolean)).toHaveLength(1 + 3)
})

test('large bulk additions require confirmation and filters with no match disable the actions', async ({ page, request }) => {
  const many = 'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n' + Array.from({ length: 520 }, (_, i) => `U${i},ZO:MM:M:PR_REL_ST_E${i}_N1:ALL,G1,20200101,99991231`).join('\n') + '\n'
  await seeded.cleanup(); seeded = await seedSources(request, { roles, users: many })
  await open(page)
  const actions = page.getByRole('group', { name: 'Filtered release role actions' })
  await actions.getByRole('button', { name: 'Add filtered roles' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add many release roles?' })
  await expect(dialog).toContainText('520 distinct release roles')
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByRole('button', { name: /Access package \(/ })).toHaveCount(0)
  await actions.getByRole('button', { name: 'Add filtered roles' }).click()
  await page.getByRole('dialog', { name: 'Add many release roles?' }).getByRole('button', { name: 'Add 520 roles' }).click()
  await expect(page.getByRole('button', { name: 'Access package (520)' })).toBeVisible()
  await pick(page, 'PR/PO', 'PR'); await page.getByRole('combobox', { name: 'Release role name', exact: true }).fill('NO_SUCH_ROLE')
  await expect(actions.getByRole('button', { name: 'Add filtered roles' })).toBeDisabled()
  await expect(actions.getByRole('button', { name: 'Export role list' })).toBeDisabled()
})

test('Release Roles filters work from the keyboard and without horizontal scroll at 375 px', async ({ page }) => {
  await open(page)
  const area = page.getByRole('combobox', { name: 'Release Area', exact: true })
  await area.focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: /^Remove Release Area/ })).toHaveCount(1)
  await page.setViewportSize({ width: 375, height: 800 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.getByRole('button', { name: /^Filters/ }).click()
  await expect(page.getByRole('dialog', { name: 'Filters' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Release Group', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Filters' })).toBeHidden()
})

test('SAP User Groups are multi-select and username or role search accepts several values', async ({ page }) => {
  await open(page)
  const names = async () => tableRoles(page)
  const all = await names()
  expect(all.length).toBeGreaterThan(1)
  await pick(page, 'Release SAP User Group', 'G1')
  await expect.poll(async () => (await names()).length).toBeLessThan(all.length)
  const first = await names()
  await pick(page, 'Release SAP User Group', 'G2')
  await expect(page.getByRole('button', { name: 'Remove Release SAP User Group G1', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Remove Release SAP User Group G2', exact: true })).toBeVisible()
  const both = await names()
  expect(both.length).toBeGreaterThanOrEqual(first.length)
  await page.getByRole('button', { name: 'Remove Release SAP User Group G2', exact: true }).click()
  await expect.poll(names).toEqual(first)
  // Several users in one search field: partial text per value, OR between values.
  await page.getByRole('button', { name: 'Remove Release SAP User Group G1', exact: true }).click()
  const username = page.getByRole('combobox', { name: 'Release username', exact: true })
  await username.fill('u1')
  await username.press('Escape')
  const one = await names()
  await username.fill('u2')
  await username.press('Escape')
  const two = await names()
  await username.fill('u1, u2')
  await username.press('Escape')
  await expect.poll(names).toEqual([...new Set([...one, ...two])].sort())
})
