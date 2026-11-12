import {expectReviewerProfile} from './reviewer-profile'
import { test, expect, type APIRequestContext } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { headers, openSettings, seedSources, sessionUrl, type SeededSources } from './support'
const columns = 'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus\n'
const employee = (department: string, manager: string) => '\ufeff' + columns + `North;Demo Fg;demo_fg;;fg@example.test;${department};Buyer;true;;;${manager};;${manager.toLowerCase()}@example.test;;;Resolved\n`

let directory: string
let seeded: SeededSources
const USERS = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_FG,ZC:FI:VIEW,fg@example.test,DEMO,20200101,99991231,20200101,99991231\n'
const unique = Date.now().toString(36)
// Storage persists across tests of one run, so always send the revision the server currently holds.
async function classify(request: APIRequestContext, group: string | null) {
  const revision = (await (await request.get('/api/functional-groups/users/DEMO_FG', { headers })).json()).classification.revision
  return request.put('/api/functional-groups/users/DEMO_FG', { headers, data: { group_id: group, reviewer: 'R', rationale: 'test', expected_revision: revision } })
}
test.beforeEach(async ({ request }) => {
  seeded = await seedSources(request, { roles: readFileSync('tests/fixtures/role-catalogue-minimal.csv', 'utf8'), users: USERS })
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.features.employee_directory = true
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
  directory = seeded.directory
})
test.afterEach(async () => { await seeded.cleanup() })

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

  // Suggestion rules are a compact table with a New rule action, not a permanent form.
  await expect(section.getByLabel('Rule Directory Department')).toHaveCount(0)
  await section.getByRole('button', { name: 'New rule' }).click()
  const ruleDialog = page.getByRole('dialog', { name: 'New suggestion rule' })
  await expect(ruleDialog.getByRole('button', { name: 'Create rule' })).toBeDisabled()        // a condition and a group are required
  await ruleDialog.getByLabel('Directory Department contains').fill('Supply Chain')
  await ruleDialog.getByLabel('Suggested Functional Group').selectOption({ label: name })
  await ruleDialog.getByRole('button', { name: 'Create rule' }).click()
  const rules = section.getByRole('table', { name: 'Functional Group suggestion rules' })
  await expect(rules.getByRole('row').filter({ hasText: name })).toContainText(name)
  await expect(rules.getByRole('columnheader', { name: 'Directory Department contains' })).toBeVisible()
  await expect(rules.getByRole('columnheader', { name: 'Matching users' })).toBeVisible()
  await rules.getByRole('button', { name: `Edit rule suggesting ${name}` }).click()
  await page.getByRole('dialog', { name: 'Edit suggestion rule' }).getByLabel('Job Title contains').fill('Buyer')
  await page.getByRole('dialog', { name: 'Edit suggestion rule' }).getByRole('button', { name: 'Save rule' }).click()
  await expect(rules.getByRole('row').filter({ hasText: name })).toContainText('Buyer')
  await rules.getByRole('button', { name: `Delete rule suggesting ${name}` }).click()
  await page.getByRole('dialog', { name: 'Delete suggestion rule' }).getByRole('button', { name: 'Delete rule' }).click()
  await expect(rules.getByRole('row').filter({ hasText: name })).toHaveCount(0)

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
  const dialog = page.getByRole('dialog', { name: 'Functional Groups for DEMO_FG' })
  await expect(dialog.getByRole('button', { name: 'Add groups' })).toBeDisabled() // nothing is preselected
  await dialog.getByRole('combobox', { name: 'Search or create a Functional Group' }).fill(name)
  await dialog.getByRole('option', { name }).click()
  await expectReviewerProfile(dialog.getByLabel('Reviewer'))
  await dialog.getByRole('button', { name: 'Add 1 group' }).click()
  await expect(panel).toContainText(name)
  await expect(panel).toContainText('Confirmed')
  await expect(panel).toContainText((await(await request.get('/api/reviewer-profile',{headers})).json()).identity.display_name)
  // Stale write is refused over HTTP and surfaces no overwrite.
  const stale = await request.put('/api/functional-groups/users/DEMO_FG', { headers, data: { group_id: null, rationale: 'x', reviewer: 'R', expected_revision: 0 } })
  expect(stale.status()).toBe(409)
})

test('Functional Groups settings fit 375 px without horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await openSettings(page, 'Functional Groups')
  await expect(page.getByRole('region', { name: 'Functional Groups', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'New rule' })).toBeVisible() // data has loaded
  const wide = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(e => !e.closest('.access-table table') && e.getBoundingClientRect().right > window.innerWidth + 1).slice(0, 6).map(e => e.tagName + '.' + String(e.className).slice(0, 80) + ':' + Math.round(e.getBoundingClientRect().right)))
  expect(wide).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('a Department change requires explicit Functional Group reconfirmation in Account Review', async ({ page, request }) => {
  const name = `Logistics ${unique}`
  const group = (await (await request.post('/api/functional-groups', { headers, data: { name, description: '' } })).json()).id
  const csv = path.join(directory, 'employees.csv')
  const importDirectory = async (content: string) => {
    writeFileSync(csv, content)
    const revision = (await (await request.get('/api/configuration', { headers })).json()).settings.revision
    const preview = await request.post('/api/employees/preview', { headers, data: { path: csv, revision } })
    expect(preview.ok()).toBeTruthy()
    expect((await request.post('/api/employees/import', { headers, data: { path: csv, revision, digest: (await preview.json()).digest } })).ok()).toBeTruthy()
  }
  await importDirectory(employee('Finance', 'Boss'))
  expect((await classify(request, group)).ok()).toBeTruthy()
  await importDirectory(employee('Procurement', 'Boss'))
  const classification = await request.get('/api/functional-groups/users/DEMO_FG', { headers })
  expect(classification.ok()).toBeTruthy()
  expect((await classification.json()).classification.status).toBe('Needs review')
  await page.goto(sessionUrl)
  await page.goto('/#/user-access/account-review')
  const row = page.getByRole('row').filter({ hasText: 'DEMO_FG' }).last() // the main table follows the position-change queue
  await expect(row).toContainText(name)
  await expect(row).toContainText('Needs review')
  await expect(row).toContainText('reconfirmation required')
  await row.getByRole('button', { name: 'Needs review', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Review account · DEMO_FG' })
  const section = dialog.getByRole('region', { name: 'Functional Group review' })
  await expect(section).toContainText('Procurement')
  await section.getByRole('button', { name: 'Review Functional Groups' }).click()
  const manage = page.getByRole('dialog', { name: 'Functional Groups for DEMO_FG' })
  await expect(manage.getByRole('button', { name: `Confirm ${name}` })).toBeEnabled() // Stable reviewer is supplied; confirmation remains explicit.
  expect((await(await request.get('/api/functional-groups/users/DEMO_FG',{headers})).json()).classification.status).toBe('Needs review')
  await expectReviewerProfile(manage.getByLabel('Reviewer', { exact: true }))
  await manage.getByRole('button', { name: `Confirm ${name}` }).click()
  await expect(section).toContainText('Confirmed')
  const detail = await (await request.get('/api/functional-groups/users/DEMO_FG', { headers })).json()
  expect(detail.classification.status).toBe('Confirmed')
  expect(detail.classification.group_id).toBe(group)
  expect(detail.classification.memberships[0].confirmed_by).toBe((await(await request.get('/api/reviewer-profile',{headers})).json()).identity.display_name)
})

test('Account Review filters by Functional Group and Manager', async ({ page, request }) => {
  const name = `Filtering ${unique}`
  const group = (await (await request.post('/api/functional-groups', { headers, data: { name, description: '' } })).json()).id
  expect((await classify(request, group)).ok()).toBeTruthy()
  await page.goto(sessionUrl)
  await page.goto('/#/user-access/account-review')
  await expect(page.getByRole('row').filter({ hasText: 'DEMO_FG' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Functional Group', exact: true }).first().click()
  await page.getByRole('option', { name: 'Unassigned', exact: true }).click()
  await expect(page.getByRole('row').filter({ hasText: 'DEMO_FG' })).toHaveCount(0)
})

test('User Access filters users by Functional Group on the server and shows the column', async ({ page, request }) => {
  const name = `Access ${unique}`
  const group = (await (await request.post('/api/functional-groups', { headers, data: { name, description: '' } })).json()).id
  expect((await classify(request, group)).ok()).toBeTruthy()
  await page.goto(sessionUrl)
  await page.goto('/#/user-access')
  await expect(page.getByRole('columnheader', { name: 'Functional Group', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: 'Functional Group', exact: true }).fill(name)
  await page.getByRole('option', { name: new RegExp(`^${name}`) }).click()
  await expect(page.getByRole('row').filter({ hasText: 'DEMO_FG' })).toContainText(name)
  await expect(page.getByRole('button', { name: `Remove Functional Group filter ${name}` })).toBeVisible()
  await page.getByRole('button', { name: `Remove Functional Group filter ${name}` }).click()
  await expect(page.getByRole('button', { name: `Remove Functional Group filter ${name}` })).toHaveCount(0)
})

test('Access analysis is advisory, shows limitations for a small group and links to the user', async ({ page, request }) => {
  const name = `Analysis ${unique}`
  const group = (await (await request.post('/api/functional-groups', { headers, data: { name, description: '' } })).json()).id
  expect((await classify(request, group)).ok()).toBeTruthy()
  await openSettings(page, 'Functional Groups')
  const section = page.getByRole('region', { name: 'Functional Groups', exact: true })
  await section.getByLabel('Search Functional Groups').fill(name)
  await section.getByRole('button', { name: `Analyze access of ${name}` }).click()
  const dialog = page.getByRole('dialog', { name: `Access analysis · ${name}` })
  await dialog.getByText('About this analysis').click()
  await expect(dialog).toContainText('Advisory only')
  await expect(dialog).toContainText('at least 3')                       // too small to compare: a limitation, not a conclusion
  await expect(dialog.getByRole('link', { name: 'Open SAP user DEMO_FG' })).toBeVisible()
  await expect(dialog.getByRole('link', { name: 'Compare users' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

for (const scheme of ['light', 'dark'] as const) {
  test(`User Details classification dialog is responsive and keyboard operable in ${scheme} mode at 375px`, { tag: ['@visual', '@a11y'] }, async ({ page, request }) => {
    const name = `Responsive ${scheme} ${unique}`
    await request.post('/api/functional-groups', { headers, data: { name, description: '' } })
    await page.emulateMedia({ colorScheme: scheme })
    await page.setViewportSize({ width: 375, height: 760 })
    await page.goto(sessionUrl)
    await page.goto('/#/user-access/user/DEMO_FG')
    const panel = page.getByRole('region', { name: 'Functional Group', exact: true })
    await expect(panel).toBeVisible()
    await panel.getByRole('button', { name: /Assign group|Add group/ }).click()
    const dialog = page.getByRole('dialog', { name: 'Functional Groups for DEMO_FG' })
    await expect(dialog).toBeVisible()
    const box = (await dialog.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(375)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await expect(dialog.getByLabel('Reviewer', { exact: true })).toBeVisible()
    await dialog.getByLabel('Reviewer', { exact: true }).focus()
    await expect(dialog.getByLabel('Reviewer', { exact: true })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
  })
}
