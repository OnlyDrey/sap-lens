import {test,expect} from '@playwright/test'
import {execFileSync} from 'node:child_process'
import { PYTHON } from './python'
import path from 'node:path'
import { layoutMatrix } from './matrix'
const headers={'X-SAP-Lens':'browser-test-session'}
function archive(){return execFileSync(PYTHON,['-c',`import sys,tempfile,json
from pathlib import Path
sys.path.insert(0,'backend')
from config_models import AppConfig
from maintenance import backup
from version import VERSION
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);data=root/'data';data.mkdir()
 (data/'deployment.json').write_text(json.dumps(dict(version=1,mode='desktop')))
 (data/'settings.json').write_text(AppConfig().model_dump_json())
 target=root/'exports'/'synthetic.tar.gz'
 backup(data,target,'desktop',VERSION)
 sys.stdout.buffer.write(target.read_bytes())`],{cwd:path.resolve('..')})}
test.afterEach(async({request})=>{await request.post('/api/backups/cancel',{headers})})
test('Settings backup requires restart; restore validates before explicit replacement confirmation',{ tag: '@workflow' }, async({page,request})=>{
 await request.post('/api/backups/cancel',{headers})
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'Backup & Restore',exact:true}).click()
 const region=page.getByRole('region',{name:'Application backup and restore'})
 await region.getByRole('button',{name:'Create backup (restart required)'}).click();await expect(region.getByText('Waiting for restart',{exact:true})).toBeVisible()
 expect((await request.post('/api/refresh',{headers})).status()).toBe(409)
 await region.getByRole('button',{name:'Cancel pending operation'}).click()
 await region.getByLabel('Application backup archive').setInputFiles({name:'invalid.zip',mimeType:'application/zip',buffer:Buffer.from('invalid')})
 await expect(region.getByRole('alert')).toContainText('Choose a non-empty SAP Lens .tar.gz backup.')
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
 await schedule.getByLabel('Successful automatic backups to keep').fill('3')
 await schedule.getByRole('button',{name:'Save backup schedule'}).click()
 await expect(schedule.getByRole('button',{name:'Save backup schedule'})).toBeEnabled()
 expect((await request.get('/api/backups/schedule',{headers})).status()).toBe(200)
 expect((await (await request.get('/api/backups/schedule',{headers})).json()).schedule.keep).toBe(3)
 await expect(page.getByLabel('Application backup archive')).toBeEnabled()
 const saved=await (await request.get('/api/backups/schedule',{headers})).json()
 await request.post('/api/backups/schedule',{headers,data:{revision:saved.revision,schedule:{...saved.schedule,keep:7,enabled:false}}})
})
