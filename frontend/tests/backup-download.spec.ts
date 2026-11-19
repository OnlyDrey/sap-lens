import {test, expect} from '@playwright/test'
import {openSettings} from './support'

const id = 'a'.repeat(32)
const filename = `AuthLens-backup-${id}.slbak`
const payload = Buffer.from('synthetic encrypted archive bytes')

test('backup download accepts the ASP.NET unquoted filename and preserves response bytes', async ({page}) => {
  await page.route('**/api/backups', route => route.fulfill({json: {id, kind: 'backup', status: 'ready', key_provider: {configured: true, escrow_verified: true}}}))
  await page.route(/\/api\/backups\/[a-f0-9]{32}\/download/, route => route.fulfill({body: payload, headers: {'Content-Type': 'application/octet-stream', 'Content-Disposition': `attachment; filename=${filename}; filename*=UTF-8''${filename}`}}))
  await openSettings(page, 'Backup & Restore')
  const completed = page.waitForEvent('download')
  await page.getByRole('button', {name: 'Download backup', exact: true}).click()
  const download = await completed
  expect(download.suggestedFilename()).toBe(filename)
  const stream = await download.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
  expect(Buffer.concat(chunks)).toEqual(payload)
  await expect(page.getByText('Invalid backup filename.', {exact: true})).toHaveCount(0)
})

test('download errors stay with their tab and clear after a successful retry', async ({page}) => {
  let valid = false
  await page.route('**/api/backups', route => route.fulfill({json: {id, kind: 'backup', status: 'ready', key_provider: {configured: true, escrow_verified: true}}}))
  await page.route(/\/api\/backups\/[a-f0-9]{32}\/download/, route => route.fulfill({body: payload, headers: {'Content-Type': 'application/octet-stream', 'Content-Disposition': `attachment; filename=${valid ? filename : '../host.key'}`}}))
  await openSettings(page, 'Backup & Restore')
  await page.getByRole('button', {name: 'Download backup', exact: true}).click()
  await expect(page.getByText('Invalid backup filename.', {exact: true})).toBeVisible()
  await page.getByRole('tab', {name: 'Scheduling', exact: true}).click()
  await expect(page.getByText('Invalid backup filename.', {exact: true})).toHaveCount(0)
  await page.getByRole('tab', {name: 'Overview', exact: true}).click()
  valid = true
  const completed = page.waitForEvent('download')
  await page.getByRole('button', {name: 'Download backup', exact: true}).click()
  await completed
  await expect(page.getByText('Invalid backup filename.', {exact: true})).toHaveCount(0)
})
