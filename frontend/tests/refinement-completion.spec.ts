import {test,expect,type Page,type TestInfo} from '@playwright/test'
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import { headers, goTo, openFilters, closeFilters } from './support'
test.setTimeout(30_000)
let directory:string
const prefix='ZC:SYN:'+ 'LONG_INVESTIGATION_IDENTIFIER_'.repeat(6)
const pattern=prefix+':*',actual=prefix+':ENP'
const child='ZS:SYN:'+ 'SOURCE_RELATIONSHIP_'.repeat(6)
const release='ZO:MM:M:PR_REL_ST_SH_N6:ALL'
async function capture(page:Page,info:TestInfo,name:string){await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:info.outputPath(name),fullPage:true})}
async function mode(page:Page,name:string){await page.getByRole('navigation',{name:'User Access view',exact:true}).getByRole('link',{name,exact:true}).click()}
async function choose(page:Page,label:string,value:string){const input=page.getByRole('combobox',{name:label,exact:true});await input.click();await input.fill(value);await page.getByRole('option').filter({hasText:value}).first().click()}
test.beforeEach(async({request})=>{
 await request.post('/api/configuration/reset',{headers})
 directory=mkdtempSync(path.join(tmpdir(),'sap-lens-refinement-'))
 const roles=path.join(directory,'roles.csv'),users=path.join(directory,'users.csv')
 writeFileSync(roles,'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\n'+`MM,${pattern},Synthetic purchasing investigation,${child},MM - ${'Long synthetic descriptive text '.repeat(8)},MIGO,Goods movement\nMM,${pattern},Synthetic purchasing investigation,ZS:SYN:SECOND,MM - Second description,ME23N,Display purchase order\n`)
 writeFileSync(users,'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,ROLE_VALID_FROM,ROLE_VALID_TO\n'+[[actual,'20000101','99991231'],[actual,'20010101','20020101'],[actual,'99980101','99991231'],[actual,'',''],[release,'20000101','99991231']].map(([r,a,b])=>`SYN_A,${r},SYN_GROUP,Alpha,Synthetic,alpha@example.test,20000101,99991231,0,${a},${b}\n`).join('')+`SYN_B,${actual},SYN_GROUP,Beta,Synthetic,beta@example.test,20000101,99991231,X,20000101,99991231\nSYN_B,${release},SYN_GROUP,Beta,Synthetic,beta@example.test,20000101,99991231,X,20000101,99991231\n`)
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings
 settings.data_csv_path=roles;settings.user_csv_path=users
 expect((await request.post('/api/configuration',{headers,data:settings})).ok()).toBeTruthy()
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(directory,{recursive:true,force:true})})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`shared layouts ${theme} ${width}`,async({page,request},info)=>{
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings;settings.theme=theme;expect((await request.post('/api/configuration',{headers,data:settings})).ok()).toBeTruthy()
 await page.setViewportSize({width,height:1000});await page.goto('/#session=browser-test-session');await expect(page.locator('html')).toHaveAttribute('data-theme',theme)
 const dashboard=page.getByRole('region',{name:'Dashboard',exact:true})
 await expect(dashboard.locator('.ui-page-title>svg')).toBeVisible()
 await expect(dashboard.getByRole('region',{name:'Key figures',exact:true})).toBeVisible()
 await expect(dashboard.getByRole('button',{name:'SAP users',exact:true})).toContainText('2')
 await expect(dashboard.getByRole('button',{name:'Role assignment records',exact:true})).toContainText('7')
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await capture(page,info,'dashboard.png')
 await goTo(page,'User Access');const region=page.getByRole('region',{name:'User Access',exact:true})
 await expect(region.locator('.ui-page-title>svg')).toBeVisible()
 await openFilters(page);await region.getByRole('button',{name:/Saved filters/}).click()
 const popup=page.getByRole('dialog',{name:'users saved filters',exact:true})
 const save=popup.getByRole('button',{name:'Save as new',exact:true}),clear=popup.getByRole('button',{name:'Clear filters',exact:true})
 const sa=(await save.boundingBox())!,cl=(await clear.boundingBox())!
 expect(Math.abs(sa.width-cl.width)).toBeLessThan(1);expect(Math.abs(sa.y-cl.y)).toBeLessThan(1);expect(cl.x-(sa.x+sa.width)).toBeGreaterThanOrEqual(7)
 expect(await popup.evaluate(el=>el.scrollHeight<=el.clientHeight+1)).toBeTruthy()
 await page.keyboard.press('Escape');if(width>=1024)await expect(region.getByRole('button',{name:/Saved filters/})).toBeFocused();await closeFilters(page)

 await capture(page,info,'user-directory.png')
 await mode(page,'Account Review');await openFilters(page);const clearReview=(await page.locator('.filter-sidebar header').getByRole('button',{name:'Clear filters',exact:true}).boundingBox())!;expect(clearReview.height).toBeLessThan(50);await closeFilters(page);await capture(page,info,'account-review.png')
 await mode(page,'Compare users');await choose(page,'User A','SYN_A');await choose(page,'User B','SYN_B');await openFilters(page);await page.getByLabel('Assignment validity',{exact:true}).selectOption('all');await closeFilters(page);await expect(page.getByRole('table',{name:'User comparison evidence',exact:true})).toContainText(actual);await capture(page,info,'comparison.png')
 await goTo(page,'Role Lookup');await page.getByRole('button',{name:'View details for Synthetic purchasing investigation',exact:true}).click();const detail=page.getByRole('dialog',{name:`Role details: ${pattern}`,exact:true});await expect(detail.getByRole('button',{name:`Copy role identifier ${child}`,exact:true})).toBeVisible();await capture(page,info,'role-details.png');await detail.getByRole('button',{name:'Close role details',exact:true}).click()
 await goTo(page,'Release Roles');await page.getByRole('button',{name:'Matrix',exact:true}).click();await expect(page.getByRole('button',{name:'Investigate PR SH N6: 2 users',exact:true})).toBeVisible();await capture(page,info,'release-matrix.png')
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Component Library',exact:true}).click();await page.getByRole('tab',{name:'All components',exact:true}).click()
 const preview=page.getByRole('region',{name:'Import preview',exact:true});await preview.getByRole('searchbox',{name:'Search validated preview'}).fill('me23n');await expect(preview.getByRole('row')).toHaveCount(2)
 await preview.getByRole('button',{name:'Clear Search validated preview',exact:true}).click();await expect(preview.getByRole('row')).toHaveCount(3);await expect(preview.getByRole('searchbox',{name:'Search validated preview'})).toBeFocused()
 const health=page.locator('.component-library .source-health-summary');await expect(health.getByText('Static',{exact:true})).toBeVisible();await expect(health.getByText('Loaded',{exact:true})).toBeVisible();await expect(health.locator('.ui-metadata-list>div')).toHaveCount(4);const color=await health.evaluate(el=>{const probe=document.createElement('span');probe.style.color='var(--success)';el.append(probe);const value=getComputedStyle(probe).color;probe.remove();return value});await expect(health.locator('.source-badge')).toHaveCSS('color',color)
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await capture(page,info,'component-library.png')
})
test('inline long-role comparison preserves all validity evidence and swap identities',async({page},info)=>{
 await page.goto('/#session=browser-test-session');await goTo(page,'User Access');await mode(page,'Compare users')
 await choose(page,'User A','SYN_A');await choose(page,'User B','SYN_B');await page.getByLabel('Assignment validity',{exact:true}).selectOption('all')
 const table=page.getByRole('table',{name:'User comparison evidence',exact:true})
 const row=table.getByRole('row').filter({has:page.getByRole('cell').filter({hasText:actual})}).first()
 await expect(table).toContainText(actual);await expect(table.getByText('Wildcard match',{exact:true})).toHaveCount(0)
 for(const text of ['Active assignment','Expired assignment','Future assignment','Unknown validity'])await expect(table.getByText(text,{exact:true}).first()).toBeVisible()
 await expect(table.getByRole('button',{name:`Copy role identifier ${actual}`,exact:true})).toHaveCount(1) // the compared role is shown once; its evidence rows no longer repeat it
 await expect(row).toBeVisible();await expect(page.getByRole('button',{name:'Swap users',exact:true})).toBeVisible();await page.getByRole('button',{name:'Swap users',exact:true}).click()
 await expect(page.getByRole('combobox',{name:'User A',exact:true})).toHaveValue('SYN_B');await expect(page.getByRole('combobox',{name:'User B',exact:true})).toHaveValue('SYN_A')
 await capture(page,info,'inline-evidence.png')
})
test('release matrix preserves distinct counts with compact keyboard-accessible cells',async({page},info)=>{
 await page.goto('/#session=browser-test-session');await goTo(page,'Release Roles');await page.getByRole('button',{name:'Matrix',exact:true}).click()
 const matrix=page.getByRole('table',{name:'PR release matrix',exact:true})
 await expect(matrix.getByRole('columnheader',{name:'N6',exact:true})).toBeVisible()
 const cell=matrix.getByRole('button',{name:'Investigate PR SH N6: 2 users',exact:true});await expect(cell).toBeVisible()
 const box=(await matrix.boundingBox())!;expect(box.width).toBeLessThan(500)
 await cell.focus();await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:'Open user SYN_A',exact:true})).toBeVisible()
 await capture(page,info,'release-drilldown.png')
})

test('validated user preview searches response-only identity fields without changing totals or active data',async({page,request})=>{
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Data Sources',exact:true}).click();await page.getByRole('tab',{name:'User Access',exact:true}).click()
 await page.getByText('Advanced import format and column mapping',{exact:true}).click()
 const source=page.getByRole('region',{name:'User access CSV configuration',exact:true});await source.getByRole('button',{name:'Preview user import',exact:true}).click()
 const preview=source.getByRole('region',{name:'Import preview',exact:true});await expect(preview.getByRole('row')).toHaveCount(8)
 await preview.getByRole('searchbox',{name:'Search validated preview'}).fill('BETA@EXAMPLE.TEST');await expect(preview.getByRole('row')).toHaveCount(3);await expect(preview.getByRole('searchbox',{name:'Search validated preview'})).toBeFocused();await expect(preview).toContainText('2 of 7 validated preview rows');await expect(preview.locator('.preview-metrics')).toContainText('7')
 await preview.getByRole('searchbox',{name:'Search validated preview'}).fill('no-such-synthetic-user');await expect(preview.getByText('No preview rows match.',{exact:true})).toBeVisible()
 const diagnostics=await(await request.get('/api/diagnostics/export',{headers})).text();expect(diagnostics).not.toContain('beta@example.test')
})

test('single-role zebra surfaces remain unchanged on hover without inner rounding',async({page})=>{
 await page.goto('/#session=browser-test-session');await goTo(page,'Role Lookup');await page.getByRole('button',{name:'View details for Synthetic purchasing investigation',exact:true}).click()
 const entries=page.getByRole('dialog',{name:`Role details: ${pattern}`,exact:true}).locator('.single-role-entry')
 const primary=await entries.nth(0).evaluate(el=>getComputedStyle(el).backgroundColor),secondary=await entries.nth(1).evaluate(el=>getComputedStyle(el).backgroundColor)
 expect(primary).not.toBe(secondary);await expect(entries.nth(0)).toHaveCSS('border-radius','0px');await expect(entries.nth(1)).toHaveCSS('border-radius','0px')
 // Hover is a distinct state on both stripes (neither the stripe nor the same colour on both), and the stripe returns when the pointer leaves.
 await entries.nth(0).hover();const hover0=await entries.nth(0).evaluate(el=>getComputedStyle(el).backgroundColor);expect(hover0).not.toBe(primary)
 await entries.nth(1).hover();const hover1=await entries.nth(1).evaluate(el=>getComputedStyle(el).backgroundColor);expect(hover1).not.toBe(secondary)
 await page.mouse.move(0,0);await expect(entries.nth(0)).toHaveCSS('background-color',primary);await expect(entries.nth(1)).toHaveCSS('background-color',secondary)
 await expect(entries.nth(0).locator('.role-entry-head .transaction-count')).toHaveText('1')
})
test('large matrix contains scrolling, empty cells and high counts in both themes',async({page,request},info)=>{
 const cells=Array.from({length:200},(_,i)=>({document_type:'PR',user_group:'SYN_GROUP',release_group:`G${Math.floor(i/20)}`,release_strategy:String(i%20).padStart(2,'0'),user_count:i===0?99999:i+1})).filter((_,i)=>i!==1)
 await page.route(url=>url.pathname==='/api/access/releases',route=>route.fulfill({json:{items:[],total:0,offset:0,limit:50,loaded:true,groups:['SYN_GROUP'],matrix_total:cells.length,matrix_offset:0,matrix:cells}}))
 for(const theme of ['light','dark']){
  const settings=(await(await request.get('/api/configuration',{headers})).json()).settings;settings.theme=theme;await request.post('/api/configuration',{headers,data:settings})
  await page.setViewportSize({width:375,height:1000});await page.goto('/#session=browser-test-session');await goTo(page,'Release Roles');await page.getByRole('button',{name:'Matrix',exact:true}).click()
  const matrix=page.getByRole('region',{name:'PR release matrix scroll area',exact:true});await expect(matrix.getByRole('button')).toHaveCount(199)
  await expect(matrix.getByRole('button',{name:'Investigate PR G0 00: 99999 users',exact:true})).toBeVisible();await expect(matrix.locator('td[data-intensity="3"]')).toHaveCount(1)
  expect(await matrix.evaluate(el=>el.scrollWidth>el.clientWidth)).toBeTruthy();await matrix.focus();await page.keyboard.press('ArrowRight');await expect.poll(()=>matrix.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await capture(page,info,`large-matrix-${theme}.png`)
 }
})

test('compact evidence retains exact dates, horizontal identifiers and keyboard popover focus',async({page},info)=>{
 await page.setViewportSize({width:1280,height:1000});await page.goto('/#session=browser-test-session');await goTo(page,'User Access');await mode(page,'Compare users')
 await choose(page,'User A','SYN_A');await choose(page,'User B','SYN_B');await page.getByLabel('Assignment validity',{exact:true}).selectOption('all')
 const panel=page.getByRole('complementary',{name:'Filters',exact:true})
 await expect(panel.getByRole('button',{name:'Clear filters',exact:true})).toBeVisible()
 const table=page.getByRole('table',{name:'User comparison evidence',exact:true});expect((await table.getByRole('columnheader').first().boundingBox())!.width).toBeLessThan(400)
 await expect(panel.getByRole('button',{name:/Saved filters/})).toHaveCount(1)
 const evidence=page.locator('.comparison-evidence-item').filter({has:page.getByRole('button',{name:'Active assignment',exact:true})}).first()
 const code=page.locator('.comparison-table .role-entry .role-identifier code').first();await expect(code).toBeVisible();expect(await code.evaluate(el=>getComputedStyle(el).whiteSpace)).toBe('nowrap') // identifiers never wrap; they scroll inside their codeblock when narrow
 await expect(evidence.locator('.role-identifier code')).toHaveCount(0) // the compared role is not repeated inside its own evidence
 const active=evidence.getByRole('button',{name:'Active assignment',exact:true});await active.click()
 const popup=page.getByRole('dialog',{name:`Assignment validity for ${actual}`,exact:true})
 await expect(popup).toContainText('01.01.2000');await expect(popup).toContainText('31.12.9999');await popup.screenshot({path:info.outputPath('assignment-popover.png')});await page.keyboard.press('Escape');await expect(active).toBeFocused()
 const unknown=page.getByRole('button',{name:'Unknown validity',exact:true}).first();await unknown.click();await expect(popup.locator('dd').nth(0)).toHaveText('Unknown');await expect(popup.locator('dd').nth(1)).toHaveText('Unknown');await page.keyboard.press('Escape')
})
test('PR and PO matrices share a content-sized row and stack at tablet width',async({page})=>{
 const matrix=['PR','PO'].map(document_type=>({document_type,user_group:'SYN_GROUP',release_group:'SH',release_strategy:'N6',user_count:2}))
 await page.route(url=>url.pathname==='/api/access/releases',route=>route.fulfill({json:{items:[],total:0,offset:0,limit:50,loaded:true,groups:['SYN_GROUP'],matrix_total:2,matrix_offset:0,matrix}}))
 await page.setViewportSize({width:1600,height:1000});await page.goto('/#session=browser-test-session');await goTo(page,'Release Roles');await page.getByRole('button',{name:'Matrix',exact:true}).click()
 const pr=page.getByRole('table',{name:'PR release matrix',exact:true}),po=page.getByRole('table',{name:'PO release matrix',exact:true})
 const a=(await pr.boundingBox())!,b=(await po.boundingBox())!;expect(Math.abs(a.y-b.y)).toBeLessThan(2);expect(b.x).toBeGreaterThan(a.x+a.width)
 await page.setViewportSize({width:800,height:1000});expect((await po.boundingBox())!.y).toBeGreaterThan((await pr.boundingBox())!.y+a.height)
})
