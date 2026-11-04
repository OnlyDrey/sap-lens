import {test,expect,type APIRequestContext,type Page} from '@playwright/test'
import {readFileSync,writeFileSync} from 'node:fs'
import path from 'node:path'
import {seedGovernance,cleanup,names,headers,openSod} from './sod-fixture'
let directory=''
const readRole='ZC:MM:SYN_READ:CDK',family='ZC:MM:SYN_READ:*'
async function importSource(request:APIRequestContext,source:'roles'|'users'){
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings
 expect((await request.post(`/api/data-sources/${source}/select`,{headers,data:{path:path.join(directory,`${source}.csv`),mode:'static',revision:settings.revision}})).ok()).toBeTruthy()
}
test.beforeEach(async({request})=>{
 directory=await seedGovernance(request)
 const catalogue=path.join(directory,'roles.csv'),users=path.join(directory,'users.csv')
 writeFileSync(catalogue,readFileSync(catalogue,'utf8')+`${family},Synthetic reporting,ZS:REPORT,X9\nZC:MM:SYN_BUY:*,Synthetic purchasing,ZS:BUY,X1\n`)
 await importSource(request,'roles')
 writeFileSync(users,readFileSync(users,'utf8')+`${names.a},${readRole},FIN,20000101,99991231\n${names.c}_ONLY,${readRole},FIN,20000101,99991231\n${names.c},ZC:MM:SYN_READ:ENO,P2P,20000101,99991231\n${names.b},ZC:MM:SYN_BUY:CDK,P2P,20000101,99991231\n`)
 await importSource(request,'users')
})
test.afterEach(async({request})=>{await cleanup(request,directory)})
async function select(page:Page,label:string,value:string){
 const control=page.getByRole('combobox',{name:label,exact:true})
 await control.click();await control.fill(value)
 await page.getByRole('option',{name:value,exact:true}).click();await control.press('Escape')
}
async function preview(page:Page){
 await openSod(page,'Reviews')
 await page.getByRole('tab',{name:'Bulk Review',exact:true}).click()
 await select(page,'Assigned role',family)
 await select(page,'Role suffix','CDK')
 const table=page.getByRole('table',{name:'Bulk assignment preview',exact:true})
 await expect(table.locator('tbody tr')).toHaveCount(2)
 await expect(table).toContainText(`${names.c}_ONLY`)
 await expect(table).not.toContainText('SYN_READ:ENO')
 return table
}
for(const [action,decision,confirm] of [['Keep','Keep','Keep 2 assignments'],['Remove','Remove','Recommend removal for 2 assignments'],['Investigate','Investigate','Mark for investigation: 2 assignments']] as const)test(`complete bulk ${action} reviews active non-conflict assignments with traceable history`,async({page,request})=>{
 await preview(page)
 await page.getByRole('button',{name:'Select all 2 matching assignments',exact:true}).click()
 await page.getByLabel('Proposed decision',{exact:true}).selectOption(action)
 await page.getByRole('button',{name:'Continue to confirmation (2)',exact:true}).click()
 const dialog=page.getByRole('dialog')
 await expect(dialog).toContainText('Filter scope:')
 await dialog.getByRole('textbox',{name:'Reviewer',exact:true}).fill('Synthetic Bulk Reviewer')
 await dialog.getByRole('textbox',{name:'Rationale',exact:true}).fill('Synthetic confirmed assignment scope')
 await dialog.getByRole('button',{name:confirm,exact:true}).click()
 await expect(dialog.getByRole('status')).toContainText('2 of 2 assignments saved')
 const subject=await(await request.get('/api/sod/subject',{headers,params:{user:`${names.c}_ONLY`}})).json()
 expect(subject.overview.risks).toEqual([])
 expect(subject.overview.activities).toEqual([])
 const row=subject.overview.assignments.find((item:{role:string})=>item.role===readRole)
 expect(row.event.decision).toBe(decision)
 const history=await(await request.get('/api/sod/decisions/assignment/history',{headers,params:{key:row.id}})).json()
 expect(history.items[0].bulk_operation_id).toMatch(/^[a-f0-9]{32}$/)
 expect(history.items[0].reviewer).toBe('Synthetic Bulk Reviewer')
})
test('legacy exact selections remain exact while new family chips clear and restore',async({page,request})=>{
 expect((await request.post('/api/saved-filters',{headers,data:{name:'Synthetic legacy exact role',view:'sod_queue',filters:{roles:[readRole],role_match:'exact',assignment_scope:'all',validity:'active'}}})).ok()).toBeTruthy()
 await preview(page)
 const saved=page.locator('[aria-label="sod_queue saved filters"]').getByRole('button',{name:/Saved filters/})
 await saved.click()
 const menu=page.getByRole('dialog',{name:'sod_queue saved filters',exact:true})
 await menu.getByRole('combobox',{name:'Saved filter',exact:true}).click()
 await page.getByRole('option').filter({hasText:'Synthetic legacy exact role'}).click()
 await menu.getByRole('button',{name:'Load',exact:true}).click();await page.keyboard.press('Escape')
 const table=page.getByRole('table',{name:'Bulk assignment preview',exact:true})
 await expect(table.locator('tbody tr')).toHaveCount(2)
 await expect(table).not.toContainText('SYN_READ:ENO')
 await page.reload()
 await expect(table.locator('tbody tr')).toHaveCount(2)
 await page.getByRole('button',{name:'Clear page filters',exact:true}).click()
 await expect(table).toContainText('SYN_READ:ENO')
})
test('a replacement import rejects an already frozen confirmation without partial decisions',async({page,request})=>{
 await preview(page)
 await page.getByRole('button',{name:'Select all 2 matching assignments',exact:true}).click()
 await page.getByRole('button',{name:'Continue to confirmation (2)',exact:true}).click()
 const dialog=page.getByRole('dialog')
 await dialog.getByRole('textbox',{name:'Reviewer',exact:true}).fill('Synthetic Reviewer')
 await dialog.getByRole('textbox',{name:'Rationale',exact:true}).fill('Synthetic frozen preview')
 const file=path.join(directory,'users.csv')
 writeFileSync(file,readFileSync(file,'utf8')+`${names.b},${readRole},P2P,20000101,99991231\n`)
 await importSource(request,'users')
 await dialog.getByRole('button',{name:'Keep 2 assignments',exact:true}).click()
 await expect(dialog.getByRole('alert')).toContainText('evidence changed')
 const subject=await(await request.get('/api/sod/subject',{headers,params:{user:`${names.c}_ONLY`}})).json()
 expect(subject.overview.assignments[0].event).toBeNull()
})
