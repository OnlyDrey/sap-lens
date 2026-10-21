import { test, expect, type Locator } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
// Capture brief feedback in the browser at the moment it appears. A slow
// automation round-trip must not miss a correctly expiring confirmation.
const observeCopy = async (button: Locator) => {
  // Await installation before sending the input event; selector resolution and
  // browser evaluation are asynchronous even when their promises start in order.
  await button.locator('..').evaluate((el) => {
    const target = el as HTMLElement & {
      copyObservation?: { message: string; inside: boolean }
    }
    const status = el.querySelector('[role="status"]')!
    target.copyObservation = undefined
    const observer = new MutationObserver(() => {
      if (!status.textContent) return
      const parent = el.getBoundingClientRect(),
        feedback = status.getBoundingClientRect()
      observer.disconnect()
      target.copyObservation = {
        message: status.textContent,
        inside:
          feedback.height > 0 &&
          feedback.top >= parent.top &&
          feedback.bottom <= parent.bottom
      }
    })
    observer.observe(status, {
      childList: true,
      characterData: true,
      subtree: true
    })
  })
  return () =>
    button
      .locator('..')
      .evaluate(
        (el) =>
          (
            el as HTMLElement & {
              copyObservation?: { message: string; inside: boolean }
            }
          ).copyObservation
      )
}

test.beforeEach(async ({ request }) => {
  expect(
    (await request.post('/api/configuration/reset', { headers })).ok()
  ).toBeTruthy()
})
for (const theme of ['dark', 'light'] as const) {
  test(`exact identifier copy, long wrapping, circular icons and detail rows in ${theme}`, async ({
    page,
    context,
    request
  }, testInfo) => {
    const directory = mkdtempSync(path.join(tmpdir(), 'sap-lens-identifiers-'))
    const file = path.join(directory, 'synthetic.csv')
    const identifier = 'DEMO_' + 'LONG_IDENTIFIER_'.repeat(24)
    writeFileSync(
      file,
      `AGR_NAME;TEXT;CHILD_AGR;CHILD_AGR_TEXT;TCODE\n${identifier};Synthetic long role;DEMO_CHILD;Synthetic child;DEMO_TRANSACTION\n`
    )
    try {
      // Exercise role visuals independently from the import/settings wizard,
      // which has dedicated UI regressions elsewhere in this suite.
      const settings = (
        await (await request.get('/api/configuration', { headers })).json()
      ).settings
      expect(
        (
          await request.post('/api/configuration', {
            headers,
            data: { ...settings, data_csv_path: file, theme }
          })
        ).ok()
      ).toBeTruthy()
      await context.grantPermissions(['clipboard-read', 'clipboard-write'])
      await page.goto('/#session=browser-test-session')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      const card = page.getByRole('article', {
        name: 'Synthetic long role',
        exact: true
      })
      await expect(card).toBeVisible()
      const copy = card.getByRole('button', {
        name: `Copy role identifier ${identifier}`,
        exact: true
      })
      const confirmation = await observeCopy(copy)
      await copy.focus()
      await page.keyboard.press('Enter')
      await expect
        .poll(confirmation)
        .toEqual({ message: 'Copied', inside: true })
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
        identifier
      )
      await expect(page.getByRole('dialog')).toBeHidden()
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth
        )
      ).toBeTruthy()
      await expect(card.locator('code')).toHaveText(identifier)
      await expect(card.locator('[data-module-icon]')).toHaveCSS(
        'border-radius',
        '50%'
      )
      await card.getByRole('button', { name: /View details/ }).click()
      const detail = page.getByRole('dialog')
      await expect(
        detail.getByRole('button', {
          name: `Copy role identifier ${identifier}`,
          exact: true
        })
      ).toBeVisible()
      const child = detail.getByRole('button', {
        name: 'Copy role identifier DEMO_CHILD',
        exact: true
      })
      const childConfirmation = await observeCopy(child)
      await child.click()
      await expect.poll(childConfirmation).toEqual({
        message: 'Copied',
        inside: true
      })
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
        'DEMO_CHILD'
      )
      await detail
        .getByRole('button', {
          name: 'Expand single role DEMO_CHILD',
          exact: true
        })
        .click()
      await expect(
        detail.getByText('DEMO_TRANSACTION', { exact: true })
      ).toBeVisible()
      expect(await detail.locator('button button').count()).toBe(0)
      await page.screenshot({
        path: testInfo.outputPath(`role-detail-${theme}.png`),
        fullPage: true
      })
      await expect(card.locator('[role="status"]')).toHaveText('')
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  })
}
test('module status separates saved state from unsaved preview and persists only on Apply', async ({
  page,
  request
}) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
  const row = page.getByRole('button', {
    name: 'Edit FI — Financial Accounting',
    exact: true
  })
  await row.click()
  const editor = page.locator('[aria-label="FI appearance editor"]')
  await editor
    .getByLabel('Show FI in module filters', { exact: true })
    .uncheck()
  await expect(row.locator('.status-pill')).toHaveText('Enabled')
  await expect(editor.locator('.status-pill')).toHaveText('Disabled')
  expect(
    (await (await request.get('/api/configuration', { headers })).json())
      .settings.module_overrides.FI?.enabled ?? true
  ).toBe(true)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.getByRole('button', { name: 'Open settings' }).click()
  await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
  if (!(await editor.isVisible())) await row.click()
  await expect(
    editor.getByLabel('Show FI in module filters', { exact: true })
  ).toBeChecked()
  await editor
    .getByLabel('Show FI in module filters', { exact: true })
    .uncheck()
  await page
    .getByRole('button', { name: 'Apply settings', exact: true })
    .click()
  await page.reload()
  await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
  await expect(row.locator('.status-pill')).toHaveText('Disabled')
})
for (const theme of ['light', 'dark'] as const) {
  test(`module icon colors remain readable for extreme, invalid and default colors in ${theme}`, async ({
    page
  }, testInfo) => {
    await page.goto('/#session=browser-test-session')
    await page
      .getByRole('tab', { name: 'Appearance & Branding', exact: true })
      .click()
    await page
      .getByRole('combobox', { name: 'Theme', exact: true })
      .selectOption(theme)
    if (
      await page
        .getByRole('button', { name: 'Apply settings', exact: true })
        .isEnabled()
    ) {
      await page
        .getByRole('button', { name: 'Apply settings', exact: true })
        .click()
      await expect(
        page.getByRole('region', { name: 'SAP Lens settings', exact: true })
      ).toBeHidden()
      await page.getByRole('button', { name: 'Open settings' }).click()
    }
    await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
    const row = page.getByRole('button', {
      name: 'Edit FI — Financial Accounting',
      exact: true
    })
    await row.click()
    const hex = page.getByLabel('FI hexadecimal color', { exact: true })
    for (const color of ['#ffffff', '#000000', '#111827', 'invalid', '']) {
      await hex.fill(color)
      const ratio = await row.locator('[data-module-icon]').evaluate((el) => {
        const style = getComputedStyle(el)
        const luminance = (color: string) => {
          const values = color
            .match(/[\d.]+/g)!
            .slice(0, 3)
            .map(Number)
            .map((v) => v / 255)
            .map((v) =>
              v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
            )
          return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722
        }
        const values = [
          luminance(style.color),
          luminance(style.backgroundColor)
        ].sort((a, b) => b - a)
        return (values[0] + 0.05) / (values[1] + 0.05)
      })
      expect(ratio).toBeGreaterThanOrEqual(3)
      await expect(row.locator('[data-module-icon]')).toHaveCSS('width', '40px')
    }
    await page
      .getByRole('button', { name: 'Reset FI hexadecimal color', exact: true })
      .click()
    await expect(hex).toHaveValue('#6f8fc5')
    await page.screenshot({
      path: testInfo.outputPath(`modules-${theme}.png`),
      fullPage: true
    })
  })
}
test('clipboard denial is announced and leaves exact identifier selectable', async ({
  page
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: async () => {
          throw new Error('denied')
        }
      }
    })
  )
  await page.goto('/#session=browser-test-session')
  await page
    .getByLabel('CSV file location', { exact: true })
    .fill(path.resolve('tests/fixtures/synthetic.csv'))
  await page
    .getByRole('button', { name: 'Save and load CSV', exact: true })
    .click()
  const card = page.getByRole('article').first()
  const copy = card.getByRole('button', { name: /^Copy role identifier/ })
  const confirmation = await observeCopy(copy)
  await copy.click()
  await expect.poll(confirmation).toEqual({
    message: 'Copy failed. Select the identifier to copy manually.',
    inside: true
  })
  await expect(card.locator('code')).toHaveCSS('user-select', 'text')
})
