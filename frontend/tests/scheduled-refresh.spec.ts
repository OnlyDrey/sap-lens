import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

const headers = { 'X-SAP-Lens': 'browser-test-session' }
const config = async (request: APIRequestContext) => (await (await request.get('/api/configuration', { headers })).json()).settings
test.beforeEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }) })
test.afterEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }) })

async function open(page: Page) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Runtime & Scheduling', exact: true }).click()
  return page.getByRole('region', { name: 'Scheduled refresh', exact: true })
}

test('a daily schedule is explained, applied, persisted and shown with its next run', async ({ page, request }) => {
  const section = await open(page)
  await expect(section.getByRole('switch', { name: 'Enable scheduled refresh' })).toHaveAttribute('aria-checked', 'false')
  await expect(section.getByLabel('Last successful run').or(section.getByText('Never').first())).toBeVisible()
  await section.getByRole('switch', { name: 'Enable scheduled refresh' }).click()
  await section.getByLabel('Daily time (24-hour)').fill('05:30')
  await section.getByRole('combobox', { name: 'Time zone', exact: true }).fill('UTC')
  await page.getByRole('option', { name: 'UTC', exact: true }).click()
  await expect(section.getByRole('status').filter({ hasText: 'At 05:30 every day (UTC)' })).toBeVisible()
  await expect(section).toContainText('Next runs:')
  expect((await config(request)).refresh_schedule.enabled).toBe(false)
  await page.getByRole('button', { name: 'Apply settings', exact: true }).click()
  await expect.poll(async () => (await config(request)).refresh_schedule).toEqual({ enabled: true, mode: 'daily', time: '05:30', cron: '0 6 * * *', timezone: 'UTC' })
  await page.reload()
  const again = await open(page)
  await expect(again.getByRole('switch', { name: 'Enable scheduled refresh' })).toHaveAttribute('aria-checked', 'true')
  await expect(again.getByLabel('Daily time (24-hour)')).toHaveValue('05:30')
  await expect(again.locator('dl')).not.toContainText('Disabled')
})

test('cron expressions are validated with readable reasons and invalid schedules are not saved', async ({ page, request }) => {
  const section = await open(page)
  await section.getByRole('switch', { name: 'Enable scheduled refresh' }).click()
  await section.getByRole('button', { name: 'Advanced (cron)' }).click()
  const cron = section.getByLabel('Cron expression')
  await cron.fill('0 6 * * 1-5')
  await expect(section.getByRole('status').filter({ hasText: 'At 06:00 on weekdays (local time)' })).toBeVisible()
  await cron.fill('99 * * * *')
  await expect(section.getByRole('alert')).toContainText('minute must be between 0 and 59')
  await cron.fill('*/2 * * * *')
  await expect(section.getByRole('alert')).toContainText('at least 5 minutes apart')
  await cron.fill('0 0 31 2 *')
  await expect(section.getByRole('alert')).toContainText('never runs')
  await cron.fill('*/2 * * * *')
  await page.getByRole('button', { name: 'Apply settings', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: /5 minutes/ }).first()).toBeVisible()
  expect((await config(request)).refresh_schedule.enabled).toBe(false)
})

test('Windows tray settings live in the runtime section, only for the Windows Desktop application', async ({ page }) => {
  await page.addInitScript(() => { (window as unknown as { pywebview: unknown }).pywebview = { api: { choose_csv: async () => null, desktop_runtime: async () => ({ windows: true, startup_supported: true, tray_available: true, warning: null }) } } })
  const section = await open(page)
  const tray = page.getByRole('region', { name: 'Windows Desktop background operation', exact: true })
  await expect(tray).toContainText('apply only to the Windows Desktop application')
  await expect(section.getByText('Where it runs')).toBeVisible()
  await page.getByRole('tab', { name: 'About SAP Lens', exact: true }).click()
  await expect(tray).toHaveCount(0)
})

test('the runtime note says what each deployment needs', async ({ page }) => {
  const section = await open(page)
  await section.getByText('Where it runs').click()
  await expect(section).toContainText('Windows Desktop: only while SAP Lens is running')
  await expect(section).toContainText('Windows Service, Linux Docker, Linux native or systemd')
})
