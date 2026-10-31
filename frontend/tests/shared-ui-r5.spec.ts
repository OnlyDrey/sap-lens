import { test, expect } from '@playwright/test'
import { cleanup, openSod, seedGovernance } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

for (const width of [375, 800, 1280]) test(`Review Context: the evaluation information is vertically centered on the dropdown (${width}px)`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 })
  await openSod(page, 'Risk Matrix')
  const bar = page.getByRole('toolbar', { name: 'Review context' }).or(page.locator('.sod-context-bar'))
  const select = bar.getByRole('combobox', { name: 'Review context' }), info = bar.getByRole('status')
  await expect(info).toContainText('Evaluation date')
  const [s, i] = [(await select.boundingBox())!, (await info.boundingBox())!]
  if (width >= 800) expect(Math.abs((s.y + s.height / 2) - (i.y + i.height / 2))).toBeLessThan(2) // one row: centered on the control
  else expect(i.y).toBeGreaterThanOrEqual(s.y + s.height - 1) // wrapped below it without overlap
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('Settings SAP Modules labels the classification as Module and Submodule', async ({ page }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
  const labels = await page.locator('.module-tile-grid span').allInnerTexts()
  const classes = labels.filter((text) => /^(module|submodule|functional area|product|component|technology)\b/i.test(text.trim()))
  expect(classes.length).toBeGreaterThan(5)
  for (const text of classes) expect(text.trim()[0]).toBe(text.trim()[0].toUpperCase())
  expect(classes.some((text) => text.trim().startsWith('Submodule'))).toBeTruthy()
  expect(classes.some((text) => text.trim().startsWith('Module'))).toBeTruthy()
})
