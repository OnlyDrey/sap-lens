import { test, expect } from '@playwright/test'
import { goTo, seedSources, type SeededSources } from './support'

const LONG = 'ZC:SYN:A_VERY_LONG_ROLE_IDENTIFIER_FOR_LAYOUT_STRESS_TESTING:ABCDEFGHIJKLMNOP:0123456789:QRSTUV'
const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:EX1,MM - Exclusive one,ME21N,Create purchase order
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:EX2,MM - Exclusive two,ME23N,Display purchase order
MM,${LONG},Long identifier role,ZS:LONG,MM - Long,MIGO,Goods movement
`
const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
U1,ZC:MM:BUY:ENP,G1,20200101,99991231
U2,${LONG},G2,20200101,99991231
`
let seeded: SeededSources
test.beforeEach(async ({ request }) => { seeded = await seedSources(request, { roles, users }) })
test.afterEach(async () => { await seeded.cleanup() })

test('module icons have no decorative hover ring', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
  const card = page.getByRole('article', { name: /Buyer plant$/ })
  const icon = card.locator('.module-icon').first()
  const ring = () => icon.evaluate(element => getComputedStyle(element).borderTopColor)
  const before = await ring()
  await icon.hover(); expect(await ring()).toBe(before)
  await card.getByRole('button', { name: /^View details/ }).hover(); expect(await ring()).toBe(before)
})

test('Single Roles alternate row backgrounds, keep independent expansion and use the shared chevron', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
  await page.getByRole('article', { name: /Buyer plant$/ }).getByRole('button', { name: /^View details/ }).click()
  const entries = page.locator('.single-role-list .single-role-entry')
  await expect(entries).toHaveCount(3)
  const bg = (index: number) => entries.nth(index).evaluate(element => getComputedStyle(element).backgroundColor)
  const [first, second, third] = [await bg(0), await bg(1), await bg(2)]
  expect(second).not.toBe(first) // alternating backgrounds
  expect(third).toBe(first)
  const toggle = entries.nth(0).getByRole('button', { name: /^Expand single role/ })
  expect((await toggle.boundingBox())!.width).toBeGreaterThanOrEqual(32) // same hit area as other icon controls
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(entries.nth(1).getByRole('button', { name: /^Expand single role/ })).toHaveAttribute('aria-expanded', 'false') // unrelated rows stay closed
  await expect(entries.nth(0).locator('.lucide-chevron-down')).toHaveCount(1)
  await expect(entries.nth(1).locator('.lucide-chevron-right')).toHaveCount(1)
})

test('SAP role identifiers never wrap and the copied value is the complete identifier', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.setViewportSize({ width: 800, height: 900 })
  await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
  const code = page.locator('.role-identifier code', { hasText: LONG }).first()
  await expect(code).toBeVisible()
  expect(await code.evaluate(element => getComputedStyle(element).whiteSpace)).toBe('nowrap')
  expect((await code.boundingBox())!.height).toBeLessThan(32) // one line
  await page.getByRole('button', { name: `Copy role identifier ${LONG}`, exact: true }).first().click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(LONG)
})

test('multi-select shows Select all, Clear and Close with icons, and Clear is visible but disabled without a selection', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#session=browser-test-session'); await goTo(page, 'User Access')
  await page.getByRole('combobox', { name: 'SAP User Group', exact: true }).click()
  const popup = page.locator('.multi-popup'), actions = popup.locator('.multi-popup-actions').getByRole('button')
  await expect(actions).toHaveCount(3)
  for (const index of [0, 1, 2]) await expect(actions.nth(index).locator('svg')).toHaveCount(1)
  await expect(actions.nth(1)).toBeVisible(); await expect(actions.nth(1)).toBeDisabled()
  await popup.getByRole('option').first().click()
  await expect(popup).toBeVisible(); await expect(actions.nth(1)).toBeEnabled()
  await page.keyboard.press('Escape')
  await expect(popup).toHaveCount(0)
})
