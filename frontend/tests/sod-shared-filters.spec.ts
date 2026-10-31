import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { cleanup, createPeriod, names, openSod, seedGovernance } from './sod-fixture'
import { pickMulti } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const sidebar = (page: Page) => page.getByRole('complementary', { name: 'Filters', exact: true })
const goto = async (page: Page, link: string) => { await page.getByRole('link', { name: link, exact: true }).click() }
const selected = (page: Page, label: string) => sidebar(page).getByRole('group', { name: `Selected ${label}` })
const rows = (page: Page) => page.locator('tbody th.matrix-row-head code')
const clearPage = (page: Page) => sidebar(page).getByRole('button', { name: 'Clear page filters', exact: true })
const clearAll = (page: Page) => sidebar(page).getByRole('button', { name: 'Clear all SoD filters', exact: true })
const roleConflicts = async (page: Page) => { await goto(page, 'Access Explorer'); await page.getByRole('tab', { name: 'Role conflicts', exact: true }).click() }

test('shared selections follow the user across the SoD pages that offer them, multi-select values intact', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(sidebar(page), 'SAP User Group', 'FIN', page)
  await pickMulti(sidebar(page), 'SAP User Group', 'P2P', page)
  await pickMulti(sidebar(page), 'Risk ID', 'R1', page)
  await expect(rows(page)).toHaveCount(2) // FIN and P2P users with R1
  for (const link of ['Activity Matrix', 'Access Explorer', 'Reviews']) {
    await goto(page, link)
    await expect(selected(page, 'SAP User Group')).toContainText('FIN')
    await expect(selected(page, 'SAP User Group')).toContainText('P2P')
    await expect(selected(page, 'Risk ID')).toContainText('R1')
  }
  await goto(page, 'Overview')
  await goto(page, 'Risk Matrix')
  await expect(selected(page, 'SAP User Group')).toContainText('P2P') // restored on returning
  // changing it on another page changes it everywhere (one source of truth)
  await goto(page, 'Activity Matrix')
  await page.getByRole('button', { name: 'Remove SAP User Group FIN', exact: true }).click()
  await goto(page, 'Risk Matrix')
  await expect(selected(page, 'SAP User Group')).not.toContainText('FIN')
  await expect(selected(page, 'SAP User Group')).toContainText('P2P')
})

test('a selection a page does not offer stays stored without affecting it and returns on a page that does', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(sidebar(page), 'SAP username', names.a, page)
  await expect(rows(page)).toHaveCount(1)
  await roleConflicts(page)
  await expect(page.getByRole('combobox', { name: 'SAP username', exact: true })).toHaveCount(0) // the page has no such filter ...
  await expect(page.getByRole('button', { name: new RegExp(`Remove SAP username`) })).toHaveCount(0) // ... and shows no chip for it
  await expect(page.getByRole('heading', { name: /potential role/i }).or(page.getByText(/potential (role|combination)/i)).first()).toBeVisible()
  await goto(page, 'Risk Matrix')
  await expect(selected(page, 'SAP username')).toContainText(names.a) // restored
  await expect(rows(page)).toHaveCount(1)
})

test('local page filters stay independent of the shared ones', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(sidebar(page), 'SAP User Group', 'FIN', page)
  await page.getByRole('button', { name: /^Pending risks/ }).click() // a status tile is local to this matrix
  await expect(page.getByRole('button', { name: /^Pending risks/ })).toHaveAttribute('aria-pressed', 'true')
  await goto(page, 'Activity Matrix')
  await expect(selected(page, 'SAP User Group')).toContainText('FIN')
  await expect(page.getByRole('button', { name: /^Pending activities/ })).toHaveAttribute('aria-pressed', 'false')
  await goto(page, 'Risk Matrix')
  await expect(page.getByRole('button', { name: /^Pending risks/ })).toHaveAttribute('aria-pressed', 'true') // and kept for this page
})

test('Clear page filters clears this page and its shared selections only; Clear all SoD filters clears everything', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(sidebar(page), 'SAP User Group', 'FIN', page)
  await pickMulti(sidebar(page), 'Risk ID', 'R2', page)
  await page.getByRole('button', { name: /^Pending risks/ }).click()
  await roleConflicts(page) // supports the risk dimension but not groups
  await expect(selected(page, 'Risk ID')).toContainText('R2')
  await clearPage(page).click()
  await expect(selected(page, 'Risk ID')).toHaveCount(0)
  await goto(page, 'Risk Matrix')
  await expect(selected(page, 'SAP User Group')).toContainText('FIN') // the unrelated shared dimension survives
  await expect(selected(page, 'Risk ID')).toHaveCount(0) // the cleared one is gone everywhere
  await expect(page.getByRole('button', { name: /^Pending risks/ })).toHaveAttribute('aria-pressed', 'true') // other pages' local filters survive
  await expect(clearAll(page)).toBeEnabled()
  await clearAll(page).click()
  await expect(selected(page, 'SAP User Group')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Pending risks/ })).toHaveAttribute('aria-pressed', 'false')
  await expect(rows(page)).toHaveCount(2)
  await expect(clearAll(page)).toBeDisabled() // nothing left to clear
  await goto(page, 'Activity Matrix')
  await expect(selected(page, 'SAP User Group')).toHaveCount(0)
})

test('Saved Filters load into the shared context and decisions are unaffected', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(sidebar(page), 'SAP User Group', 'P2P', page)
  await page.locator('div.saved-filter-toolbar[aria-label="sod_risk_matrix saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
  const menu = page.getByRole('dialog', { name: 'sod_risk_matrix saved filters', exact: true })
  await menu.getByLabel('Saved filter name', { exact: true }).fill('Shared P2P')
  await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(menu).toContainText('Saved filters updated.')
  await page.keyboard.press('Escape')
  await clearAll(page).click()
  await expect(selected(page, 'SAP User Group')).toHaveCount(0)
  await page.locator('div.saved-filter-toolbar[aria-label="sod_risk_matrix saved filters"]').getByRole('button', { name: /Saved filters/ }).click()
  const box = menu.getByRole('combobox', { name: 'Saved filter', exact: true })
  await box.click(); await box.fill('Shared')
  await page.getByRole('option').filter({ hasText: 'Shared P2P' }).first().click()
  await menu.getByRole('button', { name: 'Load', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(selected(page, 'SAP User Group')).toContainText('P2P')
  await goto(page, 'Access Explorer')
  await expect(selected(page, 'SAP User Group')).toContainText('P2P') // a loaded filter is shared like any other selection
})

test('the review context stays selected across SoD pages while filters change independently', async ({ page, request }) => {
  const id = await createPeriod(request, 'Shared filter period')
  await openSod(page, 'Risk Matrix')
  await page.reload()
  await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'SoD', exact: true }).click()
  await goto(page, 'Risk Matrix')
  const context = page.getByRole('combobox', { name: 'Review context', exact: true })
  await context.selectOption(id)
  await pickMulti(sidebar(page), 'SAP User Group', 'FIN', page)
  for (const link of ['Activity Matrix', 'Access Explorer', 'Reviews', 'Overview']) {
    await goto(page, link)
    await expect(context).toHaveValue(id)
  }
  await goto(page, 'Risk Matrix')
  await expect(selected(page, 'SAP User Group')).toContainText('FIN')
  await context.selectOption('current')
  await expect(selected(page, 'SAP User Group')).toContainText('FIN') // switching context keeps the scope filters ...
  await goto(page, 'Review Periods')
  await expect(page.getByRole('complementary', { name: 'Filters', exact: true })).toHaveCount(0) // ... and Review Periods has no investigation filters
})

test('exports follow the shared filters', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(sidebar(page), 'SAP User Group', 'P2P', page)
  await goto(page, 'Access Explorer')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /Export CSV/ }).first().click()
  const text = readFileSync((await (await download).path())!, 'utf8')
  expect(text).toContain(names.b)
  expect(text).not.toContain(names.a)
})

test('browser back and forward restore the filters of each step', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(sidebar(page), 'SAP User Group', 'FIN', page)
  await goto(page, 'Activity Matrix')
  await pickMulti(sidebar(page), 'SAP User Group', 'P2P', page)
  await expect(selected(page, 'SAP User Group')).toContainText('P2P')
  await page.goBack()
  await expect(selected(page, 'SAP User Group')).not.toContainText('P2P') // the step before the second selection
  await expect(selected(page, 'SAP User Group')).toContainText('FIN')
  await page.goBack()
  await expect(page).toHaveURL(/#\/sod\/risk-matrix/)
  await expect(selected(page, 'SAP User Group')).toContainText('FIN')
  await page.goForward()
  await page.goForward()
  await expect(selected(page, 'SAP User Group')).toContainText('P2P')
})
