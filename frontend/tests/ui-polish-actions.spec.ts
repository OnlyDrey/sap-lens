import { test, expect, type Page } from '@playwright/test'
import { seedGovernance, headers } from './sod-fixture'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
FI,ZC:FI:VIEW:ENP,Finance view,ZS:EX2,FI - Exclusive two,FB03,Display document
`
let directory: string
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-consistency-'))
  const roleFile = path.join(directory, 'roles.csv')
  writeFileSync(roleFile, roles)
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.data_csv_path = roleFile
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

const openSettings = async (page: Page, tab: string) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: tab, exact: true }).click()
}

test('role card actions: Compare (Scale) left of Add to access package (Plus), no cart icon', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Role Lookup', exact: true }).click()
  const card = page.getByRole('article', { name: /Buyer plant/ })
  const compare = card.getByRole('button', { name: 'Add to comparison', exact: true }), add = card.getByRole('button', { name: 'Add to access package', exact: true })
  const [c, a] = [await compare.boundingBox(), await add.boundingBox()]
  expect(c!.x + c!.width).toBeLessThanOrEqual(a!.x)
  expect(c!.width).toBe(a!.width); expect(c!.height).toBe(a!.height)
  expect(Math.abs(c!.y - a!.y)).toBeLessThanOrEqual(1)
  await expect(compare.locator('svg.lucide-scale')).toHaveCount(1)
  await expect(add.locator('svg.lucide-plus')).toHaveCount(1)
  await expect(page.locator('svg.lucide-shopping-cart')).toHaveCount(0)
  await expect(compare).toHaveAttribute('title', 'Add to comparison')
  await expect(add).toHaveAttribute('title', 'Add to access package')

  // The state is a label and aria-pressed change, not only an icon change; a role cannot be added twice.
  const before = await add.evaluate(el => (el as HTMLElement).offsetLeft)
  await add.click()
  const remove = card.getByRole('button', { name: 'Remove from access package', exact: true })
  await expect(remove).toHaveAttribute('aria-pressed', 'true')
  await expect(remove).toHaveAttribute('title', 'Remove from access package')
  await expect(page.getByRole('button', { name: 'Access package (1)' })).toBeVisible()
  // Hover scaling is a transform; the layout position must not move when the state changes.
  expect(await remove.evaluate(el => (el as HTMLElement).offsetLeft)).toBe(before)
  await remove.click()
  await expect(page.getByRole('button', { name: 'Access package (0)' })).toBeVisible()
})

test('Settings navigation: active item is one filled rounded surface with no underline, in both themes', async ({ page }) => {
  for (const theme of ['light', 'dark']) {
    await page.emulateMedia({ colorScheme: theme as 'light' | 'dark' })
    await openSettings(page, 'Features')
    const active = page.getByRole('tab', { name: 'Features', exact: true }), other = page.getByRole('tab', { name: 'SAP Modules', exact: true })
    const style = await active.evaluate(el => { const s = getComputedStyle(el); return { bottom: s.borderBottomWidth, top: s.borderTopWidth, left: s.borderLeftWidth, right: s.borderRightWidth, radius: parseFloat(s.borderTopLeftRadius), background: s.backgroundColor, outline: s.outlineStyle } })
    expect([style.bottom, style.top, style.left, style.right], theme).toEqual(['0px', '0px', '0px', '0px'])
    expect(style.radius, theme).toBeGreaterThanOrEqual(6)
    expect(style.background, theme).not.toBe('rgba(0, 0, 0, 0)')
    const idle = await other.evaluate(el => ({ background: getComputedStyle(el).backgroundColor, bottom: getComputedStyle(el).borderBottomWidth }))
    expect(idle.background).toBe('rgba(0, 0, 0, 0)'); expect(idle.bottom).toBe('0px')
    // Equal geometry across items so selection never shifts the list.
    const heights = await page.getByRole('tab').evaluateAll(els => els.map(el => Math.round(el.getBoundingClientRect().height)))
    expect(new Set(heights).size, theme).toBe(1)
  }
})

test('Settings navigation: keyboard focus is a separate outline and arrow keys move the selection', async ({ page }) => {
  await openSettings(page, 'Features')
  const active = page.getByRole('tab', { name: 'Features', exact: true })
  await active.focus()
  await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
  await expect(active).toBeFocused()
  expect(await active.evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid')
  await page.keyboard.press('ArrowDown')
  const next = page.getByRole('tab', { selected: true })
  await expect(next).toBeFocused()
  await expect(next).not.toHaveText(/^Features$/)
  expect(await next.evaluate(el => getComputedStyle(el).borderBottomWidth)).toBe('0px')
})

// Shared geometry scan: the Settings tab bug class (a bottom indicator drawn on a rounded button) and doubled borders.
const borderDefects = () => {
  const out: string[] = []
  const widths = (s: CSSStyleDeclaration) => [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth].map(parseFloat)
  const name = (e: Element) => `${e.tagName.toLowerCase()}.${String(e.className).trim().split(/\s+/).slice(0, 2).join('.')} "${(e.textContent || '').trim().slice(0, 24)}"`
  for (const e of Array.from(document.querySelectorAll('body *'))) {
    const box = e.getBoundingClientRect()
    if (!box.width || !box.height) continue
    const style = getComputedStyle(e), [top, right, bottom, left] = widths(style)
    if (bottom > 0 && !top && !right && !left && parseFloat(style.borderTopLeftRadius) > 2) out.push(`rounded underline: ${name(e)}`)
    const parent = e.parentElement
    if (parent && top + right + bottom + left > 0 && style.borderTopStyle !== 'none') {
      const parentStyle = getComputedStyle(parent), [pt, pr, pb, pl] = widths(parentStyle), outer = parent.getBoundingClientRect()
      const inset = [box.top - outer.top - pt, outer.right - box.right - pr, outer.bottom - box.bottom - pb, box.left - outer.left - pl]
      if (pt + pr + pb + pl > 0 && parentStyle.borderTopStyle !== 'none' && inset.every(value => Math.abs(value) < 1.5)) out.push(`double border: ${name(parent)} > ${name(e)}`)
    }
  }
  return out
}

test('no rounded underlines or double borders on Settings sections and main screens in both themes', async ({ page, request }) => {
  test.setTimeout(240_000)
  await seedGovernance(request, 'static', undefined, true)
  const defects: string[] = []
  for (const theme of ['light', 'dark']) {
    const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
    settings.theme = theme
    expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
    await page.goto('about:blank'); await page.goto('/#session=browser-test-session')
    const main = page.getByRole('navigation', { name: 'Main navigation', exact: true })
    const scan = async (label: string) => { for (const defect of await page.evaluate(borderDefects)) defects.push(`${theme} ${label}: ${defect}`) }
    for (const link of ['Dashboard', 'Role Lookup', 'User Access', 'Release Roles', 'SoD']) { await main.getByRole('link', { name: link, exact: true }).click(); await scan(link) }
    for (const tab of ['Risk Matrix', 'Access Explorer', 'Reviews', 'Review Periods', 'Reports']) { await page.getByRole('link', { name: tab, exact: true }).first().click(); await scan(`SoD ${tab}`) }
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    for (const tab of await page.getByRole('tab').evaluateAll(els => els.map(element => element.getAttribute('aria-label')!))) { await page.getByRole('tab', { name: tab, exact: true }).click(); await scan(`Settings ${tab}`) }
  }
  expect(defects).toEqual([])
})

test('keyboard: identifiers are not tab stops, only their copy and open controls are, and small targets stay at least 24px', async ({ page, request }) => {
  await seedGovernance(request, 'static', undefined, true)
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'Role Lookup', exact: true }).click()
  await page.getByRole('article').first().waitFor()
  expect(await page.locator('.role-identifier code').evaluateAll(els => els.map(element => (element as HTMLElement).tabIndex))).not.toContain(0)
  for (let step = 0; step < 40; step++) {
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => document.activeElement?.tagName === 'CODE')).toBe(false)
  }
  await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'SoD', exact: true }).click()
  await page.getByRole('link', { name: 'Risk Matrix', exact: true }).first().click()
  await expect(page.locator('.matrix-row-button').first()).toBeVisible()
  for (const selector of ['.matrix-row-button', '.sod-tile > button']) {
    const heights = await page.locator(selector).evaluateAll(els => els.map(element => element.getBoundingClientRect().height))
    expect(heights.length, selector).toBeGreaterThan(0)
    for (const height of heights) expect(height, selector).toBeGreaterThanOrEqual(23.5)
  }
})

test('keyboard focus is fully revealed inside scrolling navigation strips at 375px', async ({ page, request }) => {
  await seedGovernance(request, 'static')
  await page.setViewportSize({ width: 375, height: 900 })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'SoD', exact: true }).click()
  await page.getByRole('link', { name: 'Overview', exact: true }).first().focus()
  const seen: string[] = []
  for (let step = 0; step < 8; step++) {
    await page.keyboard.press('Tab')
    const state = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement, strip = element.closest('nav.ui-secondary-navigation')
      if (!strip) return null
      const box = element.getBoundingClientRect(), area = strip.getBoundingClientRect()
      return { name: element.textContent!.trim(), inside: box.left >= area.left - 0.5 && box.right <= area.right + 0.5 }
    })
    if (!state) continue
    seen.push(state.name)
    expect(state.inside, state.name).toBe(true)
  }
  expect(seen).toEqual(expect.arrayContaining(['Activity Matrix', 'Reviews', 'Reports']))
})

test('skip link is fully visible when focused', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.keyboard.press('Tab')
  const skip = page.getByRole('link', { name: 'Skip to main content' })
  await expect(skip).toBeFocused()
  await expect.poll(async () => (await skip.boundingBox())!.y).toBeGreaterThanOrEqual(5)
})

test('access package panel takes focus when opened, stays non-modal, and returns focus to the trigger on Escape', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'Role Lookup', exact: true }).click()
  await page.getByRole('article', { name: /Buyer plant/ }).getByRole('button', { name: 'Add to access package' }).click()
  const trigger = page.getByRole('button', { name: 'Access package (1)' })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Proposed access package' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAttribute('aria-modal', 'false')
  expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true)
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

const contrastOf = (foreground: string, background: string) => {
  const channels = (value: string) => {
    const numbers = value.match(/-?[\d.]+/g)!.map(Number)
    return value.startsWith('color(') ? numbers.slice(0, 3).map(x => x * 255) : numbers.slice(0, 3)
  }
  const luminance = (value: string) => channels(value).map(x => { const c = x / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }).reduce((sum, c, index) => sum + c * [0.2126, 0.7152, 0.0722][index], 0)
  const [a, b] = [luminance(foreground), luminance(background)]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

test('selected Settings item and active role card toggles meet 4.5:1 text and 3:1 icon contrast in both themes', async ({ page, request }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' }) // the app zeroes transitions, so colors are final immediately
  for (const theme of ['light', 'dark']) {
    const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
    settings.theme = theme
    expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
    await page.goto('about:blank'); await page.goto('/#session=browser-test-session')
    await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('link', { name: 'Role Lookup', exact: true }).click()
    const card = page.getByRole('article', { name: /Buyer plant/ })
    for (const name of ['Add to access package', 'Add to comparison']) if (await card.getByRole('button', { name, exact: true }).count()) await card.getByRole('button', { name, exact: true }).click()
    await page.mouse.move(2, 2)
    for (const name of ['Remove from access package', 'Remove from comparison']) {
      const colors = await card.getByRole('button', { name }).evaluate(el => { const s = getComputedStyle(el); return [s.color, s.backgroundColor] })
      expect(contrastOf(colors[0], colors[1]), `${theme} ${name}`).toBeGreaterThanOrEqual(3)
    }
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    await page.getByRole('tab', { name: 'Features', exact: true }).click()
    await page.mouse.move(2, 2)
    for (const [name, minimum] of [['Features', 4.5], ['SAP Modules', 4.5]] as const) {
      const colors = await page.getByRole('tab', { name, exact: true }).evaluate(el => {
        let background = 'rgb(0, 0, 0)'
        for (let node: Element | null = el; node; node = node.parentElement) { const value = getComputedStyle(node).backgroundColor; if (!/rgba\(.*, 0\)$/.test(value) && value !== 'transparent') { background = value; break } }
        return [getComputedStyle(el).color, background]
      })
      expect(contrastOf(colors[0], colors[1]), `${theme} ${name}`).toBeGreaterThanOrEqual(minimum)
    }
  }
})

test('Component Library shows the production role card and Settings navigation previews', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Component Library', exact: true }).click()
  const card = page.getByRole('article', { name: /Demo finance display role/ })
  await expect(card.locator('svg.lucide-scale')).toHaveCount(1)
  await expect(card.locator('svg.lucide-plus')).toHaveCount(1)
  await card.getByRole('button', { name: 'Add to access package', exact: true }).click()
  await expect(card.getByRole('button', { name: 'Remove from access package', exact: true })).toHaveAttribute('aria-pressed', 'true')
  const preview = page.getByRole('tablist', { name: 'Settings navigation preview' })
  await preview.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
  await expect(preview.getByRole('tab', { name: 'SAP Modules', exact: true })).toHaveAttribute('aria-selected', 'true')
  expect(await preview.getByRole('tab', { name: 'SAP Modules', exact: true }).evaluate(el => getComputedStyle(el).borderBottomWidth)).toBe('0px')
})

test('Settings actions bar keeps Cancel and Apply on one row below the status at 375px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  const [status, cancel, apply] = await Promise.all(['.settings-actions > p', '.settings-actions button:has-text("Cancel")', '.settings-actions button:has-text("Apply settings")'].map(selector => page.locator(selector).first().boundingBox()))
  expect(Math.abs(cancel!.y - apply!.y)).toBeLessThanOrEqual(1)
  expect(cancel!.x + cancel!.width).toBeLessThanOrEqual(apply!.x)
  expect(status!.y + status!.height).toBeLessThanOrEqual(cancel!.y + 1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
