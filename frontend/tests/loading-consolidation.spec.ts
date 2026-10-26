import { directoryDisplayName } from '../src/lib/directoryDisplayName'
import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
let directory: string, roles: string, users: string
const roleCSV =
  'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:DEMO:A,Demo purchasing,ZS:A,MIGO\n'
const userCSV =
  'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_ONE,ZC:DEMO:A,G1,Demo,One,one@example.test,20200101,99991231,20200101,99991231\n'
async function nav(page: Page, name: string) {
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name, exact: true })
    .click()
}
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-loading-'))
  roles = path.join(directory, 'roles.csv')
  users = path.join(directory, 'users.csv')
  writeFileSync(roles, roleCSV)
  writeFileSync(users, userCSV)
  const settings = (
    await (await request.get('/api/configuration', { headers })).json()
  ).settings
  settings.data_csv_path = roles
  settings.user_csv_path = users
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

test('startup load completion refreshes every route cache without revisiting Settings', async ({
  page,
  request,
}) => {
  let loading = true
  await page.route('**/api/configuration', async (route) => {
    const response = await route.fetch(),
      json = await response.json()
    await route.fulfill({
      response,
      json: {
        ...json,
        loading,
        data_revision: loading ? 'empty' : 'complete',
        analysis: {},
      },
    })
  })
  await page.route('**/api/dashboard', async (route) => {
    const response = await route.fetch(),
      json = await response.json()
    await route.fulfill({
      response,
      json: loading
        ? {
            ...json,
            metrics: json.metrics.map((m: { value: number | null }) => ({
              ...m,
              value: null,
            })),
          }
        : json,
    })
  })
  await page.goto('/#session=browser-test-session')
  await nav(page, 'Dashboard')
  await expect(
    page.getByRole('button', { name: 'Catalogue roles', exact: true }),
  ).toBeVisible()
  await nav(page, 'User Access')
  await expect(
    page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
  ).toBeVisible()
  loading = false
  // Config polling observes completion, but the baseline only invalidates roles/modules.
  await expect
    .poll(
      async () => {
        await nav(page, 'Dashboard')
        return page
          .getByRole('button', { name: 'Catalogue roles', exact: true })
          .innerText()
      },
      { timeout: 12000 },
    )
    .toContain('1')
})

test('navigation during refresh cancels a late old route response and updates all pages', async ({
  page,
  request,
}) => {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'Dashboard')
  await expect(
    page.getByRole('button', { name: 'SAP users', exact: true }),
  ).toContainText('1')
  let releaseRefresh!: () => void, releaseOld!: () => void
  const refreshGate = new Promise<void>((resolve) => {
      releaseRefresh = resolve
    }),
    oldGate = new Promise<void>((resolve) => {
      releaseOld = resolve
    })
  let refreshStarted = false,
    oldCaptured = false
  await page.route('**/api/refresh', async (route) => {
    refreshStarted = true
    await refreshGate
    await route.continue()
  })
  await page.route('**/api/access/users?**', async (route) => {
    if (oldCaptured) {
      await route.continue()
      return
    }
    oldCaptured = true
    const response = await route.fetch()
    await oldGate
    try {
      await route.fulfill({ response })
    } catch {
      /* The shared publication observer cancels this obsolete response. */
    }
  })
  try {
    writeFileSync(
      users,
      userCSV +
        'DEMO_TWO,ZC:DEMO:A,G2,Demo,Two,two@example.test,20200101,99991231,20200101,99991231\n',
    )
    await page
      .getByRole('button', { name: 'Refresh role data from CSV', exact: true })
      .click()
    await expect.poll(() => refreshStarted).toBe(true)
    await nav(page, 'User Access')
    await expect.poll(() => oldCaptured).toBe(true)
    await nav(page, 'Release Roles')
    await nav(page, 'Dashboard')
    await expect(
      page.getByRole('button', { name: 'SAP users', exact: true }),
    ).toContainText('1')
    releaseRefresh()
    await expect(
      page.getByRole('button', { name: 'SAP users', exact: true }),
    ).toContainText('2')
    await nav(page, 'User Access')
    await expect(
      page.getByRole('button', { name: 'DEMO_TWO', exact: true }),
    ).toBeVisible()
    releaseOld()
    await expect(
      page.getByRole('button', { name: 'DEMO_TWO', exact: true }),
    ).toBeVisible()
  } finally {
    releaseRefresh()
    releaseOld()
  }
})

test('failed refresh retains data through navigation and a subsequent refresh recovers', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'User Access')
  await expect(
    page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
  ).toBeVisible()
  writeFileSync(users, 'invalid')
  await page
    .getByRole('button', { name: 'Refresh role data from CSV', exact: true })
    .click()
  await expect(page.locator('.notification-error')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
  ).toBeVisible()
  await nav(page, 'Dashboard')
  await expect(
    page.getByRole('button', { name: 'SAP users', exact: true }),
  ).toContainText('1')
  await nav(page, 'Role Lookup')
  await expect(page.getByRole('article')).toHaveCount(1)
  writeFileSync(users, userCSV.replaceAll('DEMO_ONE', 'DEMO_RECOVERED'))
  await page
    .getByRole('button', { name: 'Refresh role data from CSV', exact: true })
    .click()
  await expect(page.locator('.notification-error')).toHaveCount(0)
  await nav(page, 'User Access')
  await expect(
    page.getByRole('button', { name: 'DEMO_RECOVERED', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
  ).toHaveCount(0)
})

test('Dashboard is the default landing route and configuration links target their own sources', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await expect(
    page.getByRole('region', { name: 'Dashboard', exact: true }),
  ).toBeVisible()
  expect(new URL(page.url()).hash).toBe('#/dashboard')
  for (const name of [
    'SAP Overview',
    'Access & Risk',
    'Directory & Data Health',
    'Configuration',
  ])
    await expect(page.getByRole('region', { name, exact: true })).toBeVisible()
  await page
    .getByRole('button', { name: 'Configure User–Role Mapping', exact: true })
    .click()
  await expect(
    page.getByRole('tab', { name: 'User Access', exact: true }),
  ).toHaveAttribute('aria-selected', 'true')
  await page
    .getByRole('button', { name: 'Back to SAP Lens', exact: true })
    .click()
  await expect(
    page.getByRole('region', { name: 'Dashboard', exact: true }),
  ).toBeVisible()
})

for (const theme of ['light', 'dark'] as const)
  for (const width of [375, 800, 1280])
    test(`consolidated routes visual QA ${theme} ${width}`, async ({
      page,
      request,
    }, info) => {
      const settings = (
        await (await request.get('/api/configuration', { headers })).json()
      ).settings
      settings.theme = theme
      await request.post('/api/configuration', { headers, data: settings })
      await page.setViewportSize({ width, height: 1000 })
      await page.goto('/#session=browser-test-session')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await expect(
        page.getByRole('region', { name: 'Dashboard', exact: true }),
      ).toBeVisible()
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({
        path: info.outputPath('dashboard.png'),
        fullPage: true,
        animations: 'disabled',
      })
      await nav(page, 'User Access')
      await expect(
        page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
      ).toBeVisible()
      const filter = page.locator('.directory-filter-grid')
      const cols = await filter.evaluate(
        (el) => getComputedStyle(el).gridTemplateColumns.split(' ').length,
      )
      expect(cols).toBe(width >= 1100 ? 4 : width >= 640 ? 2 : 1)
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({
        path: info.outputPath('user-filters.png'),
        fullPage: true,
        animations: 'disabled',
      })
      await page.getByRole('button', { name: 'DEMO_ONE', exact: true }).click()
      const profile = page.getByRole('region', {
        name: 'User profile',
        exact: true,
      })
      await expect(profile).toContainText('Demo One')
      for (const label of [
        'SAP Identity',
        'Account Status',
        'Organization',
      ])
        await expect(
          profile.getByRole('region', { name: label, exact: true }),
        ).toBeVisible()
      await expect(profile).not.toContainText('Exact email match')
      await expect(profile).not.toContainText('Site')
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({
        path: info.outputPath('user-profile.png'),
        fullPage: true,
        animations: 'disabled',
      })
      await nav(page, 'Release Roles')
      await expect(
        page.getByLabel('Sort release roles', { exact: true }),
      ).toBeVisible()
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({
        path: info.outputPath('release-compact.png'),
        fullPage: true,
        animations: 'disabled',
      })
      await page
        .getByRole('button', { name: 'Assignment date filters', exact: true })
        .click()
      await expect(
        page.getByLabel('Start date from', { exact: true }),
      ).toBeHidden()
      await page
        .getByText('Advanced interval filtering', { exact: true })
        .click()
      await expect(
        page.getByLabel('Start date from', { exact: true }),
      ).toBeVisible()
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({
        path: info.outputPath('release-filters.png'),
        fullPage: true,
        animations: 'disabled',
      })
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true)
    })

test('directory-only name formatting preserves compounds and ambiguous structures', () => {
  for (const [input, output] of [
    ['van der Berg, Anna Maria', 'Anna Maria van der Berg'],
    ['O’Neill, Mary Anne', 'Mary Anne O’Neill'],
    ['Jean-Luc Martin', 'Jean-Luc Martin'],
    ['SMITH John', 'John SMITH'],
    ['VAN DER BERG Anna Maria', 'Anna Maria VAN DER BERG'],
    ['SMITH JOHN', 'SMITH JOHN'],
    ['McDonald John', 'McDonald John'],
    ['Smith, John, Jr.', 'Smith, John, Jr.'],
    ['Team 2, Demo', 'Team 2, Demo'],
    ['Demo (Group), Analyst', 'Demo (Group), Analyst'],
    ['J, Smith', 'J, Smith'],
    ['', ''],
  ])
    expect(directoryDisplayName(input)).toBe(output)
})

test('clear user filters resets all directory controls while evidence-only clear stays scoped', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'User Access')
  await page
    .getByRole('textbox', { name: 'Search users', exact: true })
    .fill('ONE')
  await page
    .getByRole('combobox', { name: 'Sort users', exact: true })
    .selectOption('email')
  await page.getByLabel('Descending', { exact: true }).check()
  await page
    .getByRole('textbox', { name: 'Filter users by transaction', exact: true })
    .fill('MIGO')
  await page
    .getByRole('textbox', { name: 'Filter users by transaction', exact: true })
    .press('Enter')
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(
    page.getByRole('textbox', { name: 'Search users', exact: true }),
  ).toHaveValue('')
  await expect(
    page.getByRole('combobox', { name: 'Sort users', exact: true }),
  ).toHaveValue('username')
  await expect(page.getByLabel('Descending', { exact: true })).not.toBeChecked()
  await expect(
    page.getByRole('button', { name: 'Remove transaction MIGO', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'DEMO_ONE', exact: true }),
  ).toBeVisible()
})

test('restored user detail waits for the startup publication instead of flashing not found', async ({
  page,
}) => {
  let loading = true
  await page.addInitScript(() => {
    sessionStorage.setItem('sap-lens-session', 'browser-test-session')
    history.replaceState(
      { sapLensView: { page: 'users', user: 'DEMO_ONE' } },
      '',
    )
  })
  await page.route('**/api/configuration', async (route) => {
    const response = await route.fetch(),
      data = await response.json()
    await route.fulfill({
      response,
      json: { ...data, loading, data_revision: loading ? 'empty' : 'ready' },
    })
  })
  await page.route('**/api/access/users/DEMO_ONE?*', async (route) => {
    if (loading)
      await route.fulfill({ status: 404, json: { detail: 'User not found' } })
    else await route.continue()
  })
  await page.goto('/#/user-access')
  await expect(
    page.getByRole('heading', { name: 'Loading CSV data…', exact: true }),
  ).toBeVisible()
  await expect(page.getByText('User not found', { exact: true })).toHaveCount(0)
  await expect(
    page.getByRole('region', { name: 'SAP Identity', exact: true }),
  ).toHaveCount(0)
  loading = false
  await expect(
    page.locator('.profile-identity-header'),
  ).toContainText('Demo One')
})

test('Dashboard catalogue action leaves comparison mode and preserves unrelated user filters', async ({
  page,
  request,
}) => {
  writeFileSync(roles, roleCSV + 'MM,ZC:DEMO:B,Demo inventory,ZS:B,MB51\n')
  expect((await request.post('/api/refresh', { headers })).ok()).toBeTruthy()
  await page.goto('/#session=browser-test-session')
  await nav(page, 'User Access')
  await page
    .getByRole('textbox', { name: 'Search users', exact: true })
    .fill('ONE')
  await nav(page, 'Role Lookup')
  await page
    .getByRole('button', { name: 'Add to comparison', exact: true })
    .first()
    .click()
  await page
    .getByRole('button', { name: 'Add to comparison', exact: true })
    .first()
    .click()
  await page.getByRole('button', { name: 'Compare now', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Back to roles', exact: false }),
  ).toBeVisible()
  await nav(page, 'Dashboard')
  await page
    .getByRole('button', { name: 'Catalogue roles', exact: true })
    .click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await nav(page, 'User Access')
  await expect(
    page.getByRole('textbox', { name: 'Search users', exact: true }),
  ).toHaveValue('ONE')
})
