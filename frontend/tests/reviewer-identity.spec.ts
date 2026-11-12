import {test,expect} from '@playwright/test'
import {seedGovernance,cleanup,names,headers,openSod} from './sod-fixture'
let directory=''
test.beforeEach(async({request})=>{directory=await seedGovernance(request)})
test.afterEach(async({request})=>{await cleanup(request,directory)})
test('Desktop reviewer profile is stable and decisions retain the acting identity @workflow',async({page,request})=>{
 const original=await(await request.get('/api/reviewer-profile',{headers})).json()
 await openSod(page,'Risk Matrix')
 await page.getByRole('button',{name:'Reviewer profile',exact:true}).click()
 const profile=page.getByRole('dialog',{name:'Local reviewer profile',exact:true})
 await profile.getByLabel('Reviewer display name').fill('Synthetic stable reviewer')
 await profile.getByRole('button',{name:'Save reviewer profile'}).click()
 await expect(profile).toHaveCount(0)
 const current=await(await request.get('/api/reviewer-profile',{headers})).json()
 expect(current.identity.id).toBe(original.identity.id)
 expect(current.identity.provenance).toBe('desktop-local')
 const response=await(await request.get('/api/sod/subject',{headers,params:{user:names.a,risk:'R1'}})).json()
 const assignment=response.overview.assignments.find((row:{role:string})=>row.role==='ROLE_A1')
 // A malicious/obsolete client label cannot replace the stable local attribution.
 const decision=await request.post('/api/sod/decisions/assignment',{headers,data:{context:'current',expected_revision:response.revision,expected_generation:response.generation,items:[{key:assignment.id,user:names.a,ref:assignment.role,evidence_version:assignment.evidence_version}],decision:'Keep',reviewer:'Forged reviewer',justification:'Synthetic explicit review'}})
 expect(decision.ok()).toBe(true)
 const event=(await decision.json()).events[0]
 expect(event.reviewer).toBe('Synthetic stable reviewer')
 expect(event.actor_identity).toEqual(current.identity)
 const next=await request.post('/api/reviewer-profile',{headers,data:{display_name:'Renamed local reviewer',expected_revision:current.revision}})
 expect(next.ok()).toBe(true)
 const history=await(await request.get('/api/sod/decisions/assignment/history',{headers,params:{key:assignment.id}})).json()
 expect(history.items[0]).toEqual(event)
 await page.reload()
 await page.getByRole('button',{name:'Reviewer profile',exact:true}).click()
 await expect(page.getByLabel('Reviewer display name')).toHaveValue('Renamed local reviewer')
 expect((await(await request.get('/api/reviewer-profile',{headers})).json()).identity.id).toBe(original.identity.id)
})
