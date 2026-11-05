import { test, expect, type APIRequestContext } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { headers, seedSources, sessionUrl, type SeededSources } from './support'

const USERS = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\n' +
  'DEMO_DONE,ZC:FI:VIEW,done@example.test,DEMO,20000101,20010101,20000101,20010101\nDEMO_OPEN2,ZC:FI:VIEW,open2@example.test,DEMO,20000101,20010101,20000101,20010101\n'
let seeded: SeededSources
test.beforeEach(async ({ request }) => { seeded = await seedSources(request, { roles: readFileSync('tests/fixtures/role-catalogue-minimal.csv', 'utf8'), users: USERS }) })
test.afterEach(async () => { await seeded.cleanup() })

async function decide(request: APIRequestContext, user: string, state: string) {
  const list = await (await request.get('/api/account-review?include_completed=true&limit=100', { headers })).json()
  const row = list.items.find((item: { username: string }) => item.username === user)
  const response = await request.post(`/api/account-review/decision/${user}`, { headers, data: { state, reviewer: 'R', rationale: 'checked', evidence_version: row.evidence_version, expected_decision: row.decision?.timestamp } })
  expect(response.ok(), await response.text()).toBeTruthy()
}
const rows = (page: import('@playwright/test').Page, user: string) => page.getByRole('row').filter({ hasText: user })

test('a completed review leaves the default queue, Show reviewed brings it back and the finding stays', async ({ page, request }) => {
  await decide(request, 'DEMO_DONE', 'No action required')
  await page.goto(sessionUrl); await page.goto('/#/user-access/account-review')
  await expect(rows(page, 'DEMO_OPEN2').last()).toBeVisible()
  await expect(rows(page, 'DEMO_DONE')).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: '1 completed review hidden' })).toBeVisible()
  await page.getByRole('button', { name: 'Show reviewed' }).click()
  const done = rows(page, 'DEMO_DONE').last()
  await expect(done).toBeVisible()
  await expect(done).toContainText('Review completed')
  await expect(done).toContainText('Expired SAP account') // the underlying finding is preserved
  await expect(page.getByRole('checkbox', { name: 'Include completed reviews' })).toBeChecked()
  await page.getByRole('checkbox', { name: 'Include completed reviews' }).uncheck()
  await expect(rows(page, 'DEMO_DONE')).toHaveCount(0)
})

test('filtering by a completed decision shows it, while Investigating stays in the default queue', async ({ page, request }) => {
  await decide(request, 'DEMO_DONE', 'No action required')
  await decide(request, 'DEMO_OPEN2', 'Investigating')
  await page.goto(sessionUrl); await page.goto('/#/user-access/account-review')
  await expect(rows(page, 'DEMO_OPEN2').last()).toBeVisible()
  await expect(rows(page, 'DEMO_DONE')).toHaveCount(0)
  const decision = page.getByRole('combobox', { name: 'Review decision', exact: true })
  await decision.click(); await decision.fill('No action required'); await page.getByRole('option', { name: 'No action required', exact: true }).click()
  await expect(rows(page, 'DEMO_DONE').last()).toBeVisible()
})

test('the review CSV export follows the same completed-review semantics as the list', async ({ page, request }) => {
  await decide(request, 'DEMO_DONE', 'No action required')
  const hidden = await (await request.get('/api/account-review?limit=100', { headers })).json()
  const shown = await (await request.get('/api/account-review?limit=100&include_completed=true', { headers })).json()
  expect(shown.total - hidden.total).toBe(hidden.completed_hidden)
  expect(hidden.items.map((r: { username: string }) => r.username)).not.toContain('DEMO_DONE')
  await page.goto(sessionUrl); await page.goto('/#/user-access/account-review')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export review CSV' }).click()
  const text = (await import('node:fs')).readFileSync(await (await download).path()!, 'utf8')
  expect(text).not.toContain('DEMO_DONE'); expect(text).toContain('DEMO_OPEN2')
})
