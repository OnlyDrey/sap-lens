import { expect, test } from '@playwright/test'
import {openSettings} from './support'

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
  months: 24, count: 0, protected: 3, digest: 'd'.repeat(64), reasons: { 'Immutable audit evidence': 3 },
  sample: [], protected_sample: [{name: 'Q1 2024 review', state: 'Closed', reason: 'Immutable audit evidence'}], truncated: false,
}

async function open(page: import('@playwright/test').Page) {
  await openSettings(page, 'Backup & Restore')
  await page.getByRole('tab', { name: 'Retention', exact: true }).click()
}

test('source and review retention are separate, each needs its own preview and approval', async ({ page }) => {
  const approved = { source: false, review: false }
  const posted: unknown[] = []
  await page.route('**/api/retention', route => route.fulfill({ json: status(approved.source ? 'approved' : 'awaiting_approval', approved.review ? 'approved' : 'awaiting_approval') }))
  await page.route('**/api/retention/preview?category=*', route => route.fulfill({ json: route.request().url().includes('category=review') ? reviewPreview : sourcePreview }))
  await page.route('**/api/retention/approve', async route => { const body = route.request().postDataJSON(); posted.push(body); approved[body.category as 'source' | 'review'] = true; await route.fulfill({ json: {} }) })
  await open(page)
  const panel = page.getByRole('region', { name: 'Data retention', exact: true })
  await expect(panel.locator('tbody tr')).toHaveCount(3)
  const sourceRow = panel.getByRole('row').filter({hasText: 'Source revisions'})
  await expect(sourceRow).toContainText('Needs approval')
  await expect(panel.getByRole('button', { name: /^Approve / })).toHaveCount(0)
  await panel.getByRole('button', {name: 'Configure Review evidence', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'Configure Review evidence'})
  const review = dialog.getByRole('region', {name: 'Review retention'})
  await expect(dialog.getByRole('button',{name:/^Approve /})).toHaveCount(0)
  await review.getByRole('button',{name:'Preview review cleanup',exact:true}).click()
  await expect(review).toContainText('3 review periods are protected')
  await expect(review).toContainText('Q1 2024 review')
  await expect(review).toContainText('Immutable audit evidence')
  await expect(review).toContainText('does not delete immutable periods')
  expect(approved.source).toBe(false)
  const approve = review.getByRole('button', { name: 'Approve review policy' })
  await expect(approve).toBeDisabled()
  await review.getByRole('checkbox', { name: /I reviewed this review preview/ }).check()
  await approve.click()
  await expect(review).toContainText('Policy approved; evidence protected')
  expect(posted).toEqual([{ category: 'review', confirm: true, preview_digest: 'd'.repeat(64) }])
  await dialog.getByRole('button', {name: 'Close', exact: true}).click()
  await expect(sourceRow).toContainText('Needs approval')
  await panel.getByRole('button', {name: 'Preview Source revisions cleanup', exact: true}).click()
  const source = page.getByRole('dialog', {name: 'Configure Source revisions'}).getByRole('region', {name: 'Source retention'})
  await expect(source).toContainText('3 item(s), 3.0 MB eligible')
  await expect(source).toContainText('1 waiting to be classified')
})

test('retention periods are saved explicitly, bounded and independent per category', async ({ page }) => {
  const saved: unknown[] = []
  let current = status('approved', 'approved')
  await page.route('**/api/retention', route => route.fulfill({ json: current }))
  await page.route('**/api/retention/policy', async route => { const body=route.request().postDataJSON();saved.push(body);current=status('approved','awaiting_approval');current.policy.review_months=body.review_months;current.categories.review.months=body.review_months;await route.fulfill({ json: current }) })
  await open(page)
  const panel = page.getByRole('region', { name: 'Data retention', exact: true })
  const save = panel.getByRole('button', { name: 'Save retention settings' })
  await expect(save).toBeDisabled()
  await panel.getByRole('button', {name: 'Configure Review evidence'}).click()
  const dialog = page.getByRole('dialog', {name: 'Configure Review evidence'})
  const reviewMonths = dialog.getByRole('spinbutton', { name: 'Review retention period (months)' })
  await reviewMonths.fill('3')
  await expect(reviewMonths).toHaveValue('6')
  await reviewMonths.fill('200')
  await expect(reviewMonths).toHaveValue('120')
  await reviewMonths.fill('12')
  await dialog.getByRole('button', {name: 'Save policy', exact: true}).click()
  await expect(dialog.getByText('Retention policy saved. Shortened periods require renewed approval.')).toBeVisible()
  await dialog.getByRole('button', {name: 'Close', exact: true}).click()
  await expect(panel.getByRole('row').filter({hasText: 'Source revisions'})).toContainText('24 months')
  await expect(panel.getByRole('row').filter({hasText: 'Review evidence'})).toContainText('12 months')
  await expect(panel.getByRole('row').filter({hasText: 'Review evidence'})).toContainText('Needs approval')
  expect(saved).toEqual([{ enabled: true, months: 24, review_months: 12, backup_days: 90 }])
})

test('restore holds keep previews available, block approval and retain expandable history', async ({page}) => {
  const current = status('awaiting_approval','awaiting_approval',[{at:'2026-11-18T09:00:00Z',trigger:'restore',status:'changed',category:'source',months:24,by:'admin.synthetic',bytes:0,message:'Hold applied; previous approvals are void.'}])
  current.quiet_until='2099-01-01T00:00:00Z'
  let approved=0
  await page.route('**/api/retention', route=>route.fulfill({json:current}))
  await page.route('**/api/retention/preview?category=source', route=>route.fulfill({json:sourcePreview}))
  await page.route('**/api/retention/approve', route=>{approved++;return route.fulfill({json:{}})})
  await open(page)
  const panel=page.getByRole('region',{name:'Data retention',exact:true})
  await expect(panel).toContainText('No cleanup until')
  await panel.getByRole('button',{name:'Preview Source revisions cleanup',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'Configure Source revisions'})
  await expect(dialog).toContainText('3 item(s), 3.0 MB eligible')
  await dialog.getByRole('checkbox',{name:/I reviewed this source preview/}).check()
  await expect(dialog.getByRole('button',{name:'Approve source cleanup',exact:true})).toBeDisabled()
  expect(approved).toBe(0)
  await dialog.getByRole('button',{name:'Close',exact:true}).click()
  await panel.getByText('Retention history',{exact:true}).click()
  await expect(panel.getByText(/Hold applied; previous approvals are void/)).toBeVisible()
})

for(const width of [375,800,1280,1600] as const) for(const theme of ['light','dark'] as const){
 test(`retention policies stay compact at ${width}px in ${theme}`,async({page,request},testInfo)=>{
  await request.post('/api/configuration/theme',{data:{theme}})
  try{
   await page.setViewportSize({width,height:900})
   await page.route('**/api/retention',route=>route.fulfill({json:status('awaiting_approval','awaiting_approval')}))
   await open(page)
   const panel=page.getByRole('region',{name:'Data retention',exact:true})
   await expect(panel.locator('tbody tr')).toHaveCount(3)
   await expect(page.locator('html')).toHaveAttribute('data-theme',theme)
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true)
   await panel.scrollIntoViewIfNeeded()
   await page.screenshot({path:testInfo.outputPath(`retention-${width}-${theme}.png`),fullPage:true})
   await panel.getByRole('button',{name:'Configure Automatic backups',exact:true}).click()
   const dialog=page.getByRole('dialog',{name:'Configure Automatic backups'})
   await expect(dialog.getByRole('spinbutton',{name:'Backup retention period (days)'})).toHaveValue('90')
   await dialog.getByRole('button',{name:'Close',exact:true}).click()
   await expect(panel.getByRole('button',{name:'Configure Automatic backups',exact:true})).toBeFocused()
  }finally{await request.post('/api/configuration/theme',{data:{theme:'dark'}})}
 })
}

test('backup retention shows its 90-day coverage, protects manual and migration backups and needs its own approval', async ({ page }) => {
  let approved = false
  const posted: unknown[] = []
  const preview = {
    days: 90, keep: 7, count_limit: [],
    count: 1, bytes: 2_097_152, digest: 'e'.repeat(64), counts: { automatic: 4, manual: 2, unclassified: 1, migration: 1 },
    reasons: { 'Manual backup: removed only by an administrator': 2, 'Migration backup waiting for administrator confirmation': 1, 'No reliable classification (protected)': 1 },
    sample: [{ id: 'f'.repeat(32), created: '2025-06-01T00:00:00+00:00', bytes: 2_097_152, age_days: 200, note: '', rule: 'Older than 90 days', rules: ['age'] }], protected_sample: [], truncated: false,
  }
  await page.route('**/api/retention', route => route.fulfill({ json: status('approved', 'approved', [], approved ? 'approved' : 'awaiting_approval') }))
  await page.route('**/api/retention/preview?category=backup', route => route.fulfill({ json: preview }))
  await page.route('**/api/retention/approve', async route => { posted.push(route.request().postDataJSON()); approved = true; await route.fulfill({ json: {} }) })
  await open(page)
  const panel = page.getByRole('region', { name: 'Data retention', exact: true })
  await panel.getByRole('button', {name: 'Configure Automatic backups'}).click()
  const backup = page.getByRole('dialog', {name: 'Configure Automatic backups'}).getByRole('region', { name: 'Backup retention' })
  await expect(backup.getByRole('spinbutton', { name: 'Backup retention period (days)' })).toHaveValue('90')
  await expect(backup).toContainText('Automatic backups: 4 · manual (kept): 2 · migration (kept): 1')
  await expect(backup.getByLabel('Backup retention rules')).toContainText('Automatic backups older than 90 days are removed only after approval')
  await expect(backup.getByLabel('Backup retention rules')).toContainText('Recent backups are protected')
  await expect(backup).toContainText('Last successful cleanup:')
  await expect(backup).toContainText('Next scheduled check:')
  await backup.getByRole('button', { name: 'Preview backup cleanup' }).click()
  await expect(backup).toContainText('1 automatic backup(s)')
  await expect(backup).toContainText('rule: Older than 90 days')
  await expect(backup.getByText(/Count limit:/)).toHaveCount(0)
  await expect(backup).toContainText('Protected: 2 · Manual backup')
  await expect(backup).toContainText('Protected: 1 · Migration backup waiting for administrator confirmation')
  await expect(backup).toContainText('historical records')
  await backup.getByRole('checkbox', { name: /I reviewed this backup preview/ }).check()
  await backup.getByRole('button', { name: 'Approve backup cleanup' }).click()
  await expect(backup).toContainText('Automatic cleanup approved')
  expect(posted).toEqual([{ category: 'backup', confirm: true, preview_digest: 'e'.repeat(64) }])
})
