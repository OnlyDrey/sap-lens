import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers, goTo } from './support'

let directory: string, usersPath: string
const roles = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:MM:A,Demo purchasing,ZS:A,MIGO\n'
const userCsv = (names: string[]) => 'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n' + names.map(name => `${name},ZC:MM:A,G1,20200101,99991231\n`).join('')

test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-revision-'))
  const rolePath = path.join(directory, 'roles.csv')
  usersPath = path.join(directory, 'users.csv')
  writeFileSync(rolePath, roles)
  writeFileSync(usersPath, userCsv(['DEMO_ONE', 'DEMO_TWO']))
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = rolePath
  settings.user_csv_path = usersPath
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

async function open(page: Page) {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  await expect(page.getByText('DEMO_ONE', { exact: true }).first()).toBeVisible()
}

// API-level integration through the real test server and /api/refresh; complements test_data_revision (cache.load_cache), FULL only.
test('every API response names the data revision and a refresh that publishes data advances it', { tag: '@integration' }, async ({ request }) => {
  const before = (await request.get('/api/access/users?limit=5', { headers })).headers()['x-data-revision']
  expect(before).toMatch(/^[a-f0-9]+\.\d+\.\d+$/)
  writeFileSync(usersPath, userCsv(['DEMO_ONE', 'DEMO_TWO', 'DEMO_THREE']))
  expect((await request.post('/api/refresh', { headers })).ok()).toBeTruthy()
  const after = (await request.get('/api/access/users?limit=5', { headers })).headers()['x-data-revision']
  const [bootA, publicationA] = before.split('.'), [bootB, publicationB] = after.split('.')
  expect(bootB).toBe(bootA)
  expect(Number(publicationB)).toBeGreaterThan(Number(publicationA))
})

test('a response built from older data is repeated and never shown', async ({ page }) => {
  await open(page)
  let seen = ''
  page.on('response', response => { const token = response.headers()['x-data-revision']; if (token) seen = token })
  await expect.poll(() => seen).not.toBe('')
  const boot = seen.split('.')[0]
  let calls = 0
  await page.route(/\/api\/access\/users\?/, async route => {
    calls += 1
    const real = await route.fetch()
    if (calls > 1) return route.fulfill({ response: real })
    // The first answer to the next query comes from data older than the revision this page already knows: wrong content, stale revision.
    const body = await real.json()
    body.items[0].username = 'STALE_USER'
    await route.fulfill({ response: real, json: body, headers: { ...real.headers(), 'x-data-revision': `${boot}.0.0` } })
  })
  await page.getByPlaceholder('Username, name, email or group').fill('DEMO')
  await expect.poll(() => calls).toBeGreaterThanOrEqual(2)                                  // the stale answer was discarded and the query repeated
  await expect(page.getByText('DEMO_ONE', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('STALE_USER', { exact: true })).toHaveCount(0)
})

test('data published by someone else is noticed from the next response, without the configuration poll', async ({ page, request }) => {
  await open(page)
  let polls = 0
  await page.route('**/api/configuration', async route => {
    if (route.request().method() !== 'GET') return route.continue()
    polls += 1
    await route.fulfill({ status: 503, json: { detail: 'poll blocked by the test' } })         // the periodic poll can no longer report the change
  })
  writeFileSync(usersPath, userCsv(['DEMO_ONE', 'DEMO_TWO', 'DEMO_THREE']))
  expect((await request.post('/api/refresh', { headers })).ok()).toBeTruthy()                    // another user publishes new data
  const polled = polls
  await page.getByPlaceholder('Username, name, email or group').fill('DEMO')
  await expect(page.getByText('DEMO_THREE', { exact: true }).first()).toBeVisible()
  await expect.poll(() => polls).toBeGreaterThan(polled)                                       // the newer revision made the application re-read its shared state itself
})
