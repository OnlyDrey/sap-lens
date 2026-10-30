import { test, expect } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

test('interactive KPIs are keyboard buttons with a full-border active state and informational KPIs are plain groups', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Risk Matrix')
  const figures = page.getByRole('region', { name: 'Risk matrix figures' })
  const pending = figures.getByRole('button', { name: /^Pending risks/ })
  await pending.focus()
  await expect(pending).toHaveAttribute('aria-pressed', 'false')
  await page.keyboard.press('Enter')
  await expect(pending).toHaveAttribute('aria-pressed', 'true')
  await expect(pending).toBeFocused() // toggling a KPI filter keeps keyboard focus on it
  // The active state is a subtle full border, not a thick left bar, and does not shift layout.
  const style = await pending.evaluate((element) => { const css = getComputedStyle(element); return { left: css.borderLeftWidth, top: css.borderTopWidth, shadow: css.boxShadow, color: css.borderLeftColor } })
  expect(style.left).toBe(style.top)
  expect(style.shadow).not.toMatch(/inset\s+3px|3px 0px 0px 0px inset/)
  await page.keyboard.press('Space')
  await expect(pending).toHaveAttribute('aria-pressed', 'false')
  // Informational figures are groups, not buttons.
  const info = figures.getByRole('group', { name: 'Users with conflicts' })
  await expect(info).toBeVisible()
  await expect(figures.getByRole('button', { name: /^Users with conflicts/ })).toHaveCount(0)
})

test('the multi-select toolbar shows Select all, Clear and Close as three real buttons in one row', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Risk Matrix')
  await page.getByRole('combobox', { name: 'SAP username', exact: true }).click()
  const popup = page.locator('.multi-popup')
  const buttons = popup.locator('.multi-popup-actions').getByRole('button')
  await expect(buttons).toHaveCount(3)
  await expect(buttons.nth(0)).toHaveText('Select all')
  await expect(buttons.nth(1)).toHaveText('Clear')
  await expect(buttons.nth(2)).toHaveText('Close')
  const boxes = await Promise.all([0, 1, 2].map(async (index) => (await buttons.nth(index).boundingBox())!))
  expect(Math.max(...boxes.map(box => box.y)) - Math.min(...boxes.map(box => box.y))).toBeLessThan(2)
  for (const index of [0, 1, 2]) expect(await buttons.nth(index).evaluate(element => getComputedStyle(element).borderTopWidth)).not.toBe('0px') // Close is a bordered button, not plain text
  await popup.getByRole('option').first().click()
  await expect(popup).toBeVisible() // stays open while selecting
  await expect(buttons.nth(1)).toBeEnabled()
  await buttons.nth(2).click()
  await expect(popup).toHaveCount(0)
})

test('Saved filters and the assignment-style sidebar buttons use the full sidebar width', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Risk Matrix')
  const sidebar = page.getByRole('complementary', { name: 'Filters' })
  const saved = sidebar.getByRole('button', { name: /Saved filters/ })
  const body = await sidebar.locator('.filter-sidebar-body').boundingBox(), box = await saved.boundingBox()
  expect(box!.width).toBeGreaterThan(body!.width - 40)
})

test('disclosures share the compact chevron control and matrix status pills have vertical padding', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Reports')
  const summary = page.locator('details > summary').first()
  const before = await summary.evaluate(element => { const css = getComputedStyle(element, '::before'); return { width: css.width, height: css.height, display: getComputedStyle(element).display } })
  expect(before.width).toBe('34px'); expect(before.height).toBe('34px'); // the shared compact control size, equal to icon buttons; expect(before.display).toBe('flex')
  await openSod(page, 'Risk Matrix')
  const pill = page.locator('.matrix-pill').first()
  const height = (await pill.boundingBox())!.height
  expect(height).toBeGreaterThanOrEqual(24)
})

test('zebra striping, hover and selected rows stay distinguishable', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
  const rows = page.getByRole('table', { name: 'Access list' }).locator('tbody tr')
  await expect(rows.nth(3)).toBeVisible()
  const bg = (index: number) => rows.nth(index).locator('td').nth(1).evaluate(element => getComputedStyle(element).backgroundColor)
  const stripe = await bg(1), plain = await bg(0)
  expect(stripe).not.toBe(plain) // alternating rows
  await rows.nth(1).getByRole('checkbox').check()
  const selected = await bg(1)
  expect(selected).not.toBe(stripe)
  await rows.nth(3).hover()
  const hovered = await bg(3)
  expect(hovered).not.toBe(selected)
  expect(hovered).not.toBe(await bg(2))
  await rows.nth(1).hover()
  expect(await bg(1)).not.toBe(selected) // hover over a selected row is stronger still
})
