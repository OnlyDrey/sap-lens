import { test, expect, type Page } from '@playwright/test'
import { cleanup, headers, names, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const STALE = { detail: 'Application request is not authorized.', code: 'stale_session' }
const notice = (page: Page) => page.locator('.session-notice')

/** An automatic restore ran moments ago (this is what the guard looks like after one), so the notification and its explicit Reconnect action stay visible. */
const restoredRecently = (page: Page) => page.addInitScript(() => { try { sessionStorage.setItem('sap-lens-session-recovery', JSON.stringify({ at: Date.now() })) } catch { /* storage unavailable */ } })

async function openUser(page: Page) {
  await page.goto('/#session=browser-test-session')
  await page.goto(`/#/user-access/user/${names.a}`)
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible()
}
/** Simulates a restarted backend: every API call is refused as a stale session. Returns the number of calls that reached the network. */
async function restartBackend(page: Page) {
  const state = { calls: 0 }
  await page.route('**/api/**', (route) => { state.calls++; return route.fulfill({ status: 403, json: STALE }) })
  return state
}

test('a clean start shows no session notification', async ({ page }) => {
  await openUser(page)
  await expect(notice(page)).toHaveCount(0)
  await expect(page.getByText('Unable to load user details')).toHaveCount(0)
})

test('a restarted backend shows exactly one notification, one compact empty state and blocks further requests', async ({ page }) => {
  await restoredRecently(page)
  await openUser(page)
  const backend = await restartBackend(page)
  await page.getByRole('button', { name: 'Refresh role data from CSV' }).click().catch(() => undefined)
  await page.goto(`/#/user-access/user/${names.b}`)
  await expect(notice(page)).toHaveCount(1)
  await expect(notice(page)).toContainText('Session disconnected')
  await expect(notice(page)).toContainText('no longer valid')
  await expect(page.getByRole('alert').filter({ hasText: 'no longer valid' })).toHaveCount(1)       // announced once, never repeated elsewhere
  await expect(page.getByText('Unable to load user details')).toHaveCount(1)                          // contextual empty state, no raw error
  await expect(page.getByText('Record navigation unavailable')).toHaveCount(0)
  await expect(page.getByText('Reload trusted session')).toHaveCount(0)                               // one reconnect action only
  await expect(page.getByRole('button', { name: 'Reconnect session' })).toHaveCount(1)
  await expect(page.getByRole('breadcrumb').or(page.getByRole('navigation', { name: 'Breadcrumb' }))).toBeVisible() // header and navigation stay
  // Protected requests are refused locally: further navigation produces no new network calls.
  const before = backend.calls
  await page.goto(`/#/user-access/user/${names.a}`)
  await page.waitForTimeout(600)
  expect(backend.calls).toBe(before)
  await expect(notice(page)).toHaveCount(1)
})

test('Reconnect re-establishes the session through the guarded document and reloads the affected data', async ({ page }) => {
  await restoredRecently(page)
  await openUser(page)
  await page.route('**/api/**', (route) => route.fulfill({ status: 403, json: STALE }))
  await page.goto(`/#/user-access/user/${names.b}`)
  await expect(notice(page)).toHaveCount(1)
  await page.unroute('**/api/**')                                                                       // the backend answers again
  const navigated = page.waitForEvent('load')
  await page.getByRole('button', { name: 'Reconnect session' }).click()
  await navigated
  await expect(notice(page)).toHaveCount(0)
  await expect(page).toHaveURL(new RegExp(`#/user-access/user/${names.b}`))                           // navigation context is preserved
})

test('unsaved input is protected before a reconnect and nothing is replayed', async ({ page }) => {
  await restoredRecently(page)
  await openUser(page)
  const writes: string[] = []
  await page.route('**/api/**', (route) => { if (route.request().method() === 'POST') writes.push(route.request().url()); return route.fulfill({ status: 403, json: STALE }) })
  await page.goto(`/#/user-access/user/${names.b}`)
  await expect(notice(page)).toHaveCount(1)
  await page.evaluate(() => { const dialog = document.createElement('div'); dialog.setAttribute('role', 'dialog'); const input = document.createElement('input'); dialog.append(input); document.body.append(dialog); input.value = 'draft rationale' })
  await page.getByRole('button', { name: 'Reconnect session' }).click()
  await expect(notice(page)).toContainText('text typed into open forms will be lost')
  await expect(page.getByRole('button', { name: 'Reconnect anyway' })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(notice(page)).toContainText('no longer valid')
  expect(writes).toHaveLength(0)                                                                        // no write was sent or queued
})

test('a restarted backend is restored automatically when nothing typed would be lost', async ({ page }) => {
  await openUser(page)
  let restarted = false
  page.on('request', (request) => { if (request.isNavigationRequest()) restarted = true })        // the guarded document is requested: from then on the "new backend" answers
  await page.route('**/api/**', (route) => (restarted ? route.fallback() : route.fulfill({ status: 403, json: STALE })))
  await page.goto(`/#/user-access/user/${names.b}`)
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible()
  await expect(notice(page)).toHaveCount(0)
  await expect(page).toHaveURL(new RegExp(`#/user-access/user/${names.b}`))                       // the view is kept
})

test('a temporary connection loss is explained once and recovers with Retry', async ({ page }) => {
  await openUser(page)
  await page.route('**/api/**', (route) => route.abort('connectionrefused'))
  await page.goto(`/#/user-access/user/${names.b}`)
  await expect(notice(page)).toHaveCount(1)
  await expect(notice(page)).toContainText('Connection lost')
  await expect(page.getByRole('button', { name: 'Reconnect session' })).toHaveCount(0)               // only actions that work in this state
  await page.unroute('**/api/**')
  await page.getByRole('button', { name: 'Retry connection' }).click()
  await expect(notice(page)).toHaveCount(0)
})

test('the notification is compact, keyboard operable, readable in dark mode and does not overflow at 375px', async ({ page, request }) => {
  await restoredRecently(page)
  await openUser(page)
  await page.route('**/api/**', (route) => route.fulfill({ status: 403, json: STALE }))
  for (const [width, theme] of [[1280, 'light'], [375, 'dark']] as const) {
    await page.setViewportSize({ width, height: 800 })
    await page.evaluate((value) => { document.documentElement.dataset.theme = value; document.documentElement.classList.toggle('dark', value === 'dark') }, theme)
    await page.goto(`/#/user-access/user/${names.b}?w=${width}`)
    await expect(notice(page)).toHaveCount(1)
    const box = await notice(page).boundingBox()
    expect(box!.height).toBeLessThan(width === 375 ? 220 : 120)                                          // compact
    if (width >= 1280) expect(box!.width).toBeLessThanOrEqual(681)                                      // capped, not viewport wide
    else expect(box!.width).toBeGreaterThan(width * 0.9)                                                 // fills a narrow container
    const head = await notice(page).locator('.session-notice-head').boundingBox()
    const action = await page.getByRole('button', { name: 'Reconnect session' }).boundingBox()
    expect(action!.y).toBeGreaterThanOrEqual(head!.y - 1); expect(action!.y + action!.height).toBeLessThanOrEqual(head!.y + head!.height + 1) // action lives in the header
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    const reconnect = page.getByRole('button', { name: 'Reconnect session' })
    await reconnect.focus(); await expect(reconnect).toBeFocused()
    await page.getByText('Technical details').click()
    await expect(notice(page)).toContainText('stale_session')
    await expect(notice(page)).not.toContainText('browser-test-session')                                // the capability is never shown
    await page.getByText('Technical details').click()
  }
  void request; void headers
})
