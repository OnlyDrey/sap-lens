import {test, expect} from '@playwright/test'
import {openSettings} from './support'

const id = 'c'.repeat(32)
const backup = {id, created: '2026-11-18T09:00:00Z', sha256: 'c'.repeat(64), size_bytes: 1024}
const base = {state: 'ready', schema_version: 9, size_bytes: 4096, revisions: [{source: 'users', rows: 48000, entities: 4000, activated: backup.created}], problems: []}

test('functional acceptance is explicit and retains the migration backup until separate deletion', async ({page}) => {
  let confirmed = false, deleted = false, confirmations = 0
  await page.route('**/api/storage/status', route => route.fulfill({json: {...base, requires_confirmation: !confirmed, backup: confirmed ? null : backup, retained: confirmed && !deleted ? {...backup, confirmed_at: backup.created, confirmed_by: 'synthetic operator'} : null}}))
  await page.route('**/api/storage/migration/confirm', route => {
    expect(route.request().postDataJSON()).toEqual({migration_id: id, confirm: true})
    confirmations++; confirmed = true
    return route.fulfill({json: {}})
  })
  await page.route('**/api/storage/migration/delete-backup', route => {
    expect(route.request().postDataJSON()).toEqual({migration_id: id, confirm: true})
    deleted = true
    return route.fulfill({json: {}})
  })
  await openSettings(page, 'Backup & Restore')
  const section = page.getByRole('region', {name: 'Storage upgrade'})
  await expect(section.getByText(`Backup identifier: ${id}`)).toBeVisible()
  await expect(section).toContainText('users 48,000 rows')
  await expect(section).toContainText('automatic retention never deletes it')
  const approve = section.getByRole('button', {name: 'Confirm that the upgrade works'})
  await expect(approve).toBeDisabled(); expect(confirmations).toBe(0)
  await section.getByRole('checkbox', {name: 'I checked that AuthLens works after the upgrade'}).check()
  await approve.click()
  await expect(section.getByText('Upgrade confirmed. The pre-migration backup is still retained.')).toBeVisible()
  await expect(approve).toHaveCount(0)
  expect(confirmations).toBe(1); expect(deleted).toBe(false)
  const remove = section.getByRole('button', {name: 'Delete pre-migration backup', exact: true})
  await expect(remove).toBeDisabled()
  await section.getByRole('checkbox', {name: 'Delete the pre-migration backup permanently'}).check()
  await remove.click()
  await expect(section.getByText('The confirmed pre-migration backup was deleted.')).toBeVisible()
  await expect(remove).toHaveCount(0)
  expect(deleted).toBe(true)
})

test('unhealthy storage blocks approval and reports SQLite problems without claiming a JSON fallback', async ({page}) => {
  await page.route('**/api/storage/status', route => route.fulfill({json: {...base, state: 'unavailable', requires_confirmation: true, backup, problems: ['Synthetic integrity failure']}}))
  await openSettings(page, 'Backup & Restore')
  const section = page.getByRole('region', {name: 'Storage upgrade'})
  await expect(section.getByText('SQLite store needs attention')).toBeVisible()
  await expect(section.getByRole('alert')).toHaveText('Synthetic integrity failure')
  await section.getByRole('checkbox').check()
  await expect(section.getByRole('button', {name: 'Confirm that the upgrade works'})).toBeDisabled()
  await expect(section).not.toContainText('JSON snapshots')
})
