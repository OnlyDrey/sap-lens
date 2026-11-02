import {test,expect} from '@playwright/test'
import {cleanup,seedGovernance,openSod,names,headers} from './sod-fixture'
let directory=''
test.beforeEach(async({request})=>{directory=await seedGovernance(request)})
test.afterEach(async({request})=>{await cleanup(request,directory)})
test('review saving shows immediate action feedback and preserves confirmed decisions',async({page},info)=>{
 await openSod(page,'Reviews');await page.getByRole('button',{name:`Open review for ${names.a}`,exact:true}).click()
 const panel=page.getByRole('dialog'),keep=panel.getByRole('button',{name:'Keep ROLE_B',exact:true}),remove=panel.getByRole('button',{name:'Remove ROLE_B',exact:true})
 await panel.getByRole('textbox',{name:'Reviewer (self-reported)',exact:true}).fill('Synthetic Performance Reviewer')
 let release:()=>void=()=>{};const gate=new Promise<void>(resolve=>{release=resolve})
 await page.route('**/api/sod/decisions/assignment',async route=>{await gate;await route.continue()})
 const gets:string[]=[];page.on('request',request=>{if(request.method()==='GET'&&request.url().includes('/api/sod/'))gets.push(new URL(request.url()).pathname)})
 const response=page.waitForResponse(response=>response.url().endsWith('/api/sod/decisions/assignment')&&response.request().method()==='POST')
 await keep.evaluate(element=>{
  element.addEventListener('click',()=>{
   element.dataset.started=String(performance.now())
   const observer=new MutationObserver(()=>{
    if(element.getAttribute('aria-busy')==='true'&&!element.dataset.pending)element.dataset.pending=String(performance.now())
    if(element.getAttribute('aria-pressed')==='true'){element.dataset.confirmed=String(performance.now());observer.disconnect()}
   });observer.observe(element,{attributes:true,attributeFilter:['aria-busy','aria-pressed']})
  },{once:true,capture:true})
 })
 const begin=Date.now();await keep.click();await expect(keep).toHaveAttribute('aria-busy','true')
 const feedback=Date.now()-begin,busy=await panel.getByRole('group',{name:'Decision for ROLE_B'}).locator('[aria-busy="true"]').count()
 expect(busy).toBe(1)
 await expect(keep.locator('svg')).toHaveCount(1) // spinner replaces, rather than accompanies, its normal icon
 await expect(remove).not.toHaveAttribute('aria-busy','true')
 await expect(remove).toBeDisabled();await expect(panel.getByRole('button',{name:'Keep ROLE_A1',exact:true})).toBeEnabled()
 await keep.evaluate(element=>{element.dataset.released=String(performance.now())})
 const released=Date.now();release();expect((await response).ok()).toBeTruthy();const api=Date.now()-released
 await expect(keep).toHaveAttribute('aria-pressed','true');await expect(keep).toBeEnabled();const confirmed=Date.now()-released
 await page.waitForLoadState('networkidle')
 const dom=await keep.evaluate(element=>({pending_ms:Number(element.dataset.pending)-Number(element.dataset.started),confirmed_after_release_ms:Number(element.dataset.confirmed)-Number(element.dataset.released)}))
 expect(gets.filter(path=>path==='/api/sod/filter-options')).toHaveLength(0)
 const measured={dom,feedback_ms:feedback,api_after_release_ms:api,confirmed_after_release_ms:confirmed,get_requests:gets.length,paths:gets}
 console.log('REVIEW_METRICS',JSON.stringify(measured));await info.attach('review-metrics',{body:JSON.stringify(measured),contentType:'application/json'})
})

test('failed decisions restore row controls and never claim a saved choice',async({page})=>{
 await openSod(page,'Reviews');await page.getByRole('button',{name:`Open review for ${names.a}`,exact:true}).click()
 const panel=page.getByRole('dialog'),keep=panel.getByRole('button',{name:'Keep ROLE_B',exact:true})
 await panel.getByRole('textbox',{name:'Reviewer (self-reported)',exact:true}).fill('Synthetic Reviewer')
 await page.route('**/api/sod/decisions/assignment',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Synthetic unavailable storage'})}))
 await keep.click();await expect(panel.getByRole('alert')).toContainText('was not saved');await expect(keep).toBeEnabled();await expect(keep).toHaveAttribute('aria-pressed','false');await expect(keep).not.toHaveAttribute('aria-busy','true')
 await page.unroute('**/api/sod/decisions/assignment');await keep.click();await expect(keep).toHaveAttribute('aria-pressed','true');await expect(keep).toBeEnabled()
})


test('a concurrent decision on the same assignment is not automatically overwritten',async({page,request})=>{
 await openSod(page,'Reviews');await page.getByRole('button',{name:`Open review for ${names.a}`,exact:true}).click()
 const panel=page.getByRole('dialog');await panel.getByRole('textbox',{name:'Reviewer (self-reported)',exact:true}).fill('Synthetic Local Reviewer')
 const subject=await(await request.get('/api/sod/subject',{headers,params:{user:names.a}})).json() as import('../src/api/sod').Subject
 const row=subject.overview.assignments.find(item=>item.role==='ROLE_B')!
 let posts=0
 await page.route('**/api/sod/decisions/assignment',async route=>{
  posts++
  if(posts===1){const competing=await request.post('/api/sod/decisions/assignment',{headers,data:{context:'current',expected_revision:subject.revision,expected_generation:subject.generation,items:[{key:row.id,user:names.a,ref:row.role,evidence_version:row.evidence_version}],decision:'Remove',reviewer:'Synthetic Concurrent Reviewer',justification:'Synthetic independent review'}});expect(competing.ok()).toBeTruthy()}
  await route.continue()
 })
 await panel.getByRole('button',{name:'Keep ROLE_B',exact:true}).click()
 await expect(panel.getByRole('alert')).toContainText('changed in another session')
 await expect(panel.getByRole('button',{name:'Remove ROLE_B',exact:true})).toHaveAttribute('aria-pressed','true')
 expect(posts).toBe(1)
 const history=await(await request.get('/api/sod/decisions/assignment/history',{headers,params:{context:'current',key:row.id}})).json()
 expect(history.items.map((item:{decision:string})=>item.decision)).toEqual(['Remove'])
})
