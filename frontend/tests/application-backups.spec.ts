import {test,expect} from '@playwright/test'
import {execFileSync} from 'node:child_process'
import path from 'node:path'
const headers={'X-SAP-Lens':'browser-test-session'}
function archive(){return execFileSync('python',['-c',`import sys,tempfile,json
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
test('Settings backup requires restart; restore validates before explicit replacement confirmation',async({page,request})=>{
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
 const confirm=region.getByRole('button',{name:'Confirm restore on restart'});await expect(confirm).toBeDisabled()
 await region.getByRole('checkbox').check();await expect(confirm).toBeEnabled();await confirm.click()
 await expect(region.getByText(/Restart required. Destination data/)).toBeVisible()
 await region.getByRole('button',{name:'Cancel pending operation'}).click()
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`Backup and Restore ${theme} ${width}`,async({page,request},info)=>{
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
