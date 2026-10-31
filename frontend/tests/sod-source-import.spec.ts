import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers, openSettings } from './support'

const HEAD = 'RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT'
const GOOD = `${HEAD}\nSYN01,H,S,Synthetic incompatible activities,CREATE,APPROVE,ACTVT1,CREATE,X001,Synthetic creation\nSYN01,H,S,Synthetic incompatible activities,CREATE,APPROVE,ACTVT2,APPROVE,X002,Synthetic approval\nSYN02,M,X,Not evaluated type,CREATE,APPROVE,ACTVT1,CREATE,X003,\nSYN02,M,X,Not evaluated type,CREATE,APPROVE,ACTVT2,APPROVE,X004,\n`
let directory = '', good = ''
test.setTimeout(120_000)
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-sod-import-'))
  good = path.join(directory, 'matrix.csv'); writeFileSync(good, GOOD)
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  expect((await request.post('/api/data-sources/sod/select', { headers, data: { path: good, revision: settings.revision, mode: 'static' } })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }); rmSync(directory, { recursive: true, force: true }) })

async function open(page: Page) {
  await openSettings(page, 'Data Sources')
  await page.getByRole('tab', { name: 'SoD Matrix', exact: true }).click()
  await page.getByText('Advanced import format and column mapping', { exact: true }).click()
  return page.getByRole('region', { name: 'SoD Matrix CSV configuration', exact: true })
}
const active = async (request: any) => (await (await request.get('/api/data-sources/sod/inspection', { headers })).json())

test('the SoD source offers format, column mapping, validation and a preview of the selected file', async ({ page, request }) => {
  const before = await active(request)
  const editor = await open(page)
  await expect(editor.getByRole('heading', { name: 'CSV Import Format' })).toBeVisible()
  await expect(editor.getByLabel('Delimiter')).toHaveValue('auto'); await expect(editor.getByLabel('Encoding')).toHaveValue('auto')
  await expect(editor.getByRole('status').filter({ hasText: 'delimiter' })).toContainText('delimiter ","')
  await expect(editor.getByRole('heading', { name: 'Column mapping' })).toBeVisible()
  for (const column of ['RISK', 'CRITICITY', 'TYPE', 'TEXT', 'ACTVT1', 'ACTVT2', 'ACTIVITY_SLOT', 'ACTIVITY', 'TCODE', 'TTEXT']) await expect(editor.getByRole('combobox', { name: `SoD column ${column}`, exact: true })).toBeVisible()
  const status = editor.getByRole('table', { name: 'SoD column status' })
  await expect(status.getByRole('row', { name: /^TTEXT / })).toContainText('Optional')
  await expect(status.getByRole('row', { name: /^RISK / })).toContainText('Detected')
  const preview = editor.getByRole('region', { name: 'Import preview' })
  await expect(preview).toContainText('matrix.csv'); await expect(preview).toContainText('Preview validated')
  await expect(preview.locator('.preview-metrics')).toContainText('Parsed rows'); await expect(preview.locator('.preview-metrics')).toContainText('Not evaluated risks')
  await expect(preview.getByRole('table', { name: 'CSV preview records' })).toContainText('SYN01')
  const checks = editor.getByRole('region', { name: 'SoD validation results' })
  await expect(checks).toContainText('Evaluated risk types'); await expect(checks).toContainText('Transaction descriptions')
  // inspecting changed nothing
  const after = await active(request)
  expect([after.counts, after.metadata.snapshot, after.metadata.imported_at]).toEqual([before.counts, before.metadata.snapshot, before.metadata.imported_at])
})

test('a renamed header is mapped by hand, validates and is saved with the import; an invalid file never replaces the active data', async ({ page, request }) => {
  const renamed = path.join(directory, 'renamed.csv')
  writeFileSync(renamed, GOOD.replace('RISK,', 'Risk_ID;').replaceAll(',', ';').replace('Risk_ID;', 'Risk_ID;'))
  const before = await active(request)
  const editor = await open(page)
  const source = page.getByRole('region', { name: 'SoD Matrix source management', exact: true })
  await source.getByRole('textbox', { name: 'SoD Matrix CSV location', exact: true }).fill(renamed)
  await expect(editor.getByRole('alert').first()).toContainText(/RISK|header|column/i) // required RISK is missing
  await expect(editor.getByRole('region', { name: 'Import preview' })).toContainText('Validation failed')
  await editor.getByRole('combobox', { name: 'SoD column RISK', exact: true }).click()
  await page.getByRole('option', { name: 'Risk_ID', exact: true }).click()
  await expect(editor.getByRole('region', { name: 'Import preview' })).toContainText('Preview validated')
  await expect(editor.getByRole('table', { name: 'SoD column status' }).getByRole('row', { name: /^RISK / })).toContainText('Mapped')
  expect((await active(request)).metadata.snapshot).toBe(before.metadata.snapshot) // still read-only
  await source.getByRole('button', { name: 'Refresh source', exact: true }).click()
  await expect(source.getByText(/Completed · /)).toBeVisible()
  const saved = await active(request)
  expect(saved.metadata.path).toBe(renamed)
  expect(saved.metadata.format.mapping).toEqual({ RISK: 'Risk_ID' })
  expect(saved.counts.risks).toBe(2)
  // an invalid replacement keeps the last valid dataset and says so
  const broken = path.join(directory, 'broken.csv'); writeFileSync(broken, 'RISK,CRITICITY\nSYN01,H\n')
  await source.getByRole('textbox', { name: 'SoD Matrix CSV location', exact: true }).fill(broken)
  await expect(editor.getByRole('region', { name: 'Import preview' })).toContainText('Validation failed')
  await source.getByRole('button', { name: 'Refresh source', exact: true }).click()
  await expect(source.getByRole('alert')).toContainText('No source data was replaced')
  const kept = await active(request)
  expect([kept.metadata.snapshot, kept.counts.risks, kept.metadata.path]).toEqual([saved.metadata.snapshot, 2, renamed])
})

test('the existing source actions stay available next to the new section', async ({ page }) => {
  await open(page)
  const source = page.getByRole('region', { name: 'SoD Matrix source management', exact: true })
  for (const name of ['Browse CSV', 'Refresh source', 'Preview data', 'View changes', 'Technical source details', 'Clear source data']) await expect(source.getByRole('button', { name, exact: true }), name).toBeVisible()
  await expect(source.getByRole('button', { name: 'Browse CSV', exact: true })).toBeEnabled() // a configured source can still be replaced
  await expect(source.getByRole('button', { name: 'Refresh source', exact: true })).toBeEnabled()
  await source.getByRole('button', { name: 'Preview data', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'SoD Matrix source inspection', exact: true })).toContainText('Validation results')
})

for (const theme of ['light', 'dark']) for (const width of [375, 1280]) test(`the SoD import section keeps the page free of horizontal scrolling in ${theme} at ${width}px`, async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings; settings.theme = theme
  await request.post('/api/configuration', { headers, data: settings })
  await page.setViewportSize({ width, height: 900 })
  const editor = await open(page)
  const preview = editor.getByRole('region', { name: 'Import preview' })
  await expect(preview).toContainText('Preview validated')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  // a wide preview table scrolls inside its own container
  const region = preview.getByRole('region', { name: /Scrollable CSV preview records|CSV preview records/ }).first()
  if (await region.count()) expect(await region.evaluate((element) => getComputedStyle(element).overflowX)).toMatch(/auto|scroll/)
  if (process.env.SHOTS) { await editor.getByRole('heading', { name: 'Column mapping' }).scrollIntoViewIfNeeded(); await page.screenshot({ path: `${process.env.SHOTS}/sod-import-mapping-${theme}-${width}.png` }); await preview.scrollIntoViewIfNeeded(); await page.screenshot({ path: `${process.env.SHOTS}/sod-import-preview-${theme}-${width}.png` }) }
})
