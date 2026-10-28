import { useSyncExternalStore } from 'react'
import { apiRequest } from '@/api/client'
import { downloadFile } from '@/api/sod'

/** Proposed access package: catalogue roles collected from Role Lookup. Names only; it never changes SAP access. */
export interface PackageItem { role: string; suffix: string }
export interface PackageState { defaultSuffix: string; items: PackageItem[] }
export const PACKAGE_LIMIT = 200
const KEY = 'sap-lens-access-package'

const read = (): PackageState => {
  try {
    const value = JSON.parse(sessionStorage.getItem(KEY) || 'null')
    if (value && typeof value.defaultSuffix === 'string' && Array.isArray(value.items)) {
      return { defaultSuffix: value.defaultSuffix.slice(0, 64), items: value.items.filter((item: PackageItem) => typeof item?.role === 'string' && typeof item.suffix === 'string').slice(0, PACKAGE_LIMIT) }
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
  add: (role: string) => {
    if (state.items.some((item) => item.role === role)) return true
    if (state.items.length >= PACKAGE_LIMIT) return false
    commit({ ...state, items: [...state.items, { role, suffix: '' }] })
    return true
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
  role: string; description: string; suffix: string; suffix_source: 'override' | 'default' | 'none'; name: string | null
  status: 'ok' | 'needs_suffix' | 'ambiguous' | 'invalid' | 'unknown_role' | 'duplicate'; messages: string[]
  catalogue: { status: 'exact' | 'wildcard' | 'ambiguous' | 'unmapped'; candidates: string[] } | null
}
export interface PackagePreview { items: PackageRow[]; exportable: number; max_roles: number }
export interface Naming { suffixes: { value: string; roles: number }[]; evidence_roles: number }

const body = (value: PackageState) => ({ default_suffix: value.defaultSuffix, items: value.items.map((item) => ({ role: item.role, suffix: item.suffix })) })
export const previewPackage = (value: PackageState) => apiRequest<PackagePreview>('/api/roles/package/preview', 'POST', body(value))
export const fetchNaming = () => apiRequest<Naming>('/api/roles/naming')
export const exportPackage = (value: PackageState) => downloadFile('/api/roles/package/export', { method: 'POST', body: body(value), namePattern: /^sap-lens-access-package-\d{4}-\d{2}-\d{2}\.csv$/, kind: 'csv', nativeCsv: 'save_role_package_csv' })
