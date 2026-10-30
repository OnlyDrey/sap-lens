import {test,expect} from '@playwright/test'
import {textMatches} from '../src/lib/searchMatching'
import {mkdtempSync,writeFileSync,appendFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import { headers } from './support'
let root:string
const cases:[string,string,boolean][]=[['ME23N','ME*',true],['ME23N','*23N',true],['ME23N','*me*',true],['ME23N','ME*23*',true],['XME23N','ME*',false],['ME23NX','*23N',false],['abc','',true],['abc','b',true],['[a].+','[a].*',true],['abc','a?c',false],['a','a*a',false],['Åse','å*',true],['ab','a**b',true],['','**',true]]
test('literal SAP wildcard matching agrees with backend semantics',()=>{for(const [value,query,result] of cases)expect(textMatches(value,query)).toBe(result)})
test.beforeEach(async({request})=>{
 await request.post('/api/configuration/reset',{headers});root=mkdtempSync(path.join(tmpdir(),'sap-lens-search-ui-'))
 const roles=path.join(root,'roles.csv'),users=path.join(root,'users.csv')
 writeFileSync(roles,'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:SYN:BUY,Purchasing,ZS:SYN:BUY,ME23N\nMM,ZC:SYN:BUY,Purchasing,ZS:SYN:BUY,MIGO\nFI,ZC:SYN:FI,Finance,ZS:SYN:FI,FB03\n')
 writeFileSync(users,'USERNAME,ROLE_NAME,EMAIL,ROLE_VALID_FROM,ROLE_VALID_TO\nSYN_BUY,ZC:SYN:BUY,synthetic@example.test,20000101,99991231\nSYN_FI,ZC:SYN:FI,other@example.test,20000101,99991231\n')
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings;settings.data_csv_path=roles;settings.user_csv_path=users
 expect((await request.post('/api/configuration',{headers,data:settings})).ok()).toBeTruthy()
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(root,{recursive:true,force:true})})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`dashboard settings navigation and source layout ${theme} ${width}`,async({page,request},info)=>{
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings;settings.theme=theme;await request.post('/api/configuration',{headers,data:settings})
 await page.setViewportSize({width,height:900});await page.goto('/#session=browser-test-session')
 await expect(page.getByRole('region',{name:'Assignment Distribution',exact:true})).toBeVisible()
 await expect(page.getByRole('region',{name:'Review Progress',exact:true}).locator('.chart-stack-bar')).toHaveCSS('height','14px')
 await page.screenshot({path:info.outputPath(`dashboard-${theme}-${width}.png`)})
 await page.getByRole('button',{name:'Investigate users with 0–5 currently valid roles',exact:true}).click()
 await expect(page.getByRole('button',{name:'Remove assignment count filter',exact:true})).toBeVisible()
 await expect(page.getByRole('navigation',{name:'User Access view',exact:true}).getByRole('link',{name:'User directory',exact:true})).toHaveCSS('border-bottom-width','2px')
 await page.getByRole('link', { name: 'SYN_BUY',exact:true}).click();await expect(page.getByRole('columnheader',{name:'Role description',exact:true})).toHaveCount(0);await expect(page.getByRole('region',{name:'User role assignments',exact:true})).toContainText('Purchasing')
 const back=page.getByRole('button',{name:'Back to users',exact:true});await expect(back).toHaveCSS('border-top-width','1px')
 await expect(page.locator('.profile-matching-evidence')).toHaveCSS('margin-top','16px')
 await page.getByRole('button',{name:'View role details: ZC:SYN:BUY',exact:true}).click()
 const close=page.getByRole('button',{name:'Close role details',exact:true});await expect(close).toBeVisible()
 await expect(page.locator('.role-detail-header .detail-back-action')).toHaveCSS('color',await page.locator('.role-detail-header').evaluate(element=>getComputedStyle(element).color))
 const closeBox=(await close.boundingBox())!,identifier=(await page.locator('.role-detail-identifier').boundingBox())!
 expect(Math.abs(closeBox.x+closeBox.width-identifier.x-identifier.width)).toBeLessThan(2)
 await page.screenshot({path:info.outputPath(`sidebar-${theme}-${width}.png`)});await close.click()
 await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'SAP Modules',exact:true}).click()
 const grid=page.locator('.module-tile-grid');await expect(grid).toBeVisible();
 await page.screenshot({path:info.outputPath(`modules-${theme}-${width}.png`)});expect((await grid.evaluate(element=>getComputedStyle(element).gridTemplateColumns.split(' ').length))).toBe(width<=600?1:width<=1100?2:3)
 await expect(page.getByLabel('Module availability',{exact:true})).toHaveCount(0)
 await page.getByRole('searchbox').first().fill('zzzz-no-module');await expect(grid.getByText('No areas match your search.',{exact:true})).toBeVisible()
 await page.getByRole('tab',{name:'Appearance & Branding',exact:true}).click();await expect(page.getByAltText('Header logo preview',{exact:true})).toBeVisible()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await page.screenshot({path:info.outputPath(`appearance-${theme}-${width}.png`)})
})
test('wildcard role and transaction searches compose with user search and clear controls',async({page})=>{
 await page.goto('/#session=browser-test-session')
 const nav=page.getByRole('navigation',{name:'Main navigation',exact:true})
 await nav.getByRole('link',{name:'Role Lookup',exact:true}).click()
 await page.getByPlaceholder('Search roles by name or description...').fill('ZC:SYN:B*')
 await page.getByRole('textbox',{name:'Filter catalogue by transaction',exact:true}).fill('*23N')
 await expect(page.getByRole('region',{name:'Role catalogue investigation',exact:true})).toHaveAttribute('aria-busy','false')
 await expect(page.getByRole('article',{name:'Purchasing',exact:true})).toBeVisible()
 await expect(page.getByRole('article',{name:'Finance',exact:true})).toHaveCount(0)
 await nav.getByRole('link',{name:'User Access',exact:true}).click()
 await page.getByLabel('Search users',{exact:true}).fill('SYN_B*')
 await expect(page.getByRole('link', { name: 'SYN_BUY',exact:true})).toBeVisible()
 await expect(page.getByRole('link', { name: 'SYN_FI',exact:true})).toHaveCount(0)
 await page.getByRole('button',{name:'Clear filters',exact:true}).click()
 await expect(page.getByRole('link', { name: 'SYN_FI',exact:true})).toBeVisible()
})

test('Release Roles wildcard availability agrees with the matching result',async({page,request})=>{
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings
 appendFileSync(settings.user_csv_path,'SYN_BUY,ZO:MM:M:PR_REL_ST_G1_N1:ALL,synthetic@example.test,20000101,99991231\n')
 expect((await request.post('/api/data-sources/users/select',{headers,data:{path:settings.user_csv_path,revision:settings.revision,mode:'dynamic'}})).ok()).toBeTruthy()
 await page.goto('/#session=browser-test-session')
 await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('link',{name:'Release Roles',exact:true}).click();await page.getByRole('button',{name:'Table',exact:true}).click()
 const checked=page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname==='/api/access/release-options'&&url.searchParams.get('field')==='username'&&url.searchParams.get('selected')==='SYN_B*'})
 await page.getByRole('combobox',{name:'Release username',exact:true}).fill('SYN_B*')
 expect((await(await checked).json()).selected_available).toBe(true)
 await expect(page.getByRole('button',{name:'Copy role identifier ZO:MM:M:PR_REL_ST_G1_N1:ALL',exact:true})).toBeVisible()
 await expect(page.getByText('No available value matches this filter in the current context. Clear it or select All.',{exact:true})).toHaveCount(0)
})
