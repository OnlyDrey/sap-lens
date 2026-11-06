import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { goTo, headers, seedSources, type SeededSources } from './support'

const unique = Date.now().toString(36)
const USERS = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\n' +
  ['BULK_A', 'BULK_B', 'BULK_C'].map(u => `${u},ZC:FI:VIEW,${u.toLowerCase()}@example.test,DEMO,20200101,99991231,20200101,99991231`).join('\n') + '\n'
let seeded: SeededSources
test.beforeEach(async ({ request }) => {
  seeded = await seedSources(request, { roles: readFileSync('tests/fixtures/role-catalogue-minimal.csv', 'utf8'), users: USERS })
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.features.employee_directory = true
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async () => { await seeded.cleanup() })

async function group(request: APIRequestContext, name: string) {
  const response = await request.post('/api/functional-groups', { headers, data: { name, description: '' } })
  expect(response.ok()).toBeTruthy(); return (await response.json()).id as string
}
const row = (page: Page, user: string) => page.getByRole('row').filter({ has: page.getByRole('link', { name: user, exact: true }) })

test('bulk assignment: toolbar order, replacement confirmation, results, profile and filter sync', async ({ page, request }) => {
  const target = `Bulk Target ${unique}`, other = `Bulk Other ${unique}`
  await group(request, target); const otherId = await group(request, other)
  const first = await request.put('/api/functional-groups/users/BULK_B', { headers, data: { group_id: otherId, reviewer: 'R', rationale: 'seed', expected_revision: 0 } })
  expect(first.ok(), await first.text()).toBeTruthy()
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  await expect(page.getByRole('button', { name: 'Assign group' })).toHaveCount(0)
  await row(page, 'BULK_A').getByRole('checkbox').check(); await row(page, 'BULK_B').getByRole('checkbox').check()
  await expect(page.getByRole('heading', { name: /2 selected/ })).toBeVisible()
  // order and uniform size: Assign group, Clear selection, Export CSV
  const names = ['Assign group', 'Clear selection', 'Export CSV']
  const boxes = []
  for (const name of names) { const button = page.getByRole('button', { name, exact: true }); await expect(button.locator('svg')).toHaveCount(1); boxes.push((await button.boundingBox())!) }
  expect(boxes[0].x).toBeLessThan(boxes[1].x); expect(boxes[1].x).toBeLessThan(boxes[2].x)
  expect(new Set(boxes.map(b => Math.round(b.height))).size).toBe(1)
  await page.getByRole('button', { name: 'Assign group', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Assign Functional Groups' })
  await expect(dialog).toContainText('2 users selected')
  const submit = dialog.getByRole('button', { name: 'Assign groups' })
  await expect(submit).toBeDisabled()
  const picker = dialog.getByRole('combobox', { name: 'Search or create a Functional Group' })
  await picker.fill(target)
  await dialog.getByRole('option', { name: target }).click()
  await picker.fill(other)                                                                                  // several groups, the list stays usable
  await dialog.getByRole('option', { name: other }).click()
  await expect(dialog.getByRole('list', { name: 'Selected Functional Groups' })).toContainText(target)
  await expect(dialog.getByRole('list', { name: 'Selected Functional Groups' })).toContainText(other)
  await expect(dialog).toContainText('Current assignments'); await expect(dialog).toContainText(`${other}: 1 user`); await expect(dialog).toContainText('Unassigned: 1 user')
  await expect(dialog).toContainText('keeps all existing groups')                                           // adding, never replacing
  await dialog.getByLabel('Reviewer').fill('Reviewer One')
  await expect(submit).toBeDisabled()                                                                       // explicit confirmation first
  await dialog.getByRole('checkbox').check()
  await submit.click()
  await expect(dialog).toContainText('2 users updated')
  await dialog.getByRole('button', { name: 'Done', exact: true }).click()
  await expect(row(page, 'BULK_A')).toContainText(target); await expect(row(page, 'BULK_B')).toContainText(target)
  await expect(row(page, 'BULK_B')).toContainText(other)                                                   // the existing membership is kept
  await expect(row(page, 'BULK_C')).toContainText('Unassigned')
  // Clear selection keeps data and filters
  await page.getByRole('button', { name: 'Clear selection' }).click()
  await expect(page.getByRole('button', { name: 'Assign group', exact: true })).toHaveCount(0)
  // profile sync
  await page.getByRole('link', { name: 'BULK_A', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Functional Group', exact: true })).toContainText(target)
})

test('cancel changes nothing and the dialog fits a narrow screen', async ({ page, request }) => {
  const name = `Cancel Target ${unique}`
  await group(request, name)
  await page.goto('/#session=browser-test-session'); await goTo(page, 'User Access')
  await row(page, 'BULK_C').getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Assign group', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Assign Functional Groups' })
  await dialog.getByRole('combobox', { name: 'Search or create a Functional Group' }).fill(name); await dialog.getByRole('option', { name }).click()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toHaveCount(0); await expect(row(page, 'BULK_C')).toContainText('Unassigned')
  // narrow screen: dialog usable, no page overflow
  await page.setViewportSize({ width: 375, height: 800 })
  await page.getByRole('button', { name: 'Assign group', exact: true }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('dialog', { name: 'Assign Functional Groups' }).getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
})
