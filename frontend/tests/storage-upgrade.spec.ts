import { expect, test } from '@playwright/test'

const status = (required: boolean) => ({
  state: 'ready', schema_version: 1, size_bytes: 8_388_608, requires_confirmation: required,
  revisions: [{ source: 'users', rows: 48000, entities: 4000, activated: '2026-01-01T00:00:00+00:00' }],
  backup: required ? { id: 'a'.repeat(32), created: '2026-01-01T00:00:00+00:00', sha256: 'b'.repeat(64), size_bytes: 3_145_728, app_version: '1.0.0' } : null,
})

test('the pre-migration backup is kept until the administrator explicitly confirms the upgrade', async ({ page }) => {
  let required = true
  const posted: unknown[] = []
  await page.route('**/api/storage/status', route => route.fulfill({ json: status(required) }))
  await page.route('**/api/storage/migration/confirm', async route => {
    posted.push(route.request().postDataJSON())
    required = false
    await route.fulfill({ json: status(false) })
  })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Backup & Restore', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Storage upgrade' })
  await expect(panel).toContainText('SQLite store ready')
  await expect(panel).toContainText('users 48,000 rows')
  await expect(panel).toContainText('never deleted automatically')
  const release = panel.getByRole('button', { name: 'Confirm upgrade and release the backup' })
  await expect(release).toBeDisabled()
  expect(posted).toEqual([])
  await panel.getByRole('checkbox', { name: 'I checked that SAP Lens works after the upgrade' }).check()
  await release.click()
  await expect(release).toHaveCount(0)
  expect(posted).toEqual([{ migration_id: 'a'.repeat(32), confirm: true }])
  await expect(panel).toContainText('SQLite store ready')
})
