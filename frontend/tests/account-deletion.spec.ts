import {test,expect,type Page} from '@playwright/test'
import {openSettings} from './support'

const keeper={id:'keeper-id',username:'keeper',display_name:'Keeper',role:'administrator',enabled:true,revision:2,last_login:null}
const temporary={id:'temporary-id',username:'temporary',display_name:'Temporary',role:'reviewer',enabled:true,revision:7,last_login:null}
async function fixture(page:Page,fail=false){
 let users=[keeper,temporary],deletes=0
 await page.route('**/api/auth/state',route=>route.fulfill({json:{provider:'local-sessions',setup_required:false}}))
 await page.route('**/api/auth/me',route=>route.fulfill({json:keeper}))
 await page.route('**/api/auth/migration',route=>route.fulfill({json:{items:[]}}))
 await page.route('**/api/auth/audit',route=>route.fulfill({json:{items:deletes&&!fail?[{id:'audit-delete',at:1795200000,actor:JSON.stringify({id:'temporary-id',provenance:'deleted-account'}),operation:'user.delete',target:'temporary-id'}]:[]}}))
 await page.route('**/api/auth/users**',async route=>{
  if(route.request().method()==='DELETE'){
   deletes++
   expect(route.request().url()).toMatch(/\/api\/auth\/users\/temporary-id$/)
   expect(route.request().postDataJSON()).toEqual({expected_revision:7,confirm_username:'temporary',confirm:true})
   if(fail)return route.fulfill({status:409,json:{detail:'stale_user',code:'stale_user'}})
   users=users.filter(user=>user.id!=='temporary-id');return route.fulfill({json:{ok:true}})
  }
  return route.fulfill({json:{items:users}})
 })
 await openSettings(page,'User Management')
 await expect(page.getByRole('heading',{name:'User Management',exact:true,level:2})).toBeVisible()
 return ()=>deletes
}

test('permanent deletion requires confirmation, preserves cancellation and refreshes accounts/audit @component',async({page})=>{
 const deletes=await fixture(page)
 await page.getByRole('button',{name:'Actions for keeper',exact:true}).click()
 await expect(page.getByRole('button',{name:/^Delete account You cannot delete your own account$/})).toBeDisabled()
 await page.keyboard.press('Escape')
 const open=async()=>{await page.getByRole('button',{name:'Actions for temporary',exact:true}).click();await page.getByRole('button',{name:/^Delete account Permanently remove account and sign-in secrets$/}).click()}
 await open()
 const dialog=page.getByRole('dialog',{name:'Permanently delete temporary?',exact:true})
 await expect(dialog).toContainText('Historical review evidence and existing backups are preserved')
 await dialog.getByRole('button',{name:'Cancel',exact:true}).click();expect(deletes()).toBe(0)
 await expect(page.getByRole('button',{name:'Actions for temporary',exact:true})).toBeVisible()
 await open();await page.keyboard.press('Escape');expect(deletes()).toBe(0)
 await open();await dialog.getByRole('button',{name:'Delete account',exact:true}).focus();await page.keyboard.press('Enter')
 await expect(page.getByRole('button',{name:'Actions for temporary',exact:true})).toHaveCount(0)
 await expect(page.getByRole('button',{name:'Actions for keeper',exact:true})).toBeVisible()
 await expect(page.getByText('Account temporary permanently deleted.',{exact:true})).toBeVisible()
 await expect(page.getByText('Deleted account (temporary-id)',{exact:true})).toBeVisible()
 expect(deletes()).toBe(1)
})

test('stale deletion keeps the account and reports refusal without success @component',async({page})=>{
 const deletes=await fixture(page,true)
 await page.getByRole('button',{name:'Actions for temporary',exact:true}).click();await page.getByRole('button',{name:/^Delete account Permanently remove account and sign-in secrets$/}).click()
 await page.getByRole('dialog',{name:'Permanently delete temporary?',exact:true}).getByRole('button',{name:'Delete account',exact:true}).click()
 await expect(page.getByRole('alert').filter({hasText:/account changed|stale_user/})).toBeVisible()
 await expect(page.getByRole('button',{name:'Actions for temporary',exact:true})).toBeVisible()
 await expect(page.getByText('Account temporary permanently deleted.',{exact:true})).toHaveCount(0)
 expect(deletes()).toBe(1)
})

test('mobile account deletion dialog fits and Escape leaves account intact @component',async({page})=>{
 await page.setViewportSize({width:390,height:844});const deletes=await fixture(page)
 await page.getByRole('button',{name:'Actions for temporary',exact:true}).click();await page.getByRole('button',{name:/^Delete account Permanently remove account and sign-in secrets$/}).click()
 const dialog=page.getByRole('dialog',{name:'Permanently delete temporary?',exact:true});await expect(dialog).toBeVisible()
 const box=(await dialog.boundingBox())!;expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(390)
 await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);expect(deletes()).toBe(0)
})
