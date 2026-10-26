import {expect,type Page} from '@playwright/test'
/** Inspect the actual modal evidence, then return to the source cards. */
export async function inspectTechnicalSources(page:Page) {
 for(const name of ['Role Catalogue CSV','User Access CSV','Employee Directory CSV']){
  const trigger=page.getByRole('region',{name,exact:true}).getByRole('button',{name:'Technical source details',exact:true})
  await trigger.click();const dialog=page.getByRole('dialog',{name:`${name} technical details`,exact:true})
  await expect(dialog.getByText('Configured file',{exact:true})).toBeVisible()
  await expect(dialog.getByText('Loaded source',{exact:true})).toBeVisible()
  await page.keyboard.press('Escape');await expect(trigger).toBeFocused()
 }
}
