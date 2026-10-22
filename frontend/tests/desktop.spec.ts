import { test, expect } from '@playwright/test'
import path from 'node:path'

// This exercises the bridge contract with a stub; Windows verifies the real window,
// and the native picker itself remains on the manual Windows checklist.
test('first launch, native picker contract, invalid CSV, persistence and private session reload', async ({ page, request }) => {
  expect((await request.post('/api/configuration/reset', {headers: {'X-SAP-Lens': 'browser-test-session'}})).ok()).toBeTruthy()
  const file = path.resolve('tests/fixtures/synthetic.csv')
  const errors: string[] = []
  const external: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:18745/')) external.push(request.url()) })
  await page.addInitScript(({ file }) => {
    window.pywebview = { api: { choose_csv: async token => {
      if (token !== 'browser-test-session') throw new Error('Wrong desktop session')
      return file
    } } }
  }, { file })
  await page.goto('/#session=browser-test-session')
  await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeVisible()
  expect(new URL(page.url()).hash).toBe('#/role-lookup')
  expect(page.url()).not.toContain('browser-test-session')
  expect(await page.evaluate(()=>JSON.stringify(history.state))).not.toContain('browser-test-session')
  await expect(page.getByRole('button', { name: 'Browse for CSV…' })).toBeEnabled()
  await page.getByRole('button', { name: 'Browse for CSV…' }).click()
  await expect(page.getByLabel('CSV file location', {exact:true})).toHaveValue(file)
  await page.getByLabel('CSV file location', {exact:true}).fill(path.resolve('tests/fixtures/missing.csv'))
  await page.getByRole('button', { name: 'Save and load CSV' }).click()
  await expect(page.getByRole('alert')).toContainText('CSV file not found')
  await page.getByRole('button', { name: 'Browse for CSV…' }).click()
  await page.getByRole('button', { name: 'Save and load CSV' }).click()
  await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeHidden()
  await expect(page.getByRole('article', {name:'Synthetic finance viewer', exact:true})).toBeVisible()
  await page.reload()
  await expect(page.getByRole('article', {name:'Synthetic finance viewer', exact:true})).toBeVisible()
  await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeHidden()
  await page.getByRole('button', { name: 'Open settings' }).click()
  await page.getByRole('tab', { name: 'Data Source & Import' }).click()
  await expect(page.getByText(`Saved file location: ${file}`)).toBeVisible()
  await page.evaluate(() => { window.pywebview!.api.choose_csv = async () => null })
  await page.getByRole('button', { name: 'Browse for CSV…' }).click()
  await expect(page.getByLabel('CSV file location', {exact:true})).toHaveValue(file)
  await page.getByRole('button', { name: 'Back to SAP Lens' }).click()
  await page.getByRole('button', { name: 'Refresh role data from CSV' }).click()
  await expect(page.getByText(/Updated /)).toBeVisible()
  expect((await request.get('/api/settings')).status()).toBe(403)
  expect((await request.get('/api/settings', { headers: { 'X-SAP-Lens': 'browser-test-session', Origin: 'http://127.0.0.1:18743' } })).status()).toBe(403)
  expect(errors).toEqual([])
  expect(external).toEqual([])
})

test('application information displays the resolved API identity for beta stable and development builds', async ({ page, request }) => {
  const headers = { 'X-SAP-Lens': 'browser-test-session' }
  expect((await request.post('/api/configuration/reset', {headers})).ok()).toBeTruthy()
  const settings = (await (await request.get('/api/configuration', {headers})).json()).settings
  settings.data_csv_path = path.resolve('tests/fixtures/synthetic.csv')
  expect((await request.post('/api/configuration', {headers, data:settings})).ok()).toBeTruthy()
  const actual = await (await request.get('/api/version', {headers})).json()
  const health = await (await request.get('/health')).json()
  expect(actual.version).toBe(health.version)
  expect(actual.app).toBe('SAP Lens')
  expect((await request.get('/api/version')).status()).toBe(403)
  let identity = {app:'SAP Lens',version:'0.1.0-beta-1',mode:'beta'}
  await page.route('**/api/version', route => route.fulfill({json:identity}))
  for (const [version, mode] of [['0.1.0-beta-1','beta'],['0.1.0','stable'],['0.1.0-dev.123.2','build'],['0.0.0-dev.local','local']]) {
    identity = {app:'SAP Lens',version,mode}
    await page.goto('/#session=browser-test-session')
    await page.reload() // A running app's version is immutable; simulate a fresh process for each identity.
    await expect(page.getByLabel('Application version', {exact:true})).toContainText(`SAP Lens v${version}`)
    if (mode === 'build' || mode === 'local') await expect(page.getByLabel('Application version')).toContainText('Development build')
    else await expect(page.getByLabel('Application version')).not.toContainText('Development build')
    await page.reload()
    await expect(page.getByLabel('Application version')).toContainText(version)
  }
  identity = {app:'SAP Lens',version:'0.1.0-beta-1',mode:'beta'}
  for (const theme of ['light','dark']) {
    expect((await request.post('/api/configuration/theme',{headers,data:{theme}})).ok()).toBeTruthy()
    await page.reload()
    await expect(page.getByLabel('Application version')).toContainText('0.1.0-beta-1')
    await page.screenshot({path:test.info().outputPath(`version-${theme}.png`), fullPage:true, animations:'disabled'})
  }
})
