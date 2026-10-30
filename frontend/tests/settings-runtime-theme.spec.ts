import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { headers } from './support'
const config = async (request: APIRequestContext) => (await (await request.get('/api/configuration', { headers })).json()).settings
test.beforeEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }) })
test.afterEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }) })
async function open(page: Page, tab: string) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: tab, exact: true }).click()
}

for (const width of [375, 1280]) test(`feature cards put the Enabled switch above Configure at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  await open(page, 'Features')
  for (const name of ['User–Role Mapping', 'Employee Directory', 'Segregation of Duties']) {
    const configure = 'Configure source'
    const card = page.getByRole('region', { name: `${name} feature settings`, exact: true })
    const toggle = await card.getByRole('switch', { name: `${name} feature` }).boundingBox(), button = await card.getByRole('button', { name: configure }).boundingBox()
    expect(toggle!.y + toggle!.height, name).toBeLessThanOrEqual(button!.y + 1)
    const controls = await card.locator('.feature-controls').boundingBox()
    // Enabled and Configure share the right edge of the card's content box.
    const edge = await card.evaluate(node => node.getBoundingClientRect().right - parseFloat(getComputedStyle(node).paddingRight))
    expect(Math.abs(toggle!.x + toggle!.width - edge), name + ' toggle').toBeLessThanOrEqual(2)
    expect(Math.abs(button!.x + button!.width - edge), name + ' configure').toBeLessThanOrEqual(2)
    expect(controls!.y, name).toBeLessThanOrEqual(toggle!.y + 1)
    expect(controls!.y + controls!.height, name).toBeGreaterThanOrEqual(button!.y + button!.height - 1)
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('SAP Modules keeps module search and configuration without a separate availability filter', async ({ page }) => {
  await open(page, 'SAP Modules')
  await expect(page.getByLabel('Module availability')).toHaveCount(0)
  const tiles = page.locator('.module-tile-grid > div')
  const all = await tiles.count()
  await page.getByRole('searchbox').first().fill('FI')
  await expect.poll(async () => tiles.count()).toBeLessThan(all)
  await page.getByRole('button', { name: /^Edit FI — / }).click()
  await expect(page.getByRole('dialog', { name: /Configure FI/ })).toBeVisible()
})

test('data source health cards use two columns where space permits and every action opens its source', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await open(page, 'Health & Diagnostics')
  const cards = page.getByRole('region', { name: 'Data source health' }).locator('section.settings-card')
  await expect(cards).toHaveCount(4)
  const lefts = await cards.evaluateAll(nodes => [...new Set(nodes.map(node => Math.round(node.getBoundingClientRect().left)))])
  expect(lefts).toHaveLength(2)
  for (const tab of ['Role Catalogue', 'User Access', 'Employee Directory', 'SoD Matrix']) {
    const card = page.getByRole('region', { name: `${tab} CSV`, exact: true })
    await expect(card.getByRole('button', { name: 'Review source', exact: true })).toHaveCount(1)
    await expect(card.getByText('Technical details', { exact: true })).toBeVisible()
    await expect(card.getByText('Records', { exact: true })).toBeVisible()
    await card.getByRole('button', { name: 'Review source', exact: true }).click()
    await expect(page.getByRole('tab', { name: tab, exact: true })).toHaveAttribute('aria-selected', 'true')
    await page.getByRole('tab', { name: 'Health & Diagnostics', exact: true }).click()
  }
  // Optional features show Enabled/Disabled at the far right of the card header; essentials stay visible while technical facts are expandable.
  const sod = page.getByRole('region', { name: 'SoD Matrix CSV', exact: true })
  const technical = sod.getByRole('button', { name: 'Technical details', exact: true })
  await expect(technical).toHaveAttribute('aria-expanded', 'false')
  await expect(sod.locator('.source-health-technical')).toHaveCount(0)
  await technical.click()
  await expect(technical).toHaveAttribute('aria-expanded', 'true')
  await expect(sod.getByText('Last validated source check')).toBeVisible()
  // Technical details and Review source sit side by side.
  const [first, second] = [await technical.boundingBox(), await sod.getByRole('button', { name: 'Review source', exact: true }).boundingBox()]
  expect(Math.abs(first!.y - second!.y)).toBeLessThan(2)
  const header = await sod.locator('.source-health-header').boundingBox(), badge = await sod.locator('.source-health-header .evidence-badge').boundingBox()
  expect(Math.abs(header!.x + header!.width - (badge!.x + badge!.width))).toBeLessThanOrEqual(2)
  await page.setViewportSize({ width: 375, height: 900 })
  const narrow = await cards.evaluateAll(nodes => [...new Set(nodes.map(node => Math.round(node.getBoundingClientRect().left)))])
  expect(narrow).toHaveLength(1)
})

test('Secondary Color is configurable, validated for contrast and used by secondary buttons', async ({ page, request }) => {
  await open(page, 'Appearance & Branding')
  const colors = page.getByRole('region', { name: 'Theme color settings', exact: true })
  const preview = page.getByLabel('Theme live preview').getByRole('button', { name: 'Secondary action' })
  const secondary = async (value: string) => { await colors.getByLabel('Secondary color', { exact: true }).fill(value) }
  await expect(preview).toHaveCSS('background-color', 'rgb(42, 49, 86)')
  await secondary('#334466')
  await expect(preview).toHaveCSS('background-color', 'rgb(51, 68, 102)')
  await secondary('#dddddd')
  await expect(page.getByText(/secondary color .* needs at least 4.5:1/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Apply settings', exact: true })).toBeDisabled()
  expect((await config(request)).theme_colors.dark.secondary).toBe('#2a3156')
  await secondary('#334466')
  await page.getByRole('button', { name: 'Apply settings', exact: true }).click()
  await expect.poll(async () => (await config(request)).theme_colors.dark.secondary).toBe('#334466')
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--secondary').trim())).toBe('#334466')
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--error').trim())).not.toBe('#334466')
})
