import { expect, test } from '@playwright/test'
import { goTo, seedSources, type SeededSources } from './support'

const roles = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:MM:A,Role A,ZS:A,MIGO\n'
const users = 'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_ONE,ZC:MM:A,G1,20200101,99991231\nDEMO_TWO,ZC:MM:A,G1,20200101,99991231\nDEMO_THREE,ZC:MM:A,G2,20200101,99991231\n'
let sources: SeededSources
test.beforeEach(async ({ request }) => { sources = await seedSources(request, { roles, users }) })
test.afterEach(async () => { await sources.cleanup() })

for (const [width, height] of [[375, 800], [800, 900], [1280, 900], [1600, 900]] as const)
  test(`user directory table scrolls inside itself at ${width}px`, { tag: '@visual' }, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await page.goto('/#session=browser-test-session')
    await goTo(page, 'User Access')
    const table = page.getByRole('region', { name: 'User directory table' })
    await expect(table).toBeVisible()
    const heads = await table.getByRole('columnheader').allTextContents()
    expect(heads.map((h) => h.trim()).filter(Boolean)).toEqual(['Username', 'Full name', 'Functional Group', 'SAP user group', 'Email', 'SAP account status', 'Lock status', 'Relevant roles'])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    if (width < 1280) {
      expect(await table.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true)
      await table.evaluate((el) => { el.scrollLeft = 400 })
      const box = await table.boundingBox()
      const user = await table.getByRole('columnheader', { name: 'Username' }).boundingBox()
      const check = await table.getByRole('checkbox', { name: 'Select all users on this page' }).boundingBox()
      expect(check!.x).toBeGreaterThanOrEqual(box!.x - 1)
      expect(user!.x).toBeLessThan(box!.x + 80)
    }
  })

test('selection checkbox state and count', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
    await goTo(page, 'User Access')
  const all = page.getByRole('checkbox', { name: 'Select all users on this page' })
  await all.check()
  await expect(page.getByRole('heading', { name: /selected/ })).toBeVisible()
  const first = page.getByRole('checkbox', { name: /^Select (?!all)/ }).first()
  await first.uncheck()
  expect(await all.evaluate((e: HTMLInputElement) => e.indeterminate)).toBe(true)
  await page.getByRole('button', { name: 'Clear selection' }).click()
  await expect(page.getByRole('heading', { name: /selected/ })).toHaveCount(0)
})
