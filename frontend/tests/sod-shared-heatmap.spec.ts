import { test, expect, type Page } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const heatmap = (page: Page) => page.getByRole('region', { name: 'SAP User Group heatmap', exact: true })
const sidebar = (page: Page) => page.getByRole('complementary', { name: 'Filters', exact: true })
const PAGES = ['Overview', 'Risk Matrix', 'Activity Matrix', 'Access Explorer', 'Reviews', 'Review Periods', 'Reports']

test('one shared heatmap sits directly under the Review Context on every SoD page and is expanded by default', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openSod(page)
  for (const name of PAGES) {
    await page.getByRole('link', { name, exact: true }).click()
    await expect(heatmap(page)).toHaveCount(1)
    await expect(heatmap(page).getByRole('button', { name: /Conflicts by SAP User Group/ })).toHaveAttribute('aria-expanded', 'true')
    await expect(heatmap(page).getByRole('table')).toBeVisible()
    const context = (await page.locator('[aria-label="Review context"]').first().boundingBox())!, box = (await heatmap(page).boundingBox())!
    expect(box.y).toBeGreaterThanOrEqual(context.y + context.height - 1) // directly below the shared context, before page content
    expect(box.y - (context.y + context.height)).toBeLessThan(60)
  }
})

test('collapsing the heatmap persists across SoD pages and reloads, and expanding restores it', async ({ page }) => {
  await openSod(page)
  const toggle = () => heatmap(page).getByRole('button', { name: /Conflicts by SAP User Group/ })
  await toggle().click()
  await expect(toggle()).toHaveAttribute('aria-expanded', 'false')
  await expect(heatmap(page).getByRole('table')).toHaveCount(0)
  for (const name of ['Risk Matrix', 'Reports', 'Review Periods']) { await page.getByRole('link', { name, exact: true }).click(); await expect(toggle()).toHaveAttribute('aria-expanded', 'false') }
  await page.reload()
  await expect(toggle()).toHaveAttribute('aria-expanded', 'false')
  await toggle().focus(); await page.keyboard.press('Enter') // keyboard operable
  await expect(toggle()).toHaveAttribute('aria-expanded', 'true')
  await expect(heatmap(page).getByRole('table')).toBeVisible()
  await page.reload()
  await expect(toggle()).toHaveAttribute('aria-expanded', 'true')
})

test('the heatmap is expanded in a new session, remembers a collapse within the session and starts expanded again in the next one', async ({ page, browser }) => {
  await openSod(page)
  const toggle = (target = page) => heatmap(target).getByRole('button', { name: /Conflicts by SAP User Group/ })
  await expect(toggle()).toHaveAttribute('aria-expanded', 'true')
  await expect(toggle().locator('svg').first()).toBeVisible()
  await toggle().click()
  await expect(toggle()).toHaveAttribute('aria-expanded', 'false')
  await page.getByRole('link', { name: 'Reports', exact: true }).click()
  await expect(toggle()).toHaveAttribute('aria-expanded', 'false') // kept while moving between SoD tabs
  const other = await browser.newContext(), next = await other.newPage() // a new session: nothing is remembered
  await openSod(next)
  await expect(toggle(next)).toHaveAttribute('aria-expanded', 'true')
  await expect(heatmap(next).getByRole('table')).toBeVisible()
  await next.keyboard.press('Shift'); await toggle(next).focus() // the toggle is one control: header text and chevron share one focus ring
  expect(await toggle(next).evaluate((element) => { const style = getComputedStyle(element); return [style.outlineStyle !== 'none', parseFloat(style.borderTopLeftRadius) > 0] })).toEqual([true, true])
  await other.close()
})

test('group, risk and cell selections filter the page, keep other filters, show removable filters and clear', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openSod(page, 'Risk Matrix')
  const filters = heatmap(page).getByRole('group', { name: 'Active heatmap filters' })
  await expect(filters).toHaveCount(0)
  // an unrelated page filter that the heatmap must not discard
  await page.getByRole('button', { name: /Pending risks/ }).click()
  await expect(page.getByRole('button', { name: /Pending risks/ })).toHaveAttribute('aria-pressed', 'true')
  await heatmap(page).getByRole('button', { name: 'FIN: filter to this SAP User Group' }).click()
  await expect(filters).toContainText('SAP User Group: FIN')
  await expect(sidebar(page).getByRole('button', { name: 'Remove SAP User Group FIN', exact: true })).toBeVisible() // the page itself applies it
  await heatmap(page).getByRole('button', { name: 'R1: filter to this risk' }).click()
  await expect(filters).toContainText('Risk: R1')
  await expect(sidebar(page).getByRole('button', { name: 'Remove Risk ID R1', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Pending risks/ })).toHaveAttribute('aria-pressed', 'true') // unrelated filter kept
  await expect(heatmap(page).getByRole('button', { name: 'FIN: remove SAP User Group filter' })).toHaveAttribute('aria-pressed', 'true')
  await filters.getByRole('button', { name: 'Remove filter SAP User Group FIN' }).click()
  await expect(filters).not.toContainText('SAP User Group: FIN')
  await heatmap(page).getByRole('row', { name: /^P2P\b/ }).getByRole('button', { name: /with R1/ }).click() // a cell sets group and risk together
  await expect(filters).toContainText('SAP User Group: P2P'); await expect(filters).toContainText('Risk: R1')
  await filters.getByRole('button', { name: 'Clear heatmap filters' }).click()
  await expect(filters).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Pending risks/ })).toHaveAttribute('aria-pressed', 'true') // clearing removes only the heatmap's own filters
})

test('on pages that cannot filter by group and risk a selection opens the matching matrix with the filter applied', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openSod(page, 'Reports')
  await heatmap(page).getByRole('row', { name: /^FIN\b/ }).getByRole('button', { name: /with R2/ }).click()
  await expect(page).toHaveURL(/#\/sod\/risk-matrix/)
  await expect(sidebar(page).getByRole('button', { name: 'Remove SAP User Group FIN', exact: true })).toBeVisible()
  await expect(sidebar(page).getByRole('button', { name: 'Remove Risk ID R2', exact: true })).toBeVisible()
  await expect(heatmap(page).getByRole('group', { name: 'Active heatmap filters' })).toContainText('Risk: R2')
  await page.getByRole('link', { name: 'Review Periods', exact: true }).click()
  await heatmap(page).getByRole('button', { name: 'Activities', exact: true }).click()
  await heatmap(page).getByRole('button', { name: 'B: filter to this activity' }).click()
  await expect(page).toHaveURL(/#\/sod\/activity-matrix/)
  await expect(sidebar(page).getByRole('button', { name: 'Remove Activity B', exact: true })).toBeVisible()
})
