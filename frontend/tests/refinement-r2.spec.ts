import { test, expect, type Page } from '@playwright/test'
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

test('Dashboard shows a compact key figure row, information lists and no future assignment record row', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#session=browser-test-session')
  const dashboard = page.getByRole('region', { name: 'Dashboard', exact: true })
  const key = dashboard.getByRole('region', { name: 'Key figures', exact: true })
  await expect(key.locator('.ui-kpi')).toHaveCount(3)
  await expect(key).toContainText('SAP users'); await expect(key).toContainText('Review completion')
  const list = dashboard.getByRole('region', { name: 'Access & Risk', exact: true }).getByRole('list')
  await expect(list).toBeVisible()
  await expect(list.locator('.info-row').first()).toBeVisible()
  await expect(dashboard.getByText(/Future assignment/i)).toHaveCount(0)
  // secondary facts are rows, not tiles: an information row is much shorter than a key figure
  const rowHeight = (await list.locator('.info-row').first().boundingBox())!.height
  const kpiHeight = (await key.locator('.ui-kpi').first().boundingBox())!.height
  expect(rowHeight).toBeLessThan(kpiHeight)
})

test('Dashboard charts show real counts, expose tooltips and drill down', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#session=browser-test-session')
  const dashboard = page.getByRole('region', { name: 'Dashboard', exact: true })
  const distribution = dashboard.getByRole('region', { name: 'Role Distribution', exact: true })
  const bars = distribution.getByRole('button', { name: /^Investigate .* catalogue roles$/ })
  await expect(bars.first()).toBeVisible()
  await expect(bars.first()).toHaveAttribute('title', /catalogue roles/)
  await bars.first().click()
  await expect(page.getByRole('heading', { name: 'Role Lookup', exact: true })).toBeVisible()
  await goTo(page, 'Dashboard')
  const progress = dashboard.getByRole('region', { name: 'Review Progress', exact: true })
  await expect(progress.getByRole('img', { name: /Account review progress: Completed reviews 0, Not yet reviewed 2/ })).toBeVisible()
  await progress.getByRole('button', { name: /^Not yet reviewed/ }).click()
  await expect(page.getByRole('region', { name: /Account Review|Key figures/ }).first()).toBeVisible()
})

// Dashboard addendum: semantic health colors, stable card layout and the Role Distribution detail view, on controlled dashboard data.
type Overrides = { review?: { reviewed: number; pending: number; outdated: number; population: number }; matched?: number; coverage?: number; roles?: Record<string, number>; assignments?: Record<string, number> }
const mockDashboard = async (page: Page, overrides: Overrides) => {
  await page.route('**/api/dashboard', async route => {
    const response = await route.fetch(), json = await response.json()
    const set = (id: string, value: number) => { const metric = json.metrics.find((item: { id: string }) => item.id === id); if (metric) { metric.value = value; metric.unavailable_reason = null } }
    if (overrides.matched !== undefined) { set('email_matches', overrides.matched); set('unresolved', (overrides.coverage ?? 0) - overrides.matched); json.coverage_total = overrides.coverage }
    if (overrides.review) { const r = overrides.review; json.review_population = r.population; set('reviewed', r.reviewed); set('pending', r.pending); set('outdated', r.outdated) }
    if (overrides.roles) json.role_distribution = overrides.roles
    if (overrides.assignments) json.assignment_distribution = overrides.assignments
    await route.fulfill({ response, json })
  })
}
const section = (page: Page, name: string) => page.getByRole('region', { name: 'Dashboard', exact: true }).getByRole('region', { name, exact: true })

test('Directory match progress uses central health thresholds, shows the percentage as text and keeps spacing', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  const cases: [number, string, string][] = [[251, '95.1%', 'success'], [230, '87.1%', 'warning'], [100, '37.9%', 'error'], [264, '100.0%', 'success']]
  for (const [matched, percent, tone] of cases) {
    await page.unroute('**/api/dashboard').catch(() => undefined)
    await mockDashboard(page, { matched, coverage: 264 })
    await page.goto('/#session=browser-test-session'); await page.reload()
    const directory = section(page, 'Directory & Data Health')
    const bar = directory.getByRole('progressbar', { name: new RegExp(`${percent.replace('.', '\\.')} matched`) })
    await expect(bar).toHaveAttribute('data-tone', tone)
    await expect(directory.locator('.info-row').first()).toContainText(`${percent} matched`) // numeric value independent of color
    const fill = await bar.evaluate(el => getComputedStyle(el).getPropertyValue('--progress-fill').trim())
    expect(fill).toBe(await page.evaluate(token => getComputedStyle(document.documentElement).getPropertyValue(token).trim() || token, `--${tone}`))
  }
  const directory = section(page, 'Directory & Data Health')
  const first = directory.locator('li').first(), next = directory.locator('li').nth(1)
  const bar = await first.locator('progress').boundingBox(), label = await first.locator('.info-row-label').boundingBox(), after = await next.boundingBox()
  expect(Math.abs(bar!.x - label!.x)).toBeLessThanOrEqual(1) // the bar starts under the label
  expect(after!.y - (bar!.y + bar!.height)).toBeGreaterThanOrEqual(8) // room before the next row
})

test('Role Distribution keeps five areas in the card, shows all in a dialog and never stretches neighbouring cards', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockDashboard(page, { roles: { MM: 9, FI: 7, SD: 5, HR: 4, BC: 3, PP: 2, QM: 1 }, review: { reviewed: 0, pending: 2, outdated: 0, population: 2 } })
  await page.goto('/#session=browser-test-session')
  const card = section(page, 'Role Distribution')
  await expect(card.getByRole('button', { name: /^Investigate .* catalogue roles$/ })).toHaveCount(5)
  const heights = async () => Promise.all(['Access & Risk', 'Directory & Data Health', 'Review Progress', 'Role Distribution', 'Assignment Distribution'].map(async name => Math.round((await section(page, name).boundingBox())!.height)))
  const before = await heights()
  const trigger = card.getByRole('button', { name: 'Show all 7 areas' })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Role Distribution by SAP area' })
  await expect(dialog.getByRole('button', { name: /^Investigate .* catalogue roles$/ })).toHaveCount(7)
  expect(await heights()).toEqual(before) // the dashboard grid is untouched
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0); await expect(trigger).toBeFocused()
  await trigger.click()
  await dialog.getByRole('button', { name: 'Investigate QM catalogue roles' }).click() // every area keeps its drill-down
  await expect(page.getByRole('heading', { name: 'Role Lookup', exact: true })).toBeVisible()
})

test('Review Progress segments are semantic at 0%, partial and complete', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  const tones = async () => section(page, 'Review Progress').locator('.chart-stack-bar > span').evaluateAll(spans => spans.map(span => [span.getAttribute('data-tone'), Math.round(parseFloat((span as HTMLElement).style.width)), getComputedStyle(span).backgroundColor]))
  const run = async (review: Overrides['review']) => { await page.unroute('**/api/dashboard').catch(() => undefined); await mockDashboard(page, { review }); await page.goto('/#session=browser-test-session'); await page.reload(); await expect(section(page, 'Review Progress').locator('.chart-stack-bar')).toBeVisible() }
  await run({ reviewed: 0, pending: 8, outdated: 0, population: 8 })
  const zero = await tones()
  expect(zero.map(([tone, width]) => [tone, width])).toEqual([['neutral', 100]]) // nothing completed: no success or accent color
  const accent = await page.evaluate(() => { const probe = document.createElement('span'); probe.style.color = 'var(--accent)'; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color })
  expect(zero[0][2]).not.toBe(accent)
  await run({ reviewed: 2, pending: 6, outdated: 2, population: 8 })
  expect((await tones()).map(([tone, width]) => [tone, width])).toEqual([['success', 25], ['neutral', 50], ['warning', 25]])
  await expect(section(page, 'Review Progress').getByRole('img', { name: /Completed reviews 2, Not yet reviewed 4, Outdated reviews 2 of 8/ })).toBeVisible()
  await run({ reviewed: 8, pending: 0, outdated: 0, population: 8 })
  expect((await tones()).map(([tone, width]) => [tone, width])).toEqual([['success', 100]])
})

test('Assignment Distribution shows counts with shares, scales bars to the total and keeps explanations in an info tip', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockDashboard(page, { assignments: { '1–5': 3, '6–20': 1, '21+': 0 } })
  await page.goto('/#session=browser-test-session')
  const card = section(page, 'Assignment Distribution')
  const first = card.getByRole('button', { name: 'Investigate users with 1–5 currently valid roles' })
  await expect(first).toContainText('3'); await expect(first).toContainText('75%')
  await expect(first).toHaveAttribute('title', /75\.0% of 4 users with assignments/)
  await expect(card.getByRole('button', { name: 'Investigate users with 6–20 currently valid roles' })).toContainText('25%')
  expect(await first.locator('.chart-fill').evaluate(el => Math.round(parseFloat((el as HTMLElement).style.width)))).toBe(75)
  await expect(card.getByText(/Historical and unknown intervals/)).toHaveCount(0) // technical text is not permanently visible
  await card.getByRole('button', { name: 'About Assignment Distribution' }).click()
  await expect(page.getByText(/Historical and unknown intervals are excluded/)).toBeVisible()
  await expect(page.getByText(/High counts are not security findings/)).toBeVisible()
})

test('Dashboard cards keep their own height and there is no horizontal scroll at 375, 800, 1280 and 1600', async ({ page }) => {
  await mockDashboard(page, { matched: 251, coverage: 264, roles: { MM: 9, FI: 7, SD: 5, HR: 4, BC: 3, PP: 2, QM: 1 } })
  for (const width of [375, 800, 1280, 1600]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#session=browser-test-session'); await page.reload()
    await expect(section(page, 'Role Distribution')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
  }
  const [risk, directory] = await Promise.all([section(page, 'Access & Risk').boundingBox(), section(page, 'Directory & Data Health').boundingBox()])
  expect(directory!.height).toBeLessThan(risk!.height) // a short card is not stretched to the tallest one
})
