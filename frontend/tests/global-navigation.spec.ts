import { test, expect, type Page } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { tmpdir } from 'node:os'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
let directory = '', source = '', rows: string[] = []
const csv = () => 'USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,ROLE_VALID_FROM,ROLE_VALID_TO\n' + rows.join('\n') + '\n'
const user = (n: number) => `DEMO_${String(n).padStart(3, '0')}`
const role = (n: number) => `ZO:MM:M:PR_REL_ST_G${String(n).padStart(3, '0')}_N6:ALL`
const destination = async(page: Page, name: string) => {await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name, exact: true }).click();if(name==='Release Roles')await page.getByRole('button',{name:'Table',exact:true}).click()}
test.beforeEach(async ({ request }) => {
  await request.post('/api/configuration/reset', { headers })
  directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-global-nav-'))
  source = path.join(directory, 'synthetic-users.csv')
  rows = Array.from({ length: 125 }, (_, i) => [
    `${user(i)},${role(i)},GROUP_KEEP,Tied,20000101,99991231`,
    `${user(i)},ZC:DEMO:BUSINESS,GROUP_KEEP,Tied,20000101,99991231`,
  ]).flat()
  rows.push('DEMO_HIDDEN,ZC:DEMO:OTHER,GROUP_OTHER,Tied,20000101,99991231')
  writeFileSync(source, csv())
  const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
  settings.user_csv_path = source
  expect((await request.post('/api/configuration', { headers, data: settings })).ok()).toBeTruthy()
})
test.afterEach(async ({ request }) => { await request.post('/api/configuration/reset', { headers }); rmSync(directory, { recursive: true, force: true }) })

for (const descending of [false, true]) test(`user global navigation crosses boundaries and restores filtered origin, descending=${descending}`, async ({ page, request }, info) => {
  if (descending) {
    const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
    settings.theme = 'light'
    await request.post('/api/configuration', { headers, data: settings })
  }
  const lookups: URL[] = []
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname === '/api/access/users' && url.searchParams.has('anchor')) lookups.push(url) })
  await page.goto('/#session=browser-test-session')
  await destination(page, 'User Access')
  const list = page.getByRole('region', { name: 'User Access', exact: true })
  const filteredResponse = page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/access/users' && !url.searchParams.has('anchor') && url.searchParams.get('search') === 'DEMO_' && url.searchParams.get('group') === 'GROUP_KEEP' && url.searchParams.get('sort') === 'first_name' && url.searchParams.get('descending') === String(descending)
  })
  await list.getByLabel('Search users', { exact: true }).fill('DEMO_')
  const group = list.getByRole('combobox', { name: 'SAP User Group', exact: true })
  await group.fill('GROUP_KEEP'); await group.press('Escape')
  await list.getByRole('combobox', { name: 'Sort users', exact: true }).selectOption('first_name')
  if (descending) await list.getByLabel('Descending', { exact: true }).check()
  await (await filteredResponse).finished()
  await expect(list.getByRole('status').filter({ hasText: 'Loading local records' })).toHaveCount(0)
  const before = descending ? 75 : 49, after = descending ? 74 : 50
  const selected = list.getByRole('link', { name: user(before), exact: true })
  await page.evaluate(username => {
    const capture = (event: MouseEvent) => {
      if ((event.target as Element).closest<HTMLElement>('[data-user]')?.dataset.user !== username) return
      ;(window as Window & { originScroll?: number }).originScroll = window.scrollY
      document.removeEventListener('click', capture, true)
    }
    document.addEventListener('click', capture, true)
  }, user(before))
  await selected.click()
  const scroll = await page.evaluate(() => (window as Window & { originScroll?: number }).originScroll!)
  expect(Number.isFinite(scroll)).toBeTruthy()
  const navigation = page.getByRole('navigation', { name: 'Detail records' })
  await expect(navigation).toContainText('50 of 125')
  await navigation.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByRole('button', { name: `Copy username ${user(after)}`, exact: true })).toBeVisible()
  await expect(navigation).toContainText('51 of 125')
  await navigation.getByRole('button', { name: 'Previous', exact: true }).click()
  await expect(navigation).toContainText('50 of 125')
  await page.screenshot({ path: info.outputPath(`global-user-${descending ? 'light' : 'dark'}.png`), animations: 'disabled' })
  await page.getByRole('button', { name: 'Back to users', exact: true }).click()
  await expect(list.getByRole('navigation', { name: 'User pages' })).toContainText('1–50 of 125')
  await expect(selected).toBeFocused()
  await expect.poll(async () => Math.abs(await page.evaluate(() => window.scrollY) - scroll)).toBeLessThan(5)
  await expect(list.getByLabel('Search users', { exact: true })).toHaveValue('DEMO_')
  await expect(group).toHaveValue('GROUP_KEEP')
  await list.getByRole('link', { name: user(descending ? 124 : 0), exact: true }).click()
  await expect(navigation).toContainText('1 of 125')
  await expect(navigation.getByRole('button', { name: 'Previous', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Back to users', exact: true }).click()
  const pages = list.getByRole('navigation', { name: 'User pages' })
  await pages.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(pages).toContainText('51–100 of 125')
  await pages.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(pages).toContainText('101–125 of 125')
  await list.getByRole('link', { name: user(descending ? 0 : 124), exact: true }).click()
  await expect(navigation).toContainText('125 of 125')
  await expect(navigation.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
  expect(lookups.length).toBeGreaterThan(1)
  expect(lookups.every(url => url.searchParams.get('search') === 'DEMO_' && url.searchParams.get('limit') === '1' && url.searchParams.get('group') === 'GROUP_KEEP' && url.searchParams.get('sort') === 'first_name' && url.searchParams.get('descending') === String(descending))).toBeTruthy()
})

test('complete release list preserves descending tie order and returns focus to the origin', async ({ page }) => {
  await page.goto('/#session=browser-test-session'); await destination(page, 'Release Roles')
  const list = page.getByRole('region', { name: 'Release Roles', exact: true })
  const group = list.getByRole('combobox', { name: 'Release SAP User Group', exact: true })
  await group.fill('GROUP_KEEP'); await group.press('Escape')
  await list.getByRole('combobox', { name: 'Sort release roles', exact: true }).selectOption('assigned_users')
  await list.getByLabel('Descending', { exact: true }).check()
  await expect(list.getByRole('navigation',{name:'Release role pages'})).toHaveCount(0)
  await expect(list.getByRole('button',{name:'Release role details',exact:true})).toHaveCount(125)
  await list.getByRole('button', { name: 'Release role details', exact: true }).filter({ hasText: role(25) }).click()
  const navigation = page.getByRole('navigation', { name: 'Detail records' })
  await expect(navigation).toContainText('100 of 125')
  await navigation.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(navigation).toContainText('101 of 125')
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText(role(24))
  await page.getByRole('button', { name: 'Back to Release Roles', exact: true }).click()
  await expect(list.getByRole('button',{name:'Release role details',exact:true})).toHaveCount(125)
  await expect(list.getByLabel('Descending', { exact: true })).toBeChecked()
  await expect(list.getByRole('button', { name: 'Release role details', exact: true }).filter({ hasText: role(25) })).toBeFocused()
})

test('direct user and release investigations locate global position and handle removal after refresh', async ({ page, request }) => {
  await page.goto('/#session=browser-test-session'); await destination(page, 'Release Roles')
  await page.getByRole('button', { name: 'Release role details', exact: true }).filter({ hasText: role(50) }).click()
  await page.getByRole('region', { name: 'Release role details', exact: true }).getByRole('button', { name: `Open user ${user(50)}`, exact: true }).click()
  const navigation = page.getByRole('navigation', { name: 'Detail records' })
  await expect(navigation).toContainText('51 of 126')
  await page.getByRole('tab', { name: 'Release Roles — ZO:*', exact: true }).click()
  await page.getByRole('button', { name: 'View role details', exact: true }).click()
  await expect(navigation).toContainText('51 of 125')
  await page.getByRole('button', { name: 'Back to Release Roles', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Release assignment status', exact: true })).toHaveValue('all')
  await destination(page, 'User Access')
  await expect(navigation).toContainText('51 of 126')
  rows = rows.filter(row => !row.startsWith(user(50) + ','))
  writeFileSync(source, csv())
  await page.getByRole('button', { name: 'Refresh role data from CSV', exact: true }).click()
  await expect(page.getByText('This record is missing or no longer matches these filters.', { exact: false })).toBeVisible()
  await expect(navigation).toHaveCount(0)
  await expect(page.getByRole('alert').filter({ hasText: 'User not found' })).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: 'Back to users', exact: true }).click()
  await expect(page.getByRole('link', { name: user(50), exact: true })).toHaveCount(0)
  expect((await request.get('/api/access/users?anchor=DEMO_050&limit=1', { headers })).ok()).toBeTruthy()
})

test('a removed last-page record disables traversal and clamps an obsolete origin page', async ({ page }) => {
  await page.goto('/#session=browser-test-session'); await destination(page, 'User Access')
  const list = page.getByRole('region', { name: 'User Access', exact: true })
  const group = list.getByRole('combobox', { name: 'SAP User Group', exact: true })
  await group.fill('GROUP_KEEP'); await group.press('Escape')
  const pages = page.getByRole('navigation', { name: 'User pages' })
  await pages.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(pages).toContainText('51–100 of 125')
  await pages.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(pages).toContainText('101–125 of 125')
  await list.getByRole('link', { name: user(124), exact: true }).click()
  await expect(page.getByRole('navigation', { name: 'Detail records' })).toContainText('125 of 125')
  rows = rows.filter(row => row.startsWith(user(0) + ','))
  writeFileSync(source, csv())
  await page.getByRole('button', { name: 'Refresh role data from CSV', exact: true }).click()
  await expect(page.getByText('This record is missing or no longer matches these filters.', { exact: false })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Detail records' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Back to users', exact: true }).click()
  await expect(pages).toHaveCount(0) // single-page evidence has no pager
  await expect(list.getByRole('link', { name: user(0), exact: true })).toBeVisible()
})
