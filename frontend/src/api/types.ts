export interface TCode {
  tcode: string
  ttext: string | null
}

export interface SingleRole {
  child_agr: string
  child_agr_text: string | null
  tcodes: TCode[]
}

export interface SingleRoleInfo {
  child_agr: string
  child_agr_text: string | null
  tcode_count: number
}

export interface RoleSummary {
  agr_name: string
  text: string | null
  function_key: string | null
  module_name: string | null
  tcode_count: number
  single_role_count?: number
  matching_tcodes?: string[]
}

export interface RoleDetail extends RoleSummary {
  single_roles: SingleRole[]
}

export interface ModuleInfo {
  function_key: string
  module_name: string
}

export interface PairwiseOverlap {
  role_a: string
  role_b: string
  shared_count: number
}

export interface ComparisonRole {
  agr_name: string
  text: string | null
  function_key: string | null
  module_name: string | null
  tcode_count: number
  single_role_count: number
  matching_tcodes: string[]
  exclusive_single_roles: SingleRoleInfo[]
  unique_tcodes: TCode[]
}

export interface ComparisonResult {
  roles: ComparisonRole[]
  shared_single_roles: SingleRoleInfo[]
  pairwise_single_overlaps: PairwiseOverlap[]
  shared_tcodes: TCode[]
  pairwise_overlaps: PairwiseOverlap[]
}

export interface HealthResponse {
  status: string
  cached_roles: number
  last_loaded: string | null
}