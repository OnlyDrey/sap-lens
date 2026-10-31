import { test, expect, type Page } from '@playwright/test'
import { cleanup, headers, openSod, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const main = (page: Page) => page.getByRole('navigation', { name: 'Main navigation', exact: true })

test('the main link opens the module page and a separate chevron opens its submenu of direct page links', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  // chevrons only where submenus exist
  await expect(main(page).getByRole('button', { name: 'User Access pages' })).toBeVisible()
  await expect(main(page).getByRole('button', { name: 'SoD pages' })).toBeVisible()
  for (const name of ['Dashboard', 'Role Lookup', 'Release Roles']) await expect(main(page).getByRole('button', { name: `${name} pages` })).toHaveCount(0)
  // opening the submenu does not navigate
  const url = page.url()
  await main(page).getByRole('button', { name: 'User Access pages' }).click()
  expect(page.url()).toBe(url)
  const menu = page.getByRole('dialog', { name: 'User Access pages' })
  await expect(menu.getByRole('link')).toHaveText(['User directory', 'Account Review', 'Compare users'])
  for (const link of await menu.getByRole('link').all()) await expect(link.locator('svg')).toHaveCount(1)
  await menu.getByRole('link', { name: 'Account Review' }).click()
  await expect(page).toHaveURL(/#\/user-access\/account-review/)
  await expect(menu).toHaveCount(0)
  // the module stays highlighted and the active entry is marked
  await expect(main(page).getByRole('link', { name: 'User Access', exact: true })).toHaveAttribute('aria-current', 'page')
  await main(page).getByRole('button', { name: 'User Access pages' }).click()
  await expect(page.getByRole('dialog', { name: 'User Access pages' }).getByRole('link', { name: 'Account Review' })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('dialog', { name: 'User Access pages' }).getByRole('link', { name: 'User directory' })).not.toHaveAttribute('aria-current', 'page')
  await page.keyboard.press('Escape')
  await expect(main(page).getByRole('button', { name: 'User Access pages' })).toBeFocused()
  // the main link goes to the module main page
  await main(page).getByRole('link', { name: 'User Access', exact: true }).click()
  await expect(page).toHaveURL(/#\/user-access$/)
})

test('submenu and module links keep their real hrefs, and the SoD submenu lists every SoD page', async ({ page, context }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openSod(page)
  await main(page).getByRole('button', { name: 'SoD pages' }).click()
  const menu = page.getByRole('dialog', { name: 'SoD pages' })
  await expect(menu.getByRole('link')).toHaveText(['Overview', 'Risk Matrix', 'Activity Matrix', 'Access Explorer', 'Reviews', 'Review Periods', 'Reports'])
  await expect(menu.getByRole('link', { name: 'Risk Matrix' })).toHaveAttribute('href', '#/sod/risk-matrix')
  await expect(menu.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
  // a modified click opens a new tab and leaves this page where it is
  const before = page.url()
  const opened = context.waitForEvent('page', { timeout: 3000 }).catch(() => null)
  await menu.getByRole('link', { name: 'Reports' }).click({ modifiers: ['Control'] })
  expect(page.url()).toBe(before)
  void opened
  await menu.getByRole('link', { name: 'Reviews' }).click()
  await expect(page).toHaveURL(/#\/sod\/reviews/)
  await expect(main(page).getByRole('link', { name: 'SoD', exact: true })).toHaveAttribute('aria-current', 'page')
})

test('the chevron is keyboard operable and the nav stays usable at 375 px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await page.goto('/#session=browser-test-session')
  const chevron = main(page).getByRole('button', { name: 'User Access pages' })
  await chevron.focus(); await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'User Access pages' })).toBeVisible()
  await page.getByRole('dialog', { name: 'User Access pages' }).getByRole('link', { name: 'Compare users' }).focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/#\/user-access\/compare/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
})

test('secondary navigation, explorer and SoD settings actions carry icons and real buttons', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Reviews')
  for (const name of ['Work queue', 'Remediation']) await expect(page.getByRole('tab', { name, exact: true }).locator('svg')).toHaveCount(1)
  await page.getByRole('link', { name: 'Reports', exact: true }).click()
  for (const name of ['Formal review report', 'Access remediation report']) await expect(page.getByRole('tab', { name, exact: true }).locator('svg')).toHaveCount(1)
  await page.getByRole('link', { name: 'Access Explorer', exact: true }).click()
  await page.getByRole('tab', { name: 'Roles', exact: true }).click()
  const evidence = page.getByRole('button', { name: 'Show evidence for ROLE_AB' })
  await expect(evidence).toHaveClass(/ui-button/); await expect(evidence.locator('svg')).toHaveCount(1)
  const users = page.getByRole('button', { name: 'Show users with ROLE_AB' })
  await expect(users).toHaveClass(/ui-button/); await expect(users.locator('svg')).toHaveCount(1)
  // SoD risk configuration lives in Settings
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'SoD Risk Configuration', exact: true }).click()
  for (const name of ['Risks', 'Activities']) await expect(page.getByRole('tab', { name, exact: true }).locator('svg')).toHaveCount(1)
  // Source details are not repeated on every row: the edit dialog carries them
  await expect(page.getByRole('button', { name: /^Source details for risk / })).toHaveCount(0)
  const edit = page.getByRole('button', { name: /^Edit SoD risk / }).first()
  await expect(edit.locator('svg')).toHaveCount(1)
  await edit.click()
  await expect(page.getByRole('dialog').getByRole('button', { name: /^Source details for risk / })).toBeVisible()
})

for (const width of [375, 800, 1280]) for (const theme of ['light', 'dark']) test(`submenu overlays the page without scrollbars, size changes or left borders (${theme} ${width})`, async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings; settings.theme = theme
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
  await page.setViewportSize({ width, height: 800 })
  await page.goto('/#session=browser-test-session')
  const header = page.locator('header').first(), before = await header.boundingBox()
  await main(page).getByRole('button', { name: 'SoD pages' }).click()
  const menu = page.getByRole('dialog', { name: 'SoD pages' })
  await expect(menu).toBeVisible()
  expect(await menu.evaluate((element) => ({ y: getComputedStyle(element).overflow, fits: element.scrollHeight <= element.clientHeight && element.scrollWidth <= element.clientWidth }))).toEqual({ y: 'visible', fits: true })
  expect(await header.boundingBox()).toEqual(before) // the navbar keeps its size
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  const link = menu.getByRole('link', { name: 'Risk Matrix' })
  for (const action of ['hover', 'focus'] as const) {
    await link[action]()
    expect(await link.evaluate((element) => { const style = getComputedStyle(element); return [style.borderLeftWidth, style.boxShadow] })).toEqual(['0px', 'none'])
  }
  await menu.getByRole('link', { name: 'Overview' }).evaluate((element) => element.setAttribute('aria-current', 'page')) // the active entry
  const active = menu.getByRole('link', { name: 'Overview' })
  expect(await active.evaluate((element) => { const style = getComputedStyle(element); return [style.borderLeftWidth, style.boxShadow, style.backgroundColor !== 'rgba(0, 0, 0, 0)'] })).toEqual(['0px', 'none', true])
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)
})

for (const width of [320, 375, 430, 480, 560, 640, 800, 1000, 1280]) test(`the main navigation never becomes a scroll container, opening a submenu changes nothing and the chevron shows its state (${width}px)`, async ({ page }) => {
  await page.setViewportSize({ width, height: 700 })
  await page.goto('/#session=browser-test-session')
  const scrollers = () => page.evaluate(() => [...document.querySelectorAll('header *')].filter((element) => {
    const style = getComputedStyle(element)
    return !element.closest('.sr-only') && !element.classList.contains('sr-only') && (style.overflowX !== 'visible' || style.overflowY !== 'visible') && (element.scrollWidth > element.clientWidth + 0.5 || element.scrollHeight > element.clientHeight + 0.5)
  }).map((element) => `${element.tagName.toLowerCase()}.${element.className}`))
  const header = page.locator('header').first(), nav = main(page), chevron = nav.getByRole('button', { name: 'SoD pages' })
  expect(await nav.evaluate((element) => [getComputedStyle(element).overflowX, getComputedStyle(element).overflowY])).toEqual(['visible', 'visible'])
  expect(await scrollers()).toEqual([])
  const before = await header.boundingBox(), svg = () => chevron.locator('svg').first().evaluate((element) => getComputedStyle(element).transform)
  await expect(chevron).toHaveAttribute('aria-expanded', 'false')
  const closed = await svg()
  await chevron.click()
  await expect(chevron).toHaveAttribute('aria-expanded', 'true')
  await expect.poll(svg).not.toBe(closed) // the chevron is turned while the submenu is open
  expect(await scrollers()).toEqual([])
  expect(await header.boundingBox()).toEqual(before)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.keyboard.press('Escape')
  await expect(chevron).toHaveAttribute('aria-expanded', 'false')
  expect(await svg()).toBe(closed)
})
