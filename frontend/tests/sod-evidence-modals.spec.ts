import { test, expect } from '@playwright/test'
import { cleanup, names, openSod, seedGovernance } from './sod-fixture'

let directory: string
test.beforeEach(async ({ request }) => { directory = await seedGovernance(request, 'static') })
test.afterEach(async ({ request }) => { await cleanup(request, directory) })

test('Access Explorer user evidence opens in a wide modal with a compact summary, a scrollable table and shortcuts', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('button', { name: `Show evidence for ${names.a} R1` }).click()
  const dialog = page.getByRole('dialog', { name: new RegExp(`Role evidence · ${names.a} · R1`) })
  await expect(dialog).toBeVisible()
  expect((await dialog.boundingBox())!.width).toBeGreaterThanOrEqual(720)
  const summary = dialog.locator('.evidence-summary')
  for (const term of ['SAP user', 'Risk', 'Activities', 'Roles']) await expect(summary.getByText(term, { exact: true })).toBeVisible()
  const scroll = dialog.getByRole('region', { name: 'Roles supplying this evidence', exact: true })
  expect(await scroll.evaluate(el => getComputedStyle(el).overflowY)).toBe('auto')
  await expect(scroll.getByRole('table')).toContainText('ROLE_A1')
  await expect(dialog.getByRole('button', { name: 'Open SAP user' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: `Show evidence for ${names.a} R1` }).click()
  await page.getByRole('dialog', { name: /Role evidence/ }).getByRole('button', { name: 'Investigate', exact: true }).click()
  await expect(page.getByRole('dialog', { name: new RegExp(`${names.a} · R1`), exact: false }).first()).toBeVisible() // the investigation panel for the same pair
})

test('the Roles lookup shows the users behind a role in a wide modal with intervals and an investigate action', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('tab', { name: 'Roles', exact: true }).click()
  await page.getByRole('button', { name: 'Show evidence for ROLE_AB' }).click()
  const dialog = page.getByRole('dialog', { name: 'Users with ROLE_AB' })
  await expect(dialog).toBeVisible()
  expect((await dialog.boundingBox())!.width).toBeGreaterThanOrEqual(720)
  const table = dialog.getByRole('table', { name: 'Users with ROLE_AB' })
  await expect(table).toContainText(names.b)
  await expect(dialog.getByRole('columnheader', { name: 'SAP User Group' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: `Open SAP user ${names.b}` })).toBeVisible()
  await dialog.getByRole('button', { name: `Investigate ${names.b}` }).click()
  await expect(dialog).toHaveCount(0)
})

test('the Potential SoD evidence modal separates transactions, single roles, assigned roles, catalogue roles, validity and provenance for both activities', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Access Explorer')
  await page.getByRole('tab', { name: 'Role conflicts', exact: true }).click()
  await page.getByRole('button', { name: /^Inspect SoD evidence / }).first().click()
  const dialog = page.getByRole('dialog', { name: /^Potential SoD evidence · / })
  await expect(dialog).toBeVisible()
  const summary = dialog.getByLabel('Finding summary')
  for (const term of ['Risk', 'Activities (both required)']) await expect(summary.getByText(term, { exact: true })).toBeVisible()
  await expect(dialog).toContainText('do not establish effective SAP authorization')
  for (const side of ['ACTVT1', 'ACTVT2']) {
    const section = dialog.getByRole('region', { name: `${side} evidence` })
    await expect(section).toBeVisible()
    await expect(section.getByRole('columnheader')).toHaveText(['Transaction', 'Single role', 'Assigned role', 'Catalogue role or pattern', 'Assignment validity', 'Technical provenance'])
    await expect(section.getByRole('region', { name: `${side} supporting evidence table` })).toBeVisible()
  }
  await expect(dialog.getByText('Technical provenance').first()).toBeVisible()
})

test('Risk Review rows keep identity and status with separate review and formal acceptance actions', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSod(page, 'Risk Matrix')
  await page.getByRole('button', { name: new RegExp(`^${names.a}, risk R1:`) }).click()
  const panel = page.getByRole('dialog', { name: new RegExp(`${names.a} · R1`) })
  await panel.getByRole('tab', { name: /^Risks/ }).click()
  const row = panel.locator('.sod-review-row').filter({ has: page.getByRole('button', { name: /^Decide risk acceptance / }) }).first()
  await expect(row).toBeVisible()
  await expect(row.getByRole('button',{name:'Review risk R1',exact:true})).toHaveText('Review')
  await expect(row.getByText('Formal acceptance:', {exact:false})).toHaveCount(0)
  const [box, decide, check, status] = [await row.locator('.sod-review-compact').boundingBox(), await row.getByRole('button', { name: /^Decide risk acceptance / }).boundingBox(), await row.getByRole('checkbox').boundingBox(), await row.locator('.sod-review-compact .evidence-badge').first().boundingBox()]
  expect(Math.abs((decide!.y + decide!.height / 2) - (check!.y + check!.height / 2))).toBeLessThan(20) // one primary line
  expect(decide!.x + decide!.width).toBeGreaterThan(box!.x + box!.width - 80) // actions at the right edge
  expect(status!.x).toBeLessThan(decide!.x) // status before the decision action
  const description = row.locator('.sod-review-description')
  await expect(description).toBeVisible()
  expect((await description.boundingBox())!.y).toBeGreaterThan(box!.y + box!.height - 2) // description below the primary row
  const toggle = row.getByRole('button', { name: /^Show details for / })
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(row.getByRole('group', { name: /^Evidence for / })).toHaveCount(0) // history stays collapsed
  await toggle.click()
  await expect(row.getByRole('group', { name: /^Evidence for / })).toBeVisible()
})

test('shared username review actions switch users without stale evidence and preserve the review tab', async ({ page }) => {
  await page.setViewportSize({width:1600,height:1000})
  await openSod(page, 'Reviews')
  const a=page.getByRole('button',{name:`Open ${names.a} in SoD Review`,exact:true}), b=page.getByRole('button',{name:`Open ${names.b} in SoD Review`,exact:true})
  await a.click()
  const panel=page.locator('.ui-side-panel')
  await expect(panel.getByRole('heading',{name:names.a,exact:true})).toBeVisible()
  await expect(panel.locator('section[aria-label="Subject summary"]')).toContainText('FIN')
  await panel.getByRole('tab',{name:/^Activities/}).click()
  await expect(a).toHaveAttribute('aria-pressed','true')
  await expect(b).toHaveAttribute('aria-pressed','false')
  await panel.evaluate(el=>{el.setAttribute('data-persistent-panel','true')})
  await panel.getByRole('button',{name:'Review activity A',exact:true}).click()
  await panel.getByRole('textbox',{name:'Justification',exact:true}).fill('Synthetic unsaved review rationale')
  page.once('dialog',dialog=>dialog.dismiss())
  await b.click()
  await expect(panel.getByRole('heading',{name:names.a,exact:true})).toBeVisible()
  await expect(panel.getByRole('textbox',{name:'Justification',exact:true})).toHaveValue('Synthetic unsaved review rationale')
  page.once('dialog',dialog=>dialog.accept())
  await b.click()
  await expect(panel.getByRole('heading',{name:names.b,exact:true})).toBeVisible()
  await expect(panel).toHaveAttribute('data-persistent-panel','true')
  await expect(panel.getByRole('tab',{name:/^Activities/})).toHaveAttribute('aria-selected','true')
  await expect(panel.locator('section[aria-label="Subject summary"]')).toContainText('P2P')
  await expect(panel.locator('section[aria-label="Subject summary"]')).not.toContainText('FIN')
  await expect(a).toHaveAttribute('aria-pressed','false')
  await expect(b).toHaveAttribute('aria-pressed','true')
  // Rapidly switching reuses the panel while mounting evidence state for the final exact user only.
  await a.click()
  await b.click()
  await expect(panel.getByRole('heading',{name:names.b,exact:true})).toBeVisible()
  await expect(panel.locator('section[aria-label="Subject summary"]')).toContainText('P2P')
  await page.keyboard.press('Escape')
  await expect(panel).toHaveCount(0)
  await expect(b).toHaveAttribute('aria-pressed','false')
  // The same capability works outside the SoD page, without changing the parent page.
  await page.getByRole('navigation',{name:'Main navigation',exact:true}).getByRole('link',{name:'User Access',exact:true}).click()
  const table=page.locator('.user-directory-table table')
  await expect(table).toBeVisible()
  const row=table.getByRole('row').filter({has:page.getByRole('link',{name:names.a,exact:true})})
  await expect(row).toContainText('FIN')
  await expect(table.getByRole('button',{name:`Open ${names.c} in SoD Review`,exact:true})).toHaveCount(0)
  await row.getByRole('button',{name:`Copy username ${names.a}`,exact:true}).click()
  await expect(panel).toHaveCount(0)
  const action=row.getByRole('button',{name:`Open ${names.a} in SoD Review`,exact:true})
  await action.focus()
  await page.keyboard.press('Enter')
  await expect(panel.getByRole('heading',{name:names.a,exact:true})).toBeVisible()
  await expect(page).toHaveURL(/user-access/)
  await expect(page.locator('.ui-side-panel')).toHaveCount(1)
})

test('late subject responses cannot replace the newly selected review user',async({page})=>{
  let release!:()=>void
  const blocked=new Promise<void>(resolve=>{release=resolve})
  await page.route('**/api/sod/subject?*',async route=>{
    if(new URL(route.request().url()).searchParams.get('user')===names.a)await blocked
    await route.continue()
  })
  try{
    await openSod(page,'Reviews')
    await page.getByRole('button',{name:`Open ${names.a} in SoD Review`,exact:true}).click()
    const panel=page.locator('.ui-side-panel')
    await expect(panel.getByRole('heading',{name:names.a,exact:true})).toBeVisible()
    await page.getByRole('button',{name:`Open ${names.b} in SoD Review`,exact:true}).click()
    await expect(panel.locator('section[aria-label="Subject summary"]')).toContainText('P2P')
    release()
    await expect(panel.getByRole('heading',{name:names.b,exact:true})).toBeVisible()
    await expect(panel.locator('section[aria-label="Subject summary"]')).not.toContainText(names.a)
  }finally{release()}
})
