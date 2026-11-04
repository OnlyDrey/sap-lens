import {test,expect} from '@playwright/test'
import {cleanup,seedGovernance,openSod,headers} from './sod-fixture'
let directory=''
test.beforeEach(async({request})=>{directory=await seedGovernance(request)})
test.afterEach(async({request})=>{await cleanup(request,directory)})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`Work Queue bulk review ${theme} ${width}`,async({page,request},info)=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}})
 await page.setViewportSize({width,height:1000});await openSod(page,'Reviews')
 const queue=page.getByRole('table',{name:'SoD review work queue',exact:true})
 await expect(queue.locator('thead th')).toHaveText(['SAP user','SAP User Group','Progress','Activities','Role assignments','Risk access review','Formal acceptance','Open'])
 await expect(queue).not.toContainText('removal recommended')
 await expect(page.getByRole('button',{name:/^Removal recommended/})).toBeVisible()
 if(width>=1280){const action=queue.getByRole('button',{name:/^Open review for/}).first();const bounds=await action.boundingBox();expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(width)}
 const trigger=page.getByRole('button',{name:'Bulk review',exact:true});await trigger.click()
 const panel=page.getByRole('region',{name:'Bulk role assignment review',exact:true})
 await expect(panel.getByRole('table',{name:'Bulk assignment preview'}).locator('tbody tr')).toHaveCount(6)
 const selectAll=panel.getByRole('checkbox',{name:'Select eligible assignments on current page',exact:true});await selectAll.check()
 await expect(panel.getByRole('button',{name:'Review 6 assignments'})).toBeEnabled()
 const bounds=await panel.boundingBox();expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(width)
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await page.screenshot({path:info.outputPath(`queue-bulk-${theme}-${width}.png`)})
 await page.getByRole('tab',{name:'Work queue',exact:true}).click();await expect(panel).toBeHidden();await expect(trigger).toBeVisible()
})

test('Dashboard and Work Queue agree after bulk role assessment without formal risk acceptance',async({page,request})=>{
 const selection=await(await request.get('/api/sod/explorer/access_list/selection',{headers,params:{assignment_scope:'all'}})).json() as import('../src/api/sod').AssignmentSelection
 const result=await request.post('/api/sod/decisions/assignment/bulk',{headers,data:{context:'current',expected_revision:selection.revision,expected_generation:selection.generation,items:selection.items.map(({key,user,ref,evidence_version})=>({key,user,ref,evidence_version})),action:'Keep',atomic:true,reviewer:'Synthetic Reviewer',justification:'Synthetic full assignment assessment'}})
 expect(result.ok()).toBeTruthy()
 await page.goto('/#session=browser-test-session');await page.getByRole('link',{name:'Dashboard',exact:true}).click()
 const metric=page.getByRole('button',{name:'SoD reviews pending',exact:true});await expect(metric.locator('strong')).toHaveText('0')
 const overview=await(await request.get('/api/sod/overview',{headers})).json();expect(overview.governance.acceptance.Pending).toBe(3)
 await metric.click();const queue=page.getByRole('table',{name:'SoD review work queue',exact:true});await expect(queue).toContainText('9/9');await expect(queue).toContainText('4/4')
})
