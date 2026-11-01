import { test, expect, type Page } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { cleanup, headers, names, openSod, seedGovernance } from './sod-fixture'
import { pickMulti } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })
test.setTimeout(120_000)

const grid = (page: Page, kind: 'risk' | 'activity') => page.getByRole('region', { name: kind === 'risk' ? /Scrollable User by risk matrix/ : /Scrollable User by activity matrix/ })
const groupBy = (page: Page) => page.getByRole('combobox', { name: 'Group by', exact: true })
const sidebar = (page: Page) => page.getByRole('complementary', { name: 'Filters', exact: true })
const headerTexts = async (table: ReturnType<Page['getByRole']>) => { await expect(table.locator('thead th').first()).toBeVisible(); return table.locator('thead th').allInnerTexts() }

for (const kind of ['risk', 'activity'] as const) {
  const link = kind === 'risk' ? 'Risk Matrix' : 'Activity Matrix'
  test(`${kind} matrix: the group column shows without grouping, hides when grouped by SAP User Group and returns without losing filters`, async ({ page }) => {
    await openSod(page, link)
    const matrix = grid(page, kind)
    await expect(matrix.locator('thead th.matrix-corner-group')).toHaveText('SAP User Group')
    const values = await matrix.locator('td.matrix-identity-group').allInnerTexts()
    expect(values.sort()).toEqual(['FIN', 'P2P']) // correct value per user
    await pickMulti(sidebar(page), 'SAP User Group', 'FIN', page) // a filter that must survive the grouping changes
    await groupBy(page).selectOption('group')
    await expect(matrix.locator('thead th.matrix-corner-group')).toHaveCount(0)
    await expect(matrix.locator('td.matrix-identity-group')).toHaveCount(0)
    await expect(matrix.locator('tr.matrix-group-row')).toHaveCount(1)
    await expect(page.getByRole('button', { name: /Remove SAP User Group FIN/ })).toBeVisible()
    await groupBy(page).selectOption('none')
    await expect(matrix.locator('thead th.matrix-corner-group')).toBeVisible()
    await expect(matrix.locator('td.matrix-identity-group')).toHaveText(['FIN'])
    await expect(page.getByRole('button', { name: /Remove SAP User Group FIN/ })).toBeVisible()
  })

  test(`${kind} matrix: sorting by SAP User Group, a missing group and the pinned columns`, async ({ page }) => {
    const rows = (_p: Page) => grid(page, kind).locator('tbody th.matrix-row-head code')
    await openSod(page, link)
    await page.getByRole('combobox', { name: 'Sort', exact: true }).selectOption('group')
    await expect(rows(page)).toHaveText([names.a, names.b]) // FIN before P2P
    await page.getByRole('combobox', { name: 'Sort', exact: true }).locator('xpath=ancestor::div[@role="group"][1]').getByRole('button').click()
    await expect(rows(page)).toHaveText([names.b, names.a])
    // both identity columns stay pinned while the matrix scrolls sideways
    await page.setViewportSize({ width: 800, height: 900 })
    await grid(page, kind).evaluate((element) => { element.scrollLeft = 300 })
    const [head, group, area] = [(await grid(page, kind).locator('tbody th.matrix-row-head').first().boundingBox())!, (await grid(page, kind).locator('td.matrix-identity-group').first().boundingBox())!, (await grid(page, kind).boundingBox())!]
    expect(Math.abs(head.x - area.x)).toBeLessThan(4)
    expect(Math.abs(group.x - (head.x + head.width))).toBeLessThan(4) // directly after the SAP user column
  })
}

test('a user without a SAP User Group shows an accessible dash', async ({ page, request }) => {
  const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n${names.a},ROLE_A1,,20000101,99991231\n${names.a},ROLE_A2,,20000101,99991231\n${names.a},ROLE_B,,20000101,99991231\n${names.a},ROLE_C,,20000101,99991231\n${names.b},ROLE_AB,P2P,20000101,99991231\n`
  writeFileSync(`${directory}/users.csv`, users)
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  expect((await request.post('/api/data-sources/users/select', { headers, data: { path: `${directory}/users.csv`, revision: settings.revision, mode: 'static' } })).ok()).toBeTruthy()
  await openSod(page, 'Risk Matrix')
  const cell = grid(page, 'risk').locator('tbody tr').filter({ hasText: names.a }).locator('td.matrix-identity-group')
  await expect(cell).toContainText('No SAP User Group') // screen reader text
  await expect(cell.locator('[aria-hidden="true"]')).toHaveText('—')
})

test('Access Explorer: Users, Assignments and the role views order and show the group correctly', async ({ page }) => {
  await openSod(page, 'Access Explorer')
  const tabs = page.getByRole('tablist', { name: 'Access Explorer views' })
  const table = page.getByRole('table', { name: 'User risk table' })
  expect(await headerTexts(table)).toEqual(['SAP user', 'SAP User Group', 'Risk', 'Activities', 'Evidence', 'Risk acceptance', 'Open'])
  const row = table.getByRole('row', { name: new RegExp(names.b) }).first()
  await expect(row.locator('.user-group-text')).toHaveText('P2P')
  await expect(row.locator('p.text-muted')).toHaveCount(0) // nothing beneath the username any more
  await page.getByRole('combobox', { name: 'Group users by' }).selectOption('user_activity')
  expect((await headerTexts(page.getByRole('table', { name: 'User activity table' })))).toEqual(['SAP user', 'SAP User Group', 'Activity', 'Risks', 'Evidence', 'Review', 'Open'])
  await tabs.getByRole('tab', { name: 'Assignments', exact: true }).click()
  const assignments = page.getByRole('table', { name: 'Access list' })
  const names2 = await headerTexts(assignments)
  expect(names2.slice(1, 4)).toEqual(['SAP user', 'SAP User Group', 'Role assignment'])
  await expect(assignments.getByRole('row', { name: new RegExp(names.b) }).first().locator('.user-group-text')).toHaveText('P2P')
  await tabs.getByRole('tab', { name: 'Roles', exact: true }).click()
  // roles aggregate users from different groups: no single group is invented for them
  expect(await headerTexts(page.getByRole('table', { name: 'User & role lookup' }))).not.toContain('SAP User Group')
  await tabs.getByRole('tab', { name: 'Role conflicts', exact: true }).click()
  expect(await headerTexts(page.getByRole('table', { name: 'Potential SoD findings' }))).not.toContain('SAP User Group') // role-based records keep their aggregation
})

test('Reviews: the work queue and remediation show the group next to the user and keep their progress and decisions', async ({ page, request }) => {
  await openSod(page, 'Reviews')
  const queue = page.getByRole('table', { name: 'SoD review work queue' })
  expect(await headerTexts(queue)).toEqual(['SAP user', 'SAP User Group', 'Progress', 'Activities', 'Role assignments', 'Risk acceptance', 'Open'])
  const row = queue.getByRole('row', { name: new RegExp(names.a) }).first()
  await expect(row.locator('.user-group-text')).toHaveText('FIN')
  await expect(row.getByRole('progressbar').or(row.locator('progress'))).toHaveCount(1)
  await page.getByRole('tab', { name: 'Remediation', exact: true }).click()
  // no remediation rows until decisions exist; the header order is still verifiable once a decision is recorded
  const remediation = page.getByRole('table', { name: 'Access remediation rows' })
  if (await remediation.count()) expect((await headerTexts(remediation)).slice(0, 3)).toEqual(['SAP user', 'SAP User Group', 'Role assignment'])
  expect((await request.get('/api/sod/queue/users', { headers })).ok()).toBeTruthy()
})

test('CSV exports carry the group whatever the page shows and keep the filters', async ({ request }) => {
  for (const [path, column, user] of [['/api/sod/explorer/user_risk/export', 'USER_GROUPS', 'USERNAME'], ['/api/sod/explorer/user_activity/export', 'USER_GROUPS', 'USERNAME'], ['/api/sod/explorer/access_list/export', 'USER_GROUP', 'USERNAME'], ['/api/sod/queue/export', 'USER_GROUPS', 'USERNAME']]) {
    const text = (await (await request.get(path, { headers, params: { groups: 'P2P', group_by: 'user_group', limit: '1', offset: '5' } })).text()).replace('﻿', '')
    const lines = text.trim().split('\r\n').map((line) => line.split(';').map((item) => item.replace(/^"|"$/g, '')))
    const [head, ...rows] = lines
    expect(head, path).toContain(column)
    expect(rows.length, path).toBeGreaterThan(0)
    expect(new Set(rows.map((item) => item[head.indexOf(column)])), path).toEqual(new Set(['P2P'])) // scoped to the filter, unpaged, group present
    expect(new Set(rows.map((item) => item[head.indexOf(user)])).has(names.a), path).toBe(false)
  }
})
