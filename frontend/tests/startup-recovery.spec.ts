import { test, expect, type Page } from '@playwright/test'

// The test server answers like the desktop application (guarded loopback document, `stale_session` for an old capability), so these specs exercise the real recovery path.
const STALE = { detail: 'Application request is not authorized.', code: 'stale_session' }
const card = (page: Page) => page.locator('.startup-card')
const documentRequests = (page: Page) => {
  const seen: string[] = []
  page.on('request', (request) => { if (request.isNavigationRequest() && new URL(request.url()).pathname === '/') seen.push(request.url()) })
  return seen
}
const configurationRequests = (page: Page) => {
  const seen: string[] = []
  page.on('request', (request) => { if (new URL(request.url()).pathname === '/api/configuration' && request.method() === 'GET') seen.push(request.url()) })
  return seen
}
const appVisible = (page: Page) => page.getByRole('navigation', { name: 'Main navigation', exact: true })

test('a clean start opens the application without any recovery screen', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await expect(appVisible(page)).toBeVisible()
  await expect(card(page)).toHaveCount(0)
})

test('a session token from an earlier run is replaced automatically through the guarded document', async ({ page }) => {
  const documents = documentRequests(page)
  await page.goto('/#session=token-of-a-previous-run')
  await expect(appVisible(page)).toBeVisible()                                               // no click needed
  await expect(page.getByRole('button', { name: 'Reload trusted session' })).toHaveCount(0)
  await expect(page.getByRole('alert').filter({ hasText: 'no longer valid' })).toHaveCount(0)
  expect(documents).toHaveLength(2)                                                          // the first load and exactly one restore
  expect(await page.evaluate(() => sessionStorage.getItem('sap-lens-session'))).toBe('browser-test-session')
  expect(page.url()).not.toContain('session=')                                               // the capability never stays in the address
})

test('a session that cannot be restored stops after one attempt and offers one action', async ({ page }) => {
  const documents = documentRequests(page)
  await page.route('**/api/configuration', (route) => route.fulfill({ status: 403, json: STALE }))
  await page.goto('/#session=browser-test-session')
  await expect(card(page).getByRole('heading', { name: 'SAP Lens could not restore your local session' })).toBeVisible()
  await page.waitForTimeout(1500)                                                            // a loop would reload again within this time
  expect(documents).toHaveLength(2)
  const actions = page.getByRole('group', { name: 'Recovery actions' })
  await expect(actions.getByRole('button')).toHaveCount(1)
  await expect(actions.getByRole('button', { name: 'Retry connection' })).toHaveClass(/ui-button-primary/)
  await expect(page.getByRole('button', { name: 'Reload trusted session' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Open Backup & Restore' })).toHaveCount(0)   // not offered for a session problem
  await expect(card(page).locator('details')).not.toHaveAttribute('open', '')
  await card(page).getByText('Technical details').click()
  await expect(card(page)).toContainText('Status: 403')
  await expect(card(page)).not.toContainText('browser-test-session')                          // no token in the details
})

test('Retry connection after an unrestorable session restores it once the service answers', async ({ page }) => {
  await page.route('**/api/configuration', (route) => route.fulfill({ status: 403, json: STALE }))
  await page.goto('/#session=browser-test-session')
  await expect(page.getByRole('button', { name: 'Retry connection' })).toBeVisible()
  await page.unroute('**/api/configuration')
  await page.getByRole('button', { name: 'Retry connection' }).click()
  await expect(appVisible(page)).toBeVisible()
})

test('a service that is still starting is waited for and never reported as a session problem', async ({ page }) => {
  let refused = 0
  const documents = documentRequests(page)
  await page.route('**/api/configuration', (route) => (refused++ < 3 ? route.abort('connectionrefused') : route.continue()))
  await page.goto('/#session=browser-test-session')
  await expect(page.getByRole('status')).toHaveText('Connecting to local service…')
  await expect(appVisible(page)).toBeVisible({ timeout: 15_000 })                           // the back-off waits 0.5 s, 1 s and 2 s
  expect(refused).toBe(4)
  expect(documents).toHaveLength(1)                                                          // no session restore was attempted
})

test('a service that never answers ends in a bounded wait and one Retry action', async ({ page }) => {
  const configuration = configurationRequests(page)
  await page.route('**/api/configuration', (route) => route.abort('connectionrefused'))
  await page.goto('/#session=browser-test-session')
  await expect(card(page).getByRole('heading', { name: 'SAP Lens cannot reach its local service' })).toBeVisible({ timeout: 30_000 })
  expect(configuration).toHaveLength(7)                                                      // the first request and six retries, no endless loop
  await expect(page.getByRole('button', { name: 'Open Backup & Restore' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Reload trusted session' })).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Recovery actions' }).getByRole('button')).toHaveCount(1)
})

for (const status of [401, 403]) {
  test(`an answer ${status} without a stale-session marker is a rejection: no restore, no retry loop`, async ({ page }) => {
    const documents = documentRequests(page)
    const configuration = configurationRequests(page)
    await page.route('**/api/configuration', (route) => route.fulfill({ status, json: { detail: 'Not allowed.' } }))
    await page.goto('/#session=browser-test-session')
    await expect(card(page).getByRole('heading', { name: 'Access was not accepted' })).toBeVisible()
    await page.waitForTimeout(1000)
    expect(documents).toHaveLength(1)
    expect(configuration).toHaveLength(1)
    await expect(page.getByRole('button', { name: 'Open Backup & Restore' })).toHaveCount(0)
  })
}

test('a configuration failure is reported as such, is not retried automatically and offers Backup & Restore', async ({ page }) => {
  const configuration = configurationRequests(page)
  await page.route('**/api/configuration', (route) => route.fulfill({ status: 500, json: { detail: 'Settings storage could not be opened.' } }))
  await page.goto('/#session=browser-test-session')
  await expect(card(page).getByRole('heading', { name: 'SAP Lens could not load its configuration' })).toBeVisible()
  await page.waitForTimeout(1000)
  expect(configuration).toHaveLength(1)
  await expect(card(page)).not.toContainText('local session')                                // not presented as a session problem
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.getByRole('button', { name: 'Retry connection' }).click()
  await expect.poll(() => configuration.length).toBeGreaterThan(1)
  await page.getByRole('button', { name: 'Open Backup & Restore' }).click()
  await expect(page.getByRole('button', { name: 'Open Backup & Restore' })).toHaveAttribute('aria-expanded', 'true')
})

for (const width of [375, 800, 1280]) {
  test(`the recovery screen stays inside the card without horizontal scroll at ${width}px`, { tag: '@visual' }, async ({ page }) => {
    await page.setViewportSize({ width, height: 700 })
    await page.route('**/api/configuration', (route) => route.fulfill({ status: 500, json: { detail: 'Settings storage could not be opened.' } }))
    await page.goto('/#session=browser-test-session')
    await expect(page.getByRole('button', { name: 'Retry connection' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const box = await card(page).boundingBox()
    for (const name of ['Retry connection', 'Open Backup & Restore']) {
      const b = await page.getByRole('button', { name }).boundingBox()
      expect(b!.x).toBeGreaterThanOrEqual(box!.x - 1); expect(b!.x + b!.width).toBeLessThanOrEqual(box!.x + box!.width + 1)
    }
    const retry = (await page.getByRole('button', { name: 'Retry connection' }).boundingBox())!
    const backup = (await page.getByRole('button', { name: 'Open Backup & Restore' }).boundingBox())!
    expect(backup.y).toBeGreaterThanOrEqual(retry.y + retry.height + 8)                       // Backup & Restore is a separate, lower action; DOM order equals reading order
    expect(box!.height).toBeLessThan(width === 375 ? 640 : 560)
  })
}
