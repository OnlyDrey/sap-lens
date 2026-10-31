import { test, expect, type Page } from '@playwright/test'
import { cleanup, headers, openSod, seedGovernance } from './sod-fixture'
import { pickMulti } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })
test.setTimeout(120_000)

/** The seeded fixture has three users, so the matrix API is answered with a synthetic population (244 users in three SAP User Groups) built on a real response. */
async function population(page: Page, count = 244) {
  const names = ['FIN', 'HR', 'P2P'], requests: URL[] = []
  const users = Array.from({ length: count }, (_, index) => ({ user: `USER${String(index + 1).padStart(4, '0')}`, group: names[index % 3] }))
  await page.route(/\/api\/sod\/matrix\/(risk|activity)\?/, async (route) => {
    const url = new URL(route.request().url()); requests.push(url)
    const offset = Number(url.searchParams.get('offset')), limit = Number(url.searchParams.get('limit')), grouped = url.searchParams.get('group_by') === 'user_group'
    const base = new URL(url); base.searchParams.set('offset', '0'); base.searchParams.set('limit', '1')
    const real = await (await route.fetch({ url: base.toString() })).json()
    const list = grouped ? [...users].sort((a, b) => a.group.localeCompare(b.group) || a.user.localeCompare(b.user)) : users
    let start = 0
    const summaries = grouped ? names.map((name) => { const members = list.filter((item) => item.group === name), item = { name, users: members.length, findings: members.length, start }; start += members.length; return item }) : null
    const rows = list.slice(offset, offset + limit).map((item) => ({ ...real.rows[0], user: item.user, groups: [item.group], ...(grouped ? { group: item.group } : {}) }))
    await route.fulfill({ response: route, json: { ...real, rows, total_rows: list.length, offset, limit, group_summaries: summaries, totals: { ...real.totals, users: list.length } } } as never)
  })
  return requests
}
const control = (page: Page) => page.getByRole('combobox', { name: 'Users per page', exact: true })
const range = (page: Page) => page.getByRole('navigation', { name: 'Matrix range' }).getByRole('status')
const rows = (page: Page) => page.locator('tbody th.matrix-row-head code')
const next = (page: Page) => page.getByRole('navigation', { name: 'Matrix range' }).getByRole('button', { name: /Next/ })
const previous = (page: Page) => page.getByRole('navigation', { name: 'Matrix range' }).getByRole('button', { name: /Previous/ })
const sidebar = (page: Page) => page.getByRole('complementary', { name: 'Filters', exact: true })

test('users per page defaults to 50, offers 10, 25, 50, 100 and All, and pages with a clear range', async ({ page }) => {
  await population(page)
  await openSod(page, 'Risk Matrix')
  await expect(control(page)).toHaveValue('50')
  await expect(control(page).locator('option')).toHaveText(['10 users per page', '25 users per page', '50 users per page', '100 users per page', 'All users'])
  await expect(range(page)).toHaveText('1–50 of 244 users')
  await expect(rows(page)).toHaveCount(50)
  await expect(previous(page)).toBeDisabled()
  await next(page).click()
  await expect(range(page)).toHaveText('51–100 of 244 users')
  await expect(rows(page).first()).toHaveText('USER0051')
  await control(page).selectOption('100') // changing the size returns to the first page
  await expect(range(page)).toHaveText('1–100 of 244 users')
  await next(page).click(); await next(page).click()
  await expect(range(page)).toHaveText('201–244 of 244 users')
  await expect(next(page)).toBeDisabled()
  await control(page).selectOption('10')
  await expect(range(page)).toHaveText('1–10 of 244 users'); await expect(rows(page)).toHaveCount(10)
})

test('All lists every matching user and the page size is shared by both matrices', async ({ page }) => {
  await population(page)
  await openSod(page, 'Risk Matrix')
  await control(page).selectOption('all')
  await expect(range(page)).toHaveText('1–244 of 244 users'); await expect(rows(page)).toHaveCount(244)
  await expect(next(page)).toBeDisabled(); await expect(previous(page)).toBeDisabled()
  await page.getByRole('link', { name: 'Activity Matrix', exact: true }).click()
  await expect(control(page)).toHaveValue('all') // the same setting
  await expect(rows(page)).toHaveCount(244)
  await control(page).selectOption('25')
  await page.getByRole('link', { name: 'Risk Matrix', exact: true }).click()
  await expect(control(page)).toHaveValue('25')
  await expect(range(page)).toHaveText('1–25 of 244 users')
})

test('filter and grouping changes return to the first page; grouped pages never repeat a user', async ({ page }) => {
  const requests = await population(page)
  await openSod(page, 'Risk Matrix')
  await next(page).click(); await expect(range(page)).toHaveText('51–100 of 244 users')
  await pickMulti(sidebar(page), 'SAP User Group', 'FIN', page)
  await expect(range(page)).toHaveText('1–50 of 244 users')
  expect(requests.at(-1)!.searchParams.get('offset')).toBe('0')
  await next(page).click(); await expect(range(page)).toHaveText('51–100 of 244 users')
  await page.getByRole('combobox', { name: 'Group by', exact: true }).selectOption('group')
  await expect(range(page)).toHaveText('1–50 of 244 users') // grouping starts at page 1
  const first = await rows(page).allInnerTexts()
  await expect(page.locator('tr.matrix-group-row')).toHaveCount(1) // all 50 sit in the first group (FIN has 82 users)
  await expect(page.locator('tr.matrix-group-row')).toContainText('82 users')
  await next(page).click()
  await expect(range(page)).toHaveText('51–100 of 244 users')
  await expect(page.locator('tr.matrix-group-row').first()).toContainText('continued') // the group carries over
  const second = await rows(page).allInnerTexts()
  expect(first.filter((name) => second.includes(name))).toEqual([]) // no user is repeated across pages
  expect(new Set([...first, ...second]).size).toBe(first.length + second.length)
})

test('CSV exports contain every filtered user whatever the page size', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await control(page).selectOption('10')
  const request = page.waitForRequest((candidate) => /\/api\/sod\/explorer\/user_risk\/export/.test(candidate.url()))
  await page.getByRole('button', { name: /Export CSV/ }).first().click()
  const url = new URL((await request).url())
  expect(url.searchParams.has('limit')).toBe(false) // the export is not paged
  expect(url.searchParams.has('offset')).toBe(false)
})

test('All stays responsive with two thousand users', async ({ page }) => {
  await population(page, 2000)
  await openSod(page, 'Risk Matrix')
  const started = Date.now()
  await control(page).selectOption('all')
  await expect(rows(page)).toHaveCount(2000, { timeout: 30_000 })
  expect(Date.now() - started).toBeLessThan(15_000)
  await expect(range(page)).toHaveText('1–2000 of 2000 users')
  await page.getByRole('region', { name: /Scrollable User by risk matrix/ }).evaluate((element) => { element.scrollTop = 40_000 })
  await expect(rows(page).last()).toHaveText('USER2000')
})

for (const theme of ['light', 'dark']) for (const width of [375, 800, 1280]) test(`the control and range fit the toolbar in ${theme} at ${width}px`, async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings; settings.theme = theme
  await request.post('/api/configuration', { headers, data: settings })
  await population(page)
  await page.setViewportSize({ width, height: 900 })
  await openSod(page, 'Activity Matrix')
  await expect(control(page)).toBeVisible(); await expect(range(page)).toHaveText('1–50 of 244 users')
  const [select, sort] = [(await control(page).boundingBox())!, (await page.getByRole('combobox', { name: 'Group by', exact: true }).boundingBox())!]
  expect(Math.abs(select.height - sort.height)).toBeLessThan(2) // same control height as its neighbours
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})
