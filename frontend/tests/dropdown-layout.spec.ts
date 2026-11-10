import { test, expect, type Page } from '@playwright/test'
import { goTo, openFilters, seedSources, type SeededSources } from './support'

const LONG = 'ZO:MM:M:PR_REL_ST_G001_PURCHASE_RELEASE_STRATEGY_PLANT_0100_LONG_NAME:ALL'
const DESCRIPTION = 'Purchase requisition release strategy for plant 0100 including the approval of capital goods above the delegated limit, framework agreements and the related audit reporting duties of the cost centre owner.'
const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,${LONG},"${DESCRIPTION}",ZS:A,MIGO\nMM,ZC:MM:SHORT,Short one,ZS:B,ME21N\nFI,ZC:FI:OTHER,Finance clerk,ZS:C,FB01\n`
const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_ONE,${LONG},G1,20200101,99991231\nDEMO_TWO,ZC:MM:SHORT,G1,20200101,99991231\nDEMO_THREE,ZC:FI:OTHER,G2,20200101,99991231\n`
let sources: SeededSources
test.beforeEach(async ({ request }) => { sources = await seedSources(request, { roles, users }) })
test.afterEach(async () => { await sources.cleanup() })

async function open(page: Page) {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  await openFilters(page)
  const input = page.getByRole('combobox', { name: 'Filter users by role', exact: true })
  await input.click()
  await expect(page.getByRole('listbox', { name: 'Filter users by role options' })).toBeVisible()
  return input
}
const popup = (page: Page) => page.locator('.multi-popup')
const noPageOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

test('role options show the complete name on the first line and the description on the second, in a wide popup', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await open(page)
  const option = page.getByRole('option').filter({ hasText: LONG })
  await expect(option.locator('.multi-option-name')).toHaveText(LONG)
  await expect(option.locator('.multi-option-desc')).toHaveText(DESCRIPTION)
  const name = (await option.locator('.multi-option-name').boundingBox())!, desc = (await option.locator('.multi-option-desc').boundingBox())!
  expect(desc.y).toBeGreaterThanOrEqual(name.y + name.height - 1)                              // two lines, name first
  const box = (await popup(page).boundingBox())!, trigger = (await page.getByRole('combobox', { name: 'Filter users by role' }).boundingBox())!
  expect(box.width).toBeGreaterThanOrEqual(Math.max(trigger.width, 480))
  expect(box.width).toBeLessThanOrEqual(560 + 1)
  // The name is never cut: nothing is clipped horizontally, and the description is limited to two lines with the complete text in the tooltip.
  expect(await option.locator('.multi-option-name').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
  expect(await option.locator('.multi-option-desc').evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
  await expect(option.locator('.multi-option-text')).toHaveAttribute('title', new RegExp(`${LONG}.*${DESCRIPTION.slice(0, 40)}`))
  expect(await noPageOverflow(page)).toBe(true)
})

for (const width of [375, 800]) {
  test(`the popup stays inside a ${width}px viewport without page overflow`, { tag: '@visual' }, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await open(page)
    const box = (await popup(page).boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width)
    expect(box.width).toBeLessThanOrEqual(width - 16 + 1)
    expect(await noPageOverflow(page)).toBe(true)
    await expect(page.getByRole('option').filter({ hasText: LONG }).locator('.multi-option-name')).toHaveText(LONG)   // wraps instead of being truncated
  })
}

test('several roles can be chosen without closing, search covers descriptions, chips show names and Clear works', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const input = await open(page)
  const listbox = page.getByRole('listbox', { name: 'Filter users by role options' })
  await page.getByRole('option').filter({ hasText: LONG }).click()
  await page.getByRole('option').filter({ hasText: 'ZC:MM:SHORT' }).click()
  await expect(listbox).toBeVisible()                                                        // still open
  await expect(page.getByRole('listbox', { name: 'Filter users by role options' }).getByRole('option', { selected: true })).toHaveCount(2)
  await expect(page.getByRole('group', { name: 'Selected Filter users by role' })).toContainText(LONG)
  await expect(page.getByRole('group', { name: 'Selected Filter users by role' })).not.toContainText('Purchase requisition')   // chips carry the name only
  await input.fill('finance clerk')                                                          // found through the description
  await expect(page.getByRole('option').filter({ hasText: 'ZC:FI:OTHER' })).toBeVisible()
  await expect(page.getByRole('option').filter({ hasText: 'ZC:MM:SHORT' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear selection' }).click()
  await expect(page.getByRole('group', { name: 'Selected Filter users by role' })).toHaveCount(0)
})

test('keyboard: arrows move, Enter toggles, Escape closes and focus returns to the field', { tag: '@a11y' }, async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const input = await open(page)
  await input.press('ArrowDown')
  await input.press('Enter')
  await expect(page.getByRole('listbox', { name: 'Filter users by role options' }).getByRole('option', { selected: true })).toHaveCount(1)
  await expect(input).toHaveAttribute('aria-activedescendant', /option-\d+$/)
  await input.press('Escape')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(input).toBeFocused()
})

test('the popup is placed by the viewport, so a scrolling table or the sidebar cannot clip it', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 700 })
  await open(page)
  const box = (await popup(page).boundingBox())!
  expect(box.y).toBeGreaterThanOrEqual(0); expect(box.y + box.height).toBeLessThanOrEqual(700)
  expect(await popup(page).evaluate(el => el.parentElement === document.body)).toBe(true)  // rendered in the body: no ancestor overflow can cut it
})
