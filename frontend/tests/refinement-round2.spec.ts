import {test,expect,type Page,type APIRequestContext} from '@playwright/test'
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs'
import {randomUUID} from 'node:crypto'
import {tmpdir} from 'node:os'
import path from 'node:path'
test.setTimeout(45_000)
const headers={'X-SAP-Lens':'browser-test-session'}
const columns='Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'
let root:string,users:string,roles:string,userA:string,userB:string
const settings=async(request:APIRequestContext)=>(await(await request.get('/api/configuration',{headers})).json()).settings
async function nav(page:Page,name:string){await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('button',{name,exact:true}).click()}
async function mode(page:Page,name:string){await page.getByRole('navigation',{name:'User Access view',exact:true}).getByRole('link',{name,exact:true}).click()}
async function openUser(page:Page){await nav(page,'User Access');await page.getByRole('button',{name:userA,exact:true}).click();return page.getByRole('region',{name:'User details',exact:true})}
async function review(page:Page){await nav(page,'User Access');await mode(page,'Account Review');const row=page.getByRole('row').filter({has:page.getByRole('button',{name:userA,exact:true})});await row.getByRole('button',{name:'Needs review',exact:true}).click();return page.getByRole('dialog',{name:`Review account · ${userA}`,exact:true})}
test.beforeEach(async({request})=>{
 await request.post('/api/configuration/reset',{headers});root=mkdtempSync(path.join(tmpdir(),'sap-lens-round2-'));const suffix=randomUUID().slice(0,8).toUpperCase();userA=`SYN_A_${suffix}`;userB=`SYN_B_${suffix}`
 roles=path.join(root,'roles.csv');users=path.join(root,'users.csv');const directory=path.join(root,'directory.csv')
 writeFileSync(roles,'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nBC,ZC:SYN:A,Synthetic Alpha,ZS:SYN:A,MIGO\nBC,ZC:SYN:A,Synthetic Alpha,ZS:SYN:A,ME23N\nMM,ZC:SYN:B,Synthetic Beta,ZS:SYN:B,MIGO\n')
 writeFileSync(users,'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,ROLE_VALID_FROM,ROLE_VALID_TO\n'+[['ZC:SYN:A','20000101','99991231'],['ZC:SYN:B','20000101','99991231'],['ZC:SYN:B','20010101','20020101'],['ZC:SYN:UNKNOWN','20000101','99991231']].map(([role,start,end])=>`${userA},${role},SYN_GROUP,Ålpha,Synthetic,alpha@example.test,20000101,99991231,0,${start},${end}\n`).join('')+`${userB},ZC:SYN:B,SYN_GROUP,Beta,Synthetic,beta@example.test,20000101,99991231,0,20000101,99991231\n`)
 writeFileSync(directory,columns+'\n;Synthetic Alpha;ad_synthetic;;alpha@example.test;Synthetic department;Analyst;False;CN=Synthetic,DC=example,DC=test;;;;;;;Missing\n')
 const config=await settings(request);config.data_csv_path=roles;config.user_csv_path=users;config.features.employee_directory=true
 expect((await request.post('/api/configuration',{headers,data:config})).ok()).toBeTruthy()
 const revision=(await settings(request)).revision,preview=await request.post('/api/employees/preview',{headers,data:{path:directory,revision}});expect(preview.ok()).toBeTruthy()
 expect((await request.post('/api/employees/import',{headers,data:{path:directory,revision,digest:(await preview.json()).digest}})).ok()).toBeTruthy()
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(root,{recursive:true,force:true})})
test('tasks 15–16: assignment AND/OR and export use the same scope without repeated evidence',async({page})=>{
 await page.addInitScript(()=>{(window as any).exported='';(window as any).pywebview={api:{save_user_access_csv:async(_token:string,_name:string,text:string)=>{(window as any).exported=text;return true}}}})
 await page.goto('/#session=browser-test-session');const detail=await openUser(page)
 const input=detail.getByRole('textbox',{name:'Find roles by transaction',exact:true});await input.fill('MIGO');await input.press('Enter');await input.fill('ME23N');await input.press('Enter')
 await expect(detail.getByText('1 matching assignments',{exact:true})).toBeVisible();await expect(detail.getByRole('button',{name:'AND',exact:true})).toHaveAttribute('aria-pressed','true')
 await detail.getByRole('button',{name:'OR',exact:true}).click();await expect(detail.getByText('2 matching assignments',{exact:true})).toBeVisible()
 await detail.getByLabel('Assignment status',{exact:true}).selectOption('all');await expect(detail.getByText('3 matching assignments',{exact:true})).toBeVisible()
 await expect(detail.getByRole('region',{name:'Transaction search evidence',exact:true})).toHaveCount(0);await expect(detail.getByText('Catalogue coverage may be incomplete',{exact:true})).toBeVisible()
 await detail.getByRole('button',{name:'Export CSV',exact:true}).click();await expect.poll(()=>page.evaluate(()=>(window as any).exported)).toContain('Ålpha')
 const text=await page.evaluate(()=>(window as any).exported as string);expect(text.split('\r\n').filter(Boolean)).toHaveLength(4);expect(text.match(/ZC:SYN:B/g)).toHaveLength(2)
})
test('tasks 17–18: directory evidence opens in a labeled modal and restores focus',async({page})=>{
 await page.goto('/#session=browser-test-session');const detail=await openUser(page),trigger=detail.getByRole('button',{name:'Directory matching details · Matched',exact:true});await trigger.click()
 const dialog=page.getByRole('dialog',{name:'Directory matching details',exact:true});await expect(dialog).toContainText('alpha@example.test');await expect(dialog.getByRole('table',{name:'Directory matching source records',exact:true})).toBeVisible()
 await page.keyboard.press('Escape');await expect(dialog).toBeHidden();await expect(trigger).toBeFocused();await expect(detail.locator('.profile-group')).toHaveCount(3)
})
test('tasks 19–21: shared source evidence, interactive feature pill and technical modal',async({page,request})=>{
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Features',exact:true}).click()
 const toggle=page.getByRole('switch',{name:'Employee Directory feature',exact:true});await expect(toggle).toHaveClass(/status-pill/);await toggle.click();await expect(page.getByRole('region',{name:'Employee Directory feature settings',exact:true}).getByText('Operational',{exact:true})).toBeVisible();await expect(page.getByText('Pending change — choose Apply settings to save.',{exact:true})).toBeVisible();expect((await settings(request)).features.employee_directory).toBe(true)
 await page.getByRole('button',{name:'Apply settings',exact:true}).click();expect((await settings(request)).features.employee_directory).toBe(false)
 await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Health & Diagnostics',exact:true}).click()
 for(const name of ['Role Catalogue CSV','User Access CSV','Employee Directory CSV']){
  const card=page.getByRole('region',{name,exact:true});await expect(card.locator('.source-health-summary .ui-metadata-list>div')).toHaveCount(4)
  const trigger=card.getByRole('button',{name:'Technical source details',exact:true});await trigger.click();const dialog=page.getByRole('dialog',{name:`${name} technical details`,exact:true});await expect(dialog.getByText('Configured file',{exact:true})).toBeVisible();await page.keyboard.press('Escape');await expect(trigger).toBeFocused()
 }
})
test('tasks 22–26: dashboard uses observed distributions, review population and navigable areas',async({page,request})=>{
 await page.goto('/#session=browser-test-session');const dashboard=page.getByRole('region',{name:'Dashboard',exact:true})
 await expect(dashboard.getByRole('region',{name:'Review Progress',exact:true})).toContainText('all 2 currently imported SAP accounts')
 const data=await(await request.get('/api/dashboard',{headers})).json();expect(data.role_distribution).toEqual({BC:1,MM:1});expect(Object.values(data.assignment_distribution).reduce((a:any,b:any)=>a+b,0)).toBe(2)
 await expect(dashboard.getByRole('progressbar',{name:'SAP identity match coverage',exact:true})).toHaveCount(1)
 for(const name of ['SAP Overview','Access & Risk','Directory & Data Health','Review Progress','Role Distribution','Data Sources & Configuration'])await expect(dashboard.getByRole('heading',{name,exact:true}).locator('svg')).toBeVisible()
 await dashboard.getByRole('button',{name:'Investigate BC catalogue roles',exact:true}).click();await expect(page.getByRole('article',{name:'Synthetic Alpha',exact:true})).toBeVisible();await expect(page.getByRole('article',{name:'Synthetic Beta',exact:true})).toBeHidden()
})
test('tasks 24 and 28: review findings precede decisions, saves retain real history and Cancel protects drafts',async({page,request})=>{
 await page.goto('/#session=browser-test-session');let dialog=await review(page);await expect(dialog.getByRole('region',{name:'Current review findings',exact:true})).toContainText('AD disabled / SAP valid and unlocked')
 await dialog.getByLabel('Reviewer',{exact:true}).fill('Synthetic reviewer');await dialog.getByLabel('Rationale',{exact:true}).fill('Reviewing current source evidence')
 page.once('dialog',d=>d.dismiss());await page.keyboard.press('Escape');await expect(dialog).toBeVisible()
 await dialog.getByRole('button',{name:'Save review decision',exact:true}).click();await expect(dialog).toBeHidden()
 const row=page.getByRole('row').filter({has:page.getByRole('button',{name:userA,exact:true})});await row.getByRole('button',{name:'Needs review',exact:true}).click();dialog=page.getByRole('dialog',{name:`Review account · ${userA}`,exact:true})
 await dialog.getByLabel('Decision',{exact:true}).selectOption('Investigating');await dialog.getByRole('button',{name:'Save review decision',exact:true}).click();await expect(dialog).toBeHidden()
 const history=await(await request.get(`/api/account-review/history/${userA}`,{headers})).json();expect(history.total).toBe(1)
 await row.getByRole('button',{name:'Investigating',exact:true}).click();await expect(page.getByRole('region',{name:'Review history',exact:true})).toContainText('Needs review');await page.keyboard.press('Escape')
})
test('tasks 27 and 29: change list has readable records, real before/after modal and action icons',async({page})=>{
 await page.goto('/#session=browser-test-session');writeFileSync(roles,readFileSync(roles,'utf8').replace(/Synthetic Alpha/g,'Synthetic updated Alpha'))
 await page.getByRole('button',{name:'Refresh role data from CSV',exact:true}).click();const view=page.getByRole('button',{name:'View Changes',exact:true});await expect(view.locator('svg')).toBeVisible();await expect(page.getByRole('button',{name:'Dismiss refresh report',exact:true}).locator('svg')).toBeVisible();await view.click()
 const dialog=page.getByRole('dialog',{name:'CSV data changes',exact:true});await expect(dialog.getByRole('table',{name:'CSV record changes',exact:true}).getByRole('columnheader')).toHaveText(['Source','Record','Change','Details'])
 await dialog.getByRole('button',{name:'View details for Synthetic updated Alpha',exact:true}).first().click();const record=page.getByRole('dialog',{name:'Change details',exact:true});await expect(record).toContainText('Before:');await expect(record).toContainText('Synthetic Alpha');await expect(record).toContainText('After:');await expect(record).toContainText('Synthetic updated Alpha');await record.getByRole('button',{name:'Back to changes',exact:true}).click();await expect(dialog).toBeVisible()
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`round 2 visual ${theme} ${width}`,async({page,request},info)=>{
 const config=await settings(request);config.theme=theme;await request.post('/api/configuration',{headers,data:config});await page.setViewportSize({width,height:1000});await page.goto('/#session=browser-test-session')
 await page.screenshot({path:info.outputPath('dashboard.png'),fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 const risk=(await page.getByRole('region',{name:'Access & Risk',exact:true}).boundingBox())!,health=(await page.getByRole('region',{name:'Directory & Data Health',exact:true}).boundingBox())!;if(width>=800){expect(Math.abs(risk.y-health.y)).toBeLessThan(2);expect(health.x).toBeGreaterThan(risk.x)}else expect(health.y).toBeGreaterThan(risk.y)
 const detail=await openUser(page);await detail.getByRole('button',{name:'Directory matching details · Matched',exact:true}).click();await page.getByRole('dialog',{name:'Directory matching details',exact:true}).screenshot({path:info.outputPath('directory-match.png')});await page.keyboard.press('Escape')
 await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Health & Diagnostics',exact:true}).click();await page.getByRole('region',{name:'Role Catalogue CSV',exact:true}).getByRole('button',{name:'Technical source details',exact:true}).click();await page.getByRole('dialog',{name:'Role Catalogue CSV technical details',exact:true}).screenshot({path:info.outputPath('source-details.png')});await page.keyboard.press('Escape');await page.getByRole('tab',{name:'Features',exact:true}).click();await page.screenshot({path:info.outputPath('feature-pills.png')});await page.getByRole('button',{name:'Back to SAP Lens',exact:true}).click()
 await nav(page,'User Access');const back=page.getByRole('button',{name:'Back to users',exact:true});if(await back.count())await back.click();await mode(page,'Account Review');const row=page.getByRole('row').filter({has:page.getByRole('button',{name:userA,exact:true})});await row.getByRole('button',{name:'Needs review',exact:true}).click();const modal=page.getByRole('dialog',{name:`Review account · ${userA}`,exact:true});const box=(await modal.boundingBox())!;expect(box.width).toBeLessThanOrEqual(width-16);expect(box.y).toBeGreaterThanOrEqual(7);expect(box.y+box.height).toBeLessThanOrEqual(993);await page.screenshot({path:info.outputPath('review-dialog.png')})
})

for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`task 30 first-open date position ${theme} ${width}`,async({page,request},info)=>{
 const config=await settings(request);config.theme=theme;await request.post('/api/configuration',{headers,data:config})
 let releaseMatch!:()=>void;const gate=new Promise<void>(resolve=>{releaseMatch=resolve})
 await page.route('**/api/employees/match/**',async route=>{const response=await route.fetch();await gate;await route.fulfill({response})})
 await page.setViewportSize({width,height:2200});await page.goto('/#session=browser-test-session');const detail=await openUser(page)
 const trigger=detail.getByRole('button',{name:'Assignment date filters',exact:true}),panel=page.getByRole('dialog',{name:'Assignment date controls',exact:true})
 await trigger.click();await expect(panel).toBeVisible()
 const anchored=async()=>{const a=(await trigger.boundingBox())!,p=(await panel.boundingBox())!,profile=(await detail.getByRole('region',{name:'User profile',exact:true}).boundingBox())!;return {gap:p.y-a.y-a.height,belowProfile:p.y>=profile.y+profile.height,inside:p.x>=7&&p.x+p.width<=width-7&&p.y>=7&&p.y+p.height<=2200-7}}
 await expect.poll(async()=>{const box=await anchored();return box.gap>=4&&box.gap<=9&&box.belowProfile&&box.inside}).toBeTruthy()
 // Reproduce the first-open race: real matching data expands the profile after
 // the portal's initial measurement, without a window scroll/resize event.
 releaseMatch();await expect(detail.getByRole('region',{name:'Organization',exact:true})).toContainText('Analyst')
 await expect.poll(async()=>{const box=await anchored();return box.gap>=4&&box.gap<=9&&box.belowProfile&&box.inside}).toBeTruthy()
 await panel.screenshot({path:info.outputPath('first-open-date-controls.png')})
 await page.setViewportSize({width,height:1200});await trigger.scrollIntoViewIfNeeded();const inResizedViewport=async()=>{const a=(await trigger.boundingBox())!,p=(await panel.boundingBox())!;return Math.min(Math.abs(p.y-a.y-a.height),Math.abs(a.y-p.y-p.height))<10&&p.y>=7&&p.y+p.height<=1193&&p.x>=7&&p.x+p.width<=width-7};await expect.poll(inResizedViewport).toBeTruthy();await page.evaluate(()=>window.scrollBy(0,32));await expect.poll(inResizedViewport).toBeTruthy();await page.setViewportSize({width,height:2200})
 await page.keyboard.press('Escape');await expect(trigger).toBeFocused();await trigger.click();await expect.poll(async()=>{const box=await anchored();return box.gap>=4&&box.gap<=9&&box.belowProfile&&box.inside}).toBeTruthy()
 await panel.getByText('Advanced interval filtering',{exact:true}).click();await panel.getByLabel('Start date from',{exact:true}).fill('01.01.2000');await panel.getByRole('button',{name:'Apply date filters',exact:true}).click();await expect(panel).toBeHidden()
 const active=detail.getByRole('button',{name:'Assignment date filters (1 active)',exact:true});await active.click();await panel.getByRole('button',{name:'Clear date filters',exact:true}).click();await panel.getByRole('button',{name:'Cancel date changes',exact:true}).click();await expect(active).toBeVisible()
})

test('task 30 shared dropdown and calendar follow anchor layout changes',async({page})=>{
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Component Library',exact:true}).click();await page.getByRole('tab',{name:'All components',exact:true}).click()
 const combo=page.getByRole('combobox',{name:'Demo searchable role',exact:true});await combo.scrollIntoViewIfNeeded();await combo.click()
 await combo.evaluate(el=>{const spacer=document.createElement('div');spacer.id='synthetic-layout-shift';spacer.style.height='70px';el.closest('.ui-field')!.before(spacer)})
 const adjacent=async(anchor:any,panel:any)=>{const a=(await anchor.boundingBox())!,p=(await panel.boundingBox())!;return Math.min(Math.abs(p.y-a.y-a.height),Math.abs(a.y-p.y-p.height))<10}
 await expect.poll(()=>adjacent(combo,page.locator('.combobox-popup'))).toBeTruthy();await page.keyboard.press('Escape');await expect(combo).toBeFocused()
 await page.evaluate(()=>document.getElementById('synthetic-layout-shift')?.remove())
 const choose=page.getByRole('button',{name:'Choose Demo date',exact:true});await choose.scrollIntoViewIfNeeded();await choose.click()
 await choose.evaluate(el=>{const spacer=document.createElement('div');spacer.style.height='70px';el.closest('label')!.before(spacer)})
 await expect.poll(()=>adjacent(choose,page.getByRole('dialog',{name:'Calendar for Demo date',exact:true}))).toBeTruthy();await page.keyboard.press('Escape');await expect(choose).toBeFocused()
})

async function prepareAssignmentExport(request:APIRequestContext){
 const pr='ZO:MM:M:PR_REL_ST_SH_N6:ALL',po='ZO:MM:M:PO_REL_ST_PG_P1:ALL'
 const lines=[[userA,pr,'SYN_GROUP','20000101','99991231'],[userA,pr,'SYN_GROUP','20010101','20020101'],[userA,po,'SYN_PO','20000101','99991231'],[userB,pr,'SYN_GROUP','20000101','99991231']].map(([user,role,group,start,end])=>`${user},${role},${group},Ålpha,Synthetic,${user===userA?'alpha':'beta'}@example.test,20000101,99991231,0,${start},${end}\n`).join('')
 writeFileSync(users,readFileSync(users,'utf8')+lines);expect((await request.post('/api/refresh',{headers})).ok()).toBeTruthy()
}
async function downloadAssignments(page:Page){
 const pending=page.waitForEvent('download');await page.getByRole('button',{name:'Export CSV',exact:true}).click();const file=await pending;const location=(await file.path())!
 const bytes=readFileSync(location);expect(bytes.subarray(0,3).equals(Buffer.from([0xef,0xbb,0xbf]))).toBeTruthy()
 const {execFileSync}=await import('node:child_process')
 const rows=JSON.parse(execFileSync('python',['-c',"import csv,json,sys; print(json.dumps(list(csv.DictReader(open(sys.argv[1],encoding='utf-8-sig',newline=''),delimiter=';'))))",location],{encoding:'utf8'})) as Record<string,string>[]
 return {rows,text:bytes.toString('utf8'),filename:file.suggestedFilename()}
}
test('task 31 directory exports all assignments for filtered users with explicit matches',async({page,request})=>{
 await prepareAssignmentExport(request);await page.goto('/#session=browser-test-session');await nav(page,'User Access')
 await page.getByLabel('Search users',{exact:true}).fill(userA)
 const group=page.getByRole('combobox',{name:'SAP User Group',exact:true});await group.click();await group.fill('SYN_GROUP');await page.getByRole('option',{name:'SYN_GROUP',exact:true}).click()
 const role=page.getByRole('combobox',{name:'Filter users by role',exact:true});await role.click();await role.fill('ZC:SYN:B');await page.getByRole('option').filter({hasText:'ZC:SYN:B'}).first().click()
 await page.getByRole('textbox',{name:'Filter users by transaction',exact:true}).fill('MIGO')
 await expect(page.getByRole('button',{name:'Export CSV',exact:true})).toBeEnabled();const file=await downloadAssignments(page)
 expect(file.rows).toHaveLength(7);expect(new Set(file.rows.map(row=>row.USERNAME))).toEqual(new Set([userA]));expect(file.rows.filter(row=>row.MATCHED_FILTER==='Yes')).toHaveLength(1)
 expect(file.rows.find(row=>row.ROLE_NAME==='ZC:SYN:B'&&row.ASSIGNMENT_STATUS==='Expired')?.MATCHED_FILTER).toBe('No')
 expect(file.rows.find(row=>row.ROLE_NAME.includes('PO_REL'))?.MATCHED_FILTER).toBe('No')
 await page.getByLabel('Show expired assignments',{exact:true}).check();const expired=await downloadAssignments(page);expect(expired.rows).toHaveLength(7);expect(expired.rows.filter(row=>row.MATCHED_FILTER==='Yes')).toHaveLength(2)
 await page.getByLabel('Search users',{exact:true}).fill('NO_SYNTHETIC_MATCH');await expect(page.getByRole('button',{name:'Export CSV',exact:true})).toBeDisabled()
})
test('task 31 release Table and Matrix export identical filtered intervals',async({page,request})=>{
 await prepareAssignmentExport(request);await page.goto('/#session=browser-test-session');await nav(page,'Release Roles')
 const pr=page.getByRole('combobox',{name:'PR/PO',exact:true});await pr.click();await pr.fill('PR');await page.getByRole('option',{name:'PR',exact:true}).click()
 await page.getByLabel('Release assignment status',{exact:true}).selectOption('all')
 await expect(page.getByRole('button',{name:'Export CSV',exact:true})).toBeEnabled();const table=await downloadAssignments(page);expect(table.rows).toHaveLength(3)
 expect(table.rows.every(row=>row.PR_PO==='PR'&&row.RELEASE_GROUP==='SH'&&row.RELEASE_STRATEGY==='N6'&&row.MATCHED_FILTER==='Yes')).toBeTruthy()
 await page.getByRole('button',{name:'Matrix',exact:true}).click();const matrix=await downloadAssignments(page);expect(matrix.text).toBe(table.text)
 await pr.click();await pr.fill('PO');await page.getByRole('option',{name:'PO',exact:true}).click();const po=await downloadAssignments(page);expect(po.rows).toHaveLength(1);expect(po.rows[0].PR_PO).toBe('PO')
})
test('task 31 export includes users beyond visible pagination',async({page,request})=>{
 writeFileSync(users,readFileSync(users,'utf8')+Array.from({length:125},(_,i)=>`PAGE_${String(i).padStart(3,'0')},ZC:SYN:B,SYN_PAGE,Synthetic,Page,,20000101,99991231,0,20000101,99991231\n`).join(''));await request.post('/api/refresh',{headers})
 await page.goto('/#session=browser-test-session');await nav(page,'User Access');await page.getByLabel('Search users',{exact:true}).fill('PAGE_');await expect(page.locator('.user-directory-table tbody tr')).toHaveCount(50)
 const file=await downloadAssignments(page);expect(file.rows).toHaveLength(125);expect(new Set(file.rows.map(row=>row.USERNAME)).size).toBe(125)
})
test('task 31 desktop save uses existing capability and semicolon contract',async({page,request})=>{
 await prepareAssignmentExport(request);await page.addInitScript(()=>{(window as any).assignmentExports=[];(window as any).pywebview={api:{save_user_access_csv:async(token:string,filename:string,content:string)=>{(window as any).assignmentExports.push({token,filename,content});return true}}}})
 await page.goto('/#session=browser-test-session');await nav(page,'User Access');await page.getByRole('button',{name:'Export CSV',exact:true}).click();await expect.poll(()=>page.evaluate(()=>(window as any).assignmentExports.length)).toBe(1)
 await nav(page,'Release Roles');await page.getByRole('button',{name:'Export CSV',exact:true}).click();await expect.poll(()=>page.evaluate(()=>(window as any).assignmentExports.length)).toBe(2)
 const calls=await page.evaluate(()=>(window as any).assignmentExports);expect(calls.every((item:any)=>item.token==='browser-test-session'&&item.content.startsWith('\ufeff"USERNAME";"FIRST_NAME";'))).toBeTruthy();expect(calls[0].filename).toContain('user-directory');expect(calls[1].filename).toContain('release-roles')
})

test('task 31 stale export metadata is rejected before a download',async({page})=>{
 let downloads=0;page.on('download',()=>downloads++)
 await page.route('**/api/access/exports/users?**',async route=>{const response=await route.fetch();await route.fulfill({response,headers:{...response.headers(),'x-sap-lens-data-revision':'synthetic-stale'}})})
 await page.goto('/#session=browser-test-session');await nav(page,'User Access');await page.getByRole('button',{name:'Export CSV',exact:true}).click();await expect(page.getByRole('alert')).toContainText('Source data changed');expect(downloads).toBe(0)
})
test('task 31 filter changes cancel an in-flight export',async({page})=>{
 let release!:()=>void,arrived!:()=>void;const gate=new Promise<void>(resolve=>release=resolve),requested=new Promise<void>(resolve=>arrived=resolve);let downloads=0
 page.on('download',()=>downloads++);await page.route('**/api/access/exports/users?**',async route=>{const response=await route.fetch();arrived();await gate;await route.fulfill({response})})
 await page.goto('/#session=browser-test-session');await nav(page,'User Access');await page.getByRole('button',{name:'Export CSV',exact:true}).click();await requested
 await page.getByLabel('Search users',{exact:true}).fill('NO_SYNTHETIC_RESULT');await expect(page.locator('.user-directory-table tbody tr')).toHaveCount(0);release()
 await expect(page.getByRole('button',{name:'Export CSV',exact:true})).not.toHaveAttribute('aria-busy','true');expect(downloads).toBe(0)
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`task 31 export toolbars ${theme} ${width}`,async({page,request},info)=>{
 await prepareAssignmentExport(request);const config=await settings(request);config.theme=theme;await request.post('/api/configuration',{headers,data:config});await page.setViewportSize({width,height:1000});await page.goto('/#session=browser-test-session');await nav(page,'User Access')
 const action=page.getByRole('button',{name:'Export CSV',exact:true});await expect(action).toBeEnabled();await page.locator('.results-toolbar:visible').screenshot({path:info.outputPath('directory-export-toolbar.png')});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await nav(page,'Release Roles');await expect(action).toBeEnabled();await page.locator('.results-toolbar:visible').screenshot({path:info.outputPath('release-export-toolbar.png')});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
})
