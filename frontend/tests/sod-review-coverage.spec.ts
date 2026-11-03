import {test,expect} from '@playwright/test'
import {cleanup,seedGovernance,openSod,names,headers,decide} from './sod-fixture'
test.setTimeout(45_000)
let directory=''
test.beforeEach(async({request})=>{directory=await seedGovernance(request)})
test.afterEach(async({request})=>{await cleanup(request,directory)})
test('review tabs preserve shared reviewer, unsaved input and match derived queue progress',async({page,request})=>{
 await openSod(page,'Reviews');await page.getByRole('button',{name:`Open review for ${names.a}`,exact:true}).click()
 const panel=page.getByRole('dialog');const tabs=panel.getByRole('tab');await expect(tabs).toHaveText(['Roles 0/4','Activities 0/3','Risks 0/2'])
 await panel.getByRole('textbox',{name:'Reviewer (self-reported)',exact:true}).fill('Synthetic Shared Reviewer')
 await panel.getByRole('tab',{name:/^Activities/}).click();await panel.getByRole('button',{name:'Review activity A',exact:true}).click();await panel.getByRole('textbox',{name:'Justification',exact:true}).fill('Unsaved synthetic rationale')
 await panel.getByRole('tab',{name:/^Roles/}).click();await expect(panel.getByRole('textbox',{name:'Justification',exact:true})).not.toBeVisible()
 await panel.getByRole('tab',{name:/^Activities/}).click();await expect(panel.getByRole('textbox',{name:'Justification',exact:true})).toHaveValue('Unsaved synthetic rationale');await expect(panel.getByRole('textbox',{name:'Reviewer (self-reported)',exact:true})).toHaveValue('Synthetic Shared Reviewer')
 await panel.getByRole('button',{name:'Cancel',exact:true}).click()
 const subject=await(await request.get('/api/sod/subject',{headers,params:{user:names.a}})).json()
 for(const row of subject.overview.assignments)await decide(request,'assignment','current',[{key:row.id,user:names.a,ref:row.role,evidence_version:row.evidence_version}],row.role==='ROLE_B'?'Remove':'Keep')
 await page.reload();await expect(page.getByRole('table',{name:'SoD review work queue'}).locator('tbody tr').filter({hasText:names.a})).toContainText('9/9')
 await expect(page.getByRole('dialog').getByRole('tab',{name:'Activities 3/3',exact:true})).toBeVisible();await page.getByRole('tab',{name:'Risks 2/2',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Formal acceptance');await expect(page.getByRole('dialog')).toContainText('Pending');await page.getByRole('button',{name:'Review method for R1',exact:true}).click();const method=page.getByRole('dialog',{name:'Review method for R1',exact:true});await expect(method).toContainText('Reviewed — removal planned');await expect(method).toContainText('Formal risk acceptance is independent')
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`review coverage tabs ${theme} ${width}`,async({page,request},info)=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}});await page.setViewportSize({width,height:950});await openSod(page,'Reviews');await page.getByRole('button',{name:`Open review for ${names.a}`,exact:true}).click();const panel=page.getByRole('dialog');await expect(panel.getByRole('tab',{name:'Roles 0/4',exact:true})).toBeVisible();await panel.getByRole('tab',{name:'Roles 0/4',exact:true}).focus();await page.keyboard.press('ArrowRight');await expect(panel.getByRole('tab',{name:'Activities 0/3',exact:true})).toBeFocused();await page.screenshot({path:info.outputPath(`review-tabs-${theme}-${width}.png`)});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
})
