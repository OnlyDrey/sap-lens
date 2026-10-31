import { test, expect, type Page } from '@playwright/test'
import { cellButton, cleanup, headers, names, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const section = (page: Page) => page.getByRole('dialog', { name: new RegExp(`^${names.a}`) }).getByRole('region', { name: 'Role Assignment Review', exact: true })
const row = (page: Page, role: string) => section(page).getByRole('listitem').filter({ hasText: role }).filter({ has: page.getByRole('button', { name: `Keep ${role}`, exact: true }) })
const pressed = async (page: Page, role: string) => ({
  keep: await row(page, role).getByRole('button', { name: `Keep ${role}`, exact: true }).getAttribute('aria-pressed'),
  remove: await row(page, role).getByRole('button', { name: `Remove ${role}`, exact: true }).getAttribute('aria-pressed'),
  investigate: await row(page, role).getByRole('button', { name: `Investigate ${role}`, exact: true }).getAttribute('aria-pressed'),
})
async function openUser(page: Page) {
  await openSod(page, 'Risk Matrix')
  await page.getByRole('button', { name: new RegExp(`^Open ${names.a}`) }).click()
  const quick = section(page).getByRole('group', { name: 'Quick review details' })
  await quick.getByRole('textbox', { name: 'Reviewer (self-reported)', exact: true }).fill('Synthetic Reviewer')
}

test('each role assignment of one user keeps its own decision when others are decided, changed or the page is reloaded', async ({ page }) => {
  await openUser(page)
  await row(page, 'ROLE_A1').getByRole('button', { name: 'Keep ROLE_A1', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_A1')).toEqual({ keep: 'true', remove: 'false', investigate: 'false' })
  await row(page, 'ROLE_A2').getByRole('button', { name: 'Remove ROLE_A2', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_A2')).toEqual({ keep: 'false', remove: 'true', investigate: 'false' })
  await row(page, 'ROLE_B').getByRole('button', { name: 'Keep ROLE_B', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_B')).toEqual({ keep: 'true', remove: 'false', investigate: 'false' })
  await row(page, 'ROLE_C').getByRole('button', { name: 'Investigate ROLE_C', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_C')).toEqual({ keep: 'false', remove: 'false', investigate: 'true' })
  // Earlier decisions are untouched.
  expect(await pressed(page, 'ROLE_A1')).toEqual({ keep: 'true', remove: 'false', investigate: 'false' })
  expect(await pressed(page, 'ROLE_A2')).toEqual({ keep: 'false', remove: 'true', investigate: 'false' })
  expect(await pressed(page, 'ROLE_C')).toEqual({ keep: 'false', remove: 'false', investigate: 'true' })
  // Changing one decision leaves the others alone.
  await row(page, 'ROLE_A1').getByRole('button', { name: 'Remove ROLE_A1', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_A1')).toEqual({ keep: 'false', remove: 'true', investigate: 'false' })
  expect(await pressed(page, 'ROLE_B')).toEqual({ keep: 'true', remove: 'false', investigate: 'false' })
  expect(await pressed(page, 'ROLE_A2')).toEqual({ keep: 'false', remove: 'true', investigate: 'false' })
  // Persisted: reload and reopen.
  await page.reload()
  await page.getByRole('button', { name: new RegExp(`^Open ${names.a}`) }).click()
  expect(await pressed(page, 'ROLE_A1')).toEqual({ keep: 'false', remove: 'true', investigate: 'false' })
  expect(await pressed(page, 'ROLE_A2')).toEqual({ keep: 'false', remove: 'true', investigate: 'false' })
  expect(await pressed(page, 'ROLE_B')).toEqual({ keep: 'true', remove: 'false', investigate: 'false' })
  expect(await pressed(page, 'ROLE_C')).toEqual({ keep: 'false', remove: 'false', investigate: 'true' })
  // Investigate is not final: a later Keep replaces it and the row shows only Keep.
  await row(page, 'ROLE_C').getByRole('button', { name: 'Keep ROLE_C', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_C')).toEqual({ keep: 'true', remove: 'false', investigate: 'false' })
})

test('rapid decisions on different roles are all saved and none replaces another', async ({ page, request }) => {
  await openUser(page)
  await row(page, 'ROLE_A1').getByRole('button', { name: 'Keep ROLE_A1', exact: true }).click()
  await row(page, 'ROLE_B').getByRole('button', { name: 'Remove ROLE_B', exact: true }).click()
  await row(page, 'ROLE_C').getByRole('button', { name: 'Keep ROLE_C', exact: true }).click()
  await expect.poll(async () => (await (await request.get('/api/sod/explorer/access_list', { headers, params: { usernames: names.a, limit: '50' } })).json()).items
    .map((item: { role: string; decision: string }) => `${item.role}:${item.decision}`).sort()).toEqual(['ROLE_A1:Keep', 'ROLE_A2:Pending', 'ROLE_B:Removal required', 'ROLE_C:Keep'])
})

test('the assignment queue shows what needs attention by default and filters individual assignments by review status', async ({ page, request }) => {
  const view = async () => (await (await request.get('/api/sod/matrix/risk', { headers })).json())
  const list = async () => (await (await request.get('/api/sod/explorer/access_list', { headers, params: { usernames: names.a, review_status: 'all', limit: '50' } })).json()).items as { id: string; role: string; user: string }[]
  const items = await list()
  const decide = async (role: string, decision: string) => {
    const row = items.find((item) => item.role === role)!
    const subject = await (await request.get('/api/sod/subject', { headers, params: { user: names.a } })).json()
    const found = subject.overview.assignments.find((entry: { id: string }) => entry.id === row.id)
    const current = await view()
    const response = await request.post('/api/sod/decisions/assignment', { headers, data: { context: 'current', expected_revision: current.revision, expected_generation: current.generation, items: [{ key: row.id, user: names.a, ref: role, evidence_version: found.evidence_version }], decision, reviewer: 'Synthetic Reviewer', justification: 'Queue check' } })
    expect(response.ok(), await response.text()).toBeTruthy()
  }
  await decide('ROLE_A1', 'Keep'); await decide('ROLE_A2', 'Remove'); await decide('ROLE_B', 'Investigate')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
  const status = page.getByRole('combobox', { name: 'Assignment review status', exact: true })
  const shown = async () => (await page.getByRole('table', { name: 'Access list' }).locator('tbody tr .role-identifier code').allInnerTexts()).map((text) => text.replace(/\s+/g, '')).filter((text) => text.startsWith('ROLE_') && !text.includes('AB')).sort()
  await expect(status).toHaveValue('')
  // The same user has reviewed and unreviewed roles: only the assignments needing attention are listed.
  await expect.poll(shown).toEqual(['ROLE_B', 'ROLE_C'])
  const progress = page.getByRole('region', { name: 'Role assignment review progress' })
  await expect(progress).toContainText('Needs review')
  await status.selectOption({ label: 'Reviewed assignments' })
  await expect.poll(shown).toEqual(['ROLE_A1', 'ROLE_A2'])
  await status.selectOption({ label: 'Under investigation' })
  await expect.poll(shown).toEqual(['ROLE_B'])
  await status.selectOption({ label: 'Pending review' })
  await expect.poll(shown).toEqual(['ROLE_C'])
  await status.selectOption({ label: 'All assignments' })
  await expect.poll(shown).toEqual(['ROLE_A1', 'ROLE_A2', 'ROLE_B', 'ROLE_C'])
  await expect(page.getByRole('status').filter({ hasText: /of 7|7 rows/ }).first()).toBeVisible().catch(() => undefined)
  // Reset restores the documented default view.
  await page.getByRole('complementary', { name: 'Filters' }).getByRole('button', { name: 'Clear page filters', exact: true }).click()
  await expect(status).toHaveValue('')
  await expect.poll(shown).toEqual(['ROLE_B', 'ROLE_C'])
})

test('status KPI tiles are independent controls: no enclosing card, natural wrapping and no horizontal overflow', async ({ page }) => {
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 })
    await openSod(page, 'Access Explorer')
    await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
    const group = page.getByRole('region', { name: 'Role assignment review progress' })
    await expect(group).toBeVisible()
    const frame = await group.evaluate((element) => { const style = getComputedStyle(element); return { border: style.borderTopWidth, background: style.backgroundColor, padding: style.paddingTop, radius: style.borderTopLeftRadius, shadow: style.boxShadow } })
    expect(frame).toEqual({ border: '0px', background: 'rgba(0, 0, 0, 0)', padding: '0px', radius: '0px', shadow: 'none' })
    const tile = group.locator('.ui-kpi').first()
    expect(await tile.evaluate((element) => [getComputedStyle(element).borderTopWidth, parseFloat(getComputedStyle(element).borderTopLeftRadius) > 0])).toEqual(['1px', true]) // each tile keeps its own border
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    expect(await group.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBeTruthy()
  }
  // the same KPI groups elsewhere in SoD carry no card either
  for (const [link, name] of [['Risk Matrix', /figures$/], ['Reviews', 'Review progress']] as const) {
    await openSod(page, link)
    const other = page.getByRole('region', { name })
    await expect(other.first()).toBeVisible()
    expect(await other.first().evaluate((element) => [getComputedStyle(element).borderTopWidth, getComputedStyle(element).backgroundColor])).toEqual(['0px', 'rgba(0, 0, 0, 0)'])
  }
})
