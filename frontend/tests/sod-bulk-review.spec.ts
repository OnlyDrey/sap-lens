import { test, expect, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { enableSod, headers } from './sod-fixture'

/** Suffix CDK, EMS, ES2, ENO, ESH and ENP are all catalogue roles of the same two families, so a pattern-level filter would mix them. */
const SUFFIXES = ['CDK', 'EMS', 'ES2', 'ENO', 'ESH', 'ENP']
const catalogue = 'AGR_NAME,TEXT,CHILD_AGR,TCODE\n' + SUFFIXES.flatMap((suffix) => [[`ZC:MM:BUY:${suffix}`, 'X1'], [`ZC:MM:SEL:${suffix}`, 'X2']]).map(([role, code]) => `${role},Synthetic ${role},ZS:${role},${code}`).join('\n') + '\n'
const header = 'RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\n'
const matrix = header + 'R1,H,S,Synthetic R1,A,B,ACTVT1,A,X1,Synthetic\nR1,H,S,Synthetic R1,A,B,ACTVT2,B,X2,Synthetic\n'

let directory: string, tag = 0, user: Record<string, string> = {}, files: string[] = []
const assignments = () => [
  [user.a, 'BUY:CDK'], [user.a, 'SEL:CDK'], [user.a, 'BUY:EMS'],
  [user.b, 'BUY:ES2'], [user.b, 'SEL:ENO'],
  [user.c, 'BUY:ESH'], [user.c, 'SEL:ENP'], [user.c, 'BUY:ENP'],
  [user.d, 'BUY:CDK'], [user.d, 'SEL:ES2'],
  [user.e, 'BUY:ENP'], [user.e, 'SEL:ENP'], [user.f, 'BUY:ENP'], [user.f, 'SEL:ENP'],
].map(([name, role]) => `${name},ZC:MM:${role},GRP,20000101,99991231`).join('\n')

test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  const unique = `${process.pid}${++tag}`
  user = Object.fromEntries(['a', 'b', 'c', 'd', 'e', 'f'].map((key) => [key, `BULK_${key.toUpperCase()}${unique}`]))
  directory = mkdtempSync(path.join(tmpdir(), 'sod-bulk-ui-'))
  files = []
  for (const [source, content] of Object.entries({ roles: catalogue, users: 'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n' + assignments() + '\n', sod: matrix })) {
    const file = path.join(directory, `${source}.csv`)
    writeFileSync(file, content)
    files.push(file)
    const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
    expect((await request.post(`/api/data-sources/${source}/select`, { headers, data: { path: file, revision: settings.revision, mode: 'static' } })).ok()).toBeTruthy()
  }
  await enableSod(request)
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

async function openAssignments(page: Page, width = 1440) {
  await page.setViewportSize({ width, height: 1000 })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'SoD', exact: true }).click()
  await page.getByRole('link', { name: 'Access Explorer', exact: true }).click()
  await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
  await expect(page.getByRole('table', { name: 'Access list' })).toBeVisible()
}
const table = (page: Page) => page.getByRole('table', { name: 'Access list' })
const roles = async (page: Page) => (await table(page).locator('tbody tr .role-identifier code').allInnerTexts()).map((text) => text.replace(/\s+/g, '')).sort()
const pick = async (page: Page, label: string, option: string) => {
  const box = page.getByRole('combobox', { name: label, exact: true })
  await box.click(); await box.fill(option)
  await page.getByRole('option', { name: option, exact: true }).click()
  await box.fill('') // the search text stays after a toggle; clear it so the next option is listed
}
const toolbar = (page: Page) => page.getByRole('toolbar', { name: 'Bulk assignment review' })
const sourceHashes = () => files.map((file) => createHash('sha256').update(readFileSync(file)).digest('hex'))

test('role suffix filtering matches the exact actual role suffix and multi-selects combine with OR', async ({ page }) => {
  await openAssignments(page)
  await expect.poll(() => roles(page)).toHaveLength(14)
  await pick(page, 'Role suffix', 'CDK')
  await expect.poll(() => roles(page)).toEqual(['ZC:MM:BUY:CDK', 'ZC:MM:BUY:CDK', 'ZC:MM:SEL:CDK'])
  for (const other of ['EMS', 'ES2', 'ENO', 'ESH', 'ENP']) expect((await roles(page)).filter((role) => role.endsWith(`:${other}`))).toEqual([])
  // The list stays open: a second suffix is added without reopening it, and the AND with a username narrows both.
  await expect(page.getByRole('listbox', { name: 'Role suffix options' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Role suffix', exact: true }).fill('')
  await page.getByRole('option', { name: 'EMS', exact: true }).click()
  await expect(page.getByRole('listbox', { name: 'Role suffix options' })).toBeVisible()
  await expect.poll(() => roles(page)).toEqual(['ZC:MM:BUY:CDK', 'ZC:MM:BUY:CDK', 'ZC:MM:BUY:EMS', 'ZC:MM:SEL:CDK'])
  await page.keyboard.press('Escape')
  await expect(page.getByRole('listbox', { name: 'Role suffix options' })).toHaveCount(0)
  await pick(page, 'SAP username', user.a)
  await expect.poll(() => roles(page)).toEqual(['ZC:MM:BUY:CDK', 'ZC:MM:BUY:EMS', 'ZC:MM:SEL:CDK'])
  await expect(page.getByRole('status').filter({ hasText: /^1.*of 3|^1–3 of 3/ })).toHaveCount(0)
})

test('multi-select dropdowns stay open, search without losing selections and offer Select all with its scope and Clear selection', async ({ page }) => {
  await openAssignments(page)
  const box = page.getByRole('combobox', { name: 'Role suffix', exact: true })
  await box.click()
  const list = page.getByRole('listbox', { name: 'Role suffix options' })
  await expect(list.getByRole('option')).toHaveCount(6)
  await page.getByRole('option', { name: 'ENO', exact: true }).click()
  await page.getByRole('option', { name: 'ESH', exact: true }).click()
  await expect(list).toBeVisible() // toggling never closes the list
  await expect(page.getByRole('option', { name: 'ENO', exact: true })).toHaveAttribute('aria-selected', 'true')
  await box.fill('E')
  await box.fill('CD')
  await expect(list.getByRole('option')).toHaveText(['CDK'])
  await expect(page.getByRole('group', { name: 'Selected Role suffix' })).toContainText('ENO')
  await expect(page.getByRole('group', { name: 'Selected Role suffix' })).toContainText('ESH') // selections survive searching
  await expect(page.getByText(/1 value matching “CD”/)).toBeVisible()
  await page.getByRole('button', { name: /^Select all 1 matching “CD” Role suffix values$/ }).click()
  await expect(page.getByRole('group', { name: 'Selected Role suffix' })).toContainText('CDK')
  await page.getByRole('button', { name: 'Clear selection', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Selected Role suffix' })).toHaveCount(0)
  await box.fill('')
  await page.getByRole('button', { name: /^Select all 6 listed Role suffix values$/ }).click()
  await expect(page.getByRole('group', { name: 'Selected Role suffix' }).getByRole('button', { name: /^Remove Role suffix/ })).toHaveCount(6)
  await page.getByRole('button', { name: 'Close Role suffix options' }).first().click()
  await expect(list).toHaveCount(0)
  // Outside click closes, Escape closes, and a single chip can be removed.
  await box.click(); await expect(list).toBeVisible()
  await page.getByRole('heading', { name: /Access list|rows/ }).first().click({ force: true }).catch(() => undefined)
  await page.mouse.click(5, 5)
  await expect(list).toHaveCount(0)
  await page.getByRole('button', { name: 'Remove Role suffix CDK', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Selected Role suffix' }).getByRole('button', { name: /^Remove Role suffix/ })).toHaveCount(5)
  await page.getByRole('button', { name: 'Clear all Role suffix selections', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Selected Role suffix' })).toHaveCount(0)
})

test('multiple SAP usernames combine with OR and the options follow the other active filters', async ({ page }) => {
  await openAssignments(page)
  await pick(page, 'SAP username', user.a)
  await pick(page, 'SAP username', user.b)
  await expect.poll(async () => (await table(page).locator('tbody tr').count())).toBe(5)
  await page.keyboard.press('Escape')
  await pick(page, 'Role suffix', 'CDK')
  await expect.poll(() => roles(page)).toEqual(['ZC:MM:BUY:CDK', 'ZC:MM:SEL:CDK'])
  // Suffix options narrow to the selected users, so Select all acts on the available values only.
  await page.getByRole('combobox', { name: 'Role suffix', exact: true }).click()
  await page.getByRole('button', { name: /^Clear selection$/ }).click()
  const options = page.getByRole('listbox', { name: 'Role suffix options' }).getByRole('option')
  await expect(options).toHaveText(['CDK', 'EMS', 'ENO', 'ES2'])
  await expect(page.getByText(/within the other active filters/)).toBeVisible()
})

test('select all visible and select all matching across pages use stable identifiers and survive paging', async ({ page }) => {
  await openAssignments(page)
  await page.getByRole('combobox', { name: 'Explorer pages: rows per page' }).selectOption('10')
  await expect(page.getByRole('status').filter({ hasText: '1–10 of 14' })).toBeVisible()
  await page.getByRole('checkbox', { name: 'Select all assignments on this page' }).check()
  await expect(toolbar(page)).toContainText('10 assignments selected')
  await expect(toolbar(page)).toContainText('10 on this page')
  await expect(toolbar(page)).toContainText('14 match the current filters')
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(toolbar(page)).toContainText('10 assignments selected')
  await expect(toolbar(page)).toContainText('0 on this page')
  await expect(toolbar(page)).toContainText('10 on other pages')
  await toolbar(page).getByRole('button', { name: /^Select all 14 matching$/ }).click()
  await expect(toolbar(page)).toContainText('14 assignments selected')
  await expect(page.getByRole('status').filter({ hasText: 'Selected all 14 matching assignments.' })).toBeVisible()
  await toolbar(page).getByRole('button', { name: 'Clear selection', exact: true }).click()
  await expect(toolbar(page)).toHaveCount(0)
  // A single row selects independently and the page checkbox reports a partial selection.
  await table(page).getByRole('checkbox', { name: /^Select assignment ZC:MM:/ }).first().check()
  await expect(toolbar(page)).toContainText('1 assignment selected')
  await expect(page.getByRole('checkbox', { name: 'Select all assignments on this page' })).toHaveJSProperty('indeterminate', true)
})

test('a selection is an explicit list: changing filters never adds assignments to it', async ({ page }) => {
  await openAssignments(page)
  await pick(page, 'Role suffix', 'CDK')
  await page.keyboard.press('Escape')
  await expect.poll(() => roles(page)).toHaveLength(3)
  await page.getByRole('checkbox', { name: 'Select all assignments on this page' }).check()
  await expect(toolbar(page)).toContainText('3 assignments selected')
  await page.getByRole('button', { name: 'Remove Role suffix CDK', exact: true }).click()
  await pick(page, 'Role suffix', 'EMS')
  await page.keyboard.press('Escape')
  await expect.poll(() => roles(page)).toEqual(['ZC:MM:BUY:EMS'])
  await expect(toolbar(page)).toContainText('3 assignments selected')
  await expect(toolbar(page)).toContainText('3 on other pages or outside the current filters')
  await expect(toolbar(page)).toContainText('1 match the current filters')
  await expect(table(page).getByRole('checkbox', { name: /^Select assignment ZC:MM:BUY:EMS/ })).not.toBeChecked()
})

test('batch Keep is confirmed with a summary, persists per assignment and keeps individual history', async ({ page }) => {
  const before = sourceHashes()
  await openAssignments(page)
  await pick(page, 'Role suffix', 'CDK')
  await page.keyboard.press('Escape')
  await expect.poll(() => roles(page)).toHaveLength(3)
  await page.getByRole('checkbox', { name: 'Select all assignments on this page' }).check()
  await toolbar(page).getByRole('button', { name: 'Keep', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Keep assignments' })
  await expect(dialog.getByRole('region', { name: 'Batch review summary' })).toContainText('Assignments affected3')
  await expect(dialog.getByRole('region', { name: 'Selected role suffixes' })).toContainText('CDK · 3')
  await expect(dialog.getByRole('region', { name: 'Selected SAP users' })).toContainText(user.a)
  const apply = dialog.getByRole('button', { name: 'Keep 3 assignments' })
  await expect(apply).toBeDisabled()
  await dialog.getByRole('textbox', { name: 'Reviewer' }).fill('Synthetic Reviewer')
  await dialog.getByRole('textbox', { name: 'Rationale' }).fill('Needed for synthetic purchasing')
  await apply.click()
  await expect(dialog.getByRole('status')).toContainText('3 of 3 assignments saved.')
  await dialog.getByRole('button', { name: 'Done' }).click()
  await expect(table(page).locator('tbody tr').filter({ hasText: 'Keep' })).toHaveCount(3)
  await expect(toolbar(page)).toHaveCount(0) // saved assignments leave the selection
  // Each assignment has its own history event.
  const response = await page.request.get('/api/sod/explorer/access_list', { headers, params: { role_suffix: 'CDK', limit: '50' } })
  const items = (await response.json()).items as { id: string; decision: string }[]
  expect(items.map((item) => item.decision)).toEqual(['Keep', 'Keep', 'Keep'])
  for (const item of items) {
    const history = (await (await page.request.get('/api/sod/decisions/assignment/history', { headers, params: { key: item.id, context: 'current' } })).json()).items
    expect(history).toHaveLength(1)
    expect(history[0]).toMatchObject({ decision: 'Keep', reviewer: 'Synthetic Reviewer', justification: 'Needed for synthetic purchasing' })
  }
  expect(sourceHashes()).toEqual(before) // imported SAP evidence is never modified
})

test('Recommend removal for suffix and users, existing decisions need explicit replacement and Investigate tracks actions', async ({ page }) => {
  await openAssignments(page)
  await pick(page, 'Role suffix', 'ENP')
  await pick(page, 'SAP username', user.e)
  await pick(page, 'SAP username', user.f)
  await page.keyboard.press('Escape')
  await expect.poll(() => roles(page)).toEqual(['ZC:MM:BUY:ENP', 'ZC:MM:BUY:ENP', 'ZC:MM:SEL:ENP', 'ZC:MM:SEL:ENP'])
  await page.getByRole('button', { name: /^Select all 4 matching$/ }).or(page.getByRole('button', { name: /select all 4 matching/i })).first().click()
  await toolbar(page).getByRole('button', { name: 'Recommend removal', exact: true }).click()
  let dialog = page.getByRole('dialog', { name: 'Recommend removal' })
  await expect(dialog).toContainText('no role is removed from SAP')
  await dialog.getByRole('textbox', { name: 'Reviewer' }).fill('Synthetic Reviewer')
  await dialog.getByRole('textbox', { name: 'Rationale' }).fill('Not needed after reorganization')
  await dialog.getByRole('button', { name: 'Recommend removal for 4 assignments' }).click()
  await expect(dialog.getByRole('status')).toContainText('4 of 4 assignments saved.')
  await dialog.getByRole('button', { name: 'Done' }).click()
  await expect(table(page).locator('tbody tr').filter({ hasText: 'Remove' })).toHaveCount(4)
  // The remediation view lists the same four assignments as recommended removals.
  const remediation = await (await page.request.get('/api/sod/remediation', { headers, params: { recommended: 'Remove assignment', limit: '50' } })).json()
  expect(remediation.items.filter((row: { user: string }) => [user.e, user.f].includes(row.user))).toHaveLength(4)
  // Keeping previously reviewed assignments needs an explicit replacement confirmation.
  await page.getByRole('button', { name: /select all 4 matching/i }).first().click()
  await toolbar(page).getByRole('button', { name: 'Keep', exact: true }).click()
  dialog = page.getByRole('dialog', { name: 'Keep assignments' })
  await dialog.getByRole('textbox', { name: 'Reviewer' }).fill('Synthetic Reviewer')
  await dialog.getByRole('textbox', { name: 'Rationale' }).fill('Reconsidered')
  const keep = dialog.getByRole('button', { name: 'Keep 4 assignments' })
  await expect(dialog.getByRole('region', { name: 'Existing decisions' })).toContainText('4 assignments have an earlier review decision')
  await expect(keep).toBeDisabled()
  await dialog.getByRole('checkbox', { name: /Replace the existing decisions of these 4 assignments/ }).check()
  await keep.click()
  await expect(dialog.getByRole('status')).toContainText('4 of 4 assignments saved.')
  await dialog.getByRole('button', { name: 'Done' }).click()
  const history = await (await page.request.get('/api/sod/explorer/access_list', { headers, params: { role_suffix: 'ENP', usernames: user.e, limit: '50' } })).json()
  const key = history.items[0].id as string
  const events = (await (await page.request.get('/api/sod/decisions/assignment/history', { headers, params: { key, context: 'current' } })).json()).items
  expect(events.map((event: { decision: string }) => event.decision)).toEqual(['Keep', 'Remove']) // earlier recommendation is retained
  // Investigate creates tracked remediation actions and leaves decisions alone.
  await page.getByRole('button', { name: /select all 4 matching/i }).first().click()
  await toolbar(page).getByRole('button', { name: 'Investigate', exact: true }).click()
  dialog = page.getByRole('dialog', { name: 'Mark for further investigation' })
  await dialog.getByRole('textbox', { name: 'Reviewer' }).fill('Synthetic Reviewer')
  await dialog.getByRole('textbox', { name: 'Rationale' }).fill('Check with the line manager')
  await dialog.getByRole('button', { name: 'Track investigation for 4 assignments' }).click()
  await expect(dialog.getByRole('status')).toContainText('4 of 4 assignments saved.')
  await dialog.getByRole('button', { name: 'Done' }).click()
  const tracked = await (await page.request.get('/api/sod/remediation', { headers, params: { limit: '50' } })).json()
  expect(tracked.actions.filter((action: { recommended: string }) => action.recommended === 'Investigate assignment')).toHaveLength(4)
})

test('partial failures are reported accurately and failed assignments stay selected', async ({ page }) => {
  await openAssignments(page)
  await pick(page, 'Role suffix', 'CDK')
  await page.keyboard.press('Escape')
  await expect.poll(() => roles(page)).toHaveLength(3)
  await page.getByRole('checkbox', { name: 'Select all assignments on this page' }).check()
  await page.route('**/api/sod/decisions/assignment/bulk', async (route) => {
    const body = route.request().postDataJSON() as { items: { key: string; user: string; ref: string }[] }
    const [ok, ...rest] = body.items
    await route.fulfill({ json: { action: 'Keep', recorded: [ok.key], skipped: [], failed: rest.map((item) => ({ key: item.key, user: item.user, ref: item.ref, reason: 'Evidence changed since the selection was made.' })), revision: 9 } })
  })
  await toolbar(page).getByRole('button', { name: 'Keep', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Keep assignments' })
  await dialog.getByRole('textbox', { name: 'Reviewer' }).fill('Synthetic Reviewer')
  await dialog.getByRole('textbox', { name: 'Rationale' }).fill('Partial result check')
  await dialog.getByRole('button', { name: 'Keep 3 assignments' }).click()
  await expect(dialog.getByRole('status')).toContainText('1 of 3 assignments saved; 0 skipped and 2 failed.')
  await expect(dialog.getByRole('alert')).toContainText('Evidence changed since the selection was made.')
  await dialog.getByRole('button', { name: 'Done' }).click()
  await expect(toolbar(page)).toContainText('2 assignments selected')
})

test('a rejected request never reports success', async ({ page }) => {
  await openAssignments(page)
  await pick(page, 'Role suffix', 'ENO')
  await page.keyboard.press('Escape')
  await page.getByRole('checkbox', { name: 'Select all assignments on this page' }).check()
  await page.route('**/api/sod/decisions/assignment/bulk', (route) => route.fulfill({ status: 409, json: { detail: 'SoD evidence changed. Reload before reviewing.' } }))
  await toolbar(page).getByRole('button', { name: 'Recommend removal', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Recommend removal' })
  await dialog.getByRole('textbox', { name: 'Reviewer' }).fill('Synthetic Reviewer')
  await dialog.getByRole('textbox', { name: 'Rationale' }).fill('Conflict check')
  await dialog.getByRole('button', { name: 'Recommend removal for 1 assignment' }).click()
  await expect(dialog.getByRole('alert')).toContainText('SoD evidence changed')
  await expect(dialog.getByRole('status')).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Done' })).toHaveCount(0)
})

test('CSV export follows the same suffix and username filters as the rows', async ({ page }) => {
  await openAssignments(page)
  await pick(page, 'Role suffix', 'CDK')
  await pick(page, 'Role suffix', 'EMS')
  await page.keyboard.press('Escape')
  await pick(page, 'SAP username', user.a)
  await page.keyboard.press('Escape')
  await expect.poll(() => roles(page)).toHaveLength(3)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /Export CSV/ }).first().click()
  const file = await download
  const lines = readFileSync((await file.path())!, 'utf8').replace('﻿', '').split(/\r?\n/).filter(Boolean)
  expect(lines).toHaveLength(4) // header and the same three assignments
  expect(lines.slice(1).join('\n')).not.toMatch(/:(ES2|ENO|ESH|ENP)/)
})

test('the bulk toolbar stays usable with the filter sidebar open at 800 px and wraps instead of scrolling at 375 px', async ({ page }) => {
  for (const width of [1280, 800, 375]) {
    await openAssignments(page, width)
    if (width < 1024) await page.getByRole('button', { name: /^Filters/ }).click().catch(() => undefined)
    if (width < 1024) await page.keyboard.press('Escape')
    await page.getByRole('checkbox', { name: 'Select all assignments on this page' }).check()
    await expect(toolbar(page)).toBeVisible()
    for (const name of ['Keep', 'Investigate', 'Recommend removal', 'Clear selection']) await expect(toolbar(page).getByRole('button', { name, exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  }
})
