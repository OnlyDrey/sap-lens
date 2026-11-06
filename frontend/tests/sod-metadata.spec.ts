import { test, expect, type Page } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
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

test('pills show concise descriptions without repeated provenance and retain full source details', async ({ page, request }) => {
  await reseed(request, extended)
  await explorer(page)
  const risk = pill(page, 'Risk', 'R1')
  await expect(risk.locator('xpath=ancestor::span[contains(@class,"sod-pill")][1]')).toHaveAttribute('title', 'Risk R1 — Duplicate payments: A user can post and approve the same payment')
  await risk.click()
  const dialog = page.getByRole('dialog', { name: 'Risk R1 details' })
  await expect(dialog).toContainText('Duplicate payments'); await expect(dialog).toContainText('A user can post and approve the same payment')
  await expect(dialog).not.toContainText('Imported from the SoD CSV'); await expect(dialog).not.toContainText('Source criticality')
  await expect(dialog.getByRole('button',{name:/^Activity A /})).toHaveCount(1) // exact active ID in the read-only description
  await expect(dialog.getByRole('button',{name:/^Activity user /})).toHaveCount(0)
  await page.keyboard.press('Escape'); await expect(dialog).toHaveCount(0)
  await pill(page, 'Activity', 'A').click()
  await expect(page.getByRole('dialog', { name: 'Activity A details' })).toContainText('Creates a vendor invoice')
})

test('a risk without any description says so neutrally and local business text fills the gap with its origin', async ({ page, request }) => {
  await reseed(request, extended)
  const initial=await(await request.get('/api/sod/catalogue',{headers,params:{search:'R2',limit:'100'}})).json(), initialRisk=initial.items.find((item:{risk_id:string})=>item.risk_id==='R2')
  expect((await request.post('/api/sod/catalogue/R2',{headers,data:{expected_revision:initial.revision,definition_version:initialRisk.definition_version,metadata:{...initialRisk.local,display_name:'',explanation_en:''}}})).ok()).toBeTruthy()
  await explorer(page)
  await pill(page, 'Risk', 'R2').click()
  const dialog = page.getByRole('dialog', { name: 'Risk R2 details' })
  await expect(dialog).toContainText('No description available')
  await expect(dialog).toContainText('Unnamed approval') // the imported display name exists, the description does not
  await page.keyboard.press('Escape')
  const catalogue = await (await request.get('/api/sod/catalogue', { headers, params: { search: 'R2', current: 'current', limit: '100' } })).json(), r2 = catalogue.items.find((item: { risk_id: string }) => item.risk_id === 'R2')  // the local catalogue keeps risks of earlier tests, so ask for this one
  expect((await request.post('/api/sod/catalogue/R2', { headers, data: { expected_revision: catalogue.revision, definition_version: r2.definition_version, metadata: { ...r2.local, explanation_en: 'Local business description', display_name: 'Local name' } } })).ok()).toBeTruthy()
  await page.reload(); await expect(page.getByRole('table', { name: 'User risk table' })).toBeVisible()
  await pill(page, 'Risk', 'R2').click()
  const again = page.getByRole('dialog', { name: 'Risk R2 details' })
  await expect(again).toContainText('Local business description'); await expect(again).not.toContainText('Local business text')
  await expect(again).toContainText('Local name'); await expect(again).not.toContainText('differs: Unnamed approval')
  await page.keyboard.press('Escape');await openSettings(page,'SoD Risk Configuration');await page.getByRole('searchbox',{name:'Search SoD risks',exact:true}).fill('R2');await page.getByRole('button',{name:'Edit SoD risk R2',exact:true}).click();await page.getByRole('button',{name:'Source details for risk R2',exact:true}).click();const source=page.getByRole('dialog',{name:'Source details for risk R2',exact:true});await expect(source).toContainText('differs: Unnamed approval');await expect(source).toContainText('Local business text')
  // local annotations survive configuration resets by design, so leave none behind for the other tests
  const latest = await (await request.get('/api/sod/catalogue', { headers, params: { search: 'R2', current: 'current', limit: '100' } })).json(), current = latest.items.find((item: { risk_id: string }) => item.risk_id === 'R2')
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


test('reference workbook upload enriches exact active IDs with provenance and coverage without activating unmatched definitions @repository-only', async ({ page, request }, testInfo) => {
  await reseed(request, plain)
  const workbook = (inactive = false) => execFileSync(process.env.PYTHON || 'python', ['-c',
    "import sys;sys.path[:0]=['backend','backend/tests'];from test_sod_reference import workbook;sys.stdout.buffer.write(workbook(risks=[('REF_UNUSED','Unused')] if sys.argv[1]=='yes' else [('R1','Curated risk'),('REF_UNUSED','Unused')],activities=[('REF_UNUSED_ACTIVITY','Unused')] if sys.argv[1]=='yes' else [('A','Curated activity')]))", inactive ? 'yes' : 'no'], { cwd: path.resolve('..'), env: { ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('SAP_LENS_') && key !== 'DATA_CSV_PATH')), SAP_LENS_CONFIG_DIR: path.join(directory, 'reference-generator'), DATA_CSV_PATH: '' } })
  try {
    await openSettings(page, 'SoD Risk Configuration')
    const library = page.getByRole('region', { name: 'SoD reference library' })
    await library.getByText('Advanced reference settings',{exact:true}).click()
    await expect(library.getByRole('button', { name: 'Import reference workbook' })).toBeEnabled()
    await library.getByLabel('SoD reference workbook').setInputFiles({ name: 'synthetic-reference.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: workbook() })
    await expect(library.getByRole('status')).toContainText('2 risks and 1 activities')
    const resolved = await (await request.get('/api/sod/metadata', { headers })).json()
    expect(resolved.risks.R1.name).toBe('Curated risk'); expect(resolved.risks.R1.origin.name).toBe('reference')
    expect(resolved.risks.REF_UNUSED).toBeUndefined()
    await library.getByLabel('SoD reference workbook').setInputFiles({ name: 'invalid.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('invalid workbook') })
    await expect(library.getByRole('alert')).toContainText('not a supported reference XLSX workbook')
    await explorer(page)
    await pill(page, 'Risk', 'R1').click()
    const details = page.getByRole('dialog', { name: 'Risk R1 details' })
    await expect(details).toContainText('Curated risk'); await expect(details).not.toContainText('Curated reference library')
    await expect(details).toContainText('Synthetic controls'); await expect(details).toContainText('Synthetic guidance')
    await page.keyboard.press('Escape')
    await openSettings(page, 'Data Sources')
    await page.getByRole('tab', { name: 'SoD Matrix', exact: true }).click()
    await page.getByRole('region', { name: 'SoD Matrix source management', exact: true }).getByRole('button', { name: 'Preview data', exact: true }).click()
    const inspection = page.getByRole('dialog', { name: 'SoD Matrix source inspection' })
    await expect(inspection).toContainText('1 active risks and 1 active activities matched')
    await expect(inspection).toContainText('REF_UNUSED')
    for (const [width, theme] of [[375, 'light'], [1280, 'dark']] as const) {
      await page.setViewportSize({ width, height: 900 })
      expect((await request.post('/api/configuration/theme', { headers, data: { theme } })).ok()).toBeTruthy()
      await page.reload()
      await openSettings(page, 'Data Sources')
      await page.getByRole('tab', { name: 'SoD Matrix', exact: true }).click()
      await page.getByRole('region', { name: 'SoD Matrix source management', exact: true }).getByRole('button', { name: 'Preview data', exact: true }).click()
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await expect(inspection).toBeVisible()
      await inspection.getByRole('region', { name: 'Metadata coverage', exact: true }).scrollIntoViewIfNeeded()
      expect(await inspection.getByLabel('Optional columns').locator('dd').evaluateAll(elements => elements.every(element => element.scrollWidth <= element.clientWidth))).toBeTruthy()
      await page.screenshot({ path: testInfo.outputPath(`reference-${width}-${theme}.png`), fullPage: true })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    }
  } finally {
    const current = await (await request.get('/api/sod/reference', { headers })).json()
    expect((await request.put('/api/sod/reference', { headers, data: { expected_revision: current.revision, workbook_base64: workbook(true).toString('base64') } })).ok()).toBeTruthy()
  }
})


test('risk and activity dialogs inherit reference fields without creating overrides and safely refresh unsaved drafts @repository-only', async ({page,request})=>{
  await reseed(request, plain.replaceAll('R1','F019').replaceAll(',A,',',AP01,'))
  const referenceFile=(name='Synthetic reference risk')=>execFileSync(process.env.PYTHON||'python',['-c',"import sys;sys.path[:0]=['backend','backend/tests'];from test_sod_reference import workbook;sys.stdout.buffer.write(workbook(risks=[('F019',sys.argv[1])],activities=[('AP01','Synthetic reference activity')]))",name],{cwd:path.resolve('..'),env:{...Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('SAP_LENS_')&&key!=='DATA_CSV_PATH')),SAP_LENS_CONFIG_DIR:path.join(directory,'effective-generator'),DATA_CSV_PATH:''}})
  try{
    await openSettings(page,'SoD Risk Configuration')
    const library=page.getByRole('region',{name:'SoD reference library'})
    await library.getByText('Advanced reference settings',{exact:true}).click()
    await expect(library.getByRole('button',{name:'Import reference workbook'})).toBeEnabled()
    await library.getByLabel('SoD reference workbook').setInputFiles({name:'synthetic-reference.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:referenceFile()})
    await expect(library.getByRole('status')).toContainText('Reference library saved')
    await expect(library.getByLabel('Reference matching summary')).toContainText('1 active risks matched · 1 active activities matched')
    await page.getByRole('searchbox',{name:'Search SoD risks',exact:true}).fill('F019') // earlier specs leave catalogue entries, so the risk may not be on the first page
    await page.getByRole('button',{name:'Edit SoD risk F019',exact:true}).click()
    const risk=page.getByRole('dialog',{name:'SoD risk F019',exact:true})
    await expect(risk.getByRole('textbox',{name:'Display name',exact:true})).toHaveValue('Synthetic reference risk')
    await expect(risk.getByRole('textbox',{name:'Business explanation',exact:true})).toHaveValue('Synthetic description')
    await expect(risk.getByRole('textbox',{name:'Risk consequence',exact:true})).toHaveValue('Synthetic impact')
    await expect(risk.getByRole('textbox',{name:'Mitigating controls',exact:true})).toHaveValue('Synthetic controls')
    const firstSave=page.waitForRequest(r=>r.method()==='POST'&&r.url().endsWith('/api/sod/catalogue/F019'))
    await risk.getByRole('button',{name:'Save changes',exact:true}).click()
    const unchanged=(await firstSave).postDataJSON().metadata
    expect(unchanged.display_name).toBe('');expect(unchanged.explanation_en).toBe('');expect(unchanged.mitigating_controls_en).toBe('')
    await expect(risk).toHaveCount(0)
    await page.getByRole('searchbox',{name:'Search SoD risks',exact:true}).fill('F019') // earlier specs leave catalogue entries, so the risk may not be on the first page
    await page.getByRole('button',{name:'Edit SoD risk F019',exact:true}).click()
    await risk.getByRole('textbox',{name:'Business area',exact:true}).fill('Unsaved synthetic override')
    const version=await(await request.get('/api/sod/reference',{headers})).json()
    expect((await request.put('/api/sod/reference',{headers,data:{expected_revision:version.revision,workbook_base64:referenceFile('Updated synthetic risk').toString('base64')}})).ok()).toBeTruthy()
    await page.evaluate(()=>window.dispatchEvent(new Event('visibilitychange')))
    await expect(risk.getByRole('textbox',{name:'Display name',exact:true})).toHaveValue('Updated synthetic risk')
    await expect(risk.getByRole('textbox',{name:'Business area',exact:true})).toHaveValue('Unsaved synthetic override')
    await risk.getByRole('button',{name:'Reset Business area to inherited value',exact:true}).click()
    await expect(risk.getByRole('textbox',{name:'Business area',exact:true})).toHaveValue('Synthetic area')
    await risk.getByRole('button',{name:'Save changes',exact:true}).click();await expect(risk).toHaveCount(0)
    const catalogue=await(await request.get('/api/sod/catalogue',{headers,params:{search:'F019',limit:'100'}})).json()
    const saved=catalogue.items.find((item:{risk_id:string})=>item.risk_id==='F019')
    expect(saved.local.display_name).toBe('');expect(saved.local.business_category).toBe('');expect(saved.description_review_status).toBe('Needs description review')
    await page.getByRole('tab',{name:'Activities',exact:true}).click()
    await page.getByRole('searchbox',{name:'Search SoD activities',exact:true}).fill('AP01')
    await page.getByRole('button',{name:'Edit SoD activity AP01',exact:true}).click()
    const activity=page.getByRole('dialog',{name:'SoD activity AP01',exact:true})
    await expect(activity.getByRole('textbox',{name:'Display name',exact:true})).toHaveValue('Synthetic reference activity')
    await expect(activity.getByRole('textbox',{name:'Business explanation',exact:true})).toHaveValue('Synthetic description')
    await expect(activity.getByRole('textbox',{name:'Review guidance',exact:true})).toHaveValue('Synthetic guidance')
    await expect(activity.getByRole('textbox',{name:'Local notes',exact:true})).toHaveValue('')
    await activity.getByRole('button',{name:'Save changes',exact:true}).click();await expect(activity).toHaveCount(0)
    const stored=await(await request.get('/api/sod/catalogue-activities',{headers,params:{search:'AP01',limit:'100'}})).json()
    expect(stored.items.find((item:{activity:string})=>item.activity==='AP01').local.explanation_en).toBe('')
    const latest=await(await request.get('/api/sod/catalogue',{headers,params:{search:'F019',limit:'100'}})).json()
    const currentRisk=latest.items.find((item:{risk_id:string})=>item.risk_id==='F019')
    expect((await request.post('/api/sod/catalogue/F019',{headers,data:{expected_revision:latest.revision,definition_version:currentRisk.definition_version,metadata:{...currentRisk.local,display_name:'Preserved explicit override'}}})).ok()).toBeTruthy()
    await library.getByRole('button',{name:'Reset defaults',exact:true}).click()
    const confirmation=page.getByRole('dialog',{name:'Reset reference defaults',exact:true})
    await expect(confirmation).toContainText('review decisions and immutable history will be preserved')
    await confirmation.getByRole('button',{name:'Cancel',exact:true}).click()
    expect((await(await request.get('/api/sod/reference',{headers})).json()).origin).toBe('custom')
    await library.getByRole('button',{name:'Reset defaults',exact:true}).click()
    await confirmation.getByRole('button',{name:'Reset defaults',exact:true}).click()
    await expect(confirmation).toHaveCount(0)
    await expect(library).toContainText('Active bundled 1.0.1')
    const resolved=await(await request.get('/api/sod/metadata',{headers})).json()
    expect(resolved.risks.F019.name).toBe('Preserved explicit override')
    expect(resolved.risks.F019.reference.name).toBe('Payment Processing vs. Period Control')
    // Remove this test's explicit text, retaining the separate bundled/custom reset semantics.
    const updated=await(await request.get('/api/sod/catalogue',{headers,params:{search:'F019',limit:'100'}})).json()
    const updatedRisk=updated.items.find((item:{risk_id:string})=>item.risk_id==='F019')
    expect((await request.post('/api/sod/catalogue/F019',{headers,data:{expected_revision:updated.revision,definition_version:updatedRisk.definition_version,metadata:{...updatedRisk.local,display_name:''}}})).ok()).toBeTruthy()

  }finally{
    const current=await(await request.get('/api/sod/reference',{headers})).json()
    // Leave no active reference matches for unrelated tests sharing this disposable server.
    const unused=execFileSync(process.env.PYTHON||'python',['-c',"import sys;sys.path[:0]=['backend','backend/tests'];from test_sod_reference import workbook;sys.stdout.buffer.write(workbook(risks=[('REF_UNUSED','Unused')],activities=[('REF_UNUSED_ACTIVITY','Unused')]))"],{cwd:path.resolve('..'),env:{...Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('SAP_LENS_')&&key!=='DATA_CSV_PATH')),SAP_LENS_CONFIG_DIR:path.join(directory,'effective-generator'),DATA_CSV_PATH:''}})
    expect((await request.put('/api/sod/reference',{headers,data:{expected_revision:current.revision,workbook_base64:unused.toString('base64')}})).ok()).toBeTruthy()
  }
})


test('SoD configuration is compact with bundled defaults and advanced custom imports in both themes', async ({page,request},testInfo)=>{
  await reseed(request,plain)
  const current=await(await request.get('/api/sod/reference',{headers})).json()
  expect((await request.post('/api/sod/reference/reset',{headers,data:{expected_revision:current.revision}})).ok()).toBeTruthy()
  for(const [theme,width] of [['light',375],['dark',1280]] as const){
    expect((await request.post('/api/configuration/theme',{headers,data:{theme}})).ok()).toBeTruthy()
    await page.setViewportSize({width,height:900})
    await page.goto('/#session=browser-test-session');await page.reload()
    await page.getByRole('button',{name:'Open settings',exact:true}).click()
    await page.getByRole('tab',{name:'SoD Risk Configuration',exact:true}).click()
    const library=page.getByRole('region',{name:'SoD reference library'})
    await expect(library).toContainText('Default library');await expect(library).toContainText('1.0.1')
    await expect(library.getByRole('button',{name:'Reset defaults',exact:true})).toBeVisible()
    await expect(library.getByRole('button',{name:'Import reference workbook',exact:true})).not.toBeVisible()
    await expect(page.getByRole('heading',{name:'SoD Risk Catalogue',exact:true})).toHaveCount(0)
    await expect(page.getByRole('button',{name:'Configure SoD source',exact:true})).toHaveCount(0)
    await expect(page.getByRole('region',{name:'SoD Risk Configuration',exact:true}).getByRole('button',{name:'Export CSV',exact:true})).toHaveCount(0)
    await expect(page.getByText('About SoD evaluation evidence',{exact:true})).toHaveCount(0)
    await library.scrollIntoViewIfNeeded()
    await page.screenshot({path:testInfo.outputPath(`compact-sod-${theme}-${width}.png`)})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
    const advanced=library.getByText('Advanced reference settings',{exact:true})
    await advanced.focus();await page.keyboard.press('Enter')
    await expect(library.getByRole('button',{name:'Import reference workbook',exact:true})).toBeVisible()
    const download=page.waitForEvent('download');await library.getByRole('button',{name:'Download template',exact:true}).click();expect((await download).suggestedFilename()).toBe('sap-lens-sod-reference-template.xlsx')
    await page.getByRole('tab',{name:'Activities',exact:true}).click()
    await expect(page.getByRole('searchbox',{name:'Search SoD activities',exact:true})).toBeVisible()
  }
})

test('configuration tables use effective Display names without saving inherited values as overrides',async({page,request})=>{
 await reseed(request,extended)
 await openSettings(page,'SoD Risk Configuration')
 await page.getByRole('searchbox',{name:'Search SoD risks',exact:true}).fill('R1')
 const risks=page.getByRole('table',{name:'SoD risk configurations',exact:true})
 const risk=risks.getByRole('row').filter({has:page.getByRole('button',{name:'Edit SoD risk R1',exact:true})});await expect(risk).toContainText('Duplicate payments');await expect(risk.locator('.id-pill-activity')).toHaveText(['A','B'])
 await page.getByRole('tab',{name:'Activities',exact:true}).click()
 const activities=page.getByRole('table',{name:'SoD activity configurations',exact:true})
 await expect(activities.getByRole('row').filter({has:page.getByRole('button',{name:'Edit SoD activity A',exact:true})})).toContainText('Create invoice')
 await expect(activities).not.toContainText('No local name')
 const catalogue=await(await request.get('/api/sod/catalogue',{headers,params:{search:'R1'}})).json()
 expect(catalogue.items.find((row:{risk_id:string})=>row.risk_id==='R1').local.display_name).toBe('')
})
