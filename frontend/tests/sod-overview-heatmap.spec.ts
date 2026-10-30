import { test, expect } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const heatmap = (page: import('@playwright/test').Page) => page.getByRole('region', { name: 'SAP User Group heatmap', exact: true })

test('Overview uses Dashboard-style sections and a SAP User Group heatmap with distinct users', async ({ page }) => {
  await openSod(page)
  for (const name of ['Conflicts', 'Reviews', 'Remediation']) await expect(page.getByRole('region', { name, exact: true })).toBeVisible()
  const table = heatmap(page).getByRole('table')
  await expect(table.getByRole('row', { name: /^FIN\b/ }).getByRole('button', { name: /1 user in group FIN with R1/ })).toBeVisible()
  await expect(table.getByRole('row', { name: /^P2P\b/ }).getByRole('button', { name: /1 user in group P2P with R1/ })).toBeVisible()
  await expect(table.getByRole('row', { name: /^Distinct users/ })).toContainText('2')
  await heatmap(page).getByRole('button', { name: 'Activities', exact: true }).click()
  await expect(table.getByRole('row', { name: /^FIN\b/ }).getByRole('button', { name: /in group FIN with A\./ })).toBeVisible()
})

test('heatmap sorts groups, drills into the matrix for that group and risk, and exports CSV', async ({ page }) => {
  await openSod(page)
  const region = heatmap(page)
  const names = () => region.locator('tbody th').allInnerTexts()
  await region.getByRole('combobox', { name: 'Sort groups' }).selectOption('name')
  await expect.poll(names).toEqual(['P2P', 'FIN'])
  await region.getByRole('button', { name: /Descending order/ }).click()
  await expect.poll(names).toEqual(['FIN', 'P2P'])
  const download = page.waitForEvent('download')
  await region.getByRole('button', { name: /Export heatmap CSV/ }).click()
  expect((await download).suggestedFilename()).toMatch(/^sap-lens-sod-group-risk-heatmap-\d{4}-\d{2}-\d{2}\.csv$/)
  await region.getByRole('row', { name: /^FIN\b/ }).getByRole('button', { name: /with R2/ }).click()
  await expect(page).toHaveURL(/#\/sod\/risk-matrix/)
  const sidebar = page.getByRole('complementary', { name: 'Filters', exact: true })
  await expect(sidebar.getByRole('button', { name: 'Remove SAP User Group FIN', exact: true })).toBeVisible()
  await expect(sidebar.getByRole('button', { name: 'Remove Risk ID R2', exact: true })).toBeVisible()
})

test('Dashboard summarizes SoD when enabled and opens the matching SoD view', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  const section = page.getByRole('region', { name: 'Segregation of Duties', exact: true })
  await expect(section).toBeVisible()
  // The conflict count lives in the Segregation of Duties card next to findings, pending reviews and remediation; there is no separate key figure row.
  await expect(page.getByRole('region', { name: 'Key figures', exact: true })).toHaveCount(0)
  const key = section.getByRole('button', { name: 'Users with potential conflicts' })
  await expect(key).toContainText('2')
  await expect(section.getByRole('button', { name: 'User-risk findings' })).toBeVisible()
  await key.click()
  await expect(page).toHaveURL(/#\/sod\/risk-matrix/)
})
