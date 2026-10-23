import { test, expect } from '@playwright/test'
import { mkdtempSync, unlinkSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const headers = {'X-SAP-Lens':'browser-test-session'}
test.beforeEach(async ({request}) => { expect((await request.post('/api/configuration/reset',{headers})).ok()).toBeTruthy() })

test('system identity, private logo storage, persisted theme and portable backup/restore',async ({page}) => {
  const directory=mkdtempSync(path.join(tmpdir(),'sap-lens-test-logo-'))
  const logoPath=path.join(directory,'synthetic-logo.png')
  const logoData=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=320;canvas.height=80;const context=canvas.getContext('2d')!;context.fillStyle='#123456';context.fillRect(0,0,320,80);return canvas.toDataURL('image/png').split(',')[1]})
  writeFileSync(logoPath,Buffer.from(logoData,'base64'))
  page.on('dialog',dialog=>void dialog.accept())
  await page.addInitScript(({logoPath})=>{window.pywebview={api:{choose_csv:async()=>null,choose_logo:async()=>logoPath}}},{logoPath})
  try {
    await page.goto('/#session=browser-test-session')
    await page.getByRole('tab',{name:'System & Organization'}).click()
    await page.getByLabel('Organization name',{exact:true}).fill('Example Test Organization')
    await page.getByRole('combobox',{name:'SAP platform',exact:true}).selectOption('SAP ECC')
    await page.getByLabel('SAP system ID',{exact:true}).fill('DEMO2')
    await page.getByLabel('SAP client',{exact:true}).fill('200')
    await page.getByRole('button',{name:'Apply settings',exact:true}).click()
    await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeHidden()
    await expect(page.getByText('Example Test Organization',{exact:true})).toBeVisible()
    await page.getByRole('button',{name:'Open settings'}).click()
    await page.getByRole('tab',{name:'Appearance & Branding'}).click()
    await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('dark')
    await page.getByRole('button',{name:'Select custom logo…'}).click()
    await expect(page.getByRole('img',{name:'Header logo preview'})).toHaveAttribute('src',/^data:image\/png;base64,/)
    await page.getByRole('button',{name:'Apply settings',exact:true}).click()
    unlinkSync(logoPath)
    await page.reload()
    await expect(page.locator('html')).toHaveClass(/dark/)
    await page.getByRole('button',{name:'Back to SAP Lens'}).click()
    await expect(page.getByRole('banner').getByRole('img',{name:'Example Test Organization logo',exact:true})).toHaveAttribute('src',/^data:image\/png;base64,/)
    const headerLogo=page.getByRole('banner').getByRole('img',{name:'Example Test Organization logo',exact:true})
    await expect(headerLogo).toHaveJSProperty('naturalWidth',320)
    await expect(headerLogo).toHaveJSProperty('naturalHeight',80)
    await expect(headerLogo).toHaveCSS('object-fit','contain')
    const bounds=await headerLogo.boundingBox();expect(bounds!.width).toBeLessThanOrEqual(160);expect(bounds!.height).toBeLessThanOrEqual(48)
    // No CSV is configured, so the first-run data section remains accessible.
    if(!(await page.getByRole('region',{name:'SAP Lens settings',exact:true}).isVisible()))await page.getByRole('button',{name:'Open settings'}).click()
    await page.getByRole('tab',{name:'Application & Diagnostics'}).click()
    await page.getByLabel('Include private organization details, profiles and branding in export').check()
    const downloadPromise=page.waitForEvent('download')
    await page.getByRole('button',{name:'Export saved configuration'}).click()
    const download=await downloadPromise
    const contents=readFileSync((await download.path())!,'utf8')
    const portable=JSON.parse(contents)
    expect(portable.settings.data_csv_path).toBe('')
    expect(portable.logo_base64).toBeTruthy()
    await page.getByRole('button',{name:'Reset to defaults',exact:true}).click()
    await page.getByRole('tab',{name:'System & Organization'}).click()
    await expect(page.getByLabel('Organization name',{exact:true})).toHaveValue('Example Inc.')
    await page.getByRole('tab',{name:'Application & Diagnostics'}).click()
    await page.getByLabel('Import configuration package').setInputFiles({name:'synthetic.sap-lens.json',mimeType:'application/json',buffer:Buffer.from(contents)})
    await page.getByRole('tab',{name:'System & Organization'}).click()
    await expect(page.getByLabel('Organization name',{exact:true})).toHaveValue('Example Test Organization')
    await page.getByRole('tab',{name:'Appearance & Branding'}).click()
    await page.getByRole('button',{name:'Remove custom logo / restore SAP Lens default'}).click()
    await page.getByRole('button',{name:'Apply settings',exact:true}).click()
    await expect(page.getByRole('banner').getByRole('img',{name:'SAP Lens',exact:true})).toHaveAttribute('src','/sap-lens.png')
  } finally {rmSync(directory,{recursive:true,force:true})}
})

test('custom column mapping preserves relationships and transactions',async ({page,request})=>{
  const directory=mkdtempSync(path.join(tmpdir(),'sap-lens-mapping-'))
  const file=path.join(directory,'synthetic.csv')
  writeFileSync(file,'Module;Role;Child;Parent;Effective;Transaction\nFI;DEMO_ROOT;DEMO_CHILD;DEMO_PARENT;DEMO_EFFECTIVE;DEMO_TRANSACTION\n')
  try {
    await page.goto('/#session=browser-test-session')
    await page.getByLabel('CSV file location',{exact:true}).fill(file)
    await page.getByRole('button',{name:'Detect columns'}).click()
    await page.getByRole('combobox',{name:'AGR_NAME (required)',exact:true}).click()
    await page.getByRole('option',{name:'Role',exact:true}).click()
    for(const [field,source] of [['CHILD_AGR','Child'],['PARENT_AGR','Parent'],['Effective_Role','Effective'],['TCODE','Transaction']]) { await page.getByRole('combobox',{name:field,exact:true}).click(); await page.getByRole('option',{name:source,exact:true}).click() }
    await page.getByRole('button',{name:'Preview import',exact:true}).click()
    await expect(page.getByText(/1 composite roles/)).toBeVisible()
    await page.getByRole('button',{name:'Save and load CSV',exact:true}).click()
    await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeHidden()
    const detail=await (await request.get('/api/roles/DEMO_ROOT',{headers})).json()
    expect(detail.relationships[0].effective_role).toBe('DEMO_EFFECTIVE')
    expect(detail.single_roles[0].tcodes[0].tcode).toBe('DEMO_TRANSACTION')
  }finally{rmSync(directory,{recursive:true,force:true})}
})

test('registry customization preserves custom mappings, CSV modules and transactions',async ({page,request})=>{
  const directory=mkdtempSync(path.join(tmpdir(),'sap-lens-registry-'))
  const file=path.join(directory,'synthetic.csv')
  writeFileSync(file,'Module;Role;Child;Parent;Effective;Transaction\nFI;DEMO_ROOT;DEMO_CHILD;DEMO_PARENT;DEMO_EFFECTIVE;DEMO_TRANSACTION\n')
  try {
    // Seed explicit CSV module evidence; module preferences never classify names.
    const settings=(await (await request.get('/api/configuration',{headers})).json()).settings
    settings.data_csv_path=file
    settings.import_profiles.find((p:{id:string})=>p.id===settings.active_import).mapping={FUNCTION_KEY:'Module',AGR_NAME:'Role',CHILD_AGR:'Child',PARENT_AGR:'Parent',Effective_Role:'Effective',TCODE:'Transaction'}
    expect((await request.post('/api/configuration',{headers,data:settings})).ok()).toBeTruthy()
    await page.goto('/#session=browser-test-session')
    await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Role Lookup',exact:true}).click()

    await page.getByRole('button',{name:'Open settings'}).click()
    await page.getByRole('tab',{name:'SAP Modules'}).click()
    await page.getByLabel('Find SAP module or area',{exact:true}).fill('FI')
    await page.getByRole('button',{name:'Edit FI — Financial Accounting',exact:true}).click()
    await page.getByLabel('FI display name',{exact:true}).fill('Synthetic accounting')
    await page.getByRole('group',{name:'FI icon choices'}).getByRole('button',{name:'Layers',exact:true}).click()
    await page.getByLabel('FI hexadecimal color visual selection',{exact:true}).fill('#123456')
    await page.getByRole('button',{name:'Apply settings',exact:true}).click()
    await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeHidden()
    await expect(page.getByRole('article',{name:'DEMO_ROOT',exact:true})).toContainText('Synthetic accounting')
    const registry=(await (await request.get('/api/registry/modules',{headers})).json()).modules
    expect(registry.find((m:{id:string})=>m.id==='FI').color).toBe('#123456')
    expect(registry.find((m:{id:string})=>m.id==='FI').icon).toBe('Layers')

    const detail=await (await request.get('/api/roles/DEMO_ROOT',{headers})).json()
    expect(detail.relationships[0].effective_role).toBe('DEMO_EFFECTIVE')
    expect(detail.single_roles[0].tcodes[0].tcode).toBe('DEMO_TRANSACTION')
    expect(detail.function_key).toBe('FI')
    const saved=(await (await request.get('/api/configuration',{headers})).json()).settings
    expect(saved.classification_profiles).toBeUndefined()
    expect(saved.import_profiles.find((p:{id:string})=>p.id===saved.active_import).mapping).toEqual(settings.import_profiles.find((p:{id:string})=>p.id===settings.active_import).mapping)
  }finally{rmSync(directory,{recursive:true,force:true})}
})

test('large catalogs render bounded pages and retain cross-page comparisons',async({page,request})=>{
  const directory=mkdtempSync(path.join(tmpdir(),'sap-lens-pages-'))
  const file=path.join(directory,'synthetic.csv')
  writeFileSync(file,'AGR_NAME,TEXT,TCODE\n'+Array.from({length:205},(_,i)=>`DEMO_PAGE_${String(i).padStart(3,'0')},Synthetic page role ${String(i).padStart(3,'0')},DEMO_T`).join('\n')+'\n')
  try {
    expect((await request.post('/api/settings',{headers,data:{data_csv_path:file}})).ok()).toBeTruthy()
    await page.goto('/#session=browser-test-session')
    await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Role Lookup',exact:true}).click()
    const cards=page.getByRole('main').locator('article')
    await expect(cards).toHaveCount(100)
    await expect(cards.first()).toBeInViewport()
    await cards.first().getByRole('button',{name:'Add to comparison',exact:true}).click()
    await page.getByRole('button',{name:'Next page',exact:true}).click()
    await expect(page.getByText('Showing 101–200 of 205 roles',{exact:true})).toBeVisible()
    await cards.first().getByRole('button',{name:'Add to comparison',exact:true}).click()
    const response=page.waitForResponse(r=>r.url().endsWith('/api/compare')&&r.request().method()==='POST')
    await page.getByRole('button',{name:'Compare now',exact:true}).click()
    expect((await response).status()).toBe(200)
    expect((await (await response).json()).roles).toHaveLength(2)
  }finally{rmSync(directory,{recursive:true,force:true})}
})
