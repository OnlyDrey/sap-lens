import { test, expect } from '@playwright/test'
import { cleanup, createPeriod, headers, openSod, seedGovernance, wideMatrix } from './sod-fixture'
import { pickMulti } from './support'

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
  await pickMulti(sidebar, 'Risk ID', 'R1', page)
  await page.getByRole('button', { name: /^Hide filters/ }).click()
  await expect(sidebar).toBeHidden()
  await page.getByRole('button', { name: /^Filters/ }).click()
  await expect(sidebar.getByRole('button', { name: 'Remove Risk ID R1', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Hide filters/ })).toContainText('1')
  await sidebar.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(sidebar.getByRole('button', { name: 'Remove Risk ID R1', exact: true })).toHaveCount(0)
})

test('every SoD page has the same toolbar and only the filters it needs', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  for (const view of views) {
    await openSod(page, view)
    await expect(page.getByRole('searchbox', { name: 'Search SoD data', exact: true })).toBeVisible()
    await expect(page.getByRole('complementary', { name: 'Filters', exact: true }).getByRole('button', { name: 'Clear filters', exact: true })).toBeVisible()
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
  await pickMulti(drawer, 'Risk ID', 'R1', page)
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await expect(page.getByRole('button', { name: /^Filters/ })).toContainText('1')
  await expect(page.getByRole('button', { name: /^Filters/ })).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('risk and activity identifiers render as pills in the explorer', async ({ page }) => {
  await openSod(page, 'Access Explorer')
  await expect(page.locator('.id-pill-risk').first()).toBeVisible()
  await page.getByRole('combobox', { name: 'Group users by', exact: true }).selectOption('user_activity')
  await expect(page.locator('.id-pill-activity').first()).toBeVisible()
})

for (const width of [375, 800, 1280]) test(`overview tiles and review periods fit without horizontal overflow at ${width}`, async ({ page, request }) => {
  const periodName = `Layout period ${width}-${Date.now()}`
  await createPeriod(request, periodName)
  await page.setViewportSize({ width, height: 900 })
  for (const view of ['Overview', 'Review Periods']) {
    await openSod(page, view)
    await expect(page.getByRole('region', { name: view === 'Overview' ? 'SoD key figures' : 'SoD review periods', exact: true })).toBeVisible()
    const [scroll, inner, culprits] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth, [...document.querySelectorAll('*')].filter((e) => e.getBoundingClientRect().right > innerWidth + 1 && !e.closest('.access-table')).slice(0, 4).map((e) => e.tagName + '.' + (e as HTMLElement).className)] as const)
    expect(scroll, JSON.stringify(culprits)).toBeLessThanOrEqual(inner as number)
  }
  await page.getByRole('button', { name: `Actions for ${periodName}`, exact: true }).click()
  await expect(page.getByRole('button', { name: 'Delete…', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('matrix cells are compact, column pills use configured colors and scroll position survives leaving the matrix', async ({ page, request }) => {
  await cleanup(request, directory)
  directory = await seedGovernance(request, 'static', wideMatrix)
  const risk = (await (await request.get('/api/sod/catalogue?search=R001', { headers })).json()).items[0]
  await request.post('/api/sod/catalogue/R001', { headers, data: { expected_revision: (await (await request.get('/api/sod/catalogue', { headers })).json()).revision, definition_version: risk.definition_version, metadata: { ...risk.local, color: '#2563eb' } } })
  await openSod(page, 'Risk Matrix')
  const header = page.getByRole('columnheader', { name: /Filter to R001/ })
  await expect(header.locator('.id-pill-risk')).toHaveAttribute('data-colored', 'true')
  const cell = page.getByRole('button', { name: /^SYN_.*risk R001:/ }).first()
  expect((await cell.innerText()).trim().split('\n').join(' ').length).toBeLessThan(18)
  await expect(page.getByText('Cells show the risk acceptance status', { exact: false })).toBeVisible()
  await expect(header).not.toContainText('Criticality')
  const grid = page.getByRole('region', { name: /Scrollable User by risk matrix/ })
  await grid.evaluate((node) => { node.scrollLeft = 900 })
  await expect.poll(() => grid.evaluate((node) => node.scrollLeft)).toBeGreaterThan(800)
  await page.getByRole('link', { name: 'Access Explorer', exact: true }).click()
  await page.getByRole('link', { name: 'Risk Matrix', exact: true }).click()
  await expect.poll(() => page.getByRole('region', { name: /Scrollable User by risk matrix/ }).evaluate((node) => node.scrollLeft)).toBeGreaterThan(800)
  await openSod(page, 'Activity Matrix')
  await expect(page.getByText('Scope: activities that contribute to at least one potential conflict', { exact: false })).toBeVisible()
})

for (const width of [375, 800]) test(`the review workspace is usable without horizontal overflow at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 })
  await openSod(page, 'Reviews')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.getByRole('button', { name: /^Open review for / }).first().click()
  const panel = page.getByRole('dialog', { name: /^SYN_/ })
  for (const name of ['Activity Review', 'Role Assignment Review', 'Risk Acceptance']) await expect(panel.getByRole('region', { name, exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  const box = await panel.boundingBox()
  expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
  await panel.getByRole('button', { name: /^Review activity / }).first().click()
  await expect(panel.getByRole('button', { name: 'Save decision', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('Activity Review and Role Assignment Review rows are single-line with icon actions and keep evidence behind an expand control', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openSod(page, 'Reviews')
  await page.getByRole('button', { name: /^Open review for / }).first().click()
  const panel = page.getByRole('dialog', { name: /^SYN_/ })
  const activities = panel.getByRole('region', { name: 'Activity Review', exact: true })
  const row = activities.getByRole('listitem').filter({ has: page.getByRole('button', { name: 'Review activity A', exact: true }) })
  // Identity, status, risk pills, role coverage, decision action and expand control share one line.
  const review = row.getByRole('button', { name: 'Review activity A', exact: true }), expand = row.getByRole('button', { name: 'Show details for A', exact: true })
  await expect(review.locator('svg')).toHaveCount(1)
  await expect(row).toContainText('role assignment')
  const [reviewBox, expandBox, rowBox] = [await review.boundingBox(), await expand.boundingBox(), await row.boundingBox()]
  expect(Math.abs(reviewBox!.y - expandBox!.y)).toBeLessThan(4)
  expect(reviewBox!.height).toBeGreaterThanOrEqual(24)
  expect(rowBox!.height).toBeLessThan(80)
  // Evidence and history are behind the expand control.
  await expect(row.getByText('Activity review history')).toHaveCount(0)
  await expand.click()
  await expect(row.getByText('No decision recorded for this item yet.')).toBeVisible()
  await expect(row.getByText('Activity review history')).toBeVisible()
  await row.getByRole('button', { name: 'Hide details for A', exact: true }).click()
  await expect(row.getByText('Activity review history')).toHaveCount(0)
  // Role assignment rows show the catalogue description next to the role identifier without opening the evidence.
  const assignments = panel.getByRole('region', { name: 'Role Assignment Review', exact: true })
  await expect(assignments.getByRole('listitem').first().locator('.sod-assignment-description')).toContainText('Synt')
  await expect(assignments.getByText('SAP User Group')).toHaveCount(0)
})

test('an expanded Role Assignment Review row keeps its status and decision icons inside the panel at 375px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await openSod(page, 'Reviews')
  await page.getByRole('button', { name: /^Open review for / }).first().click()
  const panel = page.getByRole('dialog', { name: /^SYN_/ })
  const row = panel.getByRole('region', { name: 'Role Assignment Review', exact: true }).getByRole('listitem').first()
  await row.getByRole('button', { name: /^Show details for / }).click()
  await expect(row.getByRole('group', { name: /^Evidence for / })).toBeVisible()
  const panelBox = await panel.boundingBox()
  for (const control of await row.getByRole('button').all()) {
    const box = await control.boundingBox()
    expect(box!.x + box!.width, await control.getAttribute('aria-label') ?? 'control').toBeLessThanOrEqual(panelBox!.x + panelBox!.width + 1)
  }
})

test('the Overview sections fill the row at 800px: two columns with the third section spanning both', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 })
  await openSod(page)
  const sections = page.locator('.sod-overview-cards > .dashboard-section')
  await expect(sections).toHaveCount(3)
  const [a, b, c] = await Promise.all([0, 1, 2].map(async index => (await sections.nth(index).boundingBox())!))
  expect(Math.abs(a.y - b.y)).toBeLessThan(2) // first two share a row
  expect(c.y).toBeGreaterThan(a.y + 50)
  expect(c.width).toBeGreaterThan((a.width + b.width) * 0.95) // the third spans the row
})
