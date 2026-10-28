import { useSyncExternalStore } from 'react'

export interface ExportNotice { id: number; kind: 'success' | 'info' | 'error'; message: string }
const FADE_MS = 6000
let current: ExportNotice | null = null
let counter = 0
let timer: ReturnType<typeof setTimeout> | undefined
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((listener) => listener())

/** One app-wide notice for every export. Success and info fade on their own; errors stay until dismissed. */
export function announceExport(notice: Omit<ExportNotice, 'id'>) {
  clearTimeout(timer)
  current = { ...notice, id: ++counter }
  if (notice.kind !== 'error') timer = setTimeout(dismissExport, FADE_MS)
  emit()
}
export function dismissExport() {
  clearTimeout(timer)
  current = null
  emit()
}
export function useExportNotice(): ExportNotice | null {
  return useSyncExternalStore((listener) => { listeners.add(listener); return () => { listeners.delete(listener) } }, () => current)
}
