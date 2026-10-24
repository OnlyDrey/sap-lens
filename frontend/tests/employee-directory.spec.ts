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
    'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_EMPLOYEE,ZC:FI:VIEW, EMPLOYEE@example.test ,DEMO,20200101,99991231,20200101,99991231\nDEMO_NO_EMAIL,,,DEMO,20200101,99991231,,\nSAP_MANAGER,,manager@example.test,DEMO,20200101,99991231,,\n',
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
  await expect(page.getByRole('button',{name:'Save and load CSV',exact:true})).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Apply settings',exact:true})).toBeDisabled()
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
  await page.getByRole('region',{name:'Import / Replace',exact:true})
    .getByRole('button', { name: 'Import directory' })
    .click()
  await expect(preview).toBeHidden()
  await page.getByRole('tab', { name: 'Features', exact: true }).click()
  await expect(page.getByRole('switch', {name:'Employee Directory feature',exact:true})).toHaveAttribute(
    'aria-checked',
    'false',
  )
  await page.getByRole('switch', {name:'Employee Directory feature',exact:true}).click()
  await page
    .getByRole('button', { name: 'Apply settings', exact: true })
    .click()
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: 'User Access', exact: true })
    .click()
  await page.getByRole('button', { name: 'DEMO_EMPLOYEE', exact: true }).click()
  const enrichment = page.getByRole('region', {
    name: 'Organization',
    exact: true,
  })
  await expect(enrichment).toContainText('Engineering')
  await enrichment.getByRole('button', { name: 'View SAP user' }).click()
  await expect(page.getByRole('region',{name:'SAP Identity',exact:true})).toContainText('SAP_MANAGER')
  await page.goBack()
  await expect(page.getByRole('region',{name:'SAP Identity',exact:true})).toContainText('DEMO_EMPLOYEE')
  await page.reload()
  await expect(enrichment).toContainText('Engineering')
  await expect(enrichment).not.toContainText('Exact email match')
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
    page.getByRole('region', { name: 'Organization' }),
  ).toContainText('Employee Directory disabled or unavailable.')
  await expect(
    page.locator('.profile-identity-header'),
  ).toContainText('EMPLOYEE@example.test')
  await enable(request)
  await page.reload()
  await expect(
    page.getByRole('region', { name: 'Organization' }),
  ).toContainText('Engineering')
  await enable(request, false)
  await page.reload()
  await expect(
    page.getByRole('region', { name: 'Organization' }),
  ).toContainText('Employee Directory disabled or unavailable.')
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
    page.getByRole('region', { name: 'Directory import status' }),
  ).toContainText('Not configured')
  expect((await settings(request)).user_csv_path).toContain('users.csv')
  expect((await settings(request)).features.employee_directory).toBe(true)
})

for (const theme of ['light', 'dark'] as const)
  for (const width of [800, 1280]) {
    test(`directory settings visual and keyboard QA ${theme} ${width}`, async ({
      page,
      request,
    }, info) => {
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
        page.getByRole('region', { name: 'Directory import status' }),
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
      const out = info.outputPath('qa')
      mkdirSync(out, { recursive: true })
      await page.screenshot({
        path: `${out}/data-sources-${theme}-${width}.png`,
        fullPage: true,
      })
      await page.getByRole('tab', { name: 'Features', exact: true }).click()
      await expect(page.getByRole('switch', {name:'Employee Directory feature',exact:true})).toHaveAttribute(
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
    page.getByRole('region', { name: 'Organization' }),
  ).toContainText('No uniquely matched directory organization information.')
  await page
    .getByRole('button', { name: 'Back to users', exact: true })
    .click()
  await page.getByRole('button', { name: 'DEMO_NO_EMAIL', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'Organization' }),
  ).toContainText('No uniquely matched directory organization information.')
  const status = await (
    await request.get('/api/employees/status', { headers })
  ).json()
  expect(status.status).toBe('warning')
  expect(status.report.duplicate_emails).toBe(1)
})

test('directory import and clear preserve independent catalogue filters, comparison and SAP generation', async ({ page, request }) => {
  const before = (await (await request.get('/api/access/users/DEMO_EMPLOYEE', { headers })).json()).data_revision
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Role Lookup',exact:true}).click()
  const search = page.getByPlaceholder('Search roles by name or description...')
  await search.fill('finance')
  await page.getByRole('button', { name: 'Add to comparison', exact: true }).first().click()
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
  await page.getByRole('tab', { name: 'Employee Directory', exact: true }).click()
  await page.getByLabel('Employee Directory CSV location', { exact: true }).fill(csv)
  await page.getByRole('button', { name: 'Validate & preview directory', exact: true }).click()
  await page.getByRole('button', { name: 'Import directory', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Directory import preview' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
  await expect(search).toHaveValue('finance')
  await expect(page.getByRole('button', { name: 'Remove from comparison', exact: true })).toHaveCount(1)
  expect((await (await request.get('/api/access/users/DEMO_EMPLOYEE', { headers })).json()).data_revision).toBe(before)
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: 'Clear directory data', exact: true }).click()
  await expect(page.getByLabel('Employee Directory CSV location', { exact: true })).toHaveValue('')
  await page.getByRole('button', { name: 'Back to SAP Lens', exact: true }).click()
  await expect(search).toHaveValue('finance')
  await expect(page.getByRole('button', { name: 'Remove from comparison', exact: true })).toHaveCount(1)
})

test('explicit import, independent feature toggles, retained data and Diagnostics stay synchronized', async ({page,request}) => {
  await source(page)
  await page.getByLabel('Employee Directory CSV location',{exact:true}).fill(csv)
  await expect(page.getByLabel('Directory selection state',{exact:true})).toContainText('not validated or imported')
  await page.getByRole('button',{name:'Validate & preview directory',exact:true}).click()
  await expect(page.getByLabel('Directory selection state',{exact:true})).toContainText('Validated')
  await page.getByRole('button',{name:'Import directory',exact:true}).click()
  await expect(page.getByRole('status').filter({hasText:'Directory imported:'})).toContainText('2 records saved locally')
  const status=page.getByRole('region',{name:'Directory import status',exact:true})
  await expect(status).toContainText('Disabled'); await expect(status).toContainText('Records saved locally')
  const identity=(await settings(request)).employee_snapshot_id
  await status.getByRole('button',{name:'Enable in Feature Settings',exact:true}).click()
  await expect(page.getByRole('region',{name:'Employee Directory diagnostics'})).toHaveCount(0)
  await expect(page.getByRole('region',{name:'Employee Directory feature settings'})).not.toContainText('Missing emails')
  await page.getByRole('switch',{name:'Employee Directory feature',exact:true}).click()
  await page.getByRole('switch',{name:'User–Role Mapping feature',exact:true}).click()
  await page.getByRole('button',{name:'Apply settings',exact:true}).click()
  await expect(page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'User Access',exact:true})).toBeEnabled()
  await page.reload()
  await expect(page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'User Access',exact:true})).toBeEnabled()
  expect((await settings(request)).features).toEqual({employee_directory:true,user_role_mapping:false})
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'User Access',exact:true}).click()
  await expect(page.getByRole('region',{name:'User–Role Mapping disabled',exact:true})).toBeVisible()
  expect((await request.get('/api/access/users',{headers})).status()).toBe(409)
  const dependency=await (await request.get('/api/employees/status',{headers})).json()
  expect(dependency.enabled).toBe(true); expect(dependency.loaded).toBe(true); expect(dependency.dependency_satisfied).toBe(false)
  await page.getByRole('button',{name:'Open settings',exact:true}).click()
  await page.getByRole('tab',{name:'Health & Diagnostics',exact:true}).click()
  await page.getByText('Source locations and storage details',{exact:true}).click()
  for (const name of ['Role Catalogue CSV','User Access CSV']) await page.getByRole('region',{name,exact:true}).getByText('Technical source details',{exact:true}).click()
  await page.getByText('Employee Directory technical details',{exact:true}).click()
  await expect(page.getByRole('region',{name:'Employee Directory diagnostics'})).toContainText('Enable User–Role Mapping')
  await page.getByRole('tab',{name:'Features',exact:true}).click()
  await page.getByRole('switch',{name:'User–Role Mapping feature',exact:true}).click()
  await page.getByRole('button',{name:'Apply settings',exact:true}).click()
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'User Access',exact:true}).click()
  await expect(page.getByRole('button',{name:'DEMO_EMPLOYEE',exact:true})).toBeVisible()
  expect((await settings(request)).employee_snapshot_id).toBe(identity)
  expect((await (await request.get('/api/employees/status',{headers})).json()).coverage.matched).toBe(2)
})

for (const [state,message] of [['unmatched','SAP user not found'],['ambiguous','Multiple SAP users found'],['missing_email','Manager email not provided']] as const) {
  test(`manager ${state} has no broken navigation link`,async({page,request})=>{
    await importDirectory(request); await enable(request)
    await page.route('**/api/employees/match/**',async route=>{
      const response=await route.fetch(), json=await response.json()
      await route.fulfill({response,json:{...json,manager_sap:{status:state,username:null}}})
    })
    await page.goto('/#session=browser-test-session')
    await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'User Access',exact:true}).click()
    await page.getByRole('button',{name:'DEMO_EMPLOYEE',exact:true}).click()
    const profile=page.getByRole('region',{name:'Organization',exact:true})
    await expect(profile).toContainText(message)
    await expect(profile.getByRole('button',{name:'View SAP user',exact:true})).toHaveCount(0)
  })
}

for (const theme of ['light','dark'] as const) for (const width of [375,800,1280]) {
  test(`employee profile and compact date calendar visual QA ${theme} ${width}`,async({page,request},info)=>{
    await importDirectory(request); await enable(request)
    const current=await settings(request); current.theme=theme
    expect((await request.post('/api/configuration',{headers,data:current})).ok()).toBeTruthy()
    await page.setViewportSize({width,height:1000})
    await page.goto('/#session=browser-test-session')
    await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'User Access',exact:true}).click()
    await page.getByRole('button',{name:'DEMO_EMPLOYEE',exact:true}).click()
    const profile=page.getByRole('region',{name:'Organization',exact:true})
    await expect(profile).toContainText('Engineering'); await expect(page.getByRole('region',{name:'Account Status',exact:true})).toContainText('AD account status')
    await expect(profile).not.toContainText('Manager department')
    const button=page.getByRole('button',{name:'Assignment date filters',exact:true})
    const account=page.getByRole('region',{name:'Account Status'})
    expect((await button.boundingBox())!.y).toBeGreaterThan((await account.boundingBox())!.y+(await account.boundingBox())!.height)
    await page.screenshot({path:info.outputPath('employee-profile.png'),fullPage:true})
    await button.click()
    await page.getByText('Advanced interval filtering',{exact:true}).click()
    const input=page.getByLabel('Start date from',{exact:true})
    await expect(input).toHaveAttribute('placeholder','DD.MM.YYYY')
    await input.fill('31.02.2024')
    await page.getByRole('button',{name:'Apply date filters',exact:true}).click()
    await expect(page.getByRole('alert')).toContainText('valid DD.MM.YYYY')
    await input.fill('29.02.2024')
    await page.getByRole('button',{name:'Choose Start date from',exact:true}).click()
    const calendar=page.getByRole('dialog',{name:'Calendar for Start date from',exact:true})
    await expect(calendar).toContainText('februar 2024')
    await expect(calendar.getByRole('button',{name:'29.02.2024',exact:true})).toHaveAttribute('aria-pressed','true')
    await page.screenshot({path:info.outputPath('norwegian-calendar.png'),fullPage:true})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    await calendar.getByRole('button',{name:'29.02.2024',exact:true}).press('Escape')
    await expect(page.getByRole('button',{name:'Choose Start date from',exact:true})).toBeFocused()
    await page.getByRole('button',{name:'Apply date filters',exact:true}).click()
    await expect(page.getByLabel('Active assignment date filters',{exact:true})).toContainText('29.02.2024')
    await page.getByRole('button',{name:'Clear all assignment filters',exact:true}).click()
    await expect(page.getByLabel('Active assignment date filters',{exact:true})).toHaveCount(0)
  })
}

test('unified profile keeps SAP identity authoritative and directory fields in their own groups',async({page,request})=>{
  await importDirectory(request);await enable(request)
  writeFileSync(path.join(directory,'users.csv'),'USERNAME,ROLE_NAME,FIRST_NAME,LAST_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_EMPLOYEE,ZC:FI:VIEW,SAP,Authoritative,employee@example.test,DEMO,20200101,99991231,20200101,99991231\nSAP_MANAGER,,SAP,Manager,manager@example.test,DEMO,20200101,99991231,,\n')
  expect((await request.post('/api/refresh',{headers})).ok()).toBeTruthy()
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'User Access',exact:true}).click()
  await page.getByRole('button',{name:'DEMO_EMPLOYEE',exact:true}).click()
  const identity=page.getByRole('region',{name:'SAP Identity',exact:true}),account=page.getByRole('region',{name:'Account Status',exact:true}),organization=page.getByRole('region',{name:'Organization',exact:true})
  await expect(page.locator('.profile-identity-header')).toContainText('SAP Authoritative');await expect(page.locator('.profile-identity-header')).toContainText('employee@example.test')
  await expect(organization).toContainText('Engineering');await expect(organization).not.toContainText('Demo Employee')
  await expect(organization).not.toContainText('employee@example.test');await expect(account).toContainText('AD account status')
  await expect(organization).not.toContainText('Site');await expect(page.getByText('Exact email match',{exact:true})).toHaveCount(0)
  await organization.getByRole('button',{name:'View SAP user',exact:true}).click()
  await expect(identity).toContainText('SAP_MANAGER');await page.goBack();await expect(page.locator('.profile-identity-header')).toContainText('SAP Authoritative')
})
