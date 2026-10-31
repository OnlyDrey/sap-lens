import { test, expect, type Page } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { cleanup, enableSod, headers, openSod, seedGovernance } from './sod-fixture'
import { openSettings } from './support'

const HEAD = 'RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT'
const rowsFor = (extra: (risk: string, activity: string) => string[] = () => []) => {
  const lines: string[] = []
  for (const [risk, a, b, first, second] of [['R1', 'A', 'B', 'X1', 'X2'], ['R2', 'A', 'C', 'X1', 'X3']]) for (const [slot, activity, code] of [['ACTVT1', a, first], ['ACTVT2', b, second]]) lines.push([risk, 'H', 'S', `Synthetic ${risk}`, a, b, slot, activity, code, 'Synthetic', ...extra(risk, activity)].join(','))
  return lines
}
const plain = `${HEAD}\n${rowsFor().join('\n')}\n`
const extended = `${HEAD},RISK_NAME,RISK_DESCRIPTION,ACTIVITY_NAME,ACTIVITY_DESCRIPTION,RULESET_ID\n${rowsFor((risk, activity) => [risk === 'R1' ? 'Duplicate payments' : 'Unnamed approval', risk === 'R1' ? 'A user can post and approve the same payment' : '', activity === 'A' ? 'Create invoice' : '', activity === 'A' ? 'Creates a vendor invoice' : '', 'RS-SYN']).join('\n')}\n`
let directory = ''
test.setTimeout(120_000)
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const reseed = async (request: Parameters<typeof seedGovernance>[0], matrix: string) => { directory = await seedGovernance(request, 'static', matrix) }
const pill = (page: Page, kind: string, id: string) => page.getByRole('button', { name: new RegExp(`^${kind} ${id} `) }).first()
async function explorer(page: Page) { await openSod(page, 'Access Explorer'); await expect(page.getByRole('table', { name: 'User risk table' })).toBeVisible() }

test('pills show a concise description on hover and a detail popover with the origin of every value', async ({ page, request }) => {
  await reseed(request, extended)
  await explorer(page)
  const risk = pill(page, 'Risk', 'R1')
  await expect(risk.locator('xpath=ancestor::span[contains(@class,"sod-pill")][1]')).toHaveAttribute('title', 'Risk R1 — Duplicate payments: A user can post and approve the same payment')
  await risk.click()
  const dialog = page.getByRole('dialog', { name: 'Risk R1 details' })
  await expect(dialog).toContainText('Duplicate payments'); await expect(dialog).toContainText('A user can post and approve the same payment')
  await expect(dialog).toContainText('Imported from the SoD CSV'); await expect(dialog).toContainText('Source criticality')
  await page.keyboard.press('Escape'); await expect(dialog).toHaveCount(0)
  await pill(page, 'Activity', 'A').click()
  await expect(page.getByRole('dialog', { name: 'Activity A details' })).toContainText('Creates a vendor invoice')
})

test('a risk without any description says so neutrally and local business text fills the gap with its origin', async ({ page, request }) => {
  await reseed(request, extended)
  await explorer(page)
  await pill(page, 'Risk', 'R2').click()
  const dialog = page.getByRole('dialog', { name: 'Risk R2 details' })
  await expect(dialog).toContainText('No description available')
  await expect(dialog).toContainText('Unnamed approval') // the imported display name exists, the description does not
  await page.keyboard.press('Escape')
  const catalogue = await (await request.get('/api/sod/catalogue', { headers })).json(), r2 = catalogue.items.find((item: { risk_id: string }) => item.risk_id === 'R2')
  expect((await request.post('/api/sod/catalogue/R2', { headers, data: { expected_revision: catalogue.revision, definition_version: r2.definition_version, metadata: { ...r2.local, explanation_en: 'Local business description', display_name: 'Local name' } } })).ok()).toBeTruthy()
  await page.reload(); await expect(page.getByRole('table', { name: 'User risk table' })).toBeVisible()
  await pill(page, 'Risk', 'R2').click()
  const again = page.getByRole('dialog', { name: 'Risk R2 details' })
  await expect(again).toContainText('Local business description'); await expect(again).toContainText('Local business text')
  await expect(again).toContainText('Unnamed approval'); await expect(again).toContainText('differs: Local name') // both kept, origins identifiable
  // local annotations survive configuration resets by design, so leave none behind for the other tests
  const latest = await (await request.get('/api/sod/catalogue', { headers })).json(), current = latest.items.find((item: { risk_id: string }) => item.risk_id === 'R2')
  expect((await request.post('/api/sod/catalogue/R2', { headers, data: { expected_revision: latest.revision, definition_version: current.definition_version, metadata: { ...current.local, explanation_en: '', display_name: '' } } })).ok()).toBeTruthy()
})

test('an existing CSV without optional columns works and its pills carry only neutral wording', async ({ page, request }) => {
  await reseed(request, plain)
  await explorer(page)
  await expect(pill(page, 'Risk', 'R1').locator('xpath=ancestor::span[contains(@class,"sod-pill")][1]')).toHaveAttribute('title', 'Risk R1 — No description available')
  await pill(page, 'Risk', 'R1').click()
  await expect(page.getByRole('dialog', { name: 'Risk R1 details' })).toContainText('No description available')
})

test('pill details are keyboard operable, return focus and never nest interactive elements', async ({ page, request }) => {
  await reseed(request, extended)
  await explorer(page)
  const risk = pill(page, 'Risk', 'R1')
  await page.keyboard.press('Shift'); await risk.focus()
  expect(await risk.evaluate((element) => { const style = getComputedStyle(element); return [style.outlineStyle !== 'none', parseFloat(style.borderTopLeftRadius) > 0] })).toEqual([true, true]) // visible, rounded focus ring
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Risk R1 details' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(risk).toBeFocused()
  expect(await page.locator('button button, a button, button a').count()).toBe(0)
  // inside controls with their own action the pill is not a second control but keeps the tooltip
  await openSod(page, 'Risk Matrix')
  const header = page.locator('th.matrix-col').first()
  await expect(header.locator('button')).toHaveCount(1)
  await expect(header.locator('.id-pill')).toHaveAttribute('title', /Risk R1 — Duplicate payments/)
})

test('the SoD source diagnostics show metadata coverage over distinct entities and separate an absent column from missing values', async ({ page, request }) => {
  await reseed(request, extended)
  await openSettings(page, 'Data Sources')
  await page.getByRole('tab', { name: 'SoD Matrix', exact: true }).click()
  await page.getByRole('region', { name: 'SoD Matrix source management', exact: true }).getByRole('button', { name: 'Preview data', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'SoD Matrix source inspection' })
  const table = dialog.getByRole('table', { name: 'SoD metadata coverage' })
  const row = (label: string) => table.getByRole('row', { name: new RegExp(`^${label}`) })
  await expect(row('Risk display names')).toContainText('2 / 2'); await expect(row('Risk display names')).toContainText('100.0%')
  await expect(row('Risk descriptions')).toContainText('1 / 2'); await expect(row('Risk descriptions')).toContainText('Values missing') // column present, one value missing
  await expect(row('Activity descriptions')).toContainText('1 / 3') // three distinct activities however many rows repeat them
  await expect(row('Transaction descriptions')).toContainText('3 / 3')
  await expect(dialog.getByText('RULESET_ID', { exact: false }).first()).toBeVisible(); await expect(dialog).toContainText('RS-SYN')
  await expect(dialog).toContainText('Optional columns not in the CSV')
  await expect(dialog.getByRole('table', { name: 'Resolved metadata sample' })).toContainText('Duplicate payments')
})

test('an existing file shows absent optional columns as normal, and the candidate inspection reports the same coverage without importing', async ({ page, request }) => {
  await reseed(request, plain)
  await openSettings(page, 'Data Sources')
  await page.getByRole('tab', { name: 'SoD Matrix', exact: true }).click()
  await page.getByRole('region', { name: 'SoD Matrix source management', exact: true }).getByRole('button', { name: 'Preview data', exact: true }).click()
  const table = page.getByRole('dialog', { name: 'SoD Matrix source inspection' }).getByRole('table', { name: 'SoD metadata coverage' })
  await expect(table.getByRole('row', { name: /^Risk descriptions/ })).toContainText('Column not in CSV')
  await expect(page.getByRole('dialog', { name: 'SoD Matrix source inspection' })).not.toContainText('Validation failed')
  await page.getByRole('dialog', { name: 'SoD Matrix source inspection' }).getByRole('button', { name: 'Close', exact: true }).click()
  const next = `${directory}/candidate.csv`; writeFileSync(next, extended)
  await expect(page.getByRole('dialog', { name: 'SoD Matrix source inspection' })).toHaveCount(0)
  await page.getByText('Advanced import format and column mapping', { exact: true }).click()
  await page.getByRole('region', { name: 'SoD Matrix source management', exact: true }).getByRole('textbox', { name: 'SoD Matrix CSV location', exact: true }).fill(next)
  const editor = page.getByRole('region', { name: 'SoD Matrix CSV configuration', exact: true })
  const coverage = editor.getByRole('region', { name: 'Metadata coverage' })
  await expect(coverage.getByRole('table', { name: 'SoD metadata coverage' }).getByRole('row', { name: /^Risk descriptions/ })).toContainText('1 / 2')
  const active = await (await request.get('/api/data-sources/sod/inspection', { headers })).json()
  expect(active.descriptions.optional_columns.detected).toEqual([]) // the active data was not touched
  await enableSod(request)
})
