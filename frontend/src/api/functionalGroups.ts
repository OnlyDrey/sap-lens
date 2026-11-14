import { apiRequest } from './client'

export type FunctionalGroup = { id: string; name: string; description: string; status: 'active' | 'archived'; created: string; modified: string; user_count: number; deletable: boolean; references: { members: number; rules: number; history: number } }
export type ClassificationStatus = 'Unassigned' | 'Confirmed' | 'Needs review'
export type GroupRef = { id: string; name: string; status: string }
export type Review = { change_id: string; reason: string; required_since: string }
/** One membership of a user: its own status and confirmation metadata (a user may hold several). */
export type Membership = { group_id: string; group: GroupRef; status: Exclude<ClassificationStatus, 'Unassigned'>; confirmed_at: string | null; confirmed_by: string; rationale: string; review: Review | null }
export type Classification = {
  username: string; revision: number
  /** User-level summary: Unassigned without memberships, Needs review when any membership needs it, otherwise Confirmed. */
  status: ClassificationStatus
  memberships: Membership[]; group_ids: string[]
  /** Compatibility fields, set only when the user has exactly one membership. */
  group_id: string | null; group: GroupRef | null; confirmed_at: string | null; confirmed_by: string; rationale: string; review: Review | null
}
export type GroupEvent = {
  id: string; event: string; username: string; previous_group: string | null; new_group: string | null; previous_status: ClassificationStatus
  new_status: ClassificationStatus; actor: string; timestamp: string; reason: string; change_id: string
}
export type SuggestedGroup = { group_id: string; group_name: string; rule_ids: string[]; reasons: string[]; already_member: boolean }
export type Suggestion = { status: 'none' | 'suggested'; groups: SuggestedGroup[]; matches: { rule_id: string; group_id: string; group_name: string; reasons: string[] }[] }
export type DirectoryContext = { match_status: string; department?: string; title?: string; site?: string; manager?: string; manager_email?: string } | null
export type UserClassification = { classification: Classification; history: { items: GroupEvent[]; total: number }; directory: DirectoryContext; suggestion: Suggestion | null }
export type Rule = {
  id: string; group_id: string; group_name: string; group_status: string; department: string; title_contains: string
  /** `contains` for new rules; rules created before multiple memberships keep `equals` until an administrator converts them. */
  department_mode: 'contains' | 'equals'; match_count?: number | null; not_linked_count?: number | null
}

const base = '/api/functional-groups'
export const groupsKey = ['functional-groups'] as const
export const fetchGroups = () => apiRequest<{ items: FunctionalGroup[] }>(base)
export const createGroup = (name: string, description: string) => apiRequest<FunctionalGroup>(base, 'POST', { name, description })
export const updateGroup = (id: string, patch: { name?: string; description?: string }) => apiRequest<FunctionalGroup>(`${base}/${id}`, 'PATCH', patch)
export const setGroupArchived = (id: string, archived: boolean) => apiRequest<FunctionalGroup>(`${base}/${id}/${archived ? 'archive' : 'restore'}`, 'POST')
export const deleteGroup = (id: string) => apiRequest<{ status: string; id: string; name: string }>(`${base}/${id}`, 'DELETE')
export const rulesKey = ['functional-group-rules'] as const
export const fetchRules = (counts = false) => apiRequest<{ items: Rule[] }>(`${base}/rules${counts ? '?counts=true' : ''}`)
export type RuleInput = { group_id: string; department: string; title_contains: string; department_mode: 'contains' | 'equals' }
export const addRule = (rule: RuleInput) => apiRequest<Rule>(`${base}/rules`, 'POST', rule)
export const updateRule = (id: string, rule: RuleInput) => apiRequest<Rule>(`${base}/rules/${id}`, 'PUT', rule)
export type RuleMatch = { username: string; full_name: string; department: string; title: string; groups: GroupRef[]; already_member: boolean }
export type RuleMatches = { rule: Rule; total: number; items: RuleMatch[]; offset: number; limit: number; not_linked_total: number; not_linked: { full_name: string; department: string; title: string; reason: string }[]; data_revision: string }
export const fetchRuleMatches = (id: string, params: { search: string; only_new: boolean; offset: number; limit: number }) =>
  apiRequest<RuleMatches>(`${base}/rules/${id}/matches?${new URLSearchParams({ search: params.search, only_new: String(params.only_new), offset: String(params.offset), limit: String(params.limit) })}`)
export const fetchRuleSelection = (id: string, params: { search: string; only_new: boolean }) =>
  apiRequest<{ total: number; usernames: string[]; truncated: boolean; limit: number; data_revision: string }>(`${base}/rules/${id}/matches/selection?${new URLSearchParams({ search: params.search, only_new: String(params.only_new) })}`)

export type GroupMember = { username: string; full_name: string; department: string; title: string; identity: 'matched' | 'unmatched' | 'not_in_import'; status: Exclude<ClassificationStatus, 'Unassigned'>
  confirmed_at: string | null; confirmed_by: string; revision: number; review: Review | null; other_groups: string[] }
export type GroupMembers = { group: GroupRef; total: number; items: GroupMember[]; offset: number; limit: number }
export const fetchGroupMembers = (id: string, params: { search: string; status: string; offset: number; limit: number }) =>
  apiRequest<GroupMembers>(`${base}/${id}/members?${new URLSearchParams({ search: params.search, status: params.status, offset: String(params.offset), limit: String(params.limit) })}`)
export type MembershipRequest = { username: string; group_id: string; rationale: string; reviewer: string; expected_revision: number; change_id?: string }
export const addMembership = (body: MembershipRequest) => apiRequest<{ classification: Classification; outcome: 'added' | 'reconfirmed' | 'unchanged' }>(`${base}/memberships`, 'POST', body)
export const removeMembership = (body: MembershipRequest) => apiRequest<{ classification: Classification }>(`${base}/memberships/remove`, 'POST', body)
export const deleteRule = (id: string) => apiRequest<{ status: string }>(`${base}/rules/${id}`, 'DELETE')
export const fetchUserClassification = (username: string) => apiRequest<UserClassification>(`${base}/users/${encodeURIComponent(username)}`)
export const saveClassification = (username: string, body: { group_id: string | null; rationale: string; reviewer: string; expected_revision: number; change_id?: string }) =>
  apiRequest<Classification>(`${base}/users/${encodeURIComponent(username)}`, 'PUT', body)

export type OrganizationOption = { value: string; label: string; count: number }
export const organizationKey = ['functional-group-options'] as const
export const fetchOrganizationOptions = () => apiRequest<{ functional_groups: OrganizationOption[]; managers: OrganizationOption[] }>(`${base}/options`)

export type RoleFrequency = { role: string; users: number; eligible: number; frequency: number; kind: 'common' | 'shared' | 'uncommon' | 'not compared'; holders: string[] }
export type ComparedUser = { username: string; full_name: string; account_status: string; roles: number }
export type Analysis = {
  group: { id: string; name: string; status: string }; members: number; eligible: number; not_in_import: string[]; distinct_roles: number; common_roles: number
  deviations: number; comparable: boolean; limitations: string[]; roles: RoleFrequency[]
  users: { username: string; roles: number; additional_roles: string[]; missing_common_roles: string[] }[]
  compared: ComparedUser[]
  method: { common_at: number; uncommon_at: number; min_members: number; note: string }
}
export const fetchAnalysis = (id: string) => apiRequest<Analysis>(`${base}/analysis/${id}`)

export type BulkItem = { username: string; revision: number; group_ids: string[]; group_names: string[]; additions: string[]; existing: string[] }
export type BulkPreview = {
  groups: GroupRef[]; items: BulkItem[]; counts: { users: number; additions: number; existing: number; unassigned: number }; missing: string[]; requested: number; data_revision: string
}
export type BulkResult = {
  status: 'applied' | 'partial' | 'rejected'; group_names: string[]; data_revision: string
  applied: { username: string; added: string[]; reconfirmed: string[]; unchanged: string[] }[]; unchanged: { username: string }[]
  conflicts: { username: string; reason: string; detail: string }[]; rejected: { username: string; reason: string; detail: string }[]
}
export const bulkPreview = (group_ids: string[], usernames: string[]) => apiRequest<BulkPreview>(`${base}/bulk/preview`, 'POST', { group_ids, usernames })
export const bulkAssign = (body: { group_ids: string[]; usernames: string[]; expected: Record<string, number>; rationale: string; reviewer: string; operation_id: string; data_revision: string }) =>
  apiRequest<BulkResult>(`${base}/bulk`, 'POST', body)
