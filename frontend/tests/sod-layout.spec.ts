import { test, expect } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const views = ['Risk Matrix', 'Activity Matrix', 'Access Explorer', 'Reviews']

test('wide screens show a collapsible filter sidebar that keeps filter state and Saved Filters first', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openSod(page, 'Risk Matrix')
  const sidebar = page.getByRole('complementary', { name: 'Filters', exact: true })
  await expect(sidebar).toBeVisible()
  await expect(sidebar.locator('legend').first()).toHaveText('Saved Filters')
  await sidebar.getByLabel('Risk ID', { exact: true }).fill('R1')
  await page.getByRole('button', { name: /^Hide filters/ }).click()
  await expect(sidebar).toBeHidden()
  await page.getByRole('button', { name: /^Filters/ }).click()
  await expect(sidebar.getByLabel('Risk ID', { exact: true })).toHaveValue('R1')
  await expect(page.getByRole('button', { name: /^Hide filters/ })).toContainText('1')
  await page.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect(sidebar.getByLabel('Risk ID', { exact: true })).toHaveValue('')
})

test('every SoD page has the same toolbar and only the filters it needs', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  for (const view of views) {
    await openSod(page, view)
    await expect(page.getByRole('searchbox', { name: 'Search SoD data', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Reset', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /Export CSV/ }).first()).toBeVisible()
    await expect(page.getByRole('complementary', { name: 'Filters', exact: true })).toBeVisible()
  }
  await openSod(page, 'Reviews')
  await expect(page.getByRole('complementary', { name: 'Filters', exact: true }).getByLabel('Risk acceptance', { exact: true })).toHaveCount(0)
  await openSod(page, 'Risk Matrix')
  await expect(page.getByRole('combobox', { name: 'Sort', exact: true })).toBeVisible()
})

for (const width of [375, 800]) test(`narrow screens use a drawer without horizontal overflow at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  for (const view of views) {
    await openSod(page, view)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await expect(page.getByRole('dialog', { name: 'Filters', exact: true })).toBeHidden()
  }
  await openSod(page, 'Risk Matrix')
  await page.getByRole('button', { name: /^Filters/ }).click()
  const drawer = page.getByRole('dialog', { name: 'Filters', exact: true })
  await expect(drawer).toBeVisible()
  await drawer.getByLabel('Risk ID', { exact: true }).fill('R1')
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await expect(page.getByRole('button', { name: /^Filters/ })).toContainText('1')
  await expect(page.getByRole('button', { name: /^Filters/ })).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('risk and activity identifiers render as pills in the explorer', async ({ page }) => {
  await openSod(page, 'Access Explorer')
  await expect(page.locator('.id-pill-risk').first()).toBeVisible()
  await page.getByRole('tab', { name: 'User activity table', exact: true }).click()
  await expect(page.locator('.id-pill-activity').first()).toBeVisible()
})
