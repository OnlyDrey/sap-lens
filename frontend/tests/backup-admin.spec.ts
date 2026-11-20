import {test, expect, type Page} from '@playwright/test'
import {openSettings} from './support'

const id = 'b'.repeat(32)
const row = {id, created_at: '2026-11-18T09:00:00Z', origin: 'manual', status: 'ready', size: 1024, verified: true}
async function fixtures(page: Page) {
  await page.route('**/api/backups', route => route.fulfill({json: {status: 'idle', key_provider: {configured: true, escrow_verified: true, fingerprint: 'synthetic'}}}))
  await page.route('**/api/backups/schedule', route => route.fulfill({json: {revision: 0, schedule: {enabled: false, mode: 'daily', time: '06:00', timezone: 'UTC', cron: '0 6 * * *', keep: 7}, next_runs: [], description: 'Daily backup', encryption_ready: true, last_success: null, last_failure: null}}))
}

for (const width of [375, 800, 1280, 1600] as const) for (const theme of ['light', 'dark'] as const) {
  test(`backup overview is compact and accessible at ${width}px in ${theme}`, async ({page, request}, testInfo) => {
    await request.post('/api/configuration/theme', {data: {theme}})
    try {
      await page.setViewportSize({width, height: 900})
      await fixtures(page)
      await page.route('**/api/backups/history', route => route.fulfill({json: {items: [row], total: 1, storage_bytes: 1024}}))
      await openSettings(page, 'Backup & Restore')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await expect(page.getByLabel('Backup overview')).toBeVisible()
      await expect(page.getByRole('button', {name: 'Create backup', exact: true})).toBeEnabled()
      await expect(page.getByText('No restart is needed.', {exact: false})).toBeVisible()
      const recovery = page.locator('summary').filter({hasText: 'Recovery key details'})
      await expect(recovery).toBeVisible()
      await recovery.focus(); await page.keyboard.press('Enter')
      await expect(page.getByText('Verify a separately stored recovery copy', {exact: true})).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
      await page.getByLabel('Backup overview').scrollIntoViewIfNeeded()
      await page.screenshot({path: testInfo.outputPath(`backup-${width}-${theme}.png`), fullPage: true})
    } finally { await request.post('/api/configuration/theme', {data: {theme: 'dark'}}) }
  })
}

test('history verifies archives and deletes only after an explicit focused confirmation', async ({page}) => {
  let retained = true, verified = 0, deleted = 0
  await fixtures(page)
  await page.route('**/api/backups/history', route => route.fulfill({json: {items: retained ? [row] : [], total: retained ? 1 : 0, storage_bytes: retained ? 1024 : 0}}))
  await page.route(`**/api/backups/${id}/verify`, route => {verified++; return route.fulfill({json: {verified: true}})})
  await page.route(`**/api/backups/${id}/delete`, route => {expect(route.request().postDataJSON()).toEqual({confirm: true}); deleted++; retained = false; return route.fulfill({json: {}})})
  await openSettings(page, 'Backup & Restore')
  await page.getByRole('tab', {name: 'Backup History', exact: true}).click()
  const history = page.getByRole('region', {name: 'Backup history', exact: true})
  const actions = history.getByRole('button', {name: /^Actions for backup/})
  await actions.click(); await page.getByRole('button', {name: 'Verify archive', exact: true}).click()
  const verify = page.getByRole('dialog', {name: 'Verify backup archive', exact: true})
  await verify.getByRole('button', {name: 'Verify archive', exact: true}).click()
  await expect(history.getByText('Archive verified. Encryption, file hashes and SQLite integrity passed.')).toBeVisible()
  expect(verified).toBe(1)
  await actions.click(); await page.getByRole('button', {name: 'Delete archive', exact: true}).click()
  const confirm = page.getByRole('dialog', {name: 'Delete backup archive', exact: true})
  await confirm.getByRole('button', {name: 'Cancel', exact: true}).click(); expect(deleted).toBe(0)
  await expect(actions).toBeFocused()
  await actions.press('Enter'); await page.getByRole('button', {name: 'Delete archive', exact: true}).click()
  await page.getByRole('dialog', {name: 'Delete backup archive'}).getByRole('button', {name: 'Delete archive', exact: true}).click()
  await expect(history.getByText('No retained archives. Create a backup from Overview.')).toBeVisible()
  expect(deleted).toBe(1)
})
