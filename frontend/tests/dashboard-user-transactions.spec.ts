import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
let directory: string
const roles =
  'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:MM:A,Demo purchasing,ZS:A,MIGO\nFI,ZC:FI:B,Demo finance,ZS:B,ME21N\nSD,ZC:SD:C,Demo sales,ZS:C,VA03\n'
const users =
  'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_ONE,ZC:MM:A,G1,20200101,99991231\nDEMO_ONE,ZC:FI:B,G1,20200101,99991231\nDEMO_TWO,ZC:MM:A,G2,20200101,99991231\nDEMO_THREE,ZC:SD:C,G2,20200101,99991231\n'
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-dashboard-'))
  const rolePath = path.join(directory, 'roles.csv'),
    userPath = path.join(directory, 'users.csv')
  writeFileSync(rolePath, roles)
  writeFileSync(userPath, users)
  const settings = (
    await (await request.get('/api/configuration', { headers })).json()
  ).settings
  settings.data_csv_path = rolePath
  settings.user_csv_path = userPath
  expect(
    (
      await request.post('/api/configuration', { headers, data: settings })
    ).ok(),
  ).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})
async function go(page: Page, name: string) {
  await page.goto('/#session=browser-test-session')
  await nav(page, name)
}
async function nav(page: Page, name: string) {
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name, exact: true })
    .click()
}

test('editable user T-codes use AND across assignments, OR, unique chips and scoped clear', async ({
  page,
}) => {
  await go(page, 'User Access')
  const input = page.getByRole('textbox', {
    name: 'Filter users by transaction',
    exact: true,
  })
  await input.fill('migo')
  await expect(
    page.getByRole('button', { name: 'DEMO_TWO', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'DEMO_THREE', exact: true }),
  ).toHaveCount(0)
  await input.press('Enter')
  await input.fill(' me21n ')
  await input.press('Enter')
  await expect(
    page.getByRole('button', { name: 'AND', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(
    page.getByRole('button', { name: 'DEMO_TWO', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
  ).toBeVisible()
  await input.fill('MIGO')
  await input.press('Enter')
  await expect(
    page.getByRole('button', { name: 'Remove transaction MIGO', exact: true }),
  ).toHaveCount(1)
  await page.getByRole('button', { name: 'OR', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'DEMO_TWO', exact: true }),
  ).toBeVisible()
  const search = page.getByRole('textbox', {
    name: 'Search users',
    exact: true,
  })
  await search.fill('TWO')
  await page
    .getByRole('combobox', { name: 'Sort users', exact: true })
    .selectOption('email')
  const summary = page.getByRole('region', {
    name: 'Active evidence filter',
    exact: true,
  })
  await expect(summary).toContainText('Transaction: MIGO')
  await expect(summary).toContainText('Transaction: ME21N')
  await summary
    .getByRole('button', { name: 'Clear filter', exact: true })
    .click()
  await expect(summary).toHaveCount(0)
  await expect(input).toHaveValue('')
  await expect(search).toHaveValue('TWO')
  await expect(
    page.getByRole('combobox', { name: 'Sort users', exact: true }),
  ).toHaveValue('email')
  await expect(
    page.getByRole('button', { name: 'DEMO_TWO', exact: true }),
  ).toBeVisible()
})

test('incoming transaction evidence seeds the same editable controls and survives detail Back', async ({
  page,
}) => {
  await go(page, 'Role Lookup')
  await page
    .getByRole('button', {
      name: 'View details for Demo purchasing',
      exact: true,
    })
    .click()
  await page
    .getByRole('button', { name: 'Expand single role ZS:A', exact: true })
    .click()
  await page
    .getByRole('button', { name: 'Investigate users with MIGO', exact: true })
    .click()
  const summary = page.getByRole('region', {
    name: 'Active evidence filter',
    exact: true,
  })
  await expect(summary).toContainText('Transaction: MIGO')
  const input = summary.getByRole('textbox', {
    name: 'Filter users by transaction',
    exact: true,
  })
  await input.fill('ME21N')
  await input.press('Enter')
  await expect(
    page.getByRole('button', { name: 'DEMO_TWO', exact: true }),
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'DEMO_ONE', exact: true }).click()
  await page.getByRole('button', { name: 'Back to users', exact: true }).click()
  await expect(
    summary.getByRole('button', {
      name: 'Remove transaction ME21N',
      exact: true,
    }),
  ).toBeVisible()
})

test('Dashboard counts and KPI routes are meaningful, with browser Back and disabled-source states', async ({
  page,
  request,
}) => {
  await go(page, 'Dashboard')
  const dashboard = page.getByRole('region', { name: 'Dashboard', exact: true })
  await expect(
    dashboard.getByRole('button', { name: 'Catalogue roles', exact: true }),
  ).toContainText('3')
  await expect(
    dashboard.getByRole('button', {
      name: 'Role assignment records',
      exact: true,
    }),
  ).toContainText('4')
  await expect(
    dashboard.getByRole('button', {
      name: 'Employee Directory records',
      exact: true,
    }),
  ).toContainText('Unavailable')
  await dashboard
    .getByRole('button', { name: 'SAP users', exact: true })
    .click()
  await expect(
    page.getByRole('region', { name: 'User Access', exact: true }),
  ).toBeVisible()
  await page.goBack()
  await expect(dashboard).toBeVisible()
  await page.goForward()
  await expect(
    page.getByRole('region', { name: 'User Access', exact: true }),
  ).toBeVisible()
  await nav(page, 'Role Lookup')
  await expect(
    page.getByRole('button', { name: 'Catalogue roles', exact: true }),
  ).toHaveCount(0)
  const current = (
    await (await request.get('/api/configuration', { headers })).json()
  ).settings
  current.features.user_role_mapping = false
  expect(
    (await request.post('/api/configuration', { headers, data: current })).ok(),
  ).toBeTruthy()
  await page.goto('/#/dashboard')
  await page.reload()
  await expect(dashboard).toBeVisible()
  await expect(
    dashboard.getByRole('button', { name: 'SAP users', exact: true }),
  ).toContainText('User–Role Mapping disabled')
  await expect(
    dashboard.getByRole('button', { name: 'Catalogue roles', exact: true }),
  ).toContainText('3')
  await dashboard
    .getByRole('button', { name: 'Employee Directory records', exact: true })
    .click()
  await expect(
    page.getByRole('tab', { name: 'Employee Directory', exact: true }),
  ).toHaveAttribute('aria-selected', 'true')
})

for (const theme of ['light', 'dark'] as const)
  for (const width of [375, 800, 1280])
    test(`Dashboard and compact search visual QA ${theme} ${width}`, async ({
      page,
      request,
    }, info) => {
      const settings = (
        await (await request.get('/api/configuration', { headers })).json()
      ).settings
      settings.theme = theme
      expect(
        (
          await request.post('/api/configuration', { headers, data: settings })
        ).ok(),
      ).toBeTruthy()
      await page.setViewportSize({ width, height: 1000 })
      await go(page, 'Dashboard')
      await expect(
        page.getByRole('button', { name: 'Catalogue roles', exact: true }),
      ).toContainText('3')
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true)
      await page.screenshot({
        path: info.outputPath('dashboard.png'),
        fullPage: true,
      })
      await nav(page, 'Role Lookup')
      const name = page.getByPlaceholder(
          'Search roles by name or description...',
        ),
        tcode = page.getByRole('textbox', {
          name: 'Filter catalogue by transaction',
          exact: true,
        })
      const a = (await name.boundingBox())!,
        b = (await tcode.boundingBox())!
      expect(Math.abs(a.height - b.height)).toBeLessThanOrEqual(2)
      if (width > 800) {
        expect(Math.abs(a.y - b.y)).toBeLessThanOrEqual(2)
        expect(a.width).toBeGreaterThan(b.width)
      } else expect(b.y).toBeGreaterThan(a.y)
      await tcode.fill('MIGO')
      await tcode.press('Enter')
      await tcode.fill('ME21N')
      await tcode.press('Enter')
      await expect(
        page.getByRole('button', { name: 'AND', exact: true }),
      ).toHaveAttribute('aria-pressed', 'true')
      await expect(page.getByRole('article')).toHaveCount(0)
      await page.getByRole('button', { name: 'OR', exact: true }).click()
      await expect(page.getByRole('article')).toHaveCount(2)
      await page.screenshot({
        path: info.outputPath('compact-search.png'),
        fullPage: true,
      })
    })

test('shared success and error notifications align with content and dismiss by keyboard', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1000 })
  await go(page, 'Role Lookup')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page
    .getByRole('tab', { name: 'System & Organization', exact: true })
    .click()
  await page.getByLabel('Organization name', { exact: true }).fill('Example QA')
  await page
    .getByRole('button', { name: 'Apply settings', exact: true })
    .click()
  const notice = page.locator('.notification-success')
  await expect(notice).toContainText('Settings saved successfully.')
  const content = (await notice
      .locator('.notification-content')
      .boundingBox())!,
    main = (await page.locator('main').boundingBox())!
  expect(content.x).toBe(main.x)
  expect(content.width).toBe(main.width)
  const close = notice.getByRole('button', {
    name: 'Dismiss notification',
    exact: true,
  })
  await expect(close.locator('.lucide-x')).toBeVisible()
  await close.focus()
  await close.press('Enter')
  await expect(notice).toHaveCount(0)
  await page.route('**/api/refresh', (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Synthetic refresh failure' }),
    }),
  )
  await page
    .getByRole('button', { name: 'Refresh role data from CSV', exact: true })
    .click()
  const error = page.locator('.notification-error')
  await expect(error).toContainText('Synthetic refresh failure')
  await error
    .getByRole('button', { name: 'Dismiss notification', exact: true })
    .click()
  await expect(error).toHaveCount(0)
})

test('KPI navigation resets only its destination filters', async ({ page }) => {
  await go(page, 'User Access')
  const search = page.getByRole('textbox', {
    name: 'Search users',
    exact: true,
  })
  await search.fill('TWO')
  await expect(
    page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
  ).toHaveCount(0)
  await nav(page, 'Role Lookup')
  const roleSearch = page.getByPlaceholder(
    'Search roles by name or description...',
  )
  await roleSearch.fill('finance')
  await expect(page.getByRole('article')).toHaveCount(1)
  await nav(page, 'Dashboard')
  await page.getByRole('button', { name: 'SAP users', exact: true }).click()
  await expect(search).toHaveValue('')
  await expect(
    page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
  ).toBeVisible()
  await nav(page, 'Role Lookup')
  await expect(roleSearch).toHaveValue('finance')
  await nav(page, 'Dashboard')
  await page
    .getByRole('button', { name: 'Catalogue roles', exact: true })
    .click()
  await expect(roleSearch).toHaveValue('')
  await expect(page.getByRole('article')).toHaveCount(3)
})
