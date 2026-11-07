import { expect, test, type Page } from '@playwright/test'
import { THEMES, TAGS } from './matrix'
import { headers, openSettings } from './support'

/**
 * Central behavior of shared production components, rendered by Settings > Component Library (ComponentLibraryStates.tsx). Generic
 * interaction is tested here once; page specs test how each screen uses the component (its data, filters and decisions).
 */
async function library(page: Page) {
  await openSettings(page, 'Component Library')
  await page.getByRole('tab', { name: 'Status & Feedback', exact: true }).click()
  return page.getByRole('region', { name: 'Decision, chip and status previews', exact: true })
}

test.describe('shared component behavior', { tag: TAGS.component }, () => {
  test.beforeEach(async ({ request }) => { await request.post('/api/configuration/theme', { headers, data: { theme: 'light' } }) })

  test('DecisionChoice: nothing preselected, one pressed option, keyboard selection and a disabled group', async ({ page }) => {
    const preview = await library(page)
    const group = preview.getByRole('group', { name: 'Demo proposed decision', exact: true })
    await expect(group).toHaveAccessibleDescription('No decision is preselected.')
    const buttons = group.getByRole('button')
    await expect(buttons).toHaveText(['Investigate', 'Keep', 'Remove'])
    for (const button of await buttons.all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
    await group.getByRole('button', { name: 'Keep', exact: true }).click()
    await expect(group.getByRole('button', { name: 'Keep', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(preview.getByText('Selected decision: Keep', { exact: true })).toBeVisible()
    await group.getByRole('button', { name: 'Keep', exact: true }).press('Tab')
    await expect(group.getByRole('button', { name: 'Remove', exact: true })).toBeFocused()
    await page.keyboard.press('Space')
    await expect(group.getByRole('button', { name: 'Remove', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(group.getByRole('button', { name: 'Keep', exact: true })).toHaveAttribute('aria-pressed', 'false')
    await expect(group).not.toHaveAccessibleDescription('No decision is preselected.')
    const disabled = preview.getByRole('group', { name: 'Demo disabled decision', exact: true })
    for (const button of await disabled.getByRole('button').all()) await expect(button).toBeDisabled()
  })

  test('FilterChip: each chip has a named remove button that works by pointer and keyboard', async ({ page }) => {
    const preview = await library(page)
    const reset = preview.getByRole('button', { name: 'Reset demo chips', exact: true })
    await expect(reset).toBeDisabled()
    await preview.getByRole('button', { name: 'Remove PFCG filter', exact: true }).click()
    await expect(preview.getByRole('button', { name: /^Remove .* filter$/ })).toHaveCount(2)
    await preview.getByRole('button', { name: 'Remove SU01 filter', exact: true }).focus()
    await page.keyboard.press('Enter')
    await preview.getByRole('button', { name: 'Remove SE16N filter', exact: true }).click()
    await expect(preview.getByText('No transaction filters', { exact: true })).toBeVisible()
    await reset.click()
    await expect(preview.getByRole('button', { name: /^Remove .* filter$/ })).toHaveCount(3)
  })

  test('StatusPill and status badges: a switch only when it can be toggled, with one wording for every state', async ({ page }) => {
    const preview = await library(page)
    const toggle = preview.getByRole('switch', { name: 'Demo feature enabled', exact: true })
    await expect(toggle).toHaveAttribute('aria-checked', 'true'); await expect(toggle).toHaveText('Enabled')
    await toggle.click(); await expect(toggle).toHaveAttribute('aria-checked', 'false'); await expect(toggle).toHaveText('Disabled')
    await toggle.press('Space'); await expect(toggle).toHaveAttribute('aria-checked', 'true')
    const locked = preview.getByRole('switch', { name: 'Demo locked feature', exact: true })
    await expect(locked).toBeDisabled()
    await expect(preview.getByRole('switch')).toHaveCount(2)                                     // the read-only pill is not announced as a control
    const badges = preview.getByRole('region', { name: 'Status pill and badge preview', exact: true })
    for (const text of ['Enabled', 'Disabled', 'Static', 'Dynamic', 'Mode unavailable']) await expect(badges.getByText(text, { exact: true }).first()).toBeVisible()
  })

  test('IdPill and UserGroupCell: identifiers, several groups and an announced missing group', async ({ page }) => {
    const preview = await library(page)
    await expect(preview.getByText('R001', { exact: true })).toBeVisible(); await expect(preview.getByText('A010', { exact: true })).toBeVisible()
    const table = preview.getByRole('table', { name: 'SAP User Group cells', exact: true })
    await expect(table.getByRole('row', { name: /Several groups/ })).toContainText('FINANCE, SUPPORT')
    await expect(table.getByRole('row', { name: /No group/ }).getByText('No SAP User Group', { exact: true })).toBeAttached()
  })

  test('TimeInput24: only valid 24-hour times are accepted and invalid text is marked, then restored on blur', async ({ page }) => {
    const preview = await library(page)
    const input = preview.getByRole('textbox', { name: 'Demo backup time (24-hour, HH:mm)', exact: true })
    await input.fill('23:45'); await expect(preview.getByText('Accepted time: 23:45', { exact: true })).toBeVisible()
    await input.fill('7:5 PM'); await expect(input).toHaveAttribute('aria-invalid', 'true')
    await expect(preview.getByText('Accepted time: 23:45', { exact: true })).toBeVisible()        // invalid text never replaces the value
    await input.blur(); await expect(input).toHaveValue('23:45'); await expect(input).not.toHaveAttribute('aria-invalid', 'true')
  })

  test('ConfirmDialog: named destructive action, focus stays in the dialog, Escape and Cancel cancel, Confirm confirms', async ({ page }) => {
    const preview = await library(page)
    const open = preview.getByRole('button', { name: 'Delete demo record', exact: true })
    await open.click()
    const dialog = page.getByRole('dialog', { name: 'Delete demo record', exact: true })
    await expect(dialog).toBeVisible()
    for (let index = 0; index < 6; index++) {                                                     // focus is trapped while the dialog is open
      await page.keyboard.press('Tab')
      expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBeTruthy()
    }
    await page.keyboard.press('Escape'); await expect(dialog).toBeHidden()
    await expect(preview.getByText('Deletion cancelled', { exact: true })).toBeVisible()
    await open.click(); await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).toBeHidden()
    await open.click(); await dialog.getByRole('button', { name: 'Delete demo record', exact: true }).click()
    await expect(preview.getByText('Demo record deleted', { exact: true })).toBeVisible()
  })
})

// Focus appearance and colors differ per theme, and narrow screens wrap: the only part of this file that is repeated per theme and width.
for (const theme of THEMES) for (const width of [375, 1280]) test(`shared component previews fit and show a visible focus ring in ${theme} at ${width}px`, { tag: [TAGS.component, TAGS.visual] }, async ({ page, request }) => {
  await request.post('/api/configuration/theme', { headers, data: { theme } })
  await page.setViewportSize({ width, height: 900 })
  const preview = await library(page)
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  const keep = preview.getByRole('group', { name: 'Demo proposed decision', exact: true }).getByRole('button', { name: 'Keep', exact: true })
  await keep.focus(); await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Tab')       // keyboard focus, so :focus-visible applies
  await expect(keep).toBeFocused()
  const ring = await keep.evaluate(element => { const style = getComputedStyle(element); return { style: style.outlineStyle, width: parseFloat(style.outlineWidth), color: style.outlineColor, background: getComputedStyle(document.body).backgroundColor } })
  expect(ring.style).not.toBe('none'); expect(ring.width).toBeGreaterThan(0); expect(ring.color).not.toBe(ring.background)
  const box = (await preview.boundingBox())!
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width)
})
