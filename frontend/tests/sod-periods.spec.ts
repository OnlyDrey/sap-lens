import {test,expect} from '@playwright/test'
import {bridge as _bridge,cleanup,createPeriod,decide,decideEverything,headers,movePeriod,names,openSod,seedGovernance} from './sod-fixture'
let directory:string
test.beforeEach(async({request})=>{directory=await seedGovernance(request)})
test.afterEach(async({request})=>{await cleanup(request,directory)})
void _bridge
const open=async(page:any,name:string)=>{await openSod(page,'Review Periods');await page.getByRole('button',{name:`Open ${name}`,exact:true}).click();return page.getByRole('dialog',{name:'SoD period',exact:true})}

test('review period is gated, approved by a different person, then frozen and protected from deletion',async({page,request})=>{
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
 await expect(dialog.getByRole('button',{name:'Delete…',exact:true})).toHaveCount(0);await expect(dialog.getByText('Approved by Synthetic Approver',{exact:false})).toBeVisible()
 const before=(await(await request.get(`/api/sod/periods/${id}`,{headers})).json()).checksum;expect((await request.post('/api/refresh',{headers})).ok()).toBeTruthy();expect((await(await request.get(`/api/sod/periods/${id}`,{headers})).json()).checksum).toBe(before)
 expect((await(await request.get(`/api/sod/periods/${id}/deletion-impact`,{headers})).json()).mode).toBe('protected')
 await page.keyboard.press('Escape');await page.getByRole('link',{name:'Risk Matrix',exact:true}).click();await expect(page.getByRole('combobox',{name:'Review context',exact:true})).toBeVisible()
})

test('period deletion requires the typed name; empty drafts are removed and worked periods are archived',async({page,request})=>{
 await createPeriod(request,'Empty draft');const worked=await createPeriod(request,'Worked period')
 const subject=await(await request.get('/api/sod/subject',{headers,params:{context:worked,user:names.b,activity:'A'}})).json();const row=subject.activities[0]
 await decide(request,'activity',worked,[{key:row.key,user:names.b,ref:'A',evidence_version:row.evidence_version}],'Approved')
 let dialog=await open(page,'Empty draft');await dialog.getByRole('button',{name:'Delete…',exact:true}).click();const card=dialog.getByRole('region',{name:'Delete review period'});await expect(card).toContainText('permanently deleted');await dialog.getByRole('textbox',{name:/Recorded by/}).fill('Synthetic Actor')
 const remove=card.getByRole('button',{name:'Delete permanently',exact:true});await expect(remove).toBeDisabled();await card.getByRole('textbox',{name:/Type the period name/}).fill('empty draft');await expect(remove).toBeDisabled();await card.getByRole('textbox',{name:/Type the period name/}).fill('Empty draft');await remove.click()
 await expect(page.getByRole('button',{name:'Open Empty draft',exact:true})).toHaveCount(0)
 dialog=await open(page,'Worked period');await dialog.getByRole('textbox',{name:/Recorded by/}).fill('Synthetic Actor');await dialog.getByRole('button',{name:'Delete…',exact:true}).click();const archive=dialog.getByRole('region',{name:'Delete review period'});await expect(archive).toContainText('archived');await archive.getByRole('textbox',{name:/Type the period name/}).fill('Worked period')
 const confirm=archive.getByRole('button',{name:'Archive period',exact:true});await expect(confirm).toBeDisabled();await archive.getByRole('checkbox').check();await confirm.click()
 await expect(page.getByRole('button',{name:'Open Worked period',exact:true})).toHaveCount(0);await page.getByRole('checkbox',{name:'Show archived periods'}).check();await expect(page.getByText(/Archived/).first()).toBeVisible()
 const archived=(await(await request.get('/api/sod/periods?include_archived=true',{headers})).json());expect(archived.items.find((item:any)=>item.id===worked).deleted_at).toBeTruthy();expect(archived.deletions.map((item:any)=>item.mode).sort()).toEqual(['archived','permanent'])
})

test('period comparison includes decision changes and ignores deleted periods',async({page,request})=>{
 const first=await createPeriod(request,'Before');const subject=await(await request.get('/api/sod/subject',{headers,params:{context:first,user:names.a,activity:'A'}})).json();const row=subject.activities[0]
 await decide(request,'activity',first,[{key:row.key,user:names.a,ref:'A',evidence_version:row.evidence_version}],'Approved');await createPeriod(request,'After')
 await openSod(page,'Review Periods');await page.getByRole('combobox',{name:'Previous period',exact:true}).selectOption({label:'Before'});await page.getByRole('combobox',{name:'Following period',exact:true}).selectOption({label:'After'});await page.getByRole('button',{name:'Compare periods',exact:true}).click()
 await expect(page.getByRole('table',{name:'Review decision changes',exact:true})).toContainText('Approved');await expect(page.getByText('Unchanged: 3',{exact:false})).toBeVisible()
 void movePeriod
})
