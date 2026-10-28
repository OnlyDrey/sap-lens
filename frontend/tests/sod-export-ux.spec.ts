import { test, expect } from '@playwright/test'
import { deflateSync } from 'node:zlib'
import { bridge, cleanup, headers, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request) })
test.afterEach(async ({ request }) => {
  await request.delete('/api/sod/reports/branding', { headers })
  await cleanup(request, directory)
})

function crc(buffer: Buffer) {
  let value = ~0
  for (const byte of buffer) { value ^= byte; for (let bit = 0; bit < 8; bit++) value = (value >>> 1) ^ (0xedb88320 & -(value & 1)) }
  return ~value >>> 0
}
const chunk = (type: string, data: Buffer) => {
  const body = Buffer.concat([Buffer.from(type), data]), head = Buffer.alloc(4), tail = Buffer.alloc(4)
  head.writeUInt32BE(data.length); tail.writeUInt32BE(crc(body))
  return Buffer.concat([head, body, tail])
}
/** Solid-color PNG built in the test so no binary fixtures are committed. */
function png(width: number, height: number) {
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header.set([8, 2, 0, 0, 0], 8)
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3, 0x55)])
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', deflateSync(Buffer.concat(Array(height).fill(row)))), chunk('IEND', Buffer.alloc(0))])
}

test('report logo can be uploaded, replaced, rejected when unsafe and removed in Organization settings', async ({ page, request }) => {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('button', { name: 'Open settings', exact: true }).click()
  await page.getByRole('tab', { name: 'Organization & SAP System', exact: true }).click()
  const card = page.getByRole('region', { name: 'Report branding', exact: true })
  await expect(card).toContainText('No report logo selected')
  const file = card.getByLabel('Report logo file')
  await file.setInputFiles({ name: 'logo.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>') })
  await expect(card.getByRole('alert')).toContainText('PNG or JPEG')
  await file.setInputFiles({ name: 'tiny.png', mimeType: 'image/png', buffer: png(8, 8) })
  await expect(card.getByRole('alert')).toContainText('dimensions')
  await file.setInputFiles({ name: 'brand.png', mimeType: 'image/png', buffer: png(96, 48) })
  await expect(card.getByRole('img', { name: 'Report logo preview' })).toBeVisible()
  await expect(card).toContainText('brand.png · 96 × 48 px')
  const first = (await (await request.get('/api/sod/reports/branding', { headers })).json()).logo.logo_id
  await file.setInputFiles({ name: 'other.png', mimeType: 'image/png', buffer: png(128, 64) })
  await expect(card).toContainText('other.png · 128 × 64 px')
  expect((await (await request.get('/api/sod/reports/branding', { headers })).json()).logo.logo_id).not.toBe(first)
  await card.getByRole('button', { name: 'Remove logo', exact: true }).click()
  await expect(card).toContainText('No report logo selected')
  expect((await (await request.get('/api/sod/reports/branding', { headers })).json()).logo).toBeNull()
})

test('exports announce globally without shifting the page; success fades and errors persist until dismissed', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await bridge(page)
  const top = () => page.getByRole('heading', { name: 'Segregation of Duties' }).evaluate((node) => node.getBoundingClientRect().top)
  const before = await top()
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  const notice = page.locator('.export-notice')
  await expect(notice).toContainText('Exported sap-lens-sod-explorer-user-risk')
  expect(await notice.evaluate((node) => getComputedStyle(node).position)).toBe('fixed')
  expect(await top()).toBe(before)
  await expect(notice).toHaveCount(0, { timeout: 10_000 })
  await page.route('**/api/sod/explorer/user_risk/export*', (route) => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic export failure.' }) }))
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Synthetic export failure.' })).toBeVisible()
  await page.waitForTimeout(7000)
  await expect(page.getByRole('alert').filter({ hasText: 'Synthetic export failure.' })).toBeVisible()
  await page.getByRole('button', { name: 'Dismiss export message', exact: true }).click()
  await expect(page.locator('.export-notice')).toHaveCount(0)
})

test('the remediation report is useful before any decision or action exists', async ({ page }) => {
  await openSod(page, 'Reports')
  await page.getByRole('tab', { name: 'Access remediation report', exact: true }).click()
  await page.getByRole('button', { name: 'Preview report', exact: true }).click()
  const preview = page.getByRole('region', { name: 'Remediation report preview', exact: true })
  await expect(preview.getByRole('table', { name: 'Remediation summary', exact: true })).toContainText('Awaiting review')
  await expect(preview).not.toContainText('0 rows across')
  await bridge(page)
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  await expect.poll(() => page.evaluate(() => (window as any).__saved?.content)).toContain('Awaiting review')
})
