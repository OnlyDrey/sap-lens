import { test, expect } from '@playwright/test'
import { spawn,execFileSync } from 'node:child_process'
import { observeTestServer, stopTestServer, removeTestServerDirectory, type OwnedTestServer } from './server-process'
import { PYTHON } from './python'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync,existsSync,readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createServer, type AddressInfo } from 'node:net'
import { layoutMatrix } from './matrix'

// A real headless server, separate from the desktop-capability browser fixture.
let server:OwnedTestServer, root:string
let origin:string
const password='synthetic-browser-server-'+ 'a'.repeat(40)
let legacyAccounts:Buffer
async function contextFor(browser:import('@playwright/test').Browser,width:number,height:number){
 const context=await browser.newContext({viewport:{width,height}})
 const response=await context.request.post(origin+'/api/auth/login',{headers:{'X-SAP-Lens':'1'},data:{username:'admin',password}})
 expect(response.ok()).toBeTruthy()
 const csrf=(await context.cookies(origin)).find(cookie=>cookie.name==='sap-lens-csrf')?.value
 expect(csrf).toBeTruthy();await context.setExtraHTTPHeaders({'X-SAP-Lens-CSRF':csrf!})
 return context
}
test.beforeAll(async()=>{
  const reservation=createServer()
  await new Promise<void>(resolve=>reservation.listen(0,'127.0.0.1',resolve))
  const port=(reservation.address() as AddressInfo).port
  await new Promise<void>((resolve,reject)=>reservation.close(error=>error?reject(error):resolve()))
  origin=`http://127.0.0.1:${port}`
  root=mkdtempSync(path.join(tmpdir(),'sap-lens-server-'))
  mkdirSync(path.join(root,'sources'))
  writeFileSync(path.join(root,'access.secret'),password,{mode:0o600})
  execFileSync(PYTHON,['-c',`import json,sys,os;from pathlib import Path;sys.path.insert(0,str(Path('../backend').resolve()));from server_access import manage_user;from config_models import AppConfig;import backup_crypto;import windows_identity;p=json.load(sys.stdin);root=Path(p['root']);windows_identity.make_private(root,True) if os.name=='nt' else None;data=root/'data';data.mkdir();(data/'settings.json').write_text(AppConfig().model_dump_json(),encoding='utf8');manage_user(root/'legacy-users.json',dict(username='admin',password=p['password'],role='administrator',enabled=True));backup_crypto.create_key(root/'backup.key',data)`],{input:JSON.stringify({root,password}),timeout:20000})
  legacyAccounts=readFileSync(path.join(root,'legacy-users.json'))
  server=observeTestServer(spawn(PYTHON,['../backend/server.py'],{env:{...globalThis.process.env,
    SAP_LENS_DEPLOYMENT_MODE:'server',SAP_LENS_DATA_DIR:path.join(root,'data'),SAP_LENS_CONFIG_DIR:path.join(root,'data'),
    SAP_LENS_SOURCE_DIR:path.join(root,'sources'),SAP_LENS_PORT:String(port),SAP_LENS_HOST:'127.0.0.1',
    SAP_LENS_PUBLIC_ORIGIN:origin,SAP_LENS_ALLOWED_HOSTS:'127.0.0.1',SAP_LENS_AUTH:'users',SAP_LENS_USERS_FILE:path.join(root,'legacy-users.json'),SAP_LENS_BACKUP_KEY_FILE:path.join(root,'backup.key'),
    SAP_LENS_AUTH_SECRET_FILE:path.join(root,'access.secret'),SAP_LENS_TRUSTED_PROXIES:''},stdio:'ignore',detached:globalThis.process.platform!=='win32',windowsHide:true}))
  await expect.poll(async()=>{if(server.startupError())throw server.startupError();try{return (await fetch(origin+'/health/ready')).status}catch{return 0}},{timeout:10000}).toBe(200)
})
test.afterAll(async()=>{
  try {
    if(server)await stopTestServer(server)
    if(root)await removeTestServerDirectory(root)
  } catch(error) {
    throw new Error(`Test server cleanup failed; temporary directory retained: ${root}`, {cause:error})
  }
})
for (const { theme, width } of layoutMatrix([375,800,1280])){
  test(`headless browser automatic upload and download ${theme} ${width}`,{ tag: '@visual' }, async({browser},testInfo)=>{
    const context=await contextFor(browser,width,900)
    const page=await context.newPage()
    try{
      const config=(await(await context.request.get(origin+'/api/configuration')).json()).settings
      config.theme=theme
      expect((await context.request.post(origin+'/api/configuration',{headers:{'X-SAP-Lens':'1'},data:config})).ok()).toBeTruthy()
      await page.goto(origin)
      await page.getByRole('button',{name:'Open settings',exact:true}).click()
      await page.getByRole('tab',{name:'Data Sources',exact:true}).click()
      const upload=page.getByLabel('Upload Role Catalogue CSV', {exact:true})
      await upload.setInputFiles({name:'Catalogue ø.csv',mimeType:'text/csv',buffer:Buffer.from('FUNCTION_KEY,AGR_NAME,TEXT,TCODE\nMM,ZC:DEMO,Synthetic catalogue,MIGO\n')})
      await expect(page.getByRole('status').filter({hasText:'source records from Catalogue ø.csv'})).toBeVisible()
      // Browser selection activates the validated private Static snapshot immediately.
      const source=page.getByRole('region',{name:'Role Catalogue browser upload'})
      await expect(source).toBeVisible()
      await expect(page.getByRole('combobox',{name:'CSV source mode',exact:true})).toHaveValue('static')
      await source.scrollIntoViewIfNeeded()
      await page.screenshot({path:testInfo.outputPath(`server-${theme}-${width}.png`)})
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
      const active=(await(await context.request.get(origin+'/api/configuration')).json()).settings
      // Use the path produced by the actual upload field, not a client filesystem path.
      // The UI does not ask for, or display, its internal managed-upload path.
      await expect(page.getByRole('textbox',{name:'CSV file location',exact:true})).not.toBeVisible()
      const selected=active.data_csv_path
      expect(selected).toMatch(/uploads/)
      expect((await context.request.post(origin+'/api/import/preview',{headers:{'X-SAP-Lens':'1'},data:{data_csv_path:selected}})).ok()).toBeTruthy()
      expect(active.source_modes.roles).toBe('static')
      expect((await(await context.request.get(origin+'/api/roles')).json()).some((role:any)=>role.agr_name==='ZC:DEMO')).toBeTruthy()
      const diagnostic=await context.request.get(origin+'/api/diagnostics/export')
      expect(diagnostic.ok()).toBeTruthy();expect(await diagnostic.text()).not.toContain(root)
      expect((await(await context.request.get(origin+'/api/runtime')).json()).native_dialogs).toBeFalsy()
      await page.getByRole('tab',{name:'Health & Diagnostics',exact:true}).click()
      await page.getByRole('tab',{name:'Storage & Logs',exact:true}).click()
      const downloaded=page.waitForEvent('download')
      await page.getByRole('button',{name:'Export diagnostics',exact:true}).click()
      const download=await downloaded
      expect(download.suggestedFilename()).toMatch(/diagnostics.*\.json$/i)
      expect(readFileSync((await download.path())!,'utf-8')).not.toContain(root)
    }finally{await context.close()}
  })
}


test('browser uploads activate all source types and reject an invalid replacement without losing metadata', async({browser})=>{
  const context=await contextFor(browser,800,900)
  const page=await context.newPage()
  try{
    await page.goto(origin)
    await page.getByRole('button',{name:'Open settings',exact:true}).click()
    await page.getByRole('tab',{name:'Data Sources',exact:true}).click()
    const employeeHeader='Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'
    const matrix='RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\nREF1,H,S,Synthetic,A,B,ACTVT1,A,MIGO,Synthetic\nREF1,H,S,Synthetic,A,B,ACTVT2,B,ME23N,Synthetic\n'
    for(const [tab,content,source] of [
      ['Role Catalogue','AGR_NAME,TEXT,TCODE\nZC:SYNTHETIC,Synthetic,MIGO\n','roles'],
      ['User Access','USERNAME,ROLE_NAME,EMAIL\nSYNTHETIC,ZC:SYNTHETIC,synthetic@example.invalid\n','users'],
      ['Employee Directory',employeeHeader+'\nSynthetic;Example Person;synthetic;synthetic@example.invalid;synthetic@example.invalid;Demo;Tester;True;CN=Synthetic;;;;;;;\n','employees'],
      ['SoD Matrix',matrix,'sod'],
    ] as const){
      await page.getByRole('tab',{name:tab,exact:true}).click()
      const area=page.getByRole('region',{name:`${tab} source management`,exact:true})
      const chooser=area.getByLabel(`Upload ${tab} CSV`,{exact:true})
      await expect(area.getByRole('button',{name:'Browse / Upload file',exact:true})).toHaveCount(1)
      await expect(area.getByRole('button',{name:'Browse / Upload file',exact:true})).toBeEnabled()
      await expect(area.locator('details button').filter({hasText:'Browse'})).toHaveCount(0)
      const request=page.waitForRequest(request=>request.url().endsWith(`/api/server/uploads/${source}/activate`))
      await chooser.setInputFiles({name:`synthetic-${source}.csv`,mimeType:'text/csv',buffer:Buffer.from(content)})
      expect((await request).headers()['content-type']).toMatch(/^multipart\/form-data; boundary=/)
      await expect(area.getByRole('status').filter({hasText:`source records from synthetic-${source}.csv`})).toBeVisible()
      await expect(area).toContainText(`Active file: synthetic-${source}.csv`)
      const before=(await(await context.request.get(origin+'/api/configuration')).json()).settings
      await chooser.setInputFiles({name:'invalid.csv',mimeType:'text/csv',buffer:Buffer.from('UNSUPPORTED\nbroken\n')})
      await expect(area.getByRole('alert').first()).toBeVisible()
      const after=(await(await context.request.get(origin+'/api/configuration')).json()).settings
      expect(after.revision).toBe(before.revision);expect(after.data_lifecycle).toEqual(before.data_lifecycle);expect(after.employee_snapshot_id).toBe(before.employee_snapshot_id)
    }
  }finally{await context.close()}
})


test('migrated credentials sign in and recovery backup requires confirmation before deletion',async({browser})=>{
 const context=await contextFor(browser,1280,900),page=await context.newPage()
 try{
  await page.goto(origin);await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'User Management',exact:true}).click()
  const region=page.getByRole('region',{name:'Account migration backups'})
  await expect(region.getByRole('button',{name:'Confirm account migration',exact:true})).toBeVisible()
  const folder=path.join(root,'data','.application-backups','identity-migration')
  const archived=readdirSync(folder).map(id=>path.join(folder,id,'pre-identity.slbak')).filter(file=>existsSync(file))
  expect(archived).toHaveLength(1)
  await region.getByRole('button',{name:'Confirm account migration',exact:true}).click()
  await page.getByRole('dialog',{name:'Confirm account migration?',exact:true}).getByRole('button',{name:'Confirm',exact:true}).click()
  await expect(region.getByRole('button',{name:'Delete account migration backup',exact:true})).toBeVisible()
  expect(existsSync(archived[0])).toBe(true)
  await region.getByRole('button',{name:'Delete account migration backup',exact:true}).click()
  await page.getByRole('dialog',{name:'Delete account migration backup?',exact:true}).getByRole('button',{name:'Confirm',exact:true}).click()
  await expect(region).toContainText('deleted')
  expect(existsSync(archived[0])).toBe(false)
  expect(readFileSync(path.join(root,'legacy-users.json')).equals(legacyAccounts)).toBe(true)
 }finally{await context.close()}
})
