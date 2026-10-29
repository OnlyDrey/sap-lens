import type { APIRequestContext, Page } from '@playwright/test'

/** Shared browser-test helpers. Specs import these instead of redefining them. */
export const headers = { 'X-SAP-Lens': 'browser-test-session' }
export const sessionUrl = '/#session=browser-test-session'

/** Return the test server to first-run defaults (the server and its storage are per Playwright process). */
export const resetConfiguration = (request: APIRequestContext) => request.post('/api/configuration/reset', { headers })

export const mainNavigation = (page: Page) => page.getByRole('navigation', { name: 'Main navigation', exact: true })

/** Open one main navigation destination by its link name. */
export const goTo = (page: Page, name: string) => mainNavigation(page).getByRole('link', { name, exact: true }).click()

export async function openSettings(page: Page, tab?: string) {
  await page.goto(sessionUrl)
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  if (tab) await page.getByRole('tab', { name: tab, exact: true }).click()
}
