import { expect, test } from '@playwright/test'

const baseStatus = (state: string, approval: unknown = null, history: unknown[] = []) => ({
  policy: { enabled: true, months: 24 }, state, approval, last_check: '2026-01-01T00:00:00+00:00', last_preview: {}, history,
  scope: [], protected_note: 'Review decisions, evidence, review periods and their reports, backups and anything still referenced are never removed.',
})
const preview = {
  months: 24, count: 3, bytes: 3_145_728, digest: 'c'.repeat(64), categories: { 'users snapshots': { count: 3, bytes: 3_145_728, oldest_days: 900 } },
  protected: { referenced: 4, recent: 1, kept_newest: 2, unclassified: 0 }, sample: [], truncated: false,
}

test('the first destructive cleanup needs a preview and an explicit administrator approval', async ({ page }) => {
  let approved = false
  const posted: unknown[] = []
  await page.route('**/api/retention', route => route.fulfill({ json: approved
    ? baseStatus('approved', { by: 'Admin', at: '2026-01-02T00:00:00+00:00', months: 24, valid: true }, [{ at: '2026-01-02T00:00:00+00:00', trigger: 'manual', status: 'completed', months: 24, removed: { 'users snapshots': 3 }, bytes: 3145728, by: 'Admin', message: '' }])
    : baseStatus('awaiting_approval') }))
  await page.route('**/api/retention/preview', route => route.fulfill({ json: preview }))
  await page.route('**/api/retention/approve', async route => { posted.push(route.request().postDataJSON()); approved = true; await route.fulfill({ json: {} }) })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Backup & Restore', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Data retention' })
  await expect(panel).toContainText('Waiting for administrator approval')
  await expect(panel.getByRole('spinbutton', { name: 'Retention period (months)' })).toHaveValue('24')
  await expect(panel.getByRole('button', { name: 'Approve and clean up' })).toHaveCount(0)    // nothing can be approved before a preview is seen
  await panel.getByRole('button', { name: 'Preview cleanup' }).click()
  await expect(panel).toContainText('3 item(s), 3.0 MB, older than 24 months would be removed')
  await expect(panel).toContainText('4 still referenced')
  const approve = panel.getByRole('button', { name: 'Approve and clean up' })
  await expect(approve).toBeDisabled()
  expect(posted).toEqual([])
  await panel.getByRole('checkbox', { name: /I reviewed this preview/ }).check()
  await approve.click()
  await expect(panel).toContainText('Automatic cleanup approved')
  expect(posted).toEqual([{ confirm: true, preview_digest: 'c'.repeat(64) }])
  await panel.getByText('Retention history').click()
  await expect(panel).toContainText('manual · completed · Admin')
})

test('changing the retention period is saved explicitly and bounded', async ({ page }) => {
  const saved: unknown[] = []
  await page.route('**/api/retention', route => route.fulfill({ json: baseStatus('approved', { by: 'Admin', at: '2026-01-02T00:00:00+00:00', months: 24, valid: true }) }))
  await page.route('**/api/retention/policy', async route => { saved.push(route.request().postDataJSON()); await route.fulfill({ json: baseStatus('awaiting_approval') }) })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Backup & Restore', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Data retention' })
  const months = panel.getByRole('spinbutton', { name: 'Retention period (months)' })
  const save = panel.getByRole('button', { name: 'Save retention settings' })
  await expect(save).toBeDisabled()
  await months.fill('3')
  await expect(months).toHaveValue('6')
  await months.fill('12')
  await save.click()
  expect(saved).toEqual([{ enabled: true, months: 12 }])
})
