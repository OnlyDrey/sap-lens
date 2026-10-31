import { test, expect, type Page } from '@playwright/test'
import { cleanup, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const open = async (page: Page, tab: 'Risks' | 'Activities') => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'SoD Risk Configuration', exact: true }).click()
  await page.getByRole('tab', { name: tab, exact: true }).click()
}

for (const width of [375, 1280]) test(`new risks carry a compact amber badge beside the Risk ID, separated by rows, not coloured rows (${width}px)`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  // whether a risk is new depends on review history kept by earlier specs of the same run, so the list is marked new here
  await page.route(/\/api\/sod\/catalogue\?/, async (route) => { const response = await route.fetch(), body = await response.json(); body.items = body.items.map((item: object) => ({ ...item, new: true })); await route.fulfill({ response, json: body }) })
  await open(page, 'Risks')
  const table = page.getByRole('table', { name: 'SoD risk configurations' })
  const rows = table.locator('tbody tr')
  expect(await rows.count()).toBeGreaterThanOrEqual(2)
  const badges = table.locator('.sod-new-badge')
  expect(await badges.count()).toBeGreaterThanOrEqual(2) // consecutive new risks
  for (let index = 0; index < await rows.count(); index++) {
    const row = rows.nth(index), badge = row.locator('.sod-new-badge'), pill = row.locator('.sod-id-line > *').first()
    if (!(await badge.count())) continue
    await expect(badge).toHaveText('New')
    const [b, p] = [(await badge.boundingBox())!, (await pill.boundingBox())!]
    expect(Math.abs((b.y + b.height / 2) - (p.y + p.height / 2))).toBeLessThan(width >= 800 ? 4 : 14) // on the Risk ID line (it may wrap on a narrow cell)
    expect(b.height).toBeLessThan(28) // compact
    await expect(row.locator('td').nth(2)).not.toContainText('New') // no longer under Review
  }
  // the badge is amber, rows are not: every row keeps the table background and a separator
  const styles = await rows.evaluateAll((items) => items.map((row) => ({ background: getComputedStyle(row).backgroundColor, cells: [...row.children].map((cell) => getComputedStyle(cell).backgroundColor), border: getComputedStyle(row).borderBottomWidth })))
  expect(new Set(styles.map((item) => item.background)).size).toBe(1) // no alternating or warning rows
  for (const item of styles.slice(0, -1)) expect(parseFloat(item.border)).toBeGreaterThanOrEqual(1) // separators between consecutive rows
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('Enabled and Disabled carry icons, the table has no per-row Source details, and the edit dialog still reaches the source', async ({ page }) => {
  await open(page, 'Risks')
  const table = page.getByRole('table', { name: 'SoD risk configurations' })
  const status = table.locator('.evidence-badge', { hasText: /^(Enabled|Disabled)$/ })
  expect(await status.count()).toBeGreaterThan(0)
  for (let index = 0; index < await status.count(); index++) await expect(status.nth(index).locator('svg')).toHaveCount(1)
  await expect(table.getByRole('button', { name: /^Source details/ })).toHaveCount(0)
  await table.getByRole('button', { name: /^Edit SoD risk / }).first().click()
  await expect(page.getByRole('dialog').getByRole('button', { name: /^Source details for risk / })).toBeVisible()
})

test('Activities share the Risks table rhythm: alignment, row separators, compact action buttons and a minimum row height', async ({ page }) => {
  await open(page, 'Risks')
  const risks = await page.getByRole('table', { name: 'SoD risk configurations' }).locator('tbody tr').first().evaluate((row) => ({ height: row.getBoundingClientRect().height, align: getComputedStyle(row.children[0]).verticalAlign, padding: getComputedStyle(row.children[0]).paddingTop, border: getComputedStyle(row).borderBottomWidth, button: row.querySelector('.ui-button')!.getBoundingClientRect().height }))
  await page.getByRole('tab', { name: 'Activities', exact: true }).click()
  const table = page.getByRole('table', { name: 'SoD activity configurations' })
  const activities = await table.locator('tbody tr').first().evaluate((row) => ({ height: row.getBoundingClientRect().height, align: getComputedStyle(row.children[0]).verticalAlign, padding: getComputedStyle(row.children[0]).paddingTop, border: getComputedStyle(row).borderBottomWidth, button: row.querySelector('.ui-button')!.getBoundingClientRect().height }))
  expect([activities.align, activities.padding, activities.button]).toEqual([risks.align, risks.padding, risks.button])
  expect(activities.height).toBeGreaterThanOrEqual(72) // both tables use the same minimum row height
  expect(risks.height).toBeGreaterThanOrEqual(72)
  if (await table.locator('tbody tr').count() > 1) expect(parseFloat(activities.border)).toBeGreaterThanOrEqual(1)
  await expect(table.locator('tbody tr').first().getByRole('button', { name: /^Edit SoD activity / })).toBeVisible() // activity-specific actions stay
  await expect(table.locator('tbody tr').first().getByRole('button', { name: /^Show \d+ transactions/ })).toBeVisible()
})
