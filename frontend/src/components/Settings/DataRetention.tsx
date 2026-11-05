import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { Button } from '@/components/Shared/Button'
import { Checkbox, FormField, controlClass } from '@/components/Shared/Controls'
import { StatusBadge } from '@/components/Shared/Presentation'

type Name = 'source' | 'review'
type Category = { count: number; bytes?: number; digest: string; months: number }
type SourcePreview = Category & {
  categories: Record<string, { count: number; bytes: number; oldest_days: number }>
  protected: { referenced: number; recent: number; kept_newest: number; unclassified: number; unrecognised: number }
}
type ReviewPreview = Category & {
  protected: number; reasons: Record<string, number>
  sample: { name: string; state: string; completed: string; age_days: number; decisions: number; actions: number }[]
  protected_sample: { name: string; state: string; reason: string }[]
}
type State = { months: number; state: 'disabled' | 'approved' | 'awaiting_approval'; approval: { by: string; at: string; months: number; valid: boolean } | null }
type Retention = {
  policy: { enabled: boolean; months: number; review_months: number }
  categories: Record<Name, State>
  last_check: string
  quiet_until: string
  history: { at: string; trigger: string; status: string; category: Name; months: number; by: string; message: string; bytes: number }[]
  scope: Record<Name, string[]>
  protected_note: string
}

const megabytes = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`
const labels = { disabled: 'Retention off', approved: 'Automatic cleanup approved', awaiting_approval: 'Waiting for administrator approval' }
const titles: Record<Name, string> = { source: 'Source retention', review: 'Review retention' }

/** Data retention in two separate categories. Nothing is removed until an administrator has seen the preview of that category and approved it once. */
export function DataRetention() {
  const client = useQueryClient()
  const status = useQuery({ queryKey: ['retention'], queryFn: () => apiRequest<Retention>('/api/retention'), retry: false })
  const [months, setMonths] = useState<Record<Name, number | null>>({ source: null, review: null })
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [preview, setPreview] = useState<Partial<Record<Name, SourcePreview | ReviewPreview>>>({})
  const [confirmed, setConfirmed] = useState<Partial<Record<Name, boolean>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const current = status.data
  if (!current) return null
  const shown = (name: Name) => months[name] ?? current.categories[name].months
  const shownEnabled = enabled ?? current.policy.enabled
  const dirty = shown('source') !== current.policy.months || shown('review') !== current.policy.review_months || shownEnabled !== current.policy.enabled
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
  const bound = (value: string) => Math.min(120, Math.max(6, Math.round(Number(value) || 24)))
  return (
    <section aria-label="Data retention" className="grid gap-3 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="m-0 text-sm font-semibold">Data retention</h3>
        {current.last_check && <span className="text-xs text-muted">Last check {new Date(current.last_check).toLocaleString()}</span>}
        {current.quiet_until && new Date(current.quiet_until) > new Date() && <StatusBadge>No cleanup until {new Date(current.quiet_until).toLocaleDateString()} (after a restore)</StatusBadge>}
      </div>
      <p className="ui-description">Checked daily. Source and review records are separate categories with their own period and their own approval. {current.protected_note}</p>
      <Checkbox checked={shownEnabled} onChange={event => setEnabled(event.target.checked)}>Check and clean up automatically</Checkbox>
      <div className="grid gap-3 lg:grid-cols-2">
        {(['source', 'review'] as Name[]).map(name => {
          const category = current.categories[name]
          const found = preview[name]
          return (
            <section key={name} aria-label={titles[name]} className="grid content-start gap-2 rounded-md border border-line p-3">
              <div className="flex flex-wrap items-center gap-2"><h4 className="m-0 text-sm font-semibold">{titles[name]}</h4><StatusBadge>{labels[category.state]}</StatusBadge></div>
              <ul className="m-0 pl-4 text-xs text-muted">{current.scope[name].map(item => <li key={item}>{item}</li>)}</ul>
              <FormField label={`${titles[name]} period (months)`} description="Between 6 and 120. Default 24. Shortening it needs a new approval.">
                <input className={controlClass} type="number" min={6} max={120} value={shown(name)} onChange={event => setMonths(previous => ({ ...previous, [name]: bound(event.target.value) }))} />
              </FormField>
              <div><Button disabled={busy || dirty} onClick={() => void run(async () => { setConfirmed(previous => ({ ...previous, [name]: false })); setPreview(previous => ({ ...previous, [name]: undefined })); const result = await apiRequest<SourcePreview | ReviewPreview>(`/api/retention/preview?category=${name}`); setPreview(previous => ({ ...previous, [name]: result })) })}>Preview {name} cleanup</Button></div>
              {found && name === 'source' && (() => { const value = found as SourcePreview; return (
                <div className="grid gap-1 text-xs" aria-label="Source cleanup preview">
                  <p className="ui-description">{value.count === 0 ? `Nothing older than ${value.months} months can be removed.` : `${value.count} item(s), ${megabytes(value.bytes ?? 0)} eligible.`} Protected: {value.protected.referenced} still referenced, {value.protected.kept_newest} newest previous revisions, {value.protected.recent} too recent, {value.protected.unclassified} waiting to be classified.</p>
                  {Object.entries(value.categories).map(([label, row]) => <div key={label}>{label}: {row.count} · {megabytes(row.bytes)} · oldest {Math.round(row.oldest_days / 30)} months</div>)}
                </div>) })()}
              {found && name === 'review' && (() => { const value = found as ReviewPreview; return (
                <div className="grid gap-1 text-xs" aria-label="Review cleanup preview">
                  <p className="ui-description">{value.count === 0 ? `No completed review period older than ${value.months} months can be removed.` : `${value.count} completed review period(s) eligible, ${value.protected} protected.`}</p>
                  {value.sample.map(item => <div key={item.name}>Eligible: {item.name} ({item.state}, completed {new Date(item.completed).toLocaleDateString()}) · {item.decisions} decision events · {item.actions} actions</div>)}
                  {Object.entries(value.reasons).map(([reason, count]) => <div key={reason}>Protected: {count} · {reason}</div>)}
                  <p className="ui-description">Removed periods keep a deletion record and the report log. A copy is kept for 30 days and the cleanup can be undone meanwhile.</p>
                </div>) })()}
              {found && category.state !== 'approved' && (
                <div className="grid gap-2">
                  <Checkbox checked={Boolean(confirmed[name])} onChange={event => setConfirmed(previous => ({ ...previous, [name]: event.target.checked }))}>I reviewed this {name} preview and approve removing these items now and automatically in the future</Checkbox>
                  <div><Button disabled={!confirmed[name] || busy} onClick={() => void run(async () => { await apiRequest('/api/retention/approve', 'POST', { category: name, confirm: true, preview_digest: found.digest }); setPreview(previous => ({ ...previous, [name]: undefined })); setConfirmed(previous => ({ ...previous, [name]: false })) })}>Approve {name} cleanup</Button></div>
                </div>
              )}
            </section>
          )
        })}
      </div>
      <div><Button disabled={!dirty || busy} onClick={() => void run(async () => { await apiRequest('/api/retention/policy', 'PUT', { enabled: shownEnabled, months: shown('source'), review_months: shown('review') }); setMonths({ source: null, review: null }); setEnabled(null); setPreview({}) })}>Save retention settings</Button></div>
      {error && <p role="alert">{error}</p>}
      {current.history.length > 0 && (
        <details>
          <summary>Retention history</summary>
          <ul className="m-0 grid gap-1 pl-4 text-xs">
            {current.history.map(entry => <li key={entry.at + entry.trigger + entry.category}>{new Date(entry.at).toLocaleString()} · {entry.category} · {entry.trigger} · {entry.status}{entry.by ? ` · ${entry.by}` : ''}{entry.message ? ` · ${entry.message}` : ''}</li>)}
          </ul>
        </details>
      )}
    </section>
  )
}
