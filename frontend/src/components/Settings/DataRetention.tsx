import { formatTimestamp } from '@/lib/dateFormat'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { Button } from '@/components/Shared/Button'
import { Checkbox, FormField, controlClass } from '@/components/Shared/Controls'
import { StatusBadge, ErrorState, LoadingState } from '@/components/Shared/Presentation'
import { Dialog } from '@/components/Shared/Dialog'

type Name = 'source' | 'review' | 'backup'
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
type BackupPreview = Category & {
  keep: number; count_limit: { id: string; rule: string }[]
  days: number; reasons: Record<string, number>; counts: { automatic: number; manual: number; unclassified: number; migration: number }
  sample: { id: string; created: string; bytes: number; age_days: number; note: string; rule: string; rules: string[] }[]
}
type State = { months: number; days?: number; last_cleanup?: string; next_check?: string | null; last_preview?: Record<string, unknown>; state: 'disabled' | 'approved' | 'awaiting_approval'; approval: { by: string; at: string; months: number; valid: boolean } | null }
type Retention = {
  policy: { enabled: boolean; months: number; review_months: number; backup_days: number }
  categories: Record<Name, State>
  last_check: string
  quiet_until: string
  history: { at: string; trigger: string; status: string; category: Name; months: number; by: string; message: string; bytes: number }[]
  scope: Record<Name, string[]>
  protected_note: string
}

const megabytes = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`
const labels = { disabled: 'Retention off', approved: 'Automatic cleanup approved', awaiting_approval: 'Waiting for administrator approval' }
const titles: Record<Name, string> = { source: 'Source retention', review: 'Review retention', backup: 'Backup retention' }
const policies: Record<Name, string> = { source: 'Source revisions', review: 'Review evidence', backup: 'Automatic backups' }
const disclosureClass = 'cursor-pointer rounded-sm text-xs font-medium focus-visible:outline focus-visible:outline-[length:var(--focus-width)] focus-visible:outline-focus focus-visible:[outline-offset:var(--focus-offset)]'

/** Separate policies, with explicit previews and approvals. Immutable review evidence is always protected. */
export function DataRetention() {
  const client = useQueryClient()
  const status = useQuery({ queryKey: ['retention'], queryFn: () => apiRequest<Retention>('/api/retention'), retry: false })
  const [months, setMonths] = useState<Record<Name, number | null>>({ source: null, review: null, backup: null })
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [preview, setPreview] = useState<Partial<Record<Name, SourcePreview | ReviewPreview | BackupPreview>>>({})
  const [confirmed, setConfirmed] = useState<Partial<Record<Name, boolean>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [selected, setSelected] = useState<Name | null>(null)
  const current = status.data
  if (status.isLoading) return <LoadingState/>
  if (status.error) return <ErrorState error={status.error} onRetry={()=>void status.refetch()}/>
  if (!current) return null
  const shown = (name: Name) => months[name] ?? (name === 'backup' ? current.policy.backup_days : current.categories[name].months)
  const shownEnabled = enabled ?? current.policy.enabled
  const dirty = shown('source') !== current.policy.months || shown('review') !== current.policy.review_months || shown('backup') !== current.policy.backup_days || shownEnabled !== current.policy.enabled
  const held = Boolean(current.quiet_until && new Date(current.quiet_until) > new Date())
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await action()
      await client.invalidateQueries({ queryKey: ['retention'] })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The request could not be completed.')
    } finally {
      setBusy(false)
    }
  }
  const bound = (value: string, name: Name) => name === 'backup' ? Math.min(3650, Math.max(7, Math.round(Number(value) || 90))) : Math.min(120, Math.max(6, Math.round(Number(value) || 24)))
  const close = () => { if (!busy) { if (selected) { setMonths(previous=>({...previous,[selected]:null})); setConfirmed(previous=>({...previous,[selected]:false})) } setSelected(null); setError('') } }
  const save = () => run(async () => { await apiRequest('/api/retention/policy', 'PUT', { enabled: shownEnabled, months: shown('source'), review_months: shown('review'), backup_days: shown('backup') }); setMonths({ source: null, review: null, backup: null }); setEnabled(null); setPreview({}); setConfirmed({}); setMessage('Retention policy saved. Shortened periods require renewed approval.') })
  const inspect = (name: Name) => { setSelected(name); void run(async () => { setConfirmed(previous=>({...previous,[name]:false})); setPreview(previous=>({...previous,[name]:undefined})); const result=await apiRequest<SourcePreview|ReviewPreview|BackupPreview>(`/api/retention/preview?category=${name}`); setPreview(previous=>({...previous,[name]:result})) }) }
  return (
    <section aria-label="Data retention" className="grid min-w-0 gap-3 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="m-0 text-sm font-semibold">Data retention</h3>
        {current.last_check && <span className="text-xs text-muted">Last check {formatTimestamp(current.last_check)}</span>}
        {current.quiet_until && new Date(current.quiet_until) > new Date() && <StatusBadge>No cleanup until {formatTimestamp(current.quiet_until)} (after a restore)</StatusBadge>}
      </div>
      <div className="flex flex-wrap items-center gap-3"><Checkbox checked={shownEnabled} disabled={busy} onChange={event => {setEnabled(event.target.checked);setPreview({});setConfirmed({})}}>Check and clean up automatically</Checkbox><Button disabled={!dirty||busy} onClick={()=>void save()}>Save retention settings</Button>{dirty&&<StatusBadge>Unsaved changes</StatusBadge>}</div>
      <div className="min-w-0 overflow-x-auto p-1 scroll-p-1"><table className="w-full border-collapse text-left text-xs [&_th]:border-b [&_th]:border-line [&_th]:px-2 [&_th]:py-2 [&_th]:font-semibold [&_td]:border-b [&_td]:border-line [&_td]:px-2 [&_td]:py-2 [&_tr:last-child_td]:border-b-0"><thead><tr>{['Policy','Retention','Approval','Last cleanup','Next eligible cleanup','Actions'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>
       {(['source','review','backup'] as Name[]).map(name=>{const category=current.categories[name];return <tr key={name}><td className="font-medium">{policies[name]}</td><td className="whitespace-nowrap">{shown(name)} {name==='backup'?'days':'months'}</td><td><StatusBadge tone={category.state==='approved'?'success':'neutral'}>{category.state==='approved'?'Approved':category.state==='disabled'?'Off':'Needs approval'}</StatusBadge></td><td className="whitespace-nowrap">{formatTimestamp(category.last_cleanup,'Never')}</td><td>{name==='review'?'Evidence protected':!current.policy.enabled?'Off':held?`After ${formatTimestamp(current.quiet_until)}; approval required`:category.state!=='approved'?'Approval required':formatTimestamp(category.next_check,'Next daily check')}</td><td><div className="flex flex-wrap gap-2"><Button size="compact" disabled={busy} aria-label={`Configure ${policies[name]}`} onClick={()=>{setError('');setConfirmed(previous=>({...previous,[name]:false}));setSelected(name)}}>Configure</Button><Button size="compact" variant="ghost" disabled={busy||dirty} aria-label={`Preview ${policies[name]} cleanup`} onClick={()=>inspect(name)}>Preview cleanup</Button></div></td></tr>})}
      </tbody></table></div>
      <details><summary className={disclosureClass}>What stays protected?</summary><p className="ui-description mt-2">{current.protected_note} Each policy needs its own approval. Shortening a period requires renewed approval.</p></details>
      {message&&!selected&&<p role="status">{message}</p>}
      {error&&!selected&&<p role="alert">{error}</p>}
      {selected&&<Dialog title={`Configure ${policies[selected]}`} size="medium" onClose={close} footer={<><Button disabled={busy} onClick={close}>Close</Button><Button variant="primary" disabled={!dirty||busy} onClick={()=>void save()}>Save policy</Button></>}>
        {([selected] as Name[]).map(name => {
          const category = current.categories[name]
          const found = preview[name]
          return (
            <section key={name} aria-label={titles[name]} className="grid content-start gap-3">
              <div><StatusBadge>{dirty?'Unsaved policy':name==='review'&&category.state==='approved'?'Policy approved; evidence protected':labels[category.state]}</StatusBadge></div>
              <details><summary className={disclosureClass}>Protection rules</summary><ul className="mt-2 pl-4 text-xs text-muted">{(current.scope[name] ?? []).map(item => <li key={item}>{item}</li>)}</ul></details>
              <FormField label={name === 'backup' ? 'Backup retention period (days)' : `${titles[name]} period (months)`} description={name === 'backup' ? 'Between 7 and 3650. Default 90. Applies to automatic backups only. Shortening it needs a new approval.' : 'Between 6 and 120. Default 24. Shortening it needs a new approval.'}>
                <input className={controlClass} type="number" disabled={busy} min={name === 'backup' ? 7 : 6} max={name === 'backup' ? 3650 : 120} value={shown(name)} onChange={event => {setMonths(previous => ({ ...previous, [name]: bound(event.target.value, name) }));setPreview(previous=>({...previous,[name]:undefined}));setConfirmed(previous=>({...previous,[name]:false}))}} />
              </FormField>
              {name === 'backup' && <div className="grid gap-0.5 text-xs text-muted" aria-label="Backup retention rules">
                <span>Automatic backups older than {shown('backup')} days are removed only after approval. Recent backups are protected regardless of the legacy count preference.</span>
                <span>Manual and migration backups are never removed automatically.</span>
              </div>}
              {name === 'backup' && <div className="grid gap-0.5 text-xs text-muted" aria-label="Backup retention status">
                <span>Last successful cleanup: {formatTimestamp(category.last_cleanup,'never')}</span>
                <span>Next scheduled check: {formatTimestamp(category.next_check,'after the first daily check')}</span>
                {category.last_preview && 'counts' in category.last_preview && <span>Automatic backups: {(category.last_preview.counts as BackupPreview['counts']).automatic} · manual (kept): {(category.last_preview.counts as BackupPreview['counts']).manual} · migration (kept): {(category.last_preview.counts as BackupPreview['counts']).migration}</span>}
              </div>}
              {dirty&&<p className="ui-description">Save the policy before requesting a new cleanup preview.</p>}
              {held&&<p role="status">Cleanup and approval are paused after a restore until {formatTimestamp(current.quiet_until)}. Previews remain available.</p>}
              <div><Button disabled={busy || dirty} onClick={() => inspect(name)}>Preview {name} cleanup</Button></div>
              {found && name === 'source' && (() => { const value = found as SourcePreview; return (
                <div className="grid gap-1 text-xs" aria-label="Source cleanup preview">
                  <p className="ui-description">{value.count === 0 ? `Nothing older than ${value.months} months can be removed.` : `${value.count} item(s), ${megabytes(value.bytes ?? 0)} eligible.`} Protected: {value.protected.referenced} still referenced, {value.protected.kept_newest} newest previous revisions, {value.protected.recent} too recent, {value.protected.unclassified} waiting to be classified.</p>
                  {Object.entries(value.categories).map(([label, row]) => <div key={label}>{label}: {row.count} · {megabytes(row.bytes)} · oldest {Math.round(row.oldest_days / 30)} months</div>)}
                </div>) })()}
              {found && name === 'review' && (() => { const value = found as ReviewPreview; return (
                <div className="grid gap-1 text-xs" aria-label="Review cleanup preview">
                  <p className="ui-description">Immutable review evidence is preserved. {value.protected} review periods are protected.</p>
                  {value.protected_sample.map(item => <div key={item.name}>Protected: {item.name} · {item.reason}</div>)}
                  {Object.entries(value.reasons).map(([reason, count]) => <div key={reason}>Protected: {count} · {reason}</div>)}
                  <p className="ui-description">This policy records approval; it does not delete immutable periods, decisions or evidence.</p>
                </div>) })()}
              {found && name === 'backup' && (() => { const value = found as BackupPreview; return (
                <div className="grid gap-1 text-xs" aria-label="Backup cleanup preview">
                  <p className="ui-description">{value.count === 0 ? `No automatic backup older than ${value.days} days can be removed.` : `${value.count} automatic backup(s), ${megabytes(value.bytes ?? 0)}, older than ${value.days} days would be removed.`} {value.counts.automatic} automatic, {value.counts.manual} manual, {value.counts.migration} migration, {value.counts.unclassified} unclassified.</p>
                  {value.sample.map(item => <div key={item.id}>Eligible: created {formatTimestamp(item.created)} · {item.age_days} days · {megabytes(item.bytes)} · rule: {item.rule}{item.note ? ` · ${item.note}` : ''}</div>)}
                  {Object.entries(value.reasons).map(([reason, count]) => <div key={reason}>Protected: {count} · {reason}</div>)}
                  <p className="ui-description">Archives can contain historical records that source or review retention already removed from the live installation. Manual backups are removed only by an administrator.</p>
                </div>) })()}
              {found && !dirty && category.state !== 'approved' && (
                <div className="grid gap-2">
                  <Checkbox checked={Boolean(confirmed[name])} onChange={event => setConfirmed(previous => ({ ...previous, [name]: event.target.checked }))}>I reviewed this {name} preview and {name==='review'?'approve the policy with immutable evidence protected':'approve removing these eligible items now and automatically in the future'}</Checkbox>
                  <div><Button disabled={!confirmed[name] || busy || dirty || held} onClick={() => void run(async () => { await apiRequest('/api/retention/approve', 'POST', { category: name, confirm: true, preview_digest: found.digest }); setPreview(previous => ({ ...previous, [name]: undefined })); setConfirmed(previous => ({ ...previous, [name]: false }));setMessage('Approval recorded. Protected data remain unchanged.') })}>Approve {name} {name==='review'?'policy':'cleanup'}</Button></div>
                </div>
              )}
            </section>
          )
        })}
       {busy&&<LoadingState>Working…</LoadingState>}{message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
      </Dialog>}
      {current.history.length > 0 && (
        <details>
          <summary className={disclosureClass}>Retention history</summary>
          <ul className="m-0 grid gap-1 pl-4 text-xs">
            {current.history.map(entry => <li key={entry.at + entry.trigger + entry.category}>{formatTimestamp(entry.at)} · {entry.category ?? 'backup'} · {entry.trigger} · {entry.status}{entry.by ? ` · ${entry.by}` : ''}{entry.message ? ` · ${entry.message}` : ''}</li>)}
          </ul>
        </details>
      )}
    </section>
  )
}
