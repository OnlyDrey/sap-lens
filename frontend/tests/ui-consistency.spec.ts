import {test,expect} from '@playwright/test'
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import { headers } from './support'
let directory:string
const areas=['MM','FI','SD','BC','PP','QM','PM']
test.beforeEach(async({request})=>{
 await request.post('/api/configuration/reset',{headers})
 directory=mkdtempSync(path.join(tmpdir(),'sap-lens-consistency-'))
 const roles=path.join(directory,'roles.csv'),users=path.join(directory,'users.csv')
 writeFileSync(roles,'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE\n'+areas.map((area,index)=>`${area},ZC:SYN:${area},Synthetic ${area},ZS:SYN:${area},Synthetic component ${area},SYN${index}\n`).join(''))
 writeFileSync(users,'USERNAME,ROLE_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO,USER_LOCKED\nSYN_VIEW,ZC:SYN:MM,synthetic@example.test,20000101,99991231,20000101,99991231,0\n')
 const settings=(await(await request.get('/api/configuration',{headers})).json()).settings
 settings.data_csv_path=roles;settings.user_csv_path=users
 expect((await request.post('/api/configuration',{headers,data:settings})).ok()).toBeTruthy()
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(directory,{recursive:true,force:true})})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`consistent interactions previews and library ${theme} ${width}`,async({page,request},info)=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}})
 await page.setViewportSize({width,height:950});await page.goto('/#session=browser-test-session')
 const distribution=page.getByRole('region',{name:'Role Distribution',exact:true})
 await expect(distribution.getByRole('button',{name:/Investigate .* catalogue roles/})).toHaveCount(5)
 const row=distribution.getByRole('button',{name:/Investigate .* catalogue roles/}).first();await row.scrollIntoViewIfNeeded();const before=(await row.boundingBox())!
 await row.hover();const after=(await row.boundingBox())!;expect(after.y).toBe(before.y);expect(after.height).toBe(before.height)
 const showAll=distribution.getByRole('button',{name:/^Show all \d+ areas$/});await showAll.click()
 const all=page.getByRole('dialog',{name:'Role Distribution by SAP area',exact:true});await expect(all.getByRole('button',{name:/Investigate .* catalogue roles/})).toHaveCount(7)
 await page.keyboard.press('Escape');await expect(all).toHaveCount(0);await expect(distribution.getByRole('button',{name:/Investigate .* catalogue roles/})).toHaveCount(5)
 for(const band of ['0–5','6–10','11–20','21–30','31+'])await expect(page.getByRole('button',{name:`Investigate users with ${band} currently valid roles`,exact:true})).toBeVisible()
 const last=await page.locator('.dashboard-cards > :last-child').getAttribute('aria-label');expect(last).toBe('Data Sources & Configuration')
 await page.screenshot({path:info.outputPath(`dashboard-${theme}-${width}.png`),fullPage:true})
 await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('link',{name:'User Access',exact:true}).click()
 const link=page.getByRole('navigation',{name:'User Access view',exact:true}).getByRole('link',{name:'User directory',exact:true}),box=(await link.boundingBox())!
 await link.hover();await expect(link).toHaveCSS('text-decoration-line','none');await expect(link).toHaveCSS('border-top-width','0px');expect((await link.boundingBox())!.height).toBe(box.height)
 await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Organization & SAP System',exact:true}).click()
 await page.getByLabel('Organization name',{exact:true}).fill('Synthetic preview organization')
 await page.getByRole('tab',{name:'Appearance & Branding',exact:true}).click()
 const preview=page.getByLabel('Theme live preview',{exact:true});await expect(preview).toContainText('Synthetic preview organization');await expect(preview.getByAltText('Header logo preview')).toBeVisible()
 const content=(await page.locator('.settings-content').boundingBox())!,previewBox=(await preview.boundingBox())!;expect(previewBox.width/content.width).toBeGreaterThan(.65)
 expect((await(await request.get('/api/configuration',{headers})).json()).settings.organization.name).not.toBe('Synthetic preview organization')
 await page.screenshot({path:info.outputPath(`appearance-${theme}-${width}.png`)})
 await page.getByRole('tab',{name:'Component Library',exact:true}).click()
 const tabs=page.getByRole('tablist',{name:'Component categories',exact:true});await expect(tabs.getByRole('tab').first()).toHaveText('All components');await expect(tabs.getByRole('tab').first()).toHaveAttribute('aria-selected','true')
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 const library=page.getByLabel('Component Library previews',{exact:true});expect(await library.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBeTruthy()
 await page.screenshot({path:info.outputPath(`library-${theme}-${width}.png`)})
})
