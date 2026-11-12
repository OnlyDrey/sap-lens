import {expect,type Locator} from '@playwright/test'
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
