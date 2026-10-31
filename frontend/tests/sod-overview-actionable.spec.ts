import { test, expect, type Page } from '@playwright/test'
import { cleanup, decide, headers, names, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const group = (page: Page, name: string) => page.getByRole('region', { name, exact: true })

test('Conflicts counts users with more than one distinct risk and opens the filtered Explorer', async ({ page }) => {
  await openSod(page)
  const conflicts = group(page, 'Conflicts')
  const multi = conflicts.getByRole('button', { name: 'Users with more than one risk' })
  await expect(multi).toContainText('1')
  await expect(multi).toHaveAttribute('title', /different risk IDs/)
  await multi.click()
  await expect(page).toHaveURL(/#\/sod\/explorer/)
  const table = page.getByRole('table', { name: 'User risk table' })
  await expect(table).toContainText(names.a)
  await expect(table).not.toContainText(names.b)
  await expect(page.getByRole('combobox', { name: 'Risks per user' })).toHaveValue('true')
  await page.getByRole('combobox', { name: 'Risks per user' }).selectOption('')
  await expect(table).toContainText(names.b)
})

test('Remediation awaiting action opens the filtered list and the Overview no longer shows conflicting roles or verified remediation', async ({ page, request }) => {
  await openSod(page)
  const remediation = group(page, 'Remediation')
  await expect(remediation.getByRole('button', { name: 'Remediation awaiting action' })).toContainText('0')
  await expect(remediation.getByRole('button', { name: 'Remediation verified' })).toHaveCount(0)
  await expect(group(page, 'Conflicts').getByText('Most common conflicting roles')).toHaveCount(0)
  const subject = await (await request.get('/api/sod/subject', { headers, params: { context: 'current', user: names.a } })).json()
  const detail = subject.activities.find((row: { activity: string }) => row.activity === 'A')
  const found = detail.assignments.find((item: { role: string }) => item.role === 'ROLE_A2')
  await decide(request, 'assignment', 'current', [{ key: found.id, user: names.a, ref: 'ROLE_A2', evidence_version: found.evidence_version }], 'Remove')
  await page.reload()
  await openSod(page)
  await expect(group(page, 'Remediation').getByRole('button', { name: 'Remediation awaiting action' })).toContainText('1')
  await group(page, 'Remediation').getByRole('button', { name: 'Remediation awaiting action' }).click()
  await expect(page).toHaveURL(/#\/sod\/reviews/)
  const tracking = page.getByRole('toolbar', { name: 'Remediation tracking' }).or(page.getByLabel('Remediation tracking'))
  await expect(tracking.getByRole('button', { name: 'Awaiting action' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('table', { name: 'Access remediation rows' })).toContainText('ROLE_A2')
  await tracking.getByRole('button', { name: 'Verified removals' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'A completed status alone never verifies' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Access remediation rows' })).toHaveCount(0)
})

test('Conflicts, Reviews and Remediation rows share one height and spacing', async ({ page }) => {
  await openSod(page)
  const heights = new Set<number>(), tops: number[] = []
  for (const name of ['Conflicts', 'Reviews', 'Remediation']) {
    const rows = group(page, name).locator('.info-row')
    expect(await rows.count()).toBeGreaterThanOrEqual(4)
    for (const box of await rows.evaluateAll((items) => items.map((item) => item.getBoundingClientRect().height))) heights.add(Math.round(box))
    tops.push(Math.round((await rows.first().boundingBox())!.y))
  }
  expect(heights.size).toBe(1) // identical row height in every card
  expect(new Set(tops).size).toBe(1) // first rows line up across the three cards
})
