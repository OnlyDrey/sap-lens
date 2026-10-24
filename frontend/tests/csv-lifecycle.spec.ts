import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const headers = { 'X-SAP-Lens': 'browser-test-session' }
const columns =
  'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'
let root: string, roles: string, users: string, directory: string
const directoryCsv = (count: number) =>
  columns +
  '\n' +
  Array.from(
    { length: count },
    (_, i) =>
      `;Example ${String(i).padStart(2, '0')};demo_${i};;${i < 2 ? '' : i < 4 ? 'shared@example.test' : `demo_${i}@example.test`};Operations;Analyst;true;CN=DEMO_${i};;;;;;;\n`,
  ).join('')
async function settings(request: APIRequestContext) {
  return (await (await request.get('/api/configuration', { headers })).json())
    .settings
}
async function save(request: APIRequestContext, change: (config: any) => void) {
  const config = await settings(request)
  change(config)
  const response = await request.post('/api/configuration', {
    headers,
    data: config,
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}
async function source(page: Page) {
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
}
async function refresh(page: Page) {
  await page
    .getByRole('button', { name: 'Refresh role data from CSV', exact: true })
    .click()
  await expect(page.getByLabel('Refresh result', { exact: true })).toBeVisible()
}
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  root = mkdtempSync(path.join(tmpdir(), 'sap-lens-lifecycle-'))
  roles = path.join(root, 'roles.csv')
  users = path.join(root, 'users.csv')
  directory = path.join(root, 'Employees ø.csv')
  writeFileSync(
    roles,
    'FUNCTION_KEY,AGR_NAME,TEXT,TCODE\nMM,ZC:DEMO,Example role,MIGO\n',
  )
  writeFileSync(
    users,
    'USERNAME,ROLE_NAME,EMAIL,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_A,ZC:DEMO,demo_4@example.test,20200101,99991231\nDEMO_B,ZC:DEMO,demo_5@example.test,20200101,99991231\n',
  )
  writeFileSync(directory, directoryCsv(31))
  await save(request, (c) => {
    c.data_csv_path = roles
    c.user_csv_path = users
    c.features.employee_directory = true
  })
  const config = await settings(request),
    preview = await (
      await request.post('/api/employees/preview', {
        headers,
        data: { path: directory, revision: config.revision },
      })
    ).json()
  expect(
    (
      await request.post('/api/employees/import', {
        headers,
        data: {
          path: directory,
          revision: config.revision,
          digest: preview.digest,
        },
      })
    ).ok(),
  ).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(root, { recursive: true, force: true })
})

test('refresh reports full removals, traps dialog focus and retains history after dismissal', async ({
  page,
  request,
}) => {
  await save(request, (c) => {
    c.source_modes.employees = 'dynamic'
  })
  await page.goto('/#session=browser-test-session')
  writeFileSync(directory, directoryCsv(16))
  writeFileSync(
    users,
    'USERNAME,ROLE_NAME,EMAIL,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_A,ZC:DEMO,demo_4@example.test,20200101,99991231\n',
  )
  await refresh(page)
  const banner = page.getByLabel('Refresh result', { exact: true })
  await expect(banner).toContainText('Data refreshed successfully')
  await expect(banner).toContainText(
    '3 CSV sources checked · 2 updated · 1 unchanged',
  )
  await banner
    .getByRole('button', { name: 'View Changes', exact: true })
    .click()
  const dialog = page.getByRole('dialog', {
    name: 'CSV data changes',
    exact: true,
  })
  await expect(dialog).toContainText('15 removed')
  await expect(
    dialog.getByRole('table', { name: 'CSV record changes', exact: true }),
  ).toContainText('CN=DEMO_16')
  await dialog
    .getByRole('combobox', { name: 'Change source', exact: true })
    .selectOption('employees')
  await dialog
    .getByRole('combobox', { name: 'Change type', exact: true })
    .selectOption('removed')
  await expect(dialog).toContainText('15 matching changes')
  const download = page.waitForEvent('download')
  await dialog.getByRole('button', { name: 'Export changes CSV' }).click()
  expect((await download).suggestedFilename()).toBe(
    'SAP-Lens-refresh-changes.csv',
  )
  await dialog.getByRole('button', { name: 'Close', exact: true }).focus()
  await page.keyboard.press('Tab')
  await expect(
    dialog.getByRole('button', { name: 'Close dialog', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(
    banner.getByRole('button', { name: 'View Changes', exact: true }),
  ).toBeFocused()
  await banner.getByRole('button', { name: 'Dismiss refresh report' }).click()
  await expect(banner).toHaveCount(0)
  expect(
    (await (await request.get('/api/employees', { headers })).json()).total,
  ).toBe(16)
  await source(page)
  await page.getByText('Recent refresh reports', { exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'CSV refresh history' }),
  ).toContainText('2 updated')
  await page.reload()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
  await page.getByText('Recent refresh reports', { exact: true }).click()
  await expect(
    page
      .getByRole('region', { name: 'CSV refresh history', exact: true })
      .getByRole('button', { name: 'View Changes', exact: true })
      .first(),
  ).toBeVisible()
  await page
    .getByRole('region', { name: 'CSV refresh history', exact: true })
    .getByRole('button', { name: 'View Changes', exact: true })
    .first()
    .click()
  await expect(
    page.getByRole('dialog', { name: 'CSV data changes', exact: true }),
  ).toContainText('15 removed')
})

test('unchanged and skipped sources are neutral, while partial errors preserve successful updates', async ({
  page,
  request,
}) => {
  await page.goto('/#session=browser-test-session')
  await refresh(page)
  let banner = page.getByLabel('Refresh result', { exact: true })
  await expect(banner).toContainText('All data is up to date')
  await expect(banner).toContainText('1 skipped')
  await expect(
    banner.getByRole('button', { name: 'View Changes' }),
  ).toHaveCount(0)
  writeFileSync(directory, directoryCsv(1)) // static source must remain at 31.
  writeFileSync(roles, 'AGR_NAME,TEXT,TCODE\nZC:DEMO,Changed role,ME21N\n')
  rmSync(users)
  await refresh(page)
  banner = page.getByLabel('Refresh result', { exact: true })
  await expect(banner).toContainText('Refresh completed with errors')
  await expect(
    banner.getByRole('button', { name: 'View Changes' }),
  ).toHaveCount(0)
  await banner.getByRole('button', { name: 'View Errors' }).click()
  const dialog = page.getByRole('dialog', {
    name: 'Refresh errors',
    exact: true,
  })
  await expect(dialog).toContainText('configured CSV is missing')
  await expect(dialog).toContainText('Previous validated records preserved')
  await expect(dialog).not.toContainText(root)
  expect(
    (await (await request.get('/api/employees', { headers })).json()).total,
  ).toBe(31)
  expect(
    (await (await request.get('/api/access/users', { headers })).json()).total,
  ).toBe(2)
  expect(
    (await (await request.get('/api/access/users/DEMO_A', { headers })).json())
      .username,
  ).toBe('DEMO_A')
})

test('directory preview is paginated and filters quality warnings before explicit replacement', async ({
  page,
  request,
}) => {
  await page.goto('/#session=browser-test-session')
  await source(page)
  await page
    .getByRole('tab', { name: 'Employee Directory', exact: true })
    .click()
  await expect(
    page.getByRole('combobox', { name: 'CSV source mode', exact: true }),
  ).toHaveValue('static')
  await expect(
    page.getByRole('button', { name: 'Import directory', exact: true }),
  ).toBeDisabled()
  await page
    .getByRole('button', { name: 'Validate & preview directory', exact: true })
    .click()
  const preview = page.getByRole('region', {
    name: 'Directory import preview',
    exact: true,
  })
  await expect(preview).toContainText('31 matching preview records')
  await preview
    .getByRole('combobox', { name: 'Preview records', exact: true })
    .selectOption('missing_email')
  await expect(preview).toContainText('2 matching preview records')
  await preview
    .getByRole('combobox', { name: 'Preview records', exact: true })
    .selectOption('duplicate_email')
  await expect(preview).toContainText('2 matching preview records')
  expect(
    (await (await request.get('/api/employees/status', { headers })).json())
      .report.records,
  ).toBe(31)
  const replacement = path.join(root, 'replacement.csv')
  writeFileSync(replacement, directoryCsv(16))
  await page
    .getByRole('textbox', {
      name: 'Employee Directory CSV location',
      exact: true,
    })
    .fill(replacement)
  await expect(
    page.getByRole('button', { name: 'Import directory', exact: true }),
  ).toBeDisabled()
  await page
    .getByRole('button', { name: 'Validate & preview directory', exact: true })
    .click()
  await expect(
    page.getByRole('region', { name: 'Import / Replace', exact: true }),
  ).toContainText('15 removed')
  page.once('dialog', (dialog) => dialog.dismiss())
  await page
    .getByRole('button', { name: 'Import directory', exact: true })
    .click()
  expect(
    (await (await request.get('/api/employees/status', { headers })).json())
      .report.records,
  ).toBe(31)
  page.once('dialog', (dialog) => dialog.accept())
  await page
    .getByRole('button', { name: 'Import directory', exact: true })
    .click()
  await expect(
    page.getByText(/Directory imported: 16 records saved locally/),
  ).toBeVisible()
})

test('change CSV export uses the authenticated native save bridge without browser downloads', async ({
  page,
  request,
}) => {
  await save(request, (config) => {
    config.source_modes.employees = 'dynamic'
  })
  await page.goto('/#session=browser-test-session')
  writeFileSync(directory, directoryCsv(30))
  await refresh(page)
  await page.getByRole('button', { name: 'View Changes', exact: true }).click()
  await page.evaluate(() => {
    ;(window as any).__savedChanges = []
    window.pywebview = {
      api: {
        choose_csv: async () => null,
        save_refresh_changes_csv: async (token, filename, content) => {
          ;(window as any).__savedChanges.push({ token, filename, content })
          return true
        },
      },
    }
  })
  let downloads = 0
  page.on('download', () => downloads++)
  await page
    .getByRole('dialog', { name: 'CSV data changes', exact: true })
    .getByRole('button', { name: 'Export changes CSV', exact: true })
    .click()
  await expect(
    page.getByText('Changes CSV saved locally.', { exact: true }),
  ).toBeVisible()
  const calls = await page.evaluate(() => (window as any).__savedChanges)
  expect(calls).toHaveLength(1)
  expect(calls[0].token).toBe('browser-test-session')
  expect(calls[0].filename).toMatch(
    /^sap-lens-refresh-changes-report-\d{4}-\d{2}-\d{2}\.csv$/,
  )
  expect(calls[0].content).toContain(
    '\ufeff"Timestamp","Source","Change","Identifier","Field","Before","After"\r\n',
  )
  expect(calls[0].content).toContain('CN=DEMO_30')
  expect(downloads).toBe(0)
})

for (const theme of ['light', 'dark'])
  for (const width of [375, 800, 1280])
    test(`lifecycle visual ${theme} ${width}`, async ({
      page,
      request,
    }, info) => {
      await save(request, (c) => {
        c.theme = theme
        c.source_modes.employees = 'dynamic'
      })
      await page.setViewportSize({ width, height: 950 })
      await page.goto('/#session=browser-test-session')
      writeFileSync(directory, directoryCsv(30))
      await refresh(page)
      await page.screenshot({ path: info.outputPath('refresh-success.png') })
      await page
        .getByRole('button', { name: 'View Changes', exact: true })
        .click()
      const dialog = page.getByRole('dialog', {
        name: 'CSV data changes',
        exact: true,
      })
      await expect(dialog).toBeVisible()
      await expect
        .poll(async () => {
          const box = await dialog.boundingBox()
          return !!box && box.x >= 0 && box.x + box.width <= width
        })
        .toBeTruthy()
      await page.screenshot({ path: info.outputPath('change-dialog.png') })
      await page.keyboard.press('Escape')
      await refresh(page)
      await expect(
        page.getByLabel('Refresh result', { exact: true }),
      ).toContainText('All data is up to date')
      await page.screenshot({ path: info.outputPath('refresh-unchanged.png') })
      rmSync(users)
      await refresh(page)
      await page.screenshot({ path: info.outputPath('refresh-errors.png') })
      await page
        .getByRole('button', { name: 'View Errors', exact: true })
        .click()
      await page.screenshot({ path: info.outputPath('error-dialog.png') })
      await page.keyboard.press('Escape')
      await source(page)
      await page
        .getByRole('tab', { name: 'Employee Directory', exact: true })
        .click()
      await page
        .getByRole('button', {
          name: 'Validate & preview directory',
          exact: true,
        })
        .click()
      await page.screenshot({ path: info.outputPath('directory-import.png') })
      await page.getByRole('tab', { name: 'Features', exact: true }).click()
      await page.screenshot({ path: info.outputPath('features.png') })
      await page
        .getByRole('tab', { name: 'Health & Diagnostics', exact: true })
        .click()
      await page.screenshot({ path: info.outputPath('diagnostics.png') })
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy()
    })
