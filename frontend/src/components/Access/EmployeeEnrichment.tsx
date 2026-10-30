import { useState } from 'react'
import { Dialog } from '@/components/Shared/Dialog'
import { Info } from 'lucide-react'
import { DataTable, StatusBadge } from '@/components/Shared/Presentation'
import { Button } from '@/components/Shared/Button'
import { directoryDisplayName } from '@/lib/directoryDisplayName'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, Undo2, UserRoundX } from 'lucide-react'
import { apiRequest } from '@/api/client'
import type { Employee } from '@/components/Shared/EmployeeInformation'
import { userHref, useViewHistory } from '@/hooks/useViewHistory'

export interface EmployeeMatch {
  status: string
  employee: Employee | null
  diagnostics?:{source:string;sap_source:string;source_file:string;matching_method:string;sap_username:string;explanation:string;candidate_count:number;candidates:{id:string;name:string;email:string;username:string;account_status:string}[]}
  manager_sap?: {
    status: string
    username: string | null
    display_name?: string
  }
}
export function useEmployeeMatch(username: string) {
  return useQuery({
    queryKey: ['employee-match', username],
    queryFn: () =>
      apiRequest<EmployeeMatch>(
        `/api/employees/match/${encodeURIComponent(username)}`,
      ),
  })
}
/** The way back after following a manager link: the previous SAP username is kept in the trail, so several manager hops can be undone one by one. */
export function ReturnToPreviousUser({ currentUser }: { currentUser?: string }) {
  const { view, change } = useViewHistory()
  const trail = (view.userTrail || []).filter((name) => name !== currentUser), previous = trail[trail.length - 1]
  if (!previous) return null
  return (
    <Button size="compact" className="detail-return-button" aria-label={`Return to previous user: ${previous}`}
      onClick={() => change({ page: 'users', accessMode: 'directory', user: previous, userTrail: trail.slice(0, -1) })}>
      <Undo2 size={14} aria-hidden="true" />Return to previous user <strong>{previous}</strong>
    </Button>
  )
}

export function ManagerSummary({
  employee,
  manager,
  currentUser,
}: {
  employee: Employee
  manager: EmployeeMatch['manager_sap']
  currentUser?: string
}) {
  const { view, change } = useViewHistory()
  const status =
    (
      {
        ambiguous: 'Multiple SAP users found',
        unmatched: 'SAP user not found',
        missing_email: 'Manager email not provided',
        mapping_unavailable: 'SAP identity source unavailable',
      } as Record<string, string>
    )[manager?.status || 'missing_email'] || 'SAP identity unavailable'
  const name =
    manager?.display_name ||
    directoryDisplayName(employee.manager.name) ||
    'Manager not provided'
  const identity = (
    <>
      <strong>{name}</strong>
      {employee.manager.title && (
        <span className="text-sm text-[var(--muted)]">
          {employee.manager.title}
        </span>
      )}
    </>
  )
  return (
    <section aria-label="Reports to" className="profile-manager">
      <h3>Reports to</h3>
      {manager?.status === 'matched' && manager.username ? (
        <a
          className="manager-identity"
          href={userHref(manager.username)}
          aria-label="View SAP user"
          onClick={(event) => {
            if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
            event.preventDefault()
            // Route-based: Back returns to the previous user and the trail powers the visible "Back to previous user" action.
            change({ page: 'users', accessMode: 'directory', user: manager.username!, userTrail: [...(view.userTrail || []), ...(currentUser ? [currentUser] : [])] })
          }}
        >
          {identity}
          <span className="text-xs">
            View SAP user{' '}
            <ArrowUpRight size={14} aria-hidden="true" className="inline" />
          </span>
        </a>
      ) : (
        <div className="manager-identity">
          {identity}
          <span className="evidence-badge evidence-neutral">
            <UserRoundX size={13} aria-hidden="true" />
            {status}
          </span>
        </div>
      )}
      <ReturnToPreviousUser currentUser={currentUser} />
    </section>
  )
}

/** Secondary evidence only; never turns a candidate into a confirmed identity. */
export function DirectoryMatchDetails({match}:{match?:EmployeeMatch}) {
 const {change}=useViewHistory(),evidence=match?.diagnostics
 const [open,setOpen]=useState(false)
 const status=match?.status==='matched'?'Matched':match?.status?.includes('ambiguous')||match?.status?.includes('duplicate')?'Ambiguous':match?.status==='unmatched'?'Unmatched':match?.status?.includes('missing')?'Missing':'Unavailable'
 return <><Button onClick={()=>setOpen(true)} aria-label={`Directory matching details · ${status}`}><Info size={16} aria-hidden="true"/><span>Directory match</span><StatusBadge tone={status==='Matched'?'success':['Ambiguous','Unmatched'].includes(status)?'warning':'neutral'}>{status}</StatusBadge></Button>{open&&<Dialog title="Directory matching details" onClose={()=>setOpen(false)}><div className="space-y-3">{!evidence?<p>Directory matching evidence is unavailable. Check that Employee Directory and User–Role Mapping are enabled with valid imported data.</p>:<><p>{evidence.explanation}</p><p className="ui-description">Affected SAP identity: {evidence.sap_username} · SAP source: {evidence.sap_source}</p><p className="ui-description">Source: {evidence.source} · {evidence.source_file} · Matching method: {evidence.matching_method}</p>{match?.employee?.account_status==='Unknown'&&<p>AD status is unknown because the imported Enabled value is missing or unsupported. It is not interpreted as enabled or disabled.</p>}{evidence.candidate_count>0&&<><p>{evidence.candidate_count} candidate source records. IDs apply to the current directory snapshot; they are not physical CSV line numbers.</p><DataTable caption="Directory matching source records"><thead><tr><th>Record ID</th><th>Name</th><th>Email</th><th>AD username</th><th>AD status</th></tr></thead><tbody>{evidence.candidates.map(row=><tr key={row.id}><td>{row.id}</td><td>{row.name||'Not provided'}</td><td>{row.email||'Missing'}</td><td>{row.username||'Missing'}</td><td>{row.account_status}</td></tr>)}</tbody></DataTable>{evidence.candidate_count>evidence.candidates.length&&<p>Showing the first {evidence.candidates.length} records. Inspect Data Sources to review all conflicts.</p>}</>}<Button onClick={()=>{setOpen(false);change({settings:true,settingsTarget:'employees'})}}>Inspect Employee Directory source</Button><p className="ui-description">Correct conflicting source records and revalidate. Imported evidence is retained; no local identity override or silent deduplication is performed.</p></>}</div></Dialog>}</>
}
