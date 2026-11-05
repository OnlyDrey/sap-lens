import {test,expect} from '@playwright/test'
import {seedGovernance,cleanup,matrix} from './sod-fixture'
let directory=''
// Reset preserves catalogue edits, so this test saves under risk IDs no other spec uses.
let risk=''
test.beforeEach(async({request},info)=>{risk=`RCV${info.workerIndex}${info.repeatEachIndex}${info.title.includes('network')?'N':'S'}`;directory=await seedGovernance(request,'static',matrix.replace(/\bR1\b/g,risk))})
test.afterEach(async({request})=>{await cleanup(request,directory)})
for(const failure of ['server','network'])test(`configuration save errors preserve the ${failure} draft and recover without restart`,async({page})=>{
 const draft=`Synthetic retained ${failure} draft`
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'SoD Risk Configuration',exact:true}).click()
 await page.getByRole('button',{name:`Edit SoD risk ${risk}`,exact:true}).click();const dialog=page.getByRole('dialog',{name:`SoD risk ${risk}`,exact:true})
 await dialog.getByRole('textbox',{name:'Display name',exact:true}).fill(draft)
 await page.route(`**/api/sod/catalogue/${risk}`,route=>failure==='network'?route.abort('connectionrefused'):route.fulfill({status:500,contentType:'application/json',headers:{'X-Request-ID':'a'.repeat(32)},body:JSON.stringify({detail:'Synthetic recoverable storage failure'})}))
 await dialog.getByRole('button',{name:'Save changes',exact:true}).click();await expect(dialog.getByRole('alert')).toContainText(failure==='server'?'Reference: '+ 'a'.repeat(32):'could not connect')
 await expect(dialog.getByRole('textbox',{name:'Display name',exact:true})).toHaveValue(draft)
 await page.unroute(`**/api/sod/catalogue/${risk}`);await dialog.getByRole('button',{name:'Save changes',exact:true}).click();await expect(dialog).toBeHidden();await expect(page.getByRole('table',{name:'SoD risk configurations'})).toContainText(draft)
})
