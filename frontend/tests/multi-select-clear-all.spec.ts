import { test, expect, type Page } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'
import { openFilters } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

async function pick(page: Page, label: string, values: string[]) {
  const control = page.getByRole('combobox', { name: label, exact: true })
  for (const value of values) { await control.click(); await control.fill(value); await page.getByRole('option', { name: value, exact: true }).click() }
  await control.press('Escape')
}
const field = (page: Page, label: string) => page.locator('.ui-field').filter({ has: page.getByRole('combobox', { name: label, exact: true }) })

test('multi-select Clear sits at the right of the field label, only shows with a selection and clears only its own field', async ({ page }) => {
  await openSod(page, 'Access Explorer')
  await openFilters(page)
  const group = field(page, 'SAP User Group')
  const clear = group.getByRole('button', { name: 'Clear all SAP User Group selections', exact: true })
  await expect(clear).toHaveCount(0)                       // hidden without active selections
  await pick(page, 'SAP User Group', ['FIN', 'P2P'])
  await expect(clear).toHaveText('Clear')
  await expect(clear.locator('svg')).toHaveCount(1)        // circle-x icon kept
  await expect(clear).toHaveClass(/ui-button-ghost/)
  await expect(clear).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)') // no permanent background
  const [label, button, box, chips] = await Promise.all([group.locator('label').boundingBox(), clear.boundingBox(), group.boundingBox(), page.getByRole('group', { name: 'Selected SAP User Group', exact: true }).boundingBox()])
  expect(button!.y).toBeLessThan(chips!.y)                                         // above the chips, not below them
  expect(Math.abs((button!.x + button!.width) - (box!.x + box!.width))).toBeLessThanOrEqual(2) // right edge of the field
  expect(button!.x).toBeGreaterThanOrEqual(label!.x + 1)                           // on the label row
  expect(Math.abs((button!.y + button!.height / 2) - (label!.y + label!.height / 2))).toBeLessThanOrEqual(6)
  // Chip removal is unchanged and the action stays while a value remains.
  await page.getByRole('button', { name: 'Remove SAP User Group P2P', exact: true }).click()
  await expect(clear).toBeVisible()
  // Clearing one field leaves a different multi-select untouched.
  await pick(page, 'Risk ID', ['R1'])
  await clear.click()
  await expect(page.getByRole('group', { name: 'Selected SAP User Group', exact: true })).toHaveCount(0)
  await expect(clear).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Selected Risk ID', exact: true })).toBeVisible()
})

test('Clear never overlaps a long label or leaves a narrow sidebar at 375px, and is keyboard operable', { tag: '@a11y' }, async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await openSod(page, 'Access Explorer')
  await openFilters(page)
  await pick(page, 'SAP User Group', ['FIN'])
  const group = field(page, 'SAP User Group')
  const clear = group.getByRole('button', { name: 'Clear all SAP User Group selections', exact: true })
  const [label, button, box] = await Promise.all([group.locator('label').boundingBox(), clear.boundingBox(), group.boundingBox()])
  expect(button!.x + button!.width).toBeLessThanOrEqual(box!.x + box!.width + 1)
  expect(button!.x).toBeGreaterThanOrEqual(label!.x + 40) // the label keeps room; the action never covers it
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await clear.focus(); await expect(clear).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(clear).toHaveCount(0)
})
