import { test, expect, type Page } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { cleanup, headers, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const SOURCES = [['Role Catalogue', 'roles'], ['User Access', 'users'], ['SoD Matrix', 'sod']] as const
const openSource = async (page: Page, label: string) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
  await page.getByRole('tab', { name: label, exact: true }).click()
  return page.getByRole('region', { name: `${label} source management`, exact: true })
}
const settings = async (request: import('@playwright/test').APIRequestContext) => (await (await request.get('/api/configuration', { headers })).json()).settings

test('Browse CSV is always available, with one label, even when a source is already configured', async ({ page }) => {
  for (const [label] of SOURCES) {
    const area = await openSource(page, label)
    await expect(area.getByRole('textbox').first()).not.toHaveValue('') // a file is configured
    const browse = area.getByRole('button', { name: 'Browse CSV', exact: true })
    await expect(browse).toBeEnabled()
  }
})

test('without native browsing Browse CSV opens the supported alternative with an explanation', async ({ page }) => {
  const area = await openSource(page, 'Role Catalogue')
  const field = area.getByRole('textbox', { name: 'CSV file location' })
  await area.getByRole('button', { name: 'Browse CSV', exact: true }).click()
  const upload = area.getByRole('region', { name: /browser upload/ })
  if (await upload.count()) await expect(upload).toBeVisible() // server mode: the upload chooser is the alternative
  else {
    await expect(area.getByRole('status').filter({ hasText: 'Native file browsing is only available in the desktop app' })).toBeVisible()
    await expect(field).toBeFocused()
  }
})

test.describe('with the desktop file dialog', () => {
  test.beforeEach(async ({ page }) => { await page.addInitScript(() => { (window as any).selectedCSV = ''; (window as any).pywebview = { api: { choose_csv: async () => (window as any).selectedCSV, desktop_runtime: async () => ({ windows: true, startup_supported: true, tray_available: false, warning: null }) } } }) })

  test('an invalid or empty replacement leaves the configured file and data untouched; a valid one is confirmed by name', async ({ page, request }) => {
    const area = await openSource(page, 'Role Catalogue')
    const field = area.getByRole('textbox', { name: 'CSV file location' })
    const before = await settings(request)
    const bad = path.join(directory, 'bad-replacement.csv'); writeFileSync(bad, 'NOT_A_ROLE_COLUMN\nx\n')
    const empty = path.join(directory, 'empty-replacement.csv'); writeFileSync(empty, 'AGR_NAME,TEXT,CHILD_AGR,TCODE\n')
    for (const file of [bad, empty]) {
      await page.evaluate((value) => { (window as any).selectedCSV = value }, file)
      await area.getByRole('button', { name: 'Browse CSV', exact: true }).click()
      await expect(area.getByRole('alert')).toContainText('No source data was replaced')
      await expect(area.getByRole('alert')).toContainText('The active file is unchanged')
      await expect(field).toHaveValue(file) // the attempted file stays visible for correction, the configured file stays active
      await expect(area.getByRole('button', { name: 'Browse CSV', exact: true })).toBeEnabled() // and the next attempt is possible immediately
    }
    const after = await settings(request)
    expect([after.data_csv_path, after.data_lifecycle.sources.roles?.snapshot, after.revision]).toEqual([before.data_csv_path, before.data_lifecycle.sources.roles?.snapshot, before.revision])
    const good = path.join(directory, 'good-replacement.csv'); writeFileSync(good, 'AGR_NAME,TEXT,CHILD_AGR,TCODE\nROLE_NEW,Synthetic ROLE_NEW,ZS:ROLE_NEW,X1\n')
    await page.evaluate((value) => { (window as any).selectedCSV = value }, good)
    await area.getByRole('button', { name: 'Browse CSV', exact: true }).click()
    await expect(area.getByRole('status').filter({ hasText: /Completed · 1 source records from good-replacement\.csv/ })).toBeVisible()
    await expect(field).toHaveValue(good)
    expect((await settings(request)).data_csv_path).toBe(good)
  })
})

test.describe('SoD Matrix replacement with the desktop file dialog', () => {
  test.beforeEach(async ({ page }) => { await page.addInitScript(() => { (window as any).selectedCSV = ''; (window as any).pywebview = { api: { choose_csv: async () => (window as any).selectedCSV, desktop_runtime: async () => ({ windows: true, startup_supported: true, tray_available: false, warning: null }) } } }) })
  const HEADER = 'RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\n'

  test('a failed SoD import keeps the last valid matrix and its inspection', async ({ page, request }) => {
    const area = await openSource(page, 'SoD Matrix')
    const before = await (await request.get('/api/data-sources/sod/inspection', { headers })).json()
    const bad = path.join(directory, 'sod-bad.csv'); writeFileSync(bad, 'RISK,TYPE\nR1,S\n')
    const empty = path.join(directory, 'sod-empty.csv'); writeFileSync(empty, HEADER)
    for (const file of [bad, empty]) {
      await page.evaluate((value) => { (window as any).selectedCSV = value }, file)
      await area.getByRole('button', { name: 'Browse CSV', exact: true }).click()
      await expect(area.getByRole('alert')).toContainText('No source data was replaced')
      await expect(area.getByRole('button', { name: 'Browse CSV', exact: true })).toBeEnabled()
    }
    const after = await (await request.get('/api/data-sources/sod/inspection', { headers })).json()
    expect(after.counts).toEqual(before.counts)
    expect(after.metadata.snapshot).toBe(before.metadata.snapshot)
    expect((await settings(request)).sod_csv_path).toBe(before.metadata.path)
  })

  test('validation warnings of a valid import are visible in the inspection', async ({ page }) => {
    const area = await openSource(page, 'SoD Matrix')
    const rows = [['R9', 'H', 'S', 'Synthetic', 'A', 'B', 'ACTVT1', 'A', 'X1', ''], ['R9', 'H', 'S', 'Synthetic', 'A', 'B', 'ACTVT2', 'B', 'X1', ''], ['R8', 'M', 'X', 'Other type', 'C', 'D', 'ACTVT1', 'C', 'X2', 'Described'], ['R8', 'M', 'X', 'Other type', 'C', 'D', 'ACTVT2', 'D', 'X3', 'Described']]
    const file = path.join(directory, 'sod-warnings.csv'); writeFileSync(file, HEADER + rows.map((row) => row.join(',')).join('\n') + '\n')
    await page.evaluate((value) => { (window as any).selectedCSV = value }, file)
    await area.getByRole('button', { name: 'Browse CSV', exact: true }).click()
    await expect(area.getByRole('status').filter({ hasText: /Completed · 4 source records from sod-warnings\.csv/ })).toBeVisible()
    await area.getByRole('button', { name: 'Preview data', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'SoD Matrix source inspection', exact: true })
    const checks = dialog.getByRole('region', { name: 'Validation results' })
    await expect(checks).toContainText('Warning')
    await expect(checks).toContainText('1 risks have a TYPE other than S')
    await expect(checks).toContainText('2 mappings have no TTEXT')
    await expect(checks).toContainText('share a transaction code between their two activity sides')
    await expect(dialog.getByText(/validation warnings?/)).toBeVisible() // the preview's own warning list
  })
})

test('the SoD Matrix source offers the same inspection as the other sources, read-only', async ({ page, request }) => {
  const area = await openSource(page, 'SoD Matrix')
  const before = await (await request.get('/api/data-sources/sod/inspection', { headers })).json()
  const beforeSettings = await settings(request)
  await area.getByRole('button', { name: 'Preview data', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'SoD Matrix source inspection', exact: true })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('Unique records')).toBeVisible()
  await expect(dialog.getByRole('region', { name: 'Validation results' })).toContainText('Passed')
  const columns = dialog.getByRole('table', { name: 'SoD Matrix columns' })
  await expect(columns.getByRole('row')).toHaveCount(11) // header + the ten documented columns
  await expect(columns).toContainText('ACTIVITY_SLOT'); await expect(columns).toContainText('Transaction description (optional')
  await expect(dialog.getByRole('region', { name: 'Import metadata' })).toContainText('Static')
  await expect(dialog.getByRole('region', { name: 'Import metadata' })).toContainText('Imported')
  await expect(dialog.getByRole('table', { name: 'Imported source records' })).toBeVisible()
  await expect(dialog.getByRole('combobox')).toHaveCount(0) // no column remapping controls
  await page.keyboard.press('Escape')
  const after = await (await request.get('/api/data-sources/sod/inspection', { headers })).json()
  expect(after.counts).toEqual(before.counts)
  expect((await settings(request)).revision).toBe(beforeSettings.revision)
  expect((await settings(request)).sod_csv_path).toBe(beforeSettings.sod_csv_path)
})
