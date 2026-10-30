import { test, expect } from '@playwright/test'
import { cellButton, cleanup, longRoleName, names, openSod, seedGovernance } from './sod-fixture'
import { pickMulti } from './support'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static', undefined, true) })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

test('a plain-text server failure shows an application error with Retry, never a JSON parser message', async ({ page }) => {
  let failing = true
  await page.route('**/api/sod/matrix/risk**', (route) => failing
    ? route.fulfill({ status: 500, contentType: 'text/plain', body: 'Internal Server Error' })
    : route.continue())
  await openSod(page, 'Risk Matrix')
  const alert = page.getByRole('alert').filter({ hasText: 'could not be loaded' })
  await expect(alert).toBeVisible({ timeout: 15000 })
  await expect(alert).toContainText('server error 500')
  await expect(alert).not.toContainText(/Unexpected token|not valid JSON/)
  failing = false
  await alert.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(cellButton(page, names.a, 'R1')).toBeVisible()
})

test('a non-JSON success response and a lost connection are explained distinctly', async ({ page }) => {
  await page.route('**/api/sod/explorer/user_risk**', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html>proxy page</html>' }))
  await openSod(page, 'Access Explorer')
  await expect(page.getByRole('alert').filter({ hasText: 'unexpected response' })).toBeVisible({ timeout: 15000 })
  await page.unroute('**/api/sod/explorer/user_risk**')
  await page.route('**/api/sod/explorer/user_activity**', (route) => route.abort('failed'))
  await page.getByRole('combobox', { name: 'Group users by', exact: true }).selectOption('user_activity')
  await expect(page.getByRole('alert').filter({ hasText: 'could not connect' })).toBeVisible({ timeout: 15000 })
})

test('client errors fail fast with the server explanation', async ({ page }) => {
  await page.route('**/api/sod/matrix/activity**', (route) => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'SoD evidence changed. Reload.' }) }))
  const started = Date.now()
  await openSod(page, 'Activity Matrix')
  await expect(page.getByRole('alert')).toContainText('SoD evidence changed. Reload.')
  expect(Date.now() - started).toBeLessThan(6000)
})

test('opening a role from the investigation panel shows one panel; Back and close restore the investigation', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await cellButton(page, names.a, 'R1').click()
  const panel = page.getByRole('dialog', { name: `${names.a} · R1` })
  await expect(panel).toBeVisible()
  await panel.getByRole('button', { name: 'Open catalogue role ROLE_A1', exact: true }).click()
  const role = page.getByRole('dialog', { name: 'Role details: ROLE_A1', exact: true })
  await expect(role).toBeVisible()
  await expect(panel).toHaveCount(0)
  await page.goBack()
  await expect(role).toHaveCount(0)
  await expect(panel).toBeVisible()
  await panel.getByRole('button', { name: 'Open catalogue role ROLE_A1', exact: true }).click()
  await expect(role).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(role).toHaveCount(0)
  await expect(panel).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(panel).toHaveCount(0)
  await expect(page).toHaveURL(/#\/sod\/risk-matrix/)
})

test('opening a user from the panel and returning keeps the investigation and filters', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await pickMulti(page, 'SAP User Group', 'FIN')
  await cellButton(page, names.a, 'R1').click()
  await page.getByRole('dialog', { name: `${names.a} · R1` }).getByRole('link', { name: `Open SAP user ${names.a}`, exact: true }).click()
  await expect(page.getByRole('heading', { name: 'SAP Identity', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('dialog', { name: `${names.a} · R1` })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Remove SAP User Group FIN', exact: true })).toBeVisible()
})

for (const width of [375, 800]) test(`long roles never widen the page or break table actions at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  const noOverflow = () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
  await openSod(page, 'Access Explorer')
  expect(await noOverflow()).toBeTruthy()
  await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
  await expect(page.getByRole('table', { name: 'Access list' })).toContainText(longRoleName)
  expect(await noOverflow()).toBeTruthy()
  const user = page.getByRole('cell', { name: new RegExp(`^${names.a}`) }).first()
  // The user name itself stays on one line (rows may be taller for validity text).
  expect(await user.evaluate((cell) => { const range = document.createRange(); range.selectNodeContents(cell.firstChild!); return range.getBoundingClientRect().height })).toBeLessThan(40)
  await page.getByRole('tab', { name: 'Roles', exact: true }).click()
  expect(await noOverflow()).toBeTruthy()
  await openSod(page, 'Reviews')
  expect(await noOverflow()).toBeTruthy()
  const open = page.getByRole('button', { name: /^Open / }).first()
  expect((await open.boundingBox())!.height).toBeLessThan(56)
  await page.getByRole('tab', { name: 'Remediation', exact: true }).click()
  expect(await noOverflow()).toBeTruthy()
  await openSod(page, 'Risk Matrix')
  await cellButton(page, names.c, 'R1').click()
  const panel = page.getByRole('dialog', { name: `${names.c} · R1` })
  await expect(panel.getByText(longRoleName.slice(0, 30), { exact: false }).first()).toBeVisible()
  expect(await noOverflow()).toBeTruthy()
  const box = await panel.getByRole('listitem').filter({ hasText: 'VERY_LONG' }).first().boundingBox()
  expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
})
