import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
const columns =
  'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'
let directory: string, csv: string
async function settings(request: APIRequestContext) {
  return (await (await request.get('/api/configuration', { headers })).json())
    .settings
}
async function importDirectory(request: APIRequestContext) {
  const revision = (await settings(request)).revision
  const preview = await request.post('/api/employees/preview', {
    headers,
    data: { path: csv, revision },
  })
  expect(preview.ok()).toBeTruthy()
  expect(
    (
      await request.post('/api/employees/import', {
        headers,
        data: { path: csv, revision, digest: (await preview.json()).digest },
      })
    ).ok(),
  ).toBeTruthy()
}
async function enable(request: APIRequestContext, value = true) {
  const current = await settings(request)
  current.features.employee_directory = value
  expect(
    (await request.post('/api/configuration', { headers, data: current })).ok(),
  ).toBeTruthy()
}
async function source(page: Page) {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
  await page
    .getByRole('tab', { name: 'Employee Directory', exact: true })
    .click()
}
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-employees-'))
  csv = path.join(directory, 'Employees Éxport.csv')
  writeFileSync(
    csv,
    '\ufeff' +
      columns +
      '\n' +
      'North;Demo Employee;demo_employee;;employee@example.test;Engineering;Analyst;true;;;Demo Manager;demo_manager;manager@example.test;Operations;Lead;Resolved\n' +
      'West;Demo Manager;demo_manager;;manager@example.test;Operations;Lead;false;;;;;;;;\n',
  )
  const users = path.join(directory, 'users.csv')
  writeFileSync(
    users,
    'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_EMPLOYEE,ZC:FI:VIEW, EMPLOYEE@example.test ,DEMO,20200101,99991231,20200101,99991231\nDEMO_NO_EMAIL,,,DEMO,20200101,99991231,,\n',
  )
  const current = await settings(request)
  current.data_csv_path = path.resolve('tests/fixtures/synthetic.csv')
  current.user_csv_path = users
  expect(
    (await request.post('/api/configuration', { headers, data: current })).ok(),
  ).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})

test('directory preview, confirmation, feature persistence, manager drill-down and failed replacement', async ({
  page,
  request,
}) => {
  await source(page)
  await page
    .getByLabel('Employee Directory CSV location', { exact: true })
    .fill(csv)
  await page
    .getByRole('button', { name: 'Validate & preview directory', exact: true })
    .click()
  const preview = page.getByRole('region', {
    name: 'Directory import preview',
    exact: true,
  })
  await expect(preview).toContainText('2 records')
  expect((await settings(request)).employee_csv_path).toBe('')
  await preview
    .getByRole('button', { name: 'Confirm directory replacement' })
    .click()
  await expect(preview).toBeHidden()
  await page.getByRole('tab', { name: 'Features', exact: true }).click()
  await expect(page.getByRole('switch')).toHaveAttribute(
    'aria-checked',
    'false',
  )
  await page.getByRole('switch').click()
  await page
    .getByRole('button', { name: 'Apply settings', exact: true })
    .click()
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: 'User Access', exact: true })
    .click()
  await page.getByRole('button', { name: 'DEMO_EMPLOYEE', exact: true }).click()
  const enrichment = page.getByRole('region', {
    name: 'Employee Directory enrichment',
    exact: true,
  })
  await expect(enrichment).toContainText('Engineering')
  await enrichment.getByRole('button', { name: 'View manager' }).click()
  await expect(
    enrichment.getByRole('region', { name: 'Manager employee details' }),
  ).toContainText('Operations')
  await page.reload()
  await expect(enrichment).toContainText('Exact email match')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
  await page
    .getByRole('tab', { name: 'Employee Directory', exact: true })
    .click()
  writeFileSync(csv, 'invalid')
  await page
    .getByRole('button', { name: 'Validate & preview directory', exact: true })
    .click()
  await expect(page.getByRole('alert')).toContainText(
    'Previous valid data is retained',
  )
  expect(
    (await (await request.get('/api/employees', { headers })).json()).total,
  ).toBe(2)
})

test('disabled and missing optional directory never replaces SAP information or fails health', async ({
  page,
  request,
}) => {
  await importDirectory(request)
  await page.goto('/#session=browser-test-session')
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: 'User Access', exact: true })
    .click()
  await page.getByRole('button', { name: 'DEMO_EMPLOYEE', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'Employee Directory enrichment' }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('region', { name: 'User information', exact: true }),
  ).toContainText('EMPLOYEE@example.test')
  await enable(request)
  await page.reload()
  await expect(
    page.getByRole('region', { name: 'Employee Directory enrichment' }),
  ).toContainText('Demo Employee')
  await enable(request, false)
  await page.reload()
  await expect(
    page.getByRole('region', { name: 'Employee Directory enrichment' }),
  ).toHaveCount(0)
  expect((await request.get('/health')).ok()).toBeTruthy()
})

test('search, manager navigation, clear confirmation and data preservation', async ({
  page,
  request,
}) => {
  await importDirectory(request)
  await enable(request)
  await source(page)
  const search = page.getByRole('region', {
    name: 'Employee search',
    exact: true,
  })
  await search.getByRole('textbox').fill('Engineering')
  await expect(search).toContainText('1 matching employees')
  await search
    .getByRole('button', { name: 'Demo Employee', exact: true })
    .click()
  await search.getByRole('button', { name: 'View manager' }).click()
  await expect(
    search.getByRole('region', { name: 'Employee details', exact: true }),
  ).toContainText('Demo Manager')
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByRole('button', { name: 'Clear directory data' }).click()
  expect((await settings(request)).employee_csv_path).toBe(csv)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Clear directory data' }).click()
  await expect(
    page.getByRole('region', { name: 'Employee Directory diagnostics' }),
  ).toContainText('Not configured')
  expect((await settings(request)).user_csv_path).toContain('users.csv')
  expect((await settings(request)).features.employee_directory).toBe(true)
})

for (const theme of ['light', 'dark'] as const)
  for (const width of [800, 1280]) {
    test(`directory settings visual and keyboard QA ${theme} ${width}`, async ({
      page,
      request,
    }) => {
      await importDirectory(request)
      await enable(request)
      const current = await settings(request)
      current.theme = theme
      expect(
        (
          await request.post('/api/configuration', { headers, data: current })
        ).ok(),
      ).toBeTruthy()
      await page.setViewportSize({ width, height: 1000 })
      await source(page)
      await expect(
        page.getByRole('region', { name: 'Employee Directory diagnostics' }),
      ).toContainText('2')
      const tab = page.getByRole('tab', {
        name: 'Employee Directory',
        exact: true,
      })
      await tab.focus()
      await tab.press('ArrowLeft')
      await expect(
        page.getByRole('tab', { name: 'User Access', exact: true }),
      ).toBeFocused()
      await page.keyboard.press('ArrowRight')
      await expect(tab).toBeFocused()
      await page
        .getByLabel('Employee Directory CSV location', { exact: true })
        .focus()
      await expect(
        page.getByLabel('Employee Directory CSV location', { exact: true }),
      ).toBeFocused()
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true)
      const out = '/workspace/sap-lens-dev/employee-directory-qa'
      mkdirSync(out, { recursive: true })
      await page.screenshot({
        path: `${out}/data-sources-${theme}-${width}.png`,
        fullPage: true,
      })
      await page.getByRole('tab', { name: 'Features', exact: true }).click()
      await expect(page.getByRole('switch')).toHaveAttribute(
        'aria-checked',
        'true',
      )
      await page.screenshot({
        path: `${out}/features-${theme}-${width}.png`,
        fullPage: true,
      })
    })
  }

test('duplicate and missing email states remain distinct with diagnostics warnings', async ({
  page,
  request,
}) => {
  const row = (name: string) =>
    [
      'North',
      name,
      '',
      '',
      'employee@example.test',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
    ].join(';')
  writeFileSync(
    csv,
    columns + '\n' + row('Demo One') + '\n' + row('Demo Two') + '\n',
  )
  await importDirectory(request)
  await enable(request)
  await page.goto('/#session=browser-test-session')
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: 'User Access', exact: true })
    .click()
  await page.getByRole('button', { name: 'DEMO_EMPLOYEE', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'Employee Directory enrichment' }),
  ).toContainText('Duplicate directory email; no employee selected.')
  await page
    .getByRole('button', { name: 'Back to users', exact: true })
    .click()
  await page.getByRole('button', { name: 'DEMO_NO_EMAIL', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'Employee Directory enrichment' }),
  ).toContainText('SAP email is missing.')
  const status = await (
    await request.get('/api/employees/status', { headers })
  ).json()
  expect(status.status).toBe('warning')
  expect(status.report.duplicate_emails).toBe(1)
})
