import {test,expect} from '@playwright/test'
import {spawn,execFileSync} from 'node:child_process'
import {mkdtempSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {createServer,type AddressInfo} from 'node:net'
import {observeTestServer,stopTestServer,removeTestServerDirectory,type OwnedTestServer} from './server-process'
import {PYTHON} from './python'

let root:string,origin:string,server:OwnedTestServer
const password='Synthetic browser passphrase æ 123!'
test.beforeAll(async()=>{
 const reservation=createServer()
 await new Promise<void>(resolve=>reservation.listen(0,'127.0.0.1',resolve))
 const port=(reservation.address() as AddressInfo).port
 await new Promise<void>((resolve,reject)=>reservation.close(error=>error?reject(error):resolve()))
 origin=`http://127.0.0.1:${port}`;root=mkdtempSync(path.join(tmpdir(),'sap-lens-session-auth-'))
 server=observeTestServer(spawn(PYTHON,['../backend/server.py'],{env:{...process.env,SAP_LENS_DATA_DIR:root,SAP_LENS_CONFIG_DIR:root,SAP_LENS_SOURCE_DIR:path.join(root,'sources'),SAP_LENS_HOST:'127.0.0.1',SAP_LENS_PORT:String(port),SAP_LENS_ALLOWED_HOSTS:'127.0.0.1',SAP_LENS_PUBLIC_ORIGIN:origin,SAP_LENS_AUTH:'sessions',SAP_LENS_TRUSTED_PROXIES:''},stdio:'ignore',detached:process.platform!=='win32',windowsHide:true}))
 await expect.poll(async()=>{if(server.startupError())throw server.startupError();try{return(await fetch(origin+'/health/ready')).status}catch{return 0}},{timeout:10000}).toBe(200)
})
test.afterAll(async()=>{if(server)await stopTestServer(server);if(root)await removeTestServerDirectory(root)})

test('activation, application accounts, session logout and viewer isolation @workflow',async({page})=>{
 const activation=JSON.parse(execFileSync(PYTHON,['../backend/server.py','--identity-code','--data-directory',root],{encoding:'utf8',timeout:20000})) as {code:string}
 await page.goto(origin)
 await expect(page.getByRole('heading',{name:'Set up SAP Lens'})).toBeVisible()
 await page.getByLabel('Username',{exact:true}).fill('admin')
 await page.getByLabel('Display name',{exact:true}).fill('Synthetic Administrator')
 await page.getByLabel('One-time code',{exact:true}).fill(activation.code)
 await page.getByLabel('New password',{exact:true}).fill(password)
 await page.getByRole('button',{name:'Create administrator',exact:true}).click()
 await page.getByRole('button',{name:'Open settings',exact:true}).click()
 await page.getByRole('tab',{name:'User Management',exact:true}).click()
 await page.getByRole('button',{name:'Create user',exact:true}).click()
 const create=page.getByRole('dialog',{name:'Create application user'})
 await create.getByLabel('Username',{exact:true}).fill('viewer')
 await create.getByLabel('Display name',{exact:true}).fill('Synthetic Viewer')
 await create.getByLabel('Initial password',{exact:true}).fill(password)
 await create.getByRole('button',{name:'Save user',exact:true}).click()
 await expect(page.getByRole('row').filter({hasText:'Synthetic Viewer'})).toContainText('viewer')
 const viewerRow=page.getByRole('row').filter({hasText:'Synthetic Viewer'})
 await viewerRow.getByRole('button',{name:'Reset password',exact:true}).click()
 await page.getByRole('dialog',{name:'Reset password for viewer?'}).getByRole('button',{name:'Confirm',exact:true}).click()
 const resetDialog=page.getByRole('dialog',{name:'One-time password reset code'})
 const resetCode=await resetDialog.getByLabel('Password reset code').innerText()
 await resetDialog.getByRole('button',{name:'Close dialog'}).click()
 await expect(page.locator('#root')).not.toHaveAttribute('inert','')
 await expect(page.getByRole('button',{name:'Edit admin',exact:true})).toBeEnabled()
 // Existing administrator protection is enforced by the backend, including the UI path.
 await page.getByRole('button',{name:'Edit admin',exact:true}).click()
 const edit=page.getByRole('dialog',{name:'Edit admin'})
 await edit.getByLabel('Role',{exact:true}).selectOption('viewer')
 await edit.getByRole('button',{name:'Save user',exact:true}).click()
 await edit.getByRole('button',{name:'Confirm account change',exact:true}).click()
 await expect(edit.getByRole('alert')).toContainText('Keep at least one enabled Administrator.')
 await edit.getByRole('button',{name:'Close dialog'}).click()
 for(const width of [375,800,1280,1600]){
  await page.setViewportSize({width,height:900})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 }
 await page.setViewportSize({width:1280,height:900})
 await page.getByRole('button',{name:'Back to SAP Lens',exact:true}).click()
 await page.getByRole('button',{name:'My Profile',exact:true}).click()
 const profile=page.getByRole('dialog',{name:'My Profile'})
 await expect(profile).toContainText('admin')
 await profile.getByLabel('Display name',{exact:true}).fill('Updated Administrator')
 await profile.getByRole('button',{name:'Save profile',exact:true}).click()
 await expect(profile.getByRole('status')).toHaveText('Profile saved.')
 await profile.getByRole('button',{name:'Sign out',exact:true}).click()
 await expect(page.getByRole('heading',{name:'Sign in to SAP Lens'})).toBeVisible()
 await page.getByLabel('Username',{exact:true}).fill('viewer')
 await page.getByLabel('Password',{exact:true}).fill(password)
 await page.getByRole('button',{name:'Sign in',exact:true}).click()
 await expect(page.getByRole('alert')).toContainText('Username or password was not accepted.')
 await page.getByRole('button',{name:'Use password reset code'}).click()
 await page.getByLabel('One-time code',{exact:true}).fill(resetCode)
 await page.getByLabel('New password',{exact:true}).fill(password+'new')
 await page.getByRole('button',{name:'Set password',exact:true}).click()
 await expect(page.getByRole('status')).toHaveText('Password updated. Sign in with your new password.')
 await page.getByLabel('Password',{exact:true}).fill(password+'new')
 await page.getByRole('button',{name:'Sign in',exact:true}).click()

 await expect(page.getByRole('button',{name:'My Profile',exact:true})).toBeVisible()
 await expect(page.getByRole('button',{name:'Open settings',exact:true})).toBeDisabled()
 expect((await page.request.get(origin+'/api/auth/users')).status()).toBe(403)
 expect((await page.request.get(origin+'/api/configuration')).status()).toBe(403)
 expect((await page.request.post(origin+'/api/auth/logout',{headers:{'X-SAP-Lens':'1'}})).status()).toBe(403)
 // Only the clicked authenticated operation carries the session-specific CSRF header.
 await page.getByRole('button',{name:'My Profile',exact:true}).click()
 const logout=page.waitForRequest(request=>request.url().endsWith('/api/auth/logout'))
 await page.getByRole('dialog',{name:'My Profile'}).getByRole('button',{name:'Sign out',exact:true}).click()
 expect((await logout).headers()['x-sap-lens-csrf']).toBeTruthy()
 await expect(page.getByRole('heading',{name:'Sign in to SAP Lens'})).toBeVisible()
 expect((await page.request.get(origin+'/api/auth/me')).status()).toBe(401)
 expect(await page.evaluate(()=>Object.keys(localStorage).some(key=>/auth|token|csrf/.test(key)))).toBe(false)
 for(const theme of ['light','dark']){
  await page.evaluate(theme=>localStorage.setItem('sap-viz-theme',theme),theme)
  await page.reload()
  await expect(page.getByRole('heading',{name:'Sign in to SAP Lens'})).toBeVisible()
  await page.setViewportSize({width:375,height:900})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:path.resolve('../build/test-artifacts/auth-ui/login-'+theme+'-375.png')})
 }
 await page.getByLabel('Username',{exact:true}).fill('viewer')
 await page.getByLabel('Password',{exact:true}).fill(password+'new')
 await page.getByRole('button',{name:'Sign in',exact:true}).click()
 await expect(page.getByRole('button',{name:'My Profile',exact:true})).toBeVisible()
 // A server-side revocation must discard the prior user's cached data and show login,
 // not a backend-disconnected/restart instruction.
 execFileSync(PYTHON,['-c',"import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute('DELETE FROM sessions'); db.commit(); db.close()",path.join(root,'security/accounts.sqlite3')],{timeout:20000})
 await page.reload()
 await expect(page.getByRole('heading',{name:'Sign in to SAP Lens'})).toBeVisible()

})
