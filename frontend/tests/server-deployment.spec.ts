import { test, expect } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createServer, type AddressInfo } from 'node:net'

// A real headless server, separate from the desktop-capability browser fixture.
let process:ChildProcess, root:string
let origin:string
const password='synthetic-browser-server-'+ 'a'.repeat(40)
test.beforeAll(async()=>{
  const reservation=createServer()
  await new Promise<void>(resolve=>reservation.listen(0,'127.0.0.1',resolve))
  const port=(reservation.address() as AddressInfo).port
  await new Promise<void>((resolve,reject)=>reservation.close(error=>error?reject(error):resolve()))
  origin=`http://127.0.0.1:${port}`
  root=mkdtempSync(path.join(tmpdir(),'sap-lens-server-'))
  mkdirSync(path.join(root,'sources'))
  writeFileSync(path.join(root,'access.secret'),password,{mode:0o600})
  process=spawn('python',['../backend/server.py'],{env:{...globalThis.process.env,
    SAP_LENS_DEPLOYMENT_MODE:'server',SAP_LENS_DATA_DIR:path.join(root,'data'),SAP_LENS_CONFIG_DIR:path.join(root,'data'),
    SAP_LENS_SOURCE_DIR:path.join(root,'sources'),SAP_LENS_PORT:String(port),SAP_LENS_HOST:'127.0.0.1',
    SAP_LENS_PUBLIC_ORIGIN:origin,SAP_LENS_ALLOWED_HOSTS:'127.0.0.1',SAP_LENS_AUTH:'basic',
    SAP_LENS_AUTH_SECRET_FILE:path.join(root,'access.secret'),SAP_LENS_TRUSTED_PROXIES:''},stdio:'ignore'})
  await expect.poll(async()=>{try{return (await fetch(origin+'/health/ready')).status}catch{return 0}},{timeout:10000}).toBe(200)
})
test.afterAll(async()=>{
  if(process&&process.exitCode===null){const stopped=new Promise(resolve=>process.once('exit',resolve));process.kill('SIGTERM');await stopped}
  if(root)rmSync(root,{recursive:true,force:true})
})
for(const theme of ['light','dark'])for(const width of [375,800,1280]){
  test(`headless browser automatic upload and download ${theme} ${width}`,async({browser},testInfo)=>{
    const context=await browser.newContext({httpCredentials:{username:'saplens',password},viewport:{width,height:900}})
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
      await expect(page.getByRole('status').filter({hasText:'Catalogue ø.csv selected.'})).toBeVisible()
      // Browser selection activates the validated private Static snapshot immediately.
      const source=page.getByRole('region',{name:'Role Catalogue browser upload'})
      await expect(source).toBeVisible()
      await expect(page.getByRole('combobox',{name:'CSV source mode',exact:true})).toHaveValue('static')
      await source.scrollIntoViewIfNeeded()
      await page.screenshot({path:testInfo.outputPath(`server-${theme}-${width}.png`)})
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
      const active=(await(await context.request.get(origin+'/api/configuration')).json()).settings
      // Use the path produced by the actual upload field, not a client filesystem path.
      const inputs=await page.locator('input').evaluateAll(nodes=>nodes.map(n=>(n as HTMLInputElement).value))
      const selected=inputs.find(value=>value.includes('/uploads/')||value.includes('\\uploads\\'))
      expect(selected).toBeTruthy()
      expect((await context.request.post(origin+'/api/import/preview',{headers:{'X-SAP-Lens':'1'},data:{data_csv_path:selected}})).ok()).toBeTruthy()
      expect(active.data_csv_path).toBe(selected);expect(active.source_modes.roles).toBe('static')
      expect((await(await context.request.get(origin+'/api/roles')).json()).some((role:any)=>role.agr_name==='ZC:DEMO')).toBeTruthy()
      const diagnostic=await context.request.get(origin+'/api/diagnostics/export')
      expect(diagnostic.ok()).toBeTruthy();expect(await diagnostic.text()).not.toContain(root)
      expect((await(await context.request.get(origin+'/api/runtime')).json()).native_dialogs).toBeFalsy()
      await page.getByRole('tab',{name:'Health & Diagnostics',exact:true}).click()
      const downloaded=page.waitForEvent('download')
      await page.getByRole('button',{name:'Export diagnostics',exact:true}).click()
      const download=await downloaded
      expect(download.suggestedFilename()).toMatch(/diagnostics.*\.json$/i)
      expect(readFileSync((await download.path())!,'utf-8')).not.toContain(root)
    }finally{await context.close()}
  })
}
