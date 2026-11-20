import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { headers } from './support'
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
  await section.getByLabel('Daily time').fill('05:30')
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
  await expect(again.getByLabel('Daily time')).toHaveValue('05:30')
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

test('the runtime note says what each deployment needs', async ({ page }) => {
  const section = await open(page)
  await section.getByText('Where it runs').click()
  await expect(section).toContainText('Windows Desktop: only while the AuthLens window is open')
  await expect(section).toContainText('Windows service, Linux server or systemd')
})


test('daily time and timezone labels and controls align without helper-text offsets',async({page})=>{
 await page.setViewportSize({width:1280,height:900})
 const section=await open(page)
 const time=section.getByLabel('Daily time',{exact:true}),zone=section.getByRole('combobox',{name:'Time zone',exact:true})
 const a=await time.boundingBox(),b=await zone.boundingBox();expect(a).not.toBeNull();expect(b).not.toBeNull()
 expect(Math.abs(a!.y-b!.y)).toBeLessThanOrEqual(1)
 const labels=await section.locator('.schedule-grid label').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top))
 expect(Math.abs(labels[0]-labels[1])).toBeLessThanOrEqual(1)
 await expect(section.getByText('24-hour time (HH:mm)',{exact:true})).toBeVisible()
})
