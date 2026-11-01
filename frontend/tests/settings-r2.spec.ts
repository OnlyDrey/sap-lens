import { test, expect, type Page } from '@playwright/test'

const openHealth = async (page: Page, width = 1280) => {
  await page.setViewportSize({ width, height: 1000 })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Health & Diagnostics', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Data source health', exact: true })).toBeVisible()
}

test('Data Source Health cards sit in independent columns: expanding one moves only its own column', async ({ page }) => {
  await openHealth(page)
  const region = page.getByRole('region', { name: 'Data source health', exact: true })
  const columns = region.locator('.independent-column')
  expect(await columns.count()).toBeGreaterThanOrEqual(2)
  const cards = region.locator('section.source-health-card')
  const count = await cards.count()
  expect(count).toBeGreaterThanOrEqual(3)
  const boxes = async () => Promise.all(Array.from({ length: count }, async (_, index) => (await cards.nth(index).boundingBox())!))
  const columnOf = async (index: number) => cards.nth(index).evaluate(el => [...el.closest('.independent-columns')!.children].indexOf(el.closest('.independent-column')!))
  const before = await boxes()
  const first = cards.first()
  await first.getByRole('button', { name: 'Technical details' }).click()
  await expect(first.getByRole('button', { name: 'Technical details' })).toHaveAttribute('aria-expanded', 'true')
  const after = await boxes(), grown = after[0].height - before[0].height
  expect(grown).toBeGreaterThan(20)
  const firstColumn = await columnOf(0)
  for (let index = 1; index < count; index++) {
    if ((await columnOf(index)) === firstColumn) expect(Math.round(after[index].y - before[index].y)).toBe(Math.round(grown)) // below it in the same column: moves down by exactly the growth
    else { expect(Math.round(after[index].y)).toBe(Math.round(before[index].y)); expect(Math.round(after[index].height)).toBe(Math.round(before[index].height)) } // other columns: untouched
  }
  await first.getByRole('button', { name: 'Technical details' }).click()
  expect(Math.round((await first.boundingBox())!.height)).toBe(Math.round(before[0].height))
})

test('each source card has Technical details and Review source side by side with icons; locations live in the expanded section', async ({ page }) => {
  await openHealth(page)
  const first = page.getByRole('region', { name: 'Data source health', exact: true }).locator('section.source-health-card').first()
  const details = first.getByRole('button', { name: 'Technical details' }), review = first.getByRole('button', { name: 'Review source' })
  const [a, b] = [await details.boundingBox(), await review.boundingBox()]
  expect(Math.abs(a!.y - b!.y)).toBeLessThan(4); expect(b!.x).toBeGreaterThan(a!.x + a!.width - 1)
  await expect(details.locator('svg')).toHaveCount(1); await expect(review.locator('svg')).toHaveCount(1)
  await expect(first.getByRole('button', { name: 'Locations and diagnostics' })).toHaveCount(0)
  await details.click()
  await expect(first.getByRole('button', { name: 'Locations and diagnostics' })).toBeVisible()
})

test('Component Library: tab strip has room above and its scrollbar never overlaps the underline, and the new patterns are shown', async ({ page }) => {
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/#session=browser-test-session')
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    await page.getByRole('tab', { name: 'Component Library', exact: true }).click()
    const strip = page.getByRole('tablist', { name: 'Component categories' })
    const tab = strip.getByRole('tab', { name: 'All components', exact: true })
    const [stripBox, tabBox, intro] = [await strip.boundingBox(), await tab.boundingBox(), await page.getByLabel('Component Library previews').locator('> p').first().boundingBox()]
    expect(stripBox!.y - (intro!.y + intro!.height)).toBeGreaterThanOrEqual(8) // room above the tabs
    const clientHeight = await strip.evaluate(el => el.clientHeight)
    expect(tabBox!.y + tabBox!.height - stripBox!.y).toBeLessThanOrEqual(clientHeight + 0.5) // the underline is inside the client area, above any scrollbar
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
  }
  await page.setViewportSize({ width: 1280, height: 1000 })
  const patterns = page.getByRole('region', { name: 'Summaries and data presentation' })
  await patterns.scrollIntoViewIfNeeded()
  for (const name of ['Compact KPI', 'Information list', 'Chart presentation', 'Table states', 'Codeblock', 'Validation status', 'Disclosure and expandable cards', 'Multiselect toolbar', 'Heatmap controls', 'Modal layout']) await expect(patterns.getByRole('region', { name, exact: true })).toBeVisible()
  await patterns.getByRole('button', { name: 'Open wide modal' }).click()
  const dialog = page.getByRole('dialog', { name: 'Demo evidence modal' })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})
