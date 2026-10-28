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
`
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-negative-tcode-'))
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
}
const add = async (page: Page, label: string, code: string) => {
  const group = page.getByRole('group', { name: label, exact: true }), input = group.getByRole('textbox')
  await input.fill(code)
  await input.press('Enter')
}

test('roles without a transaction: negative, wildcard and combined searches', async ({ page }) => {
  await open(page)
  await expect(page.getByRole('article')).toHaveCount(4)
  await add(page, 'Filter catalogue by missing transaction', 'MIGO')
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(page.getByText('Does not have: roles that contain at least one other transaction', { exact: false })).toBeVisible()
  await expect(page.getByRole('article').filter({ hasText: 'ZC:MM:D' })).toHaveCount(1)
  await expect(page.getByRole('article').filter({ hasText: 'ZC:SD:C' })).toHaveCount(1)
  await add(page, 'Filter catalogue by missing transaction', 'VA03')
  await expect(page.getByRole('article')).toHaveCount(1)
  await page.getByRole('group', { name: 'Filter catalogue by missing transaction', exact: true }).getByRole('button', { name: /VA03/ }).first().click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await add(page, 'Filter catalogue by missing transaction', 'ME*')
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(page.getByRole('article').filter({ hasText: 'ZC:SD:C' })).toHaveCount(1)
})

test('negative filter combines with the positive transaction filter, text search and clears with the other filters', async ({ page }) => {
  await open(page)
  await add(page, 'Filter catalogue by transaction', 'MIGO')
  await expect(page.getByRole('article')).toHaveCount(2)
  await add(page, 'Filter catalogue by missing transaction', 'ME21N')
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(page.getByRole('article').filter({ hasText: 'ZC:FI:B' })).toHaveCount(1)
  await page.getByRole('button', { name: 'Clear all filters', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(4)
  await add(page, 'Filter catalogue by missing transaction', 'MIGO')
  await page.getByPlaceholder('Search roles by name or description...').fill('delta')
  await expect(page.getByRole('article')).toHaveCount(1)
})

test('the negative list is part of a Saved Filter', async ({ page, request }) => {
  await open(page)
  await add(page, 'Filter catalogue by missing transaction', 'MIGO')
  await expect(page.getByRole('article')).toHaveCount(2)
  await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
  const menu = page.getByRole('dialog', { name: 'roles saved filters', exact: true })
  await menu.getByLabel('Saved filter name', { exact: true }).fill('Roles without MIGO')
  await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(menu).toContainText('Saved filters updated.')
  const stored = (await (await request.get('/api/saved-filters', { headers })).json()).items.find((item: { name: string }) => item.name === 'Roles without MIGO')
  expect(stored.filters.notTcodes).toEqual(['MIGO'])
  await menu.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('article')).toHaveCount(4)
  await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
  const box = page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('combobox', { name: 'Saved filter', exact: true })
  await box.click()
  await box.fill('without')
  await page.getByRole('option').filter({ hasText: 'Roles without MIGO' }).first().click()
  await page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('button', { name: 'Load', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('article')).toHaveCount(2)
  page.once('dialog', (dialog) => dialog.accept())
  await page.locator('div.saved-filter-toolbar[aria-label="roles saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
  await page.getByRole('dialog', { name: 'roles saved filters', exact: true }).getByRole('button', { name: 'Delete', exact: true }).click()
  await expect.poll(async () => (await (await request.get('/api/saved-filters', { headers })).json()).items.length).toBe(0)
})
