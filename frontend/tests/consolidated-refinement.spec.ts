import { test, expect, type Page } from '@playwright/test'
import { goTo, openFilters, pickMulti, seedSources, type SeededSources } from './support'
import { cleanup, createPeriod, names, openSod, seedGovernance } from './sod-fixture'

const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
FI,ZC:FI:VIEW:ENP,Finance view,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
`
const users = `USERNAME,FIRST_NAME,LAST_NAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
UA1,Ann,One,ZC:MM:BUY:ENP,G1,20200101,99991231
UA1,Ann,One,ZO:MM:M:PR_REL_ST_E2_N1:ALL,G1,20200101,99991231
UB2,Bob,Two,ZC:FI:VIEW:ENP,G2,20200101,99991231
UC3,Cy,Three,ZO:MM:M:PR_REL_ST_E2_N1:ALL,G3,20200101,99991231
UD4,Di,Four,ZO:MM:M:PO_REL_ST_E3_N2:ALL,G2,20200101,99991231
`
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)

test.describe('access views', () => {
  let seeded: SeededSources
  test.beforeEach(async ({ request }) => { seeded = await seedSources(request, { roles, users }) })
  test.afterEach(async () => { await seeded.cleanup() })

  test('SAP User Group is a multi-select: OR within the filter, removable chips and one Clear action in the sidebar', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/#session=browser-test-session'); await goTo(page, 'User Access')
    const list = page.getByRole('region', { name: 'User Access', exact: true })
    const shown = async () => (await list.getByRole('link', { name: /^U[A-D]\d$/ }).allInnerTexts()).sort()
    await expect.poll(shown).toEqual(['UA1', 'UB2', 'UC3', 'UD4'])
    await pickMulti(list, 'SAP User Group', 'G1', page)
    await pickMulti(list, 'SAP User Group', 'G2', page)
    await expect.poll(shown).toEqual(['UA1', 'UB2', 'UD4'])
    await list.getByRole('button', { name: 'Remove user group filter G1', exact: true }).click()
    await expect.poll(shown).toEqual(['UB2', 'UD4'])
    // One reset action: the sidebar header Clear, no twin in the toolbar.
    await expect(page.getByRole('button', { name: 'Clear filters', exact: true })).toHaveCount(1)
    await page.getByRole('complementary', { name: 'Filters' }).getByRole('button', { name: 'Clear filters', exact: true }).click()
    await expect.poll(shown).toEqual(['UA1', 'UB2', 'UC3', 'UD4'])
  })

  test('multiple roles combine with OR and keep unrelated selections when one is removed', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/#session=browser-test-session'); await goTo(page, 'User Access')
    const list = page.getByRole('region', { name: 'User Access', exact: true })
    const shown = async () => (await list.getByRole('link', { name: /^U[A-D]\d$/ }).allInnerTexts()).sort()
    for (const role of ['ZC:MM:BUY:ENP', 'ZC:FI:VIEW:ENP']) {
      const box = list.getByRole('combobox', { name: 'Filter users by role', exact: true })
      await box.click(); await box.fill(role)
      await page.getByRole('option').filter({ hasText: role }).first().click()
      await box.press('Escape')
    }
    await expect.poll(shown).toEqual(['UA1', 'UB2'])
    await list.getByRole('button', { name: 'Remove role filter ZC:MM:BUY:ENP', exact: true }).click()
    await expect.poll(shown).toEqual(['UB2'])
  })

  test('the Users count of a release role opens a panel with its users, names, groups, validity and an export', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/#session=browser-test-session'); await goTo(page, 'Release Roles')
    await page.getByRole('button', { name: 'Table', exact: true }).click()
    await page.getByRole('button', { name: /^Show 2 users with ZO:MM:M:PR_REL_ST_E2_N1:ALL$/ }).click()
    const panel = page.getByRole('dialog', { name: 'Users with this release role' })
    const table = panel.getByRole('region', { name: 'Users with this release role' })
    await expect(table).toContainText('UA1'); await expect(table).toContainText('UC3')
    await expect(table).toContainText('Ann One'); await expect(table).toContainText('G3')
    await expect(table.getByText('Active assignment').first()).toBeVisible()
    await expect(table.getByText('Valid from').first()).toBeVisible()
    await expect(panel.getByRole('button', { name: /Export CSV/ })).toBeEnabled()
    await panel.getByRole('button', { name: 'View user details UC3' }).click()
    await expect(page.getByRole('region', { name: 'User details', exact: true })).toBeVisible()
  })

  test('Release Strategy is a multi-select that combines with the other release filters', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/#session=browser-test-session'); await goTo(page, 'Release Roles')
    await page.getByRole('button', { name: 'Table', exact: true }).click()
    const rows = async () => (await page.getByRole('region', { name: 'Release role results' }).getByRole('button', { name: 'Release role details' }).allInnerTexts()).map((text) => text.replace(/\s+/g, '')).sort()
    await expect.poll(rows).toHaveLength(2)
    await pickMulti(page, 'Release Strategy', 'N1', page)
    await expect.poll(rows).toEqual(['ZO:MM:M:PR_REL_ST_E2_N1:ALL'])
    await pickMulti(page, 'Release Strategy', 'N2', page)
    await expect.poll(rows).toHaveLength(2)
    await expect(page.getByRole('button', { name: 'Remove Release Strategy N1', exact: true })).toBeVisible()
  })

  test('Account Review and Compare users use the shared filter sidebar with Saved Filters and one Clear action', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/#session=browser-test-session'); await goTo(page, 'User Access')
    await page.getByRole('link', { name: 'Account Review', exact: true }).click()
    const sidebar = page.getByRole('complementary', { name: 'Filters' })
    await expect(page.locator('.review-filters')).toHaveCount(0)
    for (const name of ['Review finding', 'License group classification', 'Review decision']) await expect(sidebar.getByRole('combobox', { name, exact: true })).toBeVisible()
    await expect(sidebar.getByRole('searchbox', { name: 'Search account reviews', exact: true })).toBeVisible()
    await expect(sidebar.getByRole('button', { name: /Saved filters/ })).toBeVisible()
    await expect(page.getByRole('toolbar', { name: 'Page actions' }).getByRole('button', { name: 'Export review CSV' })).toBeVisible()
    await page.getByRole('button', { name: /^Pending reviews/ }).click()
    await expect(page.getByRole('button', { name: 'Remove review finding filter', exact: true })).toBeVisible()
    await sidebar.getByRole('button', { name: 'Clear filters', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Remove review finding filter', exact: true })).toHaveCount(0)
    await page.getByRole('link', { name: 'Compare users', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Comparison filters' })).toHaveCount(0)
    for (const name of ['Assignment validity', 'Comparison section']) await expect(sidebar.getByRole('combobox', { name, exact: true })).toBeVisible()
    await expect(sidebar.getByRole('combobox', { name: 'Comparison SAP area', exact: true })).toBeVisible()
    await expect(page.getByRole('toolbar', { name: 'Page actions' }).getByRole('combobox', { name: 'Sort comparison' })).toBeVisible()
    // The same SAP user never appears on both sides.
    const a = page.getByRole('combobox', { name: 'User A', exact: true }), b = page.getByRole('combobox', { name: 'User B', exact: true })
    await a.click(); await a.fill('UA1'); await page.getByRole('option', { name: /UA1/ }).first().click()
    await b.click(); await b.fill('UA1')
    await expect(page.getByRole('option', { name: /UA1/ })).toHaveCount(0)
  })
})

test.describe('SoD views', () => {
  let directory: string
  test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
  test.afterEach(async ({ request }) => { await cleanup(request, directory) })

  test('overview: heatmap controls share one row and the empty review period card stays compact', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await openSod(page)
    const bar = page.getByRole('toolbar', { name: 'Heatmap controls' })
    const title = page.getByRole('heading', { name: 'Conflicts by SAP user group' })
    const box = await bar.boundingBox(), head = await title.boundingBox()
    expect(Math.abs((box!.y + box!.height / 2) - (head!.y + head!.height / 2))).toBeLessThan(40) // one row with the title
    for (const name of ['Risks', 'Activities']) await expect(bar.getByRole('button', { name, exact: true })).toBeVisible()
    const card = page.getByRole('region', { name: 'Review period progress' }).or(page.locator('[aria-label="Review period progress"]'))
    await expect(card).toContainText('No approved period')
    expect((await card.boundingBox())!.height).toBeLessThan(260)
    await page.setViewportSize({ width: 375, height: 900 })
    expect(await overflow(page)).toBeTruthy()
  })

  test('assignment tiles are filter buttons that toggle, combine with filters and reset', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await openSod(page, 'Access Explorer')
    await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
    const tiles = page.getByRole('region', { name: 'Role assignment review progress' })
    const needs = tiles.getByRole('button', { name: /^Needs review/ }), completed = tiles.getByRole('button', { name: /^Completed/ })
    await expect(needs).toHaveAttribute('aria-pressed', 'true') // the default working view
    await expect(tiles.locator('.sod-tile-static')).toContainText('Outdated')
    await completed.click()
    await expect(completed).toHaveAttribute('aria-pressed', 'true')
    await expect(needs).toHaveAttribute('aria-pressed', 'false')
    await expect(page.getByText('0 rows', { exact: true })).toBeVisible()
    await completed.click() // toggles off, back to the default
    await expect(needs).toHaveAttribute('aria-pressed', 'true')
    await tiles.getByRole('button', { name: /^Removal recommended/ }).click()
    await expect(page.getByRole('button', { name: 'Reset tile filters' })).toBeVisible()
    await page.getByRole('button', { name: 'Reset tile filters' }).click()
    await expect(needs).toHaveAttribute('aria-pressed', 'true')
  })

  test('assignments and roles tables show codeblocks and pills without module labels, active badges or dates', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await openSod(page, 'Access Explorer')
    await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
    const table = page.getByRole('table', { name: 'Access list' })
    await expect(table.locator('tbody tr').first().locator('.role-identifier')).toHaveCount(2) // SAP username and role
    await expect(table.getByText('Active assignment')).toHaveCount(0)
    await expect(table.getByText('Valid from')).toHaveCount(0)
    await expect(table.locator('.module-badge')).toHaveCount(0)
    await expect(table.locator('.id-pill-risk').first()).toBeVisible()
    await expect(table.getByRole('button', { name: /^Investigate/ }).first().locator('svg')).toBeVisible()
    await page.getByRole('tab', { name: 'Roles', exact: true }).click()
    const roles = page.getByRole('table', { name: 'User & role lookup' })
    await expect(roles.locator('.module-badge')).toHaveCount(0)
    await expect(roles.getByText('Active assignment')).toHaveCount(0)
    await expect(roles.getByRole('button', { name: /^Show users with/ }).first()).toBeVisible()
    await page.getByRole('tab', { name: 'Role conflicts', exact: true }).click()
    await expect(page.locator('.id-pill-risk').first()).toBeVisible() // the established coloured risk pill, not a codeblock
  })

  test('the reviewer name is remembered for the session across review workflows and can be changed', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await openSod(page, 'Risk Matrix')
    await page.getByRole('button', { name: new RegExp(`^Open ${names.a}`) }).click()
    const panel = page.getByRole('dialog', { name: new RegExp(`^${names.a}`) })
    const section = panel.getByRole('region', { name: 'Role Assignment Review', exact: true })
    const quick = section.getByRole('group', { name: 'Quick review details' }).getByRole('textbox', { name: 'Reviewer (self-reported)' })
    await quick.fill('Session Reviewer')
    await section.getByRole('button', { name: 'Keep ROLE_B', exact: true }).click()
    await expect(section.getByRole('button', { name: 'Keep ROLE_B', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await page.keyboard.press('Escape')
    await page.getByRole('link', { name: 'Access Explorer', exact: true }).click()
    await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Select all assignments on this page' }).check()
    await page.getByRole('toolbar', { name: 'Bulk assignment review' }).getByRole('button', { name: 'Keep', exact: true }).click()
    const reviewer = page.getByRole('dialog', { name: 'Keep assignments' }).getByRole('textbox', { name: 'Reviewer' })
    await expect(reviewer).toHaveValue('Session Reviewer')
    await reviewer.fill('Another Reviewer') // it can be changed
    await expect(reviewer).toHaveValue('Another Reviewer')
  })

  test('assignment review rows are compact: decisions and status collapsed, evidence and history on expand', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await openSod(page, 'Risk Matrix')
    await page.getByRole('button', { name: new RegExp(`^Open ${names.a}`) }).click()
    const section = page.getByRole('dialog', { name: new RegExp(`^${names.a}`) }).getByRole('region', { name: 'Role Assignment Review', exact: true })
    const row = section.getByRole('listitem').filter({ hasText: 'ROLE_B' }).first()
    await expect(row.getByText('Valid from')).toHaveCount(0)
    await expect(row.getByText('SAP User Group')).toHaveCount(0)
    for (const name of ['Keep ROLE_B', 'Investigate ROLE_B', 'Remove ROLE_B']) await expect(row.getByRole('button', { name, exact: true })).toBeVisible()
    await row.getByRole('button', { name: 'Show details for ROLE_B' }).click()
    const details = row.getByRole('group', { name: 'Evidence for ROLE_B' })
    await expect(details).toContainText('SAP User Group'); await expect(details).toContainText('Validity')
    await expect(details).toContainText('Transactions')
    await expect(row.getByText('Assignment review history')).toBeVisible()
    await expect(section.getByRole('checkbox', { name: 'Select all visible in Role Assignment Review' })).toBeVisible()
    await section.getByRole('checkbox', { name: 'Select all visible in Role Assignment Review' }).check()
    await expect(section.getByRole('button', { name: /^Review selected \(\d+\)$/ })).toBeVisible()
  })

  test('review period actions use icons and share the Open button height; report details start expanded; queue shows codeblocks', async ({ page, request }) => {
    await createPeriod(request, 'Synthetic menu period')
    await page.setViewportSize({ width: 1440, height: 1000 })
    await openSod(page, 'Review Periods')
    const open = page.getByRole('button', { name: 'Open Synthetic menu period' })
    const trigger = page.getByRole('button', { name: 'Actions for Synthetic menu period' })
    expect(Math.abs((await open.boundingBox())!.height - (await trigger.boundingBox())!.height)).toBeLessThan(2)
    await trigger.click()
    const menu = page.getByRole('group', { name: 'Synthetic menu period actions' })
    for (const name of ['Review in Risk Matrix', 'View Activity Matrix', 'View work queue', 'Delete…']) await expect(menu.getByRole('button', { name }).locator('svg')).toBeVisible()
    await page.keyboard.press('Escape')
    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await expect(page.locator('details.sod-report-details').first()).toHaveAttribute('open', '')
    await expect(page.getByRole('textbox', { name: 'Prepared by' })).toBeVisible()
    await page.getByRole('link', { name: 'Reviews', exact: true }).click()
    const queue = page.getByRole('table', { name: 'SoD review work queue' })
    await expect(queue.locator('tbody tr').first().locator('.role-identifier')).toHaveCount(1)
    await expect(page.getByRole('region', { name: 'Review progress' }).getByRole('button', { name: /^All users/ })).toHaveAttribute('aria-pressed', 'true')
  })
})

test('the filter sidebar header keeps Clear and Close compact and aligned', async ({ page, request }) => {
  const seeded = await seedSources(request, { roles, users })
  try {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
    const header = page.locator('.filter-sidebar > header')
    const clear = header.getByRole('button', { name: 'Clear filters', exact: true }), close = header.getByRole('button', { name: 'Close filters', exact: true })
    await expect(clear).toContainText('Clear')
    await expect(clear).not.toContainText('all filters')
    const [c, x] = [await clear.boundingBox(), await close.boundingBox()]
    expect(Math.abs(c!.height - x!.height)).toBeLessThan(2)
    expect(Math.abs((c!.y + c!.height / 2) - (x!.y + x!.height / 2))).toBeLessThan(2)
    await openFilters(page)
  } finally { await seeded.cleanup() }
})
