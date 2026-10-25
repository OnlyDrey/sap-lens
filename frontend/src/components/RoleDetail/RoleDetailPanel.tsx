import { Button } from '@/components/Shared/Button'
import { useApplicationData } from '@/state/ApplicationData'
import { DetailNavigation } from "@/components/Shared/InvestigationNavigation"
import { RoleMetadata } from '@/components/Shared/RoleMetadata'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { useState, useEffect, useCallback, useMemo, memo } from 'react'
import { X, ChevronDown, ChevronRight, AlertTriangle, Loader2, Layers, Zap, Users, ArrowRight, ArrowLeft } from 'lucide-react'
import * as ScrollArea from '@radix-ui/react-scroll-area'
import { useRoleDetail } from '@/hooks/useRoleDetail'
import { TransactionFilter, useTransactionFilter } from '@/components/Shared/TransactionFilter'
import type { SingleRole, TCode } from '@/api/types'

const SingleRoleRow = memo(function SingleRoleRow({ sr, onTcodeUsers, transaction }: { sr: SingleRole; transaction: string[]; onTcodeUsers?: (code:string)=>void }) {
  const [expanded, setExpanded] = useState(false)
  const [searchExpanded, setSearchExpanded] = useState(true)
  const filterKey = JSON.stringify(transaction)
  useEffect(() => { setSearchExpanded(true) }, [filterKey])
  const searching = transaction.length > 0
  const open = searching ? searchExpanded : expanded
  return (
    <div className="single-role-entry">
      <div className="single-role-heading" data-expanded={open}>
        <button type="button" className="role-expand" aria-label={`Expand single role ${sr.child_agr}`} aria-expanded={open} onClick={() => searching ? setSearchExpanded(p => !p) : setExpanded(p => !p)}>
          {open ? <ChevronDown size={14} aria-hidden="true"/> : <ChevronRight size={14} aria-hidden="true"/>}
        </button>
        <div className="single-role-heading-main">
          <RoleMetadata code={sr.function_key} name={sr.module_name} description={sr.child_agr_text}/>
          <RoleIdentifier value={sr.child_agr} />
          {sr.assignment_kind === 'direct' && <span className="single-role-assignment">Direct assignment</span>}
          {sr.assignment_kind === 'effective' && <span className="single-role-assignment">Effective-role assignment</span>}
        </div>
        <span className="single-role-count" aria-label={`${sr.tcodes.length} transactions`}>
          <Zap size={12} aria-hidden="true"/>{sr.tcodes.length}
        </span>
      </div>
      {open && <div className="single-role-transactions">
        {Boolean(sr.alternate_descriptions?.length) && <p className="text-xs px-4 py-2">Alternate descriptions: {sr.alternate_descriptions?.slice(0,5).join(' · ')}</p>}
        {sr.tcodes.length === 0
          ? <p className="text-xs italic text-[var(--muted)] px-4 py-3">No transactions</p>
          : <div className="transaction-table-scroll" role="region" aria-label={`Transactions for ${sr.child_agr}`} tabIndex={0}>
            <table>
              <thead><tr><th scope="col">T-Code</th><th scope="col">Description</th><th scope="col" className="transaction-action">Action</th></tr></thead>
              <tbody>{sr.tcodes.map((tc: TCode) => <tr key={tc.tcode} data-transaction-match={searching && transaction.includes(tc.tcode.trim().toUpperCase())}>
                <td className="transaction-code">{tc.tcode}</td>
                <td className="transaction-description">{tc.ttext ?? <span className="italic text-[var(--muted)]">No description</span>}</td>
                <td className="transaction-action">{onTcodeUsers && <button type="button" className="settings-secondary-button transaction-investigate"
                  aria-label={`Investigate users with ${tc.tcode}`} title={`Investigate users with ${tc.tcode}`} onClick={() => onTcodeUsers(tc.tcode)}>
                  <Users size={14} aria-hidden="true"/>Investigate users
                </button>}</td>
              </tr>)}</tbody>
            </table>
          </div>}
      </div>}
    </div>
  )
})

export function RoleDetailPanel({ roleName, onClose, onUsers, onTcodeUsers, parent = 'Role Lookup', navigation }: { navigation?: { index: number; total: number; onPrevious?: () => void; onNext?: () => void; missing: boolean }; parent?: string; roleName: string | null; onClose: () => void; onUsers?: (role:string)=>void; onTcodeUsers?: (code:string)=>void }) {
  const {loading:dataLoading}=useApplicationData()
  const { data: role, isLoading, isError, error } = useRoleDetail(roleName)
  const transactionFilter = useTransactionFilter(roleName)
  const transaction = useMemo(() => transactionFilter.deferredCodes, [transactionFilter.deferredKey])
  const searching = transaction.length > 0
  const matchingRoles = useMemo(() => new Set(role?.single_roles.filter(sr => sr.tcodes.some(tc => transaction.includes(tc.tcode.trim().toUpperCase()))).map(sr => sr.child_agr)), [role, transaction])
  const missingMappings = role?.single_roles.filter(sr => !sr.tcodes.length).length || 0
  const onKey = useCallback((e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }, [onClose])
  useEffect(() => { document.addEventListener('keydown', onKey); return () => document.removeEventListener('keydown', onKey) }, [onKey])
  useEffect(() => { document.body.style.overflow = roleName ? 'hidden' : ''; return () => { document.body.style.overflow = '' } }, [roleName])
  if (!roleName) return null

  const cleanTitle = (t: string | null) => t ? t.replace(/^[A-Z]{2,3}\s*-\s*/, '').trim() : roleName

  return (
    <>
      <div className="fixed inset-0 z-40" style={{ backgroundColor: 'rgba(0,0,0,0.25)' }} onClick={onClose} />
      <aside className="fixed right-0 top-0 h-full z-50 flex flex-col  w-full sm:w-[560px] lg:w-[45vw] max-w-[700px]"
        style={{ backgroundColor: 'var(--surface)' }} role="dialog" aria-modal="true" aria-label={`Role details: ${roleName}`}>

        {/* Header */}
        <div className="role-detail-header flex items-start justify-between gap-3 px-4 py-3 flex-shrink-0"
          style={{ backgroundColor: 'var(--primary)', color:'var(--on-primary)', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <div className="min-w-0 flex-1">
            <nav aria-label="Breadcrumb" className="mb-2"><Button variant="ghost" size="compact" onClick={onClose}><ArrowLeft size={16} aria-hidden="true"/>Back to {parent === 'User Access' ? 'users' : parent}</Button></nav>
            <p className="text-base font-black text-current leading-snug break-words">
              {cleanTitle(role?.text ?? null)}
            </p>
            <RoleMetadata code={role?.function_key} name={role?.module_name}/>
            <div className="role-detail-identifier"><RoleIdentifier value={roleName}/></div>
          </div>
          <button aria-label="Close role details" onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-current/60 hover:text-current hover:bg-white/10 transition-colors flex-shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        <ScrollArea.Root className="flex-1 overflow-hidden">
          <ScrollArea.Viewport className="h-full w-full">
            <div className="px-4 py-3 flex flex-col gap-3">
              <DetailNavigation showBreadcrumb={false} {...navigation} parent={parent} current={roleName} onBack={onClose}/>

              {(isLoading || (dataLoading && !role)) && (
                <div className="flex flex-col items-center py-20 gap-3">
                  <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--accent2)' }} />
                  <p className="text-sm" style={{ color: 'var(--muted)' }}>Loading...</p>
                </div>
              )}
              {isError && !dataLoading && (
                <div className="flex gap-3 rounded-xl p-4" style={{ backgroundColor: 'var(--surface2)', border: '1px solid var(--error)' }}>
                  <AlertTriangle className="w-5 h-5 text-[var(--error)]" />
                  <div>
                    <p className="text-sm font-bold" style={{ color: 'var(--error)' }}>Error</p>
                    <p className="text-sm" style={{ color: 'var(--error)' }}>{error?.message}</p>
                  </div>
                </div>
              )}

              {role && (
                <>
                  {/* Stats: Single roles FIRST (left), T-codes SECOND (right) */}
                  <div className="flex gap-3 rounded-lg p-2"
                    style={{ backgroundColor: 'var(--surface2)', border: '1px solid var(--border)' }}>
                    {onUsers&&<Button size="compact" onClick={()=>onUsers(role.agr_name)}><Users size={16} aria-hidden="true"/>Assigned users<ArrowRight size={16} aria-hidden="true"/></Button>}
                    {/* Single roles â€” LEFT */}
                    <div className="flex-1 text-center">
                      <div className="flex items-center justify-center gap-1.5 mb-1">
                        <Layers className="w-4 h-4" style={{ color: 'var(--accent2)' }} />
                        <p className="text-xl font-bold leading-none" style={{ color: 'var(--accent2)' }}>
                          {role.single_roles.length}
                        </p>
                      </div>
                      <p className="text-xs font-medium" style={{ color: 'var(--muted)' }}>Single roles</p>
                    </div>

                    <div className="w-px" style={{ backgroundColor: 'var(--border)' }} />

                    {/* T-codes â€” RIGHT */}
                    <div className="flex-1 text-center">
                      <div className="flex items-center justify-center gap-1.5 mb-1">
                        <Zap className="w-4 h-4" style={{ color: 'var(--accent2)' }} />
                        <p className="text-xl font-bold leading-none" style={{ color: 'var(--accent2)' }}>
                          {role.tcode_count.toLocaleString()}
                        </p>
                      </div>
                      <p className="text-xs font-medium" style={{ color: 'var(--muted)' }}>Transactions</p>
                    </div>
                  </div>

                  <details className="text-xs border rounded-xl p-3">
                    <summary className="cursor-pointer font-semibold">Relationships &amp; analysis provenance</summary>
                    <p className="mt-2">SAP areas use explicit CSV evidence.{role.module_ambiguous ? ' Conflicting SAP areas; shown as Unclassified.' : ''}</p>
                    <p className="mt-1">Catalogue record found. {role.text?.trim() ? 'Role description available.' : 'Role description missing from the imported catalogue.'} {role.relationships?.some(r => r.child_agr || r.parent_agr || r.effective_role) ? 'Source relationships retained.' : 'No explicit role relationship fields supplied.'} {role.tcode_count ? 'Transaction mappings available; source completeness cannot be verified.' : 'No transaction mappings supplied; this does not establish absence of SAP permissions.'}</p>
                    <p className="mt-1">Single-role header labels may use a recognized module prefix in the imported description. These display labels do not reclassify roles or change transaction mappings.</p>
                    <p className="mt-1">Alternative descriptions: {role.alternate_descriptions?.join(' · ') || 'None'}</p>
                    <p className="mt-1">Import profile {String(role.analysis?.import_profile_id || 'default')}</p>
                    <table className="w-full text-left mt-2"><thead><tr><th>Child</th><th>Parent</th><th>Effective role</th></tr></thead><tbody>
                      {role.relationships?.slice(0,200).map((r,i)=><tr key={i}><td className="p-1 break-all">{r.child_agr ? <RoleIdentifier value={r.child_agr} /> : '—'}</td><td className="p-1 break-all">{r.parent_agr ? <RoleIdentifier value={r.parent_agr} /> : '—'}</td><td className="p-1 break-all">{r.effective_role ? <RoleIdentifier value={r.effective_role} /> : '—'}</td></tr>)}
                    </tbody></table>
                    {(role.relationships?.length||0)>200 && <p>Showing 200 of {role.relationships?.length} retained relationships.</p>}
                  </details>
                  <form className="role-transaction-search" aria-label="Sidebar transaction search" onSubmit={event => event.preventDefault()}>
                    <TransactionFilter label="Find transaction code" filter={transactionFilter}/>
                    {searching && <div role="status" className="basis-full text-sm">
                      {matchingRoles.size ? `${matchingRoles.size} matching single ${matchingRoles.size === 1 ? 'role' : 'roles'} for ${transaction.join(' OR ')}.` : role.tcode_count ? `No matching single roles for ${transaction.join(' OR ')} in the imported mappings.` : 'Transaction mappings unavailable in this catalogue record.'}
                      {missingMappings > 0 && <p>{missingMappings} single roles have no supplied transaction mappings; source completeness cannot be established.</p>}
                      <p>Role-derived evidence does not prove effective SAP authorization.</p>
                    </div>}
                  </form>
                  {/* Single role list */}
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <Layers className="w-3.5 h-3.5" style={{ color: 'var(--muted)' }} />
                      <p className="text-xs font-black uppercase tracking-wider" style={{ color: 'var(--muted)' }}>
                        Single roles
                      </p>
                    </div>
                    {role.single_roles.length === 0
                      ? <p className="text-sm italic" style={{ color: 'var(--muted)' }}>No single roles found</p>
                      : (
                        <div className="single-role-list rounded-xl overflow-hidden" style={{ border: '1px solid var(--border)' }}>
                          {role.single_roles.map(sr => <div key={`${roleName}:${sr.child_agr}`} hidden={searching && !matchingRoles.has(sr.child_agr)}><SingleRoleRow sr={sr} transaction={transaction} onTcodeUsers={onTcodeUsers}/></div>)}
                        </div>
                      )
                    }
                  </div>
                </>
              )}
            </div>
          </ScrollArea.Viewport>
          <ScrollArea.Scrollbar orientation="vertical"
            className="flex select-none touch-none p-0.5 w-2.5"
            style={{ backgroundColor: 'var(--surface2)' }}>
            <ScrollArea.Thumb className="flex-1 rounded-full" style={{ backgroundColor: 'var(--accent2)' }} />
          </ScrollArea.Scrollbar>
        </ScrollArea.Root>
      </aside>
    </>
  )
}
