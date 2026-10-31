import { test, expect, type Page } from '@playwright/test'
import { cleanup, longRoleName, openSod, seedGovernance } from './sod-fixture'
import { goTo, seedSources, type SeededSources } from './support'

/** A SAP role name is always one complete line: no wrapping, scrolling, clipping or ellipsis; the copy icon stays beside it. */
const MEDIUM = 'ZC:SYN:LONG_ROLE_IDENTIFIER_FOR_LAYOUT:ENP'
const LONG = 'ZC:SYN:A_VERY_LONG_ROLE_IDENTIFIER_FOR_LAYOUT_STRESS_TESTING:ABCDEFGHIJKLMNOP:0123456789:QRSTUV'
const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
MM,${MEDIUM},Medium identifier role,ZS:MED,MM - Medium,MIGO,Goods movement
MM,${LONG},Long identifier role,ZS:LONG,MM - Long,ME21N,Create purchase order
`
const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
U1,ZC:MM:BUY:ENP,G1,20200101,99991231
U1,${MEDIUM},G1,20200101,99991231
U2,${LONG},G2,20200101,99991231
U2,${MEDIUM},G2,20200101,99991231
`

/** Problems with every visible role codeblock on the page. `complete` allows a scroll region of the layout (a table, a dialog body) to bring a name that cannot fit into view; otherwise it must be fully on screen. */
async function violations(page: Page, complete = false, only: string[] = []) {
  return page.evaluate(({ onlyComplete, names }) => {
    const problems: string[] = []
    const clips = (node: Element) => {
      const rects: { box: DOMRect; scroll: boolean }[] = []
      for (let parent = node.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent)
        if (style.overflowX !== 'visible') rects.push({ box: parent.getBoundingClientRect(), scroll: style.overflowX === 'auto' || style.overflowX === 'scroll' })
      }
      rects.push({ box: new DOMRect(0, 0, innerWidth, innerHeight), scroll: false })
      return rects
    }
    for (const root of document.querySelectorAll<HTMLElement>('.role-identifier')) {
      const code = root.querySelector('code')
      if (!code || !root.getClientRects().length) continue
      const name = code.textContent || ''
      if (names.length && !names.includes(name)) continue
      const style = getComputedStyle(code), box = code.getBoundingClientRect()
      const button = root.querySelector<HTMLElement>('button[aria-label^="Copy "]'), buttonBox = button?.getBoundingClientRect()
      const where = root.closest('[role=dialog],article,table,aside,section')
      const label = `${name.slice(0, 24)}… (${Math.round(box.width)}px, in ${where?.tagName.toLowerCase()}.${(where?.getAttribute('class') || '').split(' ')[0]}, font ${style.fontSize}, fit ${root.dataset.fit})`
      if (style.whiteSpace !== 'nowrap') problems.push(`${label}: white-space ${style.whiteSpace}`)
      if (style.overflowX !== 'visible' || style.overflowY !== 'visible') problems.push(`${label}: overflow ${style.overflowX}/${style.overflowY}`)
      if (style.textOverflow !== 'clip') problems.push(`${label}: text-overflow ${style.textOverflow}`)
      if (code.scrollWidth > code.clientWidth + 1 || code.scrollHeight > code.clientHeight + 1) problems.push(`${label}: scrolls internally`)
      if (box.height > parseFloat(style.lineHeight) * 1.5) problems.push(`${label}: wraps onto ${Math.round(box.height)}px`)
      if (!buttonBox || !buttonBox.width) problems.push(`${label}: no copy icon`)
      else if (buttonBox.top > box.bottom || buttonBox.bottom < box.top) problems.push(`${label}: copy icon is not beside the name`)
      for (const { box: area, scroll } of clips(code)) {
        if (onlyComplete && scroll) break // a scroll region of the layout owns everything beyond this point
        if (box.left < area.left - 1 || box.right > area.right + 1) problems.push(`${label}: clipped by a container (${Math.round(box.left)}-${Math.round(box.right)} of ${Math.round(area.left)}-${Math.round(area.right)})`)
        if (buttonBox && buttonBox.width && buttonBox.right > area.right + 1) problems.push(`${label}: copy icon is clipped by a container`)
      }
    }
    return problems
  }, { onlyComplete: complete, names: only })
}
/** Realistic names must be fully on screen; names too long for the viewport at the smallest readable size keep their full single line and may only be reached through a scroll region of the layout, never through the codeblock itself. */
async function expectLines(page: Page) {
  expect(await violations(page, false, [MEDIUM, 'ZC:MM:BUY:ENP'])).toEqual([])
  expect(await violations(page, true, [LONG, longRoleName])).toEqual([])
}
const shown = (page: Page, name: string) => page.locator('.role-identifier code', { hasText: name }).first()

test.describe('role codeblocks with synthetic names', () => {
  let seeded: SeededSources
  test.beforeEach(async ({ request }) => { seeded = await seedSources(request, { roles, users }) })
  test.afterEach(async () => { await seeded.cleanup() })

  for (const width of [375, 800, 1280]) {
    test(`Role Lookup cards, role details and the Access Package keep every name on one visible line at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
      await expect(shown(page, MEDIUM)).toBeVisible()
      await expect(shown(page, LONG)).toBeVisible()
      expect(await shown(page, LONG).evaluate((element) => element.textContent)).toBe(LONG) // no truncation
      await expectLines(page)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
      // role details dialog
      await page.getByRole('article', { name: /Medium identifier role$/ }).getByRole('button', { name: /^View details/ }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await expectLines(page)
      await page.getByRole('button', { name: 'Close role details' }).click()
      // Access Package panel (side panel) with both names, then with a suffix applied
      for (const title of [/Medium identifier role$/, /Long identifier role$/]) await page.getByRole('article', { name: title }).getByRole('button', { name: 'Add to access package' }).click()
      await page.getByRole('button', { name: /^Access package \(2\)$/ }).click()
      const panel = page.getByRole('dialog', { name: 'Proposed access package' })
      await expect(panel.locator('.role-identifier code').first()).toBeVisible()
      await expectLines(page)
      expect(await panel.locator('.role-identifier code', { hasText: MEDIUM }).evaluate((element) => element.getBoundingClientRect().right <= innerWidth + 1)).toBeTruthy()
    })
  }

  test('copying still writes the exact role name', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.setViewportSize({ width: 375, height: 900 })
    await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
    await page.getByRole('button', { name: `Copy role identifier ${LONG}`, exact: true }).first().click()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(LONG)
  })

  test('narrow containers scale the font instead of wrapping, and a wide container keeps the normal size', async ({ page }) => {
    await page.goto('/#session=browser-test-session'); await goTo(page, 'Role Lookup')
    const size = (name: string) => shown(page, name).evaluate((element) => parseFloat(getComputedStyle(element).fontSize))
    await page.setViewportSize({ width: 1600, height: 900 })
    await expect.poll(() => size(MEDIUM)).toBeGreaterThanOrEqual(12)
    const wide = await size(MEDIUM)
    await page.setViewportSize({ width: 375, height: 900 })
    await expect.poll(() => size(MEDIUM)).toBeLessThan(wide)
    expect(await size(MEDIUM)).toBeGreaterThanOrEqual(9) // never below the readable floor
    await expectLines(page)
    await page.setViewportSize({ width: 1600, height: 900 })
    await expect.poll(() => size(MEDIUM)).toBe(wide) // and it grows back
  })

  for (const width of [375, 1280]) {
    test(`User Access and the role comparison keep names single-line at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await page.goto('/#session=browser-test-session'); await goTo(page, 'User Access')
      await page.getByRole('link', { name: 'U2', exact: true }).click()
      await expect(shown(page, LONG)).toBeVisible()
      // assignment tables are scroll regions of their own layout: names stay complete single lines and a table scrolls, never a codeblock
      expect(await violations(page, true, [MEDIUM, LONG, 'ZC:MM:BUY:ENP'])).toEqual([])
    })
  }
})

test.describe('role codeblocks in the SoD workspace', () => {
  let directory = ''
  test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static', undefined, true) })
  test.afterEach(async ({ request }) => { await cleanup(request, directory) })

  for (const width of [375, 800, 1280]) {
    test(`Access Explorer and Reviews show ${longRoleName.length}-character names on one line at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await openSod(page, 'Access Explorer')
      await expect(page.locator('.role-identifier code').first()).toBeVisible()
      await expectLines(page)
      await openSod(page, 'Reviews')
      await expectLines(page)
    })
  }
})
