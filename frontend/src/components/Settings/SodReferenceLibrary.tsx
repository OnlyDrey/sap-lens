import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, applicationToken } from '@/api/client'
import { Dialog } from '@/components/Shared/Dialog'
import { Button } from '@/components/Shared/Button'
import { formatTimestamp } from '@/lib/dateFormat'

interface Library { defaults_available:boolean; default_version:string; origin:string; library_version:string; warning:string; installed: boolean; matched_risks: number; matched_activities: number; unmatched_risks: string[]; unmatched_activities: string[]; missing_risks: string[]; missing_activities: string[]; revision: number; digest: string; imported_at: string; risks: number; activities: number; terms: number }

/** Private reference guidance, independently versioned; never imports active access rules. */
export function SodReferenceLibrary() {
  const qc = useQueryClient(), input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState(''), [confirmReset,setConfirmReset]=useState(false)
  const query = useQuery({ queryKey: ['sod-reference'], queryFn: () => apiRequest<Library>('/api/sod/reference') })
  const choose = async (file?: File) => {
    if (!file || !query.data || busy) return
    setError(''); setMessage('')
    if (!file.name.toLowerCase().endsWith('.xlsx') || !file.size || file.size > 2 * 1024 * 1024) {
      setError('Choose a non-empty XLSX reference workbook up to 2 MB.'); return
    }
    setBusy(true)
    try {
      const body = new FormData(); body.append('file', file); body.append('revision', String(query.data.revision))
      const response = await fetch('/api/sod/reference/upload', { method: 'POST', headers: { 'X-SAP-Lens': applicationToken() }, body, credentials: 'same-origin' })
      const value = await response.json() as Library & { detail?: string }
      if (!response.ok) throw new Error(typeof value.detail==='string'?value.detail:'Reference import failed; previous definitions are retained.')
      qc.setQueryData(['sod-reference'], value)
      await qc.invalidateQueries({ predicate: item => String(item.queryKey[0]).startsWith('sod') && item.queryKey[0] !== 'sod-reference' })
      setMessage(`Reference library saved: ${value.risks} risks and ${value.activities} activities. Active matrix and review decisions were not changed.`)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Reference import failed; previous definitions are retained.') }
    finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  const reset=async()=>{
    if(!query.data||busy)return
    setBusy(true);setError('');setMessage('')
    try{
      const value=await apiRequest<Library>('/api/sod/reference/reset','POST',{expected_revision:query.data.revision})
      qc.setQueryData(['sod-reference'],value)
      await qc.invalidateQueries({predicate:item=>String(item.queryKey[0]).startsWith('sod')&&item.queryKey[0]!=='sod-reference'})
      setMessage('Bundled reference defaults restored. Local overrides, active matrix and review history were preserved.');setConfirmReset(false)
    }catch(cause){setError(cause instanceof Error?cause.message:'Defaults could not be restored.')}
    finally{setBusy(false)}
  }
  return <section aria-label="SoD reference library" className="grid min-w-0 gap-2">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3>Reference definitions</h3><Button size="compact" disabled={busy||!query.data?.defaults_available} onClick={()=>setConfirmReset(true)}>Reset defaults</Button></div>
    <p className="ui-description">Curated business guidance, not verified SAP-standard metadata. Exact IDs enrich only elements in the active matrix. Non-empty local overrides take priority over imported metadata, then reference definitions. Importing replaces the reference library only.</p>
    <input ref={input} type="file" accept=".xlsx" aria-label="SoD reference workbook" className="sr-only" disabled={busy || !query.data} onChange={event => void choose(event.target.files?.[0])} />
    <Button loading={busy} disabled={!query.data} onClick={() => input.current?.click()}>Import reference workbook</Button>
    {query.data && <p className="ui-description">{query.data.installed?'Installed':'Not installed'} · Bundled version {query.data.default_version||'Unavailable'} · Active {query.data.origin} {query.data.library_version} · {query.data.risks} risks · {query.data.activities} activities · {query.data.terms} terms · Revision {query.data.revision} · {formatTimestamp(query.data.imported_at || null)}</p>}
    {query.data?.installed && <div className="ui-description break-words" aria-label="Reference matching summary"><p>{query.data.matched_risks} active risks matched · {query.data.matched_activities} active activities matched</p><p>Unmatched reference IDs: {query.data.unmatched_risks.concat(query.data.unmatched_activities).join(', ')||'None'}</p><p>Active IDs missing reference definitions: {query.data.missing_risks.concat(query.data.missing_activities).join(', ')||'None'}</p>{!query.data.matched_risks&&!query.data.matched_activities&&<p>No active matrix IDs match this reference library.</p>}</div>}
    {query.data?.warning&&<p role="alert">{query.data.warning}</p>}
    {confirmReset&&<Dialog title="Reset reference defaults" onClose={()=>{if(!busy)setConfirmReset(false)}} footer={<><Button disabled={busy} onClick={()=>setConfirmReset(false)}>Cancel</Button><Button variant="primary" loading={busy} onClick={()=>void reset()}>Reset defaults</Button></>}><p>Replace custom reference definitions with the bundled library? Local business overrides, active SoD data, review decisions and immutable history will be preserved.</p>{error&&<p role="alert">{error}</p>}</Dialog>}
    {(error || query.isError) && <p role="alert">{error || (query.error instanceof Error ? query.error.message : 'Reference library could not be read.')}</p>}
    {message && <p role="status">{message}</p>}
  </section>
}
