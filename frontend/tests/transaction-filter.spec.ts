import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers, goTo } from './support'
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
  // Saved filters live outside the configuration reset; leave none behind for other specs sharing this server.
  for (const item of (await (await request.get('/api/saved-filters', { headers })).json()).items) await request.post('/api/saved-filters/delete', { headers, data: { id: item.id, expected: item.modified } })
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

/** Wide screens keep the filter sidebar open; narrow ones use a drawer that has to be opened first. */
async function openFilters(page: Page) {
  const width = page.viewportSize()!.width
  if (width < 1024) await page.getByRole('button', { name: /^Filters/ }).click()
}
async function openRoles(page: Page) {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Role Lookup')
  await expect(page.getByRole('article')).toHaveCount(5)
  await openFilters(page)
}
async function openUsers(page: Page) {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  await expect(page.getByRole('link', { name: 'U1', exact: true })).toBeVisible()
  await openFilters(page)
}
const filter = (page: Page, label: string) => page.getByRole('group', { name: label, exact: true })
const roleInclude = (page: Page) => filter(page, 'Filter catalogue by transaction')
const roleExclude = (page: Page) => filter(page, 'Exclude roles by transaction')
const userInclude = (page: Page) => filter(page, 'Filter users by transaction')
const userExclude = (page: Page) => filter(page, 'Exclude users by transaction')
const mode = (page: Page, label: string, name: 'ALL' | 'ANY') => page.getByRole('group', { name: `${label} matching`, exact: true }).getByRole('button', { name, exact: true })
const add = async (group: ReturnType<typeof roleInclude>, code: string) => {
  const input = group.getByRole('textbox')
  await input.fill(code)
  await input.press('Enter')
}
const listed = async (page: Page) => (await page.getByRole('table').first().getByRole('link', { name: /^U\d$/ }).allInnerTexts()).sort()
const articles = (page: Page, role: string) => page.getByRole('article').filter({ hasText: role })

test.describe('Role Lookup', () => {
  test('include and exclude are separate groups; include keeps ALL/ANY and wildcards', async ({ page }) => {
    await openRoles(page)
    const include = roleInclude(page)
    await expect(include.getByRole('textbox')).toHaveCount(1)
    await expect(roleExclude(page).getByRole('textbox')).toHaveCount(1)
    await expect(page.getByRole('checkbox', { name: 'Exclude matching transactions' })).toHaveCount(0)
    await add(include, 'MIGO')
    await expect(page.getByRole('article')).toHaveCount(2)
    await add(include, 'ME*')
    await expect(page.getByRole('article')).toHaveCount(1)
    await expect(mode(page, 'Filter catalogue by transaction', 'ALL')).toHaveAttribute('aria-pressed', 'true')
    await expect(include).toContainText('ALL: roles holding every one of these transactions.')
    await mode(page, 'Filter catalogue by transaction', 'ANY').click()
    await expect(page.getByRole('article')).toHaveCount(3)
    await expect(include).toContainText('ANY: roles holding at least one of these transactions.')
  })

  test('exclude ANY drops roles holding at least one code, ALL only roles holding every code; roles without mappings never appear', async ({ page }) => {
    await openRoles(page)
    const group = roleExclude(page)
    await add(group, 'MIGO')
    await expect(page.getByRole('article')).toHaveCount(2)
    await expect(articles(page, 'ZC:SD:E')).toHaveCount(0)
    await add(group, 'ME21N')
    // ANY (default): neither code -> D, C.   ALL: not both together -> B, D, C.
    await expect(mode(page, 'Exclude roles by transaction', 'ANY')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('article')).toHaveCount(2)
    await expect(articles(page, 'ZC:FI:B')).toHaveCount(0)
    await expect(group).toContainText('leave out roles holding at least one of these transactions')
    await mode(page, 'Exclude roles by transaction', 'ALL').click()
    await expect(page.getByRole('article')).toHaveCount(3)
    await expect(articles(page, 'ZC:FI:B')).toHaveCount(1)
    await expect(group).toContainText('leave out roles holding every one of these transactions')
    await expect(group).toContainText('Roles without mapped transactions are not listed.')
  })

  test('include and exclude combine, keep their codes independently and combine with module and text filters; Clear filters resets both', async ({ page }) => {
    await openRoles(page)
    const include = roleInclude(page), exclude = roleExclude(page)
    await add(include, 'MIGO'); await add(include, 'ME23N')
    await mode(page, 'Filter catalogue by transaction', 'ANY').click()
    await expect(page.getByRole('article')).toHaveCount(3) // A, B, D
    await add(exclude, 'ME21N')
    await expect(page.getByRole('article')).toHaveCount(2) // B, D: A holds ME21N
    await expect(articles(page, 'ZC:MM:A')).toHaveCount(0)
    await expect(include.getByRole('button', { name: 'Remove transaction MIGO' })).toBeVisible()
    await expect(exclude.getByRole('button', { name: 'Remove transaction ME21N' })).toBeVisible()
    await add(exclude, 'MIGO') // contradictory with the include group: nothing can satisfy both
    await mode(page, 'Exclude roles by transaction', 'ANY').click()
    await expect(page.getByRole('article')).toHaveCount(1) // only D holds neither excluded code
    await exclude.getByRole('button', { name: 'Remove transaction MIGO' }).click()
    await expect(page.getByRole('article')).toHaveCount(2)
    await page.getByRole('group', { name: 'SAP areas', exact: true }).getByRole('button', { name: /^MM / }).click()
    await expect(page.getByRole('article')).toHaveCount(1)
    await page.getByPlaceholder('Search roles by name or description...').fill('beta')
    await expect(page.getByRole('article')).toHaveCount(0)
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
    await expect(page.getByRole('article')).toHaveCount(5)
    await expect(include.getByRole('textbox')).toHaveValue('')
    await expect(exclude.locator('.transaction-chip')).toHaveCount(0)
  })

  test('keyboard: include, then exclude, are reachable in order and the layout fits narrow screens', async ({ page }) => {
    for (const width of [375, 800, 1280]) {
      await page.goto('about:blank')
      await page.setViewportSize({ width, height: 800 })
      await openRoles(page)
      const include = roleInclude(page).getByRole('textbox'), exclude = roleExclude(page).getByRole('textbox')
      await include.focus()
      await page.keyboard.press('Tab')
      await expect(exclude).toBeFocused()
      await page.keyboard.press('Shift+Tab')
      await expect(include).toBeFocused()
      const [a, b] = await Promise.all([include.boundingBox(), exclude.boundingBox()])
      expect(a!.y + a!.height).toBeLessThanOrEqual(b!.y + 1)
      expect(b!.x + b!.width).toBeLessThanOrEqual(width)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    }
  })

  test('both groups and their modes are saved in a Saved Filter', async ({ page, request }) => {
    await openRoles(page)
    await add(roleInclude(page), 'MIGO'); await add(roleExclude(page), 'ME21N'); await add(roleExclude(page), 'VA03')
    await mode(page, 'Exclude roles by transaction', 'ALL').click()
    await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    const menu = page.getByRole('dialog', { name: 'roles saved filters', exact: true })
    await menu.getByLabel('Saved filter name', { exact: true }).fill('MIGO without both')
    await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
    await expect(menu).toContainText('Saved filters updated.')
    const stored = (await (await request.get('/api/saved-filters', { headers })).json()).items.find((item: { name: string }) => item.name === 'MIGO without both')
    expect([stored.filters.tcodes, stored.filters.excludeTcodes, stored.filters.excludeMode]).toEqual([['MIGO'], ['ME21N', 'VA03'], 'all'])
    await menu.getByRole('button', { name: 'Clear filters', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(roleExclude(page).locator('.transaction-chip')).toHaveCount(0)
    await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    const box = page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('combobox', { name: 'Saved filter', exact: true })
    await box.click(); await box.fill('without')
    await page.getByRole('option').filter({ hasText: 'MIGO without both' }).first().click()
    await page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('button', { name: 'Load', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(roleExclude(page).locator('.transaction-chip')).toHaveCount(2)
    await expect(mode(page, 'Exclude roles by transaction', 'ALL')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('article')).toHaveCount(2) // A and B hold MIGO; neither holds both excluded codes
    page.once('dialog', (dialog) => dialog.accept())
    await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    await page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('button', { name: 'Delete', exact: true }).click()
    await expect.poll(async () => (await (await request.get('/api/saved-filters', { headers })).json()).items.length).toBe(0)
  })

  test('a filter saved before the independent groups restores the same condition', async ({ page, request }) => {
    const saved = await request.post('/api/saved-filters', { headers, data: { name: 'Earlier AND exclude', view: 'roles', filters: { tcodes: ['MIGO', 'ME21N'], transactionMode: 'and', transactionExclude: true } } })
    expect(saved.ok()).toBeTruthy()
    await openRoles(page)
    await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    const dialog = page.getByRole('dialog', { name: 'roles saved filters', exact: true })
    const box = dialog.getByRole('combobox', { name: 'Saved filter', exact: true })
    await box.click(); await box.fill('Earlier')
    await page.getByRole('option').filter({ hasText: 'Earlier AND exclude' }).first().click()
    await dialog.getByRole('button', { name: 'Load', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(roleInclude(page).locator('.transaction-chip')).toHaveCount(0)
    await expect(roleExclude(page).locator('.transaction-chip')).toHaveCount(2)
    await expect(mode(page, 'Exclude roles by transaction', 'ALL')).toHaveAttribute('aria-pressed', 'true') // not both together
    await expect(page.getByRole('article')).toHaveCount(3) // B, D, C as before
  })
})

test.describe('User Access', () => {
  test('exclude ANY/ALL follow the same semantics as roles and combine with the include group', async ({ page }) => {
    await openUsers(page)
    await add(userInclude(page), 'MIGO')
    await expect.poll(() => listed(page)).toEqual(['U1', 'U2'])
    await add(userExclude(page), 'ME21N')
    await expect.poll(() => listed(page)).toEqual(['U2']) // U1 holds ME21N
    await add(userExclude(page), 'MIGO')
    await expect.poll(() => listed(page)).toEqual([]) // ANY: nobody holds MIGO without MIGO
    await mode(page, 'Exclude users by transaction', 'ALL').click()
    await expect.poll(() => listed(page)).toEqual(['U2']) // ALL: only U1 holds both
    await expect(userExclude(page)).toContainText('Users with unmapped roles are not listed.')
    await userExclude(page).getByRole('button', { name: 'Remove transaction ME21N' }).click()
    await userExclude(page).getByRole('button', { name: 'Remove transaction MIGO' }).click()
    await expect.poll(() => listed(page)).toEqual(['U1', 'U2'])
  })

  test('users with unmapped roles or no eligible assignment are never reported as lacking a transaction; wildcards and filters combine', async ({ page }) => {
    await openUsers(page)
    await add(userExclude(page), 'ME*')
    await expect.poll(() => listed(page)).toEqual(['U2', 'U3'])
    for (const unknown of ['U5', 'U6', 'U7']) await expect(page.getByRole('link', { name: unknown, exact: true })).toHaveCount(0)
    await page.getByRole('combobox', { name: 'SAP User Group', exact: true }).click()
    await page.getByRole('combobox', { name: 'SAP User Group', exact: true }).fill('G2')
    await page.getByRole('option', { name: 'G2', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect.poll(() => listed(page)).toEqual(['U3'])
    await page.getByRole('complementary', { name: 'Filters' }).getByRole('button', { name: 'Clear filters', exact: true }).click()
    await expect(userExclude(page).locator('.transaction-chip')).toHaveCount(0)
    await expect(userInclude(page).getByRole('textbox')).toHaveValue('')
    await expect.poll(() => listed(page)).toEqual(['U1', 'U2', 'U3', 'U4', 'U5', 'U6', 'U7'])
  })

  test('CSV export matches the listing and the exclude group is keyboard operable', async ({ page }) => {
    await openUsers(page)
    await userInclude(page).getByRole('textbox').focus()
    await page.keyboard.press('Tab')
    await expect(userExclude(page).getByRole('textbox')).toBeFocused()
    await page.keyboard.type('MIGO')
    await page.keyboard.press('Enter')
    await expect.poll(() => listed(page)).toEqual(['U3', 'U4'])
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
    const file = readFileSync((await (await download).path())!, 'utf8')
    const names = new Set(file.split(/\r?\n/).slice(1).filter(Boolean).map((line) => line.split(';')[0].replaceAll('"', '')))
    expect([...names].sort()).toEqual(['U3', 'U4'])
  })

  test('both groups are saved in a Saved Filter and the layout fits narrow screens', async ({ page, request }) => {
    await page.setViewportSize({ width: 375, height: 800 })
    await openUsers(page)
    await add(userInclude(page), 'MIGO')
    await add(userExclude(page), 'ME21N')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.locator('div.saved-filter-toolbar[aria-label="users saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
    const menu = page.getByRole('dialog', { name: 'users saved filters', exact: true })
    await menu.getByLabel('Saved filter name', { exact: true }).fill('Users with MIGO without ME21N')
    await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
    await expect(menu).toContainText('Saved filters updated.')
    const stored = (await (await request.get('/api/saved-filters', { headers })).json()).items.find((item: { name: string }) => item.name === 'Users with MIGO without ME21N')
    expect([stored.filters.tcodes, stored.filters.excludeTcodes, stored.filters.excludeMode]).toEqual([['MIGO'], ['ME21N'], 'any'])
    page.once('dialog', (dialog) => dialog.accept())
    await menu.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect.poll(async () => (await (await request.get('/api/saved-filters', { headers })).json()).items.length).toBe(0)
  })
})
