import { test, expect, type APIRequestContext } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { headers, openSettings, seedSources, type SeededSources } from './support'

const HEAD = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\n'
const users = (count: number) => HEAD + Array.from({ length: count }, (_, i) => [0, 1].map(r => `IC${String(i).padStart(3, '0')},ZC:FI:VIEW${r},ic${i}@example.test,${i % 2 ? 'FIN' : 'MM'},20200101,99991231,20200101,99991231`).join('\n')).join('\n') + '\n'
let seeded: SeededSources, file: string
const activeUsers = async (request: APIRequestContext) => (await (await request.get('/api/access/users?limit=1', { headers })).json()).total as number

test.beforeEach(async ({ request }) => {
  seeded = await seedSources(request, { roles: readFileSync('tests/fixtures/role-catalogue-minimal.csv', 'utf8'), users: users(40) })
  file = path.join(seeded.directory, 'users.csv')
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  const baseline = await request.post('/api/data-sources/users/select', { headers, data: { path: file, revision: settings.revision, mode: 'dynamic' } })
  expect(baseline.ok(), await baseline.text()).toBeTruthy()
})
test.afterEach(async () => { await seeded.cleanup() })

async function selectUsersFile(page: import('@playwright/test').Page) {
  await openSettings(page, 'Data Sources')
  await page.getByRole('tab', { name: 'User Access', exact: true }).click()
  const field = page.getByLabel('User CSV file location', { exact: true })
  await field.fill(file); await field.press('Enter')
}

test('a sharply smaller valid file is held, shows the change report and activates only after confirmation', async ({ page, request }) => {
  expect(await activeUsers(request)).toBe(40)
  writeFileSync(file, users(12))
  await selectUsersFile(page)
  const dialog = page.getByRole('dialog', { name: 'Confirm a much smaller import' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('list', { name: 'Triggered checks' })).toContainText('fell from')
  await expect(dialog.getByRole('table', { name: 'Active and new counts' })).toContainText('SAP users')
  expect(await activeUsers(request)).toBe(40)                 // nothing changed while the report is open
  await dialog.getByRole('button', { name: 'Keep current data' }).click()
  await expect(dialog).toHaveCount(0)
  expect(await activeUsers(request)).toBe(40)
  await selectUsersFile(page)
  await page.getByRole('dialog', { name: 'Confirm a much smaller import' }).getByRole('button', { name: 'Import anyway' }).click()
  await expect.poll(() => activeUsers(request)).toBe(12)
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  expect(settings.data_lifecycle.confirmations.at(-1)).toMatchObject({ source: 'users', old_records: 80, new_records: 24 })
})

test('an invalid file is rejected without an option to confirm, and thresholds are editable in Settings', async ({ page, request }) => {
  writeFileSync(file, 'NOT,A,USER,EXPORT\n1,2,3,4\n')
  await selectUsersFile(page)
  await expect(page.getByRole('dialog', { name: 'Confirm a much smaller import' })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'User Access source management' }).getByRole('alert')).toBeVisible()
  expect(await activeUsers(request)).toBe(40)
  await page.getByText('Import checks', { exact: true }).click()
  const limit = page.getByLabel('Largest accepted reduction (%)', { exact: true })
  await expect(limit).toHaveValue('30')
  await limit.fill('10')
  await page.getByRole('button', { name: /Apply settings|Save/ }).first().click()
  await expect.poll(async () => (await (await request.get('/api/configuration', { headers })).json()).settings.import_checks.max_drop_percent).toBe(10)
})
