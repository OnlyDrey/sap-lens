import { apiRequest, applicationToken } from './client'

export type Filters = Record<string, string | boolean | number | string[]>
export type Lifecycle = 'Pending' | 'Approved' | 'Keep' | 'Accepted' | 'Conditional' | 'Removal required' | 'Investigate' | 'Rejected' | 'Outdated' | 'Historical' | 'Resolved'

export interface ContextInfo {
  context: string
  generation: string
  as_of: string
  coverage: { status: string; reason: string | null }
  frozen: boolean
  reviewable: boolean
  revision: number
  legacy: boolean
  period: { id: string; name: string; state: string } | null
}
export interface RiskColumn { risk_id: string; criticality: string; display_name: string; source_text: string; category: string; users: number }
export interface ActivityColumn { activity: string; risks: string[]; users: number }
export interface RiskCell { finding_id: string; criticality: string; acceptance: Lifecycle; activities: Record<string, number> }
export interface ActivityCell { key: string; decision: Lifecycle; roles: number; risks: string[]; duplicate: boolean }
export interface GroupCell { users: number }
export interface MatrixRow<Cell> { user: string; groups: string[]; users?: number; cells: Record<string, Cell | GroupCell>; /** Grouped view only: the one SAP User Group this user is listed under. */ group?: string }
export interface GroupSummary { name: string; users: number; findings: number; start: number }
export interface MatrixResult<Column, Cell> extends ContextInfo {
  kind: 'risk' | 'activity'
  group_by: 'user' | 'group' | 'user_group'
  /** Grouped view only: distinct users and finding cells per SAP User Group over the whole filtered scope, in display order. */
  group_summaries?: GroupSummary[] | null
  columns: Column[]
  columns_truncated: boolean
  rows: MatrixRow<Cell>[]
  total_rows: number
  offset: number
  limit: number
  totals: { users: number; user_risk?: number; user_activity?: number; risks?: number; activities?: number }
  criticality?: Record<string, { risks: number; user_risk: number; users: number }>
  status_counts: Record<string, number>
}
export interface DecisionEvent {
  event_id: string
  kind: 'activity' | 'assignment' | 'acceptance'
  context: string
  timestamp: string
  key: string
  user: string
  ref: string
  decision: string
  reviewer: string
  approver: string
  justification: string
  controls: string
  expires: string | null
  evidence_version: string
}
export interface AssignmentRow {
  id: string
  role: string
  valid_from: string | null
  valid_to: string | null
  user_group: string
  interval_status: string | null
  tcodes: string[]
  other_activities: string[]
  risks: string[]
  catalogue_roles: string[]
  evidence_version: string
  decision: Lifecycle
  event: DecisionEvent | null
}
export interface ActivityDetail {
  activity: string
  key: string
  risks: string[]
  slots: string[]
  tcodes: string[]
  evidence_version: string
  assignments: AssignmentRow[]
  duplicate_coverage: boolean
  decision: Lifecycle
  event: DecisionEvent | null
}
export interface RemovalOption {
  slot: string
  activities: string[]
  assignments: string[]
  roles: string[]
  resolves_risk: boolean
  also_resolves: string[]
  affected_approved_activities: string[]
  warnings: string[]
}
export interface AssignmentImpact {
  assignment_id: string
  resolves: string[]
  remaining: string[]
  lost_activities: string[]
  affected_approved_activities: string[]
  warnings: string[]
  eliminates_all: boolean
}
export interface OverviewAssignment { id: string; role: string; decision: Lifecycle; event: DecisionEvent | null; evidence_version: string; risks: string[]; activities: string[]; valid_from: string | null; valid_to: string | null; interval_status: string | null; user_group: string; catalogue_roles: string[] }
export interface SubjectOverview {
  activities: { activity: string; key: string; decision: Lifecycle; event: DecisionEvent | null; evidence_version: string; risks: string[]; tcodes: string[]; roles: number; duplicate_coverage: boolean }[]
  assignments: OverviewAssignment[]
  risks: { risk_id: string; criticality: string; display_name: string; source_text: string; finding_id: string; evidence_version: string; acceptance: Lifecycle; event: DecisionEvent | null }[]
}
export interface UserQueueRow {
  user: string; total: number; decided: number; outstanding: number; removal: number; historical: number
  activity: { total: number; decided: number }; assignment: { total: number; decided: number }; acceptance: { total: number; decided: number }
}
export interface Subject extends ContextInfo {
  overview: SubjectOverview
  user: string
  groups: string[]
  account: { directory_match: string; ad_status: string; sap_validity?: string; lock_status?: string } | null
  risk: null | {
    risk_id: string
    criticality: string
    display_name: string
    source_text: string
    category: string
    risk_type: string
    finding_id: string
    evidence_version: string
    sides: Record<string, string[]>
    acceptance: Lifecycle
    event: DecisionEvent | null
    legacy_decisions: { decision?: string; annotation?: { decision: string; reviewer: string; rationale: string }; timestamp?: string }[]
  }
  activities: ActivityDetail[]
  related_risks: string[]
  impact: null | { options: RemovalOption[]; per_assignment: Record<string, AssignmentImpact> }
}
export interface QueueItem {
  kind: 'activity' | 'assignment' | 'acceptance'
  key: string
  user: string
  ref: string
  risks: string[]
  lifecycle: Lifecycle
  roles: number
  evidence_version: string
  event: DecisionEvent | null
}

const SCALAR_KEYS = ['search', 'risk', 'criticality', 'risk_type', 'category', 'username', 'group', 'composite_role', 'single_role', 'tcode', 'role', 'role_suffix', 'activity', 'account_status', 'multiple_risks', 'tracking',
  'activity_decision', 'assignment_decision', 'acceptance', 'validity', 'as_of', 'sort']

/** Exact multi-select values: OR within the list, AND with every other filter. */
const MULTI_KEYS = ['usernames', 'role_suffixes', 'risks', 'activities', 'groups', 'roles', 'tcodes', 'categories', 'criticalities']

export const emptyFilters: Filters = {
  search: '', risk: '', criticality: '', category: '', username: '', usernames: [], role_suffixes: [], risks: [], activities: [], groups: [], roles: [], tcodes: [], categories: [], criticalities: [], group: '', role: '', role_suffix: '', activity: '', tcode: '', account_status: '', multiple_risks: '', tracking: '',
  activity_decision: '', assignment_decision: '', acceptance: '', validity: 'active', as_of: '', sort: 'subject', descending: false,
}

export function scopeParams(context: string, filters: Filters, extra: Record<string, string | number> = {}): URLSearchParams {
  const params = new URLSearchParams({ context })
  for (const key of SCALAR_KEYS) {
    const value = filters[key]
    if (typeof value === 'string' && value !== '') params.set(key, value)
  }
  if (filters.descending === true) params.set('descending', 'true')
  for (const key of MULTI_KEYS) {
    const value = filters[key]
    if (Array.isArray(value)) for (const item of value) params.append(key, item)
  }
  for (const [key, value] of Object.entries(extra)) if (value !== '') params.set(key, String(value))
  return params
}

export const sod = <T>(path: string, params?: URLSearchParams) => apiRequest<T>(params ? `${path}?${params}` : path)
export const sodPost = <T>(path: string, body: unknown) => apiRequest<T>(path, 'POST', body)

async function readLimited(response: Response, limit: number): Promise<Uint8Array[]> {
  const reader = response.body?.getReader()
  if (!reader) throw Error('Export stream unavailable.')
  const blocks: Uint8Array[] = []
  let size = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    size += value.length
    if (size > limit) {
      await reader.cancel()
      throw Error('Export exceeds 32 MiB. Narrow the filters or exclude appendices.')
    }
    blocks.push(value)
  }
  return blocks
}

/** Fetch a server-generated file and save it through the browser or the guarded native dialog. Returns the saved name, or '' when cancelled. */
export async function downloadFile(path: string, options: { method?: 'GET' | 'POST'; body?: unknown; params?: URLSearchParams; namePattern: RegExp; kind: 'csv' | 'document'; nativeCsv?: 'save_sod_csv' | 'save_role_package_csv' }): Promise<string> {
  const response = await fetch(options.params ? `${path}?${options.params}` : path, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json', 'X-SAP-Lens': applicationToken() },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: 'no-store',
  })
  if (!response.ok) {
    let detail = 'Export failed. Refresh the source and retry.'
    try { const error = await response.json(); if (typeof error.detail === 'string') detail = error.detail } catch { /* keep the generic message */ }
    throw Error(detail)
  }
  const name = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]
  if (!name || !options.namePattern.test(name)) throw Error('Invalid export filename.')
  const blocks = await readLimited(response, 32 * 1024 * 1024)
  if (window.pywebview) {
    const api = window.pywebview.api
    if (options.kind === 'csv') {
      const save = api[options.nativeCsv || 'save_sod_csv']
      if (!save) throw Error('Update the desktop application for CSV export.')
      const text = new TextDecoder('utf-8', { fatal: true })
      const content = blocks.map((block, index) => text.decode(block, { stream: index < blocks.length - 1 })).join('')
      return (await save(applicationToken(), name, '﻿' + content.replace(/^﻿/, ''))) ? name : ''
    }
    if (!api.save_sod_document) throw Error('Update the desktop application for SoD document export.')
    const blob = new Blob(blocks as BlobPart[])
    const encoded = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result).split(',')[1])
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
    return (await api.save_sod_document(applicationToken(), name, encoded)) ? name : ''
  }
  const type = response.headers.get('content-type') || 'application/octet-stream'
  const url = URL.createObjectURL(new Blob(blocks as BlobPart[], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return name
}

export const EXPORT_NAME = /^sap-lens-sod-(explorer-(user-risk|user-activity|access-list|lookup)|group-(risk|activity)-heatmap|review-queue|access-remediation)-\d{4}-\d{2}-\d{2}\.csv$/
export const REPORT_NAME = /^sap-lens-(sod-report-[a-f0-9]{32}|access-remediation-(current|[a-f0-9]{32}))-\d{4}-\d{2}-\d{2}\.(pdf|docx|csv)$/

/** One filtered assignment, identified by its stable assignment id and carrying the evidence version the review is bound to. */
export interface AssignmentPick {
  key: string
  user: string
  ref: string
  suffix: string
  evidence_version: string
  decision: Lifecycle
  user_group: string
}
export interface AssignmentSelection extends ContextInfo { items: AssignmentPick[]; total: number; truncated: boolean; limit: number }
export type BulkAction = 'Keep' | 'Remove' | 'Investigate'
export interface BulkOutcome { key: string; user: string; ref: string; reason: string }
export interface BulkResult { action: BulkAction; recorded: string[]; skipped: BulkOutcome[]; failed: BulkOutcome[]; tracked_actions?: string[]; revision: number }
