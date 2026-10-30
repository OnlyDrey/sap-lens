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

test('Dashboard v4 has no key figure row, no duplicate review metric and an emphasized SAP users row inside Access & Risk', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#session=browser-test-session')
  const dashboard = page.getByRole('region', { name: 'Dashboard', exact: true })
  await expect(dashboard.getByRole('region', { name: 'Key figures', exact: true })).toHaveCount(0)
  await expect(dashboard.locator('.ui-kpi')).toHaveCount(0)
  await expect(dashboard.getByRole('button', { name: 'Accounts requiring review', exact: true })).toHaveCount(0) // review completion lives only in Review Progress
  await expect(dashboard.getByRole('button', { name: 'Review completion', exact: true })).toHaveCount(0)
  await expect(dashboard.getByText(/Future assignment/i)).toHaveCount(0)
  const risk = dashboard.getByRole('region', { name: 'Access & Risk', exact: true })
  const rows = risk.locator('.info-row')
  await expect(rows.first()).toHaveAttribute('data-primary', 'true')
  await expect(rows.first()).toContainText('SAP users')
  expect(await rows.first().locator('.info-row-value').evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThan(await rows.nth(1).locator('.info-row-value').evaluate(el => parseFloat(getComputedStyle(el).fontSize)))
  for (const name of ['AD disabled / SAP active', 'Role assignment records', 'Role/T-code mappings', 'Catalogue roles', 'Release roles']) await expect(risk.getByRole('button', { name, exact: true })).toBeVisible()
  await expect(risk.getByRole('button', { name: 'Expired assignment records', exact: true })).toHaveCount(0)
  const review = dashboard.getByRole('region', { name: 'Review Progress', exact: true })
  await expect(review.locator('.progress-summary-value')).toContainText('%')
  const directory = dashboard.getByRole('region', { name: 'Directory & Data Health', exact: true })
  for (const name of ['Matched identities', 'Missing matches', 'Ambiguous matches', 'Position changes']) await expect(directory.getByRole('button', { name, exact: true })).toBeVisible()
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
  await expect(page.getByRole('button', { name: 'Remove review finding Pending reviews', exact: true })).toBeVisible()
})

// Dashboard addendum: semantic health colors, stable card layout and the Role Distribution detail view, on controlled dashboard data.
type Overrides = { review?: { reviewed: number; pending: number; outdated: number; population: number }; matched?: number; coverage?: number; roles?: Record<string, number>; assignments?: Record<string, number> }
const mockDashboard = async (page: Page, overrides: Overrides) => {
  await page.route('**/api/dashboard', async route => {
    const response = await route.fetch(), json = await response.json()
    const set = (id: string, value: number) => { const metric = json.metrics.find((item: { id: string }) => item.id === id); if (metric) { metric.value = value; metric.unavailable_reason = null } }
    if (overrides.matched !== undefined) { set('email_matches', overrides.matched); set('directory_missing', (overrides.coverage ?? 0) - overrides.matched); set('directory_ambiguous', 0); set('unresolved', (overrides.coverage ?? 0) - overrides.matched); json.coverage_total = overrides.coverage }
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
    await expect(directory.locator('.progress-summary')).toContainText(`${percent}`) // numeric value independent of color
    await expect(directory.locator('.progress-summary')).toContainText(`${matched} / 264 SAP identities matched`)
    const fill = await bar.evaluate(el => getComputedStyle(el).getPropertyValue('--progress-fill').trim())
    expect(fill).toBe(await page.evaluate(token => getComputedStyle(document.documentElement).getPropertyValue(token).trim() || token, `--${tone}`))
  }
  const directory = section(page, 'Directory & Data Health')
  const barBox = await directory.locator('progress').boundingBox(), firstRow = await directory.locator('li').first().boundingBox()
  expect(firstRow!.y - (barBox!.y + barBox!.height)).toBeGreaterThanOrEqual(8) // the first row never sits against the bar
  const summary = await directory.locator('.progress-summary-value').boundingBox(), caption = await directory.locator('.progress-summary-caption').boundingBox()
  expect(Math.abs((summary!.y + summary!.height / 2) - (caption!.y + caption!.height / 2))).toBeLessThan(10) // percentage and count read on one line
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

test('Assignment Distribution has five ranges with counts, shares, a common scale and an info tip', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockDashboard(page, { assignments: { '0–5': 4, '6–10': 2, '11–20': 1, '21–30': 1, '31+': 0 } })
  await page.goto('/#session=browser-test-session')
  const card = section(page, 'Assignment Distribution')
  const bar = (band: string) => card.getByRole('button', { name: `Investigate users with ${band} currently valid roles`, exact: true })
  await expect(card.getByRole('button', { name: /^Investigate users with/ })).toHaveCount(5)
  await expect(bar('0–5')).toContainText('4'); await expect(bar('0–5')).toContainText('50%')
  await expect(bar('0–5')).toHaveAttribute('title', /50\.0% of 8 SAP users/)
  await expect(bar('31+')).toContainText('0%')
  const width = (band: string) => bar(band).locator('.chart-fill').evaluate(el => Math.round(parseFloat((el as HTMLElement).style.width)))
  expect([await width('0–5'), await width('6–10'), await width('11–20'), await width('21–30'), await width('31+')]).toEqual([100, 50, 25, 25, 0]) // one scale for all bars
  await expect(card.getByText(/Historical and unknown intervals/)).toHaveCount(0)
  await card.getByRole('button', { name: 'About Assignment Distribution' }).click()
  await expect(page.getByText(/Historical and unknown intervals are excluded/)).toBeVisible()
  await expect(page.getByText(/Users without any valid role are in the first range/)).toBeVisible()
})

test('Dashboard v4 uses three balanced columns on desktop, stacks responsively and never scrolls horizontally', async ({ page }) => {
  await mockDashboard(page, { matched: 251, coverage: 264, roles: { MM: 9, FI: 7, SD: 5, HR: 4, BC: 3, PP: 2, QM: 1 } })
  for (const width of [375, 800, 1280, 1600]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#session=browser-test-session'); await page.reload()
    await expect(section(page, 'Role Distribution')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
    const [risk, review, directory, sources] = await Promise.all(['Access & Risk', 'Review Progress', 'Directory & Data Health', 'Data Sources & Configuration'].map(name => section(page, name).boundingBox()))
    if (width >= 1200) {
      expect(Math.abs(risk!.y - review!.y)).toBeLessThan(2); expect(Math.abs(review!.y - directory!.y)).toBeLessThan(2)
      expect(review!.x).toBeGreaterThan(risk!.x); expect(directory!.x).toBeGreaterThan(review!.x)
      expect(Math.abs(risk!.height - review!.height)).toBeLessThan(2) // cards in a row share one height
    } else if (width >= 800) { expect(Math.abs(risk!.y - review!.y)).toBeLessThan(2); expect(directory!.y).toBeGreaterThan(risk!.y) }
    else { expect(review!.y).toBeGreaterThan(risk!.y); expect(directory!.y).toBeGreaterThan(review!.y) }
    expect(sources!.width).toBeGreaterThan(risk!.width * (width >= 1200 ? 2.5 : width >= 800 ? 1.5 : 0.99)) // the sources section spans the grid
    expect(sources!.y).toBeGreaterThan(directory!.y)
  }
})

test('Assignment Distribution drill-down opens User Access with the range filter actually applied', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await section(page, 'Assignment Distribution').getByRole('button', { name: 'Investigate users with 0–5 currently valid roles', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Active user filters' }).or(page.getByLabel('Active user filters'))).toContainText('0–5 currently valid roles')
  await expect(page.getByRole('link', { name: /^U\d$/ })).toHaveCount(2) // both users hold one valid role, so both are in the first range
  await page.getByRole('button', { name: 'Remove assignment count filter' }).click()
  await page.goBack()
  await section(page, 'Assignment Distribution').getByRole('button', { name: 'Investigate users with 6–10 currently valid roles', exact: true }).click()
  await expect(page.getByRole('link', { name: /^U\d$/ })).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: 'Currently valid roles' }).or(page.getByLabel('Currently valid roles'))).toHaveValue('6–10')
})

test('Data Sources section shows only relevant sources with honest, source-specific state and records', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  type Source = { id: string; enabled: boolean; configured: boolean; loaded: boolean; loading: boolean; error: string | null; records?: number; assignments?: number; mode?: string; last_successful_load: string | null }
  const sources: Record<string, Partial<Source>> = {}
  await page.route('**/api/diagnostics', async route => {
    const response = await route.fetch(), json = await response.json()
    json.sources = json.sources.map((source: Source) => ({ ...source, ...sources[source.id] }))
    await route.fulfill({ response, json })
  })
  Object.assign(sources, {
    roles: { loaded: true, loading: true, records: 96 },
    users: { loaded: false, loading: false, error: 'invalid', records: 0 },
    sod: { enabled: false, configured: false, loaded: false },
    employees: { enabled: true, configured: true, loaded: true, loading: false, error: null, records: 251 },
  })
  await page.goto('/#session=browser-test-session')
  const area = section(page, 'Data Sources & Configuration')
  await expect(area.getByRole('button', { name: /^Role Catalogue: Refreshing/ })).toContainText('96 composite roles')
  await expect(area.getByRole('button', { name: /^User–Role Mapping: Failed/ })).toContainText('invalid')
  await expect(area.getByRole('button', { name: /^Employee Directory: Ready/ })).toContainText('251 directory records')
  await expect(area.getByRole('button', { name: /^SoD Matrix/ })).toHaveCount(0) // disabled and unconfigured: not relevant
  Object.assign(sources, { sod: { enabled: true, configured: true, loaded: true, loading: false, error: null, records: 40 }, users: { loaded: true, loading: false, error: null, records: 264, assignments: 5120 } })
  await page.reload()
  await expect(area.getByRole('button', { name: /^SoD Matrix: Ready/ })).toContainText('40 matrix records')
  await expect(area.getByRole('button', { name: /^User–Role Mapping: Ready/ })).toContainText('264 users · 5,120 assignment records') // users and assignment records are different counts
  await expect(area.getByRole('listitem')).toHaveCount(4)
})

test('User Access role rows keep a compact module badge beside the description and an unbroken role codeblock', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session'); await goTo(page, 'User Access')
  await page.getByRole('link', { name: 'U2', exact: true }).click()
  const head = page.locator('.assigned-role-head').first()
  await expect(head).toBeVisible()
  const badge = await head.locator('.module-badge').first().boundingBox(), description = await head.locator('.assigned-role-description').boundingBox(), cell = await head.locator('xpath=../..').boundingBox()
  expect(badge!.width).toBeLessThan(cell!.width * 0.4) // never a full-width badge
  expect(Math.abs(badge!.y - description!.y)).toBeLessThan(14) // description adjacent, same line
  expect(description!.x).toBeGreaterThanOrEqual(badge!.x + badge!.width - 1)
  const code = page.locator('.assigned-role .role-identifier code').first()
  await expect(code).toHaveCSS('white-space', 'nowrap') // identifiers are never broken
  expect(await code.evaluate(el => el.textContent)).toBe(LONG) // the complete value is present, not truncated
})

test('Single Roles rows get a primary-tinted hover and the chevron reacts, while the expanded state stays distinct', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
  await page.getByRole('article', { name: /Buyer plant$/ }).getByRole('button', { name: /^View details/ }).click()
  const entries = page.locator('.single-role-list .single-role-entry')
  const token = (name: string, property: string) => page.evaluate(([variable, prop]) => { const probe = document.createElement('span'); (probe.style as never as Record<string, string>)[prop] = `var(${variable})`; document.body.append(probe); const value = getComputedStyle(probe).getPropertyValue(prop === 'color' ? 'color' : 'background-color'); probe.remove(); return value }, [name, property])
  const accent2 = await token('--accent2', 'color'), neutralHover = await token('--hover', 'backgroundColor')
  const bg = (index: number) => entries.nth(index).evaluate(el => getComputedStyle(el).backgroundColor)
  for (const index of [0, 1]) {
    const before = await bg(index)
    await entries.nth(index).hover()
    const hovered = await bg(index)
    expect(hovered).not.toBe(before)
    expect(hovered).not.toBe(neutralHover) // a primary-tinted hover, not the neutral one
  }
  const chevron = entries.nth(0).getByRole('button', { name: /^Expand single role/ })
  await entries.nth(0).hover()
  await expect(chevron).toHaveCSS('color', accent2) // the chevron takes the accent color while the row is hovered (after its short transition)
  await chevron.click()
  await expect(chevron).toHaveAttribute('aria-expanded', 'true')
  await expect(entries.nth(1).getByRole('button', { name: /^Expand single role/ })).toHaveAttribute('aria-expanded', 'false') // independent expansion
})
