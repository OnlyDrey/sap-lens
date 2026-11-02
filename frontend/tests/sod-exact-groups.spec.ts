import {test,expect} from '@playwright/test'
import {writeFileSync} from 'node:fs'
import path from 'node:path'
import {cleanup,seedGovernance,openSod,headers} from './sod-fixture'
let directory=''
const groups=['SYN-GROUP','SYN-GROUP-ONE','SYN-GROUP-TWO','SYN-GROUP-THREE']
test.beforeEach(async({request})=>{
 directory=await seedGovernance(request)
 const file=path.join(directory,'users.csv');writeFileSync(file,'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n'+groups.map((group,i)=>`SYN_FILTER_${i},ROLE_AB,${group},20000101,99991231`).join('\n')+'\n')
 const config=(await(await request.get('/api/configuration',{headers})).json()).settings;expect((await request.post('/api/data-sources/users/select',{headers,data:{path:file,revision:config.revision,mode:'static'}})).ok()).toBeTruthy()
})
test.afterEach(async({request})=>{await cleanup(request,directory)})
test('exact group selections stay independent, Select All is scoped, and Clear preserves other filters',async({page})=>{
 await openSod(page,'Reviews');const table=page.getByRole('table',{name:'SoD review work queue',exact:true});const box=page.getByRole('combobox',{name:'SAP User Group',exact:true});await box.click()
 await page.getByRole('option',{name:groups[0],exact:true}).click();await expect(table.locator('tbody tr')).toHaveCount(1);await expect(table).toContainText('SYN_FILTER_0')
 await expect(page.getByRole('listbox',{name:'SAP User Group options'})).toBeVisible();await expect(page.getByRole('option',{name:groups[1],exact:true})).toHaveAttribute('aria-selected','false')
 await page.getByRole('option',{name:groups[1],exact:true}).click();await expect(table.locator('tbody tr')).toHaveCount(2);await box.press('Escape');await box.click();await expect(page.getByRole('option',{name:groups[0],exact:true})).toHaveAttribute('aria-selected','true')
 await page.getByRole('button',{name:'Clear selection',exact:true}).click();await box.fill('THREE');await page.getByRole('button',{name:/^Select all 1 matching/}).click();await expect(table.locator('tbody tr')).toHaveCount(1);await expect(table).toContainText('SYN_FILTER_3');await box.press('Escape')
 await page.reload();await expect(table.locator('tbody tr')).toHaveCount(1);await expect(table).toContainText('SYN_FILTER_3')
 await page.locator('div.saved-filter-toolbar[aria-label="sod_queue saved filters"]').getByRole('button',{name:/Saved filters/}).click();const menu=page.getByRole('dialog',{name:'sod_queue saved filters',exact:true});await menu.getByLabel('Saved filter name',{exact:true}).fill('Synthetic exact group selection');await menu.getByRole('button',{name:'Save as new',exact:true}).click();await expect(menu).toContainText('Saved filters updated.');await page.keyboard.press('Escape')
 await box.click();await page.getByRole('button',{name:'Clear selection',exact:true}).click();await box.press('Escape');await expect(table.locator('tbody tr')).toHaveCount(4)
 await page.locator('div.saved-filter-toolbar[aria-label="sod_queue saved filters"]').getByRole('button',{name:/Saved filters/}).click();const saved=menu.getByRole('combobox',{name:'Saved filter',exact:true});await saved.click();await saved.fill('Synthetic exact group selection');await page.getByRole('option').filter({hasText:'Synthetic exact group selection'}).first().click();await menu.getByRole('button',{name:'Load',exact:true}).click();await page.keyboard.press('Escape');await expect(table.locator('tbody tr')).toHaveCount(1);await expect(table).toContainText('SYN_FILTER_3')

})
test('queue header sorting persists through review and user navigation; username copy stays independent',async({page})=>{
 await openSod(page,'Reviews');const table=page.getByRole('table',{name:'SoD review work queue',exact:true});await table.getByRole('button',{name:'Sort by SAP user',exact:true}).click();await expect(table.locator('tbody tr').first()).toContainText('SYN_FILTER_0');await table.getByRole('button',{name:'Sort by SAP user',exact:true}).click();await expect(table.locator('tbody tr').first()).toContainText('SYN_FILTER_3');await expect(table.getByRole('columnheader',{name:/SAP user/}).first()).toHaveAttribute('aria-sort','descending')
 await page.getByRole('button',{name:'Open review for SYN_FILTER_3',exact:true}).click();await page.getByRole('button',{name:'Close panel',exact:true}).click();await expect(table.locator('tbody tr').first()).toContainText('SYN_FILTER_3')
 const before=page.url();await page.context().grantPermissions(['clipboard-read','clipboard-write']);await table.locator('tbody tr').first().getByRole('button',{name:'Copy SAP username SYN_FILTER_3',exact:true}).click();expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe('SYN_FILTER_3');expect(page.url()).toBe(before)
 const link=table.locator('tbody tr').first().getByRole('link',{name:'Open SAP user SYN_FILTER_3',exact:true});await expect(link).toHaveAttribute('href',/SYN_FILTER_3/);await link.click();await expect(page).toHaveURL(/SYN_FILTER_3/);await page.goBack();await expect(table.locator('tbody tr').first()).toContainText('SYN_FILTER_3')
})
