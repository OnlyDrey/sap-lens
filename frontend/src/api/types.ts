export interface TCode {
  tcode: string
  ttext: string | null
  alternate_texts?: string[]
  assignment_sources?: {child_agr:string|null;parent_agr:string|null;effective_role:string|null}[]
}

export interface SingleRole {
  assignment_kind?: string
  alternate_descriptions?: string[]
  function_key?: string
  module_name?: string
  child_agr: string
  child_agr_text: string | null
  tcodes: TCode[]
}

export interface SingleRoleInfo {
  function_key?: string
  module_name?: string
  child_agr: string
  child_agr_text: string | null
  tcode_count: number
}

export interface RoleSummary {
  module_ambiguous?: boolean
  agr_name: string
  text: string | null
  function_key: string | null
  module_name: string | null
  tcode_count: number
  single_role_count?: number
  matching_tcodes?: string[]
}

export interface RoleDetail extends RoleSummary {
  relationships?: {child_agr:string|null; parent_agr:string|null; effective_role:string|null}[]
  alternate_descriptions?: string[]
  analysis?: Record<string,unknown>
  single_roles: SingleRole[]
}

export interface ModuleInfo {
  enabled?: boolean
  icon?: string
  color?: string
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