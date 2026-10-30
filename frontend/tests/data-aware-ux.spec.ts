import {inspectTechnicalSources} from './source-details-fixture'
import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { bootstrapDocument } from './bootstrap-fixture'
import { headers } from './support'
let directory = '', userSource = ''
const navigate = (page: Page, name: string) => page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name, exact:true }).click()
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-data-aware-'))
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = path.join(directory, 'catalogue.csv')
  writeFileSync(settings.data_csv_path, 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:MM:BUY:EN*,Purchasing,ZS:BUY,ME23N\n')
  userSource = path.resolve('../backend/tests/fixtures/user-access.csv')
  settings.user_csv_path = userSource
  expect((await request.post('/api/configuration', { headers, data:settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }); rmSync(directory, { recursive:true, force:true }) })

test('Back and Forward preserve meaningful views and detail state without reloading startup', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read','clipboard-write'])
  const documents:string[] = []
  page.on('request', request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url()) })
  await page.goto('/#session=browser-test-session')
  await navigate(page, 'User Access')
  const routeBeforeSkip = page.url()
  await page.getByRole('link',{name:'Skip to main content',exact:true}).focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()
  expect(page.url()).toBe(routeBeforeSkip)
  await page.getByLabel('Search users', { exact:true }).fill('DEMO_OTHER')
  await page.getByRole('link', { name: 'DEMO_OTHER', exact:true }).click()
  const detail = page.getByRole('region', { name:'User details', exact:true })
  await expect(detail.locator('.profile-identity-header')).toContainText('Sample Other')
  await expect(detail.getByText('Unlocked', {exact:true})).toHaveCount(1)
  await detail.getByRole('button',{name:'Copy username DEMO_OTHER',exact:true}).click()
  await expect(detail.getByText('Copied',{exact:true})).toBeVisible()
  expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe('DEMO_OTHER')
  await expect(page.getByRole('navigation', {name:'Account evidence pages'})).toHaveCount(0)
  await expect(detail.locator('details').filter({ hasText: 'User validity and account evidence' })).toHaveCount(0)
  await page.goBack()
  await expect(page.getByLabel('Search users', {exact:true})).toHaveValue('DEMO_OTHER')
  await expect(page.getByRole('link', { name: 'DEMO_OTHER',exact:true})).toBeVisible()
  await page.goForward()
  await expect(detail).toBeVisible()
  await navigate(page, 'Release Roles')
  await page.goBack()
  await expect(detail).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('heading', {name:'Release Roles',exact:true})).toBeVisible()
  expect(documents).toHaveLength(1)
  await expect(page.locator('.startup-screen')).toHaveCount(0)
  await page.goto('/#/user-access')
  await expect(page.getByRole('heading', {name:'User Access',exact:true})).toBeVisible()
})

test('release facets are data-driven, bounded, retain invalid choices and refresh', async ({ page, request }) => {
  await page.goto('/#session=browser-test-session'); await navigate(page,'Release Roles');await page.getByRole('button',{name:'Table',exact:true}).click()
  const select = async (label:string, value:string) => { await page.getByRole('combobox', {name:label,exact:true}).fill(value); await page.getByRole('option', {name:value,exact:true}).click() }
  await select('PR/PO','PR')
  await select('Release Group','SH')
  await select('Release Strategy','N6')
  await select('Release username','DEMO_ALFA')
  await select('Release role name','ZO:MM:M:PR_REL_ST_SH_N6:ALL')
  await expect(page.getByRole('button',{name:'Release role details',exact:true})).toHaveCount(1)
  await select('PR/PO','PO')
  await expect(page.getByRole('button',{name:'Remove Release Group SH',exact:true})).toBeVisible()
  await expect(page.getByText('No available value matches this filter', {exact:false}).first()).toBeVisible()
  await expect(page.getByText('No release assignments match.',{exact:false})).toBeVisible()
  await page.getByRole('button',{name:'Clear filters',exact:true}).click()
  await expect(page.getByRole('combobox',{name:'PR/PO',exact:true})).toHaveValue('')
  const settings = (await (await request.get('/api/configuration',{headers})).json()).settings
  settings.user_csv_path = path.join(directory,'many-users.csv')
  writeFileSync(settings.user_csv_path, 'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n' + Array.from({length:150},(_,i)=>`DEMO_${String(i).padStart(3,'0')},ZO:MM:M:PR_REL_ST_G${String(i).padStart(3,'0')}_N6:ALL,GROUP_TEST,20000101,99991231`).join('\n'))
  expect((await request.post('/api/configuration',{headers,data:settings})).ok()).toBeTruthy()
  await page.getByRole('button',{name:'Refresh role data from CSV',exact:true}).click()
  await page.getByRole('combobox',{name:'Release username',exact:true}).click()
  const options = page.getByRole('listbox',{name:'Release username options',exact:true})
  await expect(options.getByRole('option')).toHaveCount(51)
  await expect(options).toContainText('Type to narrow')
  await page.getByRole('combobox',{name:'Release username',exact:true}).fill('DEMO_149')
  await page.getByRole('option',{name:'DEMO_149',exact:true}).click()
  await expect(page.getByRole('button',{name:'Release role details',exact:true})).toHaveCount(1)
  await expect(page.getByRole('button',{name:'Release role details',exact:true})).toContainText('G149')
})

test('loading and reconnect stay contextual during Back and Forward', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await navigate(page,'User Access')
  let failed = false
  await page.route('**/api/configuration', async route => {
    if (failed) return route.abort()
    try { const response = await route.fetch(); const data = await response.json(); await route.fulfill({json:{...data,loading:true}}) }
    catch { await route.abort().catch(() => {}) } // the request belonged to a page that was navigating away
  })
  await page.getByRole('button',{name:'Refresh role data from CSV',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Loading CSV data…',exact:true})).toBeVisible()
  await expect(page.getByText('Loading role data…',{exact:true})).toHaveCount(0)
  await navigate(page,'Release Roles'); await page.goBack()
  await expect(page.getByRole('heading',{name:'User Access',exact:true})).toBeVisible()
  await expect(page.locator('.startup-screen')).toHaveCount(0)
  failed = true
  // The application-scoped poll detects service loss even while refresh is busy.
  await expect(page.getByText('Local service unavailable.',{exact:true})).toBeVisible()
  await expect(page.getByRole('heading',{name:'Loading CSV data…',exact:true})).toHaveCount(0)
  await expect(page.locator('.startup-screen')).toHaveCount(0)
  await page.unroute('**/api/configuration')
  await page.getByRole('button',{name:'Retry connection',exact:true}).click()
  await expect(page.getByText('Local service unavailable.',{exact:true})).toHaveCount(0)
  await expect(page.getByRole('heading',{name:'User Access',exact:true})).toBeVisible()
})

for (const theme of ['dark','light']) for (const width of [1280,800]) test(`data-aware visual QA ${theme} ${width}`, async ({page,request}, info) => {
  const settings = (await (await request.get('/api/configuration',{headers})).json()).settings
  settings.theme = theme; await request.post('/api/configuration',{headers,data:settings})
  await page.setViewportSize({width,height:900})
  await page.goto('/#session=browser-test-session')
  // The overflow check polls (layout settles after route and panel changes) and, when it still fails, attaches the offending elements and a screenshot so a rare failure is diagnosable from the report.
  const shot = async (name:string) => {
    const fits = () => page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)
    try { await expect.poll(fits, { timeout: 3000 }).toBeTruthy() }
    catch (error) {
      const offenders = await page.evaluate(() => [...document.querySelectorAll('body *')].map(element => { const box = element.getBoundingClientRect(); return { tag: element.tagName.toLowerCase(), cls: String(element.className).slice(0, 60), text: (element.textContent || '').trim().slice(0, 40), right: Math.round(box.right), width: Math.round(box.width) } }).filter(item => item.right > innerWidth + 1 && item.width > 0).slice(0, 25).concat([{ tag: 'viewport', cls: '', text: `scrollWidth ${document.documentElement.scrollWidth} innerWidth ${innerWidth}`, right: 0, width: 0 }]))
      await info.attach(`overflow-${name}.json`, { body: JSON.stringify(offenders, null, 1), contentType: 'application/json' })
      await info.attach(`overflow-${name}.png`, { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
      throw error
    }
    await page.screenshot({path:info.outputPath(`${name}.png`),fullPage:true})
  }
  await navigate(page,'User Access'); await page.getByRole('link', { name: 'DEMO_OTHER',exact:true}).click()
  await expect(page.getByRole('region',{name:'Account Status',exact:true})).toBeVisible()
  await shot('user-two-column')
  await page.getByRole('button',{name:'Open settings',exact:true}).click()
  await page.getByRole('tab',{name:'Health & Diagnostics',exact:true}).click()
  await page.getByText('Source locations and storage details',{exact:true}).click()
  await inspectTechnicalSources(page)
  const storage = page.getByRole('heading',{name:'Data & storage',exact:true})
  await expect(storage).toBeVisible()
  await expect(page.getByRole('region',{name:'User Access CSV',exact:true}).locator('dl > div').filter({has:page.getByText('Records',{exact:true})}).locator('dd')).toHaveText('7')
  await storage.scrollIntoViewIfNeeded(); await shot('diagnostics-sources')
  for (const name of ['Role Catalogue CSV', 'User Access CSV']) {
    await page.getByRole('region',{name,exact:true}).scrollIntoViewIfNeeded()
    await shot(`diagnostics-${name.startsWith('Role') ? 'catalogue' : 'users'}`)
  }
  const exported = await request.get('/api/diagnostics/export',{headers})
  const redacted = await exported.text()
  expect(redacted).not.toContain(userSource); expect(redacted).not.toContain(directory); expect(redacted).not.toContain('DEMO_ALFA')
  await page.getByRole('tab',{name:'Appearance & Branding',exact:true}).click()
  await page.getByRole('img',{name:'Header logo preview',exact:true}).scrollIntoViewIfNeeded()
  await shot('branding-controls')
  await page.getByRole('button',{name:'Back to SAP Lens',exact:true}).click()
  // The loading state is mocked only after the refresh request has been sent. Mocking it earlier races with the application's own configuration polling: when that poll lands before the click, the Refresh button is disabled (correctly) and the click waits until the test times out.
  let mockedLoading = false
  await page.route('**/api/configuration', async route => {try{const response=await route.fetch();const body=await response.json();await route.fulfill({json:mockedLoading?{...body,loading:true}:body})}catch{await route.abort().catch(()=>{})}})
  await page.route('**/api/refresh', async route => {mockedLoading=true;await route.continue()})
  await page.getByRole('button',{name:'Refresh role data from CSV',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Loading CSV data…',exact:true})).toBeVisible()
  await shot('contextual-loading')
  await page.unroute('**/api/configuration'); await page.unroute('**/api/refresh')
  // Actual authored bootstrap document and palette, browser-rendered; not native WebView2.
  const html = bootstrapDocument(theme)
  await page.route('**/synthetic-bootstrap-preview',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:html}))
  await page.goto('/synthetic-bootstrap-preview')
  await expect(page.getByRole('status')).toHaveText('Starting backend…')
  expect(await page.evaluate(() => document.characterSet)).toBe('UTF-8')
  await expect.poll(()=>page.evaluate(()=>getComputedStyle(document.documentElement).colorScheme)).toBe(theme)
  await shot('bootstrap')
})

test('bootstrap handoff replaces its history entry and never reappears at the first app route', async ({page}) => {
  const html = bootstrapDocument()
  await page.route('**/synthetic-bootstrap',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:html}))
  await page.goto('/synthetic-bootstrap')
  await expect(page.getByRole('status')).toHaveText('Starting backend…')
  expect(await page.evaluate(() => document.characterSet)).toBe('UTF-8')
  const bootstrapLength = await page.evaluate(()=>history.length)
  await page.evaluate(()=>window.location.replace('/#session=browser-test-session'))
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeVisible()
  expect(await page.evaluate(()=>history.length)).toBe(bootstrapLength + 1) // one app boundary, no added bootstrap entry
  await navigate(page,'User Access'); await page.goBack()
  await expect(page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Dashboard',exact:true})).toHaveAttribute('aria-current','page')
  await page.goBack()
  await expect.poll(()=>page.evaluate(()=>Boolean(history.state?.sapLensView && !history.state?.sapLensBoundary))).toBeTruthy()
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeVisible()
  await expect(page.getByText('Starting backend…',{exact:true})).toHaveCount(0)
  await page.goForward()
  await expect(page.getByRole('heading',{name:'User Access',exact:true})).toBeVisible()
})


test('first-launch setup retains an app history boundary before configuration is available', async ({page,request}) => {
  await request.post('/api/configuration/reset',{headers})
  await page.goto('/#session=browser-test-session')
  await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeHidden()
  await page.goBack()
  await expect.poll(()=>page.evaluate(()=>Boolean(history.state?.sapLensView && !history.state?.sapLensBoundary))).toBeTruthy()
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeVisible()
  await expect(page.locator('.startup-screen')).toHaveCount(0)
})

test('bootstrap Unicode survives legacy Python stdout and explicit UTF-8 HTTP delivery', async ({ page }) => {
  const html = bootstrapDocument(undefined, 'cp1252')
  expect(html).toContain('Starting backend…')
  expect(html).not.toContain('\uFFFD')
  await page.route('**/unicode-bootstrap', route => route.fulfill({
    contentType: 'text/html; charset=utf-8', body: Buffer.from(html, 'utf8'),
  }))
  const response = await page.goto('/unicode-bootstrap')
  expect(response?.headers()['content-type']).toBe('text/html; charset=utf-8')
  expect(await page.evaluate(() => document.characterSet)).toBe('UTF-8')
  await expect(page.getByRole('status')).toHaveText('Starting backend…')
  await page.evaluate(() => (window as unknown as {sapLensStartup:{setState:(label:string)=>void}}).sapLensStartup.setState('Connecting to local service…'))
  await expect(page.getByRole('status')).toHaveText('Connecting to local service…')
})
