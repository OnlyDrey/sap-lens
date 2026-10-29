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
  await expect.poll(() => pressed(page, 'ROLE_A1')).toEqual({ keep: 'true', remove: 'false' })
  await row(page, 'ROLE_A2').getByRole('button', { name: 'Remove ROLE_A2', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_A2')).toEqual({ keep: 'false', remove: 'true' })
  await row(page, 'ROLE_B').getByRole('button', { name: 'Keep ROLE_B', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_B')).toEqual({ keep: 'true', remove: 'false' })
  // Earlier decisions are untouched, ROLE_C stays pending.
  expect(await pressed(page, 'ROLE_A1')).toEqual({ keep: 'true', remove: 'false' })
  expect(await pressed(page, 'ROLE_A2')).toEqual({ keep: 'false', remove: 'true' })
  expect(await pressed(page, 'ROLE_C')).toEqual({ keep: 'false', remove: 'false' })
  // Changing one decision leaves the others alone.
  await row(page, 'ROLE_A1').getByRole('button', { name: 'Remove ROLE_A1', exact: true }).click()
  await expect.poll(() => pressed(page, 'ROLE_A1')).toEqual({ keep: 'false', remove: 'true' })
  expect(await pressed(page, 'ROLE_B')).toEqual({ keep: 'true', remove: 'false' })
  expect(await pressed(page, 'ROLE_A2')).toEqual({ keep: 'false', remove: 'true' })
  // Persisted: reload and reopen.
  await page.reload()
  await page.getByRole('button', { name: new RegExp(`^Open ${names.a}`) }).click()
  expect(await pressed(page, 'ROLE_A1')).toEqual({ keep: 'false', remove: 'true' })
  expect(await pressed(page, 'ROLE_A2')).toEqual({ keep: 'false', remove: 'true' })
  expect(await pressed(page, 'ROLE_B')).toEqual({ keep: 'true', remove: 'false' })
  expect(await pressed(page, 'ROLE_C')).toEqual({ keep: 'false', remove: 'false' })
})

test('rapid decisions on different roles are all saved and none replaces another', async ({ page, request }) => {
  await openUser(page)
  await row(page, 'ROLE_A1').getByRole('button', { name: 'Keep ROLE_A1', exact: true }).click()
  await row(page, 'ROLE_B').getByRole('button', { name: 'Remove ROLE_B', exact: true }).click()
  await row(page, 'ROLE_C').getByRole('button', { name: 'Keep ROLE_C', exact: true }).click()
  await expect.poll(async () => (await (await request.get('/api/sod/explorer/access_list', { headers, params: { usernames: names.a, limit: '50' } })).json()).items
    .map((item: { role: string; decision: string }) => `${item.role}:${item.decision}`).sort()).toEqual(['ROLE_A1:Keep', 'ROLE_A2:Pending', 'ROLE_B:Removal required', 'ROLE_C:Keep'])
})
