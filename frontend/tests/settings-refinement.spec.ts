import {inspectTechnicalSources} from './source-details-fixture'
import { test, expect } from '@playwright/test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
const headers = { 'X-SAP-Lens': 'browser-test-session' }
test.beforeEach(async ({ request }) => {
  expect(
    (await request.post('/api/configuration/reset', { headers })).ok()
  ).toBeTruthy()
})
const workspace = (page: import('@playwright/test').Page) =>
  page.getByRole('region', { name: 'SAP Lens settings', exact: true })

test('shared navigation and dropdown geometry retain keyboard access', async ({
  page
}) => {
  await page.goto('/#session=browser-test-session')
  const tab = page.getByRole('tab', {
    name: 'Organization & SAP System',
    exact: true
  })
  await tab.click()
  expect(await tab.evaluate((el) => getComputedStyle(el).borderWidth)).toBe(
    '0px'
  )
  await tab.focus()
  await page.keyboard.press('ArrowDown')
  await expect(
    page.getByRole('tab', { name: 'Appearance & Branding', exact: true })
  ).toBeFocused()
  await tab.click()
  const select = page.getByRole('combobox', {
    name: 'SAP platform',
    exact: true
  })
  await expect(select).toBeVisible()
  const nameBox = await page
    .getByLabel('Organization name', { exact: true })
    .boundingBox()
  const selectBox = await select.boundingBox()
  expect(selectBox!.height).toBe(nameBox!.height)
  expect(selectBox!.height).toBeGreaterThanOrEqual(42)
  expect(
    await select.evaluate((el) => parseFloat(getComputedStyle(el).paddingRight))
  ).toBeGreaterThanOrEqual(40)
  const geometry = await select.evaluate((el) => {
    const box = el.getBoundingClientRect(),
      icon = el.parentElement!.querySelector('svg')!.getBoundingClientRect()
    return {
      offset: Math.abs(box.top + box.height / 2 - (icon.top + icon.height / 2)),
      right: box.right - icon.right
    }
  })
  expect(geometry.offset).toBeLessThanOrEqual(1)
  expect(geometry.right).toBeGreaterThanOrEqual(10)
  await select.focus()
  await page.keyboard.press('ArrowDown')
  await expect(select).toHaveValue('SAP ECC')
})

test('complete icon search, module color validation and persisted icon selection', async ({
  page,
  request
}) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
  await page
    .getByRole('button', {
      name: 'Edit FI — Financial Accounting',
      exact: true
    })
    .click()
  await page.getByLabel('Find an icon', { exact: true }).fill('camera')
  await expect(page.getByText(/icons · Showing/)).toBeVisible()
  const camera = page
    .getByRole('group', { name: 'FI icon choices' })
    .getByRole('button', { name: 'Camera', exact: true })
  await camera.focus()
  await page.keyboard.press('Enter')
  await expect(camera).toHaveAttribute('aria-pressed', 'true')
  const hex = page.getByLabel('FI hexadecimal color', { exact: true })
  await hex.fill('')
  await expect(hex).toHaveValue('')
  await expect(hex).toHaveAttribute('aria-invalid', 'true')
  await expect(
    page.getByRole('button', { name: 'Apply module changes', exact: true })
  ).toBeDisabled()
  await hex.fill('invalid')
  await expect(hex).toHaveAttribute('aria-invalid', 'true')
  await expect(
    page.getByRole('button', { name: 'Apply module changes', exact: true })
  ).toBeDisabled()
  await page
    .getByRole('button', { name: 'Reset FI hexadecimal color', exact: true })
    .click()
  await expect(hex).toHaveValue('#6f8fc5')
  await page
    .getByRole('button', { name: 'Apply module changes', exact: true })
    .click()
  await page.getByRole('button',{name:'Apply settings',exact:true}).click()
  await expect(workspace(page)).toBeHidden()
  const config = await (
    await request.get('/api/configuration', { headers })
  ).json()
  expect(config.settings.module_overrides.FI.icon).toBe('Camera')
  await page.reload()
  await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
  await page
    .getByRole('button', {
      name: 'Edit FI — Financial Accounting',
      exact: true
    })
    .click()
  await expect(page.getByText('Selected icon: Camera')).toBeVisible()
  await expect(page.getByRole('dialog',{name:/Configure FI —/}).locator('svg.lucide-camera').first()).toBeVisible()
})

test('unavailable lazy icon assets keep the application usable and preserve saved icons', async ({
  page,
  request
}) => {
  const cfg = await (
    await request.get('/api/configuration', { headers })
  ).json()
  cfg.settings.module_overrides.FI = { enabled: true, icon: 'Camera' }
  expect(
    (
      await request.post('/api/configuration', { headers, data: cfg.settings })
    ).ok()
  ).toBeTruthy()
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/IconCatalog-*.js', (route) => route.abort())
  await page.goto('/#session=browser-test-session')
  await page.getByRole('tab', { name: 'SAP Modules', exact: true }).click()
  const row = page.getByRole('button', {
    name: 'Edit FI — Financial Accounting',
    exact: true
  })
  await expect(row.locator('svg.lucide-hash')).toBeVisible()
  await row.click()
  await expect(
    page
      .getByRole('alert')
      .filter({ hasText: 'Icon catalog could not be loaded' })
  ).toBeVisible()
  await expect(page.getByRole('dialog',{name:/Configure FI —/})).toBeVisible()
  expect(errors).toEqual([])
  const saved = await (
    await request.get('/api/configuration', { headers })
  ).json()
  expect(saved.settings.module_overrides.FI.icon).toBe('Camera')
})

test('CSV detection previews without loading and preserves intentional manual overrides and warns on missing columns', async ({
  page,
  request
}) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'sap-lens-auto-columns-'))
  const first = path.join(dir, 'first.csv'),
    second = path.join(dir, 'second.csv')
  writeFileSync(first, 'AGR_NAME,Role,TCODE\nDEMO_AUTO,DEMO_MANUAL,DEMO_T\n')
  writeFileSync(second, 'Alternate,TCODE\nDEMO_OTHER,DEMO_T\n')
  try {
    await page.goto('/#session=browser-test-session')
    await page.getByLabel('CSV file location', { exact: true }).fill(first)
    await expect(page.locator('.preview-metrics > div').filter({has:page.getByText('Catalogue roles',{exact:true})}).locator('dd')).toHaveText('1')
    expect((await (await request.get('/health')).json()).cached_roles).toBe(0)
    const role = page.getByLabel('AGR_NAME (required)', { exact: true })
    await role.click()
    await page.getByRole('option', { name: 'Role', exact: true }).click()
    await page
      .getByRole('button', { name: 'Preview import', exact: true })
      .click()
    await page
      .getByRole('button', { name: 'Save and load CSV', exact: true })
      .click()
    await expect(workspace(page)).toBeHidden()
    expect(
      (await request.get('/api/roles/DEMO_MANUAL', { headers })).ok()
    ).toBeTruthy()
    await page
      .getByRole('button', { name: 'Open settings', exact: true })
      .click()
    await page
      .getByRole('tab', { name: 'Data Sources', exact: true })
      .click()
    await expect(role).toBeEnabled()
    await expect(role).toHaveValue('Role')
    await page
      .getByRole('button', { name: 'Detect columns', exact: true })
      .click()
    await expect(role).toBeEnabled()
    await expect(role).toHaveValue('Role')
    await page.getByLabel('CSV file location', { exact: true }).fill(second)
    await expect(role).toHaveValue('Role')
    await expect(page.getByRole('status').filter({ hasText: /manual mappings.*(missing|retained)/i })).toBeVisible()
    await expect(role).toBeEnabled()
    expect(
      (await request.get('/api/roles/DEMO_MANUAL', { headers })).ok()
    ).toBeTruthy()
    page.once('dialog', (d) => d.accept())
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(workspace(page)).toBeHidden()
    const saved = await (
      await request.get('/api/configuration', { headers })
    ).json()
    expect(saved.settings.data_csv_path).toBe(first)
    expect(
      saved.settings.import_profiles.find(
        (p: { id: string }) => p.id === saved.settings.active_import
      ).mapping.AGR_NAME
    ).toBe('Role')
    // Clearing a path during inspection must not leave Apply disabled indefinitely.
    await page
      .getByRole('button', { name: 'Open settings', exact: true })
      .click()
    await page
      .getByRole('tab', { name: 'Data Sources', exact: true })
      .click()
    await page.getByLabel('CSV file location', { exact: true }).fill('')
    await page
      .getByRole('tab', { name: 'Organization & SAP System', exact: true })
      .click()
    await page
      .getByLabel('Organization name', { exact: true })
      .fill('Synthetic pending organization')
    await expect(
      page.getByRole('button', { name: 'Apply settings', exact: true })
    ).toBeEnabled()
    expect(
      (await request.get('/api/roles/DEMO_MANUAL', { headers })).ok()
    ).toBeTruthy()
    page.once('dialog', (d) => d.accept())
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

// Compare decoded pixels, allowing only one 8-bit channel level of edge rounding.
// PNG byte identity is too strict: a restored rounded border differed by 1/255.
async function screenshotDifference(
  page: import('@playwright/test').Page,
  a: Buffer,
  b: Buffer
) {
  return page.evaluate(
    async ({ first, second }) => {
      async function decode(bytes: number[]) {
        const bitmap = await createImageBitmap(
          new Blob([new Uint8Array(bytes)], { type: 'image/png' })
        )
        const canvas = document.createElement('canvas')
        canvas.width = bitmap.width
        canvas.height = bitmap.height
        const ctx = canvas.getContext('2d')!
        ctx.drawImage(bitmap, 0, 0)
        bitmap.close()
        return {
          width: canvas.width,
          height: canvas.height,
          data: ctx.getImageData(0, 0, canvas.width, canvas.height).data
        }
      }
      const x = await decode(first),
        y = await decode(second)
      if (x.width !== y.width || x.height !== y.height)
        return { sameSize: false, changedRatio: 1 }
      let changed = 0
      for (let i = 0; i < x.data.length; i += 4)
        if (
          [0, 1, 2, 3].some((c) => Math.abs(x.data[i + c] - y.data[i + c]) > 1)
        )
          changed++
      return { sameSize: true, changedRatio: changed / (x.width * x.height) }
    },
    { first: [...a], second: [...b] }
  )
}

test('theme preview screenshot changes and cancel restores the original pixels', async ({
  page
}, info) => {
  await page.goto('/#session=browser-test-session')
  await page
    .getByRole('tab', { name: 'Appearance & Branding', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Apply settings', exact: true })
  ).toBeDisabled()
  const preview = page.getByLabel('Theme live preview', { exact: true })
  await preview.locator('img').evaluate(async (img: HTMLImageElement) => {
    await img.decode()
  })
  const original = await preview.screenshot({
    animations: 'disabled',
    caret: 'hide'
  })
  await page.getByLabel('Primary color', { exact: true }).fill('#123456')
  const changed = await preview.screenshot({
    animations: 'disabled',
    caret: 'hide'
  })
  expect(
    (await screenshotDifference(page, original, changed)).changedRatio
  ).toBeGreaterThan(0.1)
  await info.attach('preview-original', {
    body: original,
    contentType: 'image/png'
  })
  await info.attach('preview-edited', {
    body: changed,
    contentType: 'image/png'
  })
  page.once('dialog', (d) => d.accept())
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page
    .getByRole('tab', { name: 'Appearance & Branding', exact: true })
    .click()
  const reverted = await preview.screenshot({
    animations: 'disabled',
    caret: 'hide'
  })
  await info.attach('preview-cancelled', {
    body: reverted,
    contentType: 'image/png'
  })
  const comparison = await screenshotDifference(page, original, reverted)
  expect(comparison.sameSize).toBeTruthy()
  expect(comparison.changedRatio).toBe(0)
  await page
    .getByRole('tab', { name: 'Health & Diagnostics', exact: true })
    .click()
  await page.getByText('Source locations and storage details',{exact:true}).click()
  await inspectTechnicalSources(page)
  for (const name of [
    'Application status',
    'Data & storage',
    'Troubleshooting',
    'Backup & recovery'
  ])
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  await expect(
    page.getByText('Configuration schema', { exact: true })
  ).toBeHidden()
  await page.getByText('Technical details', { exact: true }).click()
  await expect(
    page.getByText('Configuration schema', { exact: true })
  ).toBeVisible()
})

test('diagnostics format backend state without changing API evidence', async ({page,request}) => {
  const response=await request.get('/api/diagnostics',{headers})
  expect(response.ok()).toBeTruthy()
  const snapshot=await response.json()
  let backend_status='running'
  await page.route('**/api/diagnostics',route=>route.fulfill({contentType:'application/json; charset=utf-8',body:JSON.stringify({...snapshot,backend_status})}))
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button',{name:'Open settings',exact:true}).click()
  await page.getByRole('tab',{name:'Health & Diagnostics',exact:true}).click()
  const card=page.locator('.compact-health').filter({has:page.locator('.status-card-label').filter({hasText:/^Local service$/})})
  await expect(card).toContainText('Running')
  backend_status='loading'
  await page.getByRole('button',{name:'Check again',exact:true}).click()
  await expect(card).toContainText('Loading')
  await expect(card).toHaveAttribute('data-tone','info')
})
