import { useSyncExternalStore } from 'react'
import { apiRequest } from '@/api/client'
import { downloadFile } from '@/api/sod'

/** Proposed access package: catalogue roles from Role Lookup and assigned release roles from Release Roles. Names only; it never changes SAP access. */
export type PackageSource = 'catalogue' | 'release'
export interface PackageItem { role: string; suffix: string; source: PackageSource }
export interface PackageState { defaultSuffix: string; items: PackageItem[] }
const KEY = 'sap-lens-access-package'

const read = (): PackageState => {
  try {
    const value = JSON.parse(sessionStorage.getItem(KEY) || 'null')
    if (value && typeof value.defaultSuffix === 'string' && Array.isArray(value.items)) {
      return { defaultSuffix: value.defaultSuffix.slice(0, 64), items: value.items.filter((item: PackageItem) => typeof item?.role === 'string' && typeof item.suffix === 'string')
        .map((item: PackageItem) => ({ role: item.role, suffix: item.suffix, source: item.source === 'release' ? 'release' as const : 'catalogue' as const })) }
    }
  } catch { /* the cart is a per-session convenience */ }
  return { defaultSuffix: '', items: [] }
}
let state = read()
const listeners = new Set<() => void>()
const commit = (next: PackageState) => {
  state = next
  try { sessionStorage.setItem(KEY, JSON.stringify(next)) } catch { /* optional */ }
  listeners.forEach((listener) => listener())
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }

export const accessPackage = {
  add: (role: string, source: PackageSource = 'catalogue') => {
    if (state.items.some((item) => item.role === role)) return true
    commit({ ...state, items: [...state.items, { role, suffix: '', source }] })
    return true
  },
  /** One commit for a bulk add; duplicates (also within the request) are skipped. */
  addMany: (roles: string[], source: PackageSource) => {
    const known = new Set(state.items.map((item) => item.role)), fresh: PackageItem[] = []
    for (const role of roles) if (!known.has(role)) { known.add(role); fresh.push({ role, suffix: '', source }) }
    if (fresh.length) commit({ ...state, items: [...state.items, ...fresh] })
    return { added: fresh.length, existing: new Set(roles).size - fresh.length }
  },
  remove: (role: string) => commit({ ...state, items: state.items.filter((item) => item.role !== role) }),
  clear: () => commit({ defaultSuffix: '', items: [] }),
  // Changing the default never touches explicit per-role suffixes.
  setDefault: (value: string) => commit({ ...state, defaultSuffix: value.toUpperCase().slice(0, 64) }),
  setSuffix: (role: string, value: string) => commit({ ...state, items: state.items.map((item) => (item.role === role ? { ...item, suffix: value.toUpperCase().slice(0, 64) } : item)) }),
}

export function useAccessPackage() {
  const current = useSyncExternalStore(subscribe, () => state)
  return { ...current, has: (role: string) => current.items.some((item) => item.role === role), ...accessPackage }
}

export interface PackageRow {
  role: string; description: string; suffix: string; suffix_source: 'override' | 'default' | 'none'; name: string | null; source: PackageSource
  status: 'ok' | 'needs_suffix' | 'ambiguous' | 'invalid' | 'unknown_role' | 'duplicate'; messages: string[]
  /** confirmed and unconfirmed names are valid SAP names (unconfirmed ones are not found in the imported catalogue); only those are copied or exported. */
  validation: 'confirmed' | 'unconfirmed' | 'invalid' | 'needs_suffix'; exportable: boolean
  /** False for an exact role without suffix variants: its name is kept and a suffix cannot be set. */
  suffix_eligible: boolean; suffix_note: string | null
  catalogue: { status: 'exact' | 'wildcard' | 'ambiguous' | 'unmapped'; candidates: string[] } | null
}
export interface PackagePreview { items: PackageRow[]; exportable: number }
export interface Naming { suffixes: { value: string; roles: number }[]; evidence_roles: number }

const body = (value: PackageState) => ({ default_suffix: value.defaultSuffix, items: value.items.map((item) => ({ role: item.role, suffix: item.suffix, source: item.source })) })
export const previewPackage = (value: PackageState) => apiRequest<PackagePreview>('/api/roles/package/preview', 'POST', body(value))
export const fetchNaming = () => apiRequest<Naming>('/api/roles/naming')
export const exportPackage = (value: PackageState) => downloadFile('/api/roles/package/export', { method: 'POST', body: body(value), namePattern: /^sap-lens-access-package-\d{4}-\d{2}-\d{2}\.csv$/, kind: 'csv', nativeCsv: 'save_role_package_csv' })
