import { test, expect, type Page } from '@playwright/test'
import { cleanup, createPeriod, openSod, seedGovernance } from './sod-fixture'
import { goTo } from './support'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static'); await createPeriod(request, 'Status period') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })
test.setTimeout(120_000)

const zeroToneViolations = (page: Page) => page.evaluate(() => [...document.querySelectorAll<HTMLElement>('.ui-kpi, .info-row')].filter((element) => {
  const value = element.querySelector('.ui-kpi-value, .info-row-value')?.textContent?.trim() ?? ''
  return /^0(\.0+)?%?$/.test(value) && ['warning', 'error'].includes(element.dataset.tone || '')
}).map((element) => element.textContent?.trim().slice(0, 40)))
const badgeTexts = (page: Page) => page.evaluate(() => [...document.querySelectorAll<HTMLElement>('.evidence-badge, .status-pill')].map((element) => element.textContent?.trim() ?? '').filter(Boolean))

test('zero counts never use warning or danger styling on the main pages', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  expect(await zeroToneViolations(page)).toEqual([])
  await goTo(page, 'User Access'); await page.getByRole('navigation', { name: 'User Access view', exact: true }).getByRole('link', { name: 'Account Review', exact: true }).click()
  expect(await zeroToneViolations(page)).toEqual([])
  await openSod(page)
  expect(await zeroToneViolations(page)).toEqual([])
  const overdue = page.getByRole('region', { name: 'Remediation', exact: true }).getByRole('button', { name: 'Overdue actions' })
  await expect(overdue).toContainText('0'); await expect(overdue).toHaveAttribute('data-tone', 'neutral')
  await page.getByRole('link', { name: 'Risk Matrix', exact: true }).click()
  expect(await zeroToneViolations(page)).toEqual([])
  await expect(page.getByRole('button', { name: /^Rejected risks/ })).toHaveAttribute('data-tone', 'neutral')
})

test('status labels are never lowercase enum values and Enabled, Disabled, Static and Dynamic carry their icon', async ({ page }) => {
  const check = async () => { for (const text of await badgeTexts(page)) expect(text, `label "${text}"`).not.toMatch(/^[a-z]/); }
  await page.goto('/#session=browser-test-session'); await check()
  const modes = page.locator('.evidence-badge', { hasText: /^(Static|Dynamic)$/ })
  await expect(modes.first()).toBeVisible()
  for (let index = 0; index < await modes.count(); index++) await expect(modes.nth(index).locator('svg')).toHaveCount(1)
  await openSod(page); await check()
  await page.getByRole('link', { name: 'Review Periods', exact: true }).click(); await check()
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Health & Diagnostics', exact: true }).click(); await check()
  const enabled = page.locator('.evidence-badge', { hasText: /^(Enabled|Disabled)$/ })
  expect(await enabled.count()).toBeGreaterThan(0)
  for (let index = 0; index < await enabled.count(); index++) await expect(enabled.nth(index).locator('svg')).toHaveCount(1)
  await page.getByRole('tab', { name: 'SoD Risk Configuration', exact: true }).click(); await check()
})

for (const theme of ['light', 'dark']) test(`keyboard focus is one visible, rounded ring across the SoD pages and Settings (${theme})`, async ({ page, request }) => {
  const settings = (await (await request.get('/api/configuration', { headers: { 'X-SAP-Lens': 'browser-test-session' } })).json().catch(() => ({ settings: {} }))).settings
  if (settings?.theme !== undefined) { settings.theme = theme; await request.post('/api/configuration', { headers: { 'X-SAP-Lens': 'browser-test-session' }, data: settings }) }
  await page.setViewportSize({ width: 1280, height: 900 })
  const ring = () => page.evaluate(() => {
    const element = document.activeElement as HTMLElement | null
    if (!element || element === document.body) return null
    const style = getComputedStyle(element), radii = [style.borderTopLeftRadius, style.borderTopRightRadius, style.borderBottomRightRadius, style.borderBottomLeftRadius].map(parseFloat)
    return { name: `${element.tagName.toLowerCase()}.${(element.getAttribute('class') || '').split(' ')[0]}[${(element.getAttribute('aria-label') || element.textContent || '').trim().slice(0, 30)}]`, visible: style.outlineStyle === 'solid' && parseFloat(style.outlineWidth) >= 2, rounded: radii.every((value) => value > 0), shown: !!element.getClientRects().length }
  })
  const walk = async (steps: number) => {
    const problems: string[] = []
    await page.locator('body').click({ position: { x: 1, y: 1 } })
    for (let step = 0; step < steps; step++) {
      await page.keyboard.press('Tab')
      const info = await ring()
      if (info?.shown && (!info.visible || !info.rounded)) problems.push(`${info.name}: ${!info.visible ? 'no ring' : 'square corners'}`)
    }
    return [...new Set(problems)]
  }
  await openSod(page)
  expect(await walk(45)).toEqual([])
  await page.getByRole('link', { name: 'Risk Matrix', exact: true }).click()
  expect(await walk(60)).toEqual([])
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'SoD Risk Configuration', exact: true }).click()
  expect(await walk(45)).toEqual([])
})
