import { test, expect, type Page } from '@playwright/test'
import {
  mkdtempSync,
  writeFileSync,
  rmSync,
  readFileSync,
  unlinkSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { headers, goTo } from './support'
const fields =
  'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'.split(
    ';',
  )
let root: string, source: string
const current = async (request: any) =>
  (await (await request.get('/api/configuration', { headers })).json()).settings
async function review(page: Page) {
  await goTo(page, 'User Access')
  await page
    .getByRole('navigation', { name: 'User Access view', exact: true })
    .getByRole('link', { name: 'Account Review', exact: true })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Account Review', exact: true }),
  ).toBeVisible()
}
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  root = mkdtempSync(path.join(tmpdir(), 'sap-lens-review-'))
  source = path.join(root, 'directory.csv')
  const rows = [
    {
      Name: 'SURNAME Demo',
      Mail: 'open@example.test',
      Title: 'Analyst',
      Department: 'Engineering',
      Enabled: 'false',
      ManagerName: 'MANAGER Demo',
      ManagerMail: 'manager@example.test',
      ManagerTitle: 'Lead',
    },
    { Name: 'Demo Locked', Mail: 'locked@example.test', Enabled: 'false' },
    { Name: 'MANAGER Demo', Mail: 'manager@example.test', Enabled: 'true' },
  ]
  writeFileSync(
    source,
    fields.join(';') +
      '\n' +
      rows
        .map((row) =>
          fields.map((f) => (row as Record<string, string>)[f] || '').join(';'),
        )
        .join('\n'),
  )
  const users = path.join(root, 'users.csv')
  writeFileSync(
    users,
    'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,USER_TYPE,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_OPEN,ZC:FI:VIEW,UNLICENSED,SAP,Open,open@example.test,20000101,99991231,0,A,20000101,99991231\nDEMO_LOCKED,,DIALOG,Demo,Locked,locked@example.test,20000101,99991231,1,A,,\nSAP_MANAGER,,DIALOG,SAP,Manager,manager@example.test,20000101,99991231,0,A,,\nDEMO_UNKNOWN,,DIALOG,Demo,Unknown,,20000101,99991231,,S,,\n',
  )
  const settings = await current(request)
  settings.data_csv_path = path.resolve('tests/fixtures/synthetic.csv')
  settings.user_csv_path = users
  settings.features.employee_directory = true
  expect(
    (
      await request.post('/api/configuration', { headers, data: settings })
    ).ok(),
  ).toBeTruthy()
  const revision = (await current(request)).revision,
    preview = await request.post('/api/employees/preview', {
      headers,
      data: { revision, path: source },
    })
  expect(preview.ok()).toBeTruthy()
  expect(
    (
      await request.post('/api/employees/import', {
        headers,
        data: { revision, path: source, digest: (await preview.json()).digest },
      })
    ).ok(),
  ).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(root, { recursive: true, force: true })
})

test('profile header, status pills, mismatch warning and manager card keep SAP identity authoritative', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  await page.getByRole('link', { name: 'DEMO_OPEN', exact: true }).click()
  const profile = page.getByRole('region', {
      name: 'User profile',
      exact: true,
    }),
    header = profile.locator('.profile-identity-header')
  await expect(header).toContainText('SAP Open')
  await expect(header).toContainText('open@example.test')
  await expect(header).not.toContainText('Analyst')
  const identity = profile.getByRole('region', {
    name: 'SAP Identity',
    exact: true,
  })
  await expect(identity).toContainText('A · Dialog')
  await expect(identity).not.toContainText('open@example.test')
  const account = profile.getByRole('region', {
    name: 'Account Status',
    exact: true,
  })
  for (const value of ['Valid', 'Unlocked', 'Disabled'])
    await expect(account.getByText(value, { exact: true })).toBeVisible()
  await expect(profile.locator('.profile-account-warning')).toContainText(
    'Account mismatch detected',
  )
  await expect(profile.getByRole('region',{name:'Organization',exact:true})).not.toContainText('AD username')
  await expect(profile).not.toContainText('Site')
  const manager = profile.getByRole('link', {
    name: 'View SAP user',
    exact: true,
  })
  await expect(manager).toContainText('SAP Manager')
  await manager.click()
  await expect(
    page.getByRole('region', { name: 'SAP Identity', exact: true }),
  ).toContainText('SAP_MANAGER')
  await expect(
    page.getByText('Account mismatch detected', { exact: false }),
  ).toHaveCount(0)
  await page.goBack()
  await expect(
    page.getByRole('region', { name: 'SAP Identity', exact: true }),
  ).toContainText('DEMO_OPEN')
})

test('review findings, license filter, local decision persistence and spreadsheet-safe export', { tag: '@smoke' }, async ({
  page,
  request,
}) => {
  await page.goto('/#session=browser-test-session')
  await page.evaluate(() => {
    const state = {
      ...history.state,
      sapLensView: {
        ...history.state.sapLensView,
        userContext: { role: 'ZC:FI:VIEW' },
      },
    }
    history.replaceState(state, '')
    window.dispatchEvent(new PopStateEvent('popstate', { state }))
  })
  await review(page)
  await page
    .getByLabel('Review finding', { exact: true })
    .selectOption('ad_disabled_open')
  const table = page.getByRole('region', {
    name: 'Account review results',
    exact: true,
  })
  await expect(table.getByRole('row')).toHaveCount(2)
  await expect(table).toContainText('DEMO_OPEN')
  await expect(table).toContainText('Configured unlicensed group')
  await page
    .getByLabel('License group classification', { exact: true })
    .selectOption('exclude')
  await expect(
    page.getByText('No accounts match these review filters.', { exact: true }),
  ).toBeVisible()
  await page
    .getByLabel('License group classification', { exact: true })
    .selectOption('classified')
  await table
    .getByRole('button', {
      name: /^(Needs review|Investigating)$/,
      exact: true,
    })
    .click()
  await expect(page.getByRole('dialog',{name:/^Review account ·/})).toBeFocused()
  await page.getByLabel('Reviewer', { exact: true }).fill('Synthetic Reviewer')
  await page
    .getByLabel('Decision', { exact: true })
    .selectOption('Investigating')
  await page.getByLabel('Rationale', { exact: true }).fill('=Synthetic note')
  await page
    .getByRole('button', { name: 'Save review decision', exact: true })
    .click()
  await expect(
    page.getByText('Review decision saved locally.', { exact: true }),
  ).toBeVisible()
  await expect(
    table.getByRole('button', { name: 'Investigating', exact: true }),
  ).toBeFocused()
  await page.reload()
  await expect(
    page.getByRole('region', { name: 'Account Review', exact: true }),
  ).toBeVisible()
  await expect(
    table.getByRole('button', { name: 'Investigating', exact: true }),
  ).toBeVisible()
  await page
    .getByLabel('License group classification', { exact: true })
    .selectOption('classified')
  await page
    .getByLabel('Sort account reviews', { exact: true })
    .selectOption('ad_status')
  await page.getByLabel('Descending', { exact: true }).check()
  const download = page.waitForEvent('download')
  await page
    .getByRole('button', { name: 'Export review CSV', exact: true })
    .click()
  const file = await download
  const text = readFileSync((await file.path())!, 'utf8')
  expect(text).toContain('DEMO_OPEN')
  expect(text).toContain("'=Synthetic note")
  expect(text).not.toContain('DEMO_LOCKED')
  await page.evaluate(() => {
    ;(window as any).nativeReview = null
    ;(window as any).pywebview = {
      api: {
        save_user_access_csv: async (
          token: string,
          filename: string,
          content: string,
        ) => {
          ;(window as any).nativeReview = { token, filename, content }
          return true
        },
      },
    }
  })
  await page
    .getByRole('button', { name: 'Export review CSV', exact: true })
    .click()
  await expect(
    page.getByText('Review CSV saved.', { exact: true }),
  ).toBeVisible()
  const native = await page.evaluate(() => (window as any).nativeReview)
  expect(native.token).toBe('browser-test-session')
  expect(native.filename).toMatch(
    /^sap-lens-account-review-review-\d{4}-\d{2}-\d{2}\.csv$/,
  )
  expect(native.content).toContain('DEMO_OPEN')
  await table.getByRole('link', { name: 'DEMO_OPEN', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'SAP Identity', exact: true }),
  ).toContainText('DEMO_OPEN')
  await page.getByRole('link', { name: 'View SAP user', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'SAP Identity', exact: true }),
  ).toContainText('SAP_MANAGER')
  await page.goBack()
  await expect(
    page.getByRole('region', { name: 'SAP Identity', exact: true }),
  ).toContainText('DEMO_OPEN')
  await page.goBack()
  await expect(page.getByLabel('Review finding', { exact: true })).toHaveValue(
    'ad_disabled_open',
  )
  await expect(
    page.getByLabel('License group classification', { exact: true }),
  ).toHaveValue('classified')
  await expect(
    page.getByLabel('Sort account reviews', { exact: true }),
  ).toHaveValue('ad_status')
  await expect(page.getByLabel('Descending', { exact: true })).toBeChecked()
  const revision = (
    await (await request.get('/api/account-review', { headers })).json()
  ).data_revision
  expect(revision).toMatch(/^[a-f0-9]{64}$/)
})

test('Dashboard coverage and account-review KPI open supported evidence filters', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await expect(
    page
      .getByRole('region', { name: 'SAP Overview', exact: true })
      .getByRole('button'),
  ).toHaveCount(4)
  expect(
    await page
      .getByRole('region', { name: 'SAP Overview', exact: true })
      .getByRole('button')
      .evaluateAll((items) => items.map((el) => el.getAttribute('aria-label'))),
  ).toEqual([
    'SAP users',
    'Catalogue roles',
    'Release roles',
    'Role/T-code mappings',
  ])
  await expect(
    page.getByRole('button', {
      name: 'Matched SAP identities',
      exact: true,
    }),
  ).toContainText('75.0%')
  await page
    .getByRole('button', {
      name: 'Missing or ambiguous directory matches',
      exact: true,
    })
    .click()
  await expect(page.getByLabel('Review finding', { exact: true })).toHaveValue(
    'directory_match',
  )
  await expect(
    page.getByRole('region', { name: 'Account review results', exact: true }),
  ).toContainText('DEMO_UNKNOWN')
  await page.goBack()
  await page
    .getByRole('button', { name: 'Accounts requiring review', exact: true })
    .click()
  await expect(page.getByLabel('Review finding', { exact: true })).toHaveValue(
    'any',
  )
})

test('floating Norwegian calendar stays outside layout, handles maximum dates, Escape and outside click', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Release Roles')
  const filters = page.locator('.release-filters')
  await expect(
    filters.getByLabel('Sort release roles', { exact: true }),
  ).toBeVisible()
  await expect(
    filters.getByRole('button', {
      name: 'Assignment date filters',
      exact: true,
    }),
  ).toHaveCount(1)
  await page
    .getByRole('button', { name: 'Assignment date filters', exact: true })
    .click()
  await page.getByText('Advanced interval filtering', { exact: true }).click()
  await page.getByLabel('End date to', { exact: true }).fill('31.12.9999')
  const panel = page.getByRole('group', {
      name: 'Assignment date controls',
      exact: true,
    }),
    before = await panel.evaluate((el) => ({
      height: el.getBoundingClientRect().height,
      width: el.getBoundingClientRect().width,
      top: (el as HTMLElement).offsetTop,
    }))
  const choose = page.getByRole('button', {
    name: 'Choose End date to',
    exact: true,
  })
  await choose.click()
  const calendar = page.getByRole('dialog', {
    name: 'Calendar for End date to',
    exact: true,
  })
  await expect(calendar).toBeVisible()
  await expect(calendar).toContainText('desember 9999')
  expect(
    await panel.evaluate((el) => ({
      height: el.getBoundingClientRect().height,
      width: el.getBoundingClientRect().width,
      top: (el as HTMLElement).offsetTop,
    })),
  ).toEqual(before)
  expect(
    await calendar.evaluate((el) => el.parentElement === document.body),
  ).toBe(true)
  await expect(
    calendar.getByRole('button', { name: 'Next month', exact: true }),
  ).toBeDisabled()
  await calendar
    .getByRole('button', { name: '31.12.9999', exact: true })
    .press('ArrowRight')
  await expect(
    calendar.getByRole('button', { name: '31.12.9999', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(calendar).toHaveCount(0)
  await expect(choose).toBeFocused()
  await choose.click()
  // The upward-positioned date panel can cover the page heading. Use a point
  // in the navbar that is outside both floating panels, without force-clicking.
  const bannerBox = (await page.getByRole('banner').boundingBox())!
  const panelBox = (await page.getByRole('dialog',{name:'Assignment date controls',exact:true}).boundingBox())!
  expect(bannerBox.y + 2).toBeLessThan(panelBox.y)
  await page.getByRole('banner').click({position:{x:2,y:2}})
  await expect(calendar).toHaveCount(0)
  // Outside dismissal cancels the staged dates. Reopen and apply explicitly.
  await page.getByRole('button',{name:'Assignment date filters',exact:true}).click()
  await page.getByText('Advanced interval filtering',{exact:true}).click()
  await page.getByLabel('End date to',{exact:true}).fill('31.12.9999')
  await page
    .getByRole('button', { name: 'Apply date filters', exact: true })
    .click()
  await expect(
    page.getByLabel('Active assignment date filters', { exact: true }),
  ).toContainText('31.12.9999')
  await page
    .getByRole('button', { name: 'Remove End date to filter', exact: true })
    .click()
  await expect(
    page.getByLabel('Active assignment date filters', { exact: true }),
  ).toHaveCount(0)
})

test('source snapshot recovery persists records after removal and reload with concise diagnostics', async ({
  page,
  request,
}) => {
  // Deliberately create legacy path-only settings using the existing configuration workflow.
  const settings = await current(request)
  settings.employee_snapshot_id = null
  expect(
    (
      await request.post('/api/configuration', { headers, data: settings })
    ).ok(),
  ).toBeTruthy()
  await request.get('/api/employees/status', { headers })
  unlinkSync(source)
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
  await page
    .getByRole('tab', { name: 'Employee Directory', exact: true })
    .click()
  await page
    .getByRole('button', {
      name: 'Save durable directory snapshot',
      exact: true,
    })
    .click()
  await expect(
    page.getByText('Validated directory records saved locally.', {
      exact: false,
    }),
  ).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click()
  await page
    .getByRole('tab', { name: 'Employee Directory', exact: true })
    .click()
  await expect(
    page.getByRole('region', { name: 'Directory import status', exact: true }),
  ).toContainText('Records saved locally')
  await page
    .getByRole('tab', { name: 'Health & Diagnostics', exact: true })
    .click()
  const directorySource = page.getByRole('region', { name: 'Employee Directory CSV', exact: true })
  await directorySource.getByRole('button', { name: 'Technical source details', exact: true }).click()
  const sourceDetails = page.getByRole('dialog', { name: 'Employee Directory CSV technical details', exact: true })
  await expect(sourceDetails).toBeVisible()
  await expect(sourceDetails.getByText('Configured file', { exact: true })).toBeVisible()
  await expect(sourceDetails.getByRole('region', { name: 'Employee Directory diagnostics', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(sourceDetails).toHaveCount(0)
  await page.getByRole('tab', { name: 'About SAP Lens', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'About SAP Lens', exact: true }),
  ).toContainText('Application version')
})

for (const theme of ['light', 'dark'])
  for (const width of [375, 800, 1280])
    test(`operational review visual QA ${theme} ${width}`, async ({
      page,
      request,
    }, info) => {
      const settings = await current(request)
      settings.theme = theme
      await request.post('/api/configuration', { headers, data: settings })
      await page.setViewportSize({ width, height: 1000 })
      await page.goto('/#session=browser-test-session')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      const shot = async (name: string) => {
        await page.evaluate(() => window.scrollTo(0, 0))
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true)
        await page.screenshot({
          path: info.outputPath(`${name}.png`),
          fullPage: true,
          animations: 'disabled',
        })
      }
      await expect(
        page.getByRole('button', {
          name: 'Matched SAP identities',
          exact: true,
        }),
      ).toBeVisible()
      await shot('dashboard')
      await review(page)
      await expect(
        page.getByRole('region', {
          name: 'Account review results',
          exact: true,
        }),
      ).toContainText('DEMO_OPEN')
      await expect(
        page.getByRole('combobox', { name: 'Review finding', exact: true }),
      ).toHaveCSS(
        'background-color',
        await page
          .getByLabel('Search account reviews', { exact: true })
          .evaluate((el) => getComputedStyle(el).backgroundColor),
      )
      await shot('account-review')
      await page
        .getByRole('region', { name: 'Account review results', exact: true })
        .getByRole('link', { name: 'DEMO_OPEN', exact: true })
        .click()
      await expect(
        page.getByRole('region', { name: 'User profile', exact: true }),
      ).toContainText('Analyst')
      await shot('unified-profile')
      await goTo(page, 'Release Roles')
      await shot('release-compact')
      await page
        .getByRole('button', { name: 'Assignment date filters', exact: true })
        .click()
      await page
        .getByText('Advanced interval filtering', { exact: true })
        .click()
      const choose = page.getByRole('button', {
        name: 'Choose Start date from',
        exact: true,
      })
      await choose.click()
      const calendar = page.getByRole('dialog', {
        name: 'Calendar for Start date from',
        exact: true,
      })
      await expect(calendar).toBeVisible()
      const box = (await calendar.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      expect(box.y).toBeGreaterThanOrEqual(0)
      expect(box.y + box.height).toBeLessThanOrEqual(1000)
      await page.screenshot({
        path: info.outputPath('floating-calendar.png'),
        animations: 'disabled',
      })
      await page.keyboard.press('Escape')
      await page
        .getByRole('button', { name: 'Open settings', exact: true })
        .click()
      await page
        .getByRole('tab', { name: 'Health & Diagnostics', exact: true })
        .click()
      await shot('health-settings')
    })

test('unlicensed group policy can be edited, cleared and reloaded without suppressing security findings', async ({
  page,
  request,
}) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Features', exact: true }).click()
  await page
    .getByLabel('Unlicensed SAP User Groups', { exact: false })
    .fill('EXEMPT, TECH REVIEW')
  await page
    .getByRole('button', { name: 'Apply settings', exact: true })
    .click()
  expect((await current(request)).unlicensed_user_groups).toEqual([
    'EXEMPT',
    'TECH REVIEW',
  ])
  await page.reload()
  await review(page)
  await page
    .getByLabel('Review finding', { exact: true })
    .selectOption('ad_disabled_open')
  await expect(
    page.getByRole('region', { name: 'Account review results', exact: true }),
  ).toContainText('DEMO_OPEN')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Features', exact: true }).click()
  await expect(
    page.getByLabel('Unlicensed SAP User Groups', { exact: false }),
  ).toHaveValue('EXEMPT, TECH REVIEW')
  await page.getByLabel('Unlicensed SAP User Groups', { exact: false }).fill('')
  await page
    .getByRole('button', { name: 'Apply settings', exact: true })
    .click()
  expect((await current(request)).unlicensed_user_groups).toEqual([])
})

test('calendar reopening restores the selected day and Back dismisses its portal', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'Release Roles')
  await page
    .getByRole('button', { name: 'Assignment date filters', exact: true })
    .click()
  await page.getByText('Advanced interval filtering', { exact: true }).click()
  await page.getByLabel('Start date from', { exact: true }).fill('31.01.2024')
  const choose = page.getByRole('button', {
      name: 'Choose Start date from',
      exact: true,
    }),
    calendar = page.getByRole('dialog', {
      name: 'Calendar for Start date from',
      exact: true,
    })
  await choose.click()
  await expect(
    calendar.getByRole('button', { name: '31.01.2024', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('ArrowLeft')
  await expect(
    calendar.getByRole('button', { name: '30.01.2024', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('Escape')
  await choose.click()
  await expect(
    calendar.getByRole('button', { name: '31.01.2024', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect(
    calendar.getByRole('button', { name: '01.02.2024', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('Escape')
  await choose.click()
  await expect(
    calendar.getByRole('button', { name: '31.01.2024', exact: true }),
  ).toBeFocused()
  await page.goBack()
  await expect(
    page.getByRole('region', { name: 'Dashboard', exact: true }),
  ).toBeVisible()
  await expect(calendar).toHaveCount(0)
  await page.goForward()
  await expect(
    page.getByRole('heading', { name: 'Release Roles', exact: true }),
  ).toBeVisible()
  await expect(calendar).toHaveCount(0)
})

for(const theme of ['light','dark']) test(`directory conflict evidence identifies source records without selecting an identity ${theme}`,async({page,request},info)=>{
  const settings=await current(request);settings.theme=theme
  await request.post('/api/configuration',{headers,data:settings})
  const rows=[{Name:'Demo Conflict A',Mail:'open@example.test',SamAccountName:'DEMO_AD_A',Enabled:''},{Name:'Demo Conflict B',Mail:'open@example.test',SamAccountName:'DEMO_AD_B',Enabled:'false'}]
  writeFileSync(source,fields.join(';')+'\n'+rows.map(row=>fields.map(field=>(row as Record<string,string>)[field]||'').join(';')).join('\n'))
  const revision=(await current(request)).revision
  const preview=await request.post('/api/employees/preview',{headers,data:{revision,path:source}})
  expect(preview.ok()).toBeTruthy()
  expect((await request.post('/api/employees/import',{headers,data:{revision,path:source,digest:(await preview.json()).digest}})).ok()).toBeTruthy()
  await page.setViewportSize({width:800,height:1000})
  await page.goto('/#session=browser-test-session');await goTo(page,'User Access')
  await page.getByRole('link', { name: 'DEMO_OPEN',exact:true}).click()
  await page.getByRole('button',{name:'Directory matching details · Ambiguous',exact:true}).click()
  const details=page.getByRole('dialog',{name:'Directory matching details',exact:true})
  await expect(details).toContainText('No candidate is selected')
  await expect(details).toContainText('User Access CSV')
  await expect(details).toContainText('directory.csv')
  await expect(details).toContainText('not physical CSV line numbers')
  const table=details.getByRole('table',{name:'Directory matching source records',exact:true})
  await expect(table.getByRole('row')).toHaveCount(3)
  await expect(table).toContainText('DEMO_AD_A');await expect(table).toContainText('DEMO_AD_B')
  await expect(table.getByRole('cell',{name:'Unknown',exact:true})).toHaveCount(1)
  await expect(page.locator('.profile-account-warning')).toHaveCount(0)
  await details.scrollIntoViewIfNeeded()
  await page.screenshot({path:info.outputPath('matching-evidence.png')})
  await details.getByRole('button',{name:'Inspect Employee Directory source',exact:true}).click()
  await expect(page.getByRole('tab',{name:'Employee Directory',exact:true})).toHaveAttribute('aria-selected','true')
})
