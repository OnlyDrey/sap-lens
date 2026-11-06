import { apiRequest } from './client'

export type FunctionalGroup = { id: string; name: string; description: string; status: 'active' | 'archived'; created: string; modified: string; user_count: number }
export type ClassificationStatus = 'Unassigned' | 'Confirmed' | 'Needs review'
export type Classification = {
  username: string; group_id: string | null; group: { id: string; name: string; status: string } | null; status: ClassificationStatus
  revision: number; confirmed_at: string | null; confirmed_by: string; rationale: string
  review: { change_id: string; reason: string; required_since: string } | null
}
export type GroupEvent = {
  id: string; event: string; username: string; previous_group: string | null; new_group: string | null; previous_status: ClassificationStatus
  new_status: ClassificationStatus; actor: string; timestamp: string; reason: string; change_id: string
}
export type Suggestion = { status: 'none' | 'suggested' | 'ambiguous'; matches: { rule_id: string; group_id: string; group_name: string; reasons: string[] }[] }
export type DirectoryContext = { match_status: string; department?: string; title?: string; site?: string; manager?: string; manager_email?: string } | null
export type UserClassification = { classification: Classification; history: { items: GroupEvent[]; total: number }; directory: DirectoryContext; suggestion: Suggestion | null }
export type Rule = { id: string; group_id: string; group_name: string; group_status: string; department: string; title_contains: string }

const base = '/api/functional-groups'
export const groupsKey = ['functional-groups'] as const
export const fetchGroups = () => apiRequest<{ items: FunctionalGroup[] }>(base)
export const createGroup = (name: string, description: string) => apiRequest<FunctionalGroup>(base, 'POST', { name, description })
export const updateGroup = (id: string, patch: { name?: string; description?: string }) => apiRequest<FunctionalGroup>(`${base}/${id}`, 'PATCH', patch)
export const setGroupArchived = (id: string, archived: boolean) => apiRequest<FunctionalGroup>(`${base}/${id}/${archived ? 'archive' : 'restore'}`, 'POST')
export const fetchRules = () => apiRequest<{ items: Rule[] }>(`${base}/rules`)
export const addRule = (group_id: string, department: string, title_contains: string) => apiRequest<Rule>(`${base}/rules`, 'POST', { group_id, department, title_contains })
export const deleteRule = (id: string) => apiRequest<{ status: string }>(`${base}/rules/${id}`, 'DELETE')
export const fetchUserClassification = (username: string) => apiRequest<UserClassification>(`${base}/users/${encodeURIComponent(username)}`)
export const saveClassification = (username: string, body: { group_id: string | null; rationale: string; reviewer: string; expected_revision: number; change_id?: string }) =>
  apiRequest<Classification>(`${base}/users/${encodeURIComponent(username)}`, 'PUT', body)

export type OrganizationOption = { value: string; label: string; count: number }
export const organizationKey = ['functional-group-options'] as const
export const fetchOrganizationOptions = () => apiRequest<{ functional_groups: OrganizationOption[]; managers: OrganizationOption[] }>(`${base}/options`)

export type RoleFrequency = { role: string; users: number; eligible: number; frequency: number; kind: 'common' | 'shared' | 'uncommon' | 'not compared' }
export type Analysis = {
  group: { id: string; name: string; status: string }; members: number; eligible: number; not_in_import: string[]; distinct_roles: number; common_roles: number
  deviations: number; comparable: boolean; limitations: string[]; roles: RoleFrequency[]
  users: { username: string; roles: number; additional_roles: string[]; missing_common_roles: string[] }[]
  method: { common_at: number; uncommon_at: number; min_members: number; note: string }
}
export const fetchAnalysis = (id: string) => apiRequest<Analysis>(`${base}/analysis/${id}`)

export type BulkItem = { username: string; state: 'unassigned' | 'same' | 'other'; revision: number; group_id: string | null; group_name: string | null }
export type BulkPreview = { group: { id: string; name: string; status: string }; items: BulkItem[]; counts: Record<'unassigned' | 'same' | 'other', number>; missing: string[]; requested: number; data_revision: string }
export type BulkResult = {
  status: 'applied' | 'partial' | 'rejected'; group_name: string; data_revision: string
  applied: { username: string; previous_group: string | null }[]; unchanged: { username: string }[]
  conflicts: { username: string; reason: string; detail: string }[]; rejected: { username: string; reason: string; detail: string }[]
}
export const bulkPreview = (group_id: string, usernames: string[]) => apiRequest<BulkPreview>(`${base}/bulk/preview`, 'POST', { group_id, usernames })
export const bulkAssign = (body: { group_id: string; usernames: string[]; expected: Record<string, number>; replace_existing: boolean; rationale: string; reviewer: string; operation_id: string; data_revision: string }) =>
  apiRequest<BulkResult>(`${base}/bulk`, 'POST', body)
