import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers } from './support'
let directory: string
const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:A,Alpha purchasing,ZS:A1,MM - Purchasing,MIGO,Goods movement
FI,ZC:FI:B,Beta finance,ZS:B,FI - Finance,FB01,Post document
`
const users = `USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,ROLE_VALID_FROM,ROLE_VALID_TO
DEMO_ONE,ZC:MM:A,G1,Ada,One,20200101,99991231
DEMO_TWO,ZC:FI:B,G2,Bo,Two,20200101,99991231
`
test.beforeEach(async ({ request, context }) => {
  // New tabs do not inherit sessionStorage in the test browser, so give them the same test session.
  await context.addInitScript(() => { try { sessionStorage.setItem('sap-lens-session', 'browser-test-session') } catch { /* optional */ } })
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-nav-'))
  const roleFile = path.join(directory, 'roles.csv'), userFile = path.join(directory, 'users.csv')
  writeFileSync(roleFile, roles); writeFileSync(userFile, users)
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = roleFile; settings.user_csv_path = userFile
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

const main = (page: Page) => page.getByRole('navigation', { name: 'Main navigation', exact: true })
const settings = (page: Page) => page.getByRole('region', { name: 'SAP Lens settings', exact: true })
async function openSettings(page: Page) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await expect(settings(page)).toBeVisible()
}
const organization = (page: Page) => settings(page).getByRole('textbox', { name: 'Organization name', exact: true })

test.describe('main navigation from Settings', () => {
  test('destinations are links and navigate immediately when nothing changed', { tag: '@smoke' }, async ({ page }) => {
    await openSettings(page)
    await expect(main(page).getByRole('link')).toHaveCount(4)
    for (const [name, hash] of [['Role Lookup', '#/role-lookup'], ['User Access', '#/user-access'], ['Release Roles', '#/release-roles'], ['Dashboard', '#/dashboard']] as const) {
      await expect(main(page).getByRole('link', { name, exact: true })).toHaveAttribute('href', hash)
      await page.getByRole('button', { name: 'Open settings', exact: true }).click()
      await expect(settings(page)).toBeVisible()
      await main(page).getByRole('link', { name, exact: true }).click()
      await expect(settings(page)).toBeHidden()
      await expect(page).toHaveURL(new RegExp(hash.replace('/', '\\/') + '$'))
      await expect(main(page).getByRole('link', { name, exact: true })).toHaveAttribute('aria-current', 'page')
    }
  })

  test('unsaved edits ask first: Cancel keeps the draft, confirming discards it', async ({ page }) => {
    await openSettings(page)
    await organization(page).fill('Draft Organization')
    const prompts: string[] = []
    page.once('dialog', (dialog) => { prompts.push(dialog.message()); void dialog.dismiss() })
    await main(page).getByRole('link', { name: 'Role Lookup', exact: true }).click()
    expect(prompts).toEqual(['Discard unsaved settings changes?'])
    await expect(settings(page)).toBeVisible()
    await expect(organization(page)).toHaveValue('Draft Organization')
    page.once('dialog', (dialog) => { void dialog.accept() })
    await main(page).getByRole('link', { name: 'Role Lookup', exact: true }).click()
    await expect(settings(page)).toBeHidden()
    await expect(page).toHaveURL(/#\/role-lookup$/)
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    await expect(organization(page)).not.toHaveValue('Draft Organization')
  })

  test('modified clicks open a new tab and leave the Settings draft untouched; Back and Forward work', async ({ page, context }) => {
    await openSettings(page)
    await organization(page).fill('Draft Organization')
    let dialogs = 0
    page.on('dialog', (dialog) => { dialogs++; void dialog.dismiss() })
    const opened = context.waitForEvent('page')
    await main(page).getByRole('link', { name: 'User Access', exact: true }).click({ modifiers: ['Control'] })
    const tab = await opened
    await tab.waitForLoadState()
    expect(tab.url()).toContain('#/user-access')
    await tab.close()
    const middle = context.waitForEvent('page')
    await main(page).getByRole('link', { name: 'Release Roles', exact: true }).click({ button: 'middle' })
    const second = await middle
    await second.waitForLoadState()
    expect(second.url()).toContain('#/release-roles')
    await second.close()
    expect(dialogs).toBe(0)
    await expect(settings(page)).toBeVisible()
    await expect(organization(page)).toHaveValue('Draft Organization')
  })

  test('Back and Forward move between Settings and the destination', async ({ page }) => {
    await openSettings(page)
    await main(page).getByRole('link', { name: 'Role Lookup', exact: true }).click()
    await expect(page).toHaveURL(/#\/role-lookup$/)
    await page.goBack()
    await expect(settings(page)).toBeVisible()
    await page.goForward()
    await expect(page).toHaveURL(/#\/role-lookup$/)
    await expect(settings(page)).toBeHidden()
  })
})

const accessibleName = (page: Page) => page.evaluate(() => {
  const element = document.activeElement as HTMLElement
  const labelled = element.getAttribute('aria-labelledby')?.split(' ').map((id) => document.getElementById(id)?.textContent).join(' ')
  const label = (element as HTMLInputElement).labels?.[0]?.textContent
  return (element.getAttribute('aria-label') || labelled || label || element.textContent || '').replace(/\s+/g, ' ').trim()
})

test.describe('User Directory keyboard order', () => {
  // Reading order = DOM order: page toolbar, then the filter sidebar (wide) or no sidebar stops (narrow drawer is closed), then the results.
  const wide = ['Hide filters', 'Sort users', 'Ascending order, switch to descending', 'Clear filters', 'Clear all filters', 'Close filters', 'Saved filters', 'SAP User Group', 'Filter users by role', 'Roles the user must lack', 'Filter users by transaction', 'Exclude users by transaction', 'Show expired assignments', 'Search users']
  const narrow = ['Filters', 'Sort users', 'Ascending order, switch to descending', 'Clear filters', 'Search users']
  for (const width of [375, 800, 1280, 1600]) test(`Tab and Shift+Tab follow the reading order at ${width}`, async ({ page }) => {
    const order = width >= 1024 ? wide : narrow
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#session=browser-test-session')
    await main(page).getByRole('link', { name: 'User Access', exact: true }).click()
    await page.getByLabel('Search users', { exact: true }).fill('DEMO')
    await expect(page.getByRole('button', { name: 'Clear filters', exact: true })).toBeEnabled()
    await page.getByRole('toolbar', { name: 'Page actions' }).getByRole('button').first().focus()
    const forward = [await accessibleName(page)]
    for (let step = 1; step < order.length; step++) { await page.keyboard.press('Tab'); forward.push(await accessibleName(page)) }
    expect(forward).toEqual(order)
    const backward = [await accessibleName(page)]
    for (let step = 1; step < order.length; step++) { await page.keyboard.press('Shift+Tab'); backward.push(await accessibleName(page)) }
    expect(backward).toEqual([...order].reverse())
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  })

  test('the expired checkbox label is clickable and keyboard operable; dropdowns do not move focus into other controls', async ({ page }) => {
    await page.goto('/#session=browser-test-session')
    await main(page).getByRole('link', { name: 'User Access', exact: true }).click()
    const expired = page.getByRole('checkbox', { name: 'Show expired assignments', exact: true })
    await page.getByText('Show expired assignments', { exact: true }).click()
    await expect(expired).toBeChecked()
    await expired.focus()
    await page.keyboard.press('Space')
    await expect(expired).not.toBeChecked()
    const group = page.getByRole('combobox', { name: 'SAP User Group', exact: true })
    await group.focus()
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('Escape')
    await expect(group).toBeFocused()
    await page.keyboard.press('Tab')
    expect(await accessibleName(page)).toBe('Filter users by role')
  })
})

test('identifier codeblocks add no keyboard stop: Tab goes from the username link straight to its copy button', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await main(page).getByRole('link', { name: 'User Access', exact: true }).click()
  const link = page.getByRole('link', { name: 'DEMO_ONE', exact: true })
  await link.focus()
  await page.keyboard.press('Tab')
  expect(await accessibleName(page)).toBe('Copy username DEMO_ONE')
  expect(await page.locator('code[tabindex]:not([tabindex="-1"])').count()).toBe(0)
  await main(page).getByRole('link', { name: 'Role Lookup', exact: true }).click()
  expect(await page.locator('code[tabindex]:not([tabindex="-1"])').count()).toBe(0)
})

test.describe('SAP username deep links', () => {
  test('usernames are links with the user route; a plain click opens the user, modified clicks open a tab', async ({ page, context }) => {
    await page.goto('/#session=browser-test-session')
    await main(page).getByRole('link', { name: 'User Access', exact: true }).click()
    const link = page.getByRole('link', { name: 'DEMO_TWO', exact: true })
    await expect(link).toHaveAttribute('href', '#/user-access/user/DEMO_TWO')
    const opened = context.waitForEvent('page')
    await link.click({ modifiers: ['Control'] })
    const tab = await opened
    await tab.waitForLoadState()
    await expect(tab.getByRole('region', { name: 'User details', exact: true })).toContainText('DEMO_TWO', { timeout: 15000 })
    await tab.close()
    await link.click()
    await expect(page).toHaveURL(/#\/user-access\/user\/DEMO_TWO$/)
    await expect(page.getByRole('region', { name: 'User details', exact: true })).toContainText('DEMO_TWO')
    await page.goBack()
    await expect(page.getByRole('link', { name: 'DEMO_ONE', exact: true })).toBeVisible()
  })

  test('direct URL loading opens the user; an unknown user is handled gracefully', async ({ page }) => {
    await page.goto('/#session=browser-test-session')
    await page.goto('/#/user-access/user/DEMO_ONE')
    await page.reload()
    await expect(page.getByRole('region', { name: 'User details', exact: true })).toContainText('DEMO_ONE')
    await page.goto('/#/user-access/user/NO_SUCH_USER')
    await page.reload()
    await expect(page.getByRole('region', { name: 'User details', exact: true })).toBeVisible()
    await expect(page.getByRole('alert').or(page.getByText(/not found|no longer|missing/i)).first()).toBeVisible()
    await page.getByRole('button', { name: /^Back to users/ }).click()
    await expect(page.getByRole('link', { name: 'DEMO_ONE', exact: true })).toBeVisible()
  })
})

test('SoD secondary navigation shows an icon for every view', async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.features.sod = true
  await request.post('/api/configuration', { headers, data: settings })
  await page.goto('/#session=browser-test-session')
  await main(page).getByRole('link', { name: 'SoD', exact: true }).click()
  const links = page.getByRole('navigation', { name: 'SoD views', exact: true }).getByRole('link')
  await expect(links).toHaveCount(7)
  for (const link of await links.all()) await expect(link.locator('svg')).toHaveCount(1)
})
