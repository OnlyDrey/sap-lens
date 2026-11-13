import {expect,type APIRequestContext,type Locator} from '@playwright/test'
import {headers} from './support'

/** Review forms use the stable profile now; they do not accept per-action aliases.
 * Assert both the displayed identity and that the field cannot be edited. */
export async function expectReviewerProfile(field:Locator){
 const response=await field.page().request.get('/api/reviewer-profile',{headers})
 expect(response.ok()).toBe(true)
 const profile=await response.json()
 expect(profile.identity.id).toMatch(/^[a-f0-9]{32}$/)
 expect(profile.identity.provenance).toBe('desktop-local')
 await expect(field).toHaveValue(profile.identity.display_name)
 await expect(field).not.toBeEditable()
}

/** The name every review on this desktop is attributed to. A name a request submits is never used instead. */
export async function reviewerName(request:APIRequestContext){
 return (await(await request.get('/api/reviewer-profile',{headers})).json()).identity.display_name as string
}
/** Explicit profile edit, the only way the attributed name changes. The profile outlives a configuration reset, so a test that needs a name sets it. */
export async function setReviewerName(request:APIRequestContext,name:string){
 const current=await(await request.get('/api/reviewer-profile',{headers})).json()
 if(current.identity.display_name===name)return
 expect((await request.post('/api/reviewer-profile',{headers,data:{display_name:name,expected_revision:current.revision}})).ok()).toBeTruthy()
}
