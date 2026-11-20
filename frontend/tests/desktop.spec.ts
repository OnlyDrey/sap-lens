import { test, expect, request as playwrightRequest } from '@playwright/test'
import path from 'node:path'
import { headers, postConfiguration } from './support'

const testOrigin = `http://127.0.0.1:${process.env.AUTHLENS_BROWSER_TEST_PORT || 18745}`

// Windows verifies the real WebView2 window on the manual checklist.
test('first launch, path activation, invalid CSV, persistence and private session reload', { tag: '@smoke' }, async ({ page, request }) => {
  expect((await request.post('/api/configuration/reset', {headers: {'X-SAP-Lens': 'browser-test-session'}})).ok()).toBeTruthy()
  const file = path.resolve('tests/fixtures/role-catalogue-minimal.csv')
  const errors: string[] = []
  const external: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => { if (!request.url().startsWith(`${testOrigin}/`)) external.push(request.url()) })
  await page.goto('/#session=browser-test-session')
  await expect(page.getByRole('region',{name:'AuthLens settings',exact:true})).toBeVisible()
  expect(new URL(page.url()).hash).toBe('#/dashboard')
  expect(page.url()).not.toContain('browser-test-session')
  expect(await page.evaluate(()=>JSON.stringify(history.state))).not.toContain('browser-test-session')
  await expect(page.getByRole('button', { name: 'Browse / Upload file' })).toBeEnabled()
  await page.getByLabel('CSV file location', {exact:true}).fill(file)
  await page.getByLabel('CSV file location', {exact:true}).press('Enter')
  await expect(page.getByRole('status').filter({hasText:'Completed ·'})).toBeVisible()
  await page.getByLabel('CSV file location', {exact:true}).fill(path.resolve('tests/fixtures/missing.csv'))
  await page.getByLabel('CSV file location',{exact:true}).press('Enter')
  await expect(page.getByRole('alert')).toContainText('CSV file not found')
  await page.getByLabel('CSV file location', {exact:true}).fill(file)
  await page.getByLabel('CSV file location', {exact:true}).press('Enter')
  await expect(page.getByRole('status').filter({hasText:'Completed ·'})).toBeVisible()
  await page.getByRole('button', { name: 'Back to AuthLens',exact:true }).click()
  await expect(page.getByRole('region',{name:'AuthLens settings',exact:true})).toBeHidden()
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Role Lookup',exact:true}).click()
  await expect(page.getByRole('article', {name:'Synthetic finance viewer', exact:true})).toBeVisible()
  await page.reload()
  await expect(page.getByRole('article', {name:'Synthetic finance viewer', exact:true})).toBeVisible()
  await expect(page.getByRole('region',{name:'AuthLens settings',exact:true})).toBeHidden()
  await page.getByRole('button', { name: 'Open settings' }).click()
  await page.getByRole('tab', { name: 'Data Sources' }).click()
  await page.getByRole('tabpanel',{name:'Role Catalogue',exact:true}).getByRole('button',{name:'Technical source details',exact:true}).click()
  await expect(page.getByRole('dialog').locator('.ui-metadata-list>div').filter({has:page.getByText('Configured file',{exact:true})}).locator('dd')).toHaveText(file)
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('CSV file location', {exact:true})).toHaveValue(file)
  await page.getByRole('button', { name: 'Back to AuthLens' }).click()
  await page.getByRole('button', { name: 'Refresh role data from CSV' }).click()
  await expect(page.getByText('All data is up to date',{exact:true})).toBeVisible()
  await expect(page.getByRole('banner').getByText(/Updated /)).toHaveCount(0)
  // Without the access token (the harness sends one with every request; it is cleared here): no session, and a session header from a
  // foreign origin, are both refused with 401 before any data is read.
  const anonymous = await playwrightRequest.newContext({ baseURL: testOrigin, extraHTTPHeaders: { 'X-SAP-Lens-Token': '' } })
  try {
    expect((await anonymous.get('/api/settings')).status()).toBe(401)
    expect((await anonymous.get('/api/settings', { headers: { 'X-SAP-Lens': 'browser-test-session', Origin: 'http://127.0.0.1:18743' } })).status()).toBe(401)
  } finally { await anonymous.dispose() }
  expect(errors).toEqual([])
  expect(external).toEqual([])
})

test('application information displays the resolved API identity for beta stable and development builds', async ({ page, request }) => {
  expect((await request.post('/api/configuration/reset', {headers})).ok()).toBeTruthy()
  const settings = (await (await request.get('/api/configuration', {headers})).json()).settings
  settings.data_csv_path = path.resolve('tests/fixtures/role-catalogue-minimal.csv')
  expect((await postConfiguration(request, settings)).ok()).toBeTruthy()
  const actual = await (await request.get('/api/version', {headers})).json()
  const health = await (await request.get('/health')).json()
  expect(actual.version).toBe(health.version)
  expect(actual.app).toBe('AuthLens')
  const anonymous = await playwrightRequest.newContext({ baseURL: testOrigin, extraHTTPHeaders: { 'X-SAP-Lens-Token': '' } })
  try { expect((await anonymous.get('/api/version')).status()).toBe(401) } finally { await anonymous.dispose() }   // no token: refused
  let identity = {app:'AuthLens',version:'0.1.0-beta-1',mode:'beta'}
  await page.route('**/api/version', route => route.fulfill({json:identity}))
  const footerVersion = page.getByRole('contentinfo').getByLabel('Application version', {exact:true}) // the footer; Settings also shows the version
  for (const [version, mode] of [['0.1.0-beta-1','beta'],['0.1.0','stable'],['0.1.0-dev.123.2','build'],['0.0.0-dev.local','local'],['0.1.0-beta-4+local.aaaaaaaaaaaa','local-build']]) {
    identity = {app:'AuthLens',version,mode}
    await page.goto('/#session=browser-test-session')
    await page.reload() // A running app's version is immutable; simulate a fresh process for each identity.
    await expect(footerVersion).toContainText(`AuthLens v${version}`)
    if (mode === 'local-build') await expect(footerVersion).toContainText('Local build')
    if (mode === 'build' || mode === 'local') await expect(footerVersion).toContainText('Development build')
    else await expect(footerVersion).not.toContainText('Development build')
    await page.reload()
    await expect(footerVersion).toContainText(version)
  }
  identity = {app:'AuthLens',version:'0.1.0-beta-1',mode:'beta'}
  for (const theme of ['light','dark']) {
    expect((await request.post('/api/configuration/theme',{headers,data:{theme}})).ok()).toBeTruthy()
    await page.reload()
    await expect(footerVersion).toContainText('0.1.0-beta-1')
    await page.screenshot({path:test.info().outputPath(`version-${theme}.png`), fullPage:true, animations:'disabled'})
  }
})
