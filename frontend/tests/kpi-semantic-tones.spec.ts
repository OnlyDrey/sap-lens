import { test, expect, type Page } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'
import { headers } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })
test.setTimeout(90_000)

type Patch = Record<string, unknown>
async function overview(page: Page, governance: Patch, counts: Patch = {}) {
  await page.route('**/api/sod/overview**', async (route) => {
    const json = await (await route.fetch()).json()
    await route.fulfill({ json: { ...json, counts: { ...json.counts, ...counts }, governance: { ...json.governance, ...governance } } })
  })
}
const tone = (page: Page, group: string, label: string) => page.getByRole('region', { name: group, exact: true }).getByRole('button', { name: label, exact: true }).evaluate((element) => ({ tone: element.getAttribute('data-tone'), color: getComputedStyle(element.querySelector('.info-row-value')!).color, text: getComputedStyle(element).color }))

const POPULATED: Patch = {
  available: true, users_with_conflicts: 4, user_risk_findings: 9, assignments_marked_remove: 2,
  concentration: { multi_risk_users: 2 },
  activities: { Pending: 2, Outdated: 1, Approved: 3, Conditional: 1, 'Removal required': 1 },
  acceptance: { Accepted: 2, Rejected: 1, Pending: 4 },
  remediation: { open_actions: 3, overdue: 2, removal_without_action: 1 },
}

test('SoD Overview colours nonzero metrics by meaning and keeps informational totals neutral', async ({ page }) => {
  await overview(page, POPULATED, { enabled: 5 })
  await openSod(page)
  const expected: [string, string, string][] = [
    ['Conflicts', 'Users with potential conflicts', 'warning'], ['Conflicts', 'Users with more than one risk', 'warning'], ['Conflicts', 'Detected user-risk findings', 'warning'], ['Conflicts', 'Enabled risk definitions', 'neutral'],
    ['Reviews', 'Activities pending or outdated', 'warning'], ['Reviews', 'Activities approved or conditional', 'success'], ['Reviews', 'Activities marked for removal', 'warning'],
    ['Reviews', 'Risks accepted', 'success'], ['Reviews', 'Risks rejected', 'warning'], ['Reviews', 'Risk decisions pending', 'warning'],
    ['Remediation', 'Role assignments marked for removal', 'warning'], ['Remediation', 'Open actions', 'warning'], ['Remediation', 'Overdue actions', 'error'], ['Remediation', 'Remediation awaiting action', 'warning'],
  ]
  for (const [group, label, want] of expected) {
    const found = await tone(page, group, label)
    expect(found.tone, `${label} tone`).toBe(want)
    if (want === 'neutral') expect(found.color, `${label} uses the default text colour`).toBe(found.text)
    else expect(found.color, `${label} is coloured`).not.toBe(found.text)
  }
  // colour is never the only signal: every figure keeps its label and number as text
  await expect(page.getByRole('region', { name: 'Remediation', exact: true }).getByRole('button', { name: 'Overdue actions', exact: true })).toContainText('2')
})

test('every zero value is neutral, whatever the metric', async ({ page }) => {
  await overview(page, { available: true, users_with_conflicts: 0, user_risk_findings: 0, assignments_marked_remove: 0, concentration: { multi_risk_users: 0 }, activities: {}, acceptance: {}, remediation: { open_actions: 0, overdue: 0, removal_without_action: 0 } }, { enabled: 0 })
  await openSod(page)
  for (const group of ['Conflicts', 'Reviews', 'Remediation']) {
    const tones = await page.getByRole('region', { name: group, exact: true }).locator('.info-row').evaluateAll((rows) => rows.map((row) => row.getAttribute('data-tone')))
    expect(tones.length).toBeGreaterThan(0)
    expect(new Set(tones)).toEqual(new Set(['neutral']))
  }
})

test('Dashboard and Account Review use the same mapping', async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  await request.post('/api/configuration', { headers, data: settings })
  await overview(page, { ...POPULATED, acceptance: {} })
  await page.goto('/#session=browser-test-session')
  const sodCard = page.getByRole('region', { name: 'Segregation of Duties', exact: true })
  await expect(sodCard.getByRole('button', { name: 'Users with potential conflicts', exact: true })).toHaveAttribute('data-tone', 'warning')
  await expect(sodCard.getByRole('button', { name: 'Overdue remediation actions', exact: true })).toHaveAttribute('data-tone', 'error')
  await expect(sodCard.getByRole('button', { name: 'Open remediation actions', exact: true })).toHaveAttribute('data-tone', 'warning')
})

for (const theme of ['light', 'dark']) test(`warning, danger and success values keep readable contrast in ${theme}`, async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings; settings.theme = theme
  await request.post('/api/configuration', { headers, data: settings })
  await overview(page, POPULATED, { enabled: 5 })
  await openSod(page)
  const contrast = await page.evaluate(() => {
    const parse = (value: string) => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number)
    const lum = ([r, g, b]: number[]) => { const f = (c: number) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b) }
    const ratio = (a: number[], b: number[]) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
    return [...document.querySelectorAll('.info-row[data-tone]:not([data-tone="neutral"])')].map((row) => {
      const background = parse(getComputedStyle(row.closest('section')!).backgroundColor)
      return { tone: row.getAttribute('data-tone'), ratio: ratio(parse(getComputedStyle(row.querySelector('.info-row-value')!).color), background.length === 3 ? background : [255, 255, 255]) }
    })
  })
  expect(contrast.length).toBeGreaterThan(5)
  for (const item of contrast) expect(item.ratio, `${item.tone} value contrast`).toBeGreaterThan(3) // large bold figures need 3:1
})
