import { test, expect, type Locator, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers, goTo } from './support'
let root: string
const mode = async (page: Page, name: string) =>
  page
    .getByRole('navigation', { name: 'User Access view', exact: true })
    .getByRole('link', { name, exact: true })
    .click()
const saved = (page: Page, view: string) =>
  page.getByRole('dialog', { name: `${view} saved filters`, exact: true })
async function openSaved(page: Page, view: string) {
  if (!(await saved(page, view).isVisible()))
    await page
      .locator(`div.saved-filter-toolbar[aria-label="${view} saved filters"]`)
      .getByRole('button', { name: /Saved filters/ })
      .click()
}
async function comparison(page: Page) {
  await goTo(page, 'User Access')
  await mode(page, 'Compare users')
}
async function choose(page: Page, label: string, query: string) {
  const box = page.getByRole('combobox', { name: label, exact: true })
  // Saved-filter popovers deliberately focus this selector without opening it.
  // Click explicitly, including when searching for the already-selected value.
  await box.click()
  await box.fill(query)
  await page.getByRole('option').filter({ hasText: query }).first().click()
}
async function expectIntervals(page:Page,scope:Locator,expected:string[]){
 const values:string[]=[]
 for(const button of await scope.getByRole('button',{name:/^(Active assignment|Expired assignment|Future assignment|Unknown validity)$/}).all()){
  await button.click();const popup=page.getByRole('dialog',{name:/^Assignment validity for/});const facts=await popup.locator('dd').allTextContents();values.push(`${facts[0]} → ${facts[1]}`);await page.keyboard.press('Escape')
 }
 for(const interval of expected)expect(values).toContain(interval)
}
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  root = mkdtempSync(path.join(tmpdir(), 'sap-lens-tools-'))
  const roles = path.join(root, 'catalogue.csv'),
    users = path.join(root, 'users.csv')
  writeFileSync(
    roles,
    'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nFI,ZC:SHARED:*,Shared viewer,ZS:SHARED,FB03\nMM,ZC:ONLY_A,Materials,ZS:A,ME23N\nMM,ZC:ONLY_A,Materials,ZS:A,FB03\nFI,ZC:EMPTY,,ZS:EMPTY,\n',
  )
  writeFileSync(
    users,
    'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,USER_TYPE,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_A,ZC:SHARED:ENP,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20000101,99991231\nDEMO_A,ZC:SHARED:ENP,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20010101,99991231\nDEMO_A,ZC:ONLY_A,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20000101,99991231\nDEMO_A,ZC:OLD,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20000101,20010101\nDEMO_A,ZC:UNKNOWN,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,,\nDEMO_B,ZC:SHARED:ENP,DEMO,Beta,Example,b@example.test,20000101,99991231,0,A,20000101,99991231\nDEMO_EMPTY,,DEMO,Empty,Example,,20000101,99991231,,Z,,\n',
  )
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
  expect((await request.post('/api/refresh', { headers })).ok()).toBeTruthy()
  // Independent per-user file: clear only synthetic filters from previous cases.
  const items = (
    await (await request.get('/api/saved-filters', { headers })).json()
  ).items
  for (const item of items)
    expect(
      (
        await request.post('/api/saved-filters/delete', {
          headers,
          data: { id: item.id, expected: item.modified },
        })
      ).ok(),
    ).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(root, { recursive: true, force: true })
})

test('comparison entry from details retains User A and original comparison on Back', { tag: '@smoke' }, async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  await page.getByRole('link', { name: 'DEMO_A', exact: true }).click()
  await page.getByRole('button', { name: 'Compare users', exact: true }).click()
  await expect(
    page.getByRole('combobox', { name: 'User A', exact: true }),
  ).toHaveValue(/DEMO_A/)
  await choose(page, 'User B', 'DEMO_B')
  await expect(
    page
      .getByLabel('Comparison summary')
      .getByText('Shared roles', { exact: true })
      .locator('..')
      .getByText('1', { exact: true }),
  ).toBeVisible()
  const table = page.getByRole('table', { name: 'User comparison evidence' })
  await expectIntervals(page,table,['01.01.2000 → 31.12.9999','01.01.2001 → 31.12.9999'])
  await page.getByRole('button', { name: 'Open User B', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'User details', exact: true }),
  ).toBeVisible()
  await page.goBack()
  await expect(
    page.getByRole('heading', { name: 'Compare users', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('combobox', { name: 'User B', exact: true }),
  ).toHaveValue(/DEMO_B/)
})
test('comparison filters roles, validity and derived transactions with inspectable evidence', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await comparison(page)
  await choose(page, 'User A', 'Alpha')
  await choose(page, 'User B', 'b@example.test')
  await page.getByLabel('Comparison summary',{exact:true}).getByRole('button',{name:/^(Only User A|Mapped transactions only A)/}).click()
  await expect(
    page.getByRole('table', { name: 'User comparison evidence' }),
  ).toContainText('ZC:ONLY_A')
  await page
    .getByLabel('Comparison section', { exact: true })
    .selectOption('transactions')
  const table = page.getByRole('table', { name: 'User comparison evidence' })
  await expect(table).toContainText('ME23N')
  await expect(table).not.toContainText('FB03')
  await page.getByLabel('Comparison summary',{exact:true}).getByRole('button',{name:/^Shared/}).click()
  await expect(table).toContainText('FB03')
  await expect(table).toContainText('ZC:ONLY_A')
  await expect(table).toContainText('ZC:SHARED:ENP')
  await page
    .getByLabel('Assignment validity', { exact: true })
    .selectOption('unknown')
  await expect(
    page.getByText('No matching transactions.', { exact: false }),
  ).toBeVisible()
  await page
    .getByLabel('Comparison section', { exact: true })
    .selectOption('roles')
  await page.getByRole('button',{name:'Clear comparison difference',exact:true}).click()
  await expect(table).toContainText('ZC:UNKNOWN')
})
test('user selectors search alternate SAP email observations without guessing identities', async ({
  page,
  request,
}) => {
  const source = path.join(root, 'users.csv')
  writeFileSync(
    source,
    readFileSync(source, 'utf8') +
      'DEMO_A,,DEMO,Alpha,Example,alternate@example.test,20000101,99991231,0,A,,\n',
  )
  expect((await request.post('/api/refresh', { headers })).ok()).toBeTruthy()
  await page.goto('/#session=browser-test-session')
  await comparison(page)
  const response = page.waitForResponse(
    (r) =>
      r.url().includes('/api/access/users?') &&
      new URL(r.url()).searchParams.get('search') === 'alternate@example.test',
  )
  await page
    .getByRole('combobox', { name: 'User A', exact: true })
    .fill('alternate@example.test')
  await response
  await page.getByRole('option').filter({ hasText: 'DEMO_A' }).click()
  await choose(page, 'User B', 'DEMO_B')
  await expect(
    page.getByRole('table', { name: 'User comparison evidence' }),
  ).toContainText('ZC:ONLY_A')
  await expect(
    page.getByText(
      'Multiple source identities; inspect User Details before interpreting this account.',
      { exact: true },
    ),
  ).toBeVisible()
})

test('comparison metrics filter results, sorting persists and inline evidence preserves intervals', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await comparison(page)
  await choose(page, 'User A', 'DEMO_A')
  await choose(page, 'User B', 'DEMO_B')
  const summary = page.getByLabel('Comparison summary', { exact: true })
  await summary.getByRole('button', { name: /Shared roles/ }).click()
  await expect(summary.getByRole('button',{name:/^Shared roles/})).toHaveAttribute('aria-pressed','true')
  const table = page.getByRole('table', {
    name: 'User comparison evidence',
    exact: true,
  })
  await expect(table.locator('tbody>tr')).toHaveCount(1)
  await page
    .getByRole('button', { name: 'Clear comparison difference', exact: true })
    .click()
  await expect(table.locator('tbody>tr')).toHaveCount(2)
  await page.getByLabel('Sort comparison', { exact: true }).selectOption('a')
  await page.getByLabel('Descending', { exact: true }).check()
  await expect(table.locator('tbody>tr').first()).toContainText('ZC:SHARED:ENP')
  const evidence = page.getByRole('cell', {
    name: 'User A evidence for ZC:SHARED:ENP',
    exact: true,
  })
  await expect(evidence).toBeVisible()
  await expect(table.getByRole('columnheader')).toHaveText(['Role / Transaction','Difference','User A Evidence','User B Evidence'])
  await expect(table.locator('details')).toHaveCount(0)
  await expectIntervals(page,evidence,['01.01.2000 → 31.12.9999','01.01.2001 → 31.12.9999'])
  await page.getByRole('button', { name: 'Open User A', exact: true }).click()
  await page.goBack()
  await expect(page.getByLabel('Sort comparison', { exact: true })).toHaveValue(
    'a',
  )
  await expect(
    page.getByLabel('Descending', { exact: true }),
  ).toBeChecked()
  await openSaved(page, 'comparison')
  const menu = saved(page, 'comparison')
  await menu
    .getByLabel('Saved filter name', { exact: true })
    .fill('Evidence count order')
  await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(menu).toContainText('Saved filters updated.')
  await page.keyboard.press('Escape')
  await page
    .getByLabel('Sort comparison', { exact: true })
    .selectOption('identifier')
  await page.getByLabel('Descending', { exact: true }).uncheck()
  await openSaved(page, 'comparison')
  await expect(menu.getByRole('combobox',{name:'Saved filter',exact:true})).toHaveAttribute('aria-expanded','false')
  await expect(menu.getByRole('button',{name:'Clear filters',exact:true})).toBeVisible()
  await expect(page.getByRole('region',{name:'Comparison filters',exact:true}).getByRole('button',{name:'Clear filters',exact:true})).toHaveCount(1)
  await menu.getByRole('button', { name: 'Load', exact: true }).click()
  await expect(page.getByLabel('Sort comparison', { exact: true })).toHaveValue(
    'a',
  )
  await expect(
    page.getByLabel('Descending', { exact: true }),
  ).toBeChecked()
  await expect(menu).toContainText('Saved filter applied to the current data.')
  await page.keyboard.press('Escape')
  await expect(
    page.getByRole('button', { name: /Saved filters · Evidence count order/ }),
  ).not.toContainText('Modified')
})

test('same user is excluded and no-assignment user has an honest empty state', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await comparison(page)
  await choose(page, 'User A', 'DEMO_A')
  await page
    .getByRole('combobox', { name: 'User B', exact: true })
    .fill('DEMO_A')
  await expect(
    page.getByRole('option').filter({ hasText: 'DEMO_A' }),
  ).toHaveCount(0)
  await page.keyboard.press('Escape')
  await choose(page, 'User B', 'DEMO_EMPTY')
  await page.getByLabel('Comparison summary',{exact:true}).getByRole('button',{name:/^(Only User B|Mapped transactions only B)/}).click()
  await expect(
    page.getByText('No matching roles.', { exact: false }),
  ).toBeVisible()
})
test('saved filters save load rename update delete and survive page reload', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  const viewForBar = 'users'
  const bar = saved(page, 'users')
  await page.getByLabel('Search users', { exact: true }).fill('Alpha')
  await openSaved(page, viewForBar)
  await bar.getByLabel('Saved filter name').fill('Alpha users')
  await bar.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(
    page.locator('div.saved-filter-toolbar[aria-label="users saved filters"]'),
  ).toContainText('Alpha users')
  await page.getByLabel('Search users', { exact: true }).fill('Beta')
  await expect(
    page.locator('div.saved-filter-toolbar[aria-label="users saved filters"]'),
  ).toContainText('Modified')
  await openSaved(page, viewForBar)
  await bar.getByRole('button', { name: 'Load', exact: true }).click()
  await expect(page.getByLabel('Search users', { exact: true })).toHaveValue(
    'Alpha',
  )
  await openSaved(page, viewForBar)
  await bar.getByLabel('Saved filter name').fill('Renamed')
  await bar.getByRole('button', { name: 'Rename', exact: true }).click()
  await expect(
    bar.getByRole('combobox', { name: 'Saved filter', exact: true }),
  ).toHaveValue('Renamed')
  await page.getByLabel('Search users', { exact: true }).fill('Beta')
  await openSaved(page, viewForBar)
  await bar
    .getByRole('button', { name: 'Update saved filter', exact: true })
    .click()
  await expect(bar).toContainText('Saved filters updated.')
  await page.reload()
  await openSaved(page, viewForBar)
  await openSaved(page, viewForBar)
  await choose(page, 'Saved filter', 'Renamed')
  await openSaved(page, viewForBar)
  await bar.getByRole('button', { name: 'Load', exact: true }).click()
  await expect(page.getByLabel('Search users', { exact: true })).toHaveValue(
    'Beta',
  )
  await goTo(page, 'Role Lookup')
  await openSaved(page, 'roles')
  await expect(
    saved(page, 'roles').getByRole('option', { name: 'Renamed', exact: true }),
  ).toHaveCount(0)
  await goTo(page, 'User Access')
  await openSaved(page, viewForBar)
  page.once('dialog', (d) => d.accept())
  await bar.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(
    bar.getByRole('option', { name: 'Renamed', exact: true }),
  ).toHaveCount(0)
})
test('unsupported saved values warn without overwriting original definition', async ({
  page,
  request,
}) => {
  const item = await request.post('/api/saved-filters', {
    headers,
    data: {
      name: 'Old sorting',
      view: 'users',
      filters: { search: 'Alpha', sort: 'removed-sort' },
    },
  })
  expect(item.ok()).toBeTruthy()
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  const viewForBar = 'users'
  const bar = saved(page, 'users')
  await openSaved(page, viewForBar)
  await choose(page, 'Saved filter', 'Old sorting')
  await openSaved(page, viewForBar)
  await bar.getByRole('button', { name: 'Load', exact: true }).click()
  await expect(bar).toContainText('unsupported fields or values')
  await expect(page.getByLabel('Search users', { exact: true })).toHaveValue(
    'Alpha',
  )
  await expect(page.getByLabel('Sort users', { exact: true })).toHaveValue(
    'username',
  )
  const persisted = (
    await (await request.get('/api/saved-filters', { headers })).json()
  ).items[0]
  expect(persisted.filters.sort).toBe('removed-sort')
})
test('Data Health coverage and drilldown navigate to existing records', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
  await expect(
    page.getByText('Data Health & Coverage', { exact: true }),
  ).toBeVisible()
  await page.getByText('Data Health & Coverage', { exact: true }).click()
  await expect(
    page.locator('li').filter({
      hasText: 'Business/release assignment records mapped to catalogue',
    }),
  ).toContainText('4 / 6 — 66.7%')
  await page
    .getByRole('button', { name: /Assigned roles absent from catalogue/ })
    .click()
  const drill = page.getByRole('region', {
    name: 'Data Health finding records',
  })
  await expect(drill).toContainText('ZC:OLD')
  await drill
    .getByRole('link', { name: 'DEMO_A', exact: true })
    .first()
    .click()
  await expect(
    page.getByRole('heading', { name: 'User details', exact: true }),
  ).toBeVisible()
})
test('Account Review retains stale filter and includes evidence versions in export', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  await mode(page, 'Account Review')
  await expect(
    page.getByText('Outdated reviews', { exact: true }),
  ).toBeVisible()
  await page
    .getByRole('button', { name: /^Outdated reviews/ })
    .click()
  await expect(page.getByRole('button', { name: 'Remove review finding filter', exact: true })).toBeVisible()
  await expect(page.getByLabel('Review finding', { exact: true })).toHaveValue(
    'stale',
  )
  const viewForBar = 'review'
  const bar = saved(page, 'review')
  await openSaved(page, viewForBar)
  await bar.getByLabel('Saved filter name').fill('Changed evidence')
  await bar.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(bar).toContainText('Saved filters updated.')
})
test('paged comparison evidence rejects a different source generation', async ({
  page,
  request,
}) => {
  const source = path.join(root, 'users.csv')
  let content = readFileSync(source, 'utf8')
  for (let year = 1970; year < 2000; year++)
    content += `DEMO_A,ZC:SHARED:ENP,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,${year}0101,99991231\n`
  writeFileSync(source, content)
  expect((await request.post('/api/refresh', { headers })).ok()).toBeTruthy()
  await page.goto('/#session=browser-test-session')
  await comparison(page)
  await choose(page, 'User A', 'DEMO_A')
  await choose(page, 'User B', 'DEMO_B')
  await page.route('**/api/user-comparison/evidence?*', async (route) => {
    const response = await route.fetch()
    await route.fulfill({
      json: { ...(await response.json()), data_revision: 'changed-generation' },
    })
  })
  await page
    .getByRole('navigation', {
      name: 'ZC:SHARED:ENP User A evidence',
      exact: true,
    })
    .getByRole('button', { name: 'Next', exact: true })
    .click()
  await expect(page.getByRole('alert')).toContainText(
    'Source changed. Refresh the comparison',
  )
})

test('transaction investigation and browser Back retain comparison users and filters', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await comparison(page)
  await choose(page, 'User A', 'DEMO_A')
  await choose(page, 'User B', 'DEMO_B')
  await page
    .getByLabel('Comparison section', { exact: true })
    .selectOption('transactions')
  await page.getByLabel('Comparison summary',{exact:true}).getByRole('button',{name:/^(Only User A|Mapped transactions only A)/}).click()
  await page.getByRole('button', { name: 'ME23N', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'User Access', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('group', { name: 'Filter users by transaction', exact: true }),
  ).toContainText('ME23N')
  await page.goBack()
  await expect(
    page.getByRole('heading', { name: 'Compare users', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('combobox', { name: 'User A', exact: true }),
  ).toHaveValue(/DEMO_A/)
  await expect(
    page.getByRole('combobox', { name: 'User B', exact: true }),
  ).toHaveValue(/DEMO_B/)
  await expect(page.getByLabel('Comparison summary',{exact:true}).getByRole('button',{name:/^(Only User A|Mapped transactions only A)/})).toHaveAttribute('aria-pressed','true')
  await expect(
    page.getByLabel('Comparison section', { exact: true }),
  ).toHaveValue('transactions')
})

test('leaving comparison cancels a pending CSV before the native save dialog', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await comparison(page)
  await choose(page, 'User A', 'DEMO_A')
  await choose(page, 'User B', 'DEMO_B')
  await page.evaluate(() => {
    ;(window as any).exportCalls = 0
    ;(window as any).pywebview = {
      api: {
        save_user_access_csv: async () => {
          ;(window as any).exportCalls++
          return true
        },
      },
    }
  })
  let release!: () => void, started!: () => void
  const gate = new Promise<void>((resolve) => {
      release = resolve
    }),
    requested = new Promise<void>((resolve) => {
      started = resolve
    })
  await page.route('**/api/user-comparison/evidence?*', async (route) => {
    const response = await route.fetch()
    started()
    await gate
    await route.fulfill({ response })
  })
  await page
    .getByRole('button', { name: 'Export comparison CSV', exact: true })
    .click()
  await requested
  await mode(page, 'User directory')
  const response = page.waitForResponse((r) =>
    r.url().includes('/api/user-comparison/evidence?'),
  )
  release()
  await response
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  )
  expect(await page.evaluate(() => (window as any).exportCalls)).toBe(0)
})

test('comparison export uses guarded native bridge and retains distinct assignment intervals', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await comparison(page)
  await choose(page, 'User A', 'DEMO_A')
  await choose(page, 'User B', 'DEMO_B')
  await page.evaluate(() => {
    ;(window as any).comparisonExport = null
    ;(window as any).pywebview = {
      api: {
        save_user_access_csv: async (
          token: string,
          filename: string,
          content: string,
        ) => {
          ;(window as any).comparisonExport = { token, filename, content }
          return true
        },
      },
    }
  })
  await page
    .getByRole('button', { name: 'Export comparison CSV', exact: true })
    .click()
  await expect(
    page.getByText('Comparison CSV saved.', { exact: true }),
  ).toBeVisible()
  const exported = await page.evaluate(() => (window as any).comparisonExport)
  expect(exported.token).toBe('browser-test-session')
  expect(exported.filename).toMatch(
    /^sap-lens-user-comparison-review-\d{4}-\d{2}-\d{2}\.csv$/,
  )
  expect(exported.content).toContain('"2000-01-01"')
  expect(exported.content).toContain('"2001-01-01"')
  expect(exported.content).toContain('"shared"')
  expect(exported.content).toContain('"User group"')
  expect(exported.content).toContain('"Validity view"')
})
test('Role Lookup saved filters restore multi-transaction and sorting controls', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Role Lookup')
  const viewForBar = 'roles'
  const bar = saved(page, 'roles'),
    transaction = page.getByRole('textbox', {
      name: 'Filter catalogue by transaction',
      exact: true,
    })
  await transaction.fill('FB03')
  await transaction.press('Enter')
  await transaction.fill('ME23N')
  await transaction.press('Enter')
  await openSaved(page, viewForBar)
  await bar.getByLabel('Saved filter name').fill('Catalogue investigation')
  await bar.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(bar).toContainText('Saved filters updated.')
  await page
    .getByRole('button', { name: 'Clear all filters', exact: true })
    .click()
  await transaction.fill('OTHER')
  await openSaved(page, viewForBar)
  await choose(page, 'Saved filter', 'Catalogue investigation')
  await openSaved(page, viewForBar)
  await bar.getByRole('button', { name: 'Load', exact: true }).click()
  await expect(bar).toContainText('Saved filter applied to the current data.')
  await expect(transaction).toHaveValue('')
  await expect(
    page.getByRole('button', { name: 'Remove transaction FB03', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Remove transaction ME23N', exact: true }),
  ).toBeVisible()
})
test('future saved schema remains unavailable without crashing or replacing stored state', async ({
  page,
}) => {
  await page.route('**/api/saved-filters', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      json: {
        items: [
          {
            id: 'future',
            name: 'Future investigation',
            view: 'users',
            filter_schema: 9,
            filters: { newOption: 'value' },
            created: '2026-01-01',
            modified: '2026-01-01',
          },
        ],
      },
    })
  })
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  const viewForBar = 'users'
  const bar = saved(page, 'users')
  await openSaved(page, viewForBar)
  await choose(page,'Saved filter','Future investigation')
  await openSaved(page, viewForBar)
  await bar.getByRole('button', { name: 'Load', exact: true }).click()
  await expect(bar).toContainText('unsupported schema')
  await expect(page.getByLabel('Search users', { exact: true })).toHaveValue('')
})

for (const theme of ['light', 'dark'])
  for (const width of [375, 800, 1280])
    test(`investigation tools visual ${theme} ${width}`, async ({
      page,
      request,
    }, info) => {
      await page.setViewportSize({ width, height: 900 })
      const settings = (
        await (await request.get('/api/configuration', { headers })).json()
      ).settings
      settings.theme = theme
      expect(
        (
          await request.post('/api/configuration', { headers, data: settings })
        ).ok(),
      ).toBeTruthy()
      await page.goto('/#session=browser-test-session')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await comparison(page)
      await choose(page, 'User A', 'DEMO_A')
      await choose(page, 'User B', 'DEMO_B')
      await expect(
        page.getByRole('table', { name: 'User comparison evidence' }),
      ).toContainText('ZC:ONLY_A')
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      ).toBeTruthy()
      await page.screenshot({
        path: info.outputPath('comparison.png'),
        fullPage: true,
      })
      await page
        .getByRole('button', { name: 'Open settings', exact: true })
        .click()
      await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
      await expect(
        page.getByText('Data Health & Coverage', { exact: true }),
      ).toBeVisible()
      await page.getByText('Data Health & Coverage', { exact: true }).click()
      await page.screenshot({ path: info.outputPath('data-health.png') })
      await page
        .getByText('Business/release assignment records mapped to catalogue', {
          exact: true,
        })
        .scrollIntoViewIfNeeded()
      await page.screenshot({
        path: info.outputPath('data-health-findings.png'),
      })
    })


test('directory role description selection and removable chips preserve unrelated controls', async ({page}) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page,'User Access')
  await page.getByLabel('Search users',{exact:true}).fill('DEMO_')
  await page.getByLabel('Sort users',{exact:true}).selectOption('email')
  const role = page.getByRole('combobox',{name:'Filter users by role',exact:true})
  await role.fill('Materials')
  await page.getByRole('option').filter({hasText:'ZC:ONLY_A'}).click()
  await expect(page.getByRole('link', { name: 'DEMO_A',exact:true})).toBeVisible()
  await expect(page.getByRole('link', { name: 'DEMO_B',exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'Remove role filter',exact:true}).click()
  await expect(page.getByRole('link', { name: 'DEMO_B',exact:true})).toBeVisible()
  await expect(page.getByLabel('Search users',{exact:true})).toHaveValue('DEMO_')
  await expect(page.getByLabel('Sort users',{exact:true})).toHaveValue('email')
  await page.getByRole('button',{name:'Clear filters',exact:true}).click()
  await expect(page.getByLabel('Search users',{exact:true})).toHaveValue('')
  await expect(page.getByLabel('Sort users',{exact:true})).toHaveValue('username')
})
