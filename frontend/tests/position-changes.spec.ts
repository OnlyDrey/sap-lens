import { test, expect, type APIRequestContext } from '@playwright/test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers, goTo } from './support'
const columns = 'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'
const employees = (department: string, title: string, manager = 'Demo Manager') =>
  '﻿' + columns + '\n' +
  `North;Demo Mover;demo_mover;;mover@example.test;${department};${title};true;;;${manager};demo_manager;manager@example.test;Operations;Lead;Resolved\n` +
  'North;Demo Stayer;demo_stayer;;stayer@example.test;Finance;Accountant;true;;;;;;;;\n'
let directory: string, csv: string

const settings = async (request: APIRequestContext) => (await (await request.get('/api/configuration', { headers })).json()).settings
async function importDirectory(request: APIRequestContext) {
  const revision = (await settings(request)).revision
  const preview = await request.post('/api/employees/preview', { headers, data: { path: csv, revision } })
  expect(preview.ok()).toBeTruthy()
  expect((await request.post('/api/employees/import', { headers, data: { path: csv, revision, digest: (await preview.json()).digest } })).ok()).toBeTruthy()
}
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-position-'))
  csv = path.join(directory, 'employees.csv')
  const users = path.join(directory, 'users.csv')
  writeFileSync(users, 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\n' +
    'DEMO_MOVER,ZC:FI:VIEW,mover@example.test,DEMO,20200101,99991231,20200101,99991231\nDEMO_STAYER,ZC:FI:VIEW,stayer@example.test,DEMO,20200101,99991231,20200101,99991231\n')
  const current = await settings(request)
  current.data_csv_path = path.resolve('tests/fixtures/synthetic.csv'); current.user_csv_path = users
  current.features.employee_directory = true
  expect((await request.post('/api/configuration', { headers, data: current })).ok()).toBeTruthy()
  writeFileSync(csv, employees('Finance', 'Accountant'))
  await importDirectory(request)
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})
test('manager-only and formatting-only directory changes are not position changes', async ({ page, request }) => {
  writeFileSync(csv, employees(' finance ', 'ACCOUNTANT', 'Another Manager'))
  await importDirectory(request)
  await page.goto('/#session=browser-test-session')
  const tile = page.getByRole('region', { name: 'Directory & Data Health', exact: true }).getByRole('button', { name: 'Position changes', exact: true })
  await expect(tile).toContainText('0')
})

test('a department change becomes a priority review that uses the existing Account Review decision', async ({ page, request }) => {
  writeFileSync(csv, employees('Procurement', 'Accountant'))
  await importDirectory(request)
  await page.goto('/#session=browser-test-session')
  const tile = page.getByRole('region', { name: 'Directory & Data Health', exact: true }).getByRole('button', { name: 'Position changes', exact: true })
  await expect(tile).toContainText('1')
  await tile.click()
  await expect(page).toHaveURL(/#\/user-access\/account-review/)
  await expect(page.getByRole('button', { name: 'Remove review finding Position changes', exact: true })).toBeVisible()
  const queue = page.getByRole('region', { name: 'Position changes priority queue' })
  await expect(queue).toContainText('not evidence that access is inappropriate')
  const row = queue.getByRole('row').filter({ hasText: 'DEMO_MOVER' })
  // Last-known and current values are separate columns; the detection time is the first detection, not the date of the change.
  await expect(queue.getByRole('columnheader', { name: 'Previous position', exact: true })).toBeVisible()
  await expect(queue.getByRole('columnheader', { name: 'Current position', exact: true })).toBeVisible()
  await expect(queue.getByRole('columnheader', { name: 'Status', exact: true })).toHaveCount(0) // the redundant Status column is gone
  // Department and job title are stacked and labelled in each position cell; unchanged values stay muted, changed ones are emphasized.
  const [previous, current] = [row.getByRole('cell').nth(2), row.getByRole('cell').nth(3)]
  await expect(previous).toContainText('Department'); await expect(previous).toContainText('Job title')
  await expect(previous).toContainText('Finance'); await expect(current).toContainText('Procurement')
  await expect(current.locator('.position-line[data-changed]')).toHaveCount(1) // only the department changed
  await expect(row).toContainText('High')
  await expect(row.getByRole('button', { name: 'Review position change for DEMO_MOVER' }).locator('svg')).toHaveCount(1) // Review carries an icon
  await expect(queue.getByRole('row').filter({ hasText: 'DEMO_STAYER' })).toHaveCount(0)
  await expect(row.getByRole('link', { name: 'Open SAP user DEMO_MOVER' })).toHaveAttribute('href', '#/user-access/user/DEMO_MOVER')
  await row.getByRole('button', { name: 'Review position change for DEMO_MOVER' }).click()
  const dialog = page.getByRole('dialog', { name: 'Review account · DEMO_MOVER' })
  // The dialog is limited to SAP identity, organizational position changes and the review decision; findings stay under Investigate SAP user.
  for (const name of ['SAP identity', 'Review decision']) await expect(dialog.getByRole('region', { name, exact: true })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'Organizational position changes' })).toBeVisible()
  await expect(dialog.getByText('Current findings and evidence')).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: /Investigate SAP user/ })).toBeVisible()
  await dialog.getByLabel('Reviewer', { exact: true }).fill('Synthetic Reviewer')
  await dialog.getByLabel('Rationale', { exact: true }).fill('Move confirmed with the line manager.')
  await dialog.getByLabel('Decision', { exact: true }).selectOption('No action required')
  await dialog.getByRole('button', { name: /Save/ }).click()
  await expect(dialog).toHaveCount(0)
  await expect(queue).toHaveCount(0)
  await goTo(page, 'Dashboard')
  await expect(page.getByRole('region', { name: 'Directory & Data Health', exact: true }).getByRole('button', { name: 'Position changes', exact: true })).toContainText('0')
})
