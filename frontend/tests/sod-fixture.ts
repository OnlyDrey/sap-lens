import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

export const headers = { 'X-SAP-Lens': 'browser-test-session' }
const roles = 'AGR_NAME,TEXT,CHILD_AGR,TCODE\n' + [['ROLE_A1', 'X1'], ['ROLE_A2', 'X1'], ['ROLE_B', 'X2'], ['ROLE_C', 'X3'], ['ROLE_AB', 'X1'], ['ROLE_AB', 'X2']].map(([role, code]) => `${role},Synthetic ${role},ZS:${role},${code}`).join('\n') + '\n'
/** Review history survives configuration reset by design, so each test gets unique user names. */
export const names = { a: 'SYN_A', b: 'SYN_B', c: 'SYN_C' }
let sequence = 0
const users = () => 'USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\n' + [
  [names.a, 'ROLE_A1', 'FIN'], [names.a, 'ROLE_A2', 'FIN'], [names.a, 'ROLE_B', 'FIN'], [names.a, 'ROLE_C', 'FIN'], [names.b, 'ROLE_AB', 'P2P'], [names.c, 'ROLE_A1', 'P2P'],
].map(([user, role, group]) => `${user},${role},${group},20000101,99991231`).join('\n') + '\n'
const header = 'RISK,CRITICITY,TYPE,TEXT,ACTVT1,ACTVT2,ACTIVITY_SLOT,ACTIVITY,TCODE,TTEXT\n'
const risk = (id: string, a: string, b: string, first: string, second: string) => `${id},H,S,Synthetic ${id},${a},${b},ACTVT1,${a},${first},Synthetic\n${id},H,S,Synthetic ${id},${a},${b},ACTVT2,${b},${second},Synthetic\n`
const matrix = header + risk('R1', 'A', 'B', 'X1', 'X2') + risk('R2', 'A', 'C', 'X1', 'X3')

/** Two risks sharing activity A, duplicate role coverage for SYN_A, a single-role conflict for SYN_B and a control user. */
export async function seedGovernance(request: APIRequestContext, sodMode: 'static' | 'dynamic' = 'static'): Promise<string> {
  await request.post('/api/configuration/reset', { headers })
  const tag = `${process.pid}${++sequence}`
  Object.assign(names, { a: `SYN_A${tag}`, b: `SYN_B${tag}`, c: `SYN_C${tag}` })
  const directory = mkdtempSync(path.join(tmpdir(), 'sod-governance-ui-'))
  for (const [source, content] of Object.entries({ roles, users: users(), sod: matrix })) {
    const filename = path.join(directory, `${source}.csv`)
    writeFileSync(filename, content)
    const settings = (await (await request.get('/api/configuration', { headers })).json()).settings
    expect((await request.post(`/api/data-sources/${source}/select`, { headers, data: { path: filename, revision: settings.revision, mode: source === 'sod' ? sodMode : 'static' } })).ok()).toBeTruthy()
  }
  return directory
}

export async function cleanup(request: APIRequestContext, directory: string) {
  await request.post('/api/configuration/reset', { headers })
  rmSync(directory, { recursive: true, force: true })
}

export async function openSod(page: Page, link = 'Overview') {
  await page.goto('/#session=browser-test-session')
  await page.getByRole('navigation', { name: 'Main navigation', exact: true }).getByRole('button', { name: 'SoD', exact: true }).click()
  if (link !== 'Overview') await page.getByRole('link', { name: link, exact: true }).click()
}

export const cellButton = (page: Page, user: string, column: string) => page.getByRole('button', { name: new RegExp(`^${user}, (risk|activity) ${column}:`) })

type Json = Record<string, any>
const get = async (request: APIRequestContext, url: string, params: Json = {}) => {
  const response = await request.get(url, { headers, params })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

/** Record one decision for explicit items through the public API, using fresh revision and generation. */
export async function decide(request: APIRequestContext, kind: 'activity' | 'assignment' | 'acceptance', context: string, items: Json[], decision: string, extra: Json = {}) {
  const view = await get(request, '/api/sod/matrix/risk', { context })
  const response = await request.post(`/api/sod/decisions/${kind}`, { headers, data: { context, expected_revision: view.revision, expected_generation: view.generation, items, decision, reviewer: 'Synthetic Reviewer', justification: 'Synthetic business need', ...extra } })
  expect(response.ok(), await response.text()).toBeTruthy()
}

/** Approve every conflict-relevant activity and accept every risk in a context. */
export async function decideEverything(request: APIRequestContext, context: string, acceptance = 'Accepted') {
  const rows = (await get(request, '/api/sod/explorer/user_risk', { context, limit: 200 })).items as { user: string; risk_id: string }[]
  for (const user of new Set(rows.map((row) => row.user))) {
    const subject = await get(request, '/api/sod/subject', { context, user })
    await decide(request, 'activity', context, subject.activities.map((row: Json) => ({ key: row.key, user, ref: row.activity, evidence_version: row.evidence_version })), 'Approved')
  }
  for (const row of rows) {
    const risk = (await get(request, '/api/sod/subject', { context, user: row.user, risk: row.risk_id })).risk
    await decide(request, 'acceptance', context, [{ key: risk.finding_id, user: row.user, ref: row.risk_id, evidence_version: risk.evidence_version }], acceptance, { approver: 'Synthetic Approver' })
  }
}

export async function createPeriod(request: APIRequestContext, name: string): Promise<string> {
  const index = await get(request, '/api/sod/periods')
  const year = new Date().getFullYear()
  const response = await request.post('/api/sod/periods', { headers, data: { name, start: `${year}-01-01`, end: `${year}-12-31`, evaluation_date: `${year}-10-27`, expected_revision: index.revision } })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()).period.id
}

export async function movePeriod(request: APIRequestContext, id: string, state: string, extra: Json = {}) {
  const details = await get(request, `/api/sod/periods/${id}`, { limit: 1 })
  const response = await request.post(`/api/sod/periods/${id}/transition`, { headers, data: { state, expected_revision: details.revision, expected_review_revision: details.review_revision, actor: 'Synthetic Actor', ...extra } })
  expect(response.ok(), await response.text()).toBeTruthy()
}

export async function bridge(page: Page) {
  await page.evaluate(() => {
    ;(window as any).pywebview = { api: {
      save_sod_document: async (_token: string, name: string, encoded: string) => { ;(window as any).__saved = { name, encoded }; return true },
      save_sod_csv: async (_token: string, name: string, content: string) => { ;(window as any).__saved = { name, content }; return true },
    } }
  })
}
