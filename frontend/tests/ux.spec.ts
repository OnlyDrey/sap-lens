import { contrast, onColor, themePresets, themeTokens, paletteErrors } from '../src/lib/theme'
import { test, expect } from '@playwright/test'
import path from 'node:path'
const headers={'X-SAP-Lens':'browser-test-session'}
test.beforeEach(async({request})=>{expect((await request.post('/api/configuration/reset',{headers})).ok()).toBeTruthy()})
const settings=(page:import('@playwright/test').Page)=>page.getByRole('region',{name:'SAP Lens settings',exact:true})

test('full-window navigation preserves draft and main analysis state and warns before discard',async({page,request})=>{
 await request.post('/api/settings',{headers,data:{data_csv_path:path.resolve('tests/fixtures/synthetic.csv')}})
 await page.goto('/#session=browser-test-session')
 await page.getByRole('article').first().getByRole('button',{name:'Add to comparison',exact:true}).click()
 await page.getByRole('button',{name:'Open settings'}).click()
 await page.getByRole('tab',{name:'System & Organization'}).click()
 await page.getByLabel('Organization name',{exact:true}).fill('Synthetic unsaved organization')
 await page.getByRole('tab',{name:'Appearance & Branding'}).click()
 await page.getByRole('tab',{name:'System & Organization'}).click()
 await expect(page.getByLabel('Organization name',{exact:true})).toHaveValue('Synthetic unsaved organization')
 page.once('dialog',dialog=>void dialog.dismiss())
 await page.getByRole('button',{name:'Back to SAP Lens'}).click()
 await expect(settings(page)).toBeVisible()
 page.once('dialog',dialog=>void dialog.accept())
 await page.getByRole('button',{name:'Back to SAP Lens'}).click()
 await expect(settings(page)).toBeHidden()
 await expect(page.getByRole('button',{name:'Remove from comparison',exact:true})).toHaveCount(1)
 await page.getByRole('button',{name:'Open settings'}).click()
 await expect(page.getByLabel('Organization name',{exact:true})).toHaveValue('Example Inc.')
 await page.getByRole('tab',{name:'System & Organization'}).focus()
 await page.keyboard.press('ArrowDown')
 await expect(page.getByRole('tab',{name:'Data Source & Import'})).toBeFocused()
 await expect(page.getByRole('tab',{name:'Data Source & Import'})).toHaveAttribute('aria-selected','true')
})

test('theme preview, accessible validation, custom preset persistence, system appearance and cancel',async({page,request})=>{
 await page.emulateMedia({colorScheme:'dark'})
 await page.goto('/#session=browser-test-session')
 await page.getByRole('tab',{name:'Appearance & Branding'}).click()
 const primary=page.getByLabel('Primary color',{exact:true})
 const original=await page.locator('html').evaluate(el=>getComputedStyle(el).getPropertyValue('--primary'))
 await primary.fill('#123456')
 await expect(page.getByRole('region',{name:'SAP Lens settings'})).toContainText('Unsaved changes')
 expect(await page.locator('html').evaluate(el=>getComputedStyle(el).getPropertyValue('--primary'))).toBe(original)
 await page.getByLabel('Primary text color',{exact:true}).fill('#111827')
 await expect(page.getByText(/needs at least 4.5:1 contrast/).first()).toBeVisible()
 await expect(page.getByRole('button',{name:'Apply settings',exact:true})).toBeDisabled()
 await page.getByLabel('Primary text color',{exact:true}).fill('invalid')
 await expect(page.getByLabel('Primary text color',{exact:true})).toHaveAttribute('aria-invalid','true')
 await page.getByRole('button',{name:'Reset Primary text color',exact:true}).click()
 await page.getByLabel('Custom preset name',{exact:true}).fill('Synthetic theme')
 await page.getByRole('button',{name:'Save custom preset',exact:true}).click()
 await page.getByRole('button',{name:'Apply settings',exact:true}).click()
 await expect(page.locator('html')).toHaveCSS('--primary','#123456')
 await page.reload()
 await page.getByRole('tab',{name:'Appearance & Branding'}).click()
 await expect(primary).toHaveValue('#123456')
 await expect(page.getByRole('button',{name:'Synthetic theme',exact:true})).toBeVisible()
 const config=await (await request.post('/api/configuration/export',{headers})).json()
 expect(config.settings.theme_colors.dark.primary).toBe('#123456')
 expect(config.settings.theme_colors.custom_presets[0].name).toBe('Synthetic theme')
 await page.getByRole('button',{name:'Light',exact:true}).click()
 page.once('dialog',dialog=>void dialog.accept())
 await page.getByRole('button',{name:'Cancel',exact:true}).click()
 await expect(page.locator('html')).toHaveClass(/dark/)
 await page.getByRole('button',{name:'Open settings'}).click()
 await page.getByRole('tab',{name:'Appearance & Branding'}).click()
 await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('system')
 await page.getByRole('button',{name:'Apply settings',exact:true}).click()
 await page.emulateMedia({colorScheme:'light'})
 await expect(page.locator('html')).not.toHaveClass(/dark/)
 await page.emulateMedia({colorScheme:'dark'})
 await expect(page.locator('html')).toHaveClass(/dark/)
})

test('empty organization fallback, icon search and keyboard selection', async ({ page }) => {
 await page.goto('/#session=browser-test-session')
 await page.getByRole('tab',{name:'System & Organization'}).click()
 await page.getByLabel('Organization name',{exact:true}).fill('')
 await page.getByRole('button',{name:'Apply settings',exact:true}).click()
 // The header stays clickable during saving; wait for the async close before reopening.
 await expect(settings(page)).toBeHidden()
 await expect(page.getByRole('banner').getByText('SAP Lens',{exact:true})).toBeVisible()
 await page.getByRole('button',{name:'Open settings'}).click()
 await page.getByRole('tab',{name:'SAP Modules'}).click()
 await page.getByRole('button',{name:'Edit FI — Financial Accounting',exact:true}).click()
 await page.getByLabel('Find an icon',{exact:true}).fill('layer')
 await page.getByRole('group',{name:'FI icon choices'}).getByRole('button',{name:'Layers',exact:true}).focus()
 await page.keyboard.press('Enter')
 await expect(page.getByRole('button',{name:'Layers',exact:true})).toHaveAttribute('aria-pressed','true')
})

// Isolate each visual case: six viewports/themes shared one 30-second budget before.
// Keep the same timeout, assertions and screenshots without retries or arbitrary sleeps.
for (const theme of ['SAP Lens Default', 'Light']) {
 for (const [width, height] of [[1280,720], [1366,768], [1920,1080]]) {
  test(`responsive settings: ${theme}, ${width}x${height}`, async ({ page }, testInfo) => {
   await page.setViewportSize({ width, height })
   await page.goto('/#session=browser-test-session')
   await page.getByRole('tab',{name:'Appearance & Branding'}).click()
   await page.getByRole('button',{name:theme,exact:true}).click()
   const apply = page.getByRole('button',{name:'Apply settings',exact:true})
   if (await apply.isEnabled()) await apply.click()
   else await page.getByRole('button',{name:'Cancel',exact:true}).click()
   await expect(settings(page)).toBeHidden()
   await page.getByRole('button',{name:'Open settings'}).click()
   await expect(settings(page)).toBeVisible()
   for (const section of ['System & Organization','Data Source & Import','SAP Modules','Appearance & Branding','Application & Diagnostics']) {
    await page.getByRole('tab',{name:section,exact:true}).click()
    const action = page.getByRole('button',{name:section==='Data Source & Import'?'Save and load CSV':'Apply settings',exact:true})
    await expect(action).toBeInViewport()
    const bounds = await action.boundingBox()
    expect(bounds!.y).toBeGreaterThanOrEqual(0)
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(height)
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
    expect(await page.locator('.settings-scroll').evaluate(el=>el.scrollWidth<=el.clientWidth)).toBeTruthy()
   }
   await page.getByRole('tab',{name:'Appearance & Branding'}).click()
   await page.screenshot({path:testInfo.outputPath(`settings-${theme.replace(/ /g,'-')}-${width}.png`)})
  })
 }
}

test('startup connection failure has actionable recovery and configuration notices dismiss once',async({page})=>{
 await page.route('**/api/configuration',route=>route.abort())
 await page.goto('/#session=browser-test-session')
 await expect(page.getByRole('heading',{name:'Unable to connect to the local service'})).toBeVisible()
 await expect(page.getByRole('button',{name:'Retry connection'})).toBeVisible()
 await page.unroute('**/api/configuration')
 await page.getByRole('button',{name:'Retry connection'}).click()
 await expect(settings(page)).toBeVisible()
 await page.route('**/api/configuration',async route=>{const response=await route.fetch();const data=await response.json();await route.fulfill({json:{...data,notice:'File settings migrated to schema 2; the original was backed up locally.'}})})
 await page.reload()
 await expect(page.getByText(/File settings migrated to schema 2/)).toBeVisible()
 await page.getByRole('button',{name:'Dismiss configuration notice'}).click()
 await page.getByRole('tab',{name:'System & Organization'}).click()
 await expect(page.getByText(/File settings migrated to schema 2/)).toBeHidden()
 await page.reload()
 await expect(page.getByRole('button',{name:'Dismiss configuration notice'})).toBeHidden()
})

test('branded startup document displays real status messages and recovery without external requests',async({page},testInfo)=>{
 const {execFileSync}=await import('node:child_process')
 const document=execFileSync('python',['-c',"import sys;sys.path.insert(0,'../backend');from pathlib import Path;from startup_screen import startup_html;sys.stdout.buffer.write(startup_html(Path('../assets/sap-lens.png'),'synthetic-preview-capability').encode('utf-8'))"],{encoding:'utf8',maxBuffer:8*1024*1024})
 const external:string[]=[]
 page.on('request',request=>{if(request.url().startsWith('http'))external.push(request.url())})
 await page.setViewportSize({width:1280,height:720})
 await page.setContent(document)
 await expect(page.getByRole('img',{name:'SAP Lens',exact:true})).toBeVisible()
 await expect(page.getByRole('status')).toHaveText('Starting backend…')
 for(const label of ['Connecting to local service…','Loading configuration…']) {
  await page.evaluate(label=>(window as unknown as {sapLensStartup:{setState:(label:string,error?:string)=>void}}).sapLensStartup.setState(label),label)
  await expect(page.getByRole('status')).toHaveText(label)
 }
 await page.evaluate(()=>(window as unknown as {sapLensStartup:{setState:(label:string,error:string)=>void}}).sapLensStartup.setState('Startup needs attention','The local service did not become ready.'))
 await expect(page.getByRole('alert')).toHaveText('The local service did not become ready.')
 await expect(page.getByRole('button',{name:'Close SAP Lens'})).toBeVisible()
 expect(external).toEqual([])
 await page.screenshot({path:testInfo.outputPath('startup-recovery.png')})
})

test('active role loading is explained and a subsequent CSV error opens source recovery',async({page,request})=>{
 await request.post('/api/settings',{headers,data:{data_csv_path:path.resolve('tests/fixtures/synthetic.csv')}})
 let phase='loading'
 await page.route('**/api/configuration',async route=>{const response=await route.fetch();const data=await response.json();await route.fulfill({json:{...data,loading:phase==='loading',error:phase==='error'?'Synthetic data read failed. Choose another file.':null}})})
 await page.goto('/#session=browser-test-session')
 await expect(page.getByRole('heading',{name:'Loading role data…'})).toBeVisible()
 await expect(page.getByRole('button',{name:'Review data source',exact:true})).toBeVisible()
 await page.getByRole('button',{name:'Review data source',exact:true}).click()
 await expect(settings(page)).toBeVisible()
 phase='error'
 await page.reload()
 await expect(settings(page)).toBeVisible()
 await expect(page.getByText('Synthetic data read failed. Choose another file.',{exact:true})).toBeVisible()
 await expect(page.getByLabel('CSV file location',{exact:true})).toBeVisible()
})


test('theme tokens keep primary controls readable across grayscale accents and presets',async()=>{
 for(let value=0;value<=255;value++) {
  const channel=value.toString(16).padStart(2,'0');const color='#'+channel.repeat(3)
  expect(contrast(color,onColor(color))).toBeGreaterThanOrEqual(4.5)
 }
 for(const preset of themePresets) {
  expect(paletteErrors(preset.colors)).toEqual([])
  const tokens=themeTokens(preset.colors)
  expect(contrast(tokens['--text'],tokens['--surface2'])).toBeGreaterThanOrEqual(4.5)
  expect(contrast(tokens['--text'],tokens['--hover'])).toBeGreaterThanOrEqual(4.5)
  expect(contrast(tokens['--border'],tokens['--surface'])).toBeGreaterThanOrEqual(3)
 }
})
