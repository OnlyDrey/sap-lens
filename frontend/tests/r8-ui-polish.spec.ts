import { test, expect, type Page } from '@playwright/test'
import { goTo, headers, openSettings, seedSources } from './support'

const long = 'MM - ' + 'A deliberately long composite role description that must wrap over several lines inside the role card without moving the module badge away from its first line. '.repeat(2)
const roles = 'AGR_NAME,TEXT,CHILD_AGR,TCODE\n' + [['ZC:R8:LONG', long, 'ZS:R8:LONG', 'ME21N'], ['ZC:R8:SHORT', 'MM - Short description', 'ZS:R8:SHORT', 'ME22N']].map((row) => row.join(',')).join('\n') + '\n'
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
    const head = entry.querySelector('.role-entry-head')!, badge = head.querySelector('.module-badge'), title = head.querySelector('.role-entry-title')!
    const range = document.createRange(); range.selectNodeContents(title)
    const lines = [...range.getClientRects()], first = lines[0], box = entry.getBoundingClientRect(), actions = head.querySelector('.role-entry-actions')?.getBoundingClientRect()
    const rows = new Set(lines.map((line) => Math.round(line.top)))
    return { text: title.textContent!.slice(0, 20), badgeCentre: badge ? badge.getBoundingClientRect().top + badge.getBoundingClientRect().height / 2 : null, firstLineCentre: first.top + first.height / 2, lineCount: rows.size, top: box.top, height: box.height, headTop: head.getBoundingClientRect().top, actionsTop: actions?.top ?? null }
  }))
}

for (const theme of ['light', 'dark']) for (const width of [375, 800, 1280, 1600]) test(`Role Lookup: the module badge sits level with the first description line in ${theme} at ${width}px`, async ({ page, request }) => {
  await setTheme(request, theme)
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Role Lookup')
  await expect(page.locator('.role-entry').first()).toBeVisible()
  await expect(page.locator('.role-entry')).toHaveCount(2)
  const entries = await geometry(page)
  const wrapped = entries.find((entry) => entry.lineCount > 1)
  expect(wrapped, 'the long description wraps over several lines').toBeTruthy()
  for (const entry of entries) {
    if (entry.badgeCentre !== null) expect(Math.abs(entry.badgeCentre - entry.firstLineCentre), entry.text).toBeLessThan(6) // the badge follows the first line, not the whole block
    if (entry.actionsTop !== null) expect(entry.actionsTop - entry.headTop, 'actions stay at the top right').toBeLessThan(6)
  }
  // cards in one row keep one height, so their bottom-aligned actions line up
  const sameRow = entries.filter((entry) => Math.abs(entry.top - entries[0].top) < 2)
  if (sameRow.length > 1) expect(new Set(sameRow.map((entry) => Math.round(entry.height))).size).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  if (process.env.SHOTS && [375, 1280].includes(width)) await page.screenshot({ path: `${process.env.SHOTS}/lookup-${theme}-${width}.png` })
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
