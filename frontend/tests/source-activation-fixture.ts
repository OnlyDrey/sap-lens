import {expect,type Page} from '@playwright/test'
/** A deliberate user selection; waits for committed activation, never a fixed delay. */
export async function activateCSV(page:Page,source:'roles'|'users'|'employees',file:string){
 const label=source==='roles'?'CSV file location':source==='users'?'User CSV file location':'Employee Directory CSV location'
 const field=page.getByLabel(label,{exact:true});await field.fill(file)
 const [response]=await Promise.all([page.waitForResponse(result=>result.url().endsWith(`/api/data-sources/${source}/select`)&&result.request().method()==='POST'),field.press('Enter')])
 expect(response.ok(),await response.text()).toBeTruthy()
 const name=source==='roles'?'Role Catalogue':source==='users'?'User Access':'Employee Directory'
 await expect(page.getByRole('region',{name:`${name} source management`,exact:true}).getByRole('status').filter({hasText:'Completed ·'})).toBeVisible()
}
