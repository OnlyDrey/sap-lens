import {test,expect,type Page,type APIRequestContext} from '@playwright/test'
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {jaccard,containment} from '../src/lib/comparisonMetrics'
const headers={'X-SAP-Lens':'browser-test-session'}
let directory:string,userPath:string
const config=async(request:APIRequestContext)=>(await(await request.get('/api/configuration',{headers})).json()).settings
const nav=async(page:Page,name:string)=>page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('button',{name,exact:true}).click()
const settings=async(page:Page,tab:string)=>{await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:tab,exact:true}).click()}
test.beforeEach(async({request})=>{
 await request.post('/api/configuration/reset',{headers});directory=mkdtempSync(path.join(tmpdir(),'sap-lens-refine-'));userPath=path.join(directory,'users.csv');const rolePath=path.join(directory,'roles.csv')
 writeFileSync(rolePath,'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:SYN:A,Synthetic Alpha,ZS:SYN:ONE,MIGO\nMM,ZC:SYN:B,Synthetic Beta,ZS:SYN:ONE,MIGO\nMM,ZC:SYN:B,Synthetic Beta,ZS:SYN:TWO,ME23N\nBC,ZC:SYN:'+ 'LONG_'.repeat(25)+',Synthetic Long,ZS:SYN:THREE,VA03\n')
 writeFileSync(userPath,'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,ROLE_VALID_FROM,ROLE_VALID_TO\nSYN_REVIEW,ZC:SYN:A,SYN,Demo,Synthetic,demo@example.test,20000101,99991231,0,20000101,99991231\n')
 const value=await config(request);value.data_csv_path=rolePath;value.user_csv_path=userPath;expect((await request.post('/api/configuration',{headers,data:value})).ok()).toBeTruthy()
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(directory,{recursive:true,force:true})})
test('comparison metric distinguishes symmetric similarity from directional containment',()=>{
 expect(jaccard(2,2,2)).toBe(100);expect(jaccard(1,1,2)).toBe(50);expect(jaccard(1,2,2)).toBe(33);expect(jaccard(0,2,3)).toBe(0);expect(jaccard(0,0,0)).toBe(0);expect(containment(1,1)).toBe(100);expect(containment(1,2)).toBe(50)
})
test('catalogue search visual order matches keyboard order and cards contain long identifiers',async({page})=>{
 await page.goto('/#session=browser-test-session');await nav(page,'Role Lookup')
 const tc=page.getByRole('textbox',{name:'Filter catalogue by transaction',exact:true}),name=page.getByPlaceholder('Search roles by name or description...')
 await expect(tc).not.toBeFocused();expect((await tc.boundingBox())!.x).toBeLessThan((await name.boundingBox())!.x)
 await tc.focus();await page.keyboard.press('Tab');await expect(name).toBeFocused()
 for(const card of await page.locator('article.role-card').all()){const box=(await card.boundingBox())!;expect(box.x+box.width).toBeLessThanOrEqual(1280);await expect(card.getByRole('button',{name:/View details/})).toHaveCSS('min-height','34px')}
 await tc.fill('MIGO');await expect(page.locator('article.role-card')).toHaveCount(2)
})
test('role comparison subset uses Jaccard summaries and directional matrix labels',async({page,request})=>{
 const response=await request.post('/api/compare',{headers,data:{roles:['ZC:SYN:A','ZC:SYN:B']}});expect((await response.json()).pairwise_single_overlaps[0].shared_count).toBe(1)
 await page.goto('/#session=browser-test-session');await nav(page,'Role Lookup')
 for(const title of ['Synthetic Alpha','Synthetic Beta'])await page.getByRole('article',{name:title,exact:true}).getByRole('button',{name:'Add to comparison',exact:true}).click()
 await page.getByRole('button',{name:'Compare now',exact:true}).click();await expect(page.getByText('mean Jaccard similarity',{exact:true})).toBeVisible();await expect(page.getByText('50%',{exact:true}).first()).toBeVisible()
 const cell=page.getByRole('button',{name:/Synthetic Alpha and Synthetic Beta: 1 shared/});await expect(cell).toHaveAttribute('title',/100% of row role; 50% of column role; 50% Jaccard/);await cell.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');await expect(cell).toBeFocused();await expect(cell).toHaveCSS('outline-style','solid');const panels=page.locator('.comparison-columns>div');expect((await panels.nth(0).boundingBox())!.height).toBeLessThan((await panels.nth(1).boundingBox())!.height);await cell.click();await expect(page.getByRole('dialog',{name:'Shared single roles',exact:true})).toBeVisible();await page.keyboard.press('Escape')
})
test('module configuration applies only to parent draft and cancel discards local edits',async({page,request})=>{
 await page.goto('/#session=browser-test-session');await settings(page,'SAP Modules');const edit=page.getByRole('button',{name:/Edit MM —/});await edit.click()
 let modal=page.getByRole('dialog',{name:/Configure MM —/});await modal.getByLabel('MM display name',{exact:true}).fill('Synthetic draft');page.once('dialog',dialog=>dialog.accept());await modal.getByRole('button',{name:'Cancel module changes',exact:true}).click();expect((await config(request)).module_overrides.MM?.display_name).toBeFalsy()
 await edit.click();modal=page.getByRole('dialog',{name:/Configure MM —/});await expect(modal.getByLabel('MM display name',{exact:true})).toHaveValue('');await modal.getByLabel('MM display name',{exact:true}).fill('Synthetic draft');await modal.getByRole('button',{name:'Apply module changes',exact:true}).click();expect((await config(request)).module_overrides.MM?.display_name).toBeFalsy();await page.getByRole('button',{name:'Apply settings',exact:true}).click();expect((await config(request)).module_overrides.MM.display_name).toBe('Synthetic draft')
})
test('complete release matrix includes cells beyond the legacy 200-cell page and exports the same records',async({page,request})=>{
 writeFileSync(userPath,'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n'+Array.from({length:230},(_,i)=>`SYN_${i},ZO:MM:M:PR_REL_ST_G${i}_S1:ALL,SYN,20000101,99991231`).join('\n'))
 await request.post('/api/refresh',{headers});const paged=await(await request.get('/api/access/releases',{headers})).json();expect(paged.matrix.length).toBe(200)
 const full=await(await request.get('/api/access/releases?matrix_complete=true',{headers})).json();expect(full.matrix.length).toBe(230)
 await page.goto('/#session=browser-test-session');await nav(page,'Release Roles');await page.getByRole('button',{name:'Matrix',exact:true}).click();await expect(page.getByRole('table',{name:'PR release matrix',exact:true}).getByRole('row')).toHaveCount(231);await expect(page.getByRole('navigation',{name:'Matrix pagination',exact:true})).toHaveCount(0);await page.getByRole('button',{name:'Investigate PR G229 S1: 1 users',exact:true}).click();await expect(page.getByRole('button',{name:'Open user SYN_229',exact:true})).toBeVisible()
})
test('library categories remain isolated and anchored controls are measured before visible frames',async({page,request})=>{
 await page.goto('/#session=browser-test-session');const before=await config(request);await settings(page,'Component Library');await expect(page.getByRole('button',{name:'Primary',exact:true})).toBeVisible();await expect(page.getByLabel('Demo date',{exact:true})).toHaveCount(0)
 await page.getByRole('tab',{name:'Forms & Inputs',exact:true}).click();await expect(page.getByLabel('Demo date',{exact:true})).toBeVisible()
 await page.getByRole('tab',{name:'Dialogs & Popovers',exact:true}).click();const trigger=page.getByRole('button',{name:'Open demo popover',exact:true});await trigger.scrollIntoViewIfNeeded()
 await page.evaluate(()=>{(window as any).visibleFrames=[];const loop=()=>{const p=document.querySelector('.ui-popover') as HTMLElement|null;if(p&&getComputedStyle(p).visibility==='visible'){const b=p.getBoundingClientRect();(window as any).visibleFrames.push({x:b.x,y:b.y,height:b.height})}if((window as any).visibleFrames.length<3)requestAnimationFrame(loop)};requestAnimationFrame(loop)})
 await trigger.click();await expect.poll(()=>page.evaluate(()=>(window as any).visibleFrames.length)).toBeGreaterThanOrEqual(3);const anchor=(await trigger.boundingBox())!;for(const box of await page.evaluate(()=>(window as any).visibleFrames)){expect(box.x).toBeGreaterThanOrEqual(7);expect(Math.min(Math.abs(box.y-anchor.y-anchor.height),Math.abs(anchor.y-box.y-box.height))).toBeLessThan(10);expect(box.y).toBeGreaterThan(0)}
 await page.keyboard.press('Escape');await expect(trigger).toBeFocused();expect((await config(request)).revision).toBe(before.revision)
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`refinement visual ${theme} ${width}`,async({page,request},info)=>{
 await page.addInitScript(()=>{(window as any).pywebview={api:{choose_csv:async()=>null,desktop_runtime:async()=>({windows:true,startup_supported:true,tray_available:false,warning:null})}}})
 const value=await config(request);value.theme=theme;await request.post('/api/configuration',{headers,data:value});await page.setViewportSize({width,height:1000});await page.goto('/#session=browser-test-session')
 const capture=async(name:string)=>{expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:info.outputPath(name+'.png'),fullPage:true})}
 const distribution=(await page.getByRole('region',{name:'Role Distribution',exact:true}).boundingBox())!,sources=(await page.getByRole('region',{name:'Configuration',exact:true}).boundingBox())!;if(width>800){expect(Math.abs(distribution.y-sources.y)).toBeLessThan(2);expect(sources.x).toBeGreaterThan(distribution.x)}else expect(sources.y).toBeGreaterThan(distribution.y)
 await capture('dashboard');await nav(page,'Role Lookup');await capture('role-cards');await page.getByRole('button',{name:'View details for Synthetic Long',exact:true}).click();await capture('role-details');await page.getByRole('button',{name:'Close role details',exact:true}).click();await settings(page,'Appearance & Branding');await capture('appearance');await page.getByLabel('Logo file location',{exact:true}).scrollIntoViewIfNeeded();await capture('logo-controls');await page.getByRole('tab',{name:'SAP Modules',exact:true}).click();await page.getByRole('button',{name:/Edit MM —/}).click();await capture('module-dialog');await page.keyboard.press('Escape');await page.getByRole('tab',{name:'Component Library',exact:true}).click();await page.getByRole('tab',{name:'Status & Feedback',exact:true}).click();await page.emulateMedia({reducedMotion:'reduce'});await expect(page.locator('.animate-spin').first()).toHaveCSS('animation-name','none');await capture('component-library');await page.getByRole('tab',{name:'Features',exact:true}).click();await expect(page.getByRole('region',{name:'Windows Desktop background operation',exact:true})).toBeVisible();await capture('desktop-options')
})

test('profile match placement and manual review wording preserve separate account evidence',async({page})=>{
 await page.goto('/#session=browser-test-session');await nav(page,'User Access');await page.getByRole('button',{name:'SYN_REVIEW',exact:true}).click()
 const identity=page.getByRole('region',{name:'SAP Identity',exact:true});await expect(identity.getByRole('button',{name:/Directory matching details/})).toBeVisible()
 await page.getByRole('button',{name:'Back to users',exact:true}).click();await page.getByRole('link',{name:'Account Review',exact:true}).click()
 const row=page.getByRole('row').filter({has:page.getByRole('button',{name:'SYN_REVIEW',exact:true})});await expect(row).toContainText('No automated findings');await expect(row).toContainText('Pending manual review');await expect(row.locator('.review-account-dates')).toContainText('From: 01.01.2000To: 31.12.9999')
})

test('release fields align and Data Health reuses canonical source state',async({page})=>{
 await page.goto('/#session=browser-test-session');await nav(page,'Release Roles')
 for(const grid of await page.locator('.release-filters .filter-grid').all()){
  const controls=await grid.locator('input:not([type=checkbox]),select').all();expect(controls.length).toBeGreaterThan(0)
  const boxes=await Promise.all(controls.map(control=>control.boundingBox()));const visible=boxes.filter(box=>box!==null)
  expect(Math.max(...visible.map(box=>box!.y))-Math.min(...visible.map(box=>box!.y))).toBeLessThanOrEqual(1)
  for(const box of visible)expect(box!.height).toBe(42)
 }
 await settings(page,'Data Sources');await page.getByText('Data Health & Coverage',{exact:true}).click();await expect(page.locator('.health-source-grid .source-compact')).toHaveCount(3);await expect(page.locator('.health-source-grid').getByText('Loaded',{exact:true})).toHaveCount(2)
})

test('Windows tray settings use the parent draft, persist and respond to native settings navigation',async({page,request})=>{
 await page.addInitScript(()=>{(window as any).pywebview={api:{choose_csv:async()=>null,desktop_runtime:async(token:string)=>{if(token!=='browser-test-session')throw Error('Wrong capability');return {windows:true,startup_supported:true,tray_available:false,warning:null}}}}})
 await page.goto('/#session=browser-test-session');await expect.poll(()=>page.evaluate(()=>window.__sapLensSettingsReady)).toBe(true);await page.evaluate(()=>window.dispatchEvent(new Event('sap-lens-open-settings')));await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeVisible();await page.getByRole('tab',{name:'Features',exact:true}).click()
 const area=page.getByRole('region',{name:'Windows Desktop background operation',exact:true}),toggle=area.getByRole('switch',{name:'Minimize to System Tray on Close',exact:true})
 await expect(toggle).toHaveAttribute('aria-checked','false');await expect(area.getByLabel('Start minimized to the system tray',{exact:true})).toBeDisabled()
 await toggle.click();await area.getByLabel('Start minimized to the system tray',{exact:true}).check();await area.getByLabel('Start SAP Lens at Windows sign-in',{exact:true}).check();expect((await config(request)).desktop.close_to_tray).toBe(false)
 await page.getByRole('button',{name:'Apply settings',exact:true}).click();expect((await config(request)).desktop).toEqual({close_to_tray:true,run_at_signin:true,start_minimized:true})
 await page.reload();await settings(page,'Features');await expect(toggle).toHaveAttribute('aria-checked','true');await expect(area.getByLabel('Start minimized to the system tray',{exact:true})).toBeChecked();await toggle.click();await expect(area.getByLabel('Start minimized to the system tray',{exact:true})).not.toBeChecked()
})
test('Windows tray controls are unavailable without the native Windows capability',async({page})=>{
 await page.goto('/#session=browser-test-session');await settings(page,'Features');await expect(page.getByRole('region',{name:'Windows Desktop background operation',exact:true})).toHaveCount(0)
 await page.evaluate(()=>{(window as any).pywebview={api:{choose_csv:async()=>null,desktop_runtime:async()=>({windows:false,startup_supported:false,tray_available:false,warning:null})}}});await page.getByRole('tab',{name:'About SAP Lens',exact:true}).click();await page.getByRole('tab',{name:'Features',exact:true}).click();await expect(page.getByRole('region',{name:'Windows Desktop background operation',exact:true})).toHaveCount(0)
})
