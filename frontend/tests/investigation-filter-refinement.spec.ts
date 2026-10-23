import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
let directory: string
const roles =
  'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nMM,ZC:MM:A,Alpha purchasing,ZS:A1,MM - Purchasing,MIGO,Goods movement\nMM,ZC:MM:A,Alpha purchasing,ZS:A2,MM - Purchasing,ME21N,Create purchase order\nFI,ZC:FI:B,Beta finance,ZS:B,FI - Finance,MIGO,Goods movement\nSD,ZC:SD:C,Gamma sales,ZS:C,SD - Sales,VA03,Display sales\n'
const users =
  'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO,USER_VALID_FROM,USER_VALID_TO\nDEMO_ONE,ZC:MM:A,G1,20200101,99991231,20200101,99991231\nDEMO_ONE,ZC:FI:B,G1,20240101,20260101,20200101,99991231\nDEMO_ONE,ZO:MM:M:PR_REL_ST_G1_N1:ALL,G1,20240101,99991231,20200101,99991231\nDEMO_TWO,ZO:MM:M:PR_REL_ST_G1_N1:ALL,G2,20250101,20251231,20200101,99991231\nDEMO_TWO,ZO:MM:M:PO_REL_ST_G2_N2:ALL,G2,,,20200101,99991231\nDEMO_THREE,ZO:UNKNOWN,G2,20300101,99991231,20200101,99991231\n'
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-filter-'))
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
async function go(page: Page, view = 'Role Lookup') {
  await page.goto('/#session=browser-test-session')
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: view, exact: true })
    .click()
}
async function user(page: Page) {
  await go(page, 'User Access')
  await page.getByRole('button', { name: 'DEMO_ONE', exact: true }).click()
  return page.getByRole('region', { name: 'User details', exact: true })
}
async function openDates(page: Page) {
  const summary = page.locator('.assignment-date-filters > summary:visible')
  if (!(await summary.locator('..').evaluate((el) => el.hasAttribute('open'))))
    await summary.click()
}

test('catalogue AND/OR is exact across mapping rows; multi-area OR combines with role text using AND', async ({
  page,
}) => {
  await go(page)
  const tx = page.getByRole('group', {
      name: 'Filter catalogue by transaction',
      exact: true,
    }),
    input = tx.getByRole('textbox'),
    areas = page.getByRole('group', { name: 'SAP areas', exact: true })
  await input.fill(' migo ')
  await input.press('Enter')
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(
    tx.getByRole('group', { name: 'Transaction matching' }),
  ).toHaveCount(0)
  await input.fill('ME21N')
  await input.press('Enter')
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(
    tx.getByRole('button', { name: 'AND', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  expect(
    await tx.evaluate(
      (el) =>
        !!(
          el
            .querySelector('[aria-label="Transaction matching"]')!
            .compareDocumentPosition(el.querySelector('.transaction-chip')!) &
          Node.DOCUMENT_POSITION_FOLLOWING
        ),
    ),
  ).toBe(true)
  await input.fill('me21n')
  await input.press('Enter')
  await expect(
    tx.getByRole('button', { name: 'Remove transaction ME21N' }),
  ).toHaveCount(1)
  await tx.getByRole('button', { name: 'OR', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await areas.getByRole('button', { name: /^SD / }).click()
  await expect(page.getByRole('article')).toHaveCount(0)
  await areas.getByRole('button', { name: /^MM / }).click()
  await expect(page.getByRole('article')).toHaveCount(1)
  await areas.getByRole('button', { name: /^FI / }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await areas.getByRole('button', { name: /^MM / }).click()
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(areas.getByRole('button', { name: /^FI / })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const search = page.getByPlaceholder('Search roles by name or description...')
  await search.fill('Beta')
  await expect(page.getByRole('article')).toHaveCount(1)
  await search.fill('MIGO')
  await expect(page.getByRole('article')).toHaveCount(0)
  await page
    .getByRole('button', { name: 'Clear all filters', exact: true })
    .click()
  await expect(page.getByRole('article')).toHaveCount(3)
  await expect(search).toHaveValue('')
  await expect(areas.getByRole('button', { name: /^All / })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(
    page.getByRole('button', { name: 'Clear all filters', exact: true }),
  ).toHaveCount(0)
})

test('one catalogue reset covers live-only transaction, text, areas, mode and sorting without clearing comparisons', async ({
  page,
}) => {
  await go(page)
  const tx = page.getByRole('group', {
    name: 'Filter catalogue by transaction',
    exact: true,
  })
  await page
    .getByRole('button', { name: 'Add to comparison', exact: true })
    .first()
    .click()
  await tx.getByRole('textbox').fill('MIGO')
  await expect(
    page.getByRole('button', { name: 'Clear all filters', exact: true }),
  ).toBeVisible()
  await page
    .getByRole('button', { name: 'Clear all filters', exact: true })
    .click()
  await expect(page.getByRole('article')).toHaveCount(3)
  await page.getByRole('button', { name: 'Name A to Z', exact: true }).click()
  await page.getByRole('button', { name: 'Name Z to A', exact: true }).click()
  await page
    .getByRole('button', { name: 'Clear all filters', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Name A to Z', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Remove from comparison', exact: true }),
  ).toHaveCount(1)
  await page
    .getByPlaceholder('Search roles by name or description...')
    .fill('ME21N')
  await expect(page.getByRole('article')).toHaveCount(0)
  await page
    .getByPlaceholder('Search roles by name or description...')
    .fill('purchasing')
  await expect(page.getByRole('article')).toHaveCount(1)
})

test('catalogue detail neighbours and browser history keep the complete filtered sort order', async ({
  page,
}) => {
  await go(page)
  await page
    .getByRole('textbox', {
      name: 'Filter catalogue by transaction',
      exact: true,
    })
    .fill('MIGO')
  await expect(page.getByRole('article')).toHaveCount(2)
  await page
    .getByRole('button', {
      name: 'View details for Alpha purchasing',
      exact: true,
    })
    .click()
  const dialog = page.getByRole('dialog'),
    nav = dialog.getByRole('navigation', {
      name: 'Detail records',
      exact: true,
    })
  await expect(nav).toContainText('1 of 2')
  await nav.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(nav).toContainText('2 of 2')
  await expect(dialog).toContainText('Beta finance')
  await page.goBack()
  await expect(nav).toContainText('1 of 2')
  await page.goForward()
  await expect(nav).toContainText('2 of 2')
  await dialog.getByRole('button', { name: 'Close role details' }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(
    page.getByRole('textbox', {
      name: 'Filter catalogue by transaction',
      exact: true,
    }),
  ).toHaveValue('MIGO')
})

test('user date ranges are inclusive, independent, recover from invalid bounds and match the exported CSV', async ({
  page,
}) => {
  const detail = await user(page)
  await detail
    .getByLabel('Assignment status', { exact: true })
    .selectOption('all')
  await openDates(page)
  await detail
    .getByLabel('Valid from earliest', { exact: true })
    .fill('2024-01-01')
  await detail
    .getByLabel('Valid from latest', { exact: true })
    .fill('2024-01-01')
  await expect(
    detail
      .getByRole('region', { name: 'User role assignments' })
      .getByRole('row'),
  ).toHaveCount(3)
  await detail
    .getByLabel('Valid to earliest', { exact: true })
    .fill('9999-12-31')
  await expect(
    detail
      .getByRole('region', { name: 'User role assignments' })
      .getByRole('row'),
  ).toHaveCount(2)
  await detail
    .getByRole('button', { name: 'Clear valid from', exact: true })
    .click()
  await expect(
    detail.getByLabel('Valid to earliest', { exact: true }),
  ).toHaveValue('9999-12-31')
  const download = page.waitForEvent('download')
  await detail.getByRole('button', { name: 'Export CSV', exact: true }).click()
  const contents = readFileSync((await (await download).path())!, 'utf8')
  expect(contents).toContain('ZC:MM:A')
  expect(contents).toContain('ZO:MM:M:PR_REL_ST_G1_N1:ALL')
  expect(contents).not.toContain('ZC:FI:B')
  await detail
    .getByRole('button', { name: 'Clear valid to', exact: true })
    .click()
  await detail
    .getByLabel('Valid from earliest', { exact: true })
    .fill('2025-01-01')
  await detail
    .getByLabel('Valid from latest', { exact: true })
    .fill('2024-01-01')
  await expect(
    detail.getByLabel('Valid from latest', { exact: true }),
  ).toBeVisible()
  await expect(
    detail
      .getByText(
        'Earliest assignment dates must not follow their latest dates.',
        { exact: true },
      )
      .first(),
  ).toBeVisible()
  await detail
    .getByRole('button', { name: 'Clear all assignment filters', exact: true })
    .click()
  await expect(
    detail.getByLabel('Valid from earliest', { exact: true }),
  ).toHaveValue('')
  await expect(
    detail
      .getByRole('region', { name: 'User role assignments' })
      .getByRole('row'),
  ).toHaveCount(3)
})

test('business and release assignment tabs have dedicated split-date columns without release catalogue noise', async ({
  page,
}) => {
  const detail = await user(page)
  await detail
    .getByRole('button', { name: 'Business Roles — ZC:*', exact: true })
    .click()
  let table = detail.getByRole('region', { name: 'User role assignments' })
  await expect(
    table.getByRole('columnheader', { name: 'Catalogue match', exact: true }),
  ).toBeVisible()
  await expect(
    table.getByRole('columnheader', { name: 'Type', exact: true }),
  ).toHaveCount(0)
  await detail
    .getByRole('button', { name: 'Release Roles — ZO:*', exact: true })
    .click()
  table = detail.getByRole('region', { name: 'User role assignments' })
  for (const name of [
    'Type',
    'Release group',
    'Release strategy',
    'Valid from',
    'Valid to',
  ])
    await expect(
      table.getByRole('columnheader', { name, exact: true }),
    ).toBeVisible()
  await expect(
    table.getByRole('columnheader', { name: 'Catalogue match', exact: true }),
  ).toHaveCount(0)
  await expect(table).not.toContainText('Unmapped')
  await expect(table).toContainText('31.12.9999')
  await expect(table).toContainText('Active assignment')
  await detail
    .getByRole('button', { name: 'View role details', exact: true })
    .click()
  const release = page.getByRole('region', {
    name: 'Release role details',
    exact: true,
  })
  await expect(
    release.getByRole('definition').filter({ hasText: 'PR' }),
  ).toBeVisible()
  const assignments = release.getByRole('region', {
    name: 'Release role user assignments',
  })
  await expect(assignments.getByRole('columnheader')).toHaveText([
    'Username',
    'User group',
    'Valid from',
    'Valid to',
    'Assignment status',
    'Details',
  ])
  await expect(assignments).not.toContainText('ZO:MM:')
  await expect(assignments).not.toContainText('Account evidence')
  await expect(
    assignments.getByRole('button', {
      name: 'Copy username DEMO_ONE',
      exact: true,
    }),
  ).toBeVisible()
  await assignments
    .getByRole('button', { name: 'Open user DEMO_ONE', exact: true })
    .click()
  await expect(
    page.getByRole('region', { name: 'User details', exact: true }),
  ).toContainText('DEMO_ONE')
})

test('release date filters compose with matrix, counts and navigation, and return to the filtered origin', async ({
  page,
}) => {
  await go(page, 'Release Roles')
  const list = page.getByRole('region', { name: 'Release Roles', exact: true })
  await list
    .getByRole('combobox', { name: 'Release assignment status', exact: true })
    .selectOption('all')
  await openDates(page)
  await list.getByLabel('Valid from latest', { exact: true }).fill('2024-01-01')
  await expect(
    list.getByRole('button', { name: 'Release role details', exact: true }),
  ).toHaveCount(1)
  await list.getByRole('button', { name: 'Matrix', exact: true }).click()
  await list
    .getByRole('button', { name: 'Investigate PR G1 N1: 1 users', exact: true })
    .click()
  const detail = page.getByRole('region', {
    name: 'Release role details',
    exact: true,
  })
  await expect(detail).toContainText('1 distinct users · 1 assignment records')
  await page
    .getByRole('button', { name: 'Back to Release Roles', exact: true })
    .click()
  await expect(
    list.getByRole('button', { name: 'Matrix', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(
    list.getByLabel('Valid from latest', { exact: true }),
  ).toHaveValue('2024-01-01')
  await list.getByRole('button', { name: 'Table', exact: true }).click()
  await list
    .getByRole('button', { name: 'Release role details', exact: true })
    .click()
  await expect(
    page.getByRole('navigation', { name: 'Detail records', exact: true }),
  ).toContainText('1 of 1')
  await expect(
    detail
      .getByRole('region', { name: 'Release role user assignments' })
      .getByRole('row'),
  ).toHaveCount(2)
})

for (const theme of ['light', 'dark'] as const)
  for (const width of [800, 1280])
    test(`filtered catalogue and assignment visual QA ${theme} ${width}`, async ({
      page,
      request,
    }, info) => {
      const current = (
        await (await request.get('/api/configuration', { headers })).json()
      ).settings
      current.theme = theme
      expect(
        (
          await request.post('/api/configuration', { headers, data: current })
        ).ok(),
      ).toBeTruthy()
      await page.setViewportSize({ width, height: 1000 })
      await go(page)
      const tx = page.getByRole('group', {
        name: 'Filter catalogue by transaction',
        exact: true,
      })
      await tx.getByRole('textbox').fill('MIGO')
      await tx.getByRole('textbox').press('Enter')
      await tx.getByRole('textbox').fill('ME21N')
      await tx.getByRole('textbox').press('Enter')
      await expect(page.getByRole('article')).toHaveCount(1)
      const areas = page.getByRole('group', { name: 'SAP areas', exact: true })
      await areas.getByRole('button', { name: /^MM / }).click()
      await areas.getByRole('button', { name: /^FI / }).click()
      await page.screenshot({
        animations: 'disabled',
        path: info.outputPath('catalogue.png'),
        fullPage: true,
      })
      await page
        .getByRole('navigation', { name: 'Main navigation' })
        .getByRole('button', { name: 'User Access', exact: true })
        .click()
      await page.getByRole('button', { name: 'DEMO_ONE', exact: true }).click()
      await page
        .getByRole('button', { name: 'Release Roles — ZO:*', exact: true })
        .click()
      await expect(
        page.getByRole('region', { name: 'User role assignments' }),
      ).toContainText('Active assignment')
      await page.screenshot({
        animations: 'disabled',
        path: info.outputPath('release-tab.png'),
        fullPage: true,
      })
      if (width === 800) {
        const table = page.getByRole('region', { name: 'User role assignments', exact: true })
        await table.focus()
        await table.press('ArrowRight')
        await expect.poll(() => table.evaluate(el => el.scrollLeft)).toBeGreaterThan(0)
      }

      await page
        .getByRole('button', { name: 'View role details', exact: true })
        .click()
      await expect(
        page.getByRole('region', { name: 'Release role user assignments' }),
      ).toContainText('31.12.9999')
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true)
      await page.screenshot({
        animations: 'disabled',
        path: info.outputPath('release-details.png'),
        fullPage: true,
      })
    })

test('catalogue detail navigation crosses page boundaries and returns to its original page', async ({
  page,
  request,
}) => {
  const file = path.join(directory, 'large-roles.csv')
  writeFileSync(
    file,
    'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\n' +
      Array.from(
        { length: 125 },
        (_, i) =>
          `MM,ZC:MM:PAGE:${String(i).padStart(3, '0')},Demo role ${String(i).padStart(3, '0')},ZS:${i},MIGO`,
      ).join('\n'),
  )
  const settings = (
    await (await request.get('/api/configuration', { headers })).json()
  ).settings
  settings.data_csv_path = file
  expect(
    (
      await request.post('/api/configuration', { headers, data: settings })
    ).ok(),
  ).toBeTruthy()
  await go(page)
  const pages = page.getByRole('navigation', {
    name: 'Role pages',
    exact: true,
  })
  await expect(pages).toContainText('1–100 of 125')
  await page
    .getByRole('button', {
      name: 'View details for Demo role 099',
      exact: true,
    })
    .click()
  const dialog = page.getByRole('dialog'),
    navigation = dialog.getByRole('navigation', {
      name: 'Detail records',
      exact: true,
    })
  await expect(navigation).toContainText('100 of 125')
  await navigation.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(navigation).toContainText('101 of 125')
  await expect(dialog).toContainText('ZC:MM:PAGE:100')
  await dialog.getByRole('button', { name: 'Close role details' }).click()
  await expect(pages).toContainText('1–100 of 125')
})

test('unparsed release roles and unknown assignment dates remain visible without invented metadata', async ({ page }) => {
  await go(page, 'Release Roles')
  const list = page.getByRole('region', { name: 'Release Roles', exact: true })
  await list.getByRole('combobox', { name: 'Release assignment status', exact: true }).selectOption('all')
  await list.getByRole('button', { name: 'Release role details', exact: true }).filter({ hasText: 'ZO:UNKNOWN' }).click()
  const detail = page.getByRole('region', { name: 'Release role details', exact: true })
  await expect(detail.getByRole('definition').filter({ hasText: 'Unparsed' })).toBeVisible()
  await expect(detail.getByRole('region', { name: 'Release role user assignments' })).not.toContainText('Unmapped')
  await page.getByRole('button', { name: 'Back to Release Roles', exact: true }).click()
  await list.getByRole('button', { name: 'Release role details', exact: true }).filter({ hasText: 'PO_REL_ST_G2_N2' }).click()
  const assignments = detail.getByRole('region', { name: 'Release role user assignments', exact: true })
  await expect(assignments).toContainText('Unknown validity')
  await expect(assignments.getByRole('cell', { name: 'Unknown', exact: true })).toHaveCount(2)
  await openDates(page)
  await detail.getByRole('combobox', { name: 'Open-ended assignments', exact: true }).selectOption('only')
  await expect(assignments.getByRole('row')).toHaveCount(1)
  await detail.getByRole('button', { name: 'Clear valid to', exact: true }).click()
  await expect(assignments.getByRole('row')).toHaveCount(2)
})
