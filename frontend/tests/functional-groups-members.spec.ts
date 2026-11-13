import {expectReviewerProfile,reviewerName} from './reviewer-profile'
import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { headers, openSettings, seedSources, sessionUrl, type SeededSources } from './support'

const unique = Date.now().toString(36)
const NAMES = ['FG_A', 'FG_B', 'FG_C', 'FG_D', 'FG_E']
const ROLES: Record<string, string[]> = { FG_A: ['ZC:FI:VIEW', 'ZC:FI:EXTRA'], FG_B: ['ZC:FI:VIEW', 'ZC:FI:EXTRA'], FG_C: ['ZC:FI:VIEW'], FG_D: ['ZC:FI:VIEW'], FG_E: ['ZC:FI:VIEW', 'ZC:FI:PAY'] }
const USERS = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\n' +
  NAMES.flatMap(n => ROLES[n].map(r => `${n},${r},${n.toLowerCase()}@example.test,DEMO,20200101,99991231,20200101,99991231`)).join('\n') + '\n'
const columns = 'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus\n'
const DEPARTMENT: Record<string, [string, string]> = { FG_A: ['Global Supply Chain', 'Senior Buyer'], FG_B: ['Supply Chain Planning', 'Planner'], FG_C: ['Supply Chain', 'Buyer'], FG_D: ['Finance', 'Accountant'], FG_E: ['Finance', 'Payer'] }
const directoryCsv = '﻿' + columns + NAMES.map(n => `North;Person ${n};${n.toLowerCase()};;${n.toLowerCase()}@example.test;${DEPARTMENT[n][0]};${DEPARTMENT[n][1]};true;;;Boss;;boss@example.test;;;Resolved`).join('\n') + '\n'
let seeded: SeededSources

test.beforeEach(async ({ request }) => {
  seeded = await seedSources(request, { roles: readFileSync('tests/fixtures/role-catalogue-minimal.csv', 'utf8'), users: USERS })
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.features.employee_directory = true
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
  const csv = path.join(seeded.directory, 'employees.csv')
  writeFileSync(csv, directoryCsv)
  const revision = (await (await request.get('/api/configuration', { headers })).json()).settings.revision
  const preview = await request.post('/api/employees/preview', { headers, data: { path: csv, revision } })
  expect(preview.ok(), await preview.text()).toBeTruthy()
  expect((await request.post('/api/employees/import', { headers, data: { path: csv, revision, digest: (await preview.json()).digest } })).ok()).toBeTruthy()
  await resetClassification(request)
})
test.afterEach(async () => { await seeded.cleanup() })

/** The classification store is shared by the disposable test server, so every test starts from users without memberships and without rules. */
async function resetClassification(request: APIRequestContext) {
  for (const name of NAMES) {
    const { classification } = await (await request.get(`/api/functional-groups/users/${name}`, { headers })).json()
    if (classification.memberships.length) {
      const response = await request.put(`/api/functional-groups/users/${name}`, { headers, data: { group_id: null, rationale: 'test reset', reviewer: 'Reset', expected_revision: classification.revision } })
      expect(response.ok(), await response.text()).toBeTruthy()
    }
  }
  for (const rule of (await (await request.get('/api/functional-groups/rules', { headers })).json()).items) await request.delete(`/api/functional-groups/rules/${rule.id}`, { headers })
}

async function group(request: APIRequestContext, name: string) {
  const response = await request.post('/api/functional-groups', { headers, data: { name, description: '' } })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()).id as string
}
async function join(request: APIRequestContext, username: string, groupId: string) {
  const current = (await (await request.get(`/api/functional-groups/users/${username}`, { headers })).json()).classification.revision
  const response = await request.post('/api/functional-groups/memberships', { headers, data: { username, group_id: groupId, reviewer: 'Seeder', rationale: 'seed', expected_revision: current } })
  expect(response.ok(), await response.text()).toBeTruthy()
}
async function groupsSection(page: Page, name: string) {
  await openSettings(page, 'Functional Groups')
  const section = page.getByRole('region', { name: 'Functional Groups', exact: true })
  await section.getByLabel('Search Functional Groups').fill(name)
  return section
}

test('a user holds several groups: add keeps the others, remove is per membership with history', async ({ page, request }) => {
  const [one, two] = [`Supply ${unique}`, `Buyers ${unique}`]
  const idOne = await group(request, one)
  await group(request, two)
  await join(request, 'FG_A', idOne)
  await page.goto(sessionUrl)
  await page.goto('/#/user-access/user/FG_A')
  const panel = page.getByRole('region', { name: 'Functional Group', exact: true })
  await expect(panel).toContainText(one)
  await panel.getByRole('button', { name: 'Add group' }).click()
  const dialog = page.getByRole('dialog', { name: 'Functional Groups for FG_A' })
  const picker = dialog.getByRole('combobox', { name: 'Search or create a Functional Group' })
  await picker.fill(two)
  await dialog.getByRole('option', { name: two }).click()
  await expect(dialog.getByRole('list', { name: 'Selected Functional Groups' })).toContainText(two)
  // an existing membership is not offered again; creating a group inline selects it and keeps the earlier choice
  await picker.fill(one)
  await expect(dialog.getByRole('option', { name: new RegExp(one) })).toHaveAttribute('aria-disabled', 'true')   // shown as already a member, not selectable
  const created = `Created ${unique}`
  await picker.fill(created)
  await dialog.getByRole('option', { name: `Create group “${created}”` }).click()
  await expect(dialog.getByRole('list', { name: 'Selected Functional Groups' })).toContainText(created)
  await expect(dialog.getByRole('list', { name: 'Selected Functional Groups' })).toContainText(two)
  await expectReviewerProfile(dialog.getByLabel('Reviewer', { exact: true }))
  await dialog.getByRole('button', { name: 'Add 2 groups' }).click()
  for (const name of [one, two, created]) await expect(panel).toContainText(name)
  // remove one membership: it needs a rationale, and the others stay
  await panel.getByRole('button', { name: 'Manage groups' }).click()
  const manage = page.getByRole('dialog', { name: 'Functional Groups for FG_A' })
  await manage.getByRole('button', { name: `Remove ${two}` }).click()
  const removal = manage.getByRole('group', { name: `Remove ${two}` })
  await expect(removal.getByRole('button', { name: 'Remove group' })).toBeDisabled()
  await removal.getByLabel('Rationale (required)').fill('left the function')
  await removal.getByRole('button', { name: 'Remove group' }).click()
  await expect(panel).not.toContainText(two)
  await expect(panel).toContainText(one); await expect(panel).toContainText(created)
  const detail = await (await request.get('/api/functional-groups/users/FG_A', { headers })).json()
  expect(detail.classification.memberships).toHaveLength(2)
  expect(detail.history.items.map((e: { event: string }) => e.event)).toContain('removed')
})

test('View Members lists members with Directory context, filters, and removes a single membership', async ({ page, request }) => {
  const name = `Members ${unique}`, other = `Other ${unique}`
  const id = await group(request, name), otherId = await group(request, other)
  for (const user of ['FG_A', 'FG_B', 'FG_C']) await join(request, user, id)
  await join(request, 'FG_A', otherId)
  const section = await groupsSection(page, name)
  const row = section.getByRole('row', { name: new RegExp(`^${name}`) })
  await expect(row.getByRole('button', { name: `View ${3} members of ${name}` })).toBeVisible()                // the Users count opens the members
  await row.getByRole('button', { name: `View members of ${name}` }).click()
  const dialog = page.getByRole('dialog', { name: `Members of ${name}` })
  const table = dialog.getByRole('table', { name: `Members of ${name}` })
  await expect(table.getByRole('row')).toHaveCount(4)
  const a = table.getByRole('row').filter({ hasText: 'FG_A' })
  await expect(a).toContainText('Global Supply Chain'); await expect(a).toContainText('Senior Buyer'); await expect(a).toContainText('Person FG_A'); await expect(a).toContainText('Confirmed')
  await expect(a).toContainText(await reviewerName(request)); await expect(a).not.toContainText('Seeder') // the profile, not the alias the seeding request submitted
  await dialog.getByRole('searchbox', { name: 'Search members' }).fill('planner')
  await expect(table.getByRole('row')).toHaveCount(2)
  await dialog.getByRole('searchbox', { name: 'Search members' }).fill('')
  await dialog.getByLabel('Filter by membership status').selectOption('Needs review')
  await expect(dialog.getByText('No member matches the filter.')).toBeVisible()
  await dialog.getByLabel('Filter by membership status').selectOption('')
  // remove FG_A from this group only
  await table.getByRole('button', { name: `Remove FG_A from ${name}` }).click()
  const removal = dialog.getByRole('group', { name: 'Remove members' })
  await expectReviewerProfile(removal.getByLabel('Reviewer'))
  await removal.getByLabel('Rationale (required)').fill('moved')
  await removal.getByRole('button', { name: 'Remove from group' }).click()
  await expect(table.getByRole('row')).toHaveCount(3)
  const detail = await (await request.get('/api/functional-groups/users/FG_A', { headers })).json()
  expect(detail.classification.group_ids).toEqual([otherId])                                                   // the other membership is untouched
  const counts = Object.fromEntries((await (await request.get('/api/functional-groups', { headers })).json()).items.map((g: { name: string; user_count: number }) => [g.name, g.user_count]))
  expect([counts[name], counts[other]]).toEqual([2, 1])
})

test('Access analysis: KPI tiles filter, the Members count drills down to exactly the compared users, and patterns read Common/Shared/Uncommon', async ({ page, request }) => {
  const name = `Analysis ${unique}`
  const id = await group(request, name)
  for (const user of NAMES) await join(request, user, id)
  const section = await groupsSection(page, name)
  await section.getByRole('button', { name: `Analyze access of ${name}` }).click()
  const dialog = page.getByRole('dialog', { name: `Access analysis · ${name}` })
  await expect(dialog.getByRole('button', { name: /^Members/ })).toBeVisible()
  const kpis = dialog.getByRole('group', { name: 'Group summary' })
  for (const label of ['Members', 'Compared', 'Distinct roles', 'Common roles', 'Potential deviations']) await expect(kpis).toContainText(label)
  const analysis = await (await request.get(`/api/functional-groups/analysis/${id}`, { headers })).json()
  expect(await kpis.innerText()).toContain(String(analysis.eligible))
  const roles = dialog.getByRole('table', { name: 'Role frequency' })
  await expect(roles.getByText('Common', { exact: true }).first()).toBeVisible()
  await expect(roles.getByText('Uncommon', { exact: true }).first()).toBeVisible()
  await expect(roles).not.toContainText(/\b(common|uncommon|shared)\b/)                                    // lower-case enum values are never displayed
  // drilldown: the 5 compared users, split into Has role / Missing role
  const pay = roles.getByRole('row').filter({ hasText: 'ZC:FI:PAY' })
  await pay.getByRole('button', { name: /1 of 5 members hold ZC:FI:PAY/ }).click()
  const members = dialog.getByRole('group', { name: 'Members for ZC:FI:PAY' })
  await expect(members.getByRole('row')).toHaveCount(6)                                                     // header + the same 5 compared users
  await expect(members.getByRole('row').filter({ hasText: 'FG_E' })).toContainText('Has role')
  await expect(members.getByRole('row').filter({ hasText: 'FG_A' })).toContainText('Missing role')
  await members.getByLabel('Search members for ZC:FI:PAY').fill('FG_E')
  await expect(members.getByRole('row')).toHaveCount(2)
  // KPI filters and reset
  await kpis.getByRole('button', { name: /^Common roles/ }).click()
  await expect(roles.getByRole('row').filter({ hasText: 'ZC:FI:PAY' })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Reset filters' })).toBeVisible()
  await dialog.getByRole('button', { name: 'Reset filters' }).click()
  await expect(roles.getByRole('row').filter({ hasText: 'ZC:FI:PAY' })).toHaveCount(1)
  await kpis.getByRole('button', { name: /^Compared/ }).click()
  await expect(dialog.getByRole('table', { name: 'Members included in the analysis' }).getByRole('row')).toHaveCount(6)
  await kpis.getByRole('button', { name: /^Members/ }).click()
  await expect(page.getByRole('dialog', { name: `Members of ${name}` })).toBeVisible()                       // Members opens the member list
  await expect(page.getByRole('dialog', { name: `Members of ${name}` }).getByRole('button', { name: 'Close', exact: true })).toHaveCount(0)                                   // no redundant footer Close
})

test('suggestion rule: contains matching, View Matches, select all, and assignment adds without replacing', async ({ page, request }) => {
  const name = `Sourcing ${unique}`, existing = `Existing ${unique}`
  const id = await group(request, name), existingId = await group(request, existing)
  await join(request, 'FG_C', existingId)
  await join(request, 'FG_A', id)                                                                              // already a member of the suggested group
  const section = await groupsSection(page, name)
  await section.getByRole('button', { name: 'New rule' }).click()
  const form = page.getByRole('dialog', { name: 'New suggestion rule' })
  await form.getByLabel('Directory Department contains').fill('supply chain')                                  // substring, case-insensitive: A, B and C
  await form.getByLabel('Suggested Functional Group').selectOption({ label: name })
  await form.getByRole('button', { name: 'Create rule' }).click()
  const rules = section.getByRole('table', { name: 'Functional Group suggestion rules' })
  const rule = rules.getByRole('row').filter({ hasText: name })
  await expect(rule.getByRole('button', { name: /View 3 users matching the rule/ })).toBeVisible()
  await rule.getByRole('button', { name: `View matches for the rule suggesting ${name}` }).click()
  const dialog = page.getByRole('dialog', { name: `Users matching · ${name}` })
  const table = dialog.getByRole('table', { name: 'Users matching the rule' })
  await expect(table.getByRole('row')).toHaveCount(4)
  await expect(table.getByRole('row').filter({ hasText: 'FG_A' })).toContainText('Already a member')
  await expect(table.getByRole('row').filter({ hasText: 'FG_C' })).toContainText(existing)                       // other memberships are shown, never replaced
  await expect(table.getByRole('row').filter({ hasText: 'FG_A' }).getByRole('checkbox')).toBeDisabled()
  await dialog.getByRole('searchbox', { name: 'Search matching users' }).fill('FG_B'); await expect(table.getByRole('row')).toHaveCount(2); await dialog.getByRole('searchbox', { name: 'Search matching users' }).fill('')
  await dialog.getByRole('button', { name: 'Select all not yet in the group' }).click()
  await expect(dialog).toContainText('2 selected')
  await dialog.getByRole('button', { name: 'Clear selection' }).click()
  await expect(dialog).not.toContainText('selected')
  await dialog.getByRole('button', { name: 'Select all not yet in the group' }).click()
  await dialog.getByRole('button', { name: new RegExp(`^Add ${name} to 2 selected`) }).click()
  const assign = page.getByRole('dialog', { name: 'Assign Functional Groups' })
  await expectReviewerProfile(assign.getByLabel('Reviewer'))
  await assign.getByRole('checkbox').check()
  await assign.getByRole('button', { name: 'Assign groups' }).click()
  await expect(assign).toContainText('2 users updated')
  const c = (await (await request.get('/api/functional-groups/users/FG_C', { headers })).json()).classification
  expect(c.group_ids.sort()).toEqual([id, existingId].sort())                                                   // added, not replaced
  const history = (await (await request.get('/api/functional-groups/users/FG_B', { headers })).json()).history.items
  expect(history[0].event).toBe('assigned')
})
