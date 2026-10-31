import { test, expect, type Page } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'
import { headers } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })
test.setTimeout(90_000)

const TABS: [string, string][] = [['Users', 'lucide-users'], ['Assignments', 'lucide-list-checks'], ['Roles', 'lucide-layers'], ['Role conflicts', 'lucide-shield-alert']]
const strip = (page: Page) => page.getByRole('tablist', { name: 'Access Explorer views' })

for (const theme of ['light', 'dark']) for (const width of [375, 1280]) test(`Access Explorer tabs carry their icons in ${theme} at ${width}px`, async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings; settings.theme = theme
  await request.post('/api/configuration', { headers, data: settings })
  await page.setViewportSize({ width, height: 900 })
  await openSod(page, 'Access Explorer')
  for (const [label, icon] of TABS) {
    const tab = strip(page).getByRole('tab', { name: label, exact: true })
    await expect(tab.locator(`svg.${icon}`), `${label} icon`).toBeVisible()
    const box = (await tab.locator('svg').boundingBox())!
    expect([Math.round(box.width), Math.round(box.height)]).toEqual([16, 16]) // the size every other secondary navigation uses
    expect(await tab.evaluate((element) => ({ gap: getComputedStyle(element).columnGap, align: getComputedStyle(element).alignItems, background: getComputedStyle(element).backgroundColor, side: getComputedStyle(element).borderLeftWidth }))).toEqual({ gap: '8px', align: 'center', background: 'rgba(0, 0, 0, 0)', side: '0px' }) // no background or side border
  }
  expect(await strip(page).evaluate((element) => element.scrollWidth <= element.clientWidth + 1 || getComputedStyle(element).overflowX !== 'visible')).toBeTruthy()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('the active underline stays, selecting a tab shifts no layout and arrow keys move the focus ring', async ({ page }) => {
  await openSod(page, 'Access Explorer')
  const tabs = strip(page).getByRole('tab')
  await expect(tabs).toHaveCount(4)
  const before = await tabs.evaluateAll((list) => list.map((tab) => { const box = tab.getBoundingClientRect(); return [Math.round(box.x), Math.round(box.width), Math.round(box.height)] }))
  const users = tabs.nth(0)
  await expect(users).toHaveAttribute('aria-selected', 'true')
  expect(await users.evaluate((element) => getComputedStyle(element).borderBottomColor)).not.toBe(await tabs.nth(1).evaluate((element) => getComputedStyle(element).borderBottomColor))
  expect(await tabs.nth(1).evaluate((element) => getComputedStyle(element).borderBottomWidth)).toBe('2px') // inactive tabs reserve the transparent border
  await users.focus(); await page.keyboard.press('ArrowRight')
  await expect(tabs.nth(1)).toBeFocused()
  const ring = await tabs.nth(1).evaluate((element) => { const style = getComputedStyle(element); return { style: style.outlineStyle, width: parseFloat(style.outlineWidth) } })
  expect(ring.style).not.toBe('none'); expect(ring.width).toBeGreaterThanOrEqual(2)
  await page.keyboard.press('Enter')
  await expect(tabs.nth(1)).toHaveAttribute('aria-selected', 'true')
  const after = await tabs.evaluateAll((list) => list.map((tab) => { const box = tab.getBoundingClientRect(); return [Math.round(box.x), Math.round(box.width), Math.round(box.height)] }))
  expect(after).toEqual(before) // no layout shift
  await page.keyboard.press('End'); await expect(tabs.nth(3)).toBeFocused()
  await page.keyboard.press('Home'); await expect(tabs.nth(0)).toBeFocused()
})

test('every secondary tab and view navigation shows icons', async ({ page }) => {
  await openSod(page, 'Reviews')
  for (const name of ['Review areas']) for (const tab of await page.getByRole('tablist', { name }).getByRole('tab').all()) await expect(tab.locator('svg')).toHaveCount(1)
  await page.goto('/#session=browser-test-session')
  await page.getByRole('link', { name: 'User Access', exact: true }).first().click()
  for (const link of await page.getByRole('navigation', { name: 'User Access view', exact: true }).getByRole('link').all()) await expect(link.locator('svg')).toHaveCount(1)
})
