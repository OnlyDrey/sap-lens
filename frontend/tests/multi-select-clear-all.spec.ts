import { test, expect } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

test('multi-select Clear all is a separate right-aligned ghost action with a live count that clears only its own field', async ({ page }) => {
  await openSod(page, 'Access Explorer')
  const pick = async (label: string, values: string[]) => {
    const control = page.getByRole('combobox', { name: label, exact: true })
    for (const value of values) { await control.click(); await control.fill(value); await page.getByRole('option', { name: value, exact: true }).click() }
    await control.press('Escape')
  }
  await pick('SAP User Group', ['FIN', 'P2P'])
  const selected = page.getByRole('group', { name: 'Selected SAP User Group', exact: true })
  const clear = selected.getByRole('button', { name: 'Clear all SAP User Group selections', exact: true })
  await expect(clear).toContainText('Clear all (2)')
  // Not a chip: it sits below the chips, right aligned, and is not inside the chip row.
  const chips = selected.locator('.flex').first()
  const [chipBox, clearBox, groupBox] = await Promise.all([chips.boundingBox(), clear.boundingBox(), selected.boundingBox()])
  expect(clearBox!.y).toBeGreaterThanOrEqual(chipBox!.y + chipBox!.height - 1)
  expect(Math.abs((clearBox!.x + clearBox!.width) - (groupBox!.x + groupBox!.width))).toBeLessThanOrEqual(2)
  await expect(clear.locator('svg')).toHaveCount(1)
  await expect(clear).toHaveClass(/ui-button-ghost/)
  // The count follows removals immediately; one remaining value still offers the action.
  await selected.getByRole('button', { name: 'Remove SAP User Group P2P', exact: true }).click()
  await expect(clear).toContainText('Clear all (1)')
  // Clearing one field leaves a different multi-select untouched.
  await pick('Risk ID', ['R1'])
  await selected.getByRole('button', { name: 'Clear all SAP User Group selections', exact: true }).click()
  await expect(selected).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Selected Risk ID', exact: true })).toBeVisible()
})
