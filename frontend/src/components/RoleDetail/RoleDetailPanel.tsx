import { useState, useEffect, useCallback } from 'react'
import { X, ChevronDown, ChevronRight, AlertTriangle, Loader2, Layers, Zap } from 'lucide-react'
import * as ScrollArea from '@radix-ui/react-scroll-area'
import { useDomainLabel, useModuleVisual } from '@/components/Modules/ModuleRegistry'
import { useRoleDetail } from '@/hooks/useRoleDetail'
import type { SingleRole, TCode } from '@/api/types'

function RowModIcon({ moduleId }: { moduleId?: string }) {
  const {Icon,color} = useModuleVisual(moduleId)
  return <div className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0" style={{backgroundColor:color}}><Icon className="w-3.5 h-3.5 text-white" /></div>
}

function SingleRoleRow({ sr }: { sr: SingleRole }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <button onClick={() => setOpen(p => !p)} aria-expanded={open}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:opacity-90 focus:outline-none transition-colors"
        style={{ backgroundColor: open ? 'color-mix(in srgb, var(--accent2) 8%, var(--surface))' : 'var(--surface)' }}>

        {/* Module icon */}
        <RowModIcon moduleId={sr.function_key} />

        {/* Expand arrow */}
        {open
          ? <ChevronDown  className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--accent2)' }} />
          : <ChevronRight className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--muted)'   }} />
        }

        {/* Name + description */}
        <div className="min-w-0 flex-1">
          <p className="font-mono text-xs font-bold truncate" style={{ color: 'var(--text)' }}>
            {sr.child_agr}{sr.assignment_kind==='direct'?' · Direct assignment':sr.assignment_kind==='effective'?' · Effective-role assignment':''}
          </p>
          {sr.child_agr_text && (
            <p className="text-[11px] truncate mt-0.5" style={{ color: 'var(--muted)' }}>
              {sr.child_agr_text}
            </p>
          )}
        </div>

        {/* T-code count: Zap icon + number (clearer than "8T") */}
        <div className="flex items-center gap-1 flex-shrink-0 px-2 py-0.5 rounded-lg"
          style={{ backgroundColor: 'rgba(250,100,20,0.12)' }}>
          <Zap className="w-3 h-3" style={{ color: 'var(--accent)' }} aria-hidden="true" />
          <span className="text-[11px] font-black tabular-nums" style={{ color: 'var(--accent)' }}>
            {sr.tcodes.length}
          </span>
        </div>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid var(--border)', backgroundColor: 'var(--surface2)' }}>
          {Boolean(sr.alternate_descriptions?.length) && <p className="text-xs px-4 py-2">Alternate descriptions: {sr.alternate_descriptions?.slice(0,5).join(' · ')}</p>}
          {sr.tcodes.length === 0
            ? <p className="px-4 py-3 text-xs italic" style={{ color: 'var(--muted)' }}>No T-codes</p>
            : <table className="w-full">
                <thead><tr style={{ backgroundColor: 'var(--surface2)' }}>
                  <th className="text-left px-4 py-2 text-[10px] font-black uppercase w-36"
                    style={{ color: 'var(--muted)', borderBottom: '1px solid var(--border)' }}>T-code</th>
                  <th className="text-left px-4 py-2 text-[10px] font-black uppercase"
                    style={{ color: 'var(--muted)', borderBottom: '1px solid var(--border)' }}>Description</th>
                </tr></thead>
                <tbody>
                  {sr.tcodes.map((tc: TCode, i: number) => (
                    <tr key={tc.tcode} style={{ backgroundColor: i % 2 === 1 ? 'var(--surface)' : undefined }}>
                      <td className="px-4 py-2 font-mono text-[11px] font-bold"
                        style={{ color: 'var(--accent2)', borderBottom: '1px solid var(--border)' }}>
                        {tc.tcode}
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

export function RoleDetailPanel({ roleName, onClose }: { roleName: string | null; onClose: () => void }) {
  const { data: role, isLoading, isError, error } = useRoleDetail(roleName)
  const domainLabel = useDomainLabel(role?.domain_id)
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
          style={{ backgroundColor: '#1A003B', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <div className="min-w-0 flex-1">
            <p className="text-base font-black text-white leading-snug">
              {cleanTitle(role?.text ?? null)}
            </p>
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              {role?.function_key && (
                <span className="text-xs font-bold px-2 py-0.5 rounded-md text-white"
                  style={{ backgroundColor: 'rgba(255,255,255,0.15)' }}>
                  {role.function_key}
                </span>
              )}
              {role?.module_name && (
                <span className="text-xs font-medium" style={{ color: '#8ba3c7' }}>
                  {role.module_name}
                </span>
              )}
            </div>
            <p className="font-mono text-[10px] mt-1.5 break-all" style={{ color: '#4a6a8a' }}>{roleName}</p>
          </div>
          <button onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-white/60 hover:text-white hover:bg-white/10 transition-colors flex-shrink-0 focus:outline-none">
            <X className="w-4 h-4" />
          </button>
        </div>

        <ScrollArea.Root className="flex-1 overflow-hidden">
          <ScrollArea.Viewport className="h-full w-full">
            <div className="px-6 py-5 flex flex-col gap-5">

              {isLoading && (
                <div className="flex flex-col items-center py-20 gap-3">
                  <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--accent)' }} />
                  <p className="text-sm" style={{ color: 'var(--muted)' }}>Loading...</p>
                </div>
              )}
              {isError && (
                <div className="flex gap-3 rounded-xl p-4" style={{ backgroundColor: 'var(--surface2)', border: '1px solid #fca5a5' }}>
                  <AlertTriangle className="w-5 h-5 text-red-500" />
                  <div>
                    <p className="text-sm font-bold" style={{ color: '#ef4444' }}>Error</p>
                    <p className="text-sm" style={{ color: '#f87171' }}>{error?.message}</p>
                  </div>
                </div>
              )}

              {role && (
                <>
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
                        <Zap className="w-4 h-4" style={{ color: 'var(--accent)' }} />
                        <p className="text-3xl font-black leading-none" style={{ color: 'var(--accent)' }}>
                          {role.tcode_count.toLocaleString()}
                        </p>
                      </div>
                      <p className="text-xs font-medium" style={{ color: 'var(--muted)' }}>T-codes</p>
                    </div>
                  </div>

                  <details className="text-xs border rounded-xl p-3">
                    <summary className="cursor-pointer font-semibold">Relationships &amp; analysis provenance</summary>
                    <p className="mt-2">Domain: {domainLabel || 'No customer domain'}{role.classification_ambiguous?' · Ambiguous classification':''}</p>
                    <p className="mt-1 break-all">Profile {String(role.analysis?.profile_id || 'legacy')} · version {String(role.analysis?.profile_version || 1)} · fingerprint {String(role.analysis?.profile_fingerprint || '')}</p>
                    <p className="mt-1">Alternative descriptions: {role.alternate_descriptions?.join(' · ') || 'None'}</p>
                    <p className="mt-1">Import profile {String(role.analysis?.import_profile_id || 'default')}</p>
                    <table className="w-full text-left mt-2"><thead><tr><th>Child</th><th>Parent</th><th>Effective role</th></tr></thead><tbody>
                      {role.relationships?.slice(0,200).map((r,i)=><tr key={i}><td className="p-1 break-all">{r.child_agr||'—'}</td><td className="p-1 break-all">{r.parent_agr||'—'}</td><td className="p-1 break-all">{r.effective_role||'—'}</td></tr>)}
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
                          {role.single_roles.map(sr => <SingleRoleRow key={sr.child_agr} sr={sr} />)}
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