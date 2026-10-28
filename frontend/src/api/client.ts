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

/** Failure classes the UI can explain: network (no response), server (5xx), client (4xx) and format (a response that is not the expected JSON). */
export class ApiError extends Error {
  constructor(message: string, readonly kind: 'network' | 'server' | 'client' | 'format', readonly status = 0) {
    super(message)
    this.name = 'ApiError'
  }
}

function problemDetail(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return (detail as {loc?:string[];msg?:string}[]).slice(0,3).map(e=>`${(e.loc||[]).slice(1).join('.')}: ${e.msg||'Invalid value'}`).join('; ')
  if (status >= 500) return `SAP Lens could not complete the request (server error ${status}). Retry; if it persists, check the application logs.`
  return `Request failed (${status})`
}

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
    }) } catch { throw new ApiError('SAP Lens could not connect. Retry or close and reopen the application.', 'network') }
    finally { if(timer)clearTimeout(timer) }
    // Read text first: a proxy or crash page is not JSON and must not surface as a parser exception.
    const text = await response.text().catch(() => '')
    let data: unknown
    let parsed = true
    try { data = text === '' ? undefined : JSON.parse(text) } catch { parsed = false }
    if (!response.ok) throw new ApiError(problemDetail(parsed ? data : undefined, response.status), response.status >= 500 ? 'server' : 'client', response.status)
    if (!parsed) throw new ApiError('SAP Lens received an unexpected response instead of data. Retry, or reload the application.', 'format', response.status)
    return { data: (data ?? {}) as T }
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

export async function refreshData(): Promise<HealthResponse & {refresh?: import('@/components/Shared/RefreshReport').RefreshSummary}> {
  const { data } = await apiClient.post<HealthResponse & {refresh?: import('@/components/Shared/RefreshReport').RefreshSummary}>('/api/refresh')
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
