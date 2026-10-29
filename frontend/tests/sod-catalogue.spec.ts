import {test,expect} from '@playwright/test'
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import { headers } from './support'
let directory:string
const matrix='RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\nSYN01,H,S,Synthetic incompatible activities,CREATE,APPROVE,ACTVT1,CREATE,X001,Synthetic creation\nSYN01,H,S,Synthetic incompatible activities,CREATE,APPROVE,ACTVT2,APPROVE,X002,Synthetic approval\n'
test.beforeEach(async({request})=>{
 await request.post('/api/configuration/reset',{headers});directory=mkdtempSync(path.join(tmpdir(),'sap-lens-sod-'))
 // Reset intentionally preserves review annotations. Isolate catalogue IDs through the source fixture.
 const filename=path.join(directory,'synthetic-sod.csv');writeFileSync(filename,matrix)
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings
 expect((await request.post('/api/data-sources/sod/select',{headers,data:{path:filename,revision:settings.revision,mode:'static'}})).ok()).toBeTruthy()
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(directory,{recursive:true,force:true})})
async function settings(page:any){await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'SoD Risk Configuration',exact:true}).click()}
test('SoD source uses shared automatic import and snapshot preview controls',async({page,request})=>{
 await settings(page);await page.getByRole('button',{name:'Configure SoD source',exact:true}).click()
 await expect(page.getByRole('tab',{name:'SoD Matrix',exact:true})).toHaveAttribute('aria-selected','true')
 const source=page.getByRole('region',{name:'SoD Matrix source management',exact:true});await expect(source.getByRole('textbox',{name:'SoD Matrix CSV location',exact:true})).toHaveValue(path.join(directory,'synthetic-sod.csv'))
 await source.getByRole('button',{name:'Preview data',exact:true}).click();const dialog=page.getByRole('dialog',{name:'SoD Matrix snapshot preview',exact:true});await expect(dialog.getByRole('columnheader',{name:'ACTIVITY_SLOT',exact:true})).toBeVisible();await expect(dialog.getByRole('cell',{name:'ACTVT1',exact:true})).toBeVisible();await page.keyboard.press('Escape')
 const replacement=path.join(directory,'replacement.csv');writeFileSync(replacement,matrix.replaceAll('SYN01','SYN02'))
 await source.getByRole('textbox',{name:'SoD Matrix CSV location',exact:true}).fill(replacement);await source.getByRole('textbox',{name:'SoD Matrix CSV location',exact:true}).press('Enter');await expect(source.getByRole('status').filter({hasText:'Completed · 2 source records'})).toBeVisible()
 const result=await(await request.get('/api/sod/catalogue?current=current',{headers})).json();expect(result.items.map((item:any)=>item.risk_id)).toEqual(['SYN02'])
 await page.getByRole('tab',{name:'SoD Risk Configuration',exact:true}).click();await page.getByRole('combobox',{name:'Source presence',exact:true}).selectOption('');await expect(page.getByRole('row').filter({has:page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true})})).toContainText('Historical · excluded from current analysis')
})
test('SoD catalogue edits preserve imported definitions and bulk disable requires explicit confirmation',async({page,request})=>{
 await settings(page);await page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true}).click();const dialog=page.getByRole('dialog',{name:'SoD risk SYN01',exact:true})
 await expect(dialog.getByRole('region',{name:'Imported risk definition',exact:true})).toContainText('Synthetic incompatible activities');await expect(dialog.getByRole('table',{name:'ACTVT1 transaction mappings',exact:true})).toContainText('X001')
 await dialog.getByRole('textbox',{name:'Display name',exact:true}).fill('Synthetic business review');await dialog.getByRole('textbox',{name:'Business explanation',exact:true}).fill('Synthetic explanation');await dialog.getByRole('combobox',{name:'Description review status',exact:true}).selectOption('Reviewed');await dialog.getByRole('button',{name:'Save changes',exact:true}).click();await expect(dialog).toHaveCount(0)
 await expect(page.getByRole('cell',{name:'Synthetic business review',exact:false})).toBeVisible()
 const result=await(await request.get('/api/sod/catalogue?current=current',{headers})).json();expect(result.items[0].local.explanation_en).toBe('Synthetic explanation');expect(result.items[0].source.source_text).toBe('Synthetic incompatible activities');expect(result.items[0].description_review_status).toBe('Reviewed')
 page.once('dialog',dialog=>dialog.dismiss());await page.getByRole('button',{name:'Disable all current risks',exact:true}).click();expect((await(await request.get('/api/sod/catalogue?current=current',{headers})).json()).items[0].local.enabled).toBe(true)
 page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Disable all current risks',exact:true}).click();await expect(page.getByRole('status').filter({hasText:'1 current risk configurations updated.'})).toBeVisible();expect((await(await request.get('/api/sod/catalogue?current=current',{headers})).json()).items[0].local.enabled).toBe(false)
 await page.getByRole('button',{name:'Enable all current risks',exact:true}).click();await expect(page.getByRole('row').filter({has:page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true})})).toContainText('Enabled')
})
test('risk and activity configuration is English only, colored by ID and keeps imported mappings',async({page,request})=>{
 await settings(page)
 await page.getByRole('tab',{name:'Activities',exact:true}).click()
 await expect(page.getByRole('table',{name:'SoD activity configurations',exact:true})).toContainText('CREATE')
 await expect(page.getByRole('button',{name:/^Copy/})).toHaveCount(0)
 await page.getByRole('button',{name:'Edit SoD activity CREATE',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'SoD activity CREATE',exact:true})
 await expect(dialog.getByRole('button',{name:'Close dialog',exact:true})).toBeVisible()
 await expect(dialog.getByRole('button')).toHaveCount(4);await expect(dialog.locator('footer').getByRole('button')).toHaveText(['Cancel','Save changes'])
 await expect(dialog.getByLabel(/Norwegian/)).toHaveCount(0)
 await expect(dialog.getByRole('textbox',{name:'Activity',exact:true})).toHaveCount(0)
 await dialog.getByRole('textbox',{name:'Display name',exact:true}).fill('Create documents')
 await dialog.getByRole('textbox',{name:'Activity color',exact:true}).fill('#0D9488');await expect(dialog.locator('.id-pill-activity[data-colored="true"]')).toBeVisible()
 await dialog.getByRole('button',{name:'Save changes',exact:true}).click();await expect(dialog).toHaveCount(0)
 await expect(page.getByRole('row').filter({hasText:'Create documents'}).locator('.id-pill-activity')).toHaveAttribute('data-colored','true')
 const stored=await(await request.get('/api/sod/catalogue-activities?search=CREATE',{headers})).json()
 expect(stored.items[0].local.color).toBe('#0d9488');expect(stored.items[0].tcodes).toEqual(['X001'])
 await page.getByRole('tab',{name:'Risks',exact:true}).click()
 await page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true}).click()
 const risk=page.getByRole('dialog',{name:'SoD risk SYN01',exact:true})
 await expect(risk.getByLabel(/Norwegian/)).toHaveCount(0)
 await risk.getByRole('textbox',{name:'Risk color',exact:true}).fill('#7c3aed');await risk.getByRole('button',{name:'Save changes',exact:true}).click();await expect(risk).toHaveCount(0)
 await expect(page.getByRole('row').filter({has:page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true})}).locator('.id-pill-risk')).toHaveAttribute('data-colored','true')
 const appearance=await(await request.get('/api/sod/appearance',{headers})).json();expect(appearance.risks.SYN01.color).toBe('#7c3aed');expect(appearance.activities.CREATE.name).toBe('Create documents')
})
test('SoD catalogue search and source-value filters remain independently clearable',async({page})=>{
 await settings(page);const search=page.getByRole('searchbox',{name:'Search SoD risks',exact:true});await search.fill('not-present');await expect(page.getByText('No risks match these filters.',{exact:true})).toBeVisible();await page.getByRole('button',{name:'Clear filters',exact:true}).click();await expect(page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true})).toBeVisible();await page.getByRole('textbox',{name:'Source criticality',exact:true}).fill('C');await expect(page.getByText('No risks match these filters.',{exact:true})).toBeVisible();await page.getByRole('textbox',{name:'Source criticality',exact:true}).fill('H');await expect(page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true})).toBeVisible();await page.getByRole('textbox',{name:'Source risk type',exact:true}).fill('UNSUPPORTED');await expect(page.getByText('No risks match these filters.',{exact:true})).toBeVisible();await page.getByRole('button',{name:'Clear filters',exact:true}).click();await expect(page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true})).toBeVisible()
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`SoD settings responsive ${theme} ${width}`,async({page,request},info)=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}});await page.setViewportSize({width,height:950});await settings(page);await expect(page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:info.outputPath(`sod-catalogue-${theme}-${width}.png`)})
})

test('SoD colors use the shared hex input with validation, preview and reset',async({page})=>{
 await settings(page)
 await page.getByRole('button',{name:'Edit SoD risk SYN01',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'SoD risk SYN01'}),hex=dialog.getByRole('textbox',{name:'Risk color',exact:true}),save=dialog.getByRole('button',{name:'Save changes',exact:true})
 await hex.fill('');await expect(hex).toHaveAttribute('placeholder','No color')
 await hex.fill('#12');await expect(dialog.getByRole('alert')).toContainText('six-digit HEX');await expect(save).toBeDisabled()
 await hex.fill('#7C3AED');await expect(save).toBeEnabled();await expect(dialog.locator('.id-pill-risk[data-colored="true"]')).toBeVisible()
 await dialog.getByRole('button',{name:'Reset Risk color',exact:true}).click();await expect(hex).toHaveValue('');await expect(dialog.locator('.id-pill-risk[data-colored="true"]')).toHaveCount(0);await expect(save).toBeEnabled()
})
