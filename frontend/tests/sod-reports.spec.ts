import {test,expect} from '@playwright/test'
import {bridge,cleanup,createPeriod,decide,decideEverything,headers,names,openSod,seedGovernance} from './sod-fixture'
let directory:string
test.beforeEach(async({request})=>{directory=await seedGovernance(request)})
test.afterEach(async({request})=>{await cleanup(request,directory)})
const sections=['Executive Summary','Scope and Evaluation Period','Overall Findings and Risk Exposure','Review Progress: Activity Decisions','Review Progress: Role Assignment Decisions','Review Progress: Risk Acceptance Decisions','Compensating Controls and Conditions','Outstanding Risks and Actions','Remediation Responsibilities and Status','Evidence Freshness and Limitations','Changes Since Previous Review','Conclusion and Approval','Technical Appendices']

test('formal report previews every section from one frozen model and exports PDF and DOCX',async({page,request})=>{
 const id=await createPeriod(request,'Synthetic Browser Report');await decideEverything(request,id,'Rejected')
 await openSod(page,'Reports');await page.getByRole('combobox',{name:'Report period',exact:true}).selectOption(id)
 for(const name of ['Approved','Externally signed'])await expect(page.getByRole('option',{name,exact:true})).toHaveCount(0) // only a frozen period can carry these labels
 await expect(page.getByRole('combobox',{name:'Report status',exact:true}).locator('option')).toHaveText(['Draft','Reviewed'])
 await page.getByRole('combobox',{name:'Report status',exact:true}).selectOption('Reviewed');await expect(page.getByText('The name is not authenticated, so this is not an approval.',{exact:false})).toBeVisible()
 await page.getByText('Document details',{exact:true}).click();await expect(page.getByLabel('Report language',{exact:true})).toHaveCount(0)
 await expect(page.getByRole('button',{name:'Export PDF',exact:true})).toBeDisabled()
 await page.getByRole('button',{name:'Preview report',exact:true}).click();const preview=page.getByRole('region',{name:'Structured report preview',exact:true})
 for(const title of sections)await expect(preview.locator('summary').filter({hasText:title})).toHaveCount(1)
 await expect(preview).toContainText('Snapshot reference');await bridge(page)
 await page.getByRole('button',{name:'Export PDF',exact:true}).click();await expect.poll(()=>page.evaluate(()=>(window as any).__saved?.name)).toMatch(/^sap-lens-sod-report-[a-f0-9]{32}-\d{4}-\d{2}-\d{2}\.pdf$/)
 const saved=await page.evaluate(()=>(window as any).__saved);expect(Buffer.from(saved.encoded,'base64').subarray(0,5).toString()).toBe('%PDF-')
 await page.getByRole('button',{name:'Export DOCX',exact:true}).click();await expect.poll(()=>page.evaluate(()=>(window as any).__saved?.name)).toMatch(/\.docx$/)
 await page.getByLabel('Report title',{exact:true}).fill('Changed title');await expect(page.getByRole('button',{name:'Export PDF',exact:true})).toBeDisabled()
})

test('remediation report separates handling groups, previews counts and exports CSV and PDF',async({page,request})=>{
 const subject=await(await request.get('/api/sod/subject',{headers,params:{context:'current',user:names.a,activity:'A'}})).json();const row=subject.activities[0];const duplicate=row.assignments.find((item:any)=>item.role==='ROLE_A2')
 await decide(request,'assignment','current',[{key:duplicate.id,user:names.a,ref:'ROLE_A2',evidence_version:duplicate.evidence_version}],'Remove')
 await openSod(page,'Reports');await page.getByRole('tab',{name:'Access remediation report',exact:true}).click()
 await expect(page.getByText('A proposed removal is not completed remediation',{exact:false}).first()).toBeVisible()
 await page.getByRole('button',{name:'Preview report',exact:true}).click();const preview=page.getByRole('region',{name:'Remediation report preview',exact:true});await expect(preview.getByRole('table',{name:'Remediation summary',exact:true})).toContainText('Remove assignment')
 await bridge(page);await page.getByRole('button',{name:'Export CSV',exact:true}).click();await expect.poll(()=>page.evaluate(()=>(window as any).__saved?.name)).toMatch(/^sap-lens-sod-access-remediation-\d{4}-\d{2}-\d{2}\.csv$/)
 const csv=await page.evaluate(()=>(window as any).__saved.content);expect(csv.startsWith('﻿"USERNAME"')).toBeTruthy();expect(csv).toContain('ROLE_A2');expect(csv).toContain('Remove assignment')
 await page.getByRole('button',{name:'Export PDF',exact:true}).click();await expect.poll(()=>page.evaluate(()=>(window as any).__saved?.name)).toMatch(/^sap-lens-access-remediation-current-\d{4}-\d{2}-\d{2}\.pdf$/)
})
