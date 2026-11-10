import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '@/api/client'
import { Button } from '@/components/Shared/Button'
import { Checkbox } from '@/components/Shared/Controls'
import { StatusBadge } from '@/components/Shared/Presentation'

type StorageStatus = {
  state: 'ready' | 'unavailable' | 'newer'
  schema_version: number
  size_bytes: number
  requires_confirmation: boolean
  revisions: { source: string; rows: number; entities: number; activated: string | null }[]
  backup: { id: string; created: string; sha256: string; size_bytes: number; app_version?: string } | null
  retained?: { id: string; created: string; confirmed_at?: string; confirmed_by?: string; size_bytes: number } | null
}

const megabytes = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`

/** SQLite source store status and the pre-migration backup, which is kept until an administrator confirms the upgrade works. */
export function StorageUpgrade() {
  const client = useQueryClient()
  const status = useQuery({ queryKey: ['storage-status'], queryFn: () => apiRequest<StorageStatus>('/api/storage/status'), retry: false })
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')
  const current = status.data
  if (!current) return null
  const release = async () => {
    if (!current.backup) return
    setBusy(true)
    setError('')
    try {
      await apiRequest('/api/storage/migration/confirm', 'POST', { migration_id: current.backup.id, confirm: true })
      await client.invalidateQueries({ queryKey: ['storage-status'] })
      setConfirmed(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The upgrade could not be confirmed.')
    } finally {
      setBusy(false)
    }
  }
  const deleteRetained = async () => {
    if (!current.retained) return
    setBusy(true)
    setError('')
    try {
      await apiRequest('/api/storage/migration/delete-backup', 'POST', { migration_id: current.retained.id, confirm: true })
      await client.invalidateQueries({ queryKey: ['storage-status'] })
      setDeleting(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The backup could not be deleted.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-label="Storage upgrade" className="grid gap-2 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="m-0 text-sm font-semibold">Source store</h3>
        <StatusBadge>{current.state === 'ready' ? 'SQLite store ready' : current.state === 'newer' ? 'Newer version, not in use' : 'Not in use, JSON snapshots are used'}</StatusBadge>
        <span className="text-xs text-muted">{megabytes(current.size_bytes)} · {current.revisions.map(item => `${item.source} ${item.rows.toLocaleString()} rows`).join(' · ') || 'no revisions yet'}</span>
      </div>
      {!current.requires_confirmation && current.retained && (
        <div className="grid gap-2">
          <p className="ui-description">
            The pre-migration backup ({megabytes(current.retained.size_bytes)}, confirmed {current.retained.confirmed_at ? new Date(current.retained.confirmed_at).toLocaleString() : ''}{current.retained.confirmed_by ? ` by ${current.retained.confirmed_by}` : ''}) is still kept.
            Automatic backup retention never removes it; delete it here when it is no longer needed.
          </p>
          <Checkbox checked={deleting} onChange={event => setDeleting(event.target.checked)}>Delete the pre-migration backup permanently</Checkbox>
          <div><Button disabled={!deleting || busy} onClick={() => void deleteRetained()}>Delete pre-migration backup</Button></div>
          {error && <p role="alert">{error}</p>}
        </div>
      )}
      {current.requires_confirmation && current.backup && (
        <div className="grid gap-2">
          <p className="ui-description">
            SAP Lens upgraded its storage. A verified backup of your previous data ({megabytes(current.backup.size_bytes)}, created {new Date(current.backup.created).toLocaleString()}) is kept until you confirm
            that everything works. Confirming keeps it; it is never deleted automatically and can be deleted explicitly afterwards. It contains sensitive access data.
          </p>
          <Checkbox checked={confirmed} onChange={event => setConfirmed(event.target.checked)}>I checked that SAP Lens works after the upgrade</Checkbox>
          <div><Button disabled={!confirmed || busy} onClick={() => void release()}>Confirm that the upgrade works</Button></div>
          {error && <p role="alert">{error}</p>}
        </div>
      )}
    </section>
  )
}
