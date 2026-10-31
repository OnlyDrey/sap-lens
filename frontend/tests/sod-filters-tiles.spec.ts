import { test, expect } from '@playwright/test'
import { cellButton, cleanup, openSod, seedGovernance, names } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

test('search and every filter live in the sidebar; the toolbar keeps sort, export and a styled Reset', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  for (const view of ['Risk Matrix', 'Activity Matrix', 'Access Explorer']) {
    await openSod(page, view)
    const sidebar = page.getByRole('complementary', { name: 'Filters', exact: true })
    await expect(sidebar.getByRole('searchbox', { name: 'Search SoD data', exact: true })).toBeVisible()
    const toolbar = page.getByRole('toolbar', { name: 'Page actions' })
    await expect(toolbar.getByRole('searchbox')).toHaveCount(0)
    await expect(toolbar.getByRole('combobox', { name: 'Sort', exact: true })).toBeVisible()
    await expect(toolbar.getByRole('button', { name: /Export CSV/ })).toBeVisible()
    await expect(sidebar.getByRole('button', { name: 'Clear page filters', exact: true })).toBeVisible()
  }
})

test('multi-select filter fields suggest values from the imported evidence, search them and keep selections', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  const sidebar = page.getByRole('complementary', { name: 'Filters', exact: true })
  const risk = sidebar.getByRole('combobox', { name: 'Risk ID', exact: true })
  await risk.click()
  const options = page.getByRole('listbox', { name: 'Risk ID options' })
  await expect(options.getByRole('option', { name: 'R1', exact: true })).toBeVisible()
  await expect(options.getByRole('option', { name: 'R2', exact: true })).toBeVisible()
  await risk.fill('R2')
  await expect(options.getByRole('option', { name: 'R1', exact: true })).toHaveCount(0)
  await options.getByRole('option', { name: 'R2', exact: true }).click()
  await expect(options).toBeVisible()
  await expect(sidebar.getByRole('button', { name: 'Remove Risk ID R2', exact: true })).toBeVisible()
  await expect(page.getByRole('table', { name: /User by risk matrix/ }).getByRole('columnheader', { name: /Filter to R1/ })).toHaveCount(0)
  await risk.fill('not-in-data')
  await expect(page.getByText('No matching values.')).toBeVisible()
  await expect(sidebar.getByRole('button', { name: 'Remove Risk ID R2', exact: true })).toBeVisible() // searching never drops a selection
})

test('matrix tiles count every review status over the whole filtered matrix and toggle the status filter', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  const tiles = page.getByRole('region', { name: 'Risk matrix figures' })
  const pending = tiles.getByRole('button', { name: 'Pending risks' })
  await expect(pending.locator('strong')).toHaveText('3')
  for (const label of ['Accepted risks', 'Rejected risks', 'Outdated risks']) await expect(tiles.getByRole('button', { name: label })).toBeVisible()
  await tiles.getByRole('button', { name: 'Accepted risks' }).click()
  await expect(tiles.getByRole('button', { name: 'Accepted risks' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('No users match this scope', { exact: false })).toBeVisible()
  await tiles.getByRole('button', { name: 'Accepted risks' }).click()
  await expect(pending.locator('strong')).toHaveText('3')

  await openSod(page, 'Activity Matrix')
  const activity = page.getByRole('region', { name: 'Activity matrix figures' })
  for (const label of ['Pending activities', 'Approved activities', 'Conditional activities', 'Remove activities', 'Outdated activities']) await expect(activity.getByRole('button', { name: label })).toBeVisible()
})

test('a matrix cell opens only that user-risk and can be widened to the whole user', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await cellButton(page, names.a, 'R1').click()
  const panel = page.getByRole('dialog', { name: `${names.a} · R1` })
  await expect(panel.getByRole('region', { name: 'Risk Acceptance', exact: true }).getByRole('listitem')).toHaveCount(1)
  await expect(panel).toContainText('Showing only risk R1')
  await panel.getByRole('button', { name: `Show all review items for ${names.a}` }).click()
  const all = page.getByRole('dialog', { name: names.a, exact: true })
  await expect(all.getByRole('region', { name: 'Risk Acceptance', exact: true }).getByRole('listitem')).toHaveCount(2)
  await expect(all).not.toContainText('Showing only')
})

test('Role Conflicts uses the shared filter sidebar and toolbar', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('tab', { name: 'Role conflicts', exact: true }).click()
  const sidebar = page.getByRole('complementary', { name: 'Filters', exact: true })
  await expect(sidebar.getByRole('searchbox', { name: 'Search SoD findings', exact: true })).toBeVisible()
  await expect(sidebar.getByRole('combobox', { name: 'Add catalogue role to combination', exact: true })).toBeVisible()
  const toolbar = page.getByRole('toolbar', { name: 'Page actions' })
  await expect(toolbar.getByRole('combobox', { name: 'Sort', exact: true })).toBeVisible()
  await expect(toolbar.getByRole('button', { name: /Export CSV/ })).toBeVisible()
  await expect(sidebar.getByRole('button', { name: 'Clear page filters', exact: true })).toBeVisible()
})
