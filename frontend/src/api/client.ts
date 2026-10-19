import axios from 'axios'
import type {
  ModuleInfo,
  RoleSummary,
  RoleDetail,
  ComparisonResult,
  HealthResponse,
} from './types'

const apiClient = axios.create({
  baseURL: import.meta.env.DEV
    ? import.meta.env.VITE_API_URL || 'http://localhost:8000'
    : '',
  headers: {
    'Content-Type': 'application/json',
  },
})

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error)) {
      const message =
        (error.response?.data as { detail?: string })?.detail ??
        error.message ??
        'Unexpected error'

      return Promise.reject(new Error(message))
    }

    return Promise.reject(error)
  }
)

export async function fetchModules(): Promise<ModuleInfo[]> {
  const { data } = await apiClient.get<ModuleInfo[]>('/api/modules')
  return data
}

export async function fetchRoles(
  module?: string,
  search?: string
): Promise<RoleSummary[]> {
  const params: Record<string, string> = {}

  if (module) params.module = module
  if (search) params.search = search

  const { data } = await apiClient.get<RoleSummary[]>('/api/roles', { params })
  return data
}

export async function fetchRoleDetail(
  roleName: string
): Promise<RoleDetail> {
  const { data } = await apiClient.get<RoleDetail>(
    `/api/roles/${encodeURIComponent(roleName)}`
  )

  return data
}

export async function compareRoles(
  roleNames: string[]
): Promise<ComparisonResult> {
  const { data } = await apiClient.post<ComparisonResult>(
    '/api/compare',
    { roles: roleNames }
  )

  return data
}

export async function refreshData(): Promise<HealthResponse> {
  const { data } = await apiClient.post<HealthResponse>('/api/refresh')
  return data
}

export async function fetchRolesByTcode(
  tcode: string
): Promise<RoleSummary[]> {
  const { data } = await apiClient.get<RoleSummary[]>(
    '/api/roles',
    { params: { tcode } }
  )

  return data
}