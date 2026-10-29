import {test,expect,type APIRequestContext} from '@playwright/test'
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import { headers } from './support'
let root:string,roles:string,users:string,employees:string
const settings=async(request:APIRequestContext)=>(await(await request.get('/api/configuration',{headers})).json()).settings
const directoryColumns='Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'
test.beforeEach(async({request,page})=>{
 expect((await request.post('/api/configuration/reset',{headers})).ok()).toBeTruthy()
 root=mkdtempSync(path.join(tmpdir(),'sap-lens-auto-import-'));roles=path.join(root,'roles.csv');users=path.join(root,'users.csv');employees=path.join(root,'employees.csv')
 writeFileSync(roles,'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nFI,ZC:SYN:A,Synthetic Alpha,ZS:SYN:A,FB03\n')
 writeFileSync(users,'USERNAME,ROLE_NAME,FIRST_NAME,LAST_NAME,EMAIL,ROLE_VALID_FROM,ROLE_VALID_TO\nSYN_A,ZC:SYN:A,Åse,Synthetic,synthetic@example.test,20000101,99991231\n')
 writeFileSync(employees,directoryColumns+'\n;Synthetic Identity;synthetic_ad;;synthetic@example.test;Synthetic Department;Analyst;True;CN=Synthetic,DC=example,DC=test;;;;;;;Missing\n')
 await page.addInitScript(()=>{(window as any).selectedCSV='';(window as any).pywebview={api:{choose_csv:async()=>((window as any).selectedCSV)}}})
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Data Sources',exact:true}).click()
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(root,{recursive:true,force:true})})
test('file selection activates all three sources without confirmation and keeps disabled modules disabled', { tag: '@smoke' },async({page,request})=>{
 const initial=await settings(request)
 for(const [label,file,source] of [['Role Catalogue',roles,'roles'],['User Access',users,'users'],['Employee Directory',employees,'employees']] as const){
  await page.getByRole('tab',{name:label,exact:true}).click()
  const area=page.getByRole('region',{name:`${label} source management`,exact:true})
  await page.evaluate(value=>{(window as any).selectedCSV=value},file)
  await area.getByRole('button',{name:source==='roles'?'Browse for CSV…':source==='users'?'Browse for user CSV…':'Browse employee CSV',exact:true}).click()
  await expect(area.getByRole('status').filter({hasText:'Completed · 1 source records'})).toBeVisible()
  expect((await settings(request)).data_lifecycle.sources[source]?.snapshot||source==='employees'&&(await settings(request)).employee_snapshot_id).toBeTruthy()
  await expect(area.getByRole('button',{name:/^(Import|Confirm|Validate)/})).toHaveCount(0)
  await area.getByRole('button',{name:'Preview data',exact:true}).click()
  const preview=page.getByRole('dialog',{name:`${label} snapshot preview`,exact:true});await expect(preview).toBeVisible();await expect(preview.getByRole('table')).toBeVisible();await page.keyboard.press('Escape')
 }
 expect((await settings(request)).features).toEqual(initial.features)
})
test('same-file reselection replaces data; invalid and empty replacements preserve the publication',async({page,request})=>{
 const area=page.getByRole('region',{name:'Role Catalogue source management',exact:true})
 await page.evaluate(value=>{(window as any).selectedCSV=value},roles)
 const browse=area.getByRole('button',{name:'Browse for CSV…',exact:true})
 await browse.click();await expect(area.getByRole('status').filter({hasText:'Completed · 1 source records'})).toBeVisible()
 writeFileSync(roles,'AGR_NAME,TCODE\nZC:SYN:REPLACED,MIGO\n')
 await browse.click();await expect(area.getByRole('status').filter({hasText:'1 added, 1 removed'})).toBeVisible()
 const previous=await settings(request)
 for(const contents of ['AGR_NAME,TCODE\n','INVALID\nSynthetic\n']){
  writeFileSync(roles,contents);await browse.click();await expect(area.getByRole('alert')).toContainText('No source data was replaced.')
  expect((await settings(request)).revision).toBe(previous.revision)
  expect((await settings(request)).data_lifecycle.sources.roles.snapshot).toBe(previous.data_lifecycle.sources.roles.snapshot)
 }
})
test('automatic activation preserves unrelated Settings drafts and opening source settings does not reimport',async({page,request})=>{
 await page.getByRole('tab',{name:'Organization & SAP System',exact:true}).click()
 const name=page.getByLabel('Organization name',{exact:true});await name.fill('Synthetic unsaved organization')
 await page.getByRole('tab',{name:'Data Sources',exact:true}).click()
 await page.evaluate(value=>{(window as any).selectedCSV=value},roles)
 await page.getByRole('button',{name:'Browse for CSV…',exact:true}).click()
 const area=page.getByRole('region',{name:'Role Catalogue source management',exact:true})
 await expect(area.getByRole('status').filter({hasText:'Completed · 1 source records'})).toBeVisible()
 const revision=(await settings(request)).revision;expect((await settings(request)).organization.name).not.toBe('Synthetic unsaved organization')
 await page.getByRole('tab',{name:'Organization & SAP System',exact:true}).click();await expect(name).toHaveValue('Synthetic unsaved organization')
 await page.getByRole('tab',{name:'Data Sources',exact:true}).click();await expect(area).toBeVisible()
 expect((await settings(request)).revision).toBe(revision)
 await page.getByRole('button',{name:'Apply settings',exact:true}).click()
 expect((await settings(request)).organization.name).toBe('Synthetic unsaved organization')
})
