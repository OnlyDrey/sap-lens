import {test,expect} from '@playwright/test'
import {mkdtempSync,writeFileSync,rmSync,readFileSync} from 'node:fs'
import {tmpdir} from 'node:os'
import path from 'node:path'
const headers={'X-SAP-Lens':'browser-test-session'}
let directory:string
let username:string
let risk:string
test.beforeEach(async({request},info)=>{
 await request.post('/api/configuration/reset',{headers});directory=mkdtempSync(path.join(tmpdir(),'sod-review-ui-'));const suffix=info.title.includes('period')?'REPORT':'REPORT';username=`SYN_REVIEW_${suffix}`;risk=`SYN_${suffix}`
 const files={roles:'AGR_NAME,TEXT,CHILD_AGR,TCODE\nZC:SYN:REVIEW,Synthetic role,ZS:SYN:REVIEW,X001\nZC:SYN:REVIEW,Synthetic role,ZS:SYN:REVIEW,X002\n',users:`USERNAME,ROLE_NAME,ROLE_VALID_FROM,ROLE_VALID_TO\n${username},ZC:SYN:REVIEW,20000101,99991231\n`,sod:`RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\n${risk},H,S,Synthetic review,A,B,ACTVT1,A,X001,Create\n${risk},H,S,Synthetic review,A,B,ACTVT2,B,X002,Approve\n`}
 for(const[source,content]of Object.entries(files)){const filename=path.join(directory,source+'.csv');writeFileSync(filename,content);const settings=(await(await request.get('/api/configuration',{headers})).json()).settings;expect((await request.post(`/api/data-sources/${source}/select`,{headers,data:{path:filename,revision:settings.revision,mode:source==='sod'?'dynamic':'static'}})).ok()).toBeTruthy()}
})
test.afterEach(async({request})=>{await request.post('/api/configuration/reset',{headers});rmSync(directory,{recursive:true,force:true})})

test('SoD-only refresh updates open findings without changing SAP revision and catalogue exports all matching risks',async({page,request})=>{
 await page.goto('/#session=browser-test-session');await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('button',{name:'SoD',exact:true}).click();await expect(page.getByRole('region',{name:'SoD overview',exact:true})).toContainText('Source Risks');
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export CSV',exact:true}).click();expect(readFileSync((await(await download).path())!).toString('utf8')).toContain('EXPLANATION_NO');
 await page.getByRole('link',{name:'User Conflicts',exact:true}).click();await expect(page.getByRole('button',{name:`Inspect SoD evidence ${username} ${risk}`,exact:true})).toBeVisible();
 const before=(await(await request.get('/api/configuration',{headers})).json()).data_revision;
 writeFileSync(path.join(directory,'sod.csv'),`RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\n${risk},H,S,Synthetic replacement,A,B,ACTVT1,A,X001,Create\n${risk},H,S,Synthetic replacement,A,B,ACTVT2,B,X999,Other\n`.replace(/\n/g,'\n'));
 await page.getByRole('button',{name:'Refresh role data from CSV',exact:true}).click();await expect(page.getByRole('button',{name:`Inspect SoD evidence ${username} ${risk}`,exact:true})).toHaveCount(0);await expect(page.getByText('No potential conflicts match this scope.',{exact:false})).toBeVisible();
 expect((await(await request.get('/api/configuration',{headers})).json()).data_revision).toBe(before);
})
for(const theme of ['light','dark'])for(const width of [375,800,1280,1600])test(`SoD integration ${theme} ${width}`,async({page,request},info)=>{
 await request.post('/api/configuration/theme',{headers,data:{theme}});await page.setViewportSize({width,height:950});await page.goto('/#session=browser-test-session');await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('button',{name:'SoD',exact:true}).click();await expect(page.getByRole('region',{name:'SoD overview',exact:true})).toBeVisible();
 for(const view of ['Risk Catalogue','Access Review','Review Periods','Reports']){await page.getByRole('link',{name:view,exact:true}).click();await page.screenshot({path:info.outputPath(`${view.replaceAll(' ','-')}-${theme}-${width}.png`)});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()}
})
