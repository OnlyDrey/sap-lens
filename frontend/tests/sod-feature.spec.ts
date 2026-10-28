import { test, expect } from '@playwright/test'
import { cleanup, enableSod, headers, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const mainNavigation = (page: any) => page.getByRole('navigation', { name: 'Main navigation', exact: true })
const features = async (page: any) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Features', exact: true }).click()
  return page.getByRole('region', { name: 'Segregation of Duties feature settings', exact: true })
}

test('SoD is a manual feature with status, a configure link and preserved data when disabled', async ({ page, request }) => {
  const card = await features(page)
  await expect(card).toContainText('Imported data available')
  await expect(card).toContainText('Operational')
  await card.getByRole('switch', { name: 'Segregation of Duties feature', exact: true }).click()
  await expect(card).toContainText('Pending change')
  await page.getByRole('button', { name: /Apply settings/ }).click()
  await expect.poll(async () => (await (await request.get('/api/configuration', { headers })).json()).settings.features.sod).toBe(false)
  await page.reload()
  await expect(mainNavigation(page).getByRole('link', { name: 'Dashboard', exact: true })).toBeVisible()
  await expect(mainNavigation(page).getByRole('link', { name: 'SoD', exact: true })).toHaveCount(0)
  await expect(await features(page)).toContainText('Disabled in saved settings')
  // Retained matrix and catalogue survive while disabled.
  expect((await (await request.get('/api/sod/catalogue?current=current', { headers })).json()).source.loaded).toBe(true)
  await enableSod(request)
  await page.goto('/#session=browser-test-session')
  await page.reload()
  await expect(mainNavigation(page).getByRole('link', { name: 'SoD', exact: true })).toBeVisible()
})

test('a SoD source never enables the feature and a disabled workspace explains itself', async ({ page, request }) => {
  await enableSod(request, false)
  const card = await features(page)
  await expect(card).toContainText('Disabled in saved settings')
  await card.getByRole('button', { name: 'Configure SoD', exact: true }).click()
  await expect(page.getByRole('tab', { name: 'SoD Matrix', exact: true })).toHaveAttribute('aria-selected', 'true')
  expect((await (await request.get('/api/sod/analysis', { headers })).json()).coverage.reason).toBe('sod_disabled')
})
