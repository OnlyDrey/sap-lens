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
 await expect(page.getByRole('dialog').getByRole('tab',{name:'Activities 3/3',exact:true})).toBeVisible();await page.getByRole('tab',{name:'Risks 2/2',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Acceptance pending');await expect(page.getByRole('dialog')).toContainText('Acceptance pending');await page.getByRole('button',{name:'Review method for R1',exact:true}).click();const method=page.getByRole('dialog',{name:'Review method for R1',exact:true});await expect(method).toContainText('Removal planned');await expect(method).toContainText('does not grant formal acceptance')
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`review coverage tabs ${theme} ${width}`,async({page,request},info)=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}});await page.setViewportSize({width,height:950});await openSod(page,'Reviews');await page.getByRole('button',{name:`Open review for ${names.a}`,exact:true}).click();const panel=page.getByRole('dialog');await expect(panel.getByRole('tab',{name:'Roles 0/4',exact:true})).toBeVisible();await panel.getByRole('tab',{name:'Roles 0/4',exact:true}).focus();await page.keyboard.press('ArrowRight');await expect(panel.getByRole('tab',{name:'Activities 0/3',exact:true})).toBeFocused();const trigger=panel.getByRole('button',{name:'Review method for A',exact:true});await trigger.focus();await page.keyboard.press('Enter');const popover=page.getByRole('dialog',{name:'Review method for A',exact:true});await expect(popover).toContainText('Not reviewed');const bounds=await popover.boundingBox();expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(width);await page.screenshot({path:info.outputPath(`review-tabs-${theme}-${width}.png`)});await page.keyboard.press('Escape');await expect(trigger).toBeFocused();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
})

test('role decisions update immediately and activity coverage never becomes implicit approval',async({page})=>{
 await openSod(page,'Reviews');await page.getByRole('button',{name:`Open review for ${names.a}`,exact:true}).click()
 const panel=page.getByRole('dialog'),roles=panel.getByRole('region',{name:'Role Assignment Review',exact:true})
 await panel.getByRole('textbox',{name:'Reviewer (self-reported)',exact:true}).fill('Synthetic status reviewer')
 const first=roles.getByRole('listitem').filter({hasText:'ROLE_A1'}),status=first.getByRole('button',{name:'Review method for ROLE_A1',exact:true})
 await expect(status).toHaveText('Not reviewed')
 for(const [action,label,tone] of [['Keep','Approved','success'],['Remove','Remove','error'],['Investigate','Investigate','warning']]){
  await first.getByRole('button',{name:`${action} ROLE_A1`,exact:true}).click();await expect(status).toHaveText(label);await expect(status.locator('.evidence-badge')).toHaveClass(new RegExp('evidence-'+tone))
 }
 await status.click();const popover=page.getByRole('dialog',{name:'Review method for ROLE_A1',exact:true});await expect(popover).toContainText(names.a);await expect(popover).toContainText('Synthetic status reviewer');await expect(popover).toContainText('Assignment ID');await expect(popover).toContainText('Explicit');await expect(popover).toContainText('Related activities');await page.keyboard.press('Escape')
 await first.getByRole('button',{name:'Keep ROLE_A1',exact:true}).click();await expect(status).toHaveText('Approved')
 const second=roles.getByRole('listitem').filter({hasText:'ROLE_A2'});await second.getByRole('button',{name:'Remove ROLE_A2',exact:true}).click();await expect(second.getByRole('button',{name:'Review method for ROLE_A2',exact:true})).toHaveText('Remove')
 await panel.getByRole('tab',{name:/^Activities/}).click();const activity=panel.getByRole('button',{name:'Review method for A',exact:true});await expect(activity).toHaveText('Mixed decisions');await activity.click();const detail=page.getByRole('dialog',{name:'Review method for A',exact:true});await expect(detail).toContainText('Supporting assignment decisions');await expect(detail).toContainText('Approved');await expect(detail).toContainText('Remove');await page.keyboard.press('Escape')
 await panel.getByRole('tab',{name:/^Risks/}).click();await expect(panel.getByRole('button',{name:'Review method for R1',exact:true})).toHaveText('Acceptance pending')
})

test('bulk Keep and Remove immediately show authoritative role statuses and independent acceptance',async({page})=>{
 await openSod(page,'Reviews')
 for(const action of ['Keep','Remove']){
  await page.getByRole('button',{name:'Bulk review',exact:true}).click();const preview=page.getByRole('dialog',{name:'Bulk role assignment review',exact:true})
  if(action==='Remove'){await preview.getByRole('checkbox',{name:'Include previously reviewed assignments',exact:true}).check();await preview.getByRole('combobox',{name:'Proposed decision',exact:true}).selectOption('Remove')}
  await preview.getByRole('button',{name:'Select all 5 matching assignments',exact:true}).click();await preview.getByRole('button',{name:'Continue to confirmation (5)',exact:true}).click()
  const confirm=page.getByRole('dialog',{name:action==='Keep'?'Keep assignments':'Recommend removal',exact:true})
  await confirm.getByRole('textbox',{name:'Reviewer',exact:true}).fill('Synthetic Bulk Reviewer');await confirm.getByRole('textbox',{name:'Rationale',exact:true}).fill('Synthetic decision-status validation')
  if(action==='Remove')await confirm.getByRole('checkbox',{name:/Replace the existing decisions/}).check()
  await confirm.getByRole('button',{name:action==='Keep'?'Keep 5 assignments':'Recommend removal for 5 assignments',exact:true}).click();await expect(confirm).toContainText('5 of 5 assignments saved');await confirm.getByRole('button',{name:'Done',exact:true}).click()
  await page.getByRole('button',{name:`Open review for ${names.a}`,exact:true}).click();const panel=page.getByRole('dialog'),roles=panel.getByRole('region',{name:'Role Assignment Review',exact:true})
  await expect(roles.getByRole('button',{name:/^Review method for/})).toHaveText(Array(4).fill(action==='Keep'?'Approved':'Remove'))
  await panel.getByRole('tab',{name:/^Risks/}).click();await expect(panel.getByRole('button',{name:/^Review method for R/})).toHaveText(['Acceptance pending','Acceptance pending'])
  await panel.getByRole('button',{name:'Close panel',exact:true}).click()
 }
})
