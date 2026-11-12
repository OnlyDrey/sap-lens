import {expectReviewerProfile} from './reviewer-profile'
import { test, expect, type Locator, type Page } from '@playwright/test'
import { cellButton, cleanup, headers, names, openSod, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const token = (page: Page, name: string, property: 'color' | 'backgroundColor' | 'borderColor') => page.evaluate(([variable, prop]) => {
  const probe = document.createElement('span'); probe.style[prop as 'color'] = `var(${variable})`; document.body.append(probe)
  const value = getComputedStyle(probe)[prop as 'color']; probe.remove(); return value
}, [name, property] as const)
// Computed colors may be reported as rgb() or color(srgb ...) depending on how they were produced; compare channels.
const channels = (value: string) => (value.match(/-?\d*\.?\d+/g) || []).slice(0, 3).map(Number).map((n, i, all) => (value.startsWith('color(') ? Math.round(n * 255) : n) + 0 * all.length)
const same = (actual: string, expected: string) => { const a = channels(actual), b = channels(expected); expect(a).toHaveLength(3); a.forEach((n, i) => expect(Math.abs(n - b[i])).toBeLessThanOrEqual(1)) }
const group = (page: Page) => page.locator('.decision-choice')
const button = (page: Page, name: string) => group(page).getByRole('button', { name, exact: true })
// The pointer rests on the control after a click and would show its hover color; move away and let the transition finish first.
const style = async (locator: Locator) => { await locator.page().mouse.move(1, 1); await locator.page().waitForTimeout(300); return read(locator) }
const read = (locator: Locator) => locator.evaluate((element) => { const css = getComputedStyle(element); return { color: css.color, background: css.backgroundColor, border: css.borderTopColor, weight: css.fontWeight, shadow: css.boxShadow } })

async function openBulk(page: Page) {
  await openSod(page, 'Reviews')
  await page.getByRole('tab', { name: 'Bulk Review', exact: true }).click()
  await expect(group(page)).toBeVisible()
}

test('proposed decisions are ordered Investigate, Keep, Remove with neutral unselected and semantic selected states', async ({ page }) => {
  await openBulk(page)
  await expect(group(page).getByRole('button')).toHaveText(['Investigate', 'Keep', 'Remove'])
  const pressed = async () => Promise.all(['Investigate', 'Keep', 'Remove'].map((name) => button(page, name).getAttribute('aria-pressed')))
  // Select each choice in turn; exactly the selected one carries its semantic color, the others stay neutral and identical.
  const expected = { Keep: await token(page, '--success', 'color'), Remove: await token(page, '--error', 'color') }
  const accent = await token(page, '--accent2', 'backgroundColor')
  for (const name of ['Investigate', 'Keep', 'Remove']) {
    await button(page, name).click()
    expect((await pressed()).filter((value) => value === 'true')).toHaveLength(1)
    await expect(button(page, name)).toHaveAttribute('aria-pressed', 'true')
    const selected = await style(button(page, name))
    if (name === 'Investigate') same(selected.background, accent)        // configurable primary theme color
    if (name === 'Keep') { same(selected.color, expected.Keep); same(selected.border, expected.Keep) } // success tokens
    if (name === 'Remove') { same(selected.color, expected.Remove); same(selected.border, expected.Remove) } // danger tokens
    expect(selected.shadow).not.toBe('none')                                        // selection is also marked without color
    const others = await Promise.all(['Investigate', 'Keep', 'Remove'].filter((other) => other !== name).map((other) => style(button(page, other))))
    expect(others[0]).toEqual(others[1])                                            // unselected controls share the neutral styling
    expect(others[0].background).not.toBe(accent); expect(others[0].color).not.toBe(expected.Keep); expect(others[0].color).not.toBe(expected.Remove)
  }
})

test('selected Investigate follows the primary theme and Keep and Remove follow the light and dark tokens', async ({ page, request }) => {
  await openBulk(page)
  await button(page, 'Investigate').click()
  await page.evaluate(() => document.documentElement.style.setProperty('--accent2', 'rgb(200, 30, 120)'))
  same((await style(button(page, 'Investigate'))).background, 'rgb(200, 30, 120)')
  await page.evaluate(() => document.documentElement.style.removeProperty('--accent2'))
  for (const theme of ['dark', 'light']) {
    expect((await request.post('/api/configuration/theme', { headers, data: { theme } })).ok()).toBeTruthy()
    await page.reload(); await openBulk(page)
    await button(page, 'Keep').click()
    same((await style(button(page, 'Keep'))).color, await token(page, '--success', 'color'))
    await button(page, 'Remove').click()
    same((await style(button(page, 'Remove'))).color, await token(page, '--error', 'color'))
  }
})

test('the role assignment row offers Investigate, Keep, Remove in that order and only the chosen one is colored', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await cellButton(page, `${names.a}`, 'R1').click()
  const panel = page.getByRole('dialog', { name: `${names.a} · R1` })
  await panel.getByRole('tab', { name: /^Roles/ }).click()
  await expectReviewerProfile(panel.getByRole('textbox', { name: 'Reviewer (local profile, self-reported)', exact: true }))
  const row = panel.getByRole('group', { name: 'Decision for ROLE_A1', exact: true })
  const labels = await row.getByRole('button').evaluateAll((items) => items.map((item) => item.getAttribute('aria-label')))
  expect(labels).toEqual(['Investigate ROLE_A1', 'Keep ROLE_A1', 'Remove ROLE_A1'])
  const before = await style(row.getByRole('button').nth(0)); const keepBefore = await style(row.getByRole('button').nth(1))
  expect(keepBefore).toEqual(before)                                  // unselected controls are identical (neutral)
  await row.getByRole('button', { name: 'Keep ROLE_A1', exact: true }).click()
  await expect(row.getByRole('button', { name: 'Keep ROLE_A1', exact: true })).toHaveAttribute('aria-pressed', 'true')
  same((await style(row.getByRole('button', { name: 'Keep ROLE_A1', exact: true }))).color, await token(page, '--success', 'color'))
  expect(await style(row.getByRole('button', { name: 'Investigate ROLE_A1', exact: true }))).toEqual(before)
})

test('Bulk Review starts without a decision, needs an explicit choice to confirm and resets for the next operation', async ({ page }) => {
  await openBulk(page)
  const buttons = group(page).getByRole('button')
  await expect(buttons).toHaveText(['Investigate', 'Keep', 'Remove'])
  for (const name of ['Investigate', 'Keep', 'Remove']) await expect(button(page, name)).toHaveAttribute('aria-pressed', 'false')   // nothing preselected
  await expect(page.getByText('No decision selected. Choose Investigate, Keep or Remove to continue.')).toBeVisible()
  await expect(group(page)).toHaveAttribute('aria-describedby', /.+/)                                                              // announced to assistive technology
  await expect(page.getByText(/no decision selected/i).first()).toBeVisible()
  const pageBox = page.getByRole('checkbox', { name: 'Select eligible assignments on current page' })
  await pageBox.check()
  const review = page.getByRole('button', { name: /^Review \d+ assignments$/ })
  await expect(review).toBeDisabled()                                                                                              // no decision, no confirmation
  await expect(page.getByRole('button', { name: 'Preview', exact: true })).toBeDisabled()
  await button(page, 'Investigate').click()
  await expect(button(page, 'Investigate')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('No decision selected. Choose Investigate, Keep or Remove to continue.')).toHaveCount(0)
  await expect(review).toBeEnabled()
  await review.click()
  const dialog = page.getByRole('dialog', { name: 'Mark for further investigation' })
  await expect(dialog).toBeVisible()
  await expectReviewerProfile(dialog.getByRole('textbox', { name: 'Reviewer' }))
  const confirm = dialog.getByRole('button', { name: /^Mark for/ })
  await expect(confirm).toBeDisabled()                                                                                             // rationale validation is unchanged
  await dialog.getByRole('textbox', { name: 'Rationale' }).fill('Needs a second look')
  await confirm.click()
  await expect(dialog.getByRole('region', { name: 'Batch review result' })).toBeVisible()
  await dialog.getByRole('button', { name: 'Done' }).click()
  // The finished operation does not carry its decision into the next one.
  for (const name of ['Investigate', 'Keep', 'Remove']) await expect(button(page, name)).toHaveAttribute('aria-pressed', 'false')
  // Leaving and reopening Bulk Review also starts without a decision.
  await button(page, 'Remove').click()
  await page.getByRole('tab', { name: 'Work queue', exact: true }).click()
  await page.getByRole('tab', { name: 'Bulk Review', exact: true }).click()
  for (const name of ['Investigate', 'Keep', 'Remove']) await expect(button(page, name)).toHaveAttribute('aria-pressed', 'false')
})
