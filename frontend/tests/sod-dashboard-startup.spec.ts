import { test, expect, type Page } from '@playwright/test'
import { seedGovernance, cleanup, openSod, enableSod } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const dashboard = (page: Page) => page.getByRole('region', { name: 'Dashboard', exact: true })
const sodCard = (page: Page) => dashboard(page).getByRole('region', { name: 'Segregation of Duties', exact: true })
type Phase = { loading: boolean; sod: 'real' | 'unavailable' | 'failed' | 'missing-matrix' | 'missing-catalogue'; failures?: number }
/** The backend answers SoD requests with "unavailable" while persisted data is restored; the Dashboard must neither give a verdict then nor depend on a SoD page visit later. */
const model = async (page: Page, phase: Phase) => {
  await page.route('**/api/configuration', async route => {
    if (route.request().method() !== 'GET') return route.continue()
    const response = await route.fetch(), json = await response.json()
    await route.fulfill({ response, json: { ...json, loading: phase.loading } })
  })
  await page.route('**/api/sod/overview', async route => {
    if (phase.sod === 'failed' && (phase.failures ?? 1) > 0) { phase.failures = (phase.failures ?? 1) - 1; return route.fulfill({ status: 500, json: { detail: 'SoD analysis failed.' } }) }
    const response = await route.fetch(), json = await response.json()
    if (phase.sod === 'unavailable') json.governance = { available: false, reason: 'required_source_unavailable', missing: ['roles', 'users', 'sod'] }
    if (phase.sod === 'missing-matrix') json.governance = { available: false, reason: 'required_source_unavailable', missing: ['sod'] }
    if (phase.sod === 'missing-catalogue') json.governance = { available: false, reason: 'required_source_unavailable', missing: ['roles'] }
    await route.fulfill({ response, json })
  })
}

test('Dashboard shows SoD metrics automatically after startup without visiting a SoD page, and keeps them after a SoD visit', async ({ page }) => {
  const phase: Phase = { loading: true, sod: 'unavailable' }
  await model(page, phase)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await expect(dashboard(page)).toBeVisible()
  await expect(sodCard(page)).toContainText('Preparing SoD analysis') // loading: a temporary state, not a missing-data verdict
  await expect(sodCard(page).getByText(/SoD analysis is not available/)).toHaveCount(0)
  Object.assign(phase, { loading: false, sod: 'real' })
  const users = sodCard(page).getByRole('button', { name: 'Users with potential conflicts' })
  await expect(users).toBeVisible({ timeout: 10_000 })
  await expect(sodCard(page).getByRole('button', { name: 'User-risk findings' })).toBeVisible()
  const values = await sodCard(page).locator('.info-row-value').allInnerTexts()
  expect(values.length).toBe(5)
  await openSod(page)
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Dashboard', exact: true }).click()
  await expect(sodCard(page).locator('.info-row-value')).toHaveText(values) // the same values after a SoD visit
  await page.reload()
  await expect(sodCard(page).locator('.info-row-value')).toHaveText(values) // and after another start
})

test('an unavailable analysis names the missing input and offers a real button to the right source', async ({ page }) => {
  const phase: Phase = { loading: false, sod: 'missing-matrix' }
  await model(page, phase)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await expect(sodCard(page)).toContainText('SoD analysis is not available. The SoD matrix is not loaded.')
  const button = sodCard(page).getByRole('button', { name: 'Open SoD source' })
  await expect(button).toBeVisible()
  await expect(button).toHaveClass(/ui-button/) // the shared button, not inline text
  await expect(button.locator('svg')).toHaveCount(1)
  const box = await button.boundingBox(), text = await sodCard(page).getByText(/SoD analysis is not available/).boundingBox()
  expect(box!.height).toBeGreaterThanOrEqual(28); expect(box!.y - (text!.y + text!.height)).toBeGreaterThanOrEqual(8)
  expect(await button.evaluate(el => parseFloat(getComputedStyle(el).borderTopWidth))).toBeGreaterThanOrEqual(1) // visible boundary
  await button.focus(); await expect(button).toBeFocused()
  expect(await button.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe('none')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('tab', { name: /SoD/ }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
  Object.assign(phase, { sod: 'missing-catalogue' })
  await page.reload()
  await expect(sodCard(page)).toContainText('The Role Catalogue is not loaded.')
  await expect(sodCard(page).getByRole('button', { name: 'Open Role Catalogue source' })).toBeVisible()
})

test('a failed SoD request is reported as failed and can be retried; a SoD page visit is not required', async ({ page }) => {
  const phase: Phase = { loading: false, sod: 'failed', failures: 1000 }
  await model(page, phase)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await expect(sodCard(page).getByRole('alert')).toContainText('SoD analysis could not be loaded.', { timeout: 15_000 })
  Object.assign(phase, { failures: 0 })
  await sodCard(page).getByRole('button', { name: 'Try again' }).click()
  await expect(sodCard(page).getByRole('button', { name: 'Users with potential conflicts' })).toBeVisible()
})

test('the card is absent while SoD is disabled and appears when it is enabled', async ({ page, request }) => {
  await enableSod(request, false)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await expect(dashboard(page).getByRole('region', { name: 'Access & Risk', exact: true })).toBeVisible()
  await expect(sodCard(page)).toHaveCount(0)
  await enableSod(request, true)
  await page.reload()
  await expect(sodCard(page).getByRole('button', { name: 'Users with potential conflicts' })).toBeVisible()
})
