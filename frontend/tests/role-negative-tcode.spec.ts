import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
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
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-transaction-mode-'))
  const file = path.join(directory, 'roles.csv')
  writeFileSync(file, roles)
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = file
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

async function open(page: Page) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Role Lookup', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(5)
}
const filter = (page: Page) => page.getByRole('group', { name: 'Filter catalogue by transaction', exact: true })
const mode = (page: Page) => page.getByRole('group', { name: 'Transaction match type', exact: true })
const add = async (page: Page, code: string) => {
  const input = filter(page).getByRole('textbox')
  await input.fill(code)
  await input.press('Enter')
}
const shown = async (page: Page) => (await page.getByRole('article').getByRole('heading').allInnerTexts()).sort()
const articles = (page: Page, ...ids: string[]) => Promise.all(ids.map((id) => expect(page.getByRole('article').filter({ hasText: id })).toHaveCount(1)))

test('one transaction field with a Has / Does not have selector; Has is the default and keeps the original behavior', async ({ page }) => {
  await open(page)
  await expect(filter(page).getByRole('textbox')).toHaveCount(1)
  await expect(page.getByRole('textbox', { name: /transaction/i })).toHaveCount(1)
  await expect(mode(page).getByRole('button', { name: 'Has T-code', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(mode(page).getByRole('button', { name: 'Does not have T-code', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await add(page, 'MIGO')
  await articles(page, 'ZC:MM:A', 'ZC:FI:B')
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(page.getByText('Does not have:', { exact: false })).toHaveCount(0)
  await expect(page.getByText('Transaction code/pattern filters match every selected code (AND)', { exact: false })).toBeVisible()
  // Positive wildcard and multiple values (AND, then the existing OR option).
  await add(page, 'ME*')
  await articles(page, 'ZC:MM:A')
  await expect(page.getByRole('article')).toHaveCount(1)
  await filter(page).getByRole('button', { name: 'OR', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(3)
})

test('Does not have T-code: exact, wildcard and multiple values; roles without mappings never appear', async ({ page }) => {
  await open(page)
  await add(page, 'MIGO')
  await mode(page).getByRole('button', { name: 'Does not have T-code', exact: true }).click()
  await expect(mode(page).getByRole('button', { name: 'Does not have T-code', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(filter(page).getByRole('button', { name: 'Remove transaction MIGO' })).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(2)
  await articles(page, 'ZC:MM:D', 'ZC:SD:C')
  await expect(page.getByRole('article').filter({ hasText: 'ZC:SD:E' })).toHaveCount(0)
  await expect(page.getByText('Does not have: roles with at least one transaction mapping', { exact: false })).toBeVisible()
  await expect(page.getByText('not confirmed absence', { exact: false })).toBeVisible()
  await expect(page.getByText('Transaction code/pattern filters match', { exact: false })).toHaveCount(0)
  await add(page, 'VA03')
  await expect(page.getByRole('article')).toHaveCount(1)
  await articles(page, 'ZC:MM:D')
  await expect(filter(page).getByRole('group', { name: 'Transaction matching' })).toHaveCount(0)
  await filter(page).getByRole('button', { name: 'Remove transaction MIGO' }).click()
  await filter(page).getByRole('button', { name: 'Remove transaction VA03' }).click()
  await add(page, 'ME*')
  await expect(page.getByRole('article')).toHaveCount(2)
  await articles(page, 'ZC:FI:B', 'ZC:SD:C')
})

test('switching modes keeps the query; combines with module and description filters; Clear all filters restores Has', async ({ page }) => {
  await open(page)
  await add(page, 'ME*')
  await expect(page.getByRole('article')).toHaveCount(2)
  await mode(page).getByRole('button', { name: 'Does not have T-code', exact: true }).click()
  await expect(filter(page).getByRole('button', { name: 'Remove transaction ME*' })).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(2)
  await articles(page, 'ZC:FI:B', 'ZC:SD:C')
  await mode(page).getByRole('button', { name: 'Has T-code', exact: true }).click()
  await expect(filter(page).getByRole('button', { name: 'Remove transaction ME*' })).toBeVisible()
  await articles(page, 'ZC:MM:A', 'ZC:MM:D')
  await mode(page).getByRole('button', { name: 'Does not have T-code', exact: true }).click()
  await page.getByRole('group', { name: 'SAP areas', exact: true }).getByRole('button', { name: /^SD / }).click()
  await expect(page.getByRole('article')).toHaveCount(1)
  await articles(page, 'ZC:SD:C')
  await page.getByPlaceholder('Search roles by name or description...').fill('beta')
  await expect(page.getByRole('article')).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear all filters', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(5)
  await expect(mode(page).getByRole('button', { name: 'Has T-code', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(filter(page).getByRole('textbox')).toHaveValue('')
})

test('the selector is keyboard operable and the layout fits narrow screens', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await open(page)
  await add(page, 'MIGO')
  const not = mode(page).getByRole('button', { name: 'Does not have T-code', exact: true })
  await not.focus()
  await page.keyboard.press('Enter')
  await expect(not).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('article')).toHaveCount(2)
  await mode(page).getByRole('button', { name: 'Has T-code', exact: true }).focus()
  await page.keyboard.press('Space')
  await expect(page.getByRole('article')).toHaveCount(2)
  await articles(page, 'ZC:MM:A', 'ZC:FI:B')
  // Tab order: selector, transaction input, then the role search.
  await mode(page).getByRole('button', { name: 'Does not have T-code', exact: true }).focus()
  await page.keyboard.press('Tab')
  await expect(filter(page).getByRole('textbox')).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  const box = await mode(page).boundingBox()
  expect(box!.x + box!.width).toBeLessThanOrEqual(375)
})

test('the transaction mode is part of a Saved Filter and the selector is not added to user access filtering', async ({ page, request }) => {
  await open(page)
  await add(page, 'MIGO')
  await mode(page).getByRole('button', { name: 'Does not have T-code', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
  const menu = page.getByRole('dialog', { name: 'roles saved filters', exact: true })
  await menu.getByLabel('Saved filter name', { exact: true }).fill('Roles without MIGO')
  await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(menu).toContainText('Saved filters updated.')
  const stored = (await (await request.get('/api/saved-filters', { headers })).json()).items.find((item: { name: string }) => item.name === 'Roles without MIGO')
  expect([stored.filters.transactionOperator, stored.filters.tcodes]).toEqual(['not', ['MIGO']])
  await menu.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('article')).toHaveCount(5)
  await expect(mode(page).getByRole('button', { name: 'Has T-code', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
  const box = page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('combobox', { name: 'Saved filter', exact: true })
  await box.click()
  await box.fill('without')
  await page.getByRole('option').filter({ hasText: 'Roles without MIGO' }).first().click()
  await page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('button', { name: 'Load', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(mode(page).getByRole('button', { name: 'Does not have T-code', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('article')).toHaveCount(2)
  page.once('dialog', (dialog) => dialog.accept())
  await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
  await page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('button', { name: 'Delete', exact: true }).click()
  await expect.poll(async () => (await (await request.get('/api/saved-filters', { headers })).json()).items.length).toBe(0)
  // User access has its own transaction filter and no match-type selector.
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'User Access', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Transaction match type' })).toHaveCount(0)
})
