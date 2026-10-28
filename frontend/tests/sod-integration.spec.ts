import {test,expect} from '@playwright/test'
import {writeFileSync,readFileSync} from 'node:fs'
import path from 'node:path'
import {cellButton,cleanup,enableSod,headers,names,openSod,seedGovernance} from './sod-fixture'
let directory:string
test.afterEach(async({request})=>{await cleanup(request,directory)})
const matrix=(second:string)=>`RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\nR1,H,S,Synthetic R1,A,B,ACTVT1,A,X1,Create\nR1,H,S,Synthetic R1,A,B,ACTVT2,B,${second},Approve\nR2,H,S,Synthetic R2,A,C,ACTVT1,A,X1,Create\nR2,H,S,Synthetic R2,A,C,ACTVT2,C,X3,Approve\n`

test('SoD-only refresh updates open findings without changing the SAP revision and the catalogue export lists risks',async({page,request})=>{
 directory=await seedGovernance(request,'dynamic')
 await page.goto('/#session=browser-test-session');await page.getByRole('button',{name:'Open settings',exact:true}).click();await page.getByRole('tab',{name:'SoD Risk Configuration',exact:true}).click()
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export CSV',exact:true}).click();const csv=readFileSync((await(await download).path())!).toString('utf8');expect(csv).toContain('EXPLANATION_NO');expect(csv).toContain('R1');expect(csv).toContain('R2')
 await openSod(page,'Access Explorer');const table=page.getByRole('table',{name:'User risk table',exact:true});await expect(table).toContainText('R1');await expect(table.getByRole('row').filter({hasText:names.a})).toHaveCount(2)
 const before=(await(await request.get('/api/configuration',{headers})).json()).data_revision
 writeFileSync(path.join(directory,'sod.csv'),matrix('X999'))
 await page.getByRole('button',{name:'Refresh role data from CSV',exact:true}).click();await expect(table.getByRole('row').filter({hasText:names.a})).toHaveCount(1);await expect(table.getByRole('row').filter({hasText:`${names.b}`})).toHaveCount(0)
 expect((await(await request.get('/api/configuration',{headers})).json()).data_revision).toBe(before)
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`SoD integration ${theme} ${width}`,async({page,request},info)=>{
 directory=await seedGovernance(request);await request.post('/api/configuration/theme',{headers,data:{theme}});await page.setViewportSize({width,height:950})
 for(const view of ['Overview','Risk Matrix','Activity Matrix','Access Explorer','Reviews','Review Periods','Reports']){await openSod(page,view);await expect(page.getByRole('heading',{name:'Segregation of Duties',level:1})).toBeVisible();await page.screenshot({path:info.outputPath(`${view.replaceAll(' ','-')}-${theme}-${width}.png`)});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${view} must not overflow the page`).toBeTruthy()}
 await openSod(page,'Risk Matrix');await cellButton(page,names.a,'R1').click();await expect(page.getByRole('dialog',{name:`${names.a} · R1`})).toBeVisible();await page.screenshot({path:info.outputPath(`panel-${theme}-${width}.png`)});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
})

for(const width of [375,414])test(`main navigation fits five items without clipped labels at ${width}`,async({page,request})=>{
 await enableSod(request);await page.setViewportSize({width,height:800});await page.goto('/#session=browser-test-session');const navigation=page.getByRole('navigation',{name:'Main navigation',exact:true});await expect(navigation.getByRole('button')).toHaveCount(5)
 const fit=await navigation.evaluate((nav)=>({scrolls:nav.scrollWidth>nav.clientWidth,clipped:[...nav.querySelectorAll('button')].filter((button)=>button.scrollWidth>button.clientWidth).length}))
 expect(fit).toEqual({scrolls:false,clipped:0})
})
