import { test, expect, type Page } from '@playwright/test'
import { goTo, headers, openSettings, seedSources } from './support'

const english = 'MM - A deliberately long composite role description that must stay on one line inside the role card and end in an ellipsis instead of wrapping or pushing the action buttons away from the edge of the card'
const french = "MM - Gestion des achats : description volontairement très longue d'un rôle composite, avec des accents (é, è, ê, à, ç, œ) et des caractères spéciaux — elle doit rester sur une seule ligne et se terminer par des points de suspension"
const roles = 'AGR_NAME,TEXT,CHILD_AGR,TCODE\n' + [['ZC:R8:LONG', english, 'ZS:R8:LONG', 'ME21N'], ['ZC:R8:FR', `"${french}"`, 'ZS:R8:FR', 'ME23N'], ['ZC:R8:SHORT', 'MM - Short description', 'ZS:R8:SHORT', 'ME22N']].map((row) => row.join(',')).join('\n') + '\n'
let cleanup: () => Promise<void> = async () => undefined
test.beforeEach(async ({ request }) => { cleanup = (await seedSources(request, { roles })).cleanup })
test.afterEach(async () => { await cleanup() })
test.setTimeout(120_000)

const setTheme = async (request: Parameters<typeof seedSources>[0], theme: string) => {
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings; settings.theme = theme
  await request.post('/api/configuration', { headers, data: settings })
}
async function geometry(page: Page) {
  return page.locator('.role-entry').evaluateAll((entries) => entries.map((entry) => {
    const head = entry.querySelector('.role-entry-head')!, box = (element: Element | null) => element?.getBoundingClientRect()
    const centre = (element: Element | null) => { const rect = box(element); return rect ? rect.top + rect.height / 2 : null }
    const line = (head.querySelector('.truncated-text-line') ?? head.querySelector('.role-entry-title'))!, style = getComputedStyle(head.querySelector('.role-entry-title')!)
    const actions = head.querySelector('.role-entry-actions')
    return { text: line.textContent!.slice(0, 20), head: box(head)!.height, headCentre: centre(head), badge: centre(head.querySelector('.module-badge')), title: centre(line), actions: centre(actions), actionsWidth: box(actions)?.width ?? 0,
      actionsRight: box(actions)?.right ?? 0, headRight: box(head)!.right, lineHeight: box(line)!.height, fontLine: parseFloat(style.lineHeight), cut: line.scrollWidth > line.clientWidth + 1, trigger: !!head.querySelector('button.truncated-trigger'), top: box(entry)!.top }
  }))
}

for (const theme of ['light', 'dark']) for (const width of [320, 375, 800, 1280, 1600]) test(`Role Lookup: headers are one centered line with an ellipsis and the full text on demand in ${theme} at ${width}px`, async ({ page, request }) => {
  await setTheme(request, theme)
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Role Lookup')
  await expect(page.locator('.role-entry')).toHaveCount(3)
  const entries = await geometry(page)
  for (const entry of entries) {
    expect(entry.lineHeight, `${entry.text}: one line`).toBeLessThanOrEqual(entry.fontLine + 1)
    for (const axis of [entry.badge, entry.title, entry.actions]) if (axis !== null) expect(Math.abs(axis - entry.headCentre!), `${entry.text}: shared horizontal axis`).toBeLessThan(2)
    expect(entry.actionsWidth, 'the action buttons keep their width').toBeGreaterThan(60)
    expect(entry.actionsRight).toBeLessThanOrEqual(entry.headRight + 1)
  }
  expect(new Set(entries.map((entry) => Math.round(entry.head))).size, 'one header height for every card').toBe(1)
  const [longEntry, frenchEntry, shortEntry] = ['ZC:R8:LONG', 'ZC:R8:FR', 'ZC:R8:SHORT'].map((id) => page.locator('.role-entry').filter({ hasText: id }))
  // the short description fits: plain text, no button, no tooltip
  for (const entry of entries) expect(entry.trigger, `${entry.text}: a reveal control exists exactly when the text is cut off`).toBe(entry.cut)
  if (width >= 800) await expect(shortEntry.locator('button.truncated-trigger')).toHaveCount(0)
  expect(await shortEntry.locator('.role-entry-title').evaluate((element) => element.hasAttribute('title') || !!element.querySelector('[title]'))).toBe(false)
  // the long English and French descriptions are cut off and expose the complete text three ways
  for (const [entry, fragment] of [[longEntry, 'pushing the action buttons'], [frenchEntry, 'points de suspension']] as const) {
    const trigger = entry.locator('button.truncated-trigger')
    await expect(trigger).toHaveCount(1)
    expect(await trigger.evaluate((element) => getComputedStyle(element.querySelector('.truncated-text-line')!).textOverflow)).toBe('ellipsis')
    await expect(trigger).toHaveAttribute('aria-haspopup', 'dialog')
    const popover = page.getByRole('dialog', { name: 'Role description' })
    await trigger.hover()                                         // hover
    await expect(popover).toContainText(fragment)
    await page.mouse.move(0, 0); await expect(popover).toHaveCount(0)
    await page.keyboard.press('Shift'); await trigger.focus()      // keyboard focus
    await expect(popover).toContainText(fragment)
    await page.keyboard.press('Escape'); await expect(popover).toHaveCount(0); await expect(trigger).toBeFocused()
    await trigger.click()                                          // click or tap stays open until dismissed
    await expect(popover).toContainText(fragment)
    await page.mouse.move(0, 0); await expect(popover).toHaveCount(1)
    await page.mouse.click(5, 5); await expect(popover).toHaveCount(0)
    expect(await page.locator('.role-details, [role=dialog][aria-label*="details" i]').count(), 'the click did not open the card details').toBe(0)
    const box = await trigger.boundingBox(); expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  if (process.env.SHOTS && [320, 1280].includes(width)) await page.screenshot({ path: `${process.env.SHOTS}/lookup-${theme}-${width}.png` })
})

for (const theme of ['light', 'dark']) test(`Component Library: the category tabs keep their underline, an 8px gap and the application scrollbar in ${theme}`, async ({ page, request }) => {
  await setTheme(request, theme)
  await page.setViewportSize({ width: 375, height: 900 })
  await openSettings(page, 'Component Library')
  const strip = page.getByRole('tablist', { name: 'Component categories' })
  await expect(strip).toBeVisible()
  const facts = await strip.evaluate((element) => {
    const style = getComputedStyle(element), bar = getComputedStyle(element, '::-webkit-scrollbar'), thumb = getComputedStyle(element, '::-webkit-scrollbar-thumb')
    const root = getComputedStyle(document.documentElement), tab = element.querySelector('[aria-selected="true"]')!, tabBox = tab.getBoundingClientRect(), box = element.getBoundingClientRect()
    return { overflows: element.scrollWidth > element.clientWidth, overflowX: style.overflowX, scrollbarWidth: style.scrollbarWidth, padding: style.paddingBottom, bar: bar.height, thumb: thumb.backgroundColor, accent: root.getPropertyValue('--accent2').trim(), tokenSize: root.getPropertyValue('--scrollbar-size').trim(),
      barHeight: element.offsetHeight - element.clientHeight, underline: getComputedStyle(tab).borderBottomWidth, gapBelowTab: box.top + element.clientHeight - tabBox.bottom }
  })
  expect(facts.overflows).toBe(true)
  expect(facts.overflowX).toBe('auto')
  expect(facts.scrollbarWidth).toBe('auto') // the application scrollbar styling is not switched off
  expect(facts.padding).toBe('8px')
  expect(facts.bar).toBe('5px') // the token size (headless browsers hide scrollbars, so the styling is read from the pseudo-element)
  expect(facts.tokenSize).toBe('5px')
  expect(facts.underline).toBe('2px')
  expect(facts.gapBelowTab).toBeGreaterThanOrEqual(7) // about 8px between the active underline and the scrollbar
  expect(facts.thumb).not.toBe('rgba(0, 0, 0, 0)') // the thumb uses the accent token
  // keyboard: arrows move focus and keep the focused tab inside the scroller
  await strip.getByRole('tab').first().focus(); await page.keyboard.press('End')
  const last = strip.getByRole('tab').last()
  await expect(last).toBeFocused()
  const [lastBox, area] = [(await last.boundingBox())!, (await strip.boundingBox())!]
  expect(lastBox.x + lastBox.width).toBeLessThanOrEqual(area.x + area.width + 1)
  // scrolling by touchpad or wheel stays inside the strip
  await strip.hover(); await page.mouse.wheel(300, 0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/library-${theme}-375.png` })
})
