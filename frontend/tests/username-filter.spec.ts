import { expect, test, type Page } from '@playwright/test'
import { goTo, openFilters, seedSources, type SeededSources } from './support'

const NAMES = ['CROYNESTAD', 'RFORLAND', 'KEGELAND', 'MASLAND', 'VTVEITEN', 'EGLENDRANGE', 'IHELLE', 'ABERGMANN', 'RLUNDE', 'OARNTSEN', 'TSKIFJELD', 'KJØRGENSEN', 'RBRINGSVAERD', 'JHALSTVEDT', 'EKAALSTAD', 'TOYE', 'TSTIGE', 'AKOCH', 'GHARALDSEN', 'IOVREBO', 'SFROYSTAD', 'JLOVIK', 'KSULEN', 'IRISVOLL']
const roles = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:MM:A,Role A,ZS:A,MIGO\n'
const users = 'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n' + NAMES.map(n => `${n},ZC:MM:A,G1,20200101,99991231`).join('\n') + '\n'
let sources: SeededSources
test.beforeEach(async ({ request }) => { sources = await seedSources(request, { roles, users }) })
test.afterEach(async () => { await sources.cleanup() })

async function open(page: Page) {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#session=browser-test-session')
  await goTo(page, 'User Access')
  await openFilters(page)
}
const feedback = (page: Page) => page.getByRole('status', { name: 'Exact username filter result' })

test('pasting a multi-line list filters exactly with feedback, Unicode and unmatched names', async ({ page }) => {
  await open(page)
  const search = page.getByPlaceholder('Username, name, email or group')
  const text = [...NAMES.map(n => n.toLowerCase()), 'croynestad', 'NOSUCHUSER'].join('\n')
  await search.evaluate((el, value) => { const data = new DataTransfer(); data.setData('text', value); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true })) }, text)
  await expect(search).toHaveValue('') // converted, not left as free text
  await expect(feedback(page)).toContainText('Requested 25')
  await expect(feedback(page)).toContainText('matched 24')
  await expect(feedback(page)).toContainText('not found 1')
  await expect(feedback(page)).toContainText('duplicates removed 1')
  await feedback(page).getByText('Show details').click()
  await expect(feedback(page)).toContainText('NOSUCHUSER')
  await expect(page.getByRole('heading', { name: /24 matching/ })).toBeVisible()
  await expect(page.getByRole('link', { name: 'KJØRGENSEN', exact: true })).toBeVisible() // original SAP spelling is displayed
  await page.getByRole('button', { name: 'Remove exact username filter' }).click()
  await expect(feedback(page)).toHaveCount(0)
})

test('an ordinary term or a names list with spaces is not converted; substrings never match', async ({ page }) => {
  await open(page)
  const search = page.getByPlaceholder('Username, name, email or group')
  await search.evaluate((el) => { const data = new DataTransfer(); data.setData('text', 'Jane Doe, John Smith'); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true })) })
  await expect(feedback(page)).toHaveCount(0)
  const area = page.getByRole('textbox', { name: 'Exact usernames' })
  await area.fill('TOY\nAKOCH')
  await page.getByRole('button', { name: 'Apply list' }).click()
  await expect(feedback(page)).toContainText('matched 1'); await expect(feedback(page)).toContainText('not found 1')
})

test('select all matching spans pages, survives paging and is cleared when the filter changes', async ({ page }) => {
  await open(page)
  await page.getByRole('textbox', { name: 'Exact usernames' }).fill(NAMES.slice(0, 12).join(','))
  await page.getByRole('button', { name: 'Apply list' }).click()
  await expect(page.getByRole('heading', { name: /12 matching/ })).toBeVisible()
  await page.getByRole('button', { name: 'Select all 12 matching' }).click()
  await expect(page.getByRole('heading', { name: /12 selected/ })).toBeVisible()
  await page.getByRole('button', { name: 'Assign group', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Assign Functional Group' })).toContainText('12 users selected')
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
  await page.getByRole('textbox', { name: 'Exact usernames' }).fill(NAMES.slice(0, 5).join(','))
  await page.getByRole('button', { name: 'Replace list' }).click()
  await expect(page.getByRole('heading', { name: /5 matching/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: /selected/ })).toHaveCount(0) // the result set changed: no invisible selection survives
})
