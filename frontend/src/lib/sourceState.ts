/** Honest load state of one data source, derived from what the backend actually holds, never from configuration alone. */
export type SourceStateKey = 'not_configured' | 'disabled' | 'loading' | 'refreshing' | 'ready' | 'failed' | 'unavailable'
export interface SourceStateInput { configured?: boolean; enabled?: boolean; loaded: boolean; loading: boolean; error: string | null }
export interface SourceStateResult { key: SourceStateKey; label: string; tone: 'success' | 'warning' | 'error' | 'info' | 'neutral'; detail?: string }

export function sourceState(source: SourceStateInput): SourceStateResult {
  if (source.configured === false) return { key: 'not_configured', label: 'Not configured', tone: 'neutral' }
  if (source.enabled === false) return { key: 'disabled', label: 'Disabled', tone: 'neutral', detail: source.loaded ? 'Validated data is retained.' : undefined }
  if (source.loading) return source.loaded ? { key: 'refreshing', label: 'Refreshing', tone: 'info' } : { key: 'loading', label: 'Loading', tone: 'info' }
  if (source.loaded) return source.error ? { key: 'ready', label: 'Ready', tone: 'warning', detail: 'The last check failed; previously validated data is retained.' } : { key: 'ready', label: 'Ready', tone: 'success' }
  if (source.error) return { key: 'failed', label: 'Failed', tone: 'error', detail: source.error.replace(/_/g, ' ') }
  return { key: 'unavailable', label: 'Not loaded', tone: 'neutral' }
}
