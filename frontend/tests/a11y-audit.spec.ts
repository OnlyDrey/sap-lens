import { test, expect, type Page } from '@playwright/test'
import { cleanup, createPeriod, openSod, seedGovernance } from './sod-fixture'

test.setTimeout(300_000)
let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const main = (page: Page) => page.getByRole('navigation', { name: 'Main navigation', exact: true })

/** Static checks plus a Tab walk: names, tab order hygiene, visible and unclipped focus indicators. */
async function audit(page: Page, name: string, stops = 60) {
  const problems: string[] = []
  const statics = await page.evaluate(() => {
    const issues: string[] = []
    const visible = (element: Element) => { const box = element.getBoundingClientRect(); const style = getComputedStyle(element); return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' }
    const nameOf = (element: HTMLElement) => {
      const labelled = element.getAttribute('aria-labelledby')?.split(' ').map((id) => document.getElementById(id)?.textContent).join(' ')
      const label = (element as HTMLInputElement).labels?.[0]?.textContent
      return (element.getAttribute('aria-label') || labelled || label || element.textContent || element.getAttribute('title') || element.getAttribute('placeholder') || '').replace(/\s+/g, ' ').trim()
    }
    for (const element of document.querySelectorAll<HTMLElement>('[tabindex]')) if (Number(element.getAttribute('tabindex')) > 0) issues.push(`positive tabindex on ${element.tagName.toLowerCase()}.${element.className}`)
    for (const element of document.querySelectorAll<HTMLElement>('button,a[href],input:not([type=hidden]),select,textarea,[role=button],[role=tab],[role=checkbox],[role=switch],[role=combobox],[role=link]')) {
      if (!visible(element) && !element.matches('input[type=checkbox],input[type=radio]')) continue
      if (!nameOf(element)) issues.push(`unnamed ${element.tagName.toLowerCase()}.${String(element.className).slice(0, 40)}`)
      if ((element as HTMLButtonElement).disabled && element.tabIndex >= 0 && element.matches('a')) issues.push('disabled link focusable')
    }
    return issues
  })
  problems.push(...statics.map((issue) => `${name}: ${issue}`))
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.mouse.click(1, 1).catch(() => undefined)
  const seen = new Set<string>()
  for (let step = 0; step < stops; step++) {
    await page.keyboard.press('Tab')
    const info = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null
      if (!element || element === document.body) return null
      const style = getComputedStyle(element)
      const box = element.getBoundingClientRect()
      const labelled = element.getAttribute('aria-labelledby')?.split(' ').map((id) => document.getElementById(id)?.textContent).join(' ')
      const label = (element as HTMLInputElement).labels?.[0]?.textContent
      const label2 = (element.getAttribute('aria-label') || labelled || label || element.textContent || element.getAttribute('title') || '').replace(/\s+/g, ' ').trim().slice(0, 50)
      const width = parseFloat(style.outlineWidth) || 0, offset = parseFloat(style.outlineOffset) || 0
      const ringOf = (target: Element) => { const css = getComputedStyle(target); return (css.outlineStyle !== 'none' && parseFloat(css.outlineWidth) > 0) || (css.boxShadow !== 'none' && css.boxShadow !== '') }
      const ring = ringOf(element) || (element.closest('label') ? ringOf(element.closest('label')!) : false)
      const inflate = style.outlineStyle !== 'none' ? Math.max(0, width + offset) : 0
      let clipped = ''
      for (let parent = element.parentElement; parent && parent !== document.documentElement; parent = parent.parentElement) {
        const parentStyle = getComputedStyle(parent)
        if ((parentStyle.overflowX === 'visible' && parentStyle.overflowY === 'visible') || parent === document.body) continue
        const p = parent.getBoundingClientRect()
        if (box.left >= p.left && box.right <= p.right && box.top >= p.top && box.bottom <= p.bottom && (box.left - inflate < p.left - 0.5 || box.right + inflate > p.right + 0.5 || box.top - inflate < p.top - 0.5 || box.bottom + inflate > p.bottom + 0.5)) { clipped = `${parent.tagName.toLowerCase()}.${String(parent.className).slice(0, 40)}`; break }
      }
      return { tag: element.tagName.toLowerCase(), cls: String(element.className).slice(0, 40), label: label2, ring, clipped, srOnly: element.closest('.sr-only') !== null, code: element.tagName === 'CODE', disabled: (element as HTMLButtonElement).disabled === true, key: `${element.tagName}|${label2}|${Math.round(box.x)}|${Math.round(box.y)}` }
    })
    if (!info) continue
    if (seen.has(info.key)) break
    seen.add(info.key)
    if (info.srOnly && info.tag !== 'input') problems.push(`${name}: focus on sr-only ${info.tag} "${info.label}"`)
    if (!info.label) problems.push(`${name}: tab stop without name (${info.tag}.${info.cls})`)
    if (!info.ring) problems.push(`${name}: no visible focus indicator on ${info.tag} "${info.label}"`)
    if (info.clipped) problems.push(`${name}: focus ring clipped by ${info.clipped} on ${info.tag} "${info.label}"`)
    if (info.code) problems.push(`${name}: code element is a tab stop`)
    if (info.disabled) problems.push(`${name}: disabled control received focus "${info.label}"`)
  }
  return problems
}

test('major views have names, sane tab order and visible, unclipped focus indicators', async ({ page }) => {
  const problems: string[] = []
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 })
    const tag = (label: string) => `${label}@${width}`
    await page.goto('/#session=browser-test-session')
    problems.push(...await audit(page, tag('dashboard')))
    for (const label of ['Role Lookup', 'User Access', 'Release Roles']) {
      await main(page).getByRole('link', { name: label, exact: true }).click()
      problems.push(...await audit(page, tag(label)))
    }
    for (const view of ['Overview', 'Risk Matrix', 'Activity Matrix', 'Access Explorer', 'Reviews', 'Review Periods', 'Reports']) {
      await openSod(page, view)
      problems.push(...await audit(page, tag('SoD ' + view)))
    }
    await page.goto('/#session=browser-test-session')
    await page.getByRole('button', { name: 'Open settings', exact: true }).click()
    for (const section of ['Organization & SAP System', 'Data Sources', 'SAP Modules', 'SoD Risk Configuration', 'Features', 'Runtime & Scheduling', 'Health & Diagnostics']) {
      await page.getByRole('tab', { name: section, exact: true }).click()
      problems.push(...await audit(page, tag('Settings ' + section), 40))
    }
  }
  const unique = [...new Set(problems)]
  console.log('A11Y_PROBLEMS', unique.length)
  for (const problem of unique) console.log('A11Y', problem)
  expect(unique).toEqual([])
})

test('dialogs trap and restore focus, popovers return focus on Escape, sidebars are keyboard operable', async ({ page, request }) => {
  await createPeriod(request, 'Focus period')
  await openSod(page, 'Review Periods')
  const trigger = page.getByRole('button', { name: 'Create review period', exact: true })
  await trigger.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Create SoD review period', exact: true })
  await expect(dialog).toBeVisible()
  expect(await page.evaluate(() => !!document.activeElement?.closest('[role=dialog]'))).toBeTruthy()
  for (let step = 0; step < 12; step++) await page.keyboard.press('Tab')
  expect(await page.evaluate(() => !!document.activeElement?.closest('[role=dialog]'))).toBeTruthy()
  for (let step = 0; step < 12; step++) await page.keyboard.press('Shift+Tab')
  expect(await page.evaluate(() => !!document.activeElement?.closest('[role=dialog]'))).toBeTruthy()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  const menu = page.getByRole('button', { name: 'Actions for Focus period', exact: true })
  await menu.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Actions for Focus period', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Actions for Focus period', exact: true })).toHaveCount(0)
  await expect(menu).toBeFocused()
  await openSod(page, 'Risk Matrix')
  const toggle = page.getByRole('button', { name: /^Hide filters/ })
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('complementary', { name: 'Filters', exact: true })).toBeHidden()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('complementary', { name: 'Filters', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Hide filters/ })).toBeFocused()
})
