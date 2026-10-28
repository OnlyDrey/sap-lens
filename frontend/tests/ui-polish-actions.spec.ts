import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const headers = { 'X-SAP-Lens': 'browser-test-session' }
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
