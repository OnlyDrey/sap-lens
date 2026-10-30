import type { APIRequestContext, Locator, Page } from '@playwright/test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

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

export interface SeededSources { directory: string; cleanup: () => Promise<void> }

/**
 * Reset the server, write synthetic role and/or user CSV text to a temp directory and point the settings at them.
 * Call `cleanup()` (usually in afterEach) to reset again and remove the files.
 */
export async function seedSources(request: APIRequestContext, sources: { roles?: string; users?: string }): Promise<SeededSources> {
  await resetConfiguration(request)
  const directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-test-'))
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  for (const [name, key] of [['roles', 'data_csv_path'], ['users', 'user_csv_path']] as const) {
    const text = sources[name]
    if (text === undefined) continue
    const file = path.join(directory, `${name}.csv`)
    writeFileSync(file, text)
    settings[key] = file
  }
  const saved = await request.post('/api/configuration', { headers, data: settings })
  if (!saved.ok()) throw new Error(`Seeding sources failed: ${saved.status()} ${await saved.text()}`)
  return { directory, cleanup: async () => { await resetConfiguration(request); rmSync(directory, { recursive: true, force: true }) } }
}

/** The sort direction toggle of SortControl: a pressed icon button instead of a checkbox. */
export const sortDirection = (scope: Page | Locator) => scope.getByRole('button', { name: /^(Ascending|Descending) order/ })
export async function setDescending(scope: Page | Locator, descending: boolean) {
  const toggle = sortDirection(scope)
  if ((await toggle.getAttribute('aria-pressed')) !== String(descending)) await toggle.click()
}

/** Wide screens show the filter sidebar; narrow ones (under 1024 px) use a drawer that has to be opened and closed. */
export async function openFilters(page: Page) {
  if (page.viewportSize()!.width >= 1024) return
  const trigger = page.getByRole('button', { name: /^Filters/ })
  if ((await trigger.getAttribute('aria-expanded')) !== 'true') await trigger.click()
}
export async function closeFilters(page: Page) {
  if (page.viewportSize()!.width >= 1024) return
  // The drawer covers the toolbar button with a backdrop; its own Close button is the reliable dismissal.
  const close = page.getByRole('button', { name: 'Close filters', exact: true })
  if (await close.isVisible()) await close.click()
}

/** Pick one value in a multi-select filter: open it, search, toggle the option and close the list. Selections stay independent of the search text. */
export async function pickMulti(scope: Page | Locator, label: string, option: string, page?: Page) {
  const box = scope.getByRole('combobox', { name: label, exact: true })
  await box.click(); await box.fill(option)
  await (page ?? (scope as Page)).getByRole('option', { name: option, exact: true }).click()
  await box.press('Escape')
}
