import {test,expect} from '@playwright/test'
import {execFileSync} from 'node:child_process'
import { PYTHON } from './python'
import path from 'node:path'
import { layoutMatrix } from './matrix'
const headers={'X-SAP-Lens':'browser-test-session'}
function archive(secret=''){return execFileSync(PYTHON,[path.resolve('../scripts/testing/synthetic-backup.py'),...(secret?['--encrypted']:[])],{cwd:path.resolve('..'),input:secret+'\n'})}
test.afterEach(async({request})=>{await request.post('/api/backups/cancel',{headers})})
test('Settings backup requires restart; restore validates before explicit replacement confirmation',{ tag: '@workflow' }, async({page,request})=>{
 await request.post('/api/backups/cancel',{headers})
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Backup & Restore',exact:true}).click()
 const region=page.getByRole('region',{name:'Application backup and restore'})
 await region.getByRole('button',{name:'Create backup (restart required)'}).click();await expect(region.getByText('Waiting for restart',{exact:true})).toBeVisible()
 expect((await request.post('/api/refresh',{headers})).status()).toBe(409)
 await region.getByRole('button',{name:'Cancel pending operation'}).click()
 await region.getByLabel('Application backup archive').setInputFiles({name:'invalid.zip',mimeType:'application/zip',buffer:Buffer.from('invalid')})
 await expect(region.getByRole('alert')).toContainText('Choose a non-empty SAP Lens .slbak backup or acknowledged legacy .tar.gz archive.')
 await region.getByRole('checkbox',{name:/Allow a legacy unencrypted archive import/}).check()
 await region.getByLabel('Application backup archive').setInputFiles({name:'synthetic.tar.gz',mimeType:'application/gzip',buffer:archive()})
 await expect(region.getByText('Validated upload staged on server: synthetic.tar.gz',{exact:true})).toBeVisible()
 await expect(region.getByRole('heading',{name:'Validated archive preview'})).toBeVisible()
 await region.getByRole('button',{name:'Cancel restore preview',exact:true}).click();await expect(region.getByRole('heading',{name:'Validated archive preview'})).toHaveCount(0);await expect(region.getByText(/Validated upload staged on server:/)).toHaveCount(0);await expect(region).toContainText('Restore preview cancelled. No application data was changed.');await region.getByLabel('Application backup archive').setInputFiles({name:'synthetic.tar.gz',mimeType:'application/gzip',buffer:archive()});await expect(region.getByRole('heading',{name:'Validated archive preview'})).toBeVisible()
 const confirm=region.getByRole('button',{name:'Confirm restore on restart'});await expect(confirm).toBeDisabled()
 await region.getByRole('checkbox',{name:'I confirm full replacement after restart. I understand that these histories will not be merged.'}).check();await expect(confirm).toBeEnabled();await confirm.click()
 await expect(region.getByText(/Restart required. Destination data/)).toBeVisible()
 await region.getByRole('button',{name:'Cancel pending operation'}).click()
})
for (const { theme, width } of layoutMatrix([375,800,1280,1600]))test(`Backup and Restore ${theme} ${width}`,{ tag: '@visual' }, async({page,request},info)=>{
 await request.post('/api/backups/cancel',{headers});await request.post('/api/configuration/theme',{headers,data:{theme}})
 await page.setViewportSize({width,height:1000});await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Backup & Restore',exact:true}).click()
 await expect(page.getByRole('region',{name:'Application backup and restore'})).toBeVisible()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
 await page.screenshot({path:info.outputPath(`backup-${theme}-${width}.png`),fullPage:true})
})

test('Backup recovery remains usable when the independent configuration request fails',async({page})=>{
 await page.route('**/api/configuration',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Synthetic configuration unavailable'})}))
 await page.goto('/#session=browser-test-session')
 await page.getByRole('button',{name:'Open Backup & Restore',exact:true}).click()
 const region=page.getByRole('region',{name:'Application backup and restore'})
 await expect(region).toBeVisible()
 await expect(region.getByLabel('Application backup archive')).toBeEnabled()
 await expect(region.getByRole('button',{name:'Create backup (restart required)'})).toBeEnabled()
 await expect(page.getByRole('button',{name:'Retry connection'})).toBeVisible()
})

test('Cancelling archive validation clears busy state without claiming a staged selection',async({page})=>{
 await page.goto('/#session=browser-test-session')
 await page.getByRole('button',{name:'Open settings',exact:true}).click()
 await page.getByRole('tab',{name:'Backup & Restore',exact:true}).click()
 await page.route('**/api/backups/upload',()=>{})
 const region=page.getByRole('region',{name:'Application backup and restore'})
 await region.getByLabel('Application backup archive').setInputFiles({name:'synthetic.tar.gz',mimeType:'application/gzip',buffer:Buffer.from('synthetic-pending-upload')})
 await region.getByRole('button',{name:'Cancel validation',exact:true}).click()
 await expect(region.getByRole('alert')).toContainText('No restore was confirmed')
 await expect(region.getByLabel('Application backup archive')).toBeEnabled()
 await expect(region.getByText(/Validated upload staged on server:/)).toHaveCount(0)
 await expect(region.getByRole('button',{name:'Confirm restore on restart'})).toHaveCount(0)
})

test('Backup schedule uses validated cron settings and does not hide manual or restore actions',async({page,request})=>{
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Backup & Restore',exact:true}).click()
 const schedule=page.getByRole('region',{name:'Automatic backup scheduling'})
 await schedule.getByLabel('Backup time zone',{exact:true}).fill('Unknown/Nowhere')
 await schedule.getByRole('button',{name:'Save backup schedule'}).click()
 await expect(schedule.getByRole('alert')).toBeVisible()
 await schedule.getByLabel('Backup time zone',{exact:true}).fill('UTC')
 await expect(schedule.getByText(/90 days/)).toBeVisible()
 await schedule.getByRole('button',{name:'Save backup schedule'}).click()
 await expect(schedule.getByRole('button',{name:'Save backup schedule'})).toBeEnabled()
 expect((await request.get('/api/backups/schedule',{headers})).status()).toBe(200)
 expect((await (await request.get('/api/backups/schedule',{headers})).json()).schedule.keep).toBe(7)
 await expect(page.getByLabel('Application backup archive')).toBeEnabled()
 const saved=await (await request.get('/api/backups/schedule',{headers})).json()
 await request.post('/api/backups/schedule',{headers,data:{revision:saved.revision,schedule:{...saved.schedule,keep:7,enabled:false}}})
})


test('Encrypted archive authentication precedes preview and secrets are not persisted',async({page,request})=>{
 await request.post('/api/backups/cancel',{headers})
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Backup & Restore',exact:true}).click()
 const region=page.getByRole('region',{name:'Application backup and restore'})
 const secret='Synthetic portable archive æ 123!'
 const buffer=archive(secret),input=region.getByLabel('Application backup archive')
 await region.getByLabel('Restore passphrase or exported recovery key',{exact:true}).fill('Wrong synthetic passphrase 123!')
 await input.setInputFiles({name:'synthetic.slbak',mimeType:'application/octet-stream',buffer})
 await expect(region.getByRole('alert')).toContainText('Backup authentication failed')
 await expect(region.getByRole('heading',{name:'Validated archive preview'})).toHaveCount(0)
 await region.getByLabel('Restore passphrase or exported recovery key',{exact:true}).fill(secret)
 await input.setInputFiles({name:'synthetic.slbak',mimeType:'application/octet-stream',buffer})
 await expect(region.getByRole('heading',{name:'Validated archive preview'})).toBeVisible()
 await expect(region.getByText('Authenticated encryption',{exact:true})).toBeVisible()
 await expect(region.getByLabel('Restore passphrase or exported recovery key',{exact:true})).toHaveValue('')
 expect(await page.evaluate(value=>Object.values(localStorage).some(item=>item.includes(value)),secret)).toBe(false)
 const status=await (await request.get('/api/backups',{headers})).json()
 expect(status.crypto_plan).toBeUndefined()
 await region.getByRole('button',{name:'Cancel restore preview',exact:true}).click()
})
