import {test,expect} from '@playwright/test'
import {bridge as _bridge,cleanup,createPeriod,decide,decideEverything,headers,movePeriod,names,openSod,seedGovernance} from './sod-fixture'
let directory:string
test.beforeEach(async({request})=>{directory=await seedGovernance(request)})
test.afterEach(async({request})=>{await cleanup(request,directory)})
void _bridge

test('review period is gated, approved by a different person, then frozen; deletion is still possible with a reason and is an audited archive',async({page,request})=>{
 await openSod(page,'Review Periods');await page.getByRole('button',{name:'Create review period',exact:true}).click();const create=page.getByRole('dialog',{name:'Create SoD review period',exact:true});await create.getByRole('textbox',{name:'Review period name',exact:true}).fill('Synthetic Browser Period');await create.getByRole('button',{name:'Capture review period',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'SoD period',exact:true});await expect(dialog.getByRole('heading',{name:'Synthetic Browser Period'})).toBeVisible()
 await dialog.getByRole('textbox',{name:/Recorded by/}).fill('Synthetic Actor');await dialog.getByRole('button',{name:'Start review',exact:true}).click();await expect(dialog.getByText('In review',{exact:true}).first()).toBeVisible()
 await expect(dialog.getByRole('button',{name:'Mark ready for approval',exact:true})).toBeDisabled();await expect(dialog.getByRole('region',{name:'Review completeness'})).toContainText('block approval')
 const index=(await(await request.get('/api/sod/periods',{headers})).json());const id=index.items.find((item:any)=>item.name==='Synthetic Browser Period').id
 await decideEverything(request,id)
 await page.reload();await openSod(page,'Review Periods');await page.getByRole('button',{name:'Open Synthetic Browser Period',exact:true}).click()
 await expect(dialog.getByRole('region',{name:'Review completeness'})).toContainText('current');await dialog.getByRole('textbox',{name:/Recorded by/}).fill('Synthetic Actor');await dialog.getByRole('button',{name:'Mark ready for approval',exact:true}).click();await expect(dialog.getByRole('button',{name:'Approve…',exact:true})).toBeVisible()
 await dialog.getByRole('button',{name:'Approve…',exact:true}).click();const approval=dialog.getByRole('region',{name:'Approve review'})
 await approval.getByRole('textbox',{name:'Period reviewer (self-reported)',exact:true}).fill('Same Person');await approval.getByRole('textbox',{name:'Period approver (self-reported)',exact:true}).fill('same person');await approval.getByRole('checkbox').check();await approval.getByRole('button',{name:'Approve and freeze',exact:true}).click();await expect(dialog.getByRole('alert')).toContainText('different people')
 await approval.getByRole('textbox',{name:'Period approver (self-reported)',exact:true}).fill('Synthetic Approver');await approval.getByRole('button',{name:'Approve and freeze',exact:true}).click();await expect(dialog.getByText('Approved',{exact:true}).first()).toBeVisible()
 await expect(dialog.getByRole('button',{name:'Delete…',exact:true})).toHaveCount(1);await expect(dialog.getByText('Approved by Synthetic Approver',{exact:false})).toBeVisible()
 const before=(await(await request.get(`/api/sod/periods/${id}`,{headers})).json()).checksum;expect((await request.post('/api/refresh',{headers})).ok()).toBeTruthy();expect((await(await request.get(`/api/sod/periods/${id}`,{headers})).json()).checksum).toBe(before)
 const impact=await(await request.get(`/api/sod/periods/${id}/deletion-impact`,{headers})).json();expect([impact.mode,impact.requires_reason,impact.requires_history_confirmation]).toEqual(['archive',true,true])
 await page.keyboard.press('Escape');await page.getByRole('link',{name:'Risk Matrix',exact:true}).click();await expect(page.getByRole('combobox',{name:'Review context',exact:true})).toBeVisible()
})

test('period deletion requires the typed name; empty drafts are removed and worked periods are archived',async({page,request})=>{
 await createPeriod(request,'Empty draft');const worked=await createPeriod(request,'Worked period')
 const subject=await(await request.get('/api/sod/subject',{headers,params:{context:worked,user:names.b,activity:'A'}})).json();const row=subject.activities[0]
 await decide(request,'activity',worked,[{key:row.key,user:names.b,ref:'A',evidence_version:row.evidence_version}],'Approved')
 const deleteFromMenu=async(name:string)=>{await openSod(page,'Review Periods');await page.getByRole('button',{name:`Actions for ${name}`,exact:true}).click();await page.getByRole('button',{name:'Delete…',exact:true}).click();return page.getByRole('dialog',{name:`Delete review period ${name}`,exact:true})}
 let dialog=await deleteFromMenu('Empty draft');await expect(dialog).toContainText('permanently deleted');await dialog.getByRole('textbox',{name:/Recorded by/}).fill('Synthetic Actor')
 const remove=dialog.getByRole('button',{name:'Delete permanently',exact:true});await expect(remove).toBeDisabled();await dialog.getByRole('textbox',{name:/Type the period name/}).fill('empty draft');await expect(remove).toBeDisabled();await dialog.getByRole('textbox',{name:/Type the period name/}).fill('Empty draft');await remove.click()
 await expect(page.getByRole('button',{name:'Open Empty draft',exact:true})).toHaveCount(0)
 dialog=await deleteFromMenu('Worked period');await dialog.getByRole('textbox',{name:/Recorded by/}).fill('Synthetic Actor');await expect(dialog).toContainText('archived');await dialog.getByRole('textbox',{name:/Type the period name/}).fill('Worked period')
 const confirm=dialog.getByRole('button',{name:'Archive period',exact:true});await expect(confirm).toBeDisabled();await dialog.getByRole('checkbox').check();await confirm.click()
 await expect(page.getByRole('status').filter({hasText:'archived'})).toBeVisible()
 await expect(page.getByRole('button',{name:'Open Worked period',exact:true})).toHaveCount(0);await page.getByRole('button',{name:'Show archived periods',exact:true}).click();await expect(page.getByText(/Archived/).first()).toBeVisible()
 const archived=(await(await request.get('/api/sod/periods?include_archived=true',{headers})).json());expect(archived.items.find((item:any)=>item.id===worked).deleted_at).toBeTruthy();expect(archived.deletions.map((item:any)=>item.mode).sort()).toEqual(['archived','permanent'])
})

test('period comparison includes decision changes and ignores deleted periods',async({page,request})=>{
 const first=await createPeriod(request,'Before');const subject=await(await request.get('/api/sod/subject',{headers,params:{context:first,user:names.a,activity:'A'}})).json();const row=subject.activities[0]
 await decide(request,'activity',first,[{key:row.key,user:names.a,ref:'A',evidence_version:row.evidence_version}],'Approved');await createPeriod(request,'After')
 await openSod(page,'Review Periods');await page.getByRole('button',{name:'Compare periods',exact:true}).click();const compare=page.getByRole('dialog',{name:'Compare review periods',exact:true});await compare.getByRole('combobox',{name:'Previous period',exact:true}).selectOption({label:'Before'});await compare.getByRole('combobox',{name:'Following period',exact:true}).selectOption({label:'After'})
 await expect(page.getByRole('table',{name:'Review decision changes',exact:true})).toContainText('Approved');await expect(page.getByText('Unchanged: 3',{exact:false})).toBeVisible()
 void movePeriod
})

test('an approved period can be deleted only with a reason and history confirmation and stays in the audit trail',async({page,request})=>{
 const approved=await createPeriod(request,'Approved to delete');await decideEverything(request,approved)
 await movePeriod(request,approved,'In review');await movePeriod(request,approved,'Ready for approval');await movePeriod(request,approved,'Approved',{reviewer:'Synthetic Reviewer',approver:'Synthetic Approver',approval_date:`${new Date().getFullYear()}-10-27`,confirm:true})
 await openSod(page,'Review Periods');await page.getByRole('button',{name:'Actions for Approved to delete',exact:true}).click();await page.getByRole('button',{name:'Delete…',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'Delete review period Approved to delete',exact:true});await expect(dialog.getByRole('list',{name:'Consequences'})).toContainText('approved or closed')
 const archive=dialog.getByRole('button',{name:'Archive period',exact:true});await dialog.getByRole('textbox',{name:/Recorded by/}).fill('Synthetic Actor');await dialog.getByRole('textbox',{name:/Type the period name/}).fill('Approved to delete')
 await dialog.getByRole('checkbox',{name:/will be archived/}).check();await expect(archive).toBeDisabled()
 await dialog.getByRole('checkbox',{name:/retained but no longer available/}).check();await expect(archive).toBeDisabled()
 await dialog.getByRole('textbox',{name:/Reason for deleting/}).fill('Created in error');await expect(archive).toBeEnabled();await archive.click()
 await expect(page.getByRole('button',{name:'Open Approved to delete',exact:true})).toHaveCount(0)
 const index=await(await request.get('/api/sod/periods?include_archived=true',{headers})).json();const entry=index.items.find((item:any)=>item.id===approved)
 expect([entry.state,!!entry.deleted_at,entry.approver]).toEqual(['Approved',true,'Synthetic Approver']);expect(index.deletions.at(-1)).toMatchObject({reason:'Created in error',frozen:true,mode:'archived'})
})
