import { test, expect } from '@playwright/test'
import { cleanup, names, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

test('Access Explorer user evidence opens in a wide modal with a compact summary, a scrollable table and shortcuts', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('button', { name: `Show evidence for ${names.a} R1` }).click()
  const dialog = page.getByRole('dialog', { name: new RegExp(`Role evidence · ${names.a} · R1`) })
  await expect(dialog).toBeVisible()
  expect((await dialog.boundingBox())!.width).toBeGreaterThanOrEqual(720)
  const summary = dialog.locator('.evidence-summary')
  for (const term of ['SAP user', 'Risk', 'Activities', 'Roles']) await expect(summary.getByText(term, { exact: true })).toBeVisible()
  const scroll = dialog.getByRole('region', { name: 'Roles supplying this evidence', exact: true })
  expect(await scroll.evaluate(el => getComputedStyle(el).overflowY)).toBe('auto')
  await expect(scroll.getByRole('table')).toContainText('ROLE_A1')
  await expect(dialog.getByRole('button', { name: 'Open SAP user' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: `Show evidence for ${names.a} R1` }).click()
  await page.getByRole('dialog', { name: /Role evidence/ }).getByRole('button', { name: 'Investigate', exact: true }).click()
  await expect(page.getByRole('dialog', { name: new RegExp(`${names.a} · R1`), exact: false }).first()).toBeVisible() // the investigation panel for the same pair
})

test('the Roles lookup shows the users behind a role in a wide modal with intervals and an investigate action', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('tab', { name: 'Roles', exact: true }).click()
  await page.getByRole('button', { name: 'Show evidence for ROLE_AB' }).click()
  const dialog = page.getByRole('dialog', { name: 'Users with ROLE_AB' })
  await expect(dialog).toBeVisible()
  expect((await dialog.boundingBox())!.width).toBeGreaterThanOrEqual(720)
  const table = dialog.getByRole('table', { name: 'Users with ROLE_AB' })
  await expect(table).toContainText(names.b)
  await expect(dialog.getByRole('columnheader', { name: 'SAP User Group' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: `Open SAP user ${names.b}` })).toBeVisible()
  await dialog.getByRole('button', { name: `Investigate ${names.b}` }).click()
  await expect(dialog).toHaveCount(0)
})

test('the Potential SoD evidence modal separates transactions, single roles, assigned roles, catalogue roles, validity and provenance for both activities', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('tab', { name: 'Role conflicts', exact: true }).click()
  await page.getByRole('button', { name: /^Inspect SoD evidence / }).first().click()
  const dialog = page.getByRole('dialog', { name: /^Potential SoD evidence · / })
  await expect(dialog).toBeVisible()
  const summary = dialog.getByLabel('Finding summary')
  for (const term of ['Risk', 'Activities (both required)']) await expect(summary.getByText(term, { exact: true })).toBeVisible()
  await expect(dialog).toContainText('do not establish effective SAP authorization')
  for (const side of ['ACTVT1', 'ACTVT2']) {
    const section = dialog.getByRole('region', { name: `${side} evidence` })
    await expect(section).toBeVisible()
    await expect(section.getByRole('columnheader')).toHaveText(['Transaction', 'Single role', 'Assigned role', 'Catalogue role or pattern', 'Assignment validity', 'Technical provenance'])
    await expect(section.getByRole('region', { name: `${side} supporting evidence table` })).toBeVisible()
  }
  await expect(dialog.getByText('Technical provenance').first()).toBeVisible()
})

test('Risk Acceptance rows put checkbox, Risk ID, status and a right-aligned Decide on one line, with the description and history below', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Risk Matrix')
  await page.getByRole('button', { name: new RegExp(`^${names.a}, risk R1:`) }).click()
  const panel = page.getByRole('dialog', { name: new RegExp(`${names.a} · R1`) })
  const row = panel.locator('.sod-review-row').filter({ has: page.getByRole('button', { name: /^Decide risk acceptance / }) }).first()
  await expect(row).toBeVisible()
  const [box, decide, check, status] = [await row.locator('.sod-review-compact').boundingBox(), await row.getByRole('button', { name: /^Decide risk acceptance / }).boundingBox(), await row.getByRole('checkbox').boundingBox(), await row.locator('.sod-review-compact .evidence-badge').first().boundingBox()]
  expect(Math.abs((decide!.y + decide!.height / 2) - (check!.y + check!.height / 2))).toBeLessThan(20) // one primary line
  expect(decide!.x + decide!.width).toBeGreaterThan(box!.x + box!.width - 80) // actions at the right edge
  expect(status!.x).toBeLessThan(decide!.x) // status before the decision action
  const description = row.locator('.sod-review-description')
  await expect(description).toBeVisible()
  expect((await description.boundingBox())!.y).toBeGreaterThan(box!.y + box!.height - 2) // description below the primary row
  const toggle = row.getByRole('button', { name: /^Show details for / })
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(row.getByRole('group', { name: /^Evidence for / })).toHaveCount(0) // history stays collapsed
  await toggle.click()
  await expect(row.getByRole('group', { name: /^Evidence for / })).toBeVisible()
})
