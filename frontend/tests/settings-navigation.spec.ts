import { test, expect, type Page } from '@playwright/test'

// Settings sidebar: Back at the top, four groups that scroll on their own, About SAP Lens as the footer. Without a sign-in server (this fixture)
// User Management is not listed; with one, administrators see it (authentication.spec.ts clicks it).
const groups: [string, string[]][] = [
  ['General', ['Organization & SAP System', 'Appearance & Branding']],
  ['Data & Integrations', ['Data Sources', 'SAP Modules', 'Runtime & Scheduling', 'Functional Groups']],
  ['Security & Governance', ['SoD Risk Configuration', 'Backup & Restore']],
  ['System & Tools', ['Health & Diagnostics', 'Features', 'Component Library']],
]
const order = [...groups.flatMap(([, tabs]) => tabs), 'About SAP Lens']

const open = async (page: Page, width = 1280, height = 900) => {
  await page.setViewportSize({ width, height })
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await expect(page.getByRole('tablist', { name: 'Settings sections' })).toBeVisible()
}

test('settings navigation is grouped, ordered, and every section opens with its heading @workflow', async ({ page }) => {
  await open(page)
  const nav = page.getByRole('tablist', { name: 'Settings sections' })
  await expect(nav.getByRole('tab')).toHaveText(order)
  await expect(nav.locator('.settings-nav-category')).toHaveText(groups.map(([label]) => label))
  for (const [label, tabs] of groups) await expect(nav.locator('.settings-nav-group').filter({ hasText: label }).getByRole('tab')).toHaveText(tabs)
  await expect(nav.locator('.settings-nav-footer').getByRole('tab')).toHaveText(['About SAP Lens'])
  await expect(nav.getByRole('tab', { name: 'User Management', exact: true })).toHaveCount(0)
  // Back to SAP Lens stays first, outside the tab list.
  const back = page.getByRole('button', { name: 'Back to SAP Lens', exact: true })
  expect((await back.boundingBox())!.y).toBeLessThan((await nav.boundingBox())!.y)
  for (const name of order) {
    await nav.getByRole('tab', { name, exact: true }).click()
    await expect(nav.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('#settings-heading')).toHaveText(name)
    await expect(nav.locator('[aria-selected="true"]')).toHaveCount(1)
  }
})

test('arrow keys follow the visual order and wrap through the About footer @component', async ({ page }) => {
  await open(page)
  const nav = page.getByRole('tablist', { name: 'Settings sections' })
  await nav.getByRole('tab', { name: order[0], exact: true }).focus()
  for (const name of order.slice(1)) {
    await page.keyboard.press('ArrowDown')
    await expect(nav.getByRole('tab', { name, exact: true })).toBeFocused()
    await expect(nav.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true')
  }
  await page.keyboard.press('ArrowDown')
  await expect(nav.getByRole('tab', { name: order[0], exact: true })).toBeFocused()
  await page.keyboard.press('ArrowUp')
  await expect(nav.getByRole('tab', { name: 'About SAP Lens', exact: true })).toBeFocused()
  await page.keyboard.press('Home')
  await expect(nav.getByRole('tab', { name: order[0], exact: true })).toBeFocused()
  await page.keyboard.press('End')
  await expect(nav.getByRole('tab', { name: 'About SAP Lens', exact: true })).toBeFocused()
  // Only the focused tab is in the Tab sequence.
  await expect(nav.locator('[role="tab"][tabindex="0"]')).toHaveCount(1)
})

for (const [width, height] of [[1280, 900], [1280, 520], [800, 600], [375, 700]]) {
  test(`About stays at the bottom and only the groups scroll at ${width}x${height} @visual`, async ({ page }) => {
    await open(page, width, height)
    const sidebar = page.locator('.settings-sidebar')
    const scroll = page.locator('.settings-nav-scroll')
    const about = page.getByRole('tab', { name: 'About SAP Lens', exact: true })
    const side = (await sidebar.boundingBox())!, aboutBox = (await about.boundingBox())!, scrollBox = (await scroll.boundingBox())!
    // The footer sits at the bottom of the sidebar, below the scroll area, inside the viewport.
    expect(aboutBox.y + aboutBox.height).toBeLessThanOrEqual(side.y + side.height + 1)
    expect(aboutBox.y + aboutBox.height).toBeLessThanOrEqual(height)
    expect(aboutBox.y).toBeGreaterThanOrEqual(scrollBox.y + scrollBox.height - 1)
    // The sidebar itself never scrolls; the group list may.
    expect(await sidebar.evaluate(el => el.scrollHeight <= el.clientHeight + 1)).toBe(true)
    if (height < 600) expect(await scroll.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
    // The last group tab can be scrolled into view without overlapping the footer.
    const last = page.getByRole('tab', { name: 'Component Library', exact: true })
    await last.scrollIntoViewIfNeeded()
    const lastBox = (await last.boundingBox())!
    expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(aboutBox.y)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (width <= 700) await expect(page.locator('.settings-nav-category').first()).toBeHidden()   // icon rail: labels hidden, tabs keep their names
  })
}
