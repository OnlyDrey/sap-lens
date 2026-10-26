import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
let directory: string
async function library(page: Page) {
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page
    .getByRole('tab', { name: 'Component Library', exact: true })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Component Library', exact: true }),
  ).toBeVisible()
}
async function nav(page: Page, name: string) {
  await page
    .getByRole('navigation', { name: 'Main navigation', exact: true })
    .getByRole('button', { name, exact: true })
    .click()
}
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-design-'))
  const users = path.join(directory, 'users.csv')
  writeFileSync(
    users,
    'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,USER_TYPE,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_A,ZC:FI:VIEW,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20000101,99991231\nDEMO_B,ZC:FI:VIEW,DEMO,Beta,Example,b@example.test,20000101,99991231,0,A,20000101,99991231\n',
  )
  const settings = (
    await (await request.get('/api/configuration', { headers })).json()
  ).settings
  settings.data_csv_path = path.resolve('tests/fixtures/synthetic.csv')
  settings.user_csv_path = users
  expect(
    (
      await request.post('/api/configuration', { headers, data: settings })
    ).ok(),
  ).toBeTruthy()
  expect((await request.post('/api/refresh', { headers })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
})
test('compact navbar has labeled icon utilities, focus tooltips and refresh feedback without timestamps', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  const banner = page.getByRole('banner'),
    settings = banner.getByRole('button', {
      name: 'Open settings',
      exact: true,
    })
  await expect(banner.getByText(/Updated /)).toHaveCount(0)
  await expect(settings).toHaveText('')
  await settings.focus()
  await expect(
    banner.getByRole('tooltip', { name: 'Settings', exact: true }),
  ).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(
    banner.getByRole('tooltip', { name: 'Settings', exact: true }),
  ).toBeHidden()
  const theme = banner.getByRole('button', {
    name: /Switch to (light|dark) mode/,
  })
  await expect(theme).toHaveText('')
  expect(await theme.evaluate((el) => getComputedStyle(el).minHeight)).toBe(
    '42px',
  )
  await banner
    .getByRole('button', { name: 'Refresh role data from CSV', exact: true })
    .click()
  await expect(
    page.getByText('All data is up to date', { exact: true }),
  ).toBeVisible()
  await nav(page, 'Dashboard')
  await expect(
    page.getByText('Last successful refresh:', { exact: false }),
  ).toBeVisible()
})
test('secondary navigation uses actual routes, preserves query strings and supports reload and Back', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'User Access')
  const secondary = page.getByRole('navigation', {
    name: 'User Access view',
    exact: true,
  })
  await secondary
    .getByRole('link', { name: 'Account Review', exact: true })
    .click()
  await expect(page).toHaveURL(/#\/user-access\/account-review$/)
  await expect(
    secondary.getByRole('link', { name: 'Account Review', exact: true }),
  ).toHaveAttribute('aria-current', 'page')
  await page.reload()
  await expect(
    page.getByRole('heading', { name: 'Account Review', exact: true }),
  ).toBeVisible()
  await secondary
    .getByRole('link', { name: 'Compare users', exact: true })
    .click()
  await expect(page).toHaveURL(/#\/user-access\/compare$/)
  await page.goBack()
  await expect(
    page.getByRole('heading', { name: 'Account Review', exact: true }),
  ).toBeVisible()
  await page.goto('/#/user-access/compare?view=compact')
  await expect(
    page.getByRole('heading', { name: 'Compare users', exact: true }),
  ).toBeVisible()
  await secondary
    .getByRole('link', { name: 'User directory', exact: true })
    .click()
  await expect(page).toHaveURL(/#\/user-access\?view=compact$/)
})
test('Account Review keeps investigation controls across secondary navigation and Back', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'User Access')
  const secondary = page.getByRole('navigation', {
    name: 'User Access view',
    exact: true,
  })
  await secondary
    .getByRole('link', { name: 'Account Review', exact: true })
    .click()
  await page.getByLabel('Search account reviews', { exact: true }).fill('Alpha')
  await page
    .getByLabel('Sort account reviews', { exact: true })
    .selectOption('name')
  await secondary
    .getByRole('link', { name: 'User directory', exact: true })
    .click()
  await page.goBack()
  await expect(
    page.getByLabel('Search account reviews', { exact: true }),
  ).toHaveValue('Alpha')
  await expect(
    page.getByLabel('Sort account reviews', { exact: true }),
  ).toHaveValue('name')
  await nav(page, 'Dashboard')
  await page
    .getByRole('button', { name: 'Accounts requiring review', exact: true })
    .click()
  await expect(
    page.getByLabel('Search account reviews', { exact: true }),
  ).toHaveValue('')
  await expect(
    page.getByLabel('Sort account reviews', { exact: true }),
  ).toHaveValue('username')
  await page.goBack()
  await page.goBack()
  await expect(
    page.getByLabel('Search account reviews', { exact: true }),
  ).toHaveValue('Alpha')
})

test('role content tabs have keyboard semantics and associated assignment panel', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'User Access')
  await page.getByRole('button', { name: 'DEMO_A', exact: true }).click()
  const tabs = page.getByRole('tablist', {
    name: 'User role sections',
    exact: true,
  })
  await tabs.getByRole('tab', { name: 'All roles', exact: true }).focus()
  await page.keyboard.press('End')
  const release = tabs.getByRole('tab', {
    name: 'Release Roles — ZO:*',
    exact: true,
  })
  await expect(release).toBeFocused()
  await expect(release).toHaveAttribute('aria-selected', 'true')
  const id = await release.getAttribute('aria-controls')
  await expect(page.locator(`[id="${id}"]`)).toContainText(
    'No assignments in this section',
  )
  await page.keyboard.press('Home')
  await expect(
    tabs.getByRole('tab', { name: 'All roles', exact: true }),
  ).toHaveAttribute('aria-selected', 'true')
})
test('component library previews are isolated, interactive and use canonical components', async ({
  page,
  request,
}) => {
  await page.goto('/#session=browser-test-session')
  const before = (
    await (await request.get('/api/configuration', { headers })).json()
  ).settings
  const filtersBefore = await (
    await request.get('/api/saved-filters', { headers })
  ).json()
  const writes: string[] = []
  page.on('request', (r) => {
    if (r.method() === 'POST') writes.push(new URL(r.url()).pathname)
  })
  await library(page)
  const preview = page.getByLabel('Component Library previews', { exact: true })
  await expect(
    preview.getByRole('button', { name: 'Disabled', exact: true }),
  ).toBeDisabled()
  await expect(
    preview.getByRole('button', { name: 'Loading', exact: true }),
  ).toHaveAttribute('aria-busy', 'true')
  await preview
    .getByRole('button', { name: 'Simulate loading', exact: true })
    .click()
  await expect(
    preview.getByRole('button', { name: 'Simulate loading', exact: true }),
  ).toBeEnabled()
  await preview.getByLabel('Demo checkbox', { exact: true }).check()
  await preview
    .getByRole('switch', { name: 'Demo toggle', exact: true })
    .click()
  await preview
    .getByRole('button', { name: 'Toggle validation state', exact: true })
    .click()
  await expect(
    preview.getByRole('textbox', { name: 'Demo text', exact: true }),
  ).toHaveAttribute('aria-invalid', 'true')
  await preview.getByRole('tab', { name: /Business demo roles/ }).press('Enter')
  await expect(preview.getByRole('tabpanel')).toContainText('business')
  const popoverTrigger = preview.getByRole('button', {
    name: 'Open demo popover',
    exact: true,
  })
  await popoverTrigger.click()
  const popover = page.getByRole('dialog', {
    name: 'Demo popover',
    exact: true,
  })
  await expect(
    popover.getByRole('button', { name: 'Close demo popover', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(popover).toHaveCount(0)
  await expect(popoverTrigger).toBeFocused()
  const dialogTrigger = preview.getByRole('button', {
    name: 'Open demo dialog',
    exact: true,
  })
  await dialogTrigger.click()
  const demoDialog = page.getByRole('dialog', {
    name: 'Isolated component dialog',
    exact: true,
  })
  await expect(demoDialog).toBeFocused()
  await demoDialog
    .getByRole('textbox', { name: 'Demo dialog input', exact: true })
    .fill('Synthetic only')
  await page.keyboard.press('Escape')
  await expect(demoDialog).toHaveCount(0)
  await expect(dialogTrigger).toBeFocused()
  await preview
    .getByRole('button', { name: 'Saved filters', exact: true })
    .click()
  const menu = page.getByRole('dialog', {
    name: 'library saved filters',
    exact: true,
  })
  await menu
    .getByLabel('Saved filter name', { exact: true })
    .fill('Demo filter')
  await menu.getByRole('button', { name: 'Save as new', exact: true }).click()
  await expect(menu).toContainText('Saved filters updated.')
  await page.keyboard.press('Escape')
  await preview
    .getByRole('button', { name: 'Choose Demo date', exact: true })
    .click()
  await expect(
    page.getByRole('dialog', { name: 'Calendar for Demo date', exact: true }),
  ).toBeVisible()
  await page.keyboard.press('Escape')
  expect(writes).toEqual([])
  expect(
    (await (await request.get('/api/configuration', { headers })).json())
      .settings,
  ).toEqual(before)
  expect(
    await (await request.get('/api/saved-filters', { headers })).json(),
  ).toEqual(filtersBefore)
  await expect(
    page.getByRole('button', { name: 'Save and load CSV', exact: true }),
  ).toBeHidden()
})
test('saved filters portal handles keyboard, outside dismissal and neutral clear actions', async ({
  page,
}) => {
  await page.goto('/#session=browser-test-session')
  await nav(page, 'User Access')
  const bar = page.locator(
      'div.saved-filter-toolbar[aria-label="users saved filters"]',
    ),
    trigger = bar.getByRole('button', { name: 'Saved filters', exact: true })
  await expect(bar.getByLabel('Saved filter name')).toHaveCount(0)
  await trigger.click()
  const panel = page.getByRole('dialog', {
    name: 'users saved filters',
    exact: true,
  })
  expect(
    await panel.evaluate((el) => el.parentElement === document.body),
  ).toBeTruthy()
  await expect(panel.getByLabel('Saved filter', { exact: true })).toBeFocused()
  await expect(panel.getByLabel('Saved filter', { exact: true })).toHaveAttribute('aria-expanded','false')
  await page.keyboard.press('ArrowDown')
  await expect(panel.getByLabel('Saved filter', { exact: true })).toHaveAttribute('aria-expanded','true')
  await page.keyboard.press('Escape')
  await expect(panel).toBeVisible()
  await expect(panel.getByLabel('Saved filter', { exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await trigger.click()
  await page.getByRole('heading', { name: 'User Access', exact: true }).click()
  await expect(panel).toHaveCount(0)
  await trigger.click()
  const clear = panel.getByRole('button', {
    name: 'Clear filters',
    exact: true,
  })
  await clear.hover()
  const colors = await clear.evaluate((el) => ({
    color: getComputedStyle(el).color,
    error: getComputedStyle(document.documentElement)
      .getPropertyValue('--error')
      .trim(),
  }))
  expect(colors.color).not.toBe(colors.error)
})
for (const theme of ['light', 'dark'])
  for (const width of [375, 800, 1280])
    test(`canonical component visual contracts ${theme} ${width}`, async ({
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
      for (const button of await page
        .getByRole('navigation', { name: 'Main navigation', exact: true })
        .getByRole('button')
        .all())
        await expect(button.locator('span')).toBeVisible()
      await library(page)
      const preview = page.getByLabel('Component Library previews', {
          exact: true,
        }),
        buttons = preview.getByRole('button', {
          name: /^(Primary|Secondary|Outline|Ghost|Destructive)$/,
        })
      const heights = await buttons.evaluateAll((elements) =>
        elements.map((el) => Math.round(el.getBoundingClientRect().height)),
      )
      expect(new Set(heights).size).toBe(1)
      expect(heights.every((h) => h === 42)).toBeTruthy()
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      ).toBeTruthy()
      await page.screenshot({ path: info.outputPath('component-library.png') })
      await preview
        .getByRole('heading', { name: 'Form controls', exact: true })
        .scrollIntoViewIfNeeded()
      await page.screenshot({ path: info.outputPath('component-controls.png') })
      await page
        .getByRole('button', { name: 'Back to SAP Lens', exact: true })
        .click()
      await nav(page, 'User Access')
      await page
        .getByRole('navigation', { name: 'User Access view' })
        .getByRole('link', { name: 'Compare users', exact: true })
        .click()
      await page
        .getByRole('combobox', { name: 'User A', exact: true })
        .fill('DEMO_A')
      await page.getByRole('option').filter({ hasText: 'DEMO_A' }).click()
      await page
        .getByRole('combobox', { name: 'User B', exact: true })
        .fill('DEMO_B')
      await page.getByRole('option').filter({ hasText: 'DEMO_B' }).click()
      await expect(page.getByLabel('Comparison summary')).toContainText(
        'Shared roles',
      )
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
        .locator(
          'div.saved-filter-toolbar[aria-label="comparison saved filters"]',
        )
        .getByRole('button', { name: 'Saved filters', exact: true })
        .click()
      const popup = page.getByRole('dialog', {
        name: 'comparison saved filters',
        exact: true,
      })
      const box = await popup.boundingBox()
      expect(
        box &&
          box.x >= 0 &&
          box.x + box.width <= width &&
          box.y >= 0 &&
          box.y + box.height <= 1000,
      ).toBeTruthy()
      await page.screenshot({ path: info.outputPath('saved-filters.png') })
    })

test('shared import controls and nested date drafts use isolated showcase state', async ({page,request}) => {
  await page.goto('/#session=browser-test-session')
  const before=await (await request.get('/api/configuration',{headers})).json()
  await library(page)
  const demo=page.getByLabel('Component Library previews',{exact:true})
  await demo.getByRole('button',{name:'Browse demo source',exact:true}).click()
  await expect(demo.getByLabel('Demo source file',{exact:true})).toHaveValue('C:/synthetic/replacement.csv')
  const mapping=demo.getByRole('combobox',{name:'AGR_NAME',exact:true})
  await mapping.fill('ROLE_NAME')
  await page.getByRole('option',{name:'ROLE_NAME',exact:true}).click()
  await expect(mapping).toHaveValue('ROLE_NAME')
  await demo.getByRole('button',{name:/^Assignment date filters/}).click()
  const dates=page.getByRole('dialog',{name:'Assignment date controls',exact:true})
  await dates.getByText('Advanced interval filtering',{exact:true}).click()
  await dates.getByLabel('Start date from',{exact:true}).fill('01.01.2024')
  await dates.getByRole('button',{name:'Apply date filters',exact:true}).click()
  await expect(demo.getByLabel('Active assignment date filters',{exact:true})).toContainText('01.01.2024')
  await demo.getByRole('button',{name:/^Assignment date filters/}).click()
  await dates.getByRole('button',{name:'Clear date filters',exact:true}).click()
  await dates.getByRole('button',{name:'Cancel date changes',exact:true}).click()
  await expect(demo.getByLabel('Active assignment date filters',{exact:true})).toContainText('01.01.2024')
  expect(await (await request.get('/api/configuration',{headers})).json()).toEqual(before)
})

for(const theme of ['light','dark']) for(const width of [375,800,1280])
 test(`import settings visual contracts ${theme} ${width}`,async({page,request},info)=>{
  const settings=(await(await request.get('/api/configuration',{headers})).json()).settings
  settings.theme=theme
  await request.post('/api/configuration',{headers,data:settings})
  await page.setViewportSize({width,height:1000})
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button',{name:'Open settings',exact:true}).click()
  const tabs=page.getByRole('tab')
  const names=await tabs.allTextContents()
  expect(names.indexOf('Component Library')).toBeLessThan(names.indexOf('About SAP Lens'))
  await page.getByRole('tab',{name:'Data Sources',exact:true}).click()
  for(const source of ['Role Catalogue','User Access','Employee Directory']){
   await page.getByRole('tab',{name:source,exact:true}).click()
   const row=page.locator('.source-file-row:visible').first()
   await row.scrollIntoViewIfNeeded()
   await expect(row.locator('input')).toBeVisible()
   const input=await row.locator('input').boundingBox(),button=await row.getByRole('button').boundingBox()
   expect(input!.width).toBeGreaterThan(width<1000?180:300)
   if(width>=800) expect(Math.abs(input!.y-button!.y)).toBeLessThan(4)
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy()
   await page.screenshot({path:info.outputPath(`${source.toLowerCase().replaceAll(' ','-')}.png`),animations:'disabled'})
  }
  await page.getByRole('tab',{name:'SAP Modules',exact:true}).click()
  const search=page.getByRole('searchbox',{name:'Find SAP module or area',exact:true})
  await expect(search).toBeVisible()
  expect(await search.evaluate(el=>parseFloat(getComputedStyle(el).paddingLeft))).toBeGreaterThanOrEqual(36)
  await page.screenshot({path:info.outputPath('sap-modules.png')})
 })
