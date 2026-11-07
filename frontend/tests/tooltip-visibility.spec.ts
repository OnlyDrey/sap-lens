import { test, expect, type Page } from '@playwright/test'
import { cleanup, names, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

async function openUsers(page: Page) {
  await page.goto('/#session=browser-test-session')
  await page.goto('/#/user-access')
  await expect(page.getByRole('row').filter({ hasText: names.a }).first()).toBeVisible()
}
/** The tooltip must be inside the viewport and actually painted on top at its centre (not clipped or covered). */
async function expectVisible(page: Page, tooltip: ReturnType<Page['getByRole']>) {
  await expect(tooltip).toBeVisible()
  const box = (await tooltip.boundingBox())!
  const vp = page.viewportSize()!
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(vp.width); expect(box.y + box.height).toBeLessThanOrEqual(vp.height)
  // Tooltips ignore the pointer, so hit-testing needs them to accept it for a moment.
  const covered = await tooltip.evaluate(node => { const el = node as HTMLElement; el.style.pointerEvents = 'auto'; const r = el.getBoundingClientRect(); const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); el.style.pointerEvents = ''; return !top || !el.contains(top) })
  expect(covered).toBe(false)
}
const action = (page: Page) => page.getByRole('button', { name: `Open ${names.a} in SoD Review` }).first()

test('the SoD Review action tooltip is not clipped by the scrolling table region', async ({ page }) => {
  await openUsers(page)
  await action(page).hover()
  await expectVisible(page, page.getByRole('tooltip', { name: 'Open in SoD Review' }).first())
})

test('the tooltip flips above the anchor near the bottom of the viewport and follows keyboard focus', { tag: '@a11y' }, async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 420 })
  await openUsers(page)
  await action(page).scrollIntoViewIfNeeded()
  await action(page).focus()
  const tooltip = page.getByRole('tooltip', { name: 'Open in SoD Review' }).first()
  await expectVisible(page, tooltip)
  await page.keyboard.press('Escape')
  await expect(tooltip).toBeHidden()
})

test('the tooltip stays inside a 375px viewport and inside the table when the region scrolls', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await openUsers(page)
  await action(page).scrollIntoViewIfNeeded()
  await action(page).hover()
  await expectVisible(page, page.getByRole('tooltip', { name: 'Open in SoD Review' }).first())
})
