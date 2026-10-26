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
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Component Library',exact:true}).click()
 const combo=page.getByRole('combobox',{name:'Demo searchable role',exact:true});await combo.scrollIntoViewIfNeeded();await combo.click()
 await combo.evaluate(el=>{const spacer=document.createElement('div');spacer.id='synthetic-layout-shift';spacer.style.height='70px';el.closest('.ui-field')!.before(spacer)})
 const adjacent=async(anchor:any,panel:any)=>{const a=(await anchor.boundingBox())!,p=(await panel.boundingBox())!;return Math.min(Math.abs(p.y-a.y-a.height),Math.abs(a.y-p.y-p.height))<10}
 await expect.poll(()=>adjacent(combo,page.locator('.combobox-popup'))).toBeTruthy();await page.keyboard.press('Escape');await expect(combo).toBeFocused()
 await page.evaluate(()=>document.getElementById('synthetic-layout-shift')?.remove())
 const choose=page.getByRole('button',{name:'Choose Demo date',exact:true});await choose.scrollIntoViewIfNeeded();await choose.click()
 await choose.evaluate(el=>{const spacer=document.createElement('div');spacer.style.height='70px';el.closest('label')!.before(spacer)})
 await expect.poll(()=>adjacent(choose,page.getByRole('dialog',{name:'Calendar for Demo date',exact:true}))).toBeTruthy();await page.keyboard.press('Escape');await expect(choose).toBeFocused()
})
