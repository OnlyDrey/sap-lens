import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const headers = { 'X-SAP-Lens': 'browser-test-session' }
let directory: string
const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:A,Alpha purchasing,ZS:A1,MM - Purchasing,MIGO,Goods movement
MM,ZC:MM:A,Alpha purchasing,ZS:A2,MM - Purchasing,ME21N,Create purchase order
MM,ZC:MM:D,Delta purchasing,ZS:D,MM - Purchasing,ME23N,Display purchase order
FI,ZC:FI:B,Beta finance,ZS:B,FI - Finance,MIGO,Goods movement
SD,ZC:SD:C,Gamma sales,ZS:C,SD - Sales,VA03,Display sales
SD,ZC:SD:E,Empty sales,ZS:E,SD - Sales,,
`
const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
U1,ZC:MM:A,G1,20200101,99991231
U2,ZC:FI:B,G1,20200101,99991231
U3,ZC:SD:C,G2,20200101,99991231
U4,ZC:MM:D,G2,20200101,99991231
U4,ZC:SD:C,G2,20200101,99991231
U5,ZC:XX:MISSING,G2,20200101,99991231
U6,ZC:MM:A,G2,20000101,20010101
U7,ZC:MM:D,G2,20200101,99991231
U7,ZC:XX:MISSING,G2,20200101,99991231
`
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-transaction-filter-'))
  const roleFile = path.join(directory, 'roles.csv'), userFile = path.join(directory, 'users.csv')
  writeFileSync(roleFile, roles); writeFileSync(userFile, users)
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = roleFile; settings.user_csv_path = userFile
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

const nav = (page: Page, name: string) => page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name, exact: true }).click()
async function openRoles(page: Page) {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'Role Lookup')
  await expect(page.getByRole('article')).toHaveCount(5)
}
async function openUsers(page: Page) {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'User Access')
  await expect(page.getByRole('link', { name: 'U1', exact: true })).toBeVisible()
}
const filter = (page: Page, label: string) => page.getByRole('group', { name: label, exact: true })
const roleFilter = (page: Page) => filter(page, 'Filter catalogue by transaction')
const userFilter = (page: Page) => filter(page, 'Filter users by transaction')
const exclude = (group: ReturnType<typeof roleFilter>) => group.getByRole('checkbox', { name: 'Exclude matching transactions' })
const add = async (group: ReturnType<typeof roleFilter>, code: string) => {
  const input = group.getByRole('textbox')
  await input.fill(code)
  await input.press('Enter')
}
const roleNames = async (page: Page) => (await page.getByRole('article').getByRole('heading').allInnerTexts()).map((text) => text.trim()).sort()
const listed = async (page: Page) => (await page.getByRole('table').first().getByRole('link', { name: /^U\d$/ }).allInnerTexts()).sort()

test.describe('Role Lookup', () => {
  test('one compact checkbox; unchecked keeps positive matching with AND/OR and wildcards', async ({ page }) => {
    await openRoles(page)
    const group = roleFilter(page)
    await expect(group.getByRole('textbox')).toHaveCount(1)
    await expect(exclude(group)).not.toBeChecked()
    await expect(page.getByRole('group', { name: 'Transaction match type' })).toHaveCount(0)
    await add(group, 'MIGO')
    await expect(page.getByRole('article')).toHaveCount(2)
    await add(group, 'ME*')
    await expect(page.getByRole('article')).toHaveCount(1)
    await expect(group.getByRole('button', { name: 'AND', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await group.getByRole('button', { name: 'OR', exact: true }).click()
    await expect(page.getByRole('article')).toHaveCount(3)
    await expect(page.getByText('Match all', { exact: false })).toHaveCount(0)
    await expect(page.getByText('Match any', { exact: false })).toHaveCount(0)
    await expect(page.locator('.transaction-help')).toHaveCount(0)
  })

  test('exclude: AND means not all together, OR means none; roles without mappings never appear', async ({ page }) => {
    await openRoles(page)
    const group = roleFilter(page)
    await add(group, 'MIGO')
    await exclude(group).check()
    await expect(page.getByRole('article')).toHaveCount(2)
    expect(await roleNames(page)).toEqual(expect.arrayContaining([]))
    await expect(page.getByRole('article').filter({ hasText: 'ZC:SD:E' })).toHaveCount(0)
    await add(group, 'ME21N')
    // AND: not (MIGO and ME21N together) -> B, D, C.   OR: neither -> D, C.
    await expect(page.getByRole('article')).toHaveCount(3)
    await expect(page.getByRole('article').filter({ hasText: 'ZC:FI:B' })).toHaveCount(1)
    await group.getByRole('button', { name: 'OR', exact: true }).click()
    await expect(page.getByRole('article')).toHaveCount(2)
    await expect(page.getByRole('article').filter({ hasText: 'ZC:FI:B' })).toHaveCount(0)
    await expect(page.locator('.transaction-help')).toContainText('with none of these codes')
    await group.getByRole('button', { name: 'AND', exact: true }).click()
    await expect(page.locator('.transaction-help')).toContainText('lacking at least one')
  })

  test('toggling keeps the codes, wildcards work, combines with module and text filters, Clear all restores positive', async ({ page }) => {
    await openRoles(page)
    const group = roleFilter(page)
    await add(group, 'ME*')
    await expect(page.getByRole('article')).toHaveCount(2)
    await exclude(group).check()
    await expect(group.getByRole('button', { name: 'Remove transaction ME*' })).toBeVisible()
    await expect(page.getByRole('article')).toHaveCount(2)
    await expect(page.getByRole('article').filter({ hasText: 'ZC:FI:B' })).toHaveCount(1)
    await exclude(group).uncheck()
    await expect(group.getByRole('button', { name: 'Remove transaction ME*' })).toBeVisible()
    await expect(page.getByRole('article').filter({ hasText: 'ZC:MM:A' })).toHaveCount(1)
    await exclude(group).check()
    await page.getByRole('group', { name: 'SAP areas', exact: true }).getByRole('button', { name: /^SD / }).click()
    await expect(page.getByRole('article')).toHaveCount(1)
    await page.getByPlaceholder('Search roles by name or description...').fill('beta')
    await expect(page.getByRole('article')).toHaveCount(0)
    await page.getByRole('button', { name: 'Clear all filters', exact: true }).click()
    await expect(page.getByRole('article')).toHaveCount(5)
    await expect(exclude(group)).not.toBeChecked()
    await expect(group.getByRole('textbox')).toHaveValue('')
  })

  test('keyboard: the checkbox is reachable and operable, layout fits narrow screens', async ({ page }) => {
    for (const width of [375, 800, 1280]) {
      await page.goto('about:blank')
      await page.setViewportSize({ width, height: 800 })
      await openRoles(page)
      const group = roleFilter(page), input = group.getByRole('textbox')
      await input.focus()
      await page.keyboard.press('Tab')
      await expect(exclude(group)).toBeFocused()
      await page.keyboard.press('Space')
      await expect(exclude(group)).toBeChecked()
      await page.keyboard.press('Shift+Tab')
      await expect(input).toBeFocused()
      const [a, b] = await Promise.all([input.boundingBox(), exclude(group).boundingBox()])
      expect(a!.y + a!.height).toBeLessThanOrEqual(b!.y + 1)
      expect(b!.x + b!.width).toBeLessThanOrEqual(width)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    }
  })

  test('the exclusion is saved in a Saved Filter', async ({ page, request }) => {
    await openRoles(page)
    await add(roleFilter(page), 'MIGO')
    await exclude(roleFilter(page)).check()
    await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    const menu = page.getByRole('dialog', { name: 'roles saved filters', exact: true })
    await menu.getByLabel('Saved filter name', { exact: true }).fill('Roles without MIGO')
    await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
    await expect(menu).toContainText('Saved filters updated.')
    const stored = (await (await request.get('/api/saved-filters', { headers })).json()).items.find((item: { name: string }) => item.name === 'Roles without MIGO')
    expect([stored.filters.transactionExclude, stored.filters.tcodes]).toEqual([true, ['MIGO']])
    await menu.getByRole('button', { name: 'Clear filters', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(exclude(roleFilter(page))).not.toBeChecked()
    await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    const box = page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('combobox', { name: 'Saved filter', exact: true })
    await box.click(); await box.fill('without')
    await page.getByRole('option').filter({ hasText: 'Roles without MIGO' }).first().click()
    await page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('button', { name: 'Load', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(exclude(roleFilter(page))).toBeChecked()
    await expect(page.getByRole('article')).toHaveCount(2)
    page.once('dialog', (dialog) => dialog.accept())
    await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    await page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('button', { name: 'Delete', exact: true }).click()
    await expect.poll(async () => (await (await request.get('/api/saved-filters', { headers })).json()).items.length).toBe(0)
  })
})

test.describe('User Access', () => {
  test('positive matching is unchanged and exclude follows the same AND/OR semantics with the same control', async ({ page }) => {
    await openUsers(page)
    const group = userFilter(page)
    await expect(exclude(group)).not.toBeChecked()
    await add(group, 'MIGO')
    await expect.poll(() => listed(page)).toEqual(['U1', 'U2'])
    await exclude(group).check()
    await expect.poll(() => listed(page)).toEqual(['U3', 'U4'])
    await add(group, 'ME21N')
    // AND: not both together -> U2, U3, U4. OR: neither -> U3, U4.
    await expect.poll(() => listed(page)).toEqual(['U2', 'U3', 'U4'])
    await group.getByRole('button', { name: 'OR', exact: true }).click()
    await expect.poll(() => listed(page)).toEqual(['U3', 'U4'])
    await expect(page.locator('.transaction-help')).toContainText('Users with none of these codes')
    await exclude(group).uncheck()
    await expect(group.getByRole('button', { name: 'Remove transaction MIGO' })).toBeVisible()
    await expect.poll(() => listed(page)).toEqual(['U1', 'U2'])
  })

  test('users with unmapped roles or no eligible assignment are never reported as lacking a transaction; wildcards and filters combine', async ({ page }) => {
    await openUsers(page)
    const group = userFilter(page)
    await add(group, 'ME*')
    await exclude(group).check()
    await expect.poll(() => listed(page)).toEqual(['U2', 'U3'])
    for (const unknown of ['U5', 'U6', 'U7']) await expect(page.getByRole('button', { name: unknown, exact: true })).toHaveCount(0)
    await page.getByRole('combobox', { name: 'SAP User Group', exact: true }).click()
    await page.getByRole('combobox', { name: 'SAP User Group', exact: true }).fill('G2')
    await page.getByRole('option', { name: 'G2', exact: true }).click()
    await expect.poll(() => listed(page)).toEqual(['U3'])
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
    await expect(exclude(group)).not.toBeChecked()
    await expect(group.getByRole('textbox')).toHaveValue('')
    await expect.poll(() => listed(page)).toEqual(['U1', 'U2', 'U3', 'U4', 'U5', 'U6', 'U7'])
  })

  test('CSV export matches the listing in both modes and the checkbox is keyboard operable', async ({ page }) => {
    await openUsers(page)
    const group = userFilter(page)
    await add(group, 'MIGO')
    await group.getByRole('textbox').focus()
    await page.keyboard.press('Tab')
    await expect(exclude(group)).toBeFocused()
    await page.keyboard.press('Space')
    await expect(exclude(group)).toBeChecked()
    await expect.poll(() => listed(page)).toEqual(['U3', 'U4'])
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
    const file = readFileSync((await (await download).path())!, 'utf8')
    const names = new Set(file.split(/\r?\n/).slice(1).filter(Boolean).map((line) => line.split(';')[0].replaceAll('"', '')))
    expect([...names].sort()).toEqual(['U3', 'U4'])
  })

  test('the exclusion is saved in a Saved Filter and the layout fits narrow screens', async ({ page, request }) => {
    await page.setViewportSize({ width: 375, height: 800 })
    await openUsers(page)
    await add(userFilter(page), 'MIGO')
    await exclude(userFilter(page)).check()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.locator('div.saved-filter-toolbar[aria-label="users saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    const menu = page.getByRole('dialog', { name: 'users saved filters', exact: true })
    await menu.getByLabel('Saved filter name', { exact: true }).fill('Users without MIGO')
    await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
    await expect(menu).toContainText('Saved filters updated.')
    const stored = (await (await request.get('/api/saved-filters', { headers })).json()).items.find((item: { name: string }) => item.name === 'Users without MIGO')
    expect([stored.filters.transactionExclude, stored.filters.tcodes]).toEqual([true, ['MIGO']])
    page.once('dialog', (dialog) => dialog.accept())
    await menu.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect.poll(async () => (await (await request.get('/api/saved-filters', { headers })).json()).items.length).toBe(0)
  })
})
