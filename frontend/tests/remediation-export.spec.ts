import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { cleanup, headers, names, openSod, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => {
  directory = await seedGovernance(request)
  // Remediation lists reviewed activities only: approve every activity of the two seeded users.
  const decide = async (user: string) => {
    const subject = await (await request.get('/api/sod/subject', { headers, params: { user } })).json()
    for (const activity of subject.activities) {
      const view = await (await request.get('/api/sod/matrix/risk', { headers })).json()
      const found = (await (await request.get('/api/sod/subject', { headers, params: { user } })).json()).activities.find((row: { activity: string }) => row.activity === activity.activity)
      const response = await request.post('/api/sod/decisions/activity', { headers, data: { context: 'current', expected_revision: view.revision, expected_generation: view.generation, items: [{ key: found.key, user, ref: activity.activity, evidence_version: found.evidence_version }], decision: 'Approved', reviewer: 'Synthetic Reviewer', justification: 'Synthetic business need' } })
      expect(response.ok()).toBeTruthy()
    }
  }
  await decide(names.a); await decide(names.b)
})
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

async function openRemediation(page: Page) {
  await openSod(page, 'Reviews')
  await page.getByRole('tab', { name: 'Remediation', exact: true }).click()
  await expect(page.getByRole('table', { name: 'Access remediation rows' })).toBeVisible()
}
const parse = (path: string) => readFileSync(path, 'utf8').replace(/^\uFEFF/, '').split('\r\n').filter(Boolean).map((line) => line.split(';').map((cell) => cell.replace(/^"|"$/g, '').replace(/""/g, '"')))

test('Export CSV is a dropdown with two formats, keyboard operable, and closes after a choice', { tag: '@a11y' }, async ({ page }) => {
  await openRemediation(page)
  const trigger = page.getByRole('button', { name: 'Export CSV', exact: true })
  await expect(trigger).toHaveAttribute('aria-haspopup', 'dialog'); await expect(trigger).toHaveAttribute('aria-expanded', 'false')
  await trigger.focus(); await page.keyboard.press('Enter')
  const menu = page.getByRole('group', { name: 'Export CSV formats', exact: true })
  await expect(menu).toBeVisible(); await expect(trigger).toHaveAttribute('aria-expanded', 'true')
  const items = menu.getByRole('button')
  await expect(items).toHaveCount(2)
  await expect(items.nth(0)).toContainText('Role Assignments'); await expect(items.nth(0)).toContainText('One row per unique SAP user and assigned role.')
  await expect(items.nth(1)).toContainText('Detailed Remediation'); await expect(items.nth(1)).toContainText('Full remediation details, including existing risk, activity and tracking information.')
  await expect(items.nth(0)).toBeFocused()                                  // the first option receives focus
  await page.keyboard.press('ArrowDown'); await expect(items.nth(1)).toBeFocused()
  await page.keyboard.press('ArrowUp'); await expect(items.nth(0)).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0); await expect(trigger).toBeFocused()   // Escape closes and returns focus
  await trigger.click()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /^Role Assignments/ }).click()
  await download
  await expect(menu).toHaveCount(0)                                         // closes after selecting an export
})

test('Role Assignments exports one unique row per user and role while Detailed keeps its columns and repeats assignments', async ({ page }) => {
  await openRemediation(page)
  const trigger = page.getByRole('button', { name: 'Export CSV', exact: true })
  await trigger.click()
  const simple = page.waitForEvent('download')
  await page.getByRole('button', { name: /^Role Assignments/ }).click()
  const simpleDownload = await simple
  expect(simpleDownload.suggestedFilename()).toMatch(/^sap-lens-sod-role-assignments-\d{4}-\d{2}-\d{2}\.csv$/)
  const rows = parse((await simpleDownload.path())!)
  expect(rows[0]).toEqual(['USERNAME', 'ROLE', 'SAP User Group', 'Decision Status'])
  const pairs = rows.slice(1).map((row) => `${row[0]}\u0000${row[1]}`)
  expect(pairs.length).toBeGreaterThan(0); expect(new Set(pairs).size).toBe(pairs.length)
  expect(rows.slice(1).filter((row) => row[0] === names.b && row[1] === 'ROLE_AB')).toHaveLength(1)   // one role, two activities, one row
  await trigger.click()
  const full = page.waitForEvent('download')
  await page.getByRole('button', { name: /^Detailed Remediation/ }).click()
  const fullDownload = await full
  expect(fullDownload.suggestedFilename()).toMatch(/^sap-lens-sod-access-remediation-\d{4}-\d{2}-\d{2}\.csv$/)
  const detailed = parse((await fullDownload.path())!)
  expect(detailed[0].slice(0, 5)).toEqual(['USERNAME', 'USER_GROUP', 'ACTIVITY', 'RISKS', 'ROLE'])
  expect(detailed.slice(1).filter((row) => row[0] === names.b && row[4] === 'ROLE_AB').length).toBeGreaterThan(1) // evidence export keeps activity rows
})
