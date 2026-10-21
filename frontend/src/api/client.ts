import type {
  ModuleInfo,
  RoleSummary,
  RoleDetail,
  ComparisonResult,
  HealthResponse,
} from './types'

// The desktop capability is delivered in a fragment (never sent in HTTP requests).
// Keep it in the private window session and remove it from the visible URL immediately.
const fragment = new URLSearchParams(window.location.hash.slice(1))
let desktopSession = fragment.get('session')
try {
  desktopSession ||= sessionStorage.getItem('sap-lens-session')
  if (desktopSession) sessionStorage.setItem('sap-lens-session', desktopSession)
} catch { /* The initial launch still works when browser session storage is disabled. */ }
if (fragment.has('session')) window.history.replaceState(null, '', window.location.pathname + window.location.search)

export function applicationToken(): string { return desktopSession || '1' }

// Same-origin fetch keeps the desktop bundle small and needs no HTTP client dependency.
const apiClient = {
  async request<T>(path: string, method: string, body?: unknown): Promise<{ data: T }> {
    let response: Response
    const controller = new AbortController()
    const timer = method === 'GET' ? setTimeout(()=>controller.abort(),10000) : undefined
    try { response = await fetch(path, {
      method, signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-SAP-Lens': applicationToken() },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    }) } catch { throw new Error('SAP Lens could not connect. Retry or close and reopen the application.') }
    finally { if(timer)clearTimeout(timer) }
    const data = await response.json()
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail)
        ? (data.detail as {loc?:string[];msg?:string}[]).slice(0,3).map(e=>`${(e.loc||[]).slice(1).join('.')}: ${e.msg||'Invalid value'}`).join('; ')
        : `Request failed (${response.status})`
      throw new Error(detail)
    }
    return { data: data as T }
  },
  get<T>(path: string, options?: { params: Record<string, string> }) {
    const query = options ? `?${new URLSearchParams(options.params)}` : ''
    return this.request<T>(path + query, 'GET')
  },
  post<T>(path: string, body?: unknown) {
    return this.request<T>(path, 'POST', body)
  },
}

export async function fetchModules(): Promise<ModuleInfo[]> {
  const { data } = await apiClient.get<ModuleInfo[]>('/api/modules')
  return data
}

export async function fetchRoles(
  module?: string,
  search?: string
): Promise<RoleSummary[]> {
  const params: Record<string, string> = {}

  if (module) params.function_key = module
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
export async function apiRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  return (await apiClient.request<T>(path, method, body)).data
}
