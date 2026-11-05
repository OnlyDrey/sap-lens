import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { Button } from '@/components/Shared/Button'
import { Checkbox, FormField, controlClass } from '@/components/Shared/Controls'
import { StatusBadge } from '@/components/Shared/Presentation'

type Category = { count: number; bytes: number; oldest_days: number }
type Preview = {
  months: number; count: number; bytes: number; digest: string; categories: Record<string, Category>
  protected: { referenced: number; recent: number; kept_newest: number; unclassified: number }
  sample: { category: string; id: string; bytes: number; age_days: number }[]; truncated: boolean
}
type Retention = {
  policy: { enabled: boolean; months: number }
  state: 'disabled' | 'approved' | 'awaiting_approval'
  approval: { by: string; at: string; months: number; valid: boolean } | null
  last_check: string
  last_preview: { count?: number; bytes?: number }
  history: { at: string; trigger: string; status: string; months: number; removed: Record<string, number>; bytes: number; by: string; message: string }[]
  scope: string[]
  protected_note: string
}

const megabytes = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`
const labels = { disabled: 'Retention off', approved: 'Automatic cleanup approved', awaiting_approval: 'Waiting for administrator approval' }

/** Data retention: superseded source snapshots only. Nothing is removed until an administrator has seen the preview and approved it once. */
export function DataRetention() {
  const client = useQueryClient()
  const status = useQuery({ queryKey: ['retention'], queryFn: () => apiRequest<Retention>('/api/retention'), retry: false })
  const [months, setMonths] = useState<number | null>(null)
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const current = status.data
  if (!current) return null
  const shownMonths = months ?? current.policy.months
  const shownEnabled = enabled ?? current.policy.enabled
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await action()
      await client.invalidateQueries({ queryKey: ['retention'] })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The request could not be completed.')
    } finally {
      setBusy(false)
    }
  }
  const dirty = shownMonths !== current.policy.months || shownEnabled !== current.policy.enabled
  return (
    <section aria-label="Data retention" className="grid gap-3 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="m-0 text-sm font-semibold">Data retention</h3>
        <StatusBadge>{labels[current.state]}</StatusBadge>
        {current.last_check && <span className="text-xs text-muted">Last check {new Date(current.last_check).toLocaleString()}</span>}
      </div>
      <p className="ui-description">
        Checked daily. Only superseded, unreferenced source snapshots and diagnostic copies older than the retention period can be removed. {current.protected_note}
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <Checkbox checked={shownEnabled} onChange={event => setEnabled(event.target.checked)}>Check and clean up automatically</Checkbox>
        <FormField label="Retention period (months)" description="Between 6 and 120. Default 24. Shortening it needs a new approval.">
          <input className={controlClass} type="number" min={6} max={120} value={shownMonths} onChange={event => setMonths(Math.min(120, Math.max(6, Math.round(Number(event.target.value) || 24))))} />
        </FormField>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button disabled={!dirty || busy} onClick={() => void run(async () => { await apiRequest('/api/retention/policy', 'PUT', { enabled: shownEnabled, months: shownMonths }); setMonths(null); setEnabled(null); setPreview(null) })}>Save retention settings</Button>
        <Button disabled={busy || dirty} onClick={() => void run(async () => { setConfirmed(false); setPreview(await apiRequest<Preview>('/api/retention/preview')) })}>Preview cleanup</Button>
      </div>
      {preview && (
        <div className="grid gap-2" aria-label="Cleanup preview">
          <p className="ui-description">
            {preview.count === 0 ? `Nothing older than ${preview.months} months can be removed.` : `${preview.count} item(s), ${megabytes(preview.bytes)}, older than ${preview.months} months would be removed.`} Kept: {preview.protected.referenced} still referenced,
            {' '}{preview.protected.kept_newest} newest previous revisions, {preview.protected.recent} within the period, {preview.protected.unclassified} unrecognised.
          </p>
          {preview.count > 0 && (
            <table className="text-xs">
              <thead><tr><th scope="col">Category</th><th scope="col">Items</th><th scope="col">Size</th><th scope="col">Oldest</th></tr></thead>
              <tbody>{Object.entries(preview.categories).map(([name, row]) => <tr key={name}><td>{name}</td><td>{row.count}</td><td>{megabytes(row.bytes)}</td><td>{Math.round(row.oldest_days / 30)} months</td></tr>)}</tbody>
            </table>
          )}
          {current.state !== 'approved' && (
            <div className="grid gap-2">
              <Checkbox checked={confirmed} onChange={event => setConfirmed(event.target.checked)}>I reviewed this preview and approve removing these items now and automatically in the future</Checkbox>
              <div><Button disabled={!confirmed || busy} onClick={() => void run(async () => { await apiRequest('/api/retention/approve', 'POST', { confirm: true, preview_digest: preview.digest }); setPreview(null); setConfirmed(false) })}>Approve and clean up</Button></div>
            </div>
          )}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {current.history.length > 0 && (
        <details>
          <summary>Retention history</summary>
          <ul className="m-0 grid gap-1 pl-4 text-xs">
            {current.history.map(entry => <li key={entry.at + entry.trigger}>{new Date(entry.at).toLocaleString()} · {entry.trigger} · {entry.status}{entry.by ? ` · ${entry.by}` : ''}{entry.bytes ? ` · ${megabytes(entry.bytes)}` : ''}{entry.message ? ` · ${entry.message}` : ''}</li>)}
          </ul>
        </details>
      )}
    </section>
  )
}
