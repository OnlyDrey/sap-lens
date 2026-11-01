import { test, expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { headers, openSettings } from './support'

/** The standard select, the searchable select and the multi-select filter are one component family: one list surface, one option style, one selected state. */
test.setTimeout(120_000)

const open = async (page: Page) => {
  await openSettings(page, 'Component Library')
  await page.getByRole('tab', { name: 'All components', exact: true }).click()
}
const surface = (list: Locator) => list.evaluate((element) => {
  const style = getComputedStyle(element), option = element.querySelector('[role=option]')!, optionStyle = getComputedStyle(option)
  return { background: style.backgroundColor, border: `${style.borderTopWidth} ${style.borderTopColor}`, radius: style.borderTopLeftRadius, padding: style.paddingTop, shadow: style.boxShadow, zIndex: style.zIndex,
    optionFont: optionStyle.fontSize, optionPadding: optionStyle.padding, optionRadius: optionStyle.borderRadius }
})
const setTheme = async (request: APIRequestContext, theme: string) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings; settings.theme = theme
  await request.post('/api/configuration', { headers, data: settings })
}

for (const theme of ['light', 'dark']) for (const width of [375, 1280]) test(`standard, searchable and multi-select dropdowns share one surface in ${theme} at ${width}px`, async ({ page, request }) => {
  await setTheme(request, theme)
  await page.setViewportSize({ width, height: 900 })
  await open(page)
  const select = page.getByRole('combobox', { name: 'Demo select', exact: true })
  await select.scrollIntoViewIfNeeded(); await select.click()
  const standard = page.locator('.select-popup')
  await expect(standard.getByRole('listbox')).toBeVisible()
  const standardSurface = await surface(standard)
  const selected = standard.getByRole('option', { selected: true })
  await expect(selected).toHaveText('All demo values'); await expect(selected.locator('svg')).toHaveCount(1) // the check mark
  const accent = await selected.evaluate((element) => ({ color: getComputedStyle(element).color, weight: getComputedStyle(element).fontWeight }))
  await page.keyboard.press('Escape')

  const search = page.getByRole('combobox', { name: 'Demo searchable role', exact: true })
  await search.scrollIntoViewIfNeeded(); await search.click()
  const searchable = page.locator('.combobox-popup').first()
  expect(await surface(searchable)).toEqual(standardSurface)
  const searchSelected = searchable.getByRole('option', { selected: true })
  await expect(searchSelected.locator('svg')).toHaveCount(1)
  expect(await searchSelected.evaluate((element) => ({ color: getComputedStyle(element).color, weight: getComputedStyle(element).fontWeight }))).toEqual(accent)
  await page.keyboard.press('Escape')

  const multi = page.getByRole('combobox', { name: 'Demo areas', exact: true })
  await multi.scrollIntoViewIfNeeded(); await multi.click()
  const multiple = page.locator('.multi-popup')
  const multiSurface = await surface(multiple)
  expect({ ...multiSurface, optionPadding: standardSurface.optionPadding, padding: standardSurface.padding }).toEqual(standardSurface)  // same surface; its inner list carries the padding and its options add a check box
  await page.keyboard.press('Escape')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  if (process.env.SHOTS) { await select.scrollIntoViewIfNeeded(); await select.click(); await page.screenshot({ path: `${process.env.SHOTS}/select-${theme}-${width}.png` }) }
})

test('standard select: mouse selection, disabled options, long labels, ARIA and no browser popup', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await open(page)
  const select = page.getByRole('combobox', { name: 'Demo select', exact: true })
  await select.scrollIntoViewIfNeeded()
  await expect(select).toHaveAttribute('aria-expanded', 'false')
  await select.click()
  await expect(select).toHaveAttribute('aria-expanded', 'true')
  const list = page.locator('.select-popup').getByRole('listbox')
  await expect(select).toHaveAttribute('aria-controls', (await list.getAttribute('id'))!)
  await expect(list.getByRole('option')).toHaveCount(4)
  await expect(list.getByRole('option', { name: /Archived/ })).toHaveAttribute('aria-disabled', 'true')
  const long = list.getByRole('option', { name: /deliberately long/ }), box = (await long.boundingBox())!
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(375); expect(box.height).toBeGreaterThan(40)  // wraps inside the list
  await list.getByRole('option', { name: /Archived/ }).click({ force: true })
  await expect(list).toBeVisible(); await expect(select).toHaveValue('all')                         // a disabled option does nothing
  await list.getByRole('option', { name: 'Active demo values' }).hover()
  await expect(list.getByRole('option', { name: 'Active demo values' })).toHaveClass(/highlighted/)
  await list.getByRole('option', { name: 'Active demo values' }).click()
  await expect(list).toHaveCount(0); await expect(select).toHaveValue('active'); await expect(select).toBeFocused()
  await select.click(); await select.click()                                                         // a second click closes it again
  await expect(page.locator('.select-popup')).toHaveCount(0)
  // an outside click closes without changing the value
  await select.click(); await page.getByRole('heading', { name: 'Form controls' }).first().click().catch(() => page.mouse.click(2, 2))
  await expect(page.locator('.select-popup')).toHaveCount(0); await expect(select).toHaveValue('active')
})

test('standard select: keyboard operation, Escape stays local and typing jumps to a label', async ({ page }) => {
  await open(page)
  const select = page.getByRole('combobox', { name: 'Demo select', exact: true })
  await select.scrollIntoViewIfNeeded(); await page.keyboard.press('Shift'); await select.focus()
  const list = page.locator('.select-popup').getByRole('listbox')
  await page.keyboard.press('Alt+ArrowDown'); await expect(list).toBeVisible()
  await expect(select).toHaveAttribute('aria-activedescendant', /option-0$/)
  await page.keyboard.press('ArrowDown'); await expect(select).toHaveAttribute('aria-activedescendant', /option-1$/)
  await page.keyboard.press('ArrowDown'); await expect(select).toHaveAttribute('aria-activedescendant', /option-3$/)  // the disabled option is skipped
  await page.keyboard.press('Home'); await expect(select).toHaveAttribute('aria-activedescendant', /option-0$/)
  await page.keyboard.press('End'); await expect(select).toHaveAttribute('aria-activedescendant', /option-3$/)
  await page.keyboard.press('ArrowUp'); await page.keyboard.press('Enter')
  await expect(list).toHaveCount(0); await expect(select).toHaveValue('active'); await expect(select).toBeFocused()
  await page.keyboard.press(' '); await expect(list).toBeVisible()                                   // Space opens
  await page.keyboard.type('al'); await expect(select).toHaveAttribute('aria-activedescendant', /option-0$/) // typeahead: "All demo values"
  await page.keyboard.press('Escape'); await expect(list).toHaveCount(0); await expect(select).toHaveValue('active'); await expect(select).toBeFocused()
  await page.keyboard.press('Enter'); await page.keyboard.press('ArrowUp'); await page.keyboard.press(' '); await expect(select).toHaveValue('all') // Enter opens, Space chooses the highlighted option
  await page.keyboard.press('ArrowDown'); await expect(select).toHaveValue('active'); await expect(list).toHaveCount(0) // closed: a plain arrow key changes the value like a browser select
  await page.keyboard.press('Alt+ArrowUp'); await expect(list).toBeVisible(); await page.keyboard.press('Tab'); await expect(list).toHaveCount(0)
  // Escape closes only the list while a dialog is open
  await page.getByRole('button', { name: 'Open demo dialog' }).scrollIntoViewIfNeeded(); await page.getByRole('button', { name: 'Open demo dialog' }).click()
  const dialog = page.getByRole('dialog', { name: 'Isolated component dialog' })
  const inDialog = dialog.getByRole('combobox', { name: 'Demo dialog select', exact: true })
  await inDialog.click()
  const popup = page.locator('.select-popup'); await expect(popup).toBeVisible()
  expect(await popup.evaluate((element) => Number(getComputedStyle(element).zIndex))).toBeGreaterThan(await dialog.evaluate((element) => Number(getComputedStyle(element.closest('[class*=ui-dialog], .dialog-backdrop') ?? element).zIndex) || 0))
  await page.keyboard.press('Escape'); await expect(popup).toHaveCount(0); await expect(dialog).toBeVisible()
  await inDialog.click(); await popup.getByRole('option', { name: 'Active demo values' }).click(); await expect(inDialog).toHaveValue('active'); await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape'); await expect(dialog).toHaveCount(0)
})

test('standard select: placement near the viewport edge and inside a side panel', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 520 })
  await open(page)
  await page.getByRole('button', { name: 'Open demo side panel' }).scrollIntoViewIfNeeded(); await page.getByRole('button', { name: 'Open demo side panel' }).click()
  const panelSelect = page.getByRole('combobox', { name: 'Demo side panel select', exact: true })
  await panelSelect.click()
  const popup = page.locator('.select-popup'), box = (await popup.boundingBox())!, view = page.viewportSize()!
  expect(box.y).toBeGreaterThanOrEqual(0); expect(box.y + box.height).toBeLessThanOrEqual(view.height); expect(box.x + box.width).toBeLessThanOrEqual(view.width)
  await popup.getByRole('option', { name: 'Active demo values' }).click(); await expect(panelSelect).toHaveValue('active')
  await page.keyboard.press('Escape'); await expect(page.getByRole('dialog', { name: 'Isolated side panel' })).toHaveCount(0)
  // the list follows its select when the page scrolls
  const select = page.getByRole('combobox', { name: 'Demo select', exact: true }); await select.scrollIntoViewIfNeeded(); await select.click()
  await page.evaluate(() => { const spacer = document.createElement('div'); spacer.style.height = '60px'; document.querySelector('[aria-label="Demo select"]')!.closest('.ui-field')!.before(spacer) })
  await expect.poll(async () => { const a = (await select.boundingBox())!, p = (await popup.boundingBox())!; return Math.min(Math.abs(p.y - a.y - a.height), Math.abs(a.y - p.y - p.height)) < 12 }).toBeTruthy()
})

test('selects stay form controls: the value, change events and the disabled state are native', async ({ page }) => {
  await open(page)
  const select = page.getByRole('combobox', { name: 'Demo select', exact: true })
  await select.selectOption('active'); await expect(select).toHaveValue('active')                 // programmatic selection keeps working
  await select.evaluate((element: HTMLSelectElement) => { element.disabled = true })
  await select.click({ force: true }); await expect(page.locator('.select-popup')).toHaveCount(0)
})
