import {expectReviewerProfile} from './reviewer-profile'
import { test, expect, type Page } from '@playwright/test'
import { cleanup, names, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

async function open(page: Page, width = 1440) {
  await page.setViewportSize({ width, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('button', { name: `Show evidence for ${names.a} R1` }).click()
  return page.getByRole('dialog', { name: new RegExp(`Role evidence · ${names.a} · R1`) })
}

test('each contributing role has a status and Investigate, Keep and Remove in order on one row', async ({ page }) => {
  const dialog = await open(page)
  await expect(dialog.getByRole('columnheader', { name: 'Role' })).toBeVisible()
  await expect(dialog.getByRole('columnheader', { name: 'Status' })).toBeVisible()
  await expect(dialog.getByRole('columnheader', { name: 'Review actions' })).toBeVisible()
  const first = dialog.locator('tbody tr').first()
  const buttons = first.getByRole('group').getByRole('button')
  await expect(buttons).toHaveCount(3)
  expect(await buttons.allTextContents()).toEqual(['Investigate', 'Keep', 'Remove'])
  const boxes = await Promise.all([0, 1, 2].map(i => buttons.nth(i).boundingBox()))
  expect(new Set(boxes.map(b => Math.round(b!.y))).size).toBe(1)
  expect(new Set(boxes.map(b => Math.round(b!.height))).size).toBe(1)
  expect(boxes[0]!.x).toBeLessThan(boxes[1]!.x); expect(boxes[1]!.x).toBeLessThan(boxes[2]!.x)
  // the modal itself never overflows horizontally
  expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
})

test('Keep, Remove and Investigate persist per role assignment, survive reopening and refresh the review panel', async ({ page }) => {
  const dialog = await open(page)
  const rowA = dialog.locator('tbody tr').first()
  const roleName = (await rowA.locator('td').first().innerText()).split('\n')[0].trim()
  await expectReviewerProfile(dialog.getByLabel('Reviewer (local profile, self-reported)'))
  await rowA.getByRole('button', { name: `Keep ${roleName}` }).click()
  await expect(rowA.getByRole('button', { name: `Keep ${roleName}` })).toHaveAttribute('aria-pressed', 'true')
  await expect(rowA.getByRole('button', { name: `Remove ${roleName}` })).toHaveAttribute('aria-pressed', 'false')
  // a different role of the same user is untouched
  const others = dialog.locator('tbody tr').filter({ hasNot: page.getByRole('button', { name: `Keep ${roleName}` }) })
  if (await others.count()) await expect(others.first().getByRole('button', { pressed: true })).toHaveCount(0)
  // change the decision: Remove is a recommendation only
  await rowA.getByRole('button', { name: `Remove ${roleName}` }).click()
  await expect(rowA.getByRole('button', { name: `Remove ${roleName}` })).toHaveAttribute('aria-pressed', 'true')
  await rowA.getByRole('button', { name: `Investigate ${roleName}` }).click()
  await expect(rowA.getByRole('button', { name: `Investigate ${roleName}` })).toHaveAttribute('aria-pressed', 'true')
  // persistence after reopening
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: `Show evidence for ${names.a} R1` }).click()
  const again = page.getByRole('dialog', { name: /Role evidence/ })
  await expect(again.getByRole('button', { name: `Investigate ${roleName}` }).first()).toHaveAttribute('aria-pressed', 'true')
  // the same decision is visible in Role Assignment Review
  await again.getByRole('button', { name: 'Investigate', exact: true }).click()
  await expect(page.getByRole('button', { name: `Investigate ${roleName}` }).last()).toHaveAttribute('aria-pressed', 'true')
})

test('a stable reviewer is supplied, a failed save is reported and nothing is marked saved', async ({ page }) => {
  const dialog = await open(page)
  const rowA = dialog.locator('tbody tr').first()
  const roleName = (await rowA.locator('td').first().innerText()).split('\n')[0].trim()
  await expect(rowA.getByRole('button', { name: `Keep ${roleName}` })).toHaveAttribute('aria-pressed', 'false')
  await expectReviewerProfile(dialog.getByLabel('Reviewer (local profile, self-reported)'))
  await page.route('**/api/sod/decisions/assignment', route => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic save failure' }) }))
  await rowA.getByRole('button', { name: `Keep ${roleName}` }).click()
  await expect(dialog.getByRole('alert')).toContainText('was not saved')
  await expect(rowA.getByRole('button', { name: `Keep ${roleName}` })).toHaveAttribute('aria-pressed', 'false')
})

test('the table stays usable on a narrow screen', async ({ page }) => {
  const dialog = await open(page, 375)
  const scroll = dialog.getByRole('region', { name: 'Roles supplying this evidence', exact: true })
  await expect(scroll).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(dialog.locator('tbody tr').first().getByRole('button', { name: /^Keep / })).toBeAttached()
})

test('Export evidence CSV carries a leading file-down icon and matches the neighbouring export button', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Access Explorer')
  const evidence = page.getByRole('button', { name: 'Export evidence CSV', exact: true })
  await expect(evidence.locator('svg.lucide-file-down')).toHaveCount(1)
  expect(await evidence.evaluate(el => el.firstElementChild?.tagName.toLowerCase())).toBe('svg') // icon before the label
  const neighbour = page.getByRole('button', { name: 'Export CSV', exact: true })
  const [a, b] = [await evidence.boundingBox(), await neighbour.boundingBox()]
  expect(Math.round(a!.height)).toBe(Math.round(b!.height))
})
