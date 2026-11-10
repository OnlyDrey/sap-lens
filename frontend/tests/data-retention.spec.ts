import { expect, test } from '@playwright/test'

const category = (state: string, months = 24, approval: unknown = null) => ({ months, state, approval })
const status = (source: string, review: string, history: unknown[] = [], backup = 'awaiting_approval') => ({
  policy: { enabled: true, months: 24, review_months: 24, backup_days: 90 },
  categories: { source: category(source), review: category(review), backup: { days: 90, state: backup, approval: null, last_cleanup: '2026-01-03T00:00:00+00:00', next_check: '2026-01-02T00:00:00+00:00', last_preview: { counts: { automatic: 4, manual: 2, unclassified: 0, migration: 1 } } } }, last_check: '2026-01-01T00:00:00+00:00', quiet_until: '', history,
  scope: { backup: ['Automatic (scheduled) backups older than the period'], source: ['Superseded role, user and SoD matrix snapshots'], review: ['Completed review periods older than the period, with their decisions, actions and exclusively owned evidence'] },
  protected_note: 'Current source data, active and incomplete review periods, anything still referenced, the report log, backups and the newest completed period are never removed.',
})
const sourcePreview = {
  months: 24, count: 3, bytes: 3_145_728, digest: 'c'.repeat(64), categories: { 'users snapshots': { count: 3, bytes: 3_145_728, oldest_days: 900 } },
  protected: { referenced: 4, recent: 1, kept_newest: 2, unclassified: 1, unrecognised: 0 }, sample: [], truncated: false,
}
const reviewPreview = {
  months: 24, count: 1, protected: 3, digest: 'd'.repeat(64), reasons: { 'Active or incomplete review period': 2, 'Newest completed period (comparison baseline)': 1 },
  sample: [{ name: 'Q1 2024 review', state: 'Closed', completed: '2024-04-15T00:00:00+00:00', age_days: 900, decisions: 42, actions: 3 }], protected_sample: [], truncated: false,
}

async function open(page: import('@playwright/test').Page) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Backup & Restore', exact: true }).click()
}

test('source and review retention are separate, each needs its own preview and approval', async ({ page }) => {
  const approved = { source: false, review: false }
  const posted: unknown[] = []
  await page.route('**/api/retention', route => route.fulfill({ json: status(approved.source ? 'approved' : 'awaiting_approval', approved.review ? 'approved' : 'awaiting_approval') }))
  await page.route('**/api/retention/preview?category=*', route => route.fulfill({ json: route.request().url().includes('category=review') ? reviewPreview : sourcePreview }))
  await page.route('**/api/retention/approve', async route => { const body = route.request().postDataJSON(); posted.push(body); approved[body.category as 'source' | 'review'] = true; await route.fulfill({ json: {} }) })
  await open(page)
  const panel = page.getByRole('region', { name: 'Data retention', exact: true })
  const source = panel.getByRole('region', { name: 'Source retention' })
  const review = panel.getByRole('region', { name: 'Review retention' })
  await expect(source).toContainText('Waiting for administrator approval')
  await expect(review).toContainText('Completed review periods')
  await expect(panel.getByRole('button', { name: /Approve .* cleanup/ })).toHaveCount(0)        // nothing can be approved before a preview is seen
  await review.getByRole('button', { name: 'Preview review cleanup' }).click()
  await expect(review).toContainText('1 completed review period(s) eligible, 3 protected')
  await expect(review).toContainText('Q1 2024 review')
  await expect(review).toContainText('Protected: 2 · Active or incomplete review period')
  await expect(review).toContainText('can be undone')
  await expect(source.getByRole('button', { name: 'Approve source cleanup' })).toHaveCount(0)    // the other category is unaffected
  const approve = review.getByRole('button', { name: 'Approve review cleanup' })
  await expect(approve).toBeDisabled()
  await review.getByRole('checkbox', { name: /I reviewed this review preview/ }).check()
  await approve.click()
  await expect(review).toContainText('Automatic cleanup approved')
  await expect(source).toContainText('Waiting for administrator approval')
  expect(posted).toEqual([{ category: 'review', confirm: true, preview_digest: 'd'.repeat(64) }])
  await source.getByRole('button', { name: 'Preview source cleanup' }).click()
  await expect(source).toContainText('3 item(s), 3.0 MB eligible')
  await expect(source).toContainText('1 waiting to be classified')
})

test('retention periods are saved explicitly, bounded and independent per category', async ({ page }) => {
  const saved: unknown[] = []
  await page.route('**/api/retention', route => route.fulfill({ json: status('approved', 'approved') }))
  await page.route('**/api/retention/policy', async route => { saved.push(route.request().postDataJSON()); await route.fulfill({ json: status('approved', 'awaiting_approval') }) })
  await open(page)
  const panel = page.getByRole('region', { name: 'Data retention', exact: true })
  const save = panel.getByRole('button', { name: 'Save retention settings' })
  await expect(save).toBeDisabled()
  const reviewMonths = panel.getByRole('spinbutton', { name: 'Review retention period (months)' })
  await reviewMonths.fill('3')
  await expect(reviewMonths).toHaveValue('6')
  await reviewMonths.fill('36')
  await expect(panel.getByRole('spinbutton', { name: 'Source retention period (months)' })).toHaveValue('24')
  await save.click()
  expect(saved).toEqual([{ enabled: true, months: 24, review_months: 36, backup_days: 90 }])
})

test('backup retention shows its 90-day coverage, protects manual and migration backups and needs its own approval', async ({ page }) => {
  let approved = false
  const posted: unknown[] = []
  const preview = {
    days: 90, keep: 7, count_limit: [{ id: 'c'.repeat(32), rule: 'Beyond the newest 7 automatic backups: removed by the count limit at the next scheduled backup, without approval' }],
    count: 1, bytes: 2_097_152, digest: 'e'.repeat(64), counts: { automatic: 4, manual: 2, unclassified: 1, migration: 1 },
    reasons: { 'Manual backup: removed only by an administrator': 2, 'Migration backup waiting for administrator confirmation': 1, 'No reliable classification (protected)': 1 },
    sample: [{ id: 'f'.repeat(32), created: '2025-06-01T00:00:00+00:00', bytes: 2_097_152, age_days: 200, note: '', rule: 'Older than 90 days and beyond the newest 7 automatic backups', rules: ['age', 'count'] }], protected_sample: [], truncated: false,
  }
  await page.route('**/api/retention', route => route.fulfill({ json: status('approved', 'approved', [], approved ? 'approved' : 'awaiting_approval') }))
  await page.route('**/api/retention/preview?category=backup', route => route.fulfill({ json: preview }))
  await page.route('**/api/retention/approve', async route => { posted.push(route.request().postDataJSON()); approved = true; await route.fulfill({ json: {} }) })
  await open(page)
  const panel = page.getByRole('region', { name: 'Data retention', exact: true })
  const backup = panel.getByRole('region', { name: 'Backup retention' })
  await expect(backup.getByRole('spinbutton', { name: 'Backup retention period (days)' })).toHaveValue('90')
  await expect(backup).toContainText('Automatic backups: 4 · manual (kept): 2 · migration (kept): 1')
  await expect(backup.getByLabel('Backup retention rules')).toContainText('Rule 1, count limit')
  await expect(backup.getByLabel('Backup retention rules')).toContainText('Rule 2, age limit: automatic backups older than 90 days')
  await expect(backup.getByLabel('Backup retention rules')).toContainText('a maximum, not a guarantee')
  await expect(backup).toContainText('Last successful cleanup:')
  await expect(backup).toContainText('Next scheduled check:')
  await backup.getByRole('button', { name: 'Preview backup cleanup' }).click()
  await expect(backup).toContainText('1 automatic backup(s)')
  await expect(backup).toContainText('rule: Older than 90 days and beyond the newest 7 automatic backups')
  await expect(backup).toContainText('1 more automatic backup(s) are younger than 90 days but beyond the newest 7')
  await expect(backup).toContainText('Count limit: Beyond the newest 7 automatic backups')
  await expect(backup).toContainText('Protected: 2 · Manual backup')
  await expect(backup).toContainText('Protected: 1 · Migration backup waiting for administrator confirmation')
  await expect(backup).toContainText('historical records')
  await backup.getByRole('checkbox', { name: /I reviewed this backup preview/ }).check()
  await backup.getByRole('button', { name: 'Approve backup cleanup' }).click()
  await expect(backup).toContainText('Automatic cleanup approved')
  expect(posted).toEqual([{ category: 'backup', confirm: true, preview_digest: 'e'.repeat(64) }])
})
