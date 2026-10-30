import { test, expect, type Page } from '@playwright/test'
import { goTo, seedSources, type SeededSources } from './support'

const roles = `FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:BUY:ENP,Buyer plant,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
FI,ZC:FI:VIEW:ENP,Finance view,ZS:SH,MM - Shared purchasing,MIGO,Goods movement
`
const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
U1,ZC:MM:BUY:ENP,G1,20200101,99991231
U2,ZC:FI:VIEW:ENP,G1,20200101,99991231
`
let seeded: SeededSources
test.afterEach(async () => { await seeded.cleanup() })

const STABLE_REVISION = '2026-01-01T00:00:00+00:00'
type Server = { loading: boolean; instance: string; emptyDashboard: boolean; rolesOverride?: number }
/** Models what a client sees around a backend restart: the restored snapshot keeps its revision timestamp, so only the loading phase and the instance id differ. */
const model = async (page: Page, server: Server) => {
  await page.route('**/api/configuration', async route => {
    if (route.request().method() !== 'GET') return route.continue()
    const response = await route.fetch(), json = await response.json()
    await route.fulfill({ response, json: { ...json, loading: server.loading, data_revision: STABLE_REVISION, instance_id: server.instance } })
  })
  await page.route('**/api/dashboard', async route => {
    const response = await route.fetch(), json = await response.json()
    if (server.emptyDashboard) {
      json.metrics = json.metrics.map((metric: { value: number | null }) => ({ ...metric, value: null, unavailable_reason: 'Source not loaded' }))
      json.review_population = json.role_distribution = json.assignment_distribution = null
    } else if (server.rolesOverride !== undefined) {
      json.metrics.find((metric: { id: string }) => metric.id === 'roles').value = server.rolesOverride
    }
    await route.fulfill({ response, json })
  })
}
const rolesRow = (page: Page) => page.getByRole('region', { name: 'Dashboard', exact: true }).locator('[data-metric="roles"]')

test('a load that finishes with the same revision still refreshes views read while it ran', async ({ page, request }) => {
  seeded = await seedSources(request, { roles, users })
  const server: Server = { loading: true, instance: 'A', emptyDashboard: true }
  await model(page, server)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await expect(page.getByRole('region', { name: 'Dashboard', exact: true })).toBeVisible()
  await expect(rolesRow(page)).toContainText('Loading') // loading: no permanent "missing" verdict for sources still being restored
  await expect(rolesRow(page)).not.toContainText('Unavailable')
  Object.assign(server, { loading: false, emptyDashboard: false }) // the backend finishes restoring; the revision timestamp is unchanged
  await expect(rolesRow(page)).toContainText('2', { timeout: 10_000 }) // no manual refresh, no navigation
})

test('a long-lived tab re-reads dataset views after the backend process restarts', async ({ page, request }) => {
  seeded = await seedSources(request, { roles, users })
  const server: Server = { loading: false, instance: 'A', emptyDashboard: false }
  await model(page, server)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await expect(rolesRow(page)).toContainText('2')
  Object.assign(server, { instance: 'B', rolesOverride: 7 }) // new process, restored snapshot with the same revision timestamp
  await expect(rolesRow(page)).toContainText('7', { timeout: 10_000 })
})

test('Settings source status and the Dashboard agree after startup, and a genuinely missing source is reported as such', async ({ page, request }) => {
  seeded = await seedSources(request, { roles }) // no User Access file: genuinely missing
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  const dashboard = page.getByRole('region', { name: 'Dashboard', exact: true })
  await expect(rolesRow(page)).toContainText('2')
  await expect(dashboard.locator('[data-metric="users"], [aria-label="SAP users"]').first()).toContainText('Unavailable')
  await expect(dashboard.getByText('Loaded', { exact: true }).first()).toBeVisible() // the catalogue is really loaded
  await expect(dashboard.getByText('Not loaded', { exact: true }).first()).toBeVisible() // the mapping is not
  await goTo(page, 'Role Lookup')
  await expect(page.getByRole('article')).toHaveCount(2)
})

test('refresh after startup keeps working and views stay ready', async ({ page, request }) => {
  seeded = await seedSources(request, { roles, users })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await expect(rolesRow(page)).toContainText('2')
  await page.getByRole('button', { name: /^Refresh/ }).first().click()
  await expect(rolesRow(page)).toContainText('2')
  await expect(page.getByRole('button', { name: /^Refresh/ }).first()).toBeEnabled()
})
