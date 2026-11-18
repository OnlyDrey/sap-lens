import { expect, test } from '@playwright/test'
import { openSettings } from './support'

test.use({ locale: 'en-US', timezoneId: 'Europe/Oslo' })   // a 12-hour locale: nothing may fall back to AM/PM

test('Backup & Restore uses a 24-hour time control and no AM/PM anywhere', async ({ page }) => {
  await openSettings(page, 'Backup & Restore')
  await page.getByRole('tab', { name: 'Scheduling', exact: true }).click()
  const section = page.getByRole('region', { name: 'Automatic backup scheduling' })
  await expect(section).toBeVisible()
  const time = section.getByRole('textbox', { name: 'Backup daily time' })
  if (await time.count() === 0) {
    await section.getByLabel('Backup schedule type').selectOption('daily')
  }
  await expect(time).toBeVisible()
  expect(await time.evaluate(el => (el as HTMLInputElement).type)).toBe('text')         // not a locale-driven <input type="time">
  await expect(time).toHaveAttribute('placeholder', 'HH:mm')
  for (const [typed, expected] of [['00:00', '00:00'], ['12:00', '12:00'], ['14:30', '14:30'], ['6:05', '06:05']]) {
    await time.fill(typed); await time.blur()
    await expect(time).toHaveValue(expected)
    await expect(time).not.toHaveAttribute('aria-invalid', 'true')
  }
  await time.fill('02:30 PM')
  await expect(time).toHaveAttribute('aria-invalid', 'true')
  await time.blur()
  await expect(time).toHaveValue('06:05')                                                // an invalid entry is not kept
  await expect(section).not.toContainText(/\b\d{1,2}:\d{2}\s?(AM|PM)\b/i)
})

test('weekly automatic backups save an explicit time zone and accurately report enable and disable', async ({page}) => {
  let schedule = {enabled: false, mode: 'daily', time: '06:00', cron: '0 6 * * *', timezone: 'UTC', keep: 7, weekday: undefined as number | undefined}
  let revision = 0
  await page.route('**/api/backups/schedule', async route => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      expect(body.revision).toBe(revision)
      schedule = body.schedule; revision++
    }
    await route.fulfill({json: {revision, schedule, encryption_ready: true, requires_restart: false, next_runs: schedule.enabled ? ['2026-11-23T22:15:00Z'] : [], description: 'Weekly backup in Europe/Oslo', last_success: null, last_failure: null, attempts: []}})
  })
  await openSettings(page, 'Backup & Restore')
  await page.getByRole('tab', {name: 'Scheduling', exact: true}).click()
  const section = page.getByRole('region', {name: 'Automatic backup scheduling'})
  await section.getByLabel('Backup schedule type').selectOption('weekly')
  await section.getByLabel('Backup day', {exact: true}).selectOption('1')
  await section.getByRole('textbox', {name: 'Backup weekly time'}).fill('23:15')
  await section.getByRole('textbox', {name: 'Backup weekly time'}).blur()
  await section.getByLabel('Backup time zone').fill('Europe/Oslo')
  await section.getByRole('checkbox', {name: 'Enable automatic backups'}).check()
  await section.getByRole('button', {name: 'Save backup schedule'}).click()
  await expect(section.getByText('Automatic backup schedule saved and enabled.', {exact: true})).toBeVisible()
  expect(schedule).toMatchObject({enabled: true, mode: 'weekly', weekday: 1, time: '23:15', timezone: 'Europe/Oslo'})
  await section.getByRole('checkbox', {name: 'Enable automatic backups'}).uncheck()
  await section.getByRole('button', {name: 'Save backup schedule'}).click()
  await expect(section.getByText('Schedule saved. Automatic backups are disabled.', {exact: true})).toBeVisible()
})
