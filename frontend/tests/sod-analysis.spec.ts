import {test,expect} from '@playwright/test'
import {mkdtempSync,writeFileSync,rmSync,readFileSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {enableSod} from './sod-fixture'
import { headers } from './support'
let directory:string
const matrix='RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\nUIR01,H,S,Synthetic review activities,CREATE,APPROVE,ACTVT1,CREATE,X001,Creation\nUIR01,H,S,Synthetic review activities,CREATE,APPROVE,ACTVT2,APPROVE,X002,Approval\n'
const catalogue='FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nBC,ZC:SYN:CREATE:*,Synthetic Creation,ZS:SYN:CREATE,Synthetic create component,X001,Creation\nBC,ZC:SYN:APPROVE,Synthetic Approval,ZS:SYN:APPROVE,Synthetic approve component,X002,Approval\nBC,ZC:SYN:BOTH,Synthetic Both,ZS:SYN:BOTH,Synthetic combined component,X001,Creation\nBC,ZC:SYN:BOTH,Synthetic Both,ZS:SYN:BOTH,Synthetic combined component,X002,Approval\n'
const users='USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO,USER_LOCKED\n'+[
'SYN_UI_A,ZC:SYN:CREATE:ALL,SYNTHETIC,Example,Analyst,analyst@example.test,20000101,99991231,20000101,99991231,0',
'SYN_UI_A,ZC:SYN:APPROVE,SYNTHETIC,Example,Analyst,analyst@example.test,20000101,99991231,20000101,99991231,0',
'SYN_UI_A,ZC:SYN:APPROVE,SYNTHETIC,Example,Analyst,analyst@example.test,20000101,99991231,20010101,99991231,0',
'SYN_UI_EXPIRED,ZC:SYN:BOTH,SYNTHETIC,Example,Historical,historical@example.test,20000101,99991231,20000101,20200101,1',
'SYN_UI_ONE,ZC:SYN:CREATE:ALL,SYNTHETIC,Example,One,one@example.test,20000101,99991231,20000101,99991231,0'].join('\n')+'\n'
test.beforeEach(async({request})=>{
 await request.post('/api/configuration/reset',{headers});directory=mkdtempSync(path.join(tmpdir(),'sap-lens-sod-ui-'))
 for(const[source,contents]of[['roles',catalogue],['users',users],['sod',matrix]] as const){const filename=path.join(directory,`${source}.csv`);writeFileSync(filename,contents);const config=await(await request.get('/api/configuration',{headers})).json();expect((await request.post(`/api/data-sources/${source}/select`,{headers,data:{path:filename,revision:config.settings.revision,mode:'static'}})).ok()).toBeTruthy()}
 await enableSod(request)
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(directory,{recursive:true,force:true})})
async function userView(page:any){await page.goto('/#session=browser-test-session');await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('link',{name:'SoD',exact:true}).click();await page.getByRole('link',{name:'Access Explorer',exact:true}).click()}
test('SoD user investigation retains both activity sides, wildcard provenance, intervals and navigation context',async({page})=>{
 await userView(page);await expect(page).toHaveURL(/#\/sod\/explorer/);const table=page.getByRole('table',{name:'User risk table',exact:true});await expect(table.getByRole('row')).toHaveCount(2);await expect(table).not.toContainText('SYN_UI_ONE');await expect(table).not.toContainText('SYN_UI_EXPIRED')
 await page.getByRole('button',{name:'Investigate SYN_UI_A UIR01',exact:true}).click();const panel=page.getByRole('dialog',{name:'SYN_UI_A · UIR01',exact:true})
 await expect(panel.getByRole('region',{name:'Activity CREATE',exact:true})).toContainText('ZC:SYN:CREATE:ALL');await expect(panel.getByRole('button',{name:'Open catalogue role ZC:SYN:CREATE:*',exact:true})).toBeVisible();await expect(panel.getByRole('region',{name:'Activity APPROVE',exact:true})).toContainText('ZC:SYN:APPROVE')
 await expect(panel.getByRole('region',{name:'Activity APPROVE',exact:true})).toContainText('01.01.2001');await expect(panel).toContainText('Potential conflict evidence, not effective authorization')
 await page.keyboard.press('Escape');await expect(panel).toHaveCount(0)
 await page.getByRole('searchbox',{name:'Search SoD data',exact:true}).fill('SYN_UI_A');await page.getByRole('button',{name:'Investigate SYN_UI_A UIR01',exact:true}).click();await page.getByRole('dialog',{name:'SYN_UI_A · UIR01',exact:true}).getByRole('link', { name: 'Open SAP user SYN_UI_A',exact:true}).click();await expect(page.getByRole('heading',{name:'SAP Identity',exact:true})).toBeVisible();await page.goBack();await expect(page).toHaveURL(/#\/sod\/explorer/);await expect(page.getByRole('searchbox',{name:'Search SoD data',exact:true})).toHaveValue('SYN_UI_A');await expect(page.getByRole('dialog',{name:'SYN_UI_A · UIR01',exact:true})).toBeVisible();await page.keyboard.press('Escape');await expect(page.getByRole('dialog',{name:'SYN_UI_A · UIR01',exact:true})).toHaveCount(0)
 await page.getByRole('searchbox',{name:'Search SoD data',exact:true}).fill('');await page.getByRole('combobox',{name:'Assignment validity',exact:true}).selectOption('expired');await expect(page.getByRole('table',{name:'User risk table',exact:true})).toContainText('SYN_UI_EXPIRED');await expect(page.getByRole('table',{name:'User risk table',exact:true})).not.toContainText('SYN_UI_A')
})
test('SoD role combinations preserve navigation and filtered CSV contains complete supporting paths',async({page})=>{
 await userView(page);await page.getByRole('tab',{name:'Role conflicts',exact:true}).click();await expect(page.getByRole('table',{name:'Potential SoD findings',exact:true})).toContainText('ZC:SYN:BOTH')
 for(const role of ['ZC:SYN:CREATE:*','ZC:SYN:APPROVE']){const selector=page.getByRole('combobox',{name:'Add catalogue role to combination',exact:true});await selector.fill(role);await page.getByRole('option',{name:role,exact:true}).click()}
 await expect(page.getByRole('table',{name:'Potential SoD findings',exact:true})).toContainText('Selected combination');await page.getByRole('button',{name:'Open role ZC:SYN:BOTH',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Synthetic Both');await page.keyboard.press('Escape')
 await expect(page.getByRole('button',{name:'Remove combination role ZC:SYN:CREATE:*',exact:true})).toBeVisible();await page.getByRole('searchbox',{name:'Search SoD findings',exact:true}).fill('ZC:SYN:BOTH');const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Export CSV',exact:true}).click();const download=await downloadPromise;expect(download.suggestedFilename()).toMatch(/^sap-lens-sod-roles-findings-\d{4}-\d{2}-\d{2}\.csv$/);const csv=readFileSync((await download.path())!,'utf8');expect(csv.startsWith('\ufeff"FINDING_ID"')).toBeTruthy();expect(csv).toContain('ZC:SYN:BOTH')
})
test('SoD missing dependency is unavailable rather than a false no-conflict claim',async({page,request})=>{
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings;settings.features.user_role_mapping=false;expect((await request.post('/api/configuration',{headers,data:settings})).ok()).toBeTruthy();await userView(page);await expect(page.getByText('User–Role Mapping is disabled. Re-enable it in Features to analyze retained assignment evidence.',{exact:true})).toBeVisible();await expect(page.getByText('Unavailable evidence is not proof that no access or conflict exists.',{exact:true})).toBeVisible()
})
for(const theme of ['light','dark'])for(const width of [375,1280])test(`SoD conflict preview ${theme} ${width}`,async({page,request},info)=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}});await page.setViewportSize({width,height:950});await userView(page);await expect(page.getByRole('button',{name:'Investigate SYN_UI_A UIR01',exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:info.outputPath(`sod-conflicts-${theme}-${width}.png`)})
})
test('Access Explorer assignments show active assignments by default, historical ones on request, and the export follows the choice',async({page})=>{
 await userView(page);await page.getByRole('tab',{name:'Assignments',exact:true}).click()
 const table=page.getByRole('table',{name:'Access list',exact:true});await expect(page.getByRole('combobox',{name:'Assignment validity',exact:true})).toHaveValue('active')
 await expect(table).toContainText('SYN_UI_A');await expect(table).not.toContainText('SYN_UI_EXPIRED')
 // The default table has no module label, no redundant active badge and no validity dates.
 await expect(table).not.toContainText('Active assignment');await expect(table.getByRole('columnheader',{name:/valid/i})).toHaveCount(0)
 const exported=async()=>{const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:/Export CSV/}).first().click();const file=await downloadPromise;return readFileSync((await file.path())!,'utf8')}
 const activeCsv=await exported();expect(activeCsv).toContain('SYN_UI_A');expect(activeCsv).not.toContain('SYN_UI_EXPIRED')
 await page.getByRole('combobox',{name:'Assignment validity',exact:true}).selectOption('expired')
 await expect(table).toContainText('SYN_UI_EXPIRED');await expect(table).not.toContainText('SYN_UI_A')
 const expiredCsv=await exported();expect(expiredCsv).toContain('SYN_UI_EXPIRED');expect(expiredCsv).not.toContain('SYN_UI_A')
 await page.getByRole('combobox',{name:'Assignment validity',exact:true}).selectOption('all')
 await expect(table).toContainText('SYN_UI_EXPIRED');await expect(table).toContainText('SYN_UI_A')
})
