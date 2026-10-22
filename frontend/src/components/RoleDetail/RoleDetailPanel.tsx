import { DetailNavigation } from "@/components/Shared/InvestigationNavigation"
import { ModuleIcon } from '@/components/Modules/ModuleIcon'
import { RoleIdentifier } from '@/components/Shared/RoleIdentifier'
import { useState, useEffect, useCallback } from 'react'
import { X, ChevronDown, ChevronRight, AlertTriangle, Loader2, Layers, Zap, Users, ArrowRight } from 'lucide-react'
import * as ScrollArea from '@radix-ui/react-scroll-area'
import { useRoleDetail } from '@/hooks/useRoleDetail'
import type { SingleRole, TCode } from '@/api/types'

function SingleRoleRow({ sr, onTcodeUsers }: { sr: SingleRole; onTcodeUsers?: (code:string)=>void }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <div
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:opacity-90 focus:outline-none transition-colors"
        style={{ backgroundColor: open ? 'color-mix(in srgb, var(--accent2) 8%, var(--surface))' : 'var(--surface)' }}>

        {/* Module icon */}
        <ModuleIcon moduleId={sr.function_key} />

        {/* Expand arrow */}
        <button type="button" className="role-expand" aria-label={`Expand single role ${sr.child_agr}`} aria-expanded={open} onClick={() => setOpen(p => !p)}>{open
          ? <ChevronDown  className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--accent2)' }} />
          : <ChevronRight className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--muted)'   }} />
        }</button>

        {/* Name + description */}
        <div className="min-w-0 flex-1">
          <RoleIdentifier value={sr.child_agr} />
          <span className="text-xs">{sr.assignment_kind==='direct'?'Direct assignment':sr.assignment_kind==='effective'?'Effective-role assignment':''}</span>
          {sr.child_agr_text && (
            <p className="text-xs truncate mt-0.5" style={{ color: 'var(--muted)' }}>
              {sr.child_agr_text}
            </p>
          )}
        </div>

        {/* T-code count: Zap icon + number (clearer than "8T") */}
        <div className="flex items-center gap-1 flex-shrink-0 px-2 py-0.5 rounded-lg"
          style={{ backgroundColor: 'color-mix(in srgb, var(--accent) 12%, transparent)' }}>
          <Zap className="w-3 h-3" style={{ color: 'var(--accent2)' }} aria-hidden="true" />
          <span className="text-xs font-black tabular-nums" style={{ color: 'var(--accent2)' }}>
            {sr.tcodes.length}
          </span>
        </div>
      </div>

      {open && (
        <div style={{ borderTop: '1px solid var(--border)', backgroundColor: 'var(--surface2)' }}>
          {Boolean(sr.alternate_descriptions?.length) && <p className="text-xs px-4 py-2">Alternate descriptions: {sr.alternate_descriptions?.slice(0,5).join(' · ')}</p>}
          {sr.tcodes.length === 0
            ? <p className="px-4 py-3 text-xs italic" style={{ color: 'var(--muted)' }}>No transactions</p>
            : <table className="w-full">
                <thead><tr style={{ backgroundColor: 'var(--surface2)' }}>
                  <th className="text-left px-4 py-2 text-xs font-black uppercase w-36"
                    style={{ color: 'var(--muted)', borderBottom: '1px solid var(--border)' }}>T-code</th>
                  <th className="text-left px-4 py-2 text-xs font-black uppercase"
                    style={{ color: 'var(--muted)', borderBottom: '1px solid var(--border)' }}>Description</th>
                </tr></thead>
                <tbody>
                  {sr.tcodes.map((tc: TCode, i: number) => (
                    <tr key={tc.tcode} style={{ backgroundColor: i % 2 === 1 ? 'var(--surface)' : undefined }}>
                      <td className="px-4 py-2 font-mono text-xs font-bold"
                        style={{ color: 'var(--accent2)', borderBottom: '1px solid var(--border)' }}>
                        <span>{tc.tcode}</span>
                        {onTcodeUsers&&<button className="underline block mt-1" onClick={()=>onTcodeUsers(tc.tcode)}>Investigate users with {tc.tcode}</button>}
                      </td>
                      <td className="px-4 py-2 text-xs"
                        style={{ color: 'var(--text2)', borderBottom: '1px solid var(--border)' }}>
                        {tc.ttext ?? <span className="italic" style={{ color: 'var(--muted)' }}>No description</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
          }
        </div>
      )}
    </div>
  )
}

export function RoleDetailPanel({ roleName, onClose, onUsers, onTcodeUsers, parent = 'Role Lookup' }: { parent?: string; roleName: string | null; onClose: () => void; onUsers?: (role:string)=>void; onTcodeUsers?: (code:string)=>void }) {
  const { data: role, isLoading, isError, error } = useRoleDetail(roleName)
  const onKey = useCallback((e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }, [onClose])
  useEffect(() => { document.addEventListener('keydown', onKey); return () => document.removeEventListener('keydown', onKey) }, [onKey])
  useEffect(() => { document.body.style.overflow = roleName ? 'hidden' : ''; return () => { document.body.style.overflow = '' } }, [roleName])
  if (!roleName) return null

  const cleanTitle = (t: string | null) => t ? t.replace(/^[A-Z]{2,3}\s*-\s*/, '').trim() : roleName

  return (
    <>
      <div className="fixed inset-0 z-40" style={{ backgroundColor: 'rgba(0,0,0,0.25)' }} onClick={onClose} />
      <aside className="fixed right-0 top-0 h-full z-50 flex flex-col shadow-2xl w-full sm:w-[560px] lg:w-[45vw] max-w-[700px]"
        style={{ backgroundColor: 'var(--surface)' }} role="dialog" aria-modal="true">

        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-6 py-4 flex-shrink-0"
          style={{ backgroundColor: 'var(--primary)', color:'var(--on-primary)', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <div className="min-w-0 flex-1">
            <p className="text-base font-black text-current leading-snug break-words">
              {cleanTitle(role?.text ?? null)}
            </p>
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              <ModuleIcon moduleId={role?.function_key} size="medium" />
              {role?.function_key && (
                <span className="text-xs font-bold px-2 py-0.5 rounded-md text-current"
                  style={{ backgroundColor: 'rgba(255,255,255,0.15)' }}>
                  {role.function_key}
                </span>
              )}
              {role?.module_name && (
                <span className="text-xs font-medium" style={{ color: 'var(--on-primary)' }}>
                  {role.module_name}
                </span>
              )}
            </div>
            <RoleIdentifier value={roleName} />
          </div>
          <button aria-label="Close role details" onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-current/60 hover:text-current hover:bg-white/10 transition-colors flex-shrink-0 focus:outline-none">
            <X className="w-4 h-4" />
          </button>
        </div>

        <ScrollArea.Root className="flex-1 overflow-hidden">
          <ScrollArea.Viewport className="h-full w-full">
            <div className="px-6 py-5 flex flex-col gap-5">
              <DetailNavigation parent={parent} current="Role details" onBack={onClose}/>

              {isLoading && (
                <div className="flex flex-col items-center py-20 gap-3">
                  <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--accent2)' }} />
                  <p className="text-sm" style={{ color: 'var(--muted)' }}>Loading...</p>
                </div>
              )}
              {isError && (
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
                  {onUsers&&<button className="settings-secondary-button" onClick={()=>onUsers(role.agr_name)}><Users size={16} aria-hidden="true"/>Assigned users<ArrowRight size={16} aria-hidden="true"/></button>}
                  {/* Stats: Single roles FIRST (left), T-codes SECOND (right) */}
                  <div className="flex gap-4 rounded-xl p-4"
                    style={{ backgroundColor: 'var(--surface2)', border: '1px solid var(--border)' }}>

                    {/* Single roles â€” LEFT */}
                    <div className="flex-1 text-center">
                      <div className="flex items-center justify-center gap-1.5 mb-1">
                        <Layers className="w-4 h-4" style={{ color: 'var(--accent2)' }} />
                        <p className="text-3xl font-black leading-none" style={{ color: 'var(--accent2)' }}>
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
                        <p className="text-3xl font-black leading-none" style={{ color: 'var(--accent2)' }}>
                          {role.tcode_count.toLocaleString()}
                        </p>
                      </div>
                      <p className="text-xs font-medium" style={{ color: 'var(--muted)' }}>Transactions</p>
                    </div>
                  </div>

                  <details className="text-xs border rounded-xl p-3">
                    <summary className="cursor-pointer font-semibold">Relationships &amp; analysis provenance</summary>
                    <p className="mt-2">SAP areas use explicit CSV evidence.{role.module_ambiguous ? ' Conflicting SAP areas; shown as Unclassified.' : ''}</p>
                    <p className="mt-1">Alternative descriptions: {role.alternate_descriptions?.join(' · ') || 'None'}</p>
                    <p className="mt-1">Import profile {String(role.analysis?.import_profile_id || 'default')}</p>
                    <table className="w-full text-left mt-2"><thead><tr><th>Child</th><th>Parent</th><th>Effective role</th></tr></thead><tbody>
                      {role.relationships?.slice(0,200).map((r,i)=><tr key={i}><td className="p-1 break-all">{r.child_agr ? <RoleIdentifier value={r.child_agr} /> : '—'}</td><td className="p-1 break-all">{r.parent_agr ? <RoleIdentifier value={r.parent_agr} /> : '—'}</td><td className="p-1 break-all">{r.effective_role ? <RoleIdentifier value={r.effective_role} /> : '—'}</td></tr>)}
                    </tbody></table>
                    {(role.relationships?.length||0)>200 && <p>Showing 200 of {role.relationships?.length} retained relationships.</p>}
                  </details>
                  {/* Single role list */}
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <Layers className="w-3.5 h-3.5" style={{ color: 'var(--muted)' }} />
                      <p className="text-xs font-black uppercase tracking-wider" style={{ color: 'var(--muted)' }}>
                        Single Roles
                      </p>
                    </div>
                    {role.single_roles.length === 0
                      ? <p className="text-sm italic" style={{ color: 'var(--muted)' }}>No single roles found</p>
                      : (
                        <div className="rounded-2xl overflow-hidden" style={{ border: '1px solid var(--border)' }}>
                          {role.single_roles.map(sr => <SingleRoleRow key={sr.child_agr} sr={sr} onTcodeUsers={onTcodeUsers} />)}
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
