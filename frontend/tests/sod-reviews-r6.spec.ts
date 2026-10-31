import { test, expect, type Page } from '@playwright/test'
import { cleanup, createPeriod, decide, headers, names, openSod, seedGovernance } from './sod-fixture'
import { pickMulti } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })
test.setTimeout(90_000)

const goto = (page: Page, link: string) => page.getByRole('link', { name: link, exact: true }).click()
const workQueue = async (page: Page) => { await goto(page, 'Reviews'); await page.getByRole('tab', { name: 'Work queue', exact: true }).click() }
const remediation = async (page: Page) => { await goto(page, 'Reviews'); await page.getByRole('tab', { name: 'Remediation', exact: true }).click() }
const look = (tile: ReturnType<Page['locator']>) => tile.evaluate((element) => { const style = getComputedStyle(element); return { height: Math.round(element.getBoundingClientRect().height), radius: style.borderTopLeftRadius, padding: style.padding, fontSize: style.fontSize, border: style.borderTopWidth, cursor: style.cursor } })

test('Work Queue and Remediation filter tiles are the same shared KPI control with the same states', async ({ page, request }) => {
  const subject = await (await request.get('/api/sod/subject', { headers, params: { context: 'current', user: names.a } })).json()
  const found = subject.activities.find((row: { activity: string }) => row.activity === 'A').assignments.find((item: { role: string }) => item.role === 'ROLE_A2')
  await decide(request, 'assignment', 'current', [{ key: found.id, user: names.a, ref: 'ROLE_A2', evidence_version: found.evidence_version }], 'Remove')
  await openSod(page)
  await workQueue(page)
  const queueTiles = page.getByRole('region', { name: 'Review progress' }).locator('.ui-kpi')
  expect(await queueTiles.count()).toBeGreaterThan(2)
  const queueFirst = queueTiles.first(), queueLook = await look(queueFirst)
  await expect(queueFirst).toHaveAttribute('aria-pressed', 'true') // the selected default
  await remediation(page)
  const handling = page.getByRole('region', { name: 'Recommended handling' })
  const tiles = handling.locator('button.ui-kpi')
  expect(await tiles.count()).toBe(6) // All handling and the five handling groups
  expect(await look(tiles.first())).toEqual(queueLook) // identical size, radius, padding and type
  await expect(tiles.first()).toHaveAttribute('aria-pressed', 'true')
  const remove = handling.getByRole('button', { name: /^Remove assignment/ })
  await expect(remove).toContainText('1')
  await remove.click()
  await expect(remove).toHaveAttribute('aria-pressed', 'true'); await expect(tiles.first()).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('table', { name: 'Access remediation rows' })).toContainText('ROLE_A2') // the handling filter still applies its own logic
  // informational tiles are not buttons; zero values are neutral
  await expect(handling.getByRole('group', { name: 'Overdue' })).toHaveAttribute('data-tone', 'neutral')
  await handling.getByRole('button', { name: /^All handling/ }).click()
  await expect(handling.getByRole('button', { name: /^All handling/ })).toHaveAttribute('aria-pressed', 'true')
  // hover and keyboard focus behave the same on both pages
  const hover = async (tile: ReturnType<Page['locator']>) => { await tile.hover(); return tile.evaluate((element) => getComputedStyle(element).backgroundColor) }
  const remediationHover = await hover(remove); await workQueue(page); const queueHover = await hover(queueTiles.nth(1))
  expect(remediationHover).toBe(queueHover)
  await page.keyboard.press('Shift') // keyboard modality, so focus shows the focus-visible ring
  await queueTiles.nth(1).focus()
  expect(await queueTiles.nth(1).evaluate((element) => { const style = getComputedStyle(element); return [style.outlineStyle, parseFloat(style.outlineWidth) >= 2, parseFloat(style.borderTopLeftRadius) > 0] })).toEqual(['solid', true, true])
})

test('both pages keep the shared SoD filters', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(page.getByRole('complementary', { name: 'Filters', exact: true }), 'SAP User Group', 'P2P', page)
  for (const open of [workQueue, remediation]) {
    await open(page)
    await expect(page.getByRole('complementary', { name: 'Filters', exact: true }).getByRole('group', { name: 'Selected SAP User Group' })).toContainText('P2P')
  }
  await workQueue(page)
  await page.getByRole('region', { name: 'Review progress' }).locator('.ui-kpi').nth(1).click() // a tile changes the list, the shared filter stays
  await expect(page.getByRole('complementary', { name: 'Filters', exact: true }).getByRole('group', { name: 'Selected SAP User Group' })).toContainText('P2P')
})

for (const width of [375, 800, 1280]) test(`the Active period badge sits 8px after the period name and wraps cleanly (${width}px)`, async ({ page, request }) => {
  const id = await createPeriod(request, 'Badge spacing period with a rather long descriptive name')
  await page.setViewportSize({ width, height: 900 })
  await openSod(page, 'Risk Matrix')
  await page.getByRole('combobox', { name: 'Review context', exact: true }).selectOption(id)
  await goto(page, 'Review Periods')
  const title = page.locator('.sod-period-title', { has: page.getByText('Active period', { exact: true }) })
  await expect(title).toBeVisible()
  const [name, badge] = [(await title.locator('strong').boundingBox())!, (await title.getByText('Active period', { exact: true }).boundingBox())!]
  if (Math.abs(name.y + name.height / 2 - (badge.y + badge.height / 2)) < 6) expect(Math.abs(badge.x - (name.x + name.width) - 8)).toBeLessThan(1.5) // one line: 8 px apart
  else expect(badge.y).toBeGreaterThanOrEqual(name.y + name.height - 2) // wrapped below the name, not overlapping
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})
