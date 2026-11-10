import { test, expect, type Page, type Locator } from '@playwright/test'
import { cleanup, names, openSod, seedGovernance } from './sod-fixture'
import { openFilters } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

let label = 'Review finding'
async function open(page: Page) {
  label = 'Review finding'
  await page.goto('/#session=browser-test-session')
  await page.goto('/#/user-access/account-review')
  await openFilters(page)
  const input = page.getByRole('combobox', { name: label, exact: true })
  await input.scrollIntoViewIfNeeded()
  await input.click()
  return input
}
const popup = (page: Page) => page.locator('.multi-popup')
/** The popup sits against the trigger (below or above), stays in the viewport, is opaque, and keeps its action row visible. */
async function expectAttached(page: Page, input: Locator) {
  await expect(popup(page)).toBeVisible()
  const result = await page.evaluate((l) => {
    const field = document.querySelector(`input[aria-label="${l}"]`)!.closest('.combobox-anchor')!.getBoundingClientRect()
    const pop = document.querySelector('.multi-popup') as HTMLElement, box = pop.getBoundingClientRect()
    const head = pop.querySelector('.multi-popup-head')!.getBoundingClientRect(), list = pop.querySelector('[role=listbox]') as HTMLElement
    const buttons = [...pop.querySelectorAll('.multi-popup-actions button')].map(b => { const r = b.getBoundingClientRect(); return r.top >= box.top - 1 && r.bottom <= box.bottom + 1 })
    const alpha = getComputedStyle(pop).backgroundColor
    return { gapBelow: box.top - field.bottom, gapAbove: field.top - box.bottom, top: box.top, bottom: box.bottom, vh: innerHeight, headInside: head.top >= box.top - 1, buttons, alpha,
      listScrolls: list.scrollHeight > list.clientHeight, listHeight: list.clientHeight, height: box.height }
  }, label)
  const attached = Math.abs(result.gapBelow - 4) <= 2 || Math.abs(result.gapAbove - 4) <= 2
  expect(attached, JSON.stringify(result)).toBe(true)
  expect(result.top).toBeGreaterThanOrEqual(0); expect(result.bottom).toBeLessThanOrEqual(result.vh)
  expect(result.height).toBeLessThanOrEqual(361)
  expect(result.headInside && result.buttons.every(Boolean)).toBe(true)
  expect(result.alpha).not.toMatch(/rgba\(.*, 0\)|transparent/)
  await expect(input).toHaveAttribute('aria-expanded', 'true')
  return result
}

test('the dropdown stays attached through the first search, later searches and an empty result', async ({ page }) => {
  const input = await open(page)
  await expectAttached(page, input)
  for (const query of ['pos', 'position', 'a', 'zzzz-no-such-value', '']) {
    await input.fill(query)
    await expectAttached(page, input)
    if (query.startsWith('zzzz')) await expect(popup(page)).toContainText('No matching values.')
  }
  for (const name of ['Close', 'Clear selection']) await expect(popup(page).getByRole('button', { name: new RegExp(name) })).toBeVisible()
})

test('near the bottom edge the dropdown opens upward and keeps a scrollable list', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 520 })
  const input = await open(page)
  const first = await expectAttached(page, input)
  await input.fill('a')
  const second = await expectAttached(page, input)
  expect(first.listHeight).toBeGreaterThan(40); expect(second.listHeight).toBeGreaterThan(0)
  // Shrinking and growing again must recover the full height: the size comes from the content, not from the previously clamped box.
  await input.fill('zzzz-no-such-value'); await expectAttached(page, input)
  await input.fill('')
  const again = await expectAttached(page, input)
  expect(again.listHeight).toBeGreaterThanOrEqual(first.listHeight - 2)
  await page.keyboard.press('Escape')
  await expect(popup(page)).toHaveCount(0)
})

test('at 375px the dropdown fits the viewport width and searching does not move it away from the field', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  const input = await open(page)
  await expectAttached(page, input)
  const box = (await popup(page).boundingBox())!
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(375)
  await input.fill('position')
  await expectAttached(page, input)
})

test('selections survive searching and every toggle keeps the list open', async ({ page }) => {
  const input = await open(page)
  await popup(page).getByRole('option').first().click()
  await input.fill('zzzz-no-such-value')
  await expect(page.getByRole('group', { name: `Selected ${label}` })).toBeVisible()
  await input.fill('')
  await expect(popup(page).getByRole('option').first()).toHaveAttribute('aria-selected', 'true')
  await expectAttached(page, input)
})

test('a server-searched SAP username filter stays attached across first and later searches', async ({ page }) => {
  await openSod(page, 'Reviews')
  await page.getByRole('tab', { name: 'Remediation', exact: true }).click()
  await openFilters(page)
  label = 'SAP username'
  const input = page.getByRole('combobox', { name: label, exact: true })
  await input.scrollIntoViewIfNeeded()
  await input.click()
  await expectAttached(page, input)
  for (const query of [names.a.slice(0, 4), names.a, 'zzzz-none', names.b.slice(0, 3)]) {
    await input.fill(query)
    await page.waitForTimeout(400) // server-side option search settles
    await expectAttached(page, input)
  }
})
