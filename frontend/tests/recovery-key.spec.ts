import {test, expect} from '@playwright/test'
import {openSettings} from './support'

test('recovery-copy verification reauthenticates once and clears ephemeral secrets', async ({page}) => {
  const key = 'c3ludGhldGljIHJlY292ZXJ5IG1hdGVyaWFs'
  const password = 'Synthetic administrator password'
  let verified = false, reauthenticated = false
  await page.route('**/api/backups', route => route.fulfill({json: {status: 'idle', reauthentication_required: true, key_provider: {configured: true, fingerprint: 'synthetic-fingerprint', escrow_verified: verified}}}))
  await page.route('**/api/auth/backup-reauth', async route => {
    expect(route.request().postDataJSON()).toEqual({current_password: password})
    reauthenticated = true
    await route.fulfill({json: {code: 'synthetic-single-use-proof', expires_in: 300}})
  })
  await page.route('**/api/backups/key/verify', async route => {
    expect(reauthenticated).toBe(true)
    expect(route.request().postDataJSON()).toEqual({recovery_key: key, reauth_code: 'synthetic-single-use-proof'})
    verified = true
    await route.fulfill({json: {configured: true, escrow_verified: true}})
  })
  await openSettings(page, 'Backup & Restore')
  await page.getByText('Recovery key details', {exact: true}).click()
  await page.getByText('Verify a separately stored recovery copy', {exact: true}).click()
  await page.getByLabel('Recovery key', {exact: true}).fill(key)
  await page.getByLabel('Current administrator password', {exact: true}).fill(password)
  await page.getByRole('button', {name: 'Verify recovery copy', exact: true}).click()
  await expect(page.getByText('Recovery copy verified. Automatic backups may now be enabled.', {exact: true})).toBeVisible()
  await expect(page.getByLabel('Recovery key', {exact: true})).toHaveValue('')
  await expect(page.getByLabel('Current administrator password', {exact: true})).toHaveValue('')
  const persisted = await page.evaluate(() => JSON.stringify({local: {...localStorage}, session: {...sessionStorage}}))
  for (const secret of [key, password, 'synthetic-single-use-proof']) expect(persisted).not.toContain(secret)
})
