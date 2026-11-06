import { expect, test } from '@playwright/test'
import { openSettings } from './support'

test.use({ locale: 'en-US', timezoneId: 'Europe/Oslo' })   // a 12-hour locale: nothing may fall back to AM/PM

test('Backup & Restore uses a 24-hour time control and no AM/PM anywhere', async ({ page }) => {
  await openSettings(page, 'Backup & Restore')
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
