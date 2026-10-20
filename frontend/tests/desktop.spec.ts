import { test, expect } from '@playwright/test'
import path from 'node:path'

// This exercises the bridge contract with a stub; Windows verifies the real window,
// and the native picker itself remains on the manual Windows checklist.
test('first launch, native picker contract, invalid CSV, persistence and private session reload', async ({ page, request }) => {
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
  expect(new URL(page.url()).hash).toBe('')
  await expect(page.getByRole('button', { name: 'Browse for CSV…' })).toBeEnabled()
  await page.getByRole('button', { name: 'Browse for CSV…' }).click()
  await expect(page.getByLabel('CSV file location')).toHaveValue(file)
  await page.getByLabel('CSV file location').fill(path.resolve('tests/fixtures/missing.csv'))
  await page.getByRole('button', { name: 'Save and load CSV' }).click()
  await expect(page.getByRole('alert')).toContainText('CSV file not found')
  await page.getByRole('button', { name: 'Browse for CSV…' }).click()
  await page.getByRole('button', { name: 'Save and load CSV' }).click()
  await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeHidden()
  await expect(page.getByText('Synthetic finance viewer', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('Synthetic finance viewer', { exact: true })).toBeVisible()
  await expect(page.getByRole('region',{name:'SAP Lens settings',exact:true})).toBeHidden()
  await page.getByRole('button', { name: 'Open settings' }).click()
  await page.getByRole('tab', { name: 'Data Source & Import' }).click()
  await expect(page.getByText(`Current file: ${file}`)).toBeVisible()
  await page.evaluate(() => { window.pywebview!.api.choose_csv = async () => null })
  await page.getByRole('button', { name: 'Browse for CSV…' }).click()
  await expect(page.getByLabel('CSV file location')).toHaveValue(file)
  await page.getByRole('button', { name: 'Back to SAP Lens' }).click()
  await page.getByRole('button', { name: 'Refresh role data from CSV' }).click()
  await expect(page.getByText(/Updated /)).toBeVisible()
  expect((await request.get('/api/settings')).status()).toBe(403)
  expect((await request.get('/api/settings', { headers: { 'X-SAP-Lens': 'browser-test-session', Origin: 'http://127.0.0.1:18743' } })).status()).toBe(403)
  expect(errors).toEqual([])
  expect(external).toEqual([])
})
