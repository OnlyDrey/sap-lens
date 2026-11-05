import { test, expect } from '@playwright/test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers, openSettings, sessionUrl } from './support'

let directory: string
const unique = Date.now().toString(36)
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-fg-'))
  const users = path.join(directory, 'users.csv')
  writeFileSync(users, 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\n' +
    'DEMO_FG,ZC:FI:VIEW,fg@example.test,DEMO,20200101,99991231,20200101,99991231\n')
  const current = (await (await request.get('/api/configuration', { headers })).json()).settings
  current.data_csv_path = path.resolve('tests/fixtures/role-catalogue-minimal.csv'); current.user_csv_path = users
  expect((await request.post('/api/configuration', { headers, data: current })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

test('Settings administers groups and advisory rules', async ({ page }) => {
  const name = `Purchasing ${unique}`
  await openSettings(page, 'Functional Groups')
  const section = page.getByRole('region', { name: 'Functional Groups', exact: true })
  await section.getByRole('button', { name: 'New group' }).click()
  const dialog = page.getByRole('dialog', { name: 'New Functional Group' })
  await dialog.getByLabel('Name').fill(name)
  await dialog.getByRole('button', { name: 'Create' }).click()
  const row = section.getByRole('row', { name: new RegExp(`^${name}`) })
  await expect(row).toContainText('Active')
  await section.getByRole('button', { name: 'New group' }).click()
  await page.getByRole('dialog').getByLabel('Name').fill(` ${name.toUpperCase()} `)
  await page.getByRole('dialog').getByRole('button', { name: 'Create' }).click()
  await expect(page.getByRole('alert')).toContainText('already exists')
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()

  await section.getByLabel('Rule Directory Department').fill('Supply Chain')
  await section.getByLabel('Rule target Functional Group').selectOption({ label: name })
  await section.getByRole('button', { name: 'Add rule' }).click()
  await expect(section.getByRole('row').filter({ hasText: 'Supply Chain' })).toContainText(name)

  await row.getByRole('button', { name: `Archive ${name}` }).click()
  await expect(row).toContainText('Archived')
  await row.getByRole('button', { name: `Restore ${name}` }).click()
  await expect(row).toContainText('Active')
  await section.getByLabel('Search Functional Groups').fill('no such group')
  await expect(section.getByText('No Functional Groups match the search.')).toBeVisible()
})

test('User Details classifies a user explicitly and keeps it separate from imported data', async ({ page, request }) => {
  const name = `Planning ${unique}`
  expect((await request.post('/api/functional-groups', { headers, data: { name, description: '' } })).ok()).toBeTruthy()
  await page.goto(sessionUrl + '')
  await page.goto('/#/user-access/user/DEMO_FG')
  const panel = page.getByRole('region', { name: 'Functional Group', exact: true })
  await expect(panel).toContainText('Unassigned')
  await panel.getByRole('button', { name: 'Assign group' }).click()
  const dialog = page.getByRole('dialog', { name: 'Functional Group for DEMO_FG' })
  await expect(dialog.getByRole('button', { name: 'Select a group' })).toBeDisabled() // nothing is preselected
  await dialog.getByRole('combobox', { name: 'Functional Group' }).fill(name)
  await page.getByRole('option', { name }).click()
  await dialog.getByLabel('Reviewer').fill('Reviewer One')
  await dialog.getByRole('button', { name: `Assign ${name}` }).click()
  await expect(panel).toContainText(name)
  await expect(panel).toContainText('Confirmed')
  await expect(panel).toContainText('Reviewer One')
  // Stale write is refused over HTTP and surfaces no overwrite.
  const stale = await request.put('/api/functional-groups/users/DEMO_FG', { headers, data: { group_id: null, rationale: 'x', reviewer: 'R', expected_revision: 0 } })
  expect(stale.status()).toBe(409)
})

test('Functional Groups settings fit 375 px without horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await openSettings(page, 'Functional Groups')
  await expect(page.getByRole('region', { name: 'Functional Groups', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add rule' })).toBeVisible() // data has loaded
  const wide = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(e => !e.closest('.access-table table') && e.getBoundingClientRect().right > window.innerWidth + 1).slice(0, 6).map(e => e.tagName + '.' + String(e.className).slice(0, 80) + ':' + Math.round(e.getBoundingClientRect().right)))
  expect(wide).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
