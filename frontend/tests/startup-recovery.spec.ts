import { test, expect, type Page } from '@playwright/test'

const STALE = { detail: 'Application request is not authorized.', code: 'stale_session' }
const staleStartup = async (page: Page) => {
  await page.route('**/api/configuration', route => route.fulfill({ status: 403, json: STALE }))
  await page.goto('/#session=browser-test-session')
}
const card = (page: Page) => page.locator('.startup-card')

test('stale session: Reload is primary, Retry secondary, Backup & Restore a separate tertiary action', async ({ page }) => {
  await staleStartup(page)
  const actions = page.getByRole('group', { name: 'Recovery actions' })
  const reload = actions.getByRole('button', { name: 'Reload trusted session' }), retry = actions.getByRole('button', { name: 'Retry connection' })
  const backup = card(page).getByRole('button', { name: 'Open Backup & Restore' })
  await expect(reload).toHaveClass(/ui-button-primary/)
  await expect(retry).toHaveClass(/ui-button-secondary/)
  await expect(backup).toHaveClass(/ui-button-ghost/)
  await expect(actions.getByRole('button', { name: 'Open Backup & Restore' })).toHaveCount(0) // not part of the primary row
  const [a, b, c] = await Promise.all([reload.boundingBox(), retry.boundingBox(), backup.boundingBox()])
  expect(Math.abs(a!.height - b!.height)).toBeLessThanOrEqual(1) // consistent height
  expect(c!.y).toBeGreaterThanOrEqual(Math.max(a!.y + a!.height, b!.y + b!.height) + 8) // adequate vertical separation
  // DOM order equals reading and focus order.
  await reload.focus(); await page.keyboard.press('Tab'); await expect(retry).toBeFocused()
  await page.keyboard.press('Tab'); await expect(backup).toBeFocused()
  await expect(backup).toHaveAttribute('aria-expanded', 'false')
})

test('without a stale session Retry connection is the primary action and Reload is absent', async ({ page }) => {
  await page.route('**/api/configuration', route => route.abort('connectionrefused'))
  await page.goto('/#session=browser-test-session')
  await expect(page.getByRole('button', { name: 'Retry connection' })).toHaveClass(/ui-button-primary/)
  await expect(page.getByRole('button', { name: 'Reload trusted session' })).toHaveCount(0)
})

for (const width of [375, 800, 1280]) {
  test(`recovery actions stay inside the card without horizontal scroll at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 700 })
    await staleStartup(page)
    await expect(page.getByRole('button', { name: 'Reload trusted session' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const box = await card(page).boundingBox()
    for (const name of ['Reload trusted session', 'Retry connection', 'Open Backup & Restore']) {
      const b = await page.getByRole('button', { name }).boundingBox()
      expect(b!.x).toBeGreaterThanOrEqual(box!.x - 1); expect(b!.x + b!.width).toBeLessThanOrEqual(box!.x + box!.width + 1)
    }
    const reload = await page.getByRole('button', { name: 'Reload trusted session' }).boundingBox()
    const retry = await page.getByRole('button', { name: 'Retry connection' }).boundingBox()
    if (width === 375) expect(retry!.y).toBeGreaterThan(reload!.y + reload!.height - 1) // stacked on narrow screens
    expect(box!.height).toBeLessThan(width === 375 ? 580 : 500) // no excessive whitespace
  })
}

test('Retry connection re-queries, and Backup & Restore opens on demand in dark mode', async ({ page }) => {
  let calls = 0
  await page.route('**/api/configuration', route => { calls++; return route.fulfill({ status: 403, json: STALE }) })
  await page.goto('/#session=browser-test-session')
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.getByRole('button', { name: 'Retry connection' }).click()
  await expect.poll(() => calls).toBeGreaterThan(1)
  await page.getByRole('button', { name: 'Open Backup & Restore' }).click()
  await expect(page.getByRole('button', { name: 'Open Backup & Restore' })).toHaveAttribute('aria-expanded', 'true')
})
