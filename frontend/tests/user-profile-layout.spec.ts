import { expect, test, type Page } from '@playwright/test'
import { goTo, seedSources, type SeededSources } from './support'

const long = 'ZC:VERY_LONG_USERNAME_WITHOUT_ANY_BREAK_OPPORTUNITY_FOR_THE_GRID_TO_HANDLE_0123456789'
const roles = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:MM:A,Role A,ZS:A,MIGO\n'
const users = `USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\nPROFILE_ONE,ZC:MM:A,GROUP_${'X'.repeat(60)},20200101,99991231\n`
let sources: SeededSources
test.beforeEach(async ({ request }) => { sources = await seedSources(request, { roles, users }) })
test.afterEach(async () => { await sources.cleanup() })
void long

async function open(page: Page, width: number, theme = 'light') {
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/#session=browser-test-session')
  await page.evaluate(t => document.documentElement.setAttribute('data-theme', t), theme)
  await goTo(page, 'User Access')
  await page.getByRole('link', { name: 'PROFILE_ONE', exact: true }).click()
  return page.getByRole('region', { name: 'User profile', exact: true })
}

for (const theme of ['light', 'dark']) test(`desktop profile layout ${theme}`, async ({ page }) => {
  const profile = await open(page, 1280, theme)
  const [identity, account, org, group] = await Promise.all(['SAP Identity', 'Account Status', 'Organization', 'Functional Group'].map(n => profile.getByRole('region', { name: n, exact: true }).boundingBox()))
  // three equal columns on one row, Functional Group last and full width
  expect(Math.abs(identity!.width - account!.width)).toBeLessThan(2); expect(Math.abs(account!.width - org!.width)).toBeLessThan(2)
  expect(Math.abs(identity!.y - org!.y)).toBeLessThan(2)
  expect(group!.y).toBeGreaterThan(identity!.y + identity!.height - 2)
  const box = (await profile.boundingBox())!
  expect(Math.abs(group!.width - box.width)).toBeLessThan(4)
  // Directory match only in the header, not in SAP Identity
  await expect(profile.getByRole('button', { name: /Directory matching details/ })).toHaveCount(1)
  await expect(profile.getByRole('region', { name: 'SAP Identity', exact: true }).getByRole('button', { name: /Directory matching details/ })).toHaveCount(0)
  // fields preserved
  for (const f of ['Username', 'SAP User Group', 'User type']) await expect(profile.getByRole('region', { name: 'SAP Identity', exact: true }).getByText(f, { exact: true })).toBeVisible()
  for (const f of ['Valid from', 'Valid until', 'SAP account', 'Lock status', 'AD account']) await expect(profile.getByRole('region', { name: 'Account Status', exact: true }).getByText(f, { exact: true })).toBeVisible()
  const button = group && profile.getByRole('button', { name: 'Assign group' })
  await expect(button!.locator('svg.lucide-users-round')).toHaveCount(1)
  await profile.getByText('About Functional Groups').click()
  await expect(profile).toContainText('Functional Groups are maintained in SAP Lens')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

for (const width of [375, 800]) test(`profile stacks without overflow at ${width}px`, async ({ page }) => {
  const profile = await open(page, width)
  const identity = (await profile.getByRole('region', { name: 'SAP Identity', exact: true }).boundingBox())!
  const account = (await profile.getByRole('region', { name: 'Account Status', exact: true }).boundingBox())!
  const group = (await profile.getByRole('region', { name: 'Functional Group', exact: true }).boundingBox())!
  if (width < 640) expect(account.y).toBeGreaterThan(identity.y + identity.height - 2)
  expect(group.y).toBeGreaterThan(account.y)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  const pbox = (await profile.boundingBox())!
  expect(pbox.x + pbox.width).toBeLessThanOrEqual(width + 1)
})
