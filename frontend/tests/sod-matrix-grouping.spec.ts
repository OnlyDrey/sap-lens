import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { cleanup, decide, headers, names, openSod, seedGovernance, wideMatrix } from './sod-fixture'

let directory = ''
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

const grid = (page: Page, kind: 'risk' | 'activity') => page.getByRole('region', { name: kind === 'risk' ? /Scrollable User by risk matrix/ : /Scrollable User by activity matrix/ })
const groupBy = (page: Page) => page.getByRole('combobox', { name: 'Group by', exact: true })
const pageName = { risk: 'Risk Matrix', activity: 'Activity Matrix' } as const

for (const kind of ['risk', 'activity'] as const) {
  test(`${kind} matrix: the first column shows the username with its SAP User Group beneath`, async ({ page }) => {
    await openSod(page, pageName[kind])
    const head = grid(page, kind).locator('tbody th.matrix-row-head', { hasText: names.a })
    await expect(head.getByRole('button', { name: `Copy SAP username ${names.a}` })).toBeVisible()
    const [code, small] = [await head.locator('code').boundingBox(), await head.locator('small').boundingBox()]
    await expect(head.locator('small')).toHaveText('FIN')
    expect((await head.boundingBox())!.height).toBeLessThan(66) // compact rows
    expect(small!.y).toBeGreaterThanOrEqual(code!.y + code!.height - 1) // beneath the username
    expect(await head.locator('small').evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeLessThan(await head.locator('code').evaluate((el) => parseFloat(getComputedStyle(el).fontSize)) + 0.5)
  })

  test(`${kind} matrix: grouping is optional, collapsible, counts distinct users and findings, and changes no data`, async ({ page }) => {
    await openSod(page, pageName[kind])
    await expect(groupBy(page)).toHaveValue('none')
    await expect(groupBy(page).locator('option')).toHaveText(['No grouping', 'SAP User Group'])
    const matrix = grid(page, kind)
    await expect(matrix.locator('tr.matrix-group-row')).toHaveCount(0)
    const ungrouped = await matrix.locator('tbody th.matrix-row-head code').allInnerTexts()
    const columns = await matrix.locator('thead th.matrix-col').count()
    await groupBy(page).selectOption('group')
    await expect(matrix.locator('tr.matrix-group-row')).toHaveCount(2)
    const groupRow = (name: string) => matrix.locator('tr.matrix-group-row').filter({ has: page.getByRole('button', { name: new RegExp(`^(Collapse|Expand) SAP User Group ${name}$`) }) }), fin = groupRow('FIN'), p2p = groupRow('P2P')
    await expect(fin).toContainText(kind === 'risk' ? '1 user · 2 risk findings' : '1 user · 3 activity findings')
    await expect(p2p).toContainText(kind === 'risk' ? '1 user · 1 risk finding' : '1 user · 2 activity findings')
    expect((await matrix.locator('tbody th.matrix-row-head code').allInnerTexts()).sort()).toEqual([...ungrouped].sort()) // no user duplicated or omitted
    expect(await matrix.locator('thead th.matrix-col').count()).toBe(columns) // columns are unchanged
    await fin.getByRole('button', { name: 'Collapse SAP User Group FIN' }).click()
    await expect(matrix.locator('tbody th.matrix-row-head', { hasText: names.a })).toHaveCount(0)
    await expect(matrix.locator('tbody th.matrix-row-head', { hasText: names.b })).toBeVisible()
    await expect(fin.getByRole('button', { name: 'Expand SAP User Group FIN' })).toHaveAttribute('aria-expanded', 'false')
    await page.getByRole('button', { name: 'Expand all', exact: true }).click()
    await expect(matrix.locator('tbody th.matrix-row-head', { hasText: names.a })).toBeVisible()
    await page.getByRole('button', { name: 'Collapse all', exact: true }).click()
    await expect(matrix.locator('tbody th.matrix-row-head')).toHaveCount(2) // only the two group headers remain
    await groupBy(page).selectOption('none')
    await expect(matrix.locator('tr.matrix-group-row')).toHaveCount(0)
    expect(await matrix.locator('tbody th.matrix-row-head code').allInnerTexts()).toEqual(ungrouped)
  })

  test(`${kind} matrix: the first column stays visible while scrolling sideways, in plain and grouped views`, async ({ page, request }) => {
    await cleanup(request, directory); directory = await seedGovernance(request, 'static', wideMatrix)
    await page.setViewportSize({ width: 800, height: 900 })
    await openSod(page, pageName[kind])
    const matrix = grid(page, kind)
    for (const mode of ['none', 'group']) {
      await groupBy(page).selectOption(mode)
      await matrix.evaluate((element) => { element.scrollLeft = 600 })
      const head = matrix.locator('tbody th.matrix-row-head').first()
      const [box, area] = [await head.boundingBox(), await matrix.boundingBox()]
      expect(Math.abs(box!.x - area!.x)).toBeLessThan(4) // pinned to the left edge of the scroller
      expect(await head.evaluate((element) => { const style = getComputedStyle(element); return [style.position, style.backgroundColor !== 'rgba(0, 0, 0, 0)', Number(style.zIndex) >= 1] })).toEqual(['sticky', true, true])
    }
  })
}

test('the SAP User Group filter takes several values, stays open while selecting and works with grouping', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  await groupBy(page).selectOption('group')
  const box = page.getByRole('combobox', { name: 'SAP User Group', exact: true })
  await box.click()
  const list = page.getByRole('listbox', { name: 'SAP User Group options' })
  await page.getByRole('option', { name: 'FIN', exact: true }).click()
  await expect(list).toBeVisible()
  await page.getByRole('option', { name: 'P2P', exact: true }).click()
  await expect(list).toBeVisible()
  const selected = page.getByRole('group', { name: 'Selected SAP User Group' })
  await expect(selected).toContainText('FIN'); await expect(selected).toContainText('P2P')
  const matrix = grid(page, 'risk')
  await expect(matrix.locator('tr.matrix-group-row')).toHaveCount(2)
  await page.getByRole('button', { name: 'Remove SAP User Group FIN', exact: true }).click()
  await expect(matrix.locator('tr.matrix-group-row')).toHaveCount(1)
  await expect(matrix.locator('tbody th.matrix-row-head', { hasText: names.b })).toBeVisible()
  await expect(matrix.locator('tbody th.matrix-row-head', { hasText: names.a })).toHaveCount(0)
  await box.click()
  await page.getByRole('option', { name: 'FIN', exact: true }).click()
  await expect(matrix.locator('tr.matrix-group-row')).toHaveCount(2)
  await page.getByRole('button', { name: 'Clear selection', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Selected SAP User Group' })).toHaveCount(0)
  await expect(matrix.locator('tr.matrix-group-row')).toHaveCount(2)
})

test('exports follow the active filters and are identical with and without grouping', async ({ page }) => {
  await openSod(page, 'Risk Matrix')
  const exportOnce = async () => {
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: /Export CSV/ }).first().click()
    return readFileSync((await (await download).path())!, 'utf8')
  }
  const plain = await exportOnce()
  await groupBy(page).selectOption('group')
  expect(await exportOnce()).toBe(plain)
  expect(plain).toContain(names.a); expect(plain).toContain(names.b)
  const box = page.getByRole('combobox', { name: 'SAP User Group', exact: true })
  await box.click(); await page.getByRole('option', { name: 'P2P', exact: true }).click(); await page.keyboard.press('Escape')
  const filtered = await exportOnce()
  expect(filtered).toContain(names.b); expect(filtered).not.toContain(names.a)
})

test('review decisions are untouched by grouping', async ({ page, request }) => {
  const subject = await (await request.get('/api/sod/subject', { headers, params: { context: 'current', user: names.a } })).json()
  const detail = subject.activities.find((row: { activity: string }) => row.activity === 'A')
  await decide(request, 'activity', 'current', [{ key: detail.key, user: names.a, ref: 'A', evidence_version: detail.evidence_version }], 'Remove')
  await openSod(page, 'Activity Matrix')
  const cell = page.getByRole('button', { name: new RegExp(`^${names.a}, activity A:`) })
  const label = await cell.getAttribute('aria-label')
  expect(label).toMatch(/Remove/)
  await groupBy(page).selectOption('group')
  await expect(page.getByRole('button', { name: new RegExp(`^${names.a}, activity A:`) })).toHaveAttribute('aria-label', label!)
  await expect(page.getByText('1 Activities marked for removal').or(page.getByRole('button', { name: /Remove.*activities/i })).first()).toBeVisible()
})
