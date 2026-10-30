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

test('Most common conflicting roles show the top five, expand on demand and open the filtered Explorer', async ({ page }) => {
  await page.route('**/api/sod/overview', async (route) => {
    const response = await route.fetch(), body = await response.json()
    const extra = ['ROLE_X1', 'ROLE_X2', 'ROLE_X3'].map((role) => ({ role, users: 1, findings: 1 }))
    body.governance.concentration.top_roles = [...body.governance.concentration.top_roles, ...extra]
    await route.fulfill({ response, json: body })
  })
  await openSod(page)
  const list = group(page, 'Conflicts').getByRole('list', { name: 'Most common conflicting roles' })
  await expect(list.getByRole('listitem')).toHaveCount(5)
  await expect(list.getByRole('listitem').first()).toContainText('ROLE_A1')
  await expect(list.getByRole('listitem').first()).toContainText('2')
  await expect(list.getByRole('listitem').first()).toContainText('1 user')
  const more = group(page, 'Conflicts').getByRole('button', { name: /^Show more/ })
  await more.click()
  await expect(list.getByRole('listitem')).toHaveCount(8)
  await group(page, 'Conflicts').getByRole('button', { name: 'Show fewer' }).click()
  await expect(list.getByRole('listitem')).toHaveCount(5)
  await list.getByRole('button', { name: 'ROLE_AB' }).click()
  await expect(page).toHaveURL(/#\/sod\/explorer/)
  const table = page.getByRole('table', { name: 'User risk table' })
  await expect(table).toContainText(names.b)
  await expect(table).not.toContainText(names.a)
})

test('Remediation awaiting action opens the filtered list; verified stays unavailable until a tracked removal exists', async ({ page, request }) => {
  await openSod(page)
  const remediation = group(page, 'Remediation')
  await expect(remediation.getByRole('button', { name: 'Remediation awaiting action' })).toContainText('0')
  const verified = remediation.getByRole('button', { name: 'Remediation verified' })
  await expect(verified).toContainText('Unavailable')
  // Review history survives resets, so earlier specs may have left tracked actions whose users are gone; either way the state is unavailable and explained.
  await expect(verified).toContainText(/No removal action is tracked yet\.|cannot confirm removals/)
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

test('Remediation verified shows the evidence-based count with its explanation and opens the verified list', async ({ page }) => {
  await page.route('**/api/sod/overview', async (route) => {
    const response = await route.fetch(), body = await response.json()
    body.governance.remediation.verification = { tracked: 3, verified: 2, still_present: 0, awaiting_evidence: 1, not_assessable: 0, available: true, reason: null }
    await route.fulfill({ response, json: body })
  })
  await openSod(page)
  const verified = group(page, 'Remediation').getByRole('button', { name: 'Remediation verified' })
  await expect(verified).toContainText('2')
  await expect(verified).toContainText('2 of 3 tracked removals · 1 awaiting newer evidence')
  await expect(verified).toHaveAttribute('title', /newer than the tracked action/)
  await verified.click()
  await expect(page.getByRole('button', { name: 'Verified removals' })).toHaveAttribute('aria-pressed', 'true')
})
