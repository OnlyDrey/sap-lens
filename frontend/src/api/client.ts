import { recordSession, sessionSnapshot } from './session'
import { blocksRequests } from '@/lib/sessionState'
import { RevisionTracker } from '@/lib/dataRevision'
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
let sessionRole: string | null = null
export function setSessionRole(role: string | null) { sessionRole = role }
export function configurationPath() { return sessionRole && sessionRole !== 'administrator' ? '/api/presentation' : '/api/configuration' }
export function applicationHeaders(): Record<string,string> {
  const csrf = document.cookie.split('; ').find(value=>value.startsWith('sap-lens-csrf='))?.slice('sap-lens-csrf='.length)
  return {'X-SAP-Lens': applicationToken(), ...(csrf ? {'X-SAP-Lens-CSRF': decodeURIComponent(csrf)} : {})}
}
const STALE_MESSAGE = 'SAP Lens restarted and your previous local session is no longer valid. Reconnect to continue.'

/** Failure classes the UI can explain: network (no response), server (5xx), client (4xx) and format (a response that is not the expected JSON). */
export class ApiError extends Error {
  constructor(message: string, readonly kind: 'network' | 'server' | 'client' | 'format' | 'session' | 'authentication' | 'permission', readonly status = 0, readonly detail?: unknown) {
    super(message)
    this.name = 'ApiError'
  }
}

function problemDetail(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') return (detail as { message: string }).message
  if (Array.isArray(detail)) return (detail as {loc?:string[];msg?:string}[]).slice(0,3).map(e=>`${(e.loc||[]).slice(1).join('.')}: ${e.msg||'Invalid value'}`).join('; ')
  if (status >= 500) return `SAP Lens could not complete the request (server error ${status}). Retry; if it persists, check the application logs.`
  return `Request failed (${status})`
}

/** Top-level navigation obtains a fresh capability through the guarded root document (the backend verifies the navigation, the exact loopback host and the client address).
 * History carries only existing safe view/filter state; failed writes are never replayed. */
export function recoverTrustedSession(){
 recordSession('reconnect')
 const hash=location.hash.startsWith('#/')?location.hash:''
 history.replaceState(history.state,'','/'+location.search+hash)
 // A reload requests the guarded root document again; the backend answers a verified navigation with the current capability. (A replace() to the same
 // address would be a fragment navigation and send nothing.)
 location.reload()
}

// Every API response names the revision of the data it was built from. A response older than one already seen is never allowed to stand in for newer data
// (a GET is repeated once; the server then answers from the current data), and a newer one tells the application that data changed, whoever changed it.
const revisions = new RevisionTracker()
const revisionListeners = new Set<() => void>()
export function onDataRevision(listener: () => void): () => void {
  revisionListeners.add(listener)
  return () => { revisionListeners.delete(listener) }
}

// Same-origin fetch keeps the desktop bundle small and needs no HTTP client dependency.
const apiClient = {
  async request<T>(path: string, method: string, body?: unknown, repeated = false): Promise<{ data: T }> {
    // While the session is known to be invalid nothing is sent: no failing request storm, no write queued for later replay.
    if (blocksRequests(sessionSnapshot())) throw new ApiError(STALE_MESSAGE, 'session', 403)
    let response: Response
    const controller = new AbortController()
    const timer = method === 'GET' ? setTimeout(()=>controller.abort(),10000) : undefined
    try { response = await fetch(path, {
      method, signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...applicationHeaders() },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    }) } catch (error) { recordSession('network'); throw new ApiError(error instanceof DOMException&&error.name==='AbortError' ? 'The read request timed out. The backend may still be running; retry this read.' : 'SAP Lens could not connect. Retry and check the backend service if the problem persists.', 'network') }
    finally { if(timer)clearTimeout(timer) }
    // Read text first: a proxy or crash page is not JSON and must not surface as a parser exception.
    const text = await response.text().catch(() => '')
    let data: unknown
    let parsed = true
    try { data = text === '' ? undefined : JSON.parse(text) } catch { parsed = false }
    if (response.ok) recordSession('success')
    const seen = revisions.observe(response.headers.get('X-Data-Revision'))
    if (seen === 'stale' && method === 'GET' && !repeated) return this.request<T>(path, method, body, true)
    if (seen === 'newer') for (const listener of [...revisionListeners]) listener()
    if (!response.ok) {
      const reference=response.headers.get('X-Request-ID')||''
      if(response.status===401 && sessionRole) window.dispatchEvent(new Event('sap-lens-sign-in-required'))
      if(response.status===403&&(data as {code?:string}|undefined)?.code==='stale_session'){recordSession('stale');throw new ApiError(STALE_MESSAGE,'session',403)}
      throw new ApiError(problemDetail(parsed ? data : undefined, response.status)+(/^[a-f0-9]{32}$/.test(reference)?` Reference: ${reference}`:''), response.status===401?'authentication':response.status===403?'permission':response.status >= 500 ? 'server' : 'client', response.status, parsed ? (data as { detail?: unknown } | undefined)?.detail : undefined)
    }
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

export async function apiRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  return (await apiClient.request<T>(path, method, body)).data
}
