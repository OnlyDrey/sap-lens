import {useReviewerName} from '@/hooks/useReviewerIdentity'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UsersRound } from 'lucide-react'
import { bulkAssign, bulkPreview, fetchGroups, groupsKey, type BulkPreview, type BulkResult } from '@/api/functionalGroups'
import { Button } from '@/components/Shared/Button'
import { Dialog } from '@/components/Shared/Dialog'
import { Checkbox, FormField, controlClass } from '@/components/Shared/Controls'
import { LoadingState } from '@/components/Shared/Presentation'
import { GroupPicker } from './GroupPicker'

const reviewerOf = () => { try { return localStorage.getItem('sap-lens-reviewer') ?? '' } catch { return '' } }
const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`
const message = (error: unknown) => error instanceof Error ? error.message : 'The assignment could not be saved.'

/** Bulk Functional Group assignment for an explicit list of usernames. It ADDS the selected groups: existing memberships are kept and a group a user already
 *  holds is an idempotent no-op. One atomic write, explicit per-user outcomes, retry only for users that were not applied. Classification only: SAP is never changed. */
export function BulkAssignDialog({ usernames, onClose, onChanged, lockedGroupIds }: { usernames: string[]; onClose: () => void; onChanged: () => void; lockedGroupIds?: string[] }) {
  const client = useQueryClient()
  const groups = useQuery({ queryKey: groupsKey, queryFn: fetchGroups })
  const [names, setNames] = useState(usernames)
  const [picked, setPicked] = useState<string[]>(lockedGroupIds ?? []), [reviewer, setReviewer] = useReviewerName(reviewerOf), [rationale, setRationale] = useState(''), [confirmed, setConfirmed] = useState(false)
  const [result, setResult] = useState<BulkResult | null>(null)
  const preview = useQuery({ queryKey: ['bulk-preview', picked, names], enabled: picked.length > 0, queryFn: () => bulkPreview(picked, names), staleTime: 0, gcTime: 0 })
  const operation = useRef('')
  const pickedKey = picked.join(',')
  useEffect(() => { setConfirmed(false) }, [pickedKey])
  const data: BulkPreview | undefined = preview.data
  const byId = new Map((groups.data?.items ?? []).map(group => [group.id, group.name]))
  const save = useMutation({
    mutationFn: () => {
      if (!operation.current) operation.current = crypto.randomUUID()
      return bulkAssign({ group_ids: picked, usernames: names, expected: Object.fromEntries((data?.items ?? []).map(item => [item.username, item.revision])), rationale, reviewer: reviewer.trim(),
        operation_id: operation.current, data_revision: data!.data_revision })
    },
    onSuccess: async outcome => {
      operation.current = ''
      try { localStorage.setItem('sap-lens-reviewer', reviewer.trim()) } catch { /* optional convenience */ }
      setResult(outcome)
      await Promise.all([['access-users'], ['access-user'], ['functional-group-user'], ['functional-group-options'], ['functional-groups'], ['functional-group-members'], ['account-review']].map(queryKey => client.invalidateQueries({ queryKey })))
      onChanged()
    },
    onError: () => { operation.current = '' },
  })
  const failed = result ? [...result.conflicts, ...result.rejected].map(row => row.username) : []
  const current = new Map<string, number>()
  for (const item of data?.items ?? []) for (const name of item.group_names.length ? item.group_names : ['Unassigned']) current.set(name, (current.get(name) ?? 0) + 1)
  const additions = data?.counts.additions ?? 0
  const ready = Boolean(data && reviewer.trim() && confirmed && !save.isPending && names.length > 0 && picked.length > 0)
  return (
    <Dialog title="Assign Functional Groups" onClose={save.isPending ? () => undefined : onClose}
      footer={result ? (
        <>{failed.length > 0 && <Button onClick={() => { setNames(failed); setResult(null); setConfirmed(false) }}>Retry {plural(failed.length, 'failed user')}</Button>}<Button variant="primary" onClick={onClose}>Done</Button></>
      ) : (
        <><Button onClick={onClose} disabled={save.isPending}>Cancel</Button>
          <Button variant="primary" disabled={!ready} onClick={() => save.mutate()}><UsersRound size={16} aria-hidden="true" />{save.isPending ? 'Assigning…' : 'Assign groups'}</Button></>
      )}>
      {result ? (
        <div className="grid gap-3" role="status">
          <p><strong>{result.applied.length.toLocaleString()}</strong> {result.applied.length === 1 ? 'user' : 'users'} updated with {result.group_names.join(', ')}. {plural(result.unchanged.length + result.applied.filter(row => !row.added.length && !row.reconfirmed.length).length, 'user')} already had every group, {plural(failed.length, 'user')} not updated.</p>
          {failed.length > 0 && <ul aria-label="Users not updated">{[...result.conflicts, ...result.rejected].map(row => <li key={row.username}><strong>{row.username}</strong>: {row.detail}</li>)}</ul>}
        </div>
      ) : (
        <div className="grid min-w-0 gap-3">
          <p>{plural(names.length, 'user')} selected</p>
          {lockedGroupIds ? <p>Group: <strong>{lockedGroupIds.map(id => byId.get(id) ?? id).join(', ')}</strong></p> : <GroupPicker selected={picked} onChange={setPicked} />}
          {picked.length > 0 && (preview.isLoading ? <LoadingState /> : preview.isError ? <p role="alert">{message(preview.error)}</p> : data && (
            <div className="grid gap-2">
              <p className="font-semibold">Current assignments</p>
              <ul aria-label="Current assignments">{[...current].map(([name, count]) => <li key={name}>{name}: {plural(count, 'user')}</li>)}</ul>
              {data.missing.length > 0 && <p role="alert">{plural(data.missing.length, 'selected user')} no longer in the SAP user data and will be skipped.</p>}
              <p className="ui-description">Adds {plural(additions, 'membership')} and keeps all existing groups{data.counts.existing > 0 ? `; ${plural(data.counts.existing, 'membership')} already held stay unchanged` : ''}. SAP access is not changed.</p>
            </div>
          ))}
          <FormField label="Reviewer"><input className={controlClass} readOnly value={reviewer} maxLength={120} onChange={event => setReviewer(event.target.value)} /></FormField>
          <FormField label="Rationale (optional)"><textarea className={controlClass} rows={2} maxLength={1000} value={rationale} onChange={event => setRationale(event.target.value)} /></FormField>
          {data && <Checkbox checked={confirmed} onChange={event => setConfirmed(event.target.checked)}>
            Add {picked.map(id => byId.get(id) ?? id).join(', ')} to {plural(names.length, 'selected user')}</Checkbox>}
          {save.isError && <p role="alert">{message(save.error)}</p>}
        </div>
      )}
    </Dialog>
  )
}
