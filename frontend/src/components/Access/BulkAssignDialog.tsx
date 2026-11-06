import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UsersRound } from 'lucide-react'
import { bulkAssign, bulkPreview, fetchGroups, groupsKey, type BulkPreview, type BulkResult } from '@/api/functionalGroups'
import { Button } from '@/components/Shared/Button'
import { Combobox } from '@/components/Shared/Combobox'
import { Dialog } from '@/components/Shared/Dialog'
import { FormField, controlClass } from '@/components/Shared/Controls'
import { LoadingState } from '@/components/Shared/Presentation'

const reviewerOf = () => { try { return localStorage.getItem('sap-lens-reviewer') ?? '' } catch { return '' } }
const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`
const message = (error: unknown) => error instanceof Error ? error.message : 'The assignment could not be saved.'

/** Bulk Functional Group assignment for an explicit list of usernames. Uses the atomic bulk endpoint: nothing is replaced without the confirmation,
 *  each user has an explicit outcome and only the users that were not applied can be retried. Classification only: SAP roles are never changed. */
export function BulkAssignDialog({ usernames, onClose, onChanged }: { usernames: string[]; onClose: () => void; onChanged: () => void }) {
  const client = useQueryClient()
  const groups = useQuery({ queryKey: groupsKey, queryFn: fetchGroups })
  const active = (groups.data?.items ?? []).filter(group => group.status === 'active')
  const [names, setNames] = useState(usernames)
  const [choice, setChoice] = useState(''), [reviewer, setReviewer] = useState(reviewerOf), [rationale, setRationale] = useState(''), [confirmed, setConfirmed] = useState(false)
  const [result, setResult] = useState<BulkResult | null>(null)
  const group = active.find(item => item.name === choice)
  const preview = useQuery({ queryKey: ['bulk-preview', group?.id, names], enabled: Boolean(group), queryFn: () => bulkPreview(group!.id, names), staleTime: 0, gcTime: 0 })
  const operation = useRef('')
  useEffect(() => { setConfirmed(false) }, [group?.id])
  const data: BulkPreview | undefined = preview.data
  const replacing = data?.counts.other ?? 0
  const save = useMutation({
    mutationFn: () => {
      if (!operation.current) operation.current = crypto.randomUUID()
      return bulkAssign({ group_id: group!.id, usernames: names, expected: Object.fromEntries((data?.items ?? []).map(item => [item.username, item.revision])), replace_existing: confirmed,
        rationale, reviewer: reviewer.trim(), operation_id: operation.current, data_revision: data!.data_revision })
    },
    onSuccess: async outcome => {
      operation.current = ''
      try { localStorage.setItem('sap-lens-reviewer', reviewer.trim()) } catch { /* optional convenience */ }
      setResult(outcome)
      await Promise.all([['access-users'], ['access-user'], ['functional-group-user'], ['functional-group-options'], ['functional-groups'], ['account-review']].map(queryKey => client.invalidateQueries({ queryKey })))
      onChanged()
    },
    onError: () => { operation.current = '' },
  })
  const failed = result ? [...result.conflicts, ...result.rejected].map(row => row.username) : []
  const byGroup = new Map<string, number>()
  for (const item of data?.items ?? []) byGroup.set(item.group_name ?? 'Unassigned', (byGroup.get(item.group_name ?? 'Unassigned') ?? 0) + 1)
  const ready = Boolean(group && data && reviewer.trim() && !save.isPending && (replacing === 0 || confirmed) && names.length > 0)
  return (
    <Dialog title="Assign Functional Group" onClose={save.isPending ? () => undefined : onClose}>
      {result ? (
        <div className="grid gap-3" role="status">
          <p><strong>{result.applied.length.toLocaleString()}</strong> {result.applied.length === 1 ? 'user' : 'users'} assigned to {result.group_name}. {plural(result.unchanged.length, 'user')} unchanged, {plural(failed.length, 'user')} not updated.</p>
          {failed.length > 0 && (
            <ul aria-label="Users not updated">{[...result.conflicts, ...result.rejected].map(row => <li key={row.username}><strong>{row.username}</strong>: {row.detail}</li>)}</ul>
          )}
          <div className="ui-toolbar">
            {failed.length > 0 && <Button onClick={() => { setNames(failed); setResult(null); setConfirmed(false) }}>Retry {plural(failed.length, 'failed user')}</Button>}
            <Button variant="primary" onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : (
        <div className="grid gap-3">
          <p>{plural(names.length, 'user')} selected</p>
          <FormField label="Functional Group">
            <Combobox label="Functional Group" value={choice} options={active.map(item => item.name)} onChange={setChoice} allowCustom={false} placeholder="Search or select a group" clearLabel="No group" openOnFocus={false} />
          </FormField>
          {group && (preview.isLoading ? <LoadingState /> : preview.isError ? <p role="alert">{message(preview.error)}</p> : data && (
            <div className="grid gap-2">
              <p className="font-semibold">Current assignments</p>
              <ul aria-label="Current assignments">{[...byGroup].map(([name, count]) => <li key={name}>{name}: {plural(count, 'user')}</li>)}</ul>
              {data.missing.length > 0 && <p role="alert">{plural(data.missing.length, 'selected user')} no longer in the SAP user data and will be skipped.</p>}
              {replacing > 0 && (
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
                  <span>Replace the existing Functional Group of {plural(replacing, 'user')} with {group.name}.</span>
                </label>
              )}
              {data.counts.same > 0 && <p className="ui-description">{plural(data.counts.same, 'user')} already in {group.name} stay unchanged.</p>}
            </div>
          ))}
          <FormField label="Reviewer"><input className={controlClass} value={reviewer} maxLength={120} onChange={event => setReviewer(event.target.value)} /></FormField>
          <FormField label="Rationale (optional)"><textarea className={controlClass} rows={2} maxLength={1000} value={rationale} onChange={event => setRationale(event.target.value)} /></FormField>
          {save.isError && <p role="alert">{message(save.error)}</p>}
          <div className="ui-toolbar">
            <Button onClick={onClose} disabled={save.isPending}>Cancel</Button>
            <Button variant="primary" disabled={!ready} onClick={() => save.mutate()}><UsersRound size={16} aria-hidden="true" />{save.isPending ? 'Assigning…' : 'Assign group'}</Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}
