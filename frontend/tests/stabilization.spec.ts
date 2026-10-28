import {test,expect} from '@playwright/test'
import {transactionMatches,matchingTransactions} from '../src/lib/searchMatching'
import {presentRoleDescription} from '../src/lib/rolePresentation'
import {mkdtempSync,writeFileSync,appendFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
const headers={'X-SAP-Lens':'browser-test-session'}
let directory:string
const csv='FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\n'+[
'BC,ZC:SYN:A,Synthetic Alpha,ZS:SYN:SHARED,BC - Batch Input Management,SOST,Mail',
'BC,ZC:SYN:A,Synthetic Alpha,ZS:SYN:SHARED,BC - Batch Input Management,SO20,Mail settings',
'BC,ZC:SYN:A,Synthetic Alpha,ZS:SYN:SHARED,BC - Batch Input Management,SM35,Batch',
'BC,ZC:SYN:A,Synthetic Alpha,ZD:SYN:ONLY,BC - Exclusive component,SM35,Batch',
'MM,ZC:SYN:B,Synthetic Beta,ZS:SYN:SHARED,BC - Batch Input Management,SOST,Mail',
'MM,ZC:SYN:B,Synthetic Beta,ZS:SYN:SHARED,BC - Batch Input Management,SO20,Mail settings',
'MM,ZC:SYN:B,Synthetic Beta,ZS:SYN:SHARED,BC - Batch Input Management,SO99,Other source mail',
'MM,ZC:SYN:B,Synthetic Beta,ZS:SYN:OTHER,MM - Other component,ME23N,Purchase order',
].join('\n')+'\n'
test.beforeEach(async({request})=>{
 await request.post('/api/configuration/reset',{headers});directory=mkdtempSync(path.join(tmpdir(),'sap-lens-stabilization-'))
 const roles=path.join(directory,'roles.csv'),users=path.join(directory,'users.csv');writeFileSync(roles,csv);writeFileSync(users,'USERNAME,ROLE_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\nSYN_VIEW,ZC:SYN:A,synthetic@example.test,20000101,99991231,20000101,99991231\n')
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings;settings.data_csv_path=roles;settings.user_csv_path=users;expect((await request.post('/api/configuration',{headers,data:settings})).ok()).toBeTruthy()
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(directory,{recursive:true,force:true})})
test('display descriptions and transaction matching preserve literal evidence semantics',()=>{
 expect(presentRoleDescription('BC - Batch Input Management',['BC'])).toEqual({description:'Batch Input Management',area:'BC'})
 expect(presentRoleDescription('UNKNOWN - Retain original',['BC']).description).toBe('UNKNOWN - Retain original')
 expect(presentRoleDescription('BC prose - Preserve',['BC']).description).toBe('BC prose - Preserve')
 expect(transactionMatches('sost',['SO*'])).toBe(true);expect(transactionMatches('SM35',['SO*'])).toBe(false);expect(transactionMatches('SOST',['SO'])).toBe(false)
 expect(matchingTransactions([{tcode:'SOST'},{tcode:'SO20'},{tcode:'SM35'}],['SO*']).map(row=>row.tcode)).toEqual(['SOST','SO20'])
})
test('sidebar wildcard filters rows as well as roles and restores the original collapsed state',async({page,request})=>{
 await page.goto('/#session=browser-test-session');await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('link',{name:'Role Lookup',exact:true}).click();await page.getByRole('button',{name:'View details for Synthetic Alpha',exact:true}).click()
 const dialog=page.getByRole('dialog'),input=dialog.getByRole('textbox',{name:'Find transaction code',exact:true})
 const shared=dialog.locator('.single-role-entry').filter({has:page.getByRole('button',{name:'Expand single role ZS:SYN:SHARED',exact:true})})
 await expect(shared.locator('.role-metadata-title')).toHaveText('Batch Input Management');await expect(shared.getByText('BC',{exact:true})).toBeVisible()
 const source=await(await request.get('/api/roles/'+encodeURIComponent('ZC:SYN:A'),{headers})).json();expect(source.single_roles.find((row:any)=>row.child_agr==='ZS:SYN:SHARED').child_agr_text).toBe('BC - Batch Input Management')
 await input.fill('so*');await expect(dialog.locator('.single-role-entry:visible')).toHaveCount(1);await expect(shared.locator('tbody tr')).toHaveCount(2);await expect(shared.locator('tbody')).not.toContainText('SM35');await expect(shared).toContainText('2 matching')
 await input.fill('SOST');await expect(shared.locator('tbody tr')).toHaveCount(1)
 await input.fill('NO_MATCH*');await expect(dialog.locator('.single-role-entry:visible')).toHaveCount(0)
 await input.fill('');await expect(dialog.locator('.single-role-entry:visible')).toHaveCount(2);await expect(shared.getByRole('button',{name:'Expand single role ZS:SYN:SHARED',exact:true})).toHaveAttribute('aria-expanded','false')
 await shared.getByRole('button',{name:'Expand single role ZS:SYN:SHARED',exact:true}).click();await expect(shared.locator('tbody tr')).toHaveCount(3)
})
for(const theme of ['light','dark'])test(`restored shared surfaces spacing and navigation ${theme}`,async({page,request})=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}});await page.goto('/#session=browser-test-session')
 for(const name of ['Role Distribution','Assignment Distribution']){const card=page.getByRole('region',{name,exact:true});await expect(card).toHaveCSS('padding','16px');await expect(card).toHaveCSS('border-radius','12px');await expect(card).not.toHaveCSS('background-color','rgba(0, 0, 0, 0)')}
 await expect(page.locator('.dashboard-secondary-metrics .dashboard-metric').first()).toHaveCSS('padding-left','12px')
 await expect(page.locator('.app-header-row')).toHaveCSS('min-height','72px')
 await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('link',{name:'User Access',exact:true}).click()
 const link=page.getByRole('navigation',{name:'User Access view',exact:true}).getByRole('link',{name:'User directory',exact:true});await expect(link).toHaveCSS('border-top-width','0px');await expect(link).toHaveCSS('border-bottom-width','2px');const before=(await link.boundingBox())!;await link.hover();expect((await link.boundingBox())!.height).toBe(before.height)
 await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Component Library',exact:true}).click()
 const panel=page.locator('.component-library>.ui-tabs>[role=tabpanel]');await expect(panel).toHaveCSS('display','grid');await expect(panel).toHaveCSS('row-gap','16px')
 const cards=panel.locator(':scope > .ui-card');const a=(await cards.nth(0).boundingBox())!,b=(await cards.nth(1).boundingBox())!;expect(b.y-a.y-a.height).toBeGreaterThanOrEqual(15)
})
test('comparison uses responsive tiles and shared transaction filtering without losing totals',async({page,request},info)=>{
 const source=await(await request.post('/api/compare',{headers,data:{roles:['ZC:SYN:A','ZC:SYN:B']}})).json()
 await page.goto('/#session=browser-test-session');await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('link',{name:'Role Lookup',exact:true}).click()
 for(const name of ['Synthetic Alpha','Synthetic Beta'])await page.getByRole('article',{name,exact:true}).getByRole('button',{name:'Add to comparison',exact:true}).click()
 await page.getByRole('button',{name:'Compare now',exact:true}).click()
 const comparison=page.getByRole('region',{name:'Role comparison',exact:true});await expect(comparison.getByRole('region',{name:'Single role overlap',exact:true})).toHaveCount(0)
 const shared=comparison.locator('section').filter({has:page.getByRole('heading',{name:'Shared by all 2 roles',exact:true})})
 await expect(shared.locator('.single-role-tile')).toHaveCount(source.shared_single_roles.length)
 const input=comparison.getByRole('textbox',{name:'Search comparison transactions',exact:true});await input.fill('SO*');await expect(comparison).toHaveAttribute('aria-busy','false')
 await expect(shared.locator('tbody tr')).toHaveCount(3);await expect(shared.locator('tbody')).toContainText('SO99');await expect(shared.locator('tbody')).not.toContainText('SM35');await expect(comparison.locator('.comparison-columns .single-role-tile')).toHaveCount(0)
 await expect(shared.getByLabel(`${source.shared_single_roles[0].tcode_count} transactions`,{exact:true})).toBeVisible()
 await input.fill('SOST');await expect(shared.locator('tbody tr')).toHaveCount(1)
 await input.fill('NOT_PRESENT*');await expect(comparison.getByRole('status').filter({hasText:'No single roles match this transaction filter.'})).toBeVisible()
 await input.fill('');await expect(shared.locator('.single-role-tile')).toHaveCount(source.shared_single_roles.length);await expect(comparison.locator('.comparison-columns .single-role-tile')).toHaveCount(2)
 await comparison.getByRole('button',{name:'Inspect most similar roles',exact:true}).click();await expect(page.getByRole('dialog',{name:'Shared single roles',exact:true})).toBeVisible();await page.keyboard.press('Escape');await expect(comparison.getByRole('button',{name:'Inspect most similar roles',exact:true})).toBeFocused()
 await page.screenshot({path:info.outputPath('comparison-tiles.png'),fullPage:true})
})
test('review validity stays status-only and Release Roles retains the chosen view through filters',async({page})=>{
 await page.goto('/#session=browser-test-session');const nav=page.getByRole('navigation',{name:'Main navigation',exact:true});await nav.getByRole('link',{name:'User Access',exact:true}).click();await page.getByRole('link',{name:'Account Review',exact:true}).click()
 const row=page.getByRole('row').filter({has:page.getByRole('link', { name: 'SYN_VIEW',exact:true})});await expect(row).toBeVisible();await expect(row.locator('.review-account-dates')).toHaveCount(0);await expect(row.locator('td').nth(3)).toContainText('Valid')
 await nav.getByRole('link',{name:'Release Roles',exact:true}).click();const group=page.getByRole('group',{name:'Release results view',exact:true});await expect(group.getByRole('button').first()).toHaveText('Matrix');await expect(group.getByRole('button',{name:'Matrix',exact:true})).toHaveAttribute('aria-pressed','true');await group.getByRole('button',{name:'Table',exact:true}).click();await page.getByRole('combobox',{name:'Release assignment status',exact:true}).selectOption('all');await expect(group.getByRole('button',{name:'Table',exact:true})).toHaveAttribute('aria-pressed','true')
})
test('branding carousel supports every color keyboard reset and synchronized draft logos',async({page,request})=>{
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Appearance & Branding',exact:true}).click()
 const carousel=page.getByRole('region',{name:'Theme color settings',exact:true}),viewport=carousel.getByLabel('Color properties',{exact:true})
 await carousel.scrollIntoViewIfNeeded();for(let index=0;index<5;index++){await expect(carousel.getByRole('status')).toContainText(`${index+1} / 5`);const slide=carousel.getByRole('group').nth(index);await expect(slide.locator('input:not([type=color])')).toBeInViewport();if(index<4)await carousel.getByRole('button',{name:'Next color property',exact:true}).click()}
 await viewport.focus();await viewport.press('Home');await expect(carousel.getByRole('status')).toContainText('1 / 5');await viewport.press('End');await expect(carousel.getByRole('status')).toContainText('5 / 5');await expect(carousel.getByRole('button',{name:'Next color property',exact:true})).toBeDisabled()
 const before=(await(await request.get('/api/configuration',{headers})).json()).settings
 await carousel.getByRole('button',{name:'Previous color property',exact:true}).click();const slide=carousel.getByRole('group').nth(3),value=slide.locator('input:not([type=color])');const original=await value.inputValue();await value.fill('#123456');await slide.getByRole('button',{name:'Reset Surface / card background',exact:true}).click();await expect(value).toHaveValue(original)
 const live=page.getByAltText('Header logo preview',{exact:true}),local=page.getByAltText('Selected header logo preview',{exact:true});await local.scrollIntoViewIfNeeded();await expect(local).toBeVisible();expect(await local.getAttribute('src')).toBe(await live.getAttribute('src'));expect((await(await request.get('/api/configuration',{headers})).json()).settings.theme_colors).toEqual(before.theme_colors)
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`stabilization visual ${theme} ${width}`,async({page,request},info)=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}});const settings=(await(await request.get('/api/configuration',{headers})).json()).settings;appendFileSync(settings.user_csv_path,'SYN_VIEW,ZO:MM:M:PR_REL_ST_G1_N1:ALL,synthetic@example.test,20000101,99991231,20000101,99991231\nSYN_VIEW,ZO:MM:M:PO_REL_ST_G2_N2:ALL,synthetic@example.test,20000101,99991231,20000101,99991231\n');expect((await request.post('/api/data-sources/users/select',{headers,data:{path:settings.user_csv_path,revision:settings.revision,mode:'dynamic'}})).ok()).toBeTruthy();await page.setViewportSize({width,height:950});await page.goto('/#session=browser-test-session')
 const capture=async(name:string)=>{expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:info.outputPath(`${name}-${theme}-${width}.png`)})}
 await expect(page.getByRole('region',{name:'Role Distribution',exact:true})).not.toHaveCSS('background-color','rgba(0, 0, 0, 0)');await capture('dashboard')
 const nav=page.getByRole('navigation',{name:'Main navigation',exact:true});await nav.getByRole('link',{name:'Role Lookup',exact:true}).click();await page.getByRole('button',{name:'View details for Synthetic Alpha',exact:true}).click();await page.getByRole('textbox',{name:'Find transaction code',exact:true}).fill('SO*');await expect(page.getByRole('dialog').locator('.single-role-entry:visible')).toHaveCount(1);await expect(page.getByRole('dialog').locator('.single-role-entry:visible tbody tr')).toHaveCount(2);await capture('wildcard-sidebar');await page.getByRole('button',{name:'Close role details',exact:true}).click()
 for(const name of ['Synthetic Alpha','Synthetic Beta'])await page.getByRole('article',{name,exact:true}).getByRole('button',{name:'Add to comparison',exact:true}).click();await page.getByRole('button',{name:'Compare now',exact:true}).click();await page.getByRole('textbox',{name:'Search comparison transactions',exact:true}).fill('SO*');const comparison=page.getByRole('region',{name:'Role comparison',exact:true});await expect(comparison).toHaveAttribute('aria-busy','false');await expect(comparison.locator('tbody tr')).toHaveCount(3);await capture('comparison')
 await nav.getByRole('link',{name:'User Access',exact:true}).click();await page.getByRole('link',{name:'Account Review',exact:true}).click();await expect(page.getByRole('link', { name: 'SYN_VIEW',exact:true})).toBeVisible();await capture('review');await nav.getByRole('link',{name:'Release Roles',exact:true}).click();await expect(page.getByRole('table',{name:'PR release matrix',exact:true})).toBeVisible();await capture('release-matrix')
 await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Appearance & Branding',exact:true}).click();await capture('branding');const carousel=page.getByRole('region',{name:'Theme color settings',exact:true});await carousel.scrollIntoViewIfNeeded();await capture('colors');await page.getByAltText('Selected header logo preview',{exact:true}).scrollIntoViewIfNeeded();await capture('logo')
 await page.getByRole('tab',{name:'Component Library',exact:true}).click();const panel=page.locator('.component-library>.ui-tabs>[role=tabpanel]');await expect(panel).toHaveCSS('row-gap','16px');await capture('library')
 const pagination=page.getByRole('navigation',{name:'Demo pagination',exact:true});await pagination.scrollIntoViewIfNeeded();await expect(pagination).toHaveCSS('justify-content','center');await expect(pagination.getByRole('button',{name:'Next',exact:true})).toBeVisible();expect(Math.abs((await pagination.getByRole('button',{name:'Previous',exact:true}).boundingBox())!.y-(await pagination.getByRole('button',{name:'Next',exact:true}).boundingBox())!.y)).toBeLessThanOrEqual(1);await capture('pagination')
})
