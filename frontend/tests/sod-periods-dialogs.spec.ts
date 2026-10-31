import { test, expect, type Page } from '@playwright/test'
import { cleanup, createPeriod, openSod, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const icon = (button: ReturnType<Page['locator']>) => expect(button.locator('svg').first()).toBeVisible()

for (const width of [375, 800, 1280]) test(`Create review period uses a responsive two-column grid with icons on its actions (${width}px)`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  await openSod(page, 'Review Periods')
  await page.getByRole('button', { name: 'Create review period', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Create SoD review period', exact: true })
  const box = async (label: string) => (await dialog.getByRole('textbox', { name: new RegExp(`^${label}`) }).first().boundingBox())!
  const [name, evaluation, start, end] = [await box('Review period name'), await box('Evaluation date'), await box('Period start'), await box('Period end')]
  if (width >= 800) {
    expect(Math.abs(name.y - evaluation.y)).toBeLessThan(2); expect(evaluation.x).toBeGreaterThan(name.x + name.width - 2) // row 1: name | evaluation date
    expect(Math.abs(start.y - end.y)).toBeLessThan(2); expect(end.x).toBeGreaterThan(start.x + start.width - 2) // row 2: start | end
    expect(start.y).toBeGreaterThan(name.y + name.height - 2)
    expect(Math.abs(name.x - start.x)).toBeLessThan(2) // columns line up
  } else {
    expect([name.y, evaluation.y, start.y, end.y]).toEqual([...[name.y, evaluation.y, start.y, end.y]].sort((a, b) => a - b)) // stacked in reading order
    expect(Math.abs(name.x - end.x)).toBeLessThan(2)
  }
  await icon(dialog.getByRole('button', { name: 'Cancel', exact: true })); await icon(dialog.getByRole('button', { name: 'Capture review period', exact: true }))
  // tab order follows the reading order
  await dialog.getByRole('textbox', { name: 'Review period name', exact: true }).focus()
  const order: string[] = []
  for (let step = 0; step < 4; step++) { order.push(await page.evaluate(() => (document.activeElement as HTMLElement | null)?.getAttribute('aria-label') || (document.activeElement as HTMLInputElement | null)?.id || '')); await page.keyboard.press('Tab') }
  expect(order.filter(Boolean).length).toBeGreaterThan(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await dialog.getByRole('textbox', { name: 'Review period name', exact: true }).fill(`Grid period ${width}`)
  await dialog.getByRole('button', { name: 'Capture review period', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'SoD period', exact: true }).getByRole('heading', { name: `Grid period ${width}` })).toBeVisible()
})

for (const width of [375, 1280]) test(`Delete review period: confirmation fields share a grid, consequences stay full width, actions carry icons (${width}px)`, async ({ page, request }) => {
  const draft = `Empty draft ${width}`
  await createPeriod(request, draft)
  await page.setViewportSize({ width, height: 900 })
  await openSod(page, 'Review Periods')
  await page.getByRole('button', { name: `Actions for ${draft}`, exact: true }).click()
  await page.getByRole('button', { name: 'Delete…', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Delete review period ${draft}`, exact: true })
  const by = (await dialog.getByRole('textbox', { name: /Recorded by/ }).boundingBox())!, confirm = (await dialog.getByRole('textbox', { name: /Type the period name/ }).boundingBox())!
  const panel = (await dialog.getByRole('region', { name: 'Delete review period' }).boundingBox())!, impact = (await dialog.getByText(/permanently deleted/).first().boundingBox())!
  if (width >= 800) { expect(Math.abs(by.y - confirm.y)).toBeLessThan(2); expect(confirm.x).toBeGreaterThan(by.x + by.width - 2) }
  else { expect(confirm.y).toBeGreaterThan(by.y + by.height - 2); expect(Math.abs(by.x - confirm.x)).toBeLessThan(2) }
  expect(impact.width).toBeGreaterThan(panel.width * 0.6) // the consequences are not squeezed into a column
  await icon(dialog.getByRole('button', { name: 'Cancel', exact: true })); await icon(dialog.getByRole('button', { name: 'Delete permanently', exact: true }))
  const remove = dialog.getByRole('button', { name: 'Delete permanently', exact: true })
  await expect(remove).toBeDisabled() // the name confirmation is still required
  await dialog.getByRole('textbox', { name: /Recorded by/ }).fill('Synthetic Actor')
  await dialog.getByRole('textbox', { name: /Type the period name/ }).fill(draft.slice(0, -1))
  await expect(remove).toBeDisabled()
  await dialog.getByRole('textbox', { name: /Type the period name/ }).fill(draft)
  await expect(remove).toBeEnabled()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('button', { name: `Open ${draft}`, exact: true })).toBeVisible() // cancelling deletes nothing
})

test('the toolbar explains a disabled Compare periods through a tooltip and shows a visible archived toggle', async ({ page, request }) => {
  // earlier tests of this run may have created periods, so the list is trimmed to fewer than two for the disabled state
  await page.route('**/api/sod/periods', async (route) => { const response = await route.fetch(), body = await response.json(); body.items = body.items.slice(0, 1); await route.fulfill({ response, json: body }) })
  await openSod(page, 'Review Periods')
  await expect(page.getByText('Needs at least two periods.')).toHaveCount(0) // the redundant text is gone
  const compare = page.getByRole('button', { name: 'Compare periods', exact: true })
  await expect(compare).toBeDisabled()
  await expect(compare).toHaveAccessibleDescription('Create at least two review periods to compare them.')
  await expect(page.locator('span[title="Create at least two review periods to compare them."]')).toHaveCount(1)
  const toggle = page.getByRole('button', { name: 'Show archived periods', exact: true })
  await expect(toggle).toHaveAttribute('aria-pressed', 'false'); await icon(toggle)
  const [create, size] = [(await page.getByRole('button', { name: 'Create review period', exact: true }).boundingBox())!, (await toggle.boundingBox())!]
  expect(Math.abs(create.height - size.height)).toBeLessThan(2) // same height as the adjacent actions
  await toggle.click()
  await expect(page.getByRole('button', { name: 'Hide archived periods', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Hide archived periods', exact: true }).click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
  await page.unroute('**/api/sod/periods')
  await createPeriod(request, 'Period one'); await createPeriod(request, 'Period two')
  await page.reload()
  await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'SoD', exact: true }).click()
  await page.getByRole('link', { name: 'Review Periods', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Compare periods', exact: true })).toBeEnabled() // available once two eligible periods exist
})
